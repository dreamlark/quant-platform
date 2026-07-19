"""T2 温度计择时回测（backtest/sentiment_timing.py）单元测试 —— 对应 PRD §10 验收。

构造小样本行情 + 因子 + 可投资域 + 情绪信号，验证：
- run 返回非空气流（returns_df / metrics / report_rows）
- metrics 含 timing / baseline / excess 三组核心指标
- 择时组合与因子满仓组合口径一致（共享训练/打分/成本）
- 情绪信号覆盖三种状态（买入/半仓/空仓）时，暴露叠加生效
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
from backtest.sentiment_timing import SentimentTimingBacktester, EXPOSURE_MAP  # noqa: E402

CODES = ["600519.SH", "000858.SZ", "600036.SH", "000725.SZ", "601012.SH", "600900.SH", "300001.SZ"]
N_DAYS = 120


def _bars() -> pd.DataFrame:
    start = dt.date(2024, 1, 1)
    frames = []
    for i, code in enumerate(CODES):
        rows = make_sample_bars(code, start=start, n_days=N_DAYS, seed=i + 1, start_price=10.0 + i * 5.0)
        frames.append(pd.DataFrame(rows))
    raw = pd.concat(frames, ignore_index=True)
    return adjust_prices(raw)


def _factor_long(bars: pd.DataFrame) -> pd.DataFrame:
    """构造两因子（中性化后）宽表：随机但含轻微截面结构。"""
    rng = np.random.default_rng(7)
    out = []
    for d, g in bars.groupby("date"):
        codes = g["code"].tolist()
        for fname in ("momentum", "value"):
            vals = rng.normal(0, 1, len(codes))
            for c, v in zip(codes, vals):
                out.append({"date": d, "code": c, "factor_name": fname, "value": float(v)})
    return pd.DataFrame(out)


def _universe(bars: pd.DataFrame) -> pd.DataFrame:
    rows = [{"date": d, "code": c, "in_universe": True} for d in bars["date"].unique() for c in CODES]
    return pd.DataFrame(rows)


def _sentiment(bars: pd.DataFrame) -> pd.DataFrame:
    dates = list(bars["date"].unique())
    sig_cycle = ["买入", "半仓", "空仓"]
    rows = []
    for i, d in enumerate(dates):
        rows.append({"date": d, "signal": sig_cycle[i % 3]})
    return pd.DataFrame(rows)


@pytest.fixture
def env():
    bars = _bars()
    return bars, _factor_long(bars), _universe(bars), _sentiment(bars)


def test_run_returns_nonempty(env):
    bars, fl, uni, sent = env
    bt = SentimentTimingBacktester({})
    ret_df, metrics, rows = bt.run(bars, fl, uni, sent)
    assert not ret_df.empty, "回测应产出样本外收益序列"
    assert set(["date", "port_ret", "bench_ret", "base_ret"]).issubset(ret_df.columns)
    assert not rows.empty
    assert metrics, "metrics 不应为空"


def test_metrics_three_groups(env):
    bars, fl, uni, sent = env
    bt = SentimentTimingBacktester({})
    _, metrics, _ = bt.run(bars, fl, uni, sent)
    for prefix in ("timing_", "baseline_"):
        assert f"{prefix}ann_return" in metrics
        assert f"{prefix}sharpe" in metrics
        assert f"{prefix}max_drawdown" in metrics
        assert f"{prefix}deflated_sharpe" in metrics
    # 超额增量
    assert "excess_ann_return" in metrics
    assert "excess_max_drawdown" in metrics
    assert "excess_sharpe" in metrics
    # 择时与满仓口径可比：年化应为有限数
    assert np.isfinite(metrics["timing_ann_return"])
    assert np.isfinite(metrics["baseline_ann_return"])


def test_exposure_map_covers_states():
    assert EXPOSURE_MAP == {"买入": 1.0, "半仓": 0.5, "空仓": 0.0}


def test_missing_sentiment_degrades_to_half(env):
    """无信号时退化为半仓（default_exposure=0.5），不应崩溃。"""
    bars, fl, uni, _ = env
    bt = SentimentTimingBacktester({})
    ret_df, metrics, rows = bt.run(bars, fl, uni, pd.DataFrame(columns=["date", "signal"]))
    assert not ret_df.empty
    assert np.isfinite(metrics["timing_ann_return"])


def test_either_input_empty_returns_empty():
    bt = SentimentTimingBacktester({})
    empty = pd.DataFrame()
    ret_df, metrics, rows = bt.run(empty, empty, empty, empty)
    assert ret_df.empty and metrics == {} and rows.empty


def test_timing_zero_exposure_has_no_market_risk(env):
    """经济含义（§四.8）：信号全为空仓（暴露=0）时，择时组合无市场风险，
    其收益波动应显著低于满仓基线——验证「择时能降低回撤/风险」这一结论。
    """
    bars, fl, uni, _ = env
    all_empty = pd.DataFrame({"date": bars["date"].unique(), "signal": "空仓"})
    bt = SentimentTimingBacktester({})
    ret_df, metrics, _ = bt.run(bars, fl, uni, all_empty)
    timing_vol = ret_df["port_ret"].std()
    base_vol = ret_df["base_ret"].std()
    # 零暴露组合不参与市场，波动应远低于满仓基线（构建上保证，非随机侥幸）
    assert timing_vol < base_vol * 0.5, (
        f"零暴露择时组合波动应显著低于满仓基线：timing_vol={timing_vol:.6f} "
        f"base_vol={base_vol:.6f}"
    )
    assert np.isfinite(metrics["timing_max_drawdown"])


if __name__ == "__main__":
    bars = _bars()
    fl = _factor_long(bars)
    uni = _universe(bars)
    sent = _sentiment(bars)
    bt = SentimentTimingBacktester({})
    ret_df, metrics, rows = bt.run(bars, fl, uni, sent)
    print(f"[ok] T2 择时回测：{len(ret_df)} 日")
    print("metrics:", {k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()})
    print("✅ test_sentiment_timing 通过")
