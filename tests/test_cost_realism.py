"""P1-3 回测成本 realism 验收测试。

验收标准（来自 system_optimization_v1.md → P1-3）：
- 同一信号，净收益 <= 毛收益；成本=0 时两者相等。
- 涨跌停日不产生成交记录（涨停日剔除候选）。
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from backtest.walk_forward import WalkForwardBacktester
from backtest.signal_backtest import SignalBacktester


def _bday_range(start: dt.date, n: int):
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def _make_bars_with_close(n_dates=60, seed=11):
    dates = _bday_range(dt.date(2023, 1, 1), n_dates)
    codes = [f"60000{i}.SH" for i in range(10)]
    rng = np.random.default_rng(seed)
    rows = []
    for code in codes:
        price = 50.0
        prev = price
        for date in dates:
            price *= 1.0 + rng.normal(0, 0.02)
            close = float(price)
            pre = float(prev)
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "pre_close": pre,
                    "vol": 1_000_000.0,
                    "amount": close * 1_000_000.0,
                    "adj_back_close": close,
                    "adj_front_close": close,
                }
            )
            prev = close
    return pd.DataFrame(rows), dates, codes


def _make_factor(dates, codes, seed=5):
    """单一 rng 复用构造非恒定因子（避免每元素新建生成器导致的常数列）。"""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        [
            {"date": d, "code": c, "factor_name": "f_dummy", "value": rng.normal()}
            for d in dates
            for c in codes
        ]
    )


def test_walk_forward_net_le_gross():
    """净收益 <= 毛收益（成本侵蚀非负）。"""
    bars, dates, codes = _make_bars_with_close()
    factor_long = _make_factor(dates, codes)
    universe = pd.DataFrame([{"code": c, "in_universe": True} for c in codes])
    wf = WalkForwardBacktester({})
    ret_df, metrics, _ = wf.run(bars, factor_long, universe)
    assert not ret_df.empty
    assert metrics["ann_return"] <= metrics["ann_return_gross"] + 1e-9, (
        f"净年化 {metrics['ann_return']} 应 <= 毛年化 {metrics['ann_return_gross']}"
    )


def test_walk_forward_zero_cost_net_equals_gross():
    """成本=0 时净收益 == 毛收益。"""
    bars, dates, codes = _make_bars_with_close()
    factor_long = _make_factor(dates, codes)
    universe = pd.DataFrame([{"code": c, "in_universe": True} for c in codes])
    cfg = {"cost_model": {"commission": 0.0, "stamp_duty": 0.0, "slippage_bps": 0.0, "min_commission": 0.0}}
    wf = WalkForwardBacktester(cfg)
    ret_df, metrics, _ = wf.run(bars, factor_long, universe)
    assert not ret_df.empty
    assert abs(metrics["ann_return"] - metrics["ann_return_gross"]) < 1e-9, (
        f"零成本下净 {metrics['ann_return']} 应 == 毛 {metrics['ann_return_gross']}"
    )


def test_limit_up_day_excluded_from_portfolio():
    """涨停日不可买入：被剔除后该日组合毛收益应为 0（全现金）。"""
    bars, dates, codes = _make_bars_with_close(n_dates=60, seed=3)
    target = dates[40]  # 远超预热，必为测试日
    # 把 code A 在 target 日设为涨停（close = pre_close * 1.1）
    mask = (bars["code"] == codes[0]) & (bars["date"] == target)
    bars.loc[mask, "close"] = bars.loc[mask, "pre_close"] * 1.10
    bars.loc[mask, "adj_back_close"] = bars.loc[mask, "close"]

    # 信号：code A 全程看多高置信，其余看空
    sig_rows = []
    for d in dates:
        for c in codes:
            sig_rows.append(
                {
                    "date": d,
                    "code": c,
                    "direction": 1 if c == codes[0] else 0,
                    "confidence": 0.95 if c == codes[0] else 0.1,
                }
            )
    signals = pd.DataFrame(sig_rows)
    universe = pd.DataFrame([{"code": c, "in_universe": True} for c in codes])

    bt = SignalBacktester({})
    ret_df, _metrics, _rows = bt.run(bars, signals, universe)
    assert not ret_df.empty

    g_target = float(ret_df[ret_df["date"] == target]["gross_ret"].iloc[0])
    assert abs(g_target) < 1e-9, f"涨停日 {target} 应剔除候选、毛收益=0，得到 {g_target}"

    # 对照：非涨停日 code A 应被纳入（毛收益 != 0）
    other = dates[30]
    g_other = float(ret_df[ret_df["date"] == other]["gross_ret"].iloc[0])
    assert abs(g_other) > 1e-9, f"非涨停日 {other} 应纳入候选（毛收益!=0），得到 {g_other}"
