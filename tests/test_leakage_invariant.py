"""P0-1 前视偏差不变量测试（合成探针，零外部依赖、快速、可作为 CI 门禁）。

核心不变量：
    在任意时刻 t，因子/信号/预测的生成只能读到 date <= t 的数据；
    回测在 t 的持仓只赚取 t -> t+1 的收益（次日收益），绝不使用
    t 当日收益或 t+1 -> t+2 收益。

设计思路（黄金标准 = 「追加纯未来数据 -> 历史输出不变」隔离测试）：
    若某模块在生成历史日 t 的输出时偷偷读了 t 之后的数据，则向行情
    尾部追加一段「纯未来」数据后，历史日的输出必然变化。此变化即为
    前视泄漏的实证信号。
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from factors.factor_calc import FactorCalculator
from backtest.walk_forward import WalkForwardBacktester
from factors.market_sentiment import MarketSentiment
from factors.prediction import PredictionGenerator


# ----------------------------------------------------------------------
# 合成数据构造
# ----------------------------------------------------------------------
def _bday_range(start: dt.date, n: int):
    """返回 n 个连续工作日。"""
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def _make_bars(n_dates: int = 150, codes=("600000.SH", "600519.SH"), seed: int = 42) -> pd.DataFrame:
    """构造合成日 K（后复权价 = 收盘价），随机游走、确定性可复现。"""
    rng = np.random.default_rng(seed)
    dates = _bday_range(dt.date(2023, 1, 1), n_dates)
    rows = []
    for code in codes:
        price = 100.0
        for date in dates:
            price *= 1.0 + rng.normal(0, 0.02)
            close = float(price)
            high = close * (1.0 + abs(rng.normal(0, 0.01)))
            low = close * (1.0 - abs(rng.normal(0, 0.01)))
            open_ = close * (1.0 + rng.normal(0, 0.005))
            vol = float(rng.integers(1_000_000, 5_000_000))
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "vol": vol,
                    "amount": close * vol,
                    "adj_back_close": close,
                    "adj_front_close": close,
                }
            )
    return pd.DataFrame(rows)


def _extend_future(bars: pd.DataFrame, extra: int = 40) -> pd.DataFrame:
    """在行情尾部追加一段「纯未来」日期（严格在最后日期之后），风格与原序列一致。"""
    rng = np.random.default_rng(999)
    last = bars["date"].max()
    rows = []
    for code in bars["code"].unique():
        sub = bars[bars["code"] == code].sort_values("date")
        price = float(sub["close"].iloc[-1])
        d = last
        for _ in range(extra):
            d += dt.timedelta(days=1)
            while d.weekday() >= 5:
                d += dt.timedelta(days=1)
            price *= 1.0 + rng.normal(0, 0.02)
            close = float(price)
            rows.append(
                {
                    "date": d,
                    "code": code,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "vol": 1_000_000.0,
                    "amount": close * 1_000_000.0,
                    "adj_back_close": close,
                    "adj_front_close": close,
                }
            )
    return pd.concat([bars, pd.DataFrame(rows)], ignore_index=True)


# ----------------------------------------------------------------------
# 测试
# ----------------------------------------------------------------------
def test_factor_no_lookahead_isolation():
    """黄金标准：向行情追加纯未来日期后，历史日因子值必须逐位不变。"""
    bars = _make_bars(n_dates=150)
    codes = sorted(bars["code"].unique())
    calc = FactorCalculator()

    fl_clean, _ = calc.compute(bars, codes)
    fl_ext, _ = calc.compute(_extend_future(bars, extra=40), codes)

    assert not fl_clean.empty, "因子计算返回空，数据构造可能有误"

    clean = fl_clean.pivot_table(index=["code", "date"], columns="factor_name", values="value")
    ext = fl_ext.pivot_table(index=["code", "date"], columns="factor_name", values="value")
    ext2 = ext.reindex(index=clean.index, columns=clean.columns)

    # NaN 模式必须一致（若未来数据把某 NaN 变成有值 = 前视）
    nan_clean = clean.isna()
    nan_ext = ext2.isna()
    assert (nan_clean.values == nan_ext.values).all(), (
        "因子 NaN 模式在未来数据追加后变化，疑似前视泄漏"
    )

    # 有限值必须逐位相等（容差 = 浮点）
    finite = (~nan_clean) & (~nan_ext)
    diff = (clean - ext2).abs().fillna(0.0)
    max_diff = float(diff[finite].max().max())
    assert max_diff < 1e-9, (
        f"发现前视：历史因子在未来数据追加后变化，max|Δ|={max_diff:.3e}"
    )


def test_walk_forward_uses_next_day_return():
    """回测在测试日 t 的基准收益必须等于 t -> t+1 的次日收益均值（point-in-time）。"""
    dates = _bday_range(dt.date(2023, 1, 1), 60)
    # 需 >=5 只标的，walk-forward 的 IC 加权才会在每训练日算出有效权重
    codes = [f"60000{i}.SH" for i in range(10)]
    rng = np.random.default_rng(7)
    rows = []
    for code in codes:
        price = 50.0
        for date in dates:
            price *= 1.0 + rng.normal(0, 0.02)
            close = float(price)
            rows.append(
                {
                    "date": date,
                    "code": code,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "vol": 1_000_000.0,
                    "amount": close * 1_000_000.0,
                    "adj_back_close": close,
                    "adj_front_close": close,
                }
            )
    bars = pd.DataFrame(rows)
    factor_long = pd.DataFrame(
        [
            {"date": d, "code": c, "factor_name": "f_dummy", "value": rng.normal()}
            for d in dates
            for c in codes
        ]
    )
    universe = pd.DataFrame([{"code": c, "in_universe": True} for c in codes])

    wf = WalkForwardBacktester({})
    ret_df, _metrics, _rows = wf.run(bars, factor_long, universe)
    assert not ret_df.empty, "walk-forward 未产出任何测试日"

    price = bars.pivot_table(index="date", columns="code", values="adj_back_close")
    fwd_exp = price.shift(-1) / price - 1.0

    for _, row in ret_df.iterrows():
        t = row["date"]
        fwd_t = fwd_exp.loc[t]
        if fwd_t.isna().all():
            # 末日无次日收益，回测对应 bench_ret 必为 NaN（不污染断言）
            assert pd.isna(row["bench_ret"]), f"末日 bench_ret 应为 NaN，得到 {row['bench_ret']}"
            continue
        expected = float(fwd_t.mean())
        assert abs(row["bench_ret"] - expected) < 1e-9, (
            f"bench_ret[{t}]={row['bench_ret']} 不等于 t->t+1 次日收益均值={expected} "
            f"（疑似误用当日或 t+1->t+2 收益）"
        )


def test_sentiment_rolling_pct_point_in_time():
    """温度计分位在 target 日必须只用 <= target 的数据（篡改未来不影响）。"""
    ms = MarketSentiment({})
    dates = _bday_range(dt.date(2023, 1, 1), 120)
    rng = np.random.default_rng(3)
    vals = 50.0 + np.cumsum(rng.normal(0, 1, len(dates)))
    series = pd.Series(vals, index=dates)

    target = dates[80]
    p1 = ms._rolling_pct(series, target, window=60)

    series2 = series.copy()
    for d in dates:
        if d > target:
            series2[d] = 1e9  # 恶意篡改未来
    p2 = ms._rolling_pct(series2, target, window=60)

    assert abs(p1 - p2) < 1e-9, f"分位在篡改未来后变化：{p1} vs {p2}（前视）"


def test_prediction_baseline_uses_past_only():
    """预测基线（5 日动量）纯后视；篡改未来价格不影响历史日预测。"""
    work = _make_bars(n_dates=120)
    base = PredictionGenerator._baseline_predict(work)

    # 1) 基线在 t 的动量必须 = pr/pr.shift(5)-1（纯后视）
    for code, g in work.groupby("code"):
        g = g.sort_values("date").reset_index(drop=True)
        pr = g["adj_back_close"]
        for i in range(5, len(g)):
            t = g["date"].iloc[i]
            exp = float(pr.iloc[i] / pr.iloc[i - 5] - 1.0)
            got = float(
                base[(base["code"] == code) & (base["date"] == t)]["pred_score"].iloc[0]
            )
            assert abs(got - exp) < 1e-9, f"baseline 动量公式不符：{got} vs {exp}"

    # 2) 篡改 t_mid 之后的价格 -> t_mid 的基线预测不变
    code0 = work["code"].unique()[0]
    g0 = work[work["code"] == code0].sort_values("date").reset_index(drop=True)
    t_mid = g0["date"].iloc[60]
    work2 = work.copy()
    mask = (work2["code"] == code0) & (work2["date"] > t_mid)
    work2.loc[mask, ["close", "adj_back_close", "open", "high", "low"]] *= 1e6
    base2 = PredictionGenerator._baseline_predict(work2)

    a = float(base[(base["code"] == code0) & (base["date"] == t_mid)]["pred_score"].iloc[0])
    b = float(base2[(base2["code"] == code0) & (base2["date"] == t_mid)]["pred_score"].iloc[0])
    assert abs(a - b) < 1e-9, "baseline 在篡改未来价格后变化 -> 前视泄漏"


def test_run_daily_ordering_fusion_before_market_sentiment():
    """时序护栏：run_daily 必须先 fusion 后 market_sentiment，
    否则融合会读到「当日」（尚未落库的）regime，构成前视。"""
    import inspect

    from scheduler.orchestrator import Orchestrator

    src = inspect.getsource(Orchestrator.run_daily)
    assert src.index("step_fusion") < src.index("step_market_sentiment"), (
        "run_daily 必须先调用 step_fusion 再 step_market_sentiment，"
        "否则融合层会误用当日 regime（前视偏差）"
    )
