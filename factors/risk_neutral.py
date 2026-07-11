"""风险中性化（行业/市值回归残差法，P1-4）。

融合前对因子做**行业 / 市值中性化**：以每日横截面为样本，将每个因子对
[行业虚拟变量, log(市值)] 回归，取**残差**作为中性化因子值，再横截面 z 化。
消除单一行业/市值风格暴露主导，提升信号稳健性（架构 §7.9）。

``meta`` 需提供 ``code`` / ``industry`` / ``mv``（市值）。生产来自基本面源；
缺失或不充分时**告警并原样返回**（不阻断流水线）。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from common.stats import group_zscore
from loguru import logger


class RiskNeutralizer:
    """行业/市值中性化器（回归残差法）。"""

    def __init__(self, cfg: Optional[dict] = None) -> None:
        self.cfg = cfg or {}

    def neutralize(
        self, factor_long: pd.DataFrame, meta: Optional[pd.DataFrame]
    ) -> pd.DataFrame:
        """对因子长表做中性化。

        Args:
            factor_long: (date, code, factor_name, value)。
            meta: (code, industry, mv)；缺失则跳过中性化。

        Returns:
            中性化后的因子长表（残差 z 值）。
        """
        if factor_long is None or factor_long.empty:
            return factor_long
        if meta is None or meta.empty or "industry" not in meta or "mv" not in meta:
            logger.warning("中性化：缺少 industry/mv 元数据，跳过（原样返回因子）")
            return factor_long

        meta = meta.set_index("code")
        wide = factor_long.pivot_table(
            index=["date", "code"], columns="factor_name", values="value"
        ).reset_index()

        out_parts = []
        for d, g in wide.groupby("date"):
            g = g.copy()
            codes = g["code"]
            m = meta.reindex(codes)
            if m[["industry", "mv"]].isna().any().any():
                # 该日部分标的缺元数据 -> 该日不做中性化，保留原值 z
                for fname in g.columns:
                    if fname in ("date", "code"):
                        continue
                    g[fname] = group_zscore(g, fname)
                out_parts.append(g)
                continue
            mv = np.log(m["mv"].clip(lower=1e-9).to_numpy())
            ind = pd.get_dummies(m["industry"], drop_first=True).to_numpy()
            X = np.column_stack([np.ones(len(g)), mv, ind]).astype(float)
            for fname in g.columns:
                if fname in ("date", "code"):
                    continue
                y = g[fname].to_numpy(dtype=float)
                if np.isnan(y).all():
                    g[fname] = np.nan
                    continue
                try:
                    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
                    pred = X @ coef
                    g[fname] = y - pred  # 回归残差
                except Exception:  # noqa: BLE001
                    g[fname] = y  # 退化：保留原值
            out_parts.append(g)
            continue

        if not out_parts:
            return factor_long
        neu_wide = pd.concat(out_parts, ignore_index=True)
        # 残差横截面 z 化
        for fname in [c for c in neu_wide.columns if c not in ("date", "code")]:
            neu_wide[fname] = group_zscore(neu_wide, fname)
        long = neu_wide.melt(
            id_vars=["date", "code"], var_name="factor_name", value_name="value"
        ).dropna(subset=["value"])
        logger.info("风险中性化完成（行业/市值回归残差）")
        return long
