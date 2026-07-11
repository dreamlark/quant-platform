"""KronosAdapter 单元测试：验证接线逻辑 + 优雅降级（无需真实权重）。

真实权重经 HF xet CDN 下载，沙箱内被网络策略拦截；本测试用 ``tests/stub_model``
（忠实模仿官方 model 包接口）验证适配器完整路径，并验证 vendor 缺失时的 fail-fast 降级。

运行： python3.11 tests/test_kronos_adapter.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd

from sources.adjust import make_sample_bars
from factors.kronos_adapter import KronosAdapter

_STUB = os.path.join(os.path.dirname(__file__), "stub_model")


def _make_df() -> pd.DataFrame:
    rows = make_sample_bars(
        "600977", start=dt.date(2025, 1, 1), n_days=250, seed=7, drift=0.0003, vol=0.018
    )
    return pd.DataFrame(rows)


def test_fail_fast_when_vendor_missing():
    """vendor 代码缺失 -> predict 返回 None（不崩溃，优雅降级）。"""
    os.environ["KRONOS_REPO_PATH"] = "/nonexistent/kronos/code"
    ad = KronosAdapter()
    out = ad.predict(_make_df(), 5)
    assert out is None, "vendor 缺失应降级为 None"
    print("[test] fail-fast 降级 OK")


def test_real_wiring_via_stub():
    """用桩验证：OHLCV 规整 -> predictor.predict -> ret_pred/区间 提取 全链路正确。"""
    os.environ["KRONOS_REPO_PATH"] = _STUB
    ad = KronosAdapter(sample_count=1)
    df = _make_df()
    out = ad.predict(df, 5)
    assert out is not None, "桩路径应返回预测"
    assert set(out.keys()) == {"ret_pred", "lower", "upper"}
    # 桩使 close 逐日 +1% -> ret_pred>0
    assert out["ret_pred"] > 0, f"ret_pred 应>0，实际 {out['ret_pred']}"
    assert out["upper"] > out["ret_pred"] > out["lower"], f"区间顺序错误 {out}"
    # 复用已加载模型（不应重新加载）
    out1 = ad.predict(df, 1)
    assert out1 is not None and out1["ret_pred"] > 0
    print(f"[test] 桩全链路 OK -> {out}")


def test_horizon_variants():
    os.environ["KRONOS_REPO_PATH"] = _STUB
    ad = KronosAdapter(sample_count=1)
    df = _make_df()
    for h in (1, 5, 10):
        o = ad.predict(df, h)
        assert o is not None and o["ret_pred"] > 0, f"h={h} 失败 {o}"
    print("[test] horizon 1/5/10 OK")


if __name__ == "__main__":
    test_fail_fast_when_vendor_missing()
    test_real_wiring_via_stub()
    test_horizon_variants()
    print("ALL KRONOS ADAPTER TESTS PASSED")
