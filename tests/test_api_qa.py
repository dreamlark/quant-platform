"""API 端点（T08）断言级测试：内存 Repository 注入 + FastAPI TestClient。

覆盖 13 个数据端点返回 200 且响应体非空；自选股记账接口增/查/删往返。
不依赖任何重型依赖（DuckDB 内存库 + 手工注入数据）。

运行：python3.11 -m pytest tests/test_api_qa.py -q
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from storage.duckdb_client import DuckDBClient
from storage.repository import Repository
import api.database as api_db
from api.main import app

D = dt.date(2024, 6, 1)
CODE = "600519.SH"
DISCLAIMER = "【免责声明】研究观点不构成投资建议。"


def _populate(repo: Repository) -> None:
    bars = pd.DataFrame(
        [
            {
                "code": CODE,
                "date": D,
                "open": 1600,
                "high": 1620,
                "low": 1580,
                "close": 1600,
                "pre_close": 1590,
                "adj_back_close": 1600,
                "adj_front_close": 1600,
                "vol": 1e6,
                "amount": 1.6e9,
                "source": "mem",
            }
        ]
    )
    repo.save_bars(bars)
    repo.save_universe(
        pd.DataFrame(
            [
                {
                    "date": D,
                    "code": CODE,
                    "name": "贵州茅台",
                    "in_universe": True,
                    "is_st": False,
                    "listed_days": 3000,
                    "delisted": False,
                }
            ]
        )
    )
    repo.save_factor_long(
        pd.DataFrame([{"date": D, "code": CODE, "factor_name": "f_momentum_5", "value": 0.05}])
    )
    repo.save_health(
        pd.DataFrame(
            [
                {
                    "factor_name": "f_momentum_5",
                    "date": D,
                    "ic": 0.05,
                    "icir": 0.1,
                    "rank_return": 0.02,
                    "turnover": 0.5,
                    "status": "有效",
                    "weight": 1.0,
                }
            ]
        )
    )
    repo.save_signals(
        pd.DataFrame(
            [
                {
                    "date": D,
                    "code": CODE,
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
    )
    repo.save_sector(
        pd.DataFrame(
            [
                {
                    "date": D,
                    "sector_code": "I01",
                    "sector_name": "白酒",
                    "change_pct": 0.02,
                    "rs": 0.6,
                    "net_inflow": 1e8,
                    "rotation_signal": "进攻",
                }
            ]
        )
    )
    repo.save_brief(D, "今日市场综合简报占位。", 60, DISCLAIMER)
    repo.save_review(D, CODE, "个股研究观点占位。", "买入", "因子贡献为正。", 0.8, DISCLAIMER)
    repo.upsert_watch(CODE, "贵州茅台", 1500.0, 100)


@pytest.fixture
def client():
    c = DuckDBClient(":memory:")
    repo = Repository(c, c)
    _populate(repo)
    # 注入到 api.database 模块全局（get_repository 读取此处）
    api_db._REPO = repo
    api_db._SETTINGS = {}
    yield TestClient(app)
    api_db._REPO = None
    api_db._SETTINGS = None


def test_api_endpoints_return_200_and_nonempty(client):
    paths = [
        "/",
        "/health",
        "/api/factors/list",
        "/api/factors/health",
        "/api/factors/values",
        "/api/sectors/rotation",
        "/api/dashboard/summary",
        "/api/dashboard/brief",
        f"/api/stocks/{CODE}",
        f"/api/stocks/{CODE}/bars",
        "/api/stocks/search?q=600519",
        "/api/watchlist",
        f"/api/watchlist/{CODE}/review",
    ]
    for p in paths:
        r = client.get(p)
        assert r.status_code == 200, f"GET {p} -> {r.status_code}: {r.text[:200]}"
        body = r.json()
        if isinstance(body, list):
            assert len(body) >= 1, f"{p} 返回空列表"
        else:
            assert body, f"{p} 返回空响应"


def test_watchlist_add_list_delete_roundtrip(client):
    r = client.post(
        "/api/watchlist",
        json={"code": "000001.SZ", "name": "平安银行", "cost_price": 12.5, "shares": 200},
    )
    assert r.status_code == 200
    lst = client.get("/api/watchlist").json()
    codes = [w["code"] for w in lst]
    assert "000001.SZ" in codes
    # 查（详情）
    d = client.delete("/api/watchlist/000001.SZ")
    assert d.status_code == 200
    lst2 = client.get("/api/watchlist").json()
    assert "000001.SZ" not in [w["code"] for w in lst2]
