"""API 集成测试：校验 FastAPI 层能正确读取 DuckDB 分析库。

修复要点（相对初版）：注入点必须是 ``api.database._REPO`` / ``api.database._SETTINGS``，
而非 ``api.main._REPO`` —— ``get_repository()`` 读取的是 ``api.database`` 模块的全局单例。

链路：先跑通核心编排（含 sector/LLM 步骤，让简报与板块数据落库），再注入同一内存
Repository 到 API 模块命名空间，用 TestClient 逐个校验数据端点返回 200 且非空。

运行：python tests/test_api.py
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
from sources.adjust import make_sample_bars  # noqa: E402
from sources.base import InMemoryDataSource, DataSourceRouter  # noqa: E402
from storage.duckdb_client import DuckDBClient  # noqa: E402
from storage.repository import Repository  # noqa: E402
from scheduler.orchestrator import Orchestrator  # noqa: E402

# 注入点：必须指向 api.database 模块全局
import api.database as api_db  # noqa: E402
from api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

CODES = [
    "600519.SH", "000858.SZ", "600036.SH", "000725.SZ",
    "601012.SH", "600900.SH", "300001.SZ",  # ST，应被剔除
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
    for code in CODES:
        rows.append(
            {
                "code": code,
                "name": "ST测试股" if code == "300001.SZ" else code,
                "listed_date": dt.date(2000, 1, 1),
                "delisted": False,
                "industry": INDUSTRY[code],
                "mv": MV[code],
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    print("=" * 60)
    print("A 股量化平台 · API 集成测试")
    print("=" * 60)

    settings = load_settings()
    mem = InMemoryDataSource()
    start = dt.date(2024, 1, 1)
    for i, code in enumerate(CODES):
        mem.add(code, make_sample_bars(code, start=start, n_days=N_DAYS, seed=i + 1,
                                       start_price=10.0 + i * 5.0))
    client = DuckDBClient(":memory:")
    repo = Repository(client, client)
    stock_list = build_stock_list()
    target_date = max(r["date"] for code in CODES for r in mem._data[code])
    orch = Orchestrator(repo, settings, data_source=DataSourceRouter([mem]), stock_list=stock_list)

    # 跑通全链路（含 sector / llm，让简报与板块数据落库）
    orch.step_ingest(start, target_date)
    orch.step_universe(target_date)
    orch.step_factors(target_date)
    orch.step_sentiment(target_date)
    orch.step_predict(target_date)
    orch.step_health(target_date)
    orch.step_neutralize(target_date)
    orch.step_fusion(target_date)
    orch.step_sector(target_date)
    # 预置一只自选股（必须早于 step_llm，否则不会生成逐只简评），
    # 用以验证 watchlist / dashboard 告警 / review 链路
    repo.upsert_watch("600519.SH", "600519.SH", cost_price=1500.0, shares=100)
    orch.step_llm(target_date)

    # === 关键修复：注入到 api.database 模块全局 ===
    api_db._REPO = repo
    api_db._SETTINGS = settings

    c = TestClient(app)
    failures = []

    def check(path: str, expect_codes_ok: tuple[int, ...] = (200,)) -> dict:
        r = c.get(path)
        ok = r.status_code in expect_codes_ok
        mark = "ok" if ok else "FAIL"
        print(f"[{mark}] GET {path} -> {r.status_code}")
        if not ok:
            failures.append((path, r.status_code, r.text[:200]))
        return r.json() if ok and r.status_code == 200 else {}

    # 基础 / 健康
    check("/")
    check("/health")

    # 因子页
    check("/api/factors/list")
    check("/api/factors/health")
    check("/api/factors/values")
    # 板块页
    check("/api/sectors/rotation")
    # 看板
    check("/api/dashboard/summary")
    check("/api/dashboard/brief")
    # 股票页
    check("/api/stocks/600519.SH")
    check("/api/stocks/600519.SH/bars")
    check("/api/stocks/search?q=600519")
    # 自选股
    check("/api/watchlist")
    check("/api/watchlist/600519.SH/review")
    # 运维监控（验证 monitor 改走仓储层后的聚合端点仍正常，§四.3）
    check("/api/monitor/overview")
    check("/api/monitor/batch-run")
    check("/api/monitor/history")

    print("\n--- 端点数据抽样校验 ---")
    summ = c.get("/api/dashboard/summary").json()
    print(f"  dashboard.date={summ.get('date')} "
          f"temperature={summ.get('market_temperature')} "
          f"top_signals={len(summ.get('top_signals', []))} "
          f"sectors={len(summ.get('sectors', []))} "
          f"alerts={len(summ.get('watchlist_alerts', []))}")
    assert summ.get("top_signals"), "dashboard 缺少 top_signals"
    assert summ.get("sectors"), "dashboard 缺少 sectors"
    assert summ.get("brief"), "dashboard 缺少 brief"

    sd = c.get("/api/stocks/600519.SH").json()
    print(f"  stock detail direction={sd.get('direction')} "
          f"conf={sd.get('confidence')} factor_detail={len(sd.get('factor_detail', []))}")
    assert sd.get("factor_detail"), "信号拆解下钻 factor_detail 为空"

    # 运维监控总览结构校验（§四.3：monitor 已统一走仓储层）
    ov = c.get("/api/monitor/overview").json()
    for key in ("data", "factors", "models", "freshness", "market_sentiment", "pipeline"):
        assert key in ov, f"monitor/overview 缺少字段 {key}"
    assert "latest_date" in ov["data"], "monitor data 应包含 latest_date"
    print(f"  monitor: data.latest_date={ov['data'].get('latest_date')} "
          f"factors.total={ov['factors'].get('total')} "
          f"models={len(ov['models'])} market_sentient.available={ov['market_sentiment'].get('available')}")

    if failures:
        print(f"\n❌ API 集成测试失败：{len(failures)} 个端点异常")
        for f in failures:
            print("   ", f)
        return 1

    print("\n✅ API 集成测试通过：所有数据端点均能从 DuckDB 正确返回。")
    return 0


def test_api_integration() -> None:
    """让 pytest 收集并执行 API 全链路集成测试（修复 §三.1 假绿）。

    main() 内部对失败端点返回 1，这里用断言把它转为测试失败。
    """
    assert main() == 0, "API 集成测试存在失败端点"


if __name__ == "__main__":
    sys.exit(main())
