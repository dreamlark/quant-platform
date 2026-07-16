"""缠论 / 技术信号（czsc 实装；低于最小 K 线数或 czsc 缺失时降级为量价技术打分）。

技术信号作为融合第 2 源（技术）。基于 czsc 的**笔（BI）结构**派生 ``tech_score`` ∈ [-1,1]：

  - **方向**：最后一笔方向（向上 = 偏多 / 向下 = 偏空），权重 0.45
  - **动量**：最新收盘价在最后一笔区间内的位置（确认方向），权重 0.30
  - **力度**：最后一笔 power 相对近 6 笔均值的偏离，权重 0.15
  - **加速度**：最后一笔 power 相对上一笔的放大/萎缩，权重 0.10

所有价格使用前复权调整：以 ``adj_back_close / close`` 为复权比，对 ``open/high/low``
同步复权，避免除权缺口产生虚假笔（遵循平台“统一使用 adj_back_close”约定，P0-1）。

``czsc`` 为可选依赖，仅在 ``_try_czsc`` 内懒加载；未安装或单只标的 K 线不足时自动降级。

性能：每只股票仅构建一次 ``CZSC``（已完成笔具有单调性），再按交易日二分派生全历史打分，
整体约 O(N·logB)（N=交易日数，B=笔数），远优于每日重算的 O(N²)。
"""
from __future__ import annotations

import bisect
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from common.stats import clip
from loguru import logger


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI(14)，兜底用。"""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)


def _fallback_score(g: pd.DataFrame) -> np.ndarray:
    """MA/RSI/突破 兜底（czsc 不可用或 K 线不足时），输出与 g 等长的 tech_score。"""
    pr = g["adj_back_close"]
    ma5 = pr.rolling(5).mean()
    ma20 = pr.rolling(20).mean()
    ma_gap = (ma5 / ma20 - 1.0).fillna(0.0)
    rsi = _rsi(pr, 14)
    breakout = (pr / pr.rolling(60).max() - 1.0).fillna(0.0)

    s1 = clip(ma_gap / 0.05)            # MA 金叉/死叉
    s2 = clip((rsi - 50.0) / 30.0)      # RSI 超买超卖
    s3 = clip(breakout / 0.10)          # 60 日突破
    score = 0.5 * s1 + 0.3 * s2 + 0.2 * s3
    # score 已是 numpy.ndarray（s1/s2/s3 经 common.stats.clip 返回 ndarray），
    # 直接 np.clip 即可，勿再调 .to_numpy()
    return np.clip(score, -1.0, 1.0)


class CzscSignals:
    """技术信号计算（输出 tech_score ∈ [-1,1]）。"""

    def __init__(self) -> None:
        self._czsc = self._try_czsc()
        self._min_bars = 30  # 至少 30 根日K 才足以成笔，否则降级

    @staticmethod
    def _try_czsc() -> bool:
        try:
            import czsc  # noqa: F401

            logger.debug("检测到 czsc，使用真实缠论笔结构计算技术分")
            return True
        except ImportError:
            logger.warning("未安装 czsc，技术分降级为量价打分（MA/RSI/突破）")
            return False

    def compute(self, bars_df: pd.DataFrame) -> pd.DataFrame:
        """返回 (date, code, tech_score) 长表。"""
        if bars_df is None or bars_df.empty:
            return pd.DataFrame(columns=["date", "code", "tech_score"])

        parts = []
        for code, g in bars_df.groupby("code", sort=False):
            g = g.sort_values("date").reset_index(drop=True)
            if self._czsc and len(g) >= self._min_bars:
                try:
                    score = self._czsc_score(g)
                except Exception as exc:  # 单只失败不影响整体
                    logger.warning(f"czsc 计算 {code} 失败，降级量价打分：{exc}")
                    score = _fallback_score(g)
            else:
                score = _fallback_score(g)
            parts.append(
                pd.DataFrame(
                    {
                        "date": g["date"].values,
                        "code": code,
                        "tech_score": np.asarray(score, dtype=float),
                    }
                )
            )
        return pd.concat(parts, ignore_index=True)

    # ------------------------------------------------------------------ #
    # 真实缠论打分（czsc）
    # ------------------------------------------------------------------ #
    def _czsc_score(self, g: pd.DataFrame) -> np.ndarray:
        from czsc import CZSC, Direction, Freq, RawBar

        code = g["code"].iloc[0]
        close_raw = g["close"].to_numpy(dtype=float)
        # 复权比：adj_back_close / close（除权日 close=0 时退化为 1.0）
        ratio = np.where(close_raw > 0, g["adj_back_close"].to_numpy(dtype=float) / close_raw, 1.0)
        opens = g["open"].to_numpy(dtype=float) * ratio
        highs = g["high"].to_numpy(dtype=float) * ratio
        lows = g["low"].to_numpy(dtype=float) * ratio
        closes = g["adj_back_close"].to_numpy(dtype=float)
        vols = g["vol"].to_numpy(dtype=float)
        amounts = g["amount"].to_numpy(dtype=float)
        dts = pd.to_datetime(g["date"].to_numpy())

        bars = [
            RawBar(
                symbol=code, id=i, dt=dts[i], freq=Freq.D,
                open=float(opens[i]), close=float(closes[i]),
                high=float(highs[i]), low=float(lows[i]),
                vol=float(vols[i]), amount=float(amounts[i]),
            )
            for i in range(len(g))
        ]
        c = CZSC(bars)

        bis = c.bi_list
        if not bis:
            return np.zeros(len(g), dtype=float)

        # 已完成笔按 fx_b.dt 排序（笔结构单调，可二分定位“截至某日”的状态）
        fxs = sorted(((b.fx_b.dt, b) for b in bis), key=lambda x: x[0])
        fdt = [x[0] for x in fxs]
        bi_objs = [x[1] for x in fxs]
        powers = np.array([max(b.power, 1e-9) for b in bi_objs], dtype=float)
        avg_power = float(np.mean(powers[-6:])) if len(powers) else 1.0
        last_fx_b_dt = fdt[-1]

        # 未完笔（ubi，dict）：用于最后一段“进行中”的区间
        ubi = c.ubi
        form_dir = form_lo = form_hi = form_power = None
        if ubi is not None:
            form_dir = 1 if ubi["direction"] == Direction.Up else -1
            fa = ubi["fx_a"]
            form_lo = min(fa.low, ubi["low"])
            form_hi = max(fa.high, ubi["high"])
            form_power = avg_power

        out = np.zeros(len(g), dtype=float)
        for i, d in enumerate(dts):
            idx = bisect.bisect_right(fdt, d)  # 已完成且 fx_b.dt <= d 的笔数
            if idx == 0:
                out[i] = 0.0
                continue
            active = bi_objs[idx - 1]
            prev = bi_objs[idx - 2] if idx >= 2 else None
            a_dir = 1 if active.direction == Direction.Up else -1
            a_lo = min(active.fx_a.low, active.fx_b.low)
            a_hi = max(active.fx_a.high, active.fx_b.high)
            a_power = max(active.power, 1e-9)

            if form_dir is not None and d > last_fx_b_dt:
                # 处于未完笔区间：用 ubi 的当下端点，前一笔取最后完成的笔
                a_dir, a_lo, a_hi, a_power = form_dir, form_lo, form_hi, form_power
                prev = bi_objs[-1]

            p_dir = (1 if prev.direction == Direction.Up else -1) if prev is not None else None
            p_power = max(prev.power, 1e-9) if prev is not None else None
            out[i] = self._bi_score(a_dir, a_lo, a_hi, a_power, p_dir, p_power, closes[i], avg_power)
        return out

    @staticmethod
    def _bi_score(
        dir_sign: int,
        lo: float,
        hi: float,
        power: float,
        prev_dir: Optional[int],
        prev_power: Optional[float],
        close: float,
        avg_power: float,
    ) -> float:
        """由单笔结构派生 ∈ [-1,1] 的技术分。"""
        rng = hi - lo
        pos = clip((close - lo) / rng, 0.0, 1.0) if rng > 1e-9 else 0.5
        # 动量确认：收盘价落在“确认方向”的极端 → 更极端的分
        conf = pos if dir_sign > 0 else (1.0 - pos)
        moment = 0.30 * dir_sign * conf

        # 力度：相对近 6 笔均值（0.4~1.6 → -1~1）
        pr = clip(power / avg_power, 0.4, 1.6) if avg_power > 0 else 1.0
        pterm = 0.15 * dir_sign * ((pr - 1.0) / 0.6)

        # 加速度：相对上一笔（0.4~1.6 → -1~1）
        if prev_power and prev_power > 0:
            ar = clip(power / prev_power, 0.4, 1.6)
            aterm = 0.10 * dir_sign * ((ar - 1.0) / 0.6)
        else:
            aterm = 0.0

        score = 0.45 * dir_sign + moment + pterm + aterm
        return float(clip(score, -1.0, 1.0))
