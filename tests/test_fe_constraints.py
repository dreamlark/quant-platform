"""FE 硬约束断言级单测（P0-1 / P0-2 / P0-3 / P1-1 / P1-2 / P1-3 / P1-4 / P1-5 / P2-4）。

目标：验证金融工程评审提出的硬约束是否**真的实现正确**，而非仅能跑通。
重点：复权口径（P0-1）、可投资域（P0-3）、风险中性化（P1-4）、A股成本模型（P1-1）、
walk-forward/Deflated Sharpe（P1-2/3）、四源融合（P0-2/P1-5）、Repository 往返（CRUD）、
合规口径（P2-4）。

运行：python3.11 -m pytest tests/test_fe_constraints.py -q
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

from sources.adjust import adjust_prices
from sources.universe import UniverseFilter
from factors.risk_neutral import RiskNeutralizer
from factors.qlib_factors import QlibFactorEngine
from backtest.cost_model import CostModel
from fusion.signal_pool import SignalPool
from storage.repository import Repository
from storage.duckdb_client import DuckDBClient
from llm.prompts import COMPLIANCE_PREFIX, SYSTEM_BRIEF, SYSTEM_REVIEW
from llm.brief_gen import BriefGenerator
from llm.stock_review import StockReviewer

D = dt.date(2024, 6, 1)


# =====================================================================
# P0-1 复权正确性（后复权用于计算 / 前复权仅展示）
# =====================================================================
def _dividend_bars() -> pd.DataFrame:
    """构造含一次分红（day1 分红 1 元）的标的，pre_close 已含除权。"""
    return pd.DataFrame(
        {
            "code": ["X"] * 3,
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "close": [10.0, 11.0, 12.0],
            # day1 因分红，参考价=10-1=9；day2 正常=11
            "pre_close": [float("nan"), 9.0, 11.0],
            "open": [10, 11, 12],
            "high": [10, 11, 12],
            "low": [10, 11, 12],
            "vol": [1e5] * 3,
            "amount": [1e6] * 3,
        }
    )


def _expected_back_adjusted(close: np.ndarray, pre: np.ndarray) -> np.ndarray:
    """正确的后复权（锚定最早时点，point-in-time safe，计算用）。"""
    n = len(close)
    adj = np.empty(n)
    adj[0] = close[0]
    for i in range(1, n):
        pc = pre[i]
        if pd.isna(pc) or pc == 0:
            adj[i] = adj[i - 1]
        else:
            adj[i] = adj[i - 1] * close[i] / pc
    return adj


def _expected_front_adjusted(close: np.ndarray, pre: np.ndarray) -> np.ndarray:
    """正确的前复权（锚定最新时点，仅前端展示）。"""
    n = len(close)
    adj = np.empty(n)
    adj[-1] = close[-1]
    for i in range(n - 2, -1, -1):
        pc_next = pre[i + 1]
        cl_next = close[i + 1]
        if pd.isna(pc_next) or pc_next == 0 or cl_next == 0:
            adj[i] = adj[i + 1]
        else:
            adj[i] = adj[i + 1] * pc_next / cl_next
    return adj


def test_adjust_back_close_is_back_adjusted_anchored_earliest():
    """P0-1：adj_back_close 必须满足后复权（锚定最早时点，最新价≠原始价）。"""
    out = adjust_prices(_dividend_bars(), jump_detect=False)
    close = out["close"].to_numpy(dtype=float)
    pre = out["pre_close"].to_numpy(dtype=float)
    exp = _expected_back_adjusted(close, pre)
    got = out["adj_back_close"].to_numpy(dtype=float)

    # 锚定最早：首值 == 不复权价
    assert abs(got[0] - close[0]) < 1e-9, f"后复权首值应锚定原始价，得到 {got[0]} vs {close[0]}"
    # 最新价应偏离原始价（含累计分红/送转）
    assert abs(got[-1] - close[-1]) > 1e-6, "后复权最新价不应等于原始价（存在累计权益）"
    # 整体应等于正确的后复权序列
    np.testing.assert_allclose(got, exp, atol=1e-6)


def test_adjust_front_close_is_forward_adjusted_anchored_latest():
    """P0-1：adj_front_close 必须满足前复权（锚定最新时点，最新价=原始价，仅展示）。"""
    out = adjust_prices(_dividend_bars(), jump_detect=False)
    close = out["close"].to_numpy(dtype=float)
    pre = out["pre_close"].to_numpy(dtype=float)
    exp = _expected_front_adjusted(close, pre)
    got = out["adj_front_close"].to_numpy(dtype=float)

    # 锚定最新：末值 == 不复价
    assert abs(got[-1] - close[-1]) < 1e-9, f"前复权末值应锚定原始价，得到 {got[-1]} vs {close[-1]}"
    # 首值应偏离原始价
    assert abs(got[0] - close[0]) > 1e-6, "前复权首值不应等于原始价"
    np.testing.assert_allclose(got, exp, atol=1e-6)


def test_factors_read_adj_back_close():
    """P0-1：因子计算确实读取 adj_back_close（而非 adj_front_close / close）。"""
    bars = pd.DataFrame(
        {
            "code": ["A"] * 6,
            "date": pd.to_datetime(pd.date_range("2024-01-01", periods=6)),
            "close": [10, 11, 12, 13, 14, 15.0],
            "pre_close": [float("nan"), 10, 11, 12, 13, 14.0],
            "open": [10, 11, 12, 13, 14, 15.0],
            "high": [10, 11, 12, 13, 14, 15.0],
            "low": [10, 11, 12, 13, 14, 15.0],
            "vol": [1e5] * 6,
            "amount": [1e6] * 6,
            "adj_back_close": [10, 11, 12, 13, 14, 15.0],
            "adj_front_close": [99, 99, 99, 99, 99, 99.0],  # 故意给不同值，确保因子没读它
        }
    )
    eng = QlibFactorEngine(["f_momentum_5"])
    fl = eng.compute(bars)
    expected = bars["adj_back_close"] / bars["adj_back_close"].shift(5) - 1
    got = fl[fl["factor_name"] == "f_momentum_5"]["value"].reset_index(drop=True)
    np.testing.assert_allclose(got.to_numpy(), expected.to_numpy(), atol=1e-9, equal_nan=True)


# =====================================================================
# P0-3 可投资域（剔除 ST/*ST / 次新 / 停牌；保留退市标记）
# =====================================================================
def test_universe_filters_st_new_suspended_keeps_delisted():
    snap = D
    stock_list = pd.DataFrame(
        [
            {"code": "NORMAL.SH", "name": "正常股", "listed_date": dt.date(2000, 1, 1), "delisted": False},
            {"code": "ST.SH", "name": "ST某某", "listed_date": dt.date(2000, 1, 1), "delisted": False},
            {"code": "STARST.SH", "name": "*ST某某", "listed_date": dt.date(2000, 1, 1), "delisted": False},
            {"code": "NEW.SH", "name": "次新股", "listed_date": dt.date(2024, 5, 20), "delisted": False},
            {"code": "DELIST.SH", "name": "已退市股", "listed_date": dt.date(2000, 1, 1), "delisted": True},
        ]
    )
    # 停牌股并入候选；给除停牌外的标的近期一根行情，停牌股给旧行情
    bars = pd.DataFrame(
        [
            {"code": c, "date": dt.date(2024, 5, 30), "close": 10.0, "adj_back_close": 10.0}
            for c in ["NORMAL.SH", "ST.SH", "STARST.SH", "NEW.SH", "DELIST.SH"]
        ]
        + [{"code": "SUSP.SH", "date": dt.date(2024, 4, 20), "close": 10.0, "adj_back_close": 10.0}]
    )
    stock_list = pd.concat(
        [
            stock_list,
            pd.DataFrame([{"code": "SUSP.SH", "name": "停牌股", "listed_date": dt.date(2000, 1, 1), "delisted": False}]),
        ],
        ignore_index=True,
    )
    uni = UniverseFilter().build_universe(snap, stock_list, bars)
    by = uni.set_index("code")

    assert bool(by.loc["ST.SH", "in_universe"]) is False
    assert bool(by.loc["ST.SH", "is_st"]) is True
    assert bool(by.loc["STARST.SH", "in_universe"]) is False
    assert bool(by.loc["NEW.SH", "in_universe"]) is False  # 次新<60日
    assert bool(by.loc["SUSP.SH", "in_universe"]) is False  # 长期停牌
    assert bool(by.loc["DELIST.SH", "in_universe"]) is False  # 已退市不在可交易域
    assert bool(by.loc["DELIST.SH", "delisted"]) is True  # 但保留退市标记（避免生存偏差）
    assert bool(by.loc["NORMAL.SH", "in_universe"]) is True  # 正常股入选


# =====================================================================
# P1-4 风险中性化（残差与行业/市值近似无关）
# =====================================================================
def test_risk_neutralizer_residual_orthogonal_to_industry_mv():
    rng = np.random.default_rng(0)
    n = 24
    codes = [f"C{i:02d}" for i in range(n)]
    industries = rng.choice(["A", "B", "C"], size=n)
    mv = np.exp(rng.normal(20, 1, size=n))
    mv_z = (mv - mv.mean()) / mv.std()
    # 因子强暴露于市值与行业 -> 中性化后应被去除
    f1 = 2.0 * mv_z + 1.5 * (industries == "A").astype(float) + rng.normal(0, 0.1, n)
    factor_long = pd.DataFrame({"date": [D] * n, "code": codes, "factor_name": ["f1"] * n, "value": f1})
    meta = pd.DataFrame({"code": codes, "industry": industries, "mv": mv})

    out = RiskNeutralizer().neutralize(factor_long, meta)
    assert not out.empty

    # 注：RiskNeutralizer 内部以 log(市值) 作为市值暴露代理，故以同一基准确认正交性
    vals = out[out["factor_name"] == "f1"].set_index("code")["value"]
    # 用 numpy 位置参数形式（a_min, a_max）避免 numpy2.3 ndarray.clip(lower=) 关键字泄漏
    mv_log = np.log(np.clip(mv, 1e-9, None))
    X = pd.DataFrame({"const": 1.0, "mv_log": mv_log}, index=codes)
    ind = pd.get_dummies(pd.Series(industries, index=codes), drop_first=True).astype(float)
    X = pd.concat([X, ind], axis=1)
    Xm = X.to_numpy(dtype=float)
    y = vals.reindex(codes).to_numpy(dtype=float)
    coef, *_ = np.linalg.lstsq(Xm, y, rcond=None)
    # 中性化后，市值(log)与行业系数应≈0
    assert abs(coef[1]) < 1e-6, f"市值(log)暴露未去除 coef={coef[1]}"
    for j in range(2, len(coef)):
        assert abs(coef[j]) < 1e-6, f"行业暴露未去除 coef={coef[j]}"


def test_risk_neutralizer_skips_without_meta():
    factor_long = pd.DataFrame({"date": [D], "code": ["A"], "factor_name": ["f1"], "value": [1.0]})
    out = RiskNeutralizer().neutralize(factor_long, None)
    assert out is factor_long  # 缺元数据原样返回，不阻断


# =====================================================================
# P1-1 A 股成本模型（佣金/印花税/滑点/涨跌停；T+1 配置）
# =====================================================================
def test_cost_model_commission_stamp_slippage():
    cm = CostModel()
    assert abs(cm.commission - 0.00025) < 1e-12  # 万2.5
    assert abs(cm.stamp_duty - 0.001) < 1e-12  # 千1
    v = 1_000_000.0
    # 大额佣金 = 金额×万2.5
    assert abs(cm.commission_of(v) - v * 0.00025) < 1e-9
    # 小额佣金触底 5 元
    assert abs(cm.commission_of(100.0) - 5.0) < 1e-9
    # 印花税 = 金额×千1
    assert abs(cm.stamp_of(v) - v * 0.001) < 1e-9
    # 滑点 = 金额×2bp
    assert abs(cm.slippage_of(v) - v * 2 / 1e4) < 1e-9
    # 买入成本 = 佣金 + 滑点（无印花税）
    buy = cm.cost("buy", 100.0, v)
    assert abs(buy - (cm.commission_of(v) + cm.slippage_of(v))) < 1e-9
    # 卖出成本含印花税
    sell = cm.cost("sell", 100.0, v)
    assert abs(sell - buy - cm.stamp_of(v)) < 1e-9
    assert sell > buy


def test_cost_model_limit_up_down_liquidity():
    cm = CostModel()
    pre = 10.0
    limit_up = pre * (1 + cm.limit_up_pct)  # 11
    limit_down = pre * (1 - cm.limit_down_pct)  # 9
    # 涨停（≥涨停价）不可买
    assert cm.can_trade("buy", limit_up, pre) is False
    assert cm.can_trade("buy", limit_up + 0.01, pre) is False
    assert cm.can_trade("buy", limit_up - 0.01, pre) is True
    # 跌停（≤跌停价）不可卖
    assert cm.can_trade("sell", limit_down, pre) is False
    assert cm.can_trade("sell", limit_down - 0.01, pre) is False
    assert cm.can_trade("sell", limit_down + 0.01, pre) is True


def test_cost_model_t_plus_one_config():
    """P1-1：T+1 制度默认开启（配置层）。注：CostModel 仅暴露配置开关，
    未提供显式同日买卖拦截 API —— 见测试报告中的残留风险说明。"""
    cm = CostModel()
    assert cm.t_plus_one is True
    cm2 = CostModel({"cost_model": {"t_plus_one": False}})
    assert cm2.t_plus_one is False


# =====================================================================
# P1-2 / P1-3 walk-forward + Deflated Sharpe + 基准对照
# =====================================================================
def test_walk_forward_outputs_deflated_sharpe_alpha_beta_benchmark():
    from backtest.walk_forward import WalkForwardBacktester

    rng = np.random.default_rng(3)
    n_codes, n_dates = 8, 300
    dates = pd.to_datetime(pd.date_range("2023-01-01", periods=n_dates))
    codes = [f"C{i}" for i in range(n_codes)]
    # 共同市场收益 + 极小个股特质：制造真实 IC，但组合 Sharpe 适中（避免 DSR 分母退化）
    mkt = rng.normal(0, 0.01, n_dates)
    prices = {}
    for c in codes:
        p = 10.0
        seq = [p]
        for t in range(1, n_dates):
            ret = mkt[t] + rng.normal(0, 0.001)
            p *= 1 + ret
            seq.append(p)
        prices[c] = np.array(seq)

    fwd = {}
    rows = []
    for c in codes:
        arr = prices[c]
        f = np.concatenate([arr[1:] / arr[:-1] - 1, [np.nan]])
        fwd[c] = f
        for t in range(n_dates):
            rows.append(
                {
                    "code": c,
                    "date": dates[t],
                    "adj_back_close": arr[t],
                    "open": arr[t],
                    "high": arr[t],
                    "low": arr[t],
                    "close": arr[t],
                    "pre_close": arr[t - 1] if t > 0 else arr[t],
                    "vol": 1e5,
                    "amount": 1e6,
                }
            )
    bars_df = pd.DataFrame(rows)
    fstd = np.nanstd(np.concatenate(list(fwd.values())))
    frows = [
        {"date": dates[t], "code": c, "factor_name": "f1", "value": 0.5 * fwd[c][t] + rng.normal(0, fstd * 0.5)}
        for c in codes
        for t in range(n_dates)
    ]
    factor_long = pd.DataFrame(frows)
    uni = pd.DataFrame([{"date": D, "code": c, "in_universe": True} for c in codes])

    ret_df, metrics, report_rows = WalkForwardBacktester({}).run(bars_df, factor_long, uni)
    assert not ret_df.empty, "walk-forward 未产出样本外收益"
    assert "bench_ret" in ret_df.columns
    for k in ("deflated_sharpe", "alpha_ann", "beta"):
        assert k in metrics, f"metrics 缺 {k}"
    assert "bench_sharpe" in metrics  # 基准对照字段存在
    assert "benchmark" in report_rows.columns
    assert np.isfinite(metrics["beta"])
    assert np.isfinite(metrics["deflated_sharpe"])
    assert 0.0 <= metrics["deflated_sharpe"] <= 1.0


# =====================================================================
# P0-2 / P1-5 四源融合（方向/置信度/四源贡献；预测降级）
# =====================================================================
def test_signal_pool_fuse_output_contract():
    date = D
    codes = ["A", "B", "C"]
    factor_long = pd.DataFrame(
        {
            "date": [date] * 6,
            "code": codes * 2,
            "factor_name": ["f_momentum_5", "f_reversal_5"] * 3,
            "value": [0.5, -0.3, 0.2, 0.4, -0.1, 0.7],
        }
    )
    tech_df = pd.DataFrame({"date": [date] * 3, "code": codes, "tech_score": [0.6, -0.4, 0.1]})
    sent_df = pd.DataFrame({"date": [date] * 3, "code": codes, "sentiment_score": [0.3, -0.5, 0.2]})

    out = SignalPool().fuse(factor_long, tech_df, sent_df, None, None, None, date)
    assert set(out.columns) >= {
        "direction",
        "confidence",
        "factor_contrib",
        "tech_contrib",
        "sentiment_contrib",
        "predict_contrib",
    }
    assert set(out["direction"].unique()).issubset({-1, 0, 1})
    assert (out["confidence"] >= 0).all() and (out["confidence"] <= 1).all()
    # 预测未装 -> predict_contrib 全 0（降级）
    assert (out["predict_contrib"] == 0).all()
    assert "source_tags" in out.columns


def test_signal_pool_predict_contrib_nonzero_when_predict_present():
    """预测源接入时第4源贡献应可非零（确认降级是数据驱动而非恒零）。"""
    date = D
    codes = ["A", "B"]
    factor_long = pd.DataFrame({"date": [date] * 2, "code": codes, "factor_name": ["f_momentum_5"] * 2, "value": [0.5, 0.2]})
    tech_df = pd.DataFrame({"date": [date] * 2, "code": codes, "tech_score": [0.6, -0.4]})
    sent_df = pd.DataFrame({"date": [date] * 2, "code": codes, "sentiment_score": [0.3, -0.5]})
    predict_df = pd.DataFrame(
        {
            "date": [date] * 2,
            "code": codes,
            "model_name": ["kronos"] * 2,
            "horizon": [1, 1],
            "dir_pred": [1, -1],
            "ret_pred": [0.01, -0.01],
            "lower": [0.0, 0.0],
            "upper": [0.0, 0.0],
            "dir_acc_hist": [0.6, 0.6],
        }
    )
    predict_health_df = pd.DataFrame({"model_name": ["kronos"], "date": [date], "mape": [0.1], "dir_acc": [0.6], "weight": [1.0]})
    out = SignalPool().fuse(factor_long, tech_df, sent_df, predict_df, None, predict_health_df, date)
    assert not (out["predict_contrib"] == 0).all()


# =====================================================================
# Repository CRUD 往返一致性（daily_bars / signals / watchlist）
# =====================================================================
def _mem_repo() -> Repository:
    client = DuckDBClient(":memory:")
    return Repository(client, client)


def test_repository_daily_bars_roundtrip():
    repo = _mem_repo()
    bars = pd.DataFrame(
        [
            {
                "code": "600519.SH",
                "date": D,
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "pre_close": 10,
                "adj_back_close": 10.5,
                "adj_front_close": 10.5,
                "vol": 1e5,
                "amount": 1e6,
                "source": "mem",
            },
            {
                "code": "600519.SH",
                "date": D + dt.timedelta(days=1),
                "open": 10.5,
                "high": 11.5,
                "low": 10,
                "close": 11,
                "pre_close": 10.5,
                "adj_back_close": 11,
                "adj_front_close": 11,
                "vol": 1e5,
                "amount": 1e6,
                "source": "mem",
            },
        ]
    )
    assert repo.save_bars(bars) == 2
    got = repo.load_bars(codes=["600519.SH"])
    assert len(got) == 2
    assert np.allclose(got["close"].sort_values().to_numpy(), [10.5, 11.0])
    # 幂等 upsert：重跑仍为 2 行
    repo.save_bars(bars)
    assert len(repo.load_bars(codes=["600519.SH"])) == 2


def test_repository_signals_roundtrip():
    repo = _mem_repo()
    sig = pd.DataFrame(
        [
            {
                "date": D,
                "code": "600519.SH",
                "direction": 1,
                "confidence": 0.8,
                "source_tags": "因子",
                "factor_contrib": 0.1,
                "tech_contrib": 0.2,
                "sentiment_contrib": 0.3,
                "predict_contrib": 0.0,
            }
        ]
    )
    repo.save_signals(sig)
    got = repo.load_signals(D)
    assert len(got) == 1
    assert int(got.iloc[0]["direction"]) == 1
    assert float(got.iloc[0]["confidence"]) == 0.8


def test_repository_watchlist_crud():
    repo = _mem_repo()
    repo.upsert_watch("600519.SH", "茅台", 1500.0, 100)
    assert "600519.SH" in repo.load_watch_codes()
    repo.delete_watch("600519.SH")
    assert "600519.SH" not in repo.load_watch_codes()


# =====================================================================
# P2-4 合规口径（前缀 / 免责声明 / 置信度来自信号层）
# =====================================================================
def test_compliance_prefix_present_in_prompts():
    assert "研究观点" in COMPLIANCE_PREFIX
    assert "买卖建议" in COMPLIANCE_PREFIX
    assert ("不是" in COMPLIANCE_PREFIX) or ("不得" in COMPLIANCE_PREFIX)
    # 简报/简评 system prompt 复用合规前缀
    assert SYSTEM_BRIEF.startswith(COMPLIANCE_PREFIX)
    assert SYSTEM_REVIEW.startswith(COMPLIANCE_PREFIX)


class _FakeLLM:
    def chat(self, system, user, use_cache=False):
        return "（模型生成内容占位）"


def test_brief_appends_disclaimer():
    disclaimer = "【免责声明】本研究观点不构成投资建议。"
    gen = BriefGenerator(_FakeLLM(), disclaimer)
    sig = pd.DataFrame(
        [
            {
                "date": D,
                "code": "A",
                "direction": 1,
                "confidence": 0.7,
                "source_tags": "因子",
                "factor_contrib": 0.1,
                "tech_contrib": 0.0,
                "sentiment_contrib": 0.0,
                "predict_contrib": 0.0,
            }
        ]
    )
    sector = pd.DataFrame(
        [
            {
                "date": D,
                "sector_code": "I01",
                "sector_name": "银行",
                "change_pct": 0.01,
                "rs": 0.5,
                "net_inflow": 1e8,
                "rotation_signal": "进攻",
            }
        ]
    )
    uni = pd.DataFrame([{"date": D, "code": "A", "in_universe": True}])
    content, temp = gen.generate_market_brief(D, sig, sector, uni)
    assert disclaimer in content
    assert isinstance(temp, int) and 0 <= temp <= 100


def test_review_confidence_from_signal_layer():
    disclaimer = "【免责声明】本研究观点不构成投资建议。"
    rev = StockReviewer(_FakeLLM(), disclaimer)
    signal_row = {
        "date": D,
        "code": "600519.SH",
        "direction": 1,
        "confidence": 0.82,
        "source_tags": "因子",
        "factor_contrib": 0.1,
        "tech_contrib": 0.0,
        "sentiment_contrib": 0.0,
        "predict_contrib": 0.0,
    }
    result = rev.review("600519.SH", "茅台", signal_row, {"cost_price": 1500, "shares": 100, "current_price": 1600})
    # 置信度来自信号层，非 LLM 自报
    assert abs(result.confidence - 0.82) < 1e-9
    # action 由信号方向映射（研究观点标签）
    assert result.action == "买入"
    # 正文挂固定免责声明
    assert disclaimer in result.content
