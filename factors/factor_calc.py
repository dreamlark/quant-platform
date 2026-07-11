"""因子计算日频编排（限定可投资域）。

组合 ``QlibFactorEngine``（alpha 因子）+ ``CzscSignals``（技术信号），
统一在 **universe.in_universe=true** 作用域内计算（P0-3）。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yaml

from factors.czsc_signals import CzscSignals
from factors.qlib_factors import QlibFactorEngine
from loguru import logger

_DEFAULT_FACTORS_YAML = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "factors.yaml"
)


def load_factor_config(path: Optional[str] = None) -> List[Dict]:
    """读取 config/factors.yaml，返回因子定义列表（含 direction / weight）。"""
    path = path or _DEFAULT_FACTORS_YAML
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("factors", [])


class FactorCalculator:
    """日频因子编排。"""

    def __init__(self, cfg: Optional[Dict] = None, factors_yaml: Optional[str] = None) -> None:
        self.cfg = cfg or {}
        self.factor_defs = load_factor_config(factors_yaml)
        self.factor_names = [f["name"] for f in self.factor_defs]
        self.directions: Dict[str, int] = {
            f["name"]: int(f.get("direction", 1)) for f in self.factor_defs
        }
        self.engine = QlibFactorEngine(self.factor_names)
        self.czsc = CzscSignals()

    def compute(
        self, bars_df: pd.DataFrame, universe_codes: Optional[List[str]] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """计算因子 + 技术信号。

        Returns:
            (factor_long, tech_df)：factor_long 为 (date, code, factor_name, value)，
            tech_df 为 (date, code, tech_score)。
        """
        if bars_df is None or bars_df.empty:
            logger.warning("因子计算：行情为空，跳过")
            return (
                pd.DataFrame(columns=["date", "code", "factor_name", "value"]),
                pd.DataFrame(columns=["date", "code", "tech_score"]),
            )

        work = bars_df
        if universe_codes is not None:
            work = bars_df[bars_df["code"].isin(universe_codes)].copy()

        logger.info(f"因子计算：作用域 {work['code'].nunique()} 只（universe 限定）")
        factor_long = self.engine.compute(work)
        tech_df = self.czsc.compute(work)
        return factor_long, tech_df
