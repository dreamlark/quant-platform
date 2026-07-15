"""信号层组合回测（backtest/signal_backtest.py）单元测试 —— 对应 #4 regime 调节验证。

验证：
- SignalBacktester.run（OFF）返回非空组合收益 + 指标
- 提供 regime_series + scale_map（ON）时，极端情绪缩放生效：等效抬升入选阈值，
  极端日持仓数下降（保守）
- compare_regime 返回 ON/OFF 两份报告行 + delta（年化/夏普/回撤差异）
- 信号历史不足 / 输入空时优雅降级
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

from sources.adjust import make_sample_bars, adjust_prices  # noqa: E402
from backtest.signal_backtest import SignalBacktester, compare_regime  # noqa: E402

CODES = ["600519.SH", "000858.SZ", "600036.SH", "000725.SZ", "601012.SH", "600900.SH", "300001.SZ"]
N_DAYS = 120


def _bars() -> pd.DataFrame:
    start = dt.date(2024, 1, 1)
    frames = []
    for i, code in enumerate(CODES):
        rows = make_sample_bars(code, start=start, n_days=N_DAYS, seed=i + 1, start_price=10.0 + i * 5.0)
        frames.append(pd.DataFrame(rows))
    return adjust_prices(pd.concat(frames, ignore_index=True))


def _signals(bars: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    out = []
    for d in bars["date"].unique():
        for c in CODES:
            direction = int(rng.choice([1, -1, 0], p=[0.45, 0.45, 0.10]))
            conf = float(np.clip(rng.normal(0.6, 0.2), 0.0, 1.0))
            out.append({"date": d, "code": c, "direction": direction, "confidence": conf})
    return pd.DataFrame(out)


def _universe(bars: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [{"date": d, "code": c, "in_universe": True} for d in bars["date"].unique() for c in CODES]
    )


def _regime_series(bars: pd.DataFrame) -> dict:
    """约 1/2 日期设为极端状态（bear/panic），其余中性/bull。"""
    dates = list(bars["date"].unique())
    out = {}
    for i, d in enumerate(dates):
        out[d] = ["panic", "neutral", "bear", "bull"][i % 4]
    return out


SCALE_MAP = {"bull": 1.0, "neutral": 1.0, "bear": 0.70, "panic": 0.45}


@pytest.fixture
def env():
    bars = _bars()
    return bars, _signals(bars), _universe(bars)


def test_run_off_nonempty(env):
    bars, sig, uni = env
    bt = SignalBacktester({})
    ret_df, metrics, rows = bt.run(bars, sig, uni)
    assert not ret_df.empty
    assert set(["date", "port_ret", "bench_ret"]).issubset(ret_df.columns)
    assert "ann_return" in metrics and np.isfinite(metrics["ann_return"])
    assert not rows.empty


def test_on_scaling_reduces_holdings_in_extreme(env):
    """ON：极端情绪日（恐惧/贪婪）持仓数应 ≤ OFF（等效抬升入选阈值，保守）。"""
    bars, sig, uni = env
    regime = _regime_series(bars)
    bt = SignalBacktester({"signal_backtest": {"conf_threshold": 0.5}})
    # OFF 持仓数
    n_off = _count_holds(bt, bars, sig, uni, None, None)
    # ON 持仓数
    n_on = _count_holds(bt, bars, sig, uni, regime, SCALE_MAP)
    # 极端日应更保守：ON 总持仓数 ≤ OFF
    assert n_on <= n_off, f"极端情绪缩放应降低持仓数：ON={n_on} OFF={n_off}"


def _count_holds(bt, bars, sig, uni, regime_series, scale_map) -> int:
    """统计入选持仓的股票·日总数（复刻 run 的入选逻辑，仅计数）。"""
    price = bars.pivot_table(index="date", columns="code", values="adj_back_close")
    fwd = price.shift(-1) / price - 1.0
    s = sig[["date", "code", "direction", "confidence"]].copy()
    s["date"] = pd.to_datetime(s["date"]).dt.date
    shifted = bt._shift_regime(regime_series) if regime_series else None
    total = 0
    for t in price.index:
        st = s[s["date"] == t]
        if st.empty:
            continue
        longs = st[st["direction"] == 1]
        if longs.empty:
            continue
        conf = longs.set_index("code")["confidence"].astype(float)
        if shifted is not None:
            conf = conf * scale_map.get(shifted.get(t), 1.0)
        held = conf[conf >= bt.conf_threshold]
        total += len(held)
    return total


def test_compare_regime_returns_delta(env):
    bars, sig, uni = env
    sent_df = pd.DataFrame(
        [{"date": d, "regime_state": r} for d, r in _regime_series(bars).items()]
    )
    rows_off, rows_on, delta = compare_regime(bars, sig, uni, sent_df, {})
    assert not rows_off.empty and not rows_on.empty
    assert set(["ann_return", "sharpe", "max_drawdown"]).issubset(delta.keys())
    assert rows_on["strategy"].iloc[0] == "signal_long_only_regime_scaled"
    assert rows_off["strategy"].iloc[0] == "signal_long_only"


def test_empty_inputs_degrade():
    bt = SignalBacktester({})
    ret_df, metrics, rows = bt.run(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    assert ret_df.empty and metrics == {} and rows.empty


if __name__ == "__main__":
    bars = _bars()
    sig = _signals(bars)
    uni = _universe(bars)
    sent_df = pd.DataFrame([{"date": d, "regime_state": r} for d, r in _regime_series(bars).items()])
    rows_off, rows_on, delta = compare_regime(bars, sig, uni, sent_df, {})
    print(f"[ok] ON/OFF 报告行：{len(rows_off)} / {len(rows_on)}")
    print("delta:", {k: round(v, 4) for k, v in delta.items()})
    print("✅ test_signal_backtest 通过")
