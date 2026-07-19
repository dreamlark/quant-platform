"""市场级综合情绪指数（factors/market_sentiment.MarketSentiment）单元测试（T1/T2）。

验证：
- compute 返回单日一行，含全部 sentiment_index 表字段
- index_value ∈ [0,100]（有量/价维度时）；regime∈{恐惧,中性,贪婪}；signal∈{买入,半仓,空仓}
- 五维分位合成：外部数据缺失时自动剔除该维并归一化（仅量/价仍可得指数）
- 外部数据齐备时 money/valuation/riskpremium 子维度非 None
- 无前视：compute 内部已按 date 截断 bars；输出 date == target
- GSISI 在提供 industry_map 时可计算（国信思路）

运行：python3.11 -m pytest tests/test_market_sentiment.py -q
      或 python tests/test_market_sentiment.py
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

from common.config import load_settings  # noqa: E402
from sources.adjust import make_sample_bars, adjust_prices  # noqa: E402
from factors.market_sentiment import MarketSentiment  # noqa: E402

CODES = [
    "600519.SH", "000858.SZ", "600036.SH", "000725.SZ",
    "601012.SH", "600900.SH", "300001.SZ",
]
N_DAYS = 120
INDUSTRY = {
    "600519.SH": "I02", "000858.SZ": "I02", "600036.SH": "I01",
    "000725.SZ": "I03", "601012.SH": "I04", "600900.SH": "I05",
    "300001.SZ": "I01",
}

# 用小窗口，避免测试需构造 750 个交易日历史
CFG = {
    "market_sentiment": {
        "percentile_window": 30,
        "dim_weights": {
            "volume": 0.25, "price": 0.25, "money": 0.20,
            "valuation": 0.15, "riskpremium": 0.15,
        },
        "thermometer": {"fear": 30, "greed": 70, "buy": 10, "empty": 90},
        "gsisi_window": 40,
        "gsisi_weeks": 6,
    }
}


def _bars() -> pd.DataFrame:
    start = dt.date(2024, 1, 1)
    frames = []
    for i, code in enumerate(CODES):
        rows = make_sample_bars(
            code, start=start, n_days=N_DAYS, seed=i + 1,
            start_price=10.0 + i * 5.0,
        )
        frames.append(pd.DataFrame(rows))
    raw = pd.concat(frames, ignore_index=True)
    # 与真实落库一致：计算后复权价 adj_back_close
    return adjust_prices(raw)


def _industry_map() -> dict:
    return {c: INDUSTRY[c] for c in CODES}


def _external_full(dates: pd.DatetimeIndex) -> dict:
    """构造齐备的外部数据（margin/northbound/etf/valuation/bond），覆盖 compute 全路径。"""
    idx = pd.DatetimeIndex(dates)
    rng = np.random.default_rng(0)
    df_margin = pd.DataFrame({
        "date": idx, "margin_balance": rng.uniform(1e11, 2e11, len(idx)),
        "margin_net_buy": rng.normal(1e9, 5e8, len(idx)),
    })
    df_north = pd.DataFrame({"date": idx, "net_buy": rng.normal(2e9, 1e9, len(idx))})
    df_etf = pd.DataFrame({"date": idx, "net_flow": rng.normal(5e8, 3e8, len(idx))})
    df_val = pd.DataFrame({"date": idx, "pe": rng.uniform(10, 20, len(idx))})
    df_bond = pd.DataFrame({"date": idx, "yield_10y": rng.uniform(0.02, 0.035, len(idx))})
    return {
        "margin": df_margin, "northbound": df_north, "etf": df_etf,
        "valuation": df_val, "bond": df_bond,
    }


@pytest.fixture
def env():
    bars = _bars()
    target = bars["date"].max()
    return bars, target, _industry_map()


def test_compute_shape_and_regime(env):
    bars, target, ind = env
    ms = MarketSentiment(CFG)
    df = ms.compute(target, bars, external={}, industry_map=ind)
    assert len(df) == 1, "应仅返回一行"
    row = df.iloc[0]
    assert row["date"] == target
    # 缺失外部数据时，量/价仍应算出，money/valuation/riskpremium 为 None
    assert row["sub_volume"] is not None
    assert row["sub_price"] is not None
    assert row["sub_money"] is None
    assert row["sub_valuation"] is None
    assert row["sub_riskpremium"] is None
    # 指数 ∈ [0,100]
    assert 0 <= row["index_value"] <= 100
    assert row["thermometer"] == row["index_value"]
    assert row["regime"] in ("恐惧", "中性", "贪婪")
    assert row["signal"] in ("买入", "半仓", "空仓")


def test_full_external_populates_dims(env):
    bars, target, ind = env
    dates = pd.DatetimeIndex(sorted(bars["date"].unique()))
    ext = _external_full(dates)
    ms = MarketSentiment(CFG)
    df = ms.compute(target, bars, external=ext, industry_map=ind)
    row = df.iloc[0]
    assert row["sub_money"] is not None, "外部齐备时资金维度应非空"
    assert row["sub_valuation"] is not None, "外部齐备时估值维度应非空"
    assert row["sub_riskpremium"] is not None, "外部齐备时风险溢价维度应非空"
    # 五维齐备时权重归一到 1，指数仍为 [0,100]
    assert 0 <= row["index_value"] <= 100


def test_no_lookahead(env):
    """compute 内部按 date 截断；传入含未来数据的 bars 也不应前视。

    强化（§四.8）：与「无泄漏基线」逐值比较——点-in-time 截断（compute 入口
    ``bars[bars['date'] <= date]`` + ``_rolling_pct`` 的 ``series.loc[:target]``）保证
    严格晚于目标日的数据被忽略，含泄漏输入的输出必须与纯净输入完全一致。

    注意：未来数据须**严格晚于**目标日（位移大于样本跨度），否则会与原始时间线
    重叠导致该日数据加倍，从而误判为「前视」（实为重叠而非泄漏）。
    """
    bars, target, ind = env
    future = bars.copy()
    # 位移 200 天 > 样本跨度(120天)，确保全部未来行严格晚于目标日，必被截断剔除
    future["date"] = future["date"] + dt.timedelta(days=200)
    leak = pd.concat([bars, future], ignore_index=True)
    ms = MarketSentiment(CFG)
    df_clean = ms.compute(target, bars, external={}, industry_map=ind)
    df_leak = ms.compute(target, leak, external={}, industry_map=ind)
    row = df_leak.iloc[0]
    base = df_clean.iloc[0]
    # 仅用 <= target 的数据，结果应与无泄漏时逐值一致
    assert row["sub_volume"] is not None
    assert row["sub_price"] is not None
    assert row["index_value"] == pytest.approx(base["index_value"], rel=1e-9), (
        "含未来数据的指数应与无泄漏基线逐值一致（不得前视）"
    )
    assert row["sub_volume"] == pytest.approx(base["sub_volume"], rel=1e-9)
    assert row["sub_price"] == pytest.approx(base["sub_price"], rel=1e-9)
    assert row["regime"] == base["regime"]
    assert row["signal"] == base["signal"]


def test_gsisi_computed(env):
    bars, target, ind = env
    ms = MarketSentiment(CFG)
    df = ms.compute(target, bars, external={}, industry_map=ind)
    gsisi = df.iloc[0]["gsisi"]
    assert isinstance(gsisi, (float, int))
    # 提供行业映射时 GSISI 应能产出有限值（可能为 0 仅当样本不足）
    assert np.isfinite(gsisi)


if __name__ == "__main__":
    bars = _bars()
    target = bars["date"].max()
    ind = _industry_map()
    ms = MarketSentiment(CFG)
    df = ms.compute(target, bars, external={}, industry_map=ind)
    print(f"[ok] 市场情绪：{len(df)} 行，目标日 {target}")
    print(df.iloc[0].to_dict())
    ext = _external_full(pd.DatetimeIndex(sorted(bars["date"].unique())))
    df2 = ms.compute(target, bars, external=ext, industry_map=ind)
    print("--- 含外部数据 ---")
    print(df2.iloc[0].to_dict())
    print("✅ test_market_sentiment 通过")
