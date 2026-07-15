"""P1-1b 动态 IC 加权 + 3 滚动窗口 IC≈0 剔除闸门 单元测试（纯逻辑，快速）。

验证：
- _darts_train_cutoff：截止日早于 max_date（业务日偏移）。
- _compute_ic_and_gate：清晰正 IC → 不剔除；近零 IC 跨 ≥3 窗口 → 剔除；样本不足 → nan/不剔除。
- _dynamic_weight：dropped→0；ic>eps 按比例给权；ic<=eps→0；IC 不可得回退 dir_acc。
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from factors.prediction import PredictionGenerator


def _gen(max_date=dt.date(2024, 6, 1)):
    return PredictionGenerator({})


def _ic_pairs_same(n_dates=12, start=dt.date(2024, 1, 1), actual="same"):
    """构造 ic_pairs：每日期 4 标的，ret_pred 单调递增；actual 决定 IC。

    actual='same'  → 与实际同向（IC≈+1）
    actual='zero'  → 与实际无秩相关（IC=0，构造 [0.2,0.4,0.1,0.3]）
    """
    pairs = []
    d = start
    for _ in range(n_dates):
        rp = [0.1, 0.2, 0.3, 0.4]
        ac = [0.1, 0.2, 0.3, 0.4] if actual == "same" else [0.2, 0.4, 0.1, 0.3]
        for c, (r, a) in enumerate(zip(rp, ac)):
            pairs.append({"date": d, "code": f"60000{c}.SH", "ret_pred": r, "actual": a})
        d += dt.timedelta(days=1)
    return pairs


def test_darts_train_cutoff_before_max_date():
    pg = _gen()
    md = dt.date(2024, 6, 1)
    cutoff = pg._darts_train_cutoff(md, n_eval=15, max_horizon=10)
    assert cutoff < pd.Timestamp(md)
    # 偏移 = 15 + 10 + 10 = 35 业务日
    assert (pd.Timestamp(md) - cutoff).days >= 35


def test_ic_positive_not_dropped():
    pg = _gen()
    ic, rolling, dropped = pg._compute_ic_and_gate(_ic_pairs_same(12, actual="same"))
    assert ic is not None and ic > 0.9
    assert dropped is False
    assert rolling is not None and rolling > 0.9


def test_ic_zero_triggers_drop_gate():
    pg = _gen()
    # 每窗口 3 日、需 ≥3 窗口 → 至少 9 日；构造 12 日近零 IC
    ic, rolling, dropped = pg._compute_ic_and_gate(_ic_pairs_same(12, actual="zero"))
    assert abs(ic) < 1e-6
    assert dropped is True, "连续 3 窗口 IC≈0 应触发剔除"


def test_ic_insufficient_not_dropped():
    pg = _gen()
    # 每日期仅 2 标的（<3）→ 无 per-date IC → nan / 不剔除
    pairs = [
        {"date": dt.date(2024, 1, i + 1), "code": f"60000{c}.SH",
         "ret_pred": 0.1 * (c + 1), "actual": 0.1 * (c + 1)}
        for i in range(5) for c in range(2)
    ]
    ic, rolling, dropped = pg._compute_ic_and_gate(pairs)
    assert ic is not None and pd.isna(ic)
    assert dropped is False


def test_dynamic_weight_dropped_zero():
    pg = _gen()
    assert pg._dynamic_weight(0.04, True, 0.6) == 0.0


def test_dynamic_weight_scaled_by_ic():
    pg = _gen()
    # ic=0.04 介于 eps(0.02) 与 ref(0.05) 之间 → 比例 (0.04-0.02)/(0.05-0.02)=2/3
    w = pg._dynamic_weight(0.04, False, 0.6)
    assert abs(w - pg.base_predict_weight * (2.0 / 3.0)) < 1e-9


def test_dynamic_weight_le_eps_zero():
    pg = _gen()
    assert pg._dynamic_weight(0.01, False, 0.6) == 0.0


def test_dynamic_weight_fallback_dir_acc():
    pg = _gen()
    # IC 不可得（nan）→ 回退 dir_acc 软加权
    w = pg._dynamic_weight(float("nan"), False, 0.6)
    assert abs(w - pg._weight(0.6)) < 1e-9


if __name__ == "__main__":
    test_darts_train_cutoff_before_max_date()
    test_ic_positive_not_dropped()
    test_ic_zero_triggers_drop_gate()
    test_ic_insufficient_not_dropped()
    test_dynamic_weight_dropped_zero()
    test_dynamic_weight_scaled_by_ic()
    test_dynamic_weight_le_eps_zero()
    test_dynamic_weight_fallback_dir_acc()
    print("✅ test_prediction_ic 通过")
