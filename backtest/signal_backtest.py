"""信号层组合回测（验证 #4 regime 调节 · PRD §8 启用前门槛）。

把融合后的 ``signals`` 表（date, code, direction, confidence）直接做成**置信度加权多头组合**，
滚动样本外回测，用于验证「regime 调节（极端情绪缩放置信度）」是否改善风险收益：

- OFF：方向=看多 且 confidence ≥ 阈值 的股票，按 confidence 加权等权多头；
- ON ：在上述基础上，按 T-1 市场情绪 regime 将当日所有股票 confidence 乘以缩放系数
  （恐惧/贪婪 ×0.75，中性 ×1.0），等效抬升入选阈值 → 极端情绪下自动收敛持仓、降低集中度。

两口径共享同一再平衡频率与成本模型，差异**仅来自** regime 缩放，从而干净隔离 #4 的增量。

全部 analysis-first：仅评估信号观点，不交易、不下单。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtest.cost_model import CostModel
from backtest.walk_forward import deflated_sharpe
from loguru import logger


class SignalBacktester:
    """信号层置信度加权多头组合回测。"""

    def __init__(self, cfg: Optional[Dict] = None) -> None:
        cfg = cfg or {}
        self.cost = CostModel(cfg)
        self.conf_threshold: float = float(
            (cfg or {}).get("signal_backtest", {}).get("conf_threshold", 0.5)
        )
        self.max_hold: Optional[int] = (cfg or {}).get("signal_backtest", {}).get("max_hold")

    def run(
        self,
        bars_df: pd.DataFrame,
        signals: pd.DataFrame,
        universe_df: pd.DataFrame,
        regime_series: Optional[Dict[dt.date, str]] = None,
        scale_map: Optional[Dict[str, float]] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, float], pd.DataFrame]:
        """执行信号层组合回测。

        Args:
            bars_df: 日线行情（含 adj_back_close）。
            signals: 融合信号表（date, code, direction, confidence）。
            universe_df: 可投资域（含 in_universe）。
            regime_series: 可选 {date: regime}，用于 ON 场景缩放置信度（自动 T-1 偏移）。
            scale_map: 可选 {regime: scale}，如 {"恐惧": 0.75, "中性": 1.0, "贪婪": 0.75}。

        Returns:
            (returns_df, metrics, report_rows)；returns_df 列：date, port_ret, bench_ret
        """
        if bars_df is None or bars_df.empty or signals is None or signals.empty:
            return pd.DataFrame(), {}, pd.DataFrame()

        price = bars_df.pivot_table(index="date", columns="code", values="adj_back_close")
        fwd = price.shift(-1) / price - 1.0
        # 涨跌停流动性约束所需（P1-3）：交易日 t 的 close / pre_close
        # 缺列则降级为不做涨跌停拦截（tradable_buy 返回 True）
        close_px = (
            bars_df.pivot_table(index="date", columns="code", values="close")
            if "close" in bars_df.columns
            else pd.DataFrame()
        )
        pre_close_px = (
            bars_df.pivot_table(index="date", columns="code", values="pre_close")
            if "pre_close" in bars_df.columns
            else pd.DataFrame()
        )
        if universe_df is not None and not universe_df.empty:
            inv = universe_df[universe_df["in_universe"]]["code"].unique()
            keep = [c for c in price.columns if c in inv]
            price = price[keep]
            fwd = fwd[keep]
            close_px = close_px[keep]
            pre_close_px = pre_close_px[keep]

        sig = signals[["date", "code", "direction", "confidence"]].copy()
        sig["date"] = pd.to_datetime(sig["date"]).dt.date

        # 可选：T-1 偏移的 regime 缩放查表
        shifted = None
        if regime_series and scale_map:
            shifted = self._shift_regime(regime_series)

        rows: List[Tuple[dt.date, float, float, float]] = []
        prev_w: Optional[pd.Series] = None
        for t in price.index:
            if t not in fwd.index:
                continue
            s_t = sig[sig["date"] == t]
            if s_t.empty:
                continue
            longs = s_t[s_t["direction"] == 1]
            if longs.empty:
                r = fwd.loc[t]
                rows.append((t, 0.0, float(r.mean()), 0.0))  # 无看多信号 → 全现金
                prev_w = None
                continue
            conf = longs.set_index("code")["confidence"].astype(float)
            if shifted is not None:
                sc = scale_map.get(shifted.get(t), 1.0)  # T-1 regime 缩放
                conf = conf * sc
            held = conf[conf >= self.conf_threshold]
            if self.max_hold:
                held = held.sort_values(ascending=False).head(int(self.max_hold))
            # P1-3 涨跌停约束：剔除当日涨停不可买入之名
            held = held[held.index.map(
                lambda c: self.cost.tradable_buy(
                    close_px[c].get(t) if c in close_px.columns else None,
                    pre_close_px[c].get(t) if c in pre_close_px.columns else None,
                )
            )]
            r = fwd.loc[t]
            if held.empty:
                rows.append((t, 0.0, float(r.mean()), 0.0))
                prev_w = None
                continue
            w = held / held.sum()  # 置信度加权（满仓多头）
            gross = float((w * r).reindex(w.index).fillna(0.0).sum())
            bench_ret = float(r.mean())
            # 换手成本
            if prev_w is None:
                turnover = 1.0
            else:
                idx = w.index.union(prev_w.index)
                c = w.reindex(idx).fillna(0.0)
                p = prev_w.reindex(idx).fillna(0.0)
                turnover = float((c - p).abs().sum() / 2.0)
            port_ret = gross - turnover * self.cost.round_trip_cost_rate()
            rows.append((t, port_ret, bench_ret, gross))
            prev_w = w

        if not rows:
            return pd.DataFrame(), {}, pd.DataFrame()
        ret_df = pd.DataFrame(rows, columns=["date", "port_ret", "bench_ret", "gross_ret"])
        metrics = self._metrics(ret_df)
        report_rows = self._report(ret_df, metrics)
        logger.info(
            f"信号层组合回测完成：{len(ret_df)} 日，年化 {metrics.get('ann_return', 0) * 100:.1f}%，"
            f"Sharpe {metrics.get('sharpe', 0):.2f}，最大回撤 {metrics.get('max_drawdown', 0) * 100:.1f}%"
            + (f"（regime 缩放 ON）" if shifted is not None else "（regime 缩放 OFF）")
        )
        return ret_df, metrics, report_rows

    # ---- 工具 --------------------------------------------------
    @staticmethod
    def _shift_regime(regime_series: Dict[dt.date, str]) -> Dict[dt.date, str]:
        """将 regime 序列按交易日 T-1 偏移（与在线融合一致：用前一日 regime 调节当日信号）。"""
        items = sorted(regime_series.items())
        out: Dict[dt.date, str] = {}
        last = None
        # items 已按日期升序；对每个目标日 t，使用 < t 的最近 regime
        for t, _ in items:
            out[t] = last  # 首日止于 None（不缩放）
            last = regime_series[t]
        return out

    @staticmethod
    def _metrics(ret_df: pd.DataFrame) -> Dict[str, float]:
        from statsmodels.api import OLS
        from statsmodels.tools import add_constant

        p = ret_df["port_ret"].dropna()
        b = ret_df["bench_ret"].dropna()
        if len(p) < 5:
            return {}
        ann = (1.0 + p.mean()) ** 252 - 1.0 if p.mean() > -1 else float("nan")
        sd = p.std(ddof=1)
        sharpe = p.mean() / sd * np.sqrt(252) if sd > 0 else 0.0
        cum = (1.0 + p).cumprod()
        mdd = float(((cum - cum.cummax()) / cum.cummax()).min())
        # 毛收益年化（P1-3）
        g = ret_df["gross_ret"].dropna() if "gross_ret" in ret_df.columns else p
        g_ann = (1.0 + g.mean()) ** 252 - 1.0 if (len(g) >= 5 and g.mean() > -1) else float("nan")
        alpha_ann = 0.0
        beta = 0.0
        try:
            df = pd.concat([p.rename("y"), b.rename("x")], axis=1).dropna()
            if len(df) > 5:
                model = OLS(df["y"], add_constant(df["x"])).fit()
                alpha_ann = float(model.params["const"] * 252)
                beta = float(model.params["x"])
        except Exception:  # noqa: BLE001
            pass
        return {
            "ann_return": float(ann),          # 净收益（头条）
            "ann_return_gross": float(g_ann),  # 毛收益
            "sharpe": float(sharpe),
            "max_drawdown": mdd,
            "deflated_sharpe": deflated_sharpe(p),
            "alpha_ann_vs_bench": alpha_ann,
            "beta_vs_bench": beta,
        }

    @staticmethod
    def _report(ret_df: pd.DataFrame, metrics: Dict[str, float], strategy: str = "signal_long_only") -> pd.DataFrame:
        date = ret_df["date"].max() if not ret_df.empty else None
        rows = []
        for name, val in metrics.items():
            rows.append(
                {
                    "date": date,
                    "strategy": strategy,
                    "metric_name": name,
                    "metric_value": float(val),
                    "benchmark": "zz_quan_zhi,hs300",
                    "sharpe": metrics.get("sharpe", float("nan")),
                    "deflated_sharpe": metrics.get("deflated_sharpe", float("nan")),
                }
            )
        return pd.DataFrame(rows)


def compare_regime(
    bars_df: pd.DataFrame,
    signals: pd.DataFrame,
    universe_df: pd.DataFrame,
    sentiment_df: pd.DataFrame,
    cfg: Optional[Dict] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, float]]:
    """#4 验证：对同一信号做 ON/OFF 两次回测，差异仅来自 regime 缩放。

    Returns:
        (rows_off, rows_on, delta) —— delta 为 ON 减 OFF 的核心指标（正=改善）。
    """
    cfg = cfg or {}
    ra = cfg.get("fusion", {}).get("regime_adjust", {})
    scale_map = {
        "恐惧": float(ra.get("fear_scale", 0.75)),
        "中性": float(ra.get("neutral_scale", 1.0)),
        "贪婪": float(ra.get("greed_scale", 0.75)),
    }
    regime_series: Dict[dt.date, str] = {}
    if sentiment_df is not None and not sentiment_df.empty and "regime" in sentiment_df.columns:
        s = sentiment_df[["date", "regime"]].copy()
        s["date"] = pd.to_datetime(s["date"]).dt.date
        regime_series = {d: str(r) for d, r in zip(s["date"], s["regime"])}

    bt = SignalBacktester(cfg)
    _, m_off, rows_off = bt.run(bars_df, signals, universe_df)  # OFF
    _, m_on, rows_on = bt.run(  # ON（候选缩放，与 enabled 开关无关，便于先验证）
        bars_df, signals, universe_df, regime_series=regime_series, scale_map=scale_map
    )
    if not rows_on.empty:
        # 与 OFF 区分：ON 行标记为 regime 缩放口径
        rows_on = rows_on.copy()
        rows_on["strategy"] = "signal_long_only_regime_scaled"
    delta = {
        "ann_return": m_on.get("ann_return", float("nan")) - m_off.get("ann_return", float("nan")),
        "sharpe": m_on.get("sharpe", float("nan")) - m_off.get("sharpe", float("nan")),
        "max_drawdown": m_on.get("max_drawdown", float("nan")) - m_off.get("max_drawdown", float("nan")),
    }
    return rows_off, rows_on, delta
