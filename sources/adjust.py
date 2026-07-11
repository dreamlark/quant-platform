"""复权处理（P0-1 方法学红线）。

``mootdx.bars()`` 等数据源仅返回**不复权**价；本模块统一产出：
- ``adj_back_close``  **后复权**（锚定最早时点）——因子计算/回测**唯一**可用的价格，避免前复权向前偏差。
- ``adj_front_close`` **前复权**（锚定最新时点）——**仅前端 K 线展示**，严禁用于任何计算。

算法基于交易所每日发布的 ``pre_close``（已含分红送转调整），逐日还原真实收益率：
- 后复权：``adj_back[t] = adj_back[t-1] * close[t] / pre_close[t]``，首日锚定实际收盘。
- 前复权：``adj_front[t] = adj_front[t+1] * pre_close[t+1] / close[t+1]``，末日锚定实际收盘。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

import numpy as np
import pandas as pd

from loguru import logger


def adjust_prices(
    df: pd.DataFrame, jump_detect: bool = True
) -> pd.DataFrame:
    """对单标的（或多标的分组）日 K 计算后复权/前复权价。

    Args:
        df: 含 ``close`` / ``pre_close`` 列的日 K（可为多标的，按 ``code`` 分组）；
            必须含 ``date`` 列。
        jump_detect: 是否做复权跳变检测告警（§7.13 数据质量）。

    Returns:
        在 ``df`` 基础上新增 ``adj_back_close`` / ``adj_front_close`` 列。
    """
    df = df.copy()
    if "pre_close" not in df.columns:
        df["pre_close"] = df.groupby("code")["close"].shift(1)

    out_parts = []
    for code, g in df.groupby("code", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        g = _adjust_single(g, jump_detect=jump_detect)
        out_parts.append(g)
    result = pd.concat(out_parts, ignore_index=True)
    return result


def _adjust_single(g: pd.DataFrame, jump_detect: bool = True) -> pd.DataFrame:
    close = g["close"].astype(float)
    pre = g["pre_close"].astype(float).replace(0, np.nan)

    n = len(g)
    if n == 0:
        g["adj_back_close"] = np.nan
        g["adj_front_close"] = np.nan
        return g

    # ---- 后复权（锚定首日，计算用）----
    f = (close / pre).fillna(1.0)
    cumf = f.cumprod()
    adj_back = close.iloc[0] * (cumf / cumf.iloc[0])

    # ---- 前复权（锚定末日，仅展示）----
    r = (pre.shift(-1) / close.shift(-1)).fillna(1.0)
    rev = r.iloc[::-1]
    cum = rev.cumprod().iloc[::-1]
    adj_front = close.iloc[-1] * cum

    g = g.copy()
    g["adj_back_close"] = adj_back.to_numpy()
    g["adj_front_close"] = adj_front.to_numpy()

    if jump_detect and n > 1:
        _detect_jumps(g, code=g["code"].iloc[0])
    return g


def _detect_jumps(g: pd.DataFrame, code: str = "") -> None:
    """复权跳变检测：adj_back 日收益与不复权收益背离超阈值则告警。"""
    try:
        ret_adj = g["adj_back_close"].pct_change()
        ret_raw = g["close"] / g["pre_close"].replace(0, np.nan) - 1
        diff = (ret_adj - ret_raw).abs()
        bad = g.loc[diff > 0.10, "date"]
        for d in bad:
            logger.warning(f"复权跳变疑似：{code} {d}（建议核查分红送转数据）")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"复权跳变检测跳过：{exc}")


def make_sample_bars(
    code: str,
    start: dt.date,
    n_days: int,
    seed: int = 0,
    drift: float = 0.0005,
    vol: float = 0.02,
    start_price: float = 20.0,
) -> List[Dict]:
    """生成合成日 K（不复权），便于测试 / 冒烟（零网络）。

    用几何随机游走模拟，包含停牌缺口与偶发涨跌停，演示 adjust 的效果。
    """
    rng = np.random.default_rng(seed)
    dates: List[dt.date] = []
    d = start
    while len(dates) < n_days:
        if d.weekday() < 5:  # 仅工作日
            dates.append(d)
        d += dt.timedelta(days=1)

    closes = []
    price = start_price
    for i in range(n_days):
        ret = drift + rng.normal(0, vol)
        # 偶发涨跌停（约 3% 概率）
        if rng.random() < 0.015:
            ret = 0.099 if rng.random() < 0.5 else -0.099
        price *= 1.0 + ret
        price = max(price, 1.0)
        closes.append(price)

    rows: List[Dict] = []
    for i, day in enumerate(dates):
        c = closes[i]
        pre = closes[i - 1] if i > 0 else c
        # 简单 OHLC 围绕收盘抖动
        hi = c * (1 + abs(rng.normal(0, 0.01)))
        lo = c * (1 - abs(rng.normal(0, 0.01)))
        op = pre * (1 + rng.normal(0, 0.005))
        v = float(rng.integers(50000, 500000))
        amt = v * c
        rows.append(
            {
                "code": code,
                "date": day,
                "open": round(op, 2),
                "high": round(max(hi, c, op), 2),
                "low": round(min(lo, c, op), 2),
                "close": round(c, 2),
                "pre_close": round(pre, 2),
                "vol": v,
                "amount": round(amt, 2),
            }
        )
    return rows
