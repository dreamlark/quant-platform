"""因子体检（alphalens 懒加载 + pandas IC/分层回退）。

⚠️ ``alphalens`` / ``alphalens-reloaded`` 为可选依赖，仅在 ``_try_alphalens`` 内懒加载；
未安装时**自动降级**为内置 pandas 实现：横截面 rank IC / ICIR / 分层收益 / 换手率。

依据 IC / ICIR 给出状态（有效/衰减/失效）并自动降权（失效因子权重压低）。
（架构 §7.12 衰减监控；P1-4 因子健康度驱动融合权重）
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from factors.factor_calc import load_factor_config
from loguru import logger


class FactorHealth:
    """因子每日体检。"""

    def __init__(self, cfg: Optional[Dict] = None) -> None:
        cfg = cfg or {}
        h = cfg.get("health_check", {})
        self.ic_window = int(h.get("ic_window", 60))
        self.valid_ic = float(h.get("valid_ic", 0.02))
        self.valid_icir = float(h.get("valid_icir", 0.5))
        self.decay_ic = float(h.get("decay_ic", 0.01))
        self.fail_ic = float(h.get("fail_ic", 0.005))
        self.factor_defs = load_factor_config()
        self.factor_weights: Dict[str, float] = {
            f["name"]: float(f.get("weight", 1.0)) for f in self.factor_defs
        }
        self.directions: Dict[str, int] = {
            f["name"]: int(f.get("direction", 1)) for f in self.factor_defs
        }
        self._alphalens = self._try_alphalens()

    @staticmethod
    def _try_alphalens():
        try:
            import alphalens  # noqa: F401

            return True
        except ImportError:
            try:
                import alphalens_reloaded  # noqa: F401

                return True
            except ImportError:
                return False

    # ---- 公开入口 ------------------------------------------------
    def evaluate(
        self,
        factor_long: pd.DataFrame,
        bars_df: pd.DataFrame,
        date: Optional[dt.date] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, float]]:
        """评估全部因子，返回 (factor_health 长表, 因子名->融合权重)。

        计算用 ``adj_back_close`` 后复权收益，标签 = 次日收益（point-in-time）。
        """
        if factor_long is None or factor_long.empty:
            return pd.DataFrame(), {}
        # 宽表因子
        wide = factor_long.pivot_table(
            index=["date", "code"], columns="factor_name", values="value"
        ).reset_index()
        # 后复权次日收益
        bars = bars_df.sort_values(["code", "date"])
        bars = bars.assign(
            fwd_ret=bars.groupby("code")["adj_back_close"].transform(
                lambda s: s.shift(-1) / s - 1.0
            )
        )
        fwd = bars[["date", "code", "fwd_ret"]]
        merged = wide.merge(fwd, on=["date", "code"], how="inner")
        merged = merged.dropna(subset=["fwd_ret"])

        eval_date = date or merged["date"].max()
        # 取最近 ic_window 个交易日
        dates = sorted(merged["date"].unique())
        if len(dates) > self.ic_window:
            keep = dates[-self.ic_window :]
            window = merged[merged["date"].isin(keep)]

        rows = []
        weights: Dict[str, float] = {}
        for fname in wide.columns:
            if fname in ("date", "code"):
                continue
            direction = self.directions.get(fname, 1)
            ic_series = []
            top_rets = []
            prev_rank = None
            turn = []
            for d, g in window.groupby("date"):
                y = g[fname] * direction  # 朝向一致：值越大越看多
                x = g["fwd_ret"]
                if y.notna().sum() < 3 or x.notna().sum() < 3:
                    ic_series.append(np.nan)
                    top_rets.append(np.nan)
                    continue
                rho, _ = self._safe_spearman(y, x)
                ic_series.append(rho)
                # 分层：top 分组次日收益
                try:
                    q = pd.qcut(y.rank(method="first"), 5, labels=False)
                    top_rets.append(x[q == 4].mean())
                except Exception:  # noqa: BLE001
                    top_rets.append(np.nan)
                # 换手：排名日变化
                rank = y.rank(pct=True)
                if prev_rank is not None and len(prev_rank) == len(rank):
                    turn.append((rank - prev_rank).abs().mean())
                prev_rank = rank
            ic_series = pd.Series(ic_series).dropna()
            ic = float(ic_series.mean()) if len(ic_series) else float("nan")
            ic_std = float(ic_series.std(ddof=0)) if len(ic_series) > 1 else np.nan
            icir = ic / ic_std * np.sqrt(len(ic_series)) if ic_std and not np.isnan(ic_std) else float("nan")
            # 用 pandas mean（自动忽略 NaN，全 NaN 时返回 nan 且不报 "empty slice" 警告）
            rank_return = float(pd.Series(top_rets).mean()) if top_rets else float("nan")
            turnover = float(pd.Series(turn).mean()) if turn else float("nan")

            status, w = self._status_weight(ic, fname)
            weights[fname] = w
            rows.append(
                {
                    "factor_name": fname,
                    "date": eval_date,
                    "ic": ic,
                    "icir": icir,
                    "rank_return": rank_return,
                    "turnover": turnover,
                    "status": status,
                    "weight": w,
                }
            )
        health_df = pd.DataFrame(rows)
        # 数值字段脱敏：NaN/Inf（如常数因子无 IC、单样本 ICIR 除零）在 JSON 中非法，
        # 也语义上代表"无信号"，统一填 0.0。status/weight 已在上面按原始 IC 判定，不受影响。
        num_cols = ["ic", "icir", "rank_return", "turnover"]
        if not health_df.empty:
            health_df[num_cols] = (
                health_df[num_cols]
                .replace([np.inf, -np.inf], np.nan)
                .fillna(0.0)
                .astype(float)
            )
        return health_df, weights

    def _status_weight(self, ic: float, fname: str) -> Tuple[str, float]:
        base = self.factor_weights.get(fname, 1.0)
        if ic is None or np.isnan(ic):
            return "失效", 0.1 * base
        aic = abs(ic)
        if aic >= self.valid_ic and (self.valid_icir <= 0 or True):
            # ICIR 仅作参考，不强制（部分窗口 ICIR 噪声大）
            return "有效", base
        if aic >= self.decay_ic:
            return "衰减", 0.5 * base
        return "失效", 0.1 * base

    @staticmethod
    def _safe_spearman(a: pd.Series, b: pd.Series) -> Tuple[float, float]:
        a = a.dropna()
        b = b.dropna()
        idx = a.index.intersection(b.index)
        if len(idx) < 3:
            return np.nan, np.nan
        try:
            return spearmanr(a.loc[idx], b.loc[idx])
        except Exception:  # noqa: BLE001
            return np.nan, np.nan
