"""T0 量价代理情绪（factors/sentiment.SentimentExtractor）单元测试。

验证：
- 输出每只标的 (date, code, sentiment_score)，分数 ∈ [-1,1]
- 含新增 breadth_rank / relative_strength 组件（extract_components）
- 无前视：extract 只用截至 date 的数据（输出 date 不超过目标日）
- 零外部源依赖（纯 OHLCV bars）

运行：python3.11 -m pytest tests/test_sentiment_t0.py -q
      或 python tests/test_sentiment_t0.py
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

from common.config import load_settings  # noqa: E402
from sources.adjust import make_sample_bars, adjust_prices  # noqa: E402
from factors.sentiment import SentimentExtractor  # noqa: E402

CODES = [
    "600519.SH", "000858.SZ", "600036.SH", "000725.SZ",
    "601012.SH", "600900.SH", "300001.SZ",
]
N_DAYS = 120

# 测试用行业/市值（备选，T0 不强制需要 universe）
INDUSTRY = {
    "600519.SH": "I02", "000858.SZ": "I02", "600036.SH": "I01",
    "000725.SZ": "I03", "601012.SH": "I04", "600900.SH": "I05",
    "300001.SZ": "I01",
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


@pytest.fixture
def env():
    bars = _bars()
    settings = load_settings()
    target = bars["date"].max()
    return bars, settings, target


def test_extract_shape_and_range(env):
    bars, settings, target = env
    ext = SentimentExtractor(settings)
    df = ext.extract(bars, CODES)
    assert not df.empty, "情绪输出不应为空"
    assert {"date", "code", "sentiment_score"}.issubset(df.columns)
    assert df["sentiment_score"].between(-1.0, 1.0).all(), "分数应 ∈ [-1,1]"
    assert set(df["code"]) == set(CODES), "每只标的都应有一行"
    assert (df["date"] <= target).all(), "存在前视：输出日期超过目标日"


def test_components_present(env):
    bars, settings, target = env
    ext = SentimentExtractor(settings)
    comp = ext.extract_components(bars, CODES)
    required = [
        "turnover_anomaly", "amplitude", "limit_up_rate",
        "return_skew", "breadth_rank", "relative_strength",
    ]
    for col in required:
        assert col in comp.columns, f"缺失子指标组件 {col}"
    # breadth_rank 应为 0~1 横截面分位
    assert comp["breadth_rank"].dropna().between(0, 1).all()


def test_weights_from_config(env):
    bars, settings, target = env
    # 覆盖配置：只给两个非零权重
    settings = dict(settings)
    settings["sentiment"] = {"window": 20, "weights": {"turnover_anomaly": 0.5, "amplitude": 0.5}}
    ext = SentimentExtractor(settings)
    assert ext.weights["turnover_anomaly"] == 0.5
    df = ext.extract(bars, CODES)
    assert not df.empty


def test_empty_input():
    ext = SentimentExtractor({})
    out = ext.extract(pd.DataFrame(), [])
    assert out.empty
    assert list(out.columns) == ["date", "code", "sentiment_score"]


if __name__ == "__main__":
    bars = _bars()
    settings = load_settings()
    target = bars["date"].max()
    ext = SentimentExtractor(settings)
    df = ext.extract(bars, CODES)
    print(f"[ok] T0 情绪：{len(df)} 行，目标日 {target}")
    print(f"     分数范围 [{df['sentiment_score'].min():.3f}, {df['sentiment_score'].max():.3f}]")
    comp = ext.extract_components(bars, CODES)
    print(f"     组件列：{list(comp.columns)}")
    print("✅ test_sentiment_t0 通过")
