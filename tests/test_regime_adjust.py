"""融合层 regime 调节（fusion/signal_pool.py）单元测试 —— 对应 #4 / P1-2。

验证：
- 默认开启（安全默认）：regime_state 不在缩放表或 k=1.0 时不缩放；bear/panic 缩放。
- 关闭时：无论 regime_state 为何，置信度不缩放。
- 仅缩放置信度，方向（direction）不变。
- 缩放系数来自 config（scale: bull/neutral/bear/panic），panic 最小。
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fusion.signal_pool import SignalPool  # noqa: E402

CODES = ["600519.SH", "000858.SZ", "600036.SH", "000725.SZ", "601012.SH"]


def _factor_long(date: dt.date) -> pd.DataFrame:
    vals = [1.0, -1.0, 0.5, -0.5, 2.0]
    out = []
    for fname in ("momentum", "value"):
        for c, v in zip(CODES, vals):
            out.append({"date": date, "code": c, "factor_name": fname, "value": float(v)})
    return pd.DataFrame(out)


SCALE = {"bull": 1.0, "neutral": 1.0, "bear": 0.70, "panic": 0.45}
CFG_ON = {"fusion": {"regime_adjust": {"enabled": True, "scale": dict(SCALE)}}}
CFG_OFF = {"fusion": {"regime_adjust": {"enabled": False, "scale": dict(SCALE)}}}


def _fuse(sp: SignalPool, regime=None) -> pd.DataFrame:
    date = dt.date(2024, 6, 1)
    return sp.fuse(
        _factor_long(date), None, None, None, None, None, date, CODES, regime=regime
    )


def test_default_off_no_scaling():
    sp = SignalPool(CFG_OFF)
    assert sp.regime_adjust_enabled is False
    base = _fuse(sp, regime=None)
    panic = _fuse(sp, regime="panic")
    # 关闭时 regime 被忽略，置信度一致
    for (_, rb), (_, rp) in zip(base.iterrows(), panic.iterrows()):
        assert rb["confidence"] == rp["confidence"]
        assert rb["direction"] == rp["direction"]


def test_on_extreme_scales_confidence():
    sp = SignalPool(CFG_ON)
    assert sp.regime_adjust_enabled is True
    base = _fuse(sp, regime=None)
    bear = _fuse(sp, regime="bear")
    panic = _fuse(sp, regime="panic")
    for (_, rb), (_, rbr), (_, rpa) in zip(base.iterrows(), bear.iterrows(), panic.iterrows()):
        # 置信度被缩放（≤ 原值），且 panic 比 bear 更收敛
        assert rbr["confidence"] <= rb["confidence"]
        assert rpa["confidence"] <= rb["confidence"]
        assert rpa["confidence"] <= rbr["confidence"]
        # 方向不变
        assert rbr["direction"] == rb["direction"] == rpa["direction"]
        # 缩放比例约 = 配置系数
        if rb["confidence"] > 0:
            assert abs(rbr["confidence"] - round(rb["confidence"] * SCALE["bear"], 3)) <= 0.01
            assert abs(rpa["confidence"] - round(rb["confidence"] * SCALE["panic"], 3)) <= 0.01


def test_neutral_bull_no_scaling_when_on():
    sp = SignalPool(CFG_ON)
    base = _fuse(sp, regime=None)
    for state in ("neutral", "bull"):
        s = _fuse(sp, regime=state)
        for (_, rb), (_, rs) in zip(base.iterrows(), s.iterrows()):
            assert rb["confidence"] == rs["confidence"]
            assert rb["direction"] == rs["direction"]


if __name__ == "__main__":
    sp_on = SignalPool(CFG_ON)
    b = _fuse(sp_on, regime=None)
    br = _fuse(sp_on, regime="bear")
    pa = _fuse(sp_on, regime="panic")
    print("[ok] 中性:", b["confidence"].tolist())
    print("bear:", br["confidence"].tolist())
    print("panic:", pa["confidence"].tolist())
    print("✅ test_regime_adjust 通过")
