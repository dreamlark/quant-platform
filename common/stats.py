"""通用统计 / 横截面工具（零重型依赖）。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def xs_zscore(s: pd.Series) -> pd.Series:
    """单组 z-score（标准差为 0 时返回 0）。"""
    mu = s.mean()
    sd = s.std(ddof=0)
    if sd == 0 or pd.isna(sd):
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


def xs_rank(s: pd.Series) -> pd.Series:
    """横截面百分比排名（0~1）。"""
    return s.rank(pct=True)


def group_zscore(
    df: pd.DataFrame, value_col: str, group_col: str = "date"
) -> pd.Series:
    """按 ``group_col``（通常 date）分组做横截面 z-score。"""
    return df.groupby(group_col)[value_col].transform(xs_zscore)


def group_transform(
    df: pd.DataFrame, value_col: str, func, group_col: str = "date"
) -> pd.Series:
    """按组应用任意函数（如 rank）。"""
    return df.groupby(group_col)[value_col].transform(func)


def sigmoid(x: np.ndarray | float) -> np.ndarray | float:
    """数值稳定 sigmoid。"""
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def clip(x: np.ndarray | float, lo: float = -1.0, hi: float = 1.0):
    return np.clip(np.asarray(x, dtype=float), lo, hi)
