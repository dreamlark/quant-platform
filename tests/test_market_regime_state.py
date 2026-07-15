"""P1-2 regime_state 派生（factors/market_sentiment.py）单元测试。

验证：
- _derive_regime_state：无回撤数据→情绪直接映射；深度/中度回撤→panic/bear；贪婪且未深跌→bull。
- _index_drawdown：point-in-time，仅用 ≤date 数据；追加未来数据不改变历史日的回撤（防前视）。
- compute：输出含 regime_state 列。
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from factors.market_sentiment import MarketSentiment  # noqa: E402

CODE = "600519.SH"


def _bars(levels, start=dt.date(2024, 1, 1)):
    rows = []
    d = start
    prev = levels[0]
    for lv in levels:
        lv = float(lv)
        rows.append(
            {
                "date": d,
                "code": CODE,
                "open": lv,
                "high": lv * 1.01,
                "low": lv * 0.99,
                "close": lv,
                "pre_close": float(prev),
                "vol": 1_000_000.0,
                "amount": lv * 1_000_000.0,
                "adj_back_close": lv,
            }
        )
        prev = lv
        d += dt.timedelta(days=1)
    return pd.DataFrame(rows)


def _ms():
    return MarketSentiment({"market_sentiment": {"regime_state": {}}})


def test_derive_regime_state_no_drawdown():
    ms = _ms()
    assert ms._derive_regime_state("贪婪", None) == "bull"
    assert ms._derive_regime_state("中性", None) == "neutral"
    assert ms._derive_regime_state("恐惧", None) == "bear"


def test_derive_regime_state_with_drawdown():
    ms = _ms()
    assert ms._derive_regime_state("中性", -0.20) == "panic"   # 深度回撤
    assert ms._derive_regime_state("贪婪", -0.20) == "panic"
    assert ms._derive_regime_state("中性", -0.10) == "bear"    # 中度回撤
    assert ms._derive_regime_state("贪婪", -0.02) == "bull"    # 贪婪未深跌
    assert ms._derive_regime_state("中性", -0.02) == "neutral"


def test_index_drawdown_point_in_time():
    ms = _ms()
    bars = _bars([100, 105, 110, 100, 95, 90], start=dt.date(2024, 1, 1))
    # 末日（2024-01-06, level 90）：窗口 3 → peak=100 → dd=-0.10
    d5 = dt.date(2024, 1, 6)
    dd5 = ms._index_drawdown(bars, d5, window=3)
    assert dd5 is not None and abs(dd5 - (-0.10)) < 1e-9
    # 峰值日（2024-01-03, level 110）：dd=0
    d2 = dt.date(2024, 1, 3)
    dd2 = ms._index_drawdown(bars, d2, window=3)
    assert dd2 is not None and abs(dd2 - 0.0) < 1e-9

    # point-in-time 不变性：追加未来极端数据，历史日 d2 的回撤应不变
    future = _bars([200, 300], start=dt.date(2024, 1, 7))
    extended = pd.concat([bars, future], ignore_index=True)
    dd2_ext = ms._index_drawdown(extended, d2, window=3)
    assert dd2_ext is not None and abs(dd2_ext - 0.0) < 1e-9, "未来数据不应污染历史日回撤"


def test_compute_emits_regime_state():
    # 小窗口以便用少量样本触发回撤判定
    ms = MarketSentiment({"market_sentiment": {"regime_state": {"drawdown_window": 3}}})
    # 构造一段先涨后深跌的行情，使末日处于深度回撤中
    levels = [100, 102, 105, 103, 98, 85]  # 末日 level 85，窗口内 peak=103 → dd≈-0.175
    bars = _bars(levels)
    end = dt.date(2024, 1, 6)
    row = ms.compute(end, bars)
    assert "regime_state" in row.columns
    state = row.iloc[0]["regime_state"]
    assert state in ("bull", "neutral", "bear", "panic")
    assert state == "panic", f"末日深度回撤应判为 panic，得到 {state}"


if __name__ == "__main__":
    test_derive_regime_state_no_drawdown()
    test_derive_regime_state_with_drawdown()
    test_index_drawdown_point_in_time()
    test_compute_emits_regime_state()
    print("✅ test_market_regime_state 通过")
