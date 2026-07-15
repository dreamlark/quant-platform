"""融合层 regime 调节（fusion/signal_pool.py）单元测试 —— 对应 #4。

验证：
- 默认关闭：无论 regime 为何，置信度不缩放（合规 PRD §8 默认 OFF）
- 开启后：极端情绪（恐惧/贪婪）缩放置信度；中性不缩放
- 仅缩放置信度，方向（direction）不变
- 缩放系数来自 config（fear_scale/greed_scale/neutral_scale）
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


CFG_ON = {
    "fusion": {
        "regime_adjust": {"enabled": True, "fear_scale": 0.75, "greed_scale": 0.75, "neutral_scale": 1.0}
    }
}
CFG_OFF = {
    "fusion": {
        "regime_adjust": {"enabled": False, "fear_scale": 0.5, "greed_scale": 0.5, "neutral_scale": 1.0}
    }
}


def _fuse(sp: SignalPool, regime=None) -> pd.DataFrame:
    date = dt.date(2024, 6, 1)
    return sp.fuse(
        _factor_long(date), None, None, None, None, None, date, CODES, regime=regime
    )


def test_default_off_no_scaling():
    sp = SignalPool(CFG_OFF)
    assert sp.regime_adjust_enabled is False
    base = _fuse(sp, regime=None)
    fear = _fuse(sp, regime="恐惧")
    # 关闭时 regime 被忽略，置信度一致
    for (_, rb), (_, rf) in zip(base.iterrows(), fear.iterrows()):
        assert rb["confidence"] == rf["confidence"]
        assert rb["direction"] == rf["direction"]


def test_on_extreme_scales_confidence():
    sp = SignalPool(CFG_ON)
    assert sp.regime_adjust_enabled is True
    base = _fuse(sp, regime=None)
    fear = _fuse(sp, regime="恐惧")
    greed = _fuse(sp, regime="贪婪")
    for (_, rb), (_, rf), (_, rg) in zip(base.iterrows(), fear.iterrows(), greed.iterrows()):
        # 置信度被缩放（≤ 原值）
        assert rf["confidence"] <= rb["confidence"]
        assert rg["confidence"] <= rb["confidence"]
        # 方向不变
        assert rf["direction"] == rb["direction"] == rg["direction"]
        # 缩放比例约 = fear_scale（0.75）
        if rb["confidence"] > 0:
            assert abs(rf["confidence"] - round(rb["confidence"] * 0.75, 3)) <= 0.01


def test_neutral_no_scaling_when_on():
    sp = SignalPool(CFG_ON)
    base = _fuse(sp, regime=None)
    neutral = _fuse(sp, regime="中性")
    for (_, rb), (_, rn) in zip(base.iterrows(), neutral.iterrows()):
        assert rb["confidence"] == rn["confidence"]
        assert rb["direction"] == rn["direction"]


if __name__ == "__main__":
    sp_on = SignalPool(CFG_ON)
    b = _fuse(sp_on, regime=None)
    f = _fuse(sp_on, regime="恐惧")
    print("[ok] 中性:", b["confidence"].tolist())
    print("恐惧:", f["confidence"].tolist())
    print("✅ test_regime_adjust 通过")
