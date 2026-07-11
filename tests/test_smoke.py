"""冒烟测试：核心链路 ingest→universe→factors→sentiment→neutralize→fusion→signals 落 DuckDB。

关键要求：重型依赖（qlib/czsc/kronos/darts/backtrader/quantstats）未装时该路径必须跑通。
本测试构造内存假数据源（多只股票 sample 日K），跑通全链路并打印 signals 表若干行。

运行：python tests/test_smoke.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import pandas as pd

# 仓库根加入路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import load_settings  # noqa: E402
from sources.adjust import adjust_prices, make_sample_bars  # noqa: E402
from sources.base import InMemoryDataSource, DataSourceRouter  # noqa: E402
from sources.universe import UniverseFilter  # noqa: E402
from storage.duckdb_client import DuckDBClient  # noqa: E402
from storage.repository import Repository  # noqa: E402
from scheduler.orchestrator import Orchestrator  # noqa: E402

# 7 只标的：6 只正常（覆盖申万 I01~I05）+ 1 只 ST（验证可投资域剔除）
CODES = [
    "600519.SH",  # 消费
    "000858.SZ",  # 消费
    "600036.SH",  # 金融
    "000725.SZ",  # 科技
    "601012.SH",  # 制造
    "600900.SH",  # 周期
    "300001.SZ",  # ST（名称含 ST，应被剔除）
]
N_DAYS = 120
INDUSTRY = {
    "600519.SH": "I02", "000858.SZ": "I02", "600036.SH": "I01",
    "000725.SZ": "I03", "601012.SH": "I04", "600900.SH": "I05",
    "300001.SZ": "I01",
}
MV = {
    "600519.SH": 2.0e12, "000858.SZ": 5.0e11, "600036.SH": 8.0e11,
    "000725.SZ": 1.5e11, "601012.SH": 1.2e11, "600900.SH": 4.0e11,
    "300001.SZ": 3.0e10,
}


def build_stock_list() -> pd.DataFrame:
    rows = []
    for i, code in enumerate(CODES):
        name = "ST测试股" if code == "300001.SZ" else code
        rows.append(
            {
                "code": code,
                "name": name,
                "listed_date": dt.date(2000, 1, 1),
                "delisted": False,
                "industry": INDUSTRY[code],
                "mv": MV[code],
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    print("=" * 60)
    print("A 股量化平台 · 核心链路冒烟测试")
    print("=" * 60)

    settings = load_settings()

    # 1) 构造内存假数据源
    mem = InMemoryDataSource()
    start = dt.date(2024, 1, 1)
    for i, code in enumerate(CODES):
        rows = make_sample_bars(
            code, start=start, n_days=N_DAYS, seed=i + 1,
            start_price=10.0 + i * 5.0,
        )
        mem.add(code, rows)
    print(f"[ok] 构造假数据源：{len(CODES)} 只标的 × {N_DAYS} 交易日")

    # 2) 内存 DuckDB + Repository
    client = DuckDBClient(":memory:")
    repo = Repository(client, client)
    stock_list = build_stock_list()
    target_date = max(r["date"] for code in CODES for r in mem._data[code])

    orch = Orchestrator(repo, settings, data_source=DataSourceRouter([mem]), stock_list=stock_list)

    # 3) 核心链路
    print("\n-- step: ingest --")
    raw = orch.step_ingest(start, target_date)
    print(f"[ok] 写入 daily_bars：{len(raw)} 行")

    print("-- step: universe --")
    uni = orch.step_universe(target_date)
    in_u = int(uni["in_universe"].sum())
    print(f"[ok] universe：候选 {len(uni)} / 入选 {in_u}（ST 应被剔除）")
    assert in_u == len(CODES) - 1, "ST 未被剔除"

    print("-- step: factors --")
    fl = orch.step_factors(target_date)
    print(f"[ok] factor_values：{len(fl)} 行（{fl['factor_name'].nunique()} 因子）")

    print("-- step: sentiment --")
    sd = orch.step_sentiment(target_date)
    print(f"[ok] sentiment：{len(sd)} 行")

    print("-- step: predict --")
    pd_df = orch.step_predict(target_date)
    ph = orch.predict_health
    print(f"[ok] predict_values：{len(pd_df)} 行；predict_health：{len(ph)} 行")

    print("-- step: health --")
    fh = orch.step_health(target_date)
    print(f"[ok] factor_health：{len(fh)} 行")

    print("-- step: neutralize --")
    neu = orch.step_neutralize(target_date)
    print(f"[ok] 中性化因子：{len(neu)} 行")

    print("-- step: fusion --")
    signals = orch.step_fusion(target_date)
    print(f"[ok] signals：{len(signals)} 行")

    # 4) 校验 signals 落库并可查
    db_signals = repo.load_signals(target_date)
    assert not db_signals.empty, "signals 未落库"
    assert set(
        ["direction", "confidence", "factor_contrib", "tech_contrib",
         "sentiment_contrib", "predict_contrib", "source_tags"]
    ).issubset(db_signals.columns), "signals 字段缺失"

    print("\n===== signals 表（前 8 行）=====")
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)
    show = db_signals.copy()
    show["date"] = show["date"].astype(str)
    print(show.head(8).to_string(index=False))

    # 5) 回测（可选，验证 walk-forward 可跑）
    print("\n-- step: backtest (walk-forward) --")
    try:
        rep = orch.step_backtest(target_date)
        if not rep.empty:
            print(f"[ok] backtest_report：{len(rep)} 行")
            dsr = rep[rep["metric_name"] == "deflated_sharpe"]["metric_value"]
            print(f"     Deflated Sharpe = {float(dsr.iloc[0]):.3f}" if not dsr.empty else "     (无 DSR)")
        else:
            print("[warn] backtest 无输出（样本不足）")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] backtest 异常（不影响核心链路）：{exc}")

    print("\n✅ 冒烟测试通过：核心链路可运行，signal 已落 DuckDB。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
