"""P3-3 数据质量测试：不变量检测（注入坏行必红、干净数据通过）。

用内存 DuckDB 构建可控样本，验证 evaluation/data_quality 的五类不变量：
- universe_exclusions（可投资域不含 ST/退市）
- duplicate_dates（无重复 (code,date)）
- nonpositive_price（价格 > 0）
- future_dates（无未来日期）
- adjust_jump（后复权无异常跳变）
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from evaluation.data_quality import check_data_quality
from storage.duckdb_client import DuckDBClient
from storage.repository import Repository
from storage.schema import init_schema

AS_OF = dt.date(2024, 6, 14)
SETTINGS = {"adjust": {}}


def _bars(code: str, prices, dates) -> pd.DataFrame:
    rows = []
    for d, p in zip(dates, prices):
        rows.append(
            {
                "code": code,
                "date": d,
                "open": p,
                "high": p * 1.01,
                "low": p * 0.99,
                "close": p,
                "pre_close": p,
                "adj_back_close": p,
                "adj_front_close": p,
                "vol": 1_000_000.0,
                "amount": 1.0e8,
                "source": "sample",
            }
        )
    return pd.DataFrame(rows)


def _make_repo(bars: pd.DataFrame, universe: pd.DataFrame) -> Repository:
    client = DuckDBClient(":memory:")
    init_schema(client)
    repo = Repository(client, client)
    repo.save_bars(bars)
    repo.save_universe(universe)
    return repo


def _clean_repo():
    dates = [AS_OF - dt.timedelta(days=i) for i in range(5, 0, -1)]  # 5 个交易日，均 <= AS_OF
    bars = pd.concat(
        [
            _bars("600519.SH", [100 + i for i in range(5)], dates),
            _bars("000725.SZ", [20 + i * 0.5 for i in range(5)], dates),
        ],
        ignore_index=True,
    )
    uni = pd.DataFrame(
        {
            "date": [AS_OF] * 2,
            "code": ["600519.SH", "000725.SZ"],
            "name": ["贵州茅台", "京东方Ａ"],
            "in_universe": [True, True],
            "is_st": [False, False],
            "listed_days": [3000, 3000],
            "delisted": [False, False],
        }
    )
    return _make_repo(bars, uni)


def test_clean_data_passes():
    repo = _clean_repo()
    violations = check_data_quality(repo, SETTINGS, AS_OF)
    assert violations == {}, f"干净数据不应有违规：{violations}"


def test_universe_st_detected():
    repo = _clean_repo()
    # 把一个可投资域标的改成 ST
    bad_uni = pd.DataFrame(
        {
            "date": [AS_OF],
            "code": ["600519.SH"],
            "name": ["ST 茅台"],
            "in_universe": [True],
            "is_st": [True],
            "listed_days": [3000],
            "delisted": [False],
        }
    )
    repo.save_universe(bad_uni)
    v = check_data_quality(repo, SETTINGS, AS_OF)
    assert "universe_exclusions" in v
    assert any(x["reason"] == "st_in_universe" for x in v["universe_exclusions"])


def test_universe_delisted_detected():
    repo = _clean_repo()
    bad_uni = pd.DataFrame(
        {
            "date": [AS_OF],
            "code": ["000725.SZ"],
            "name": ["京东方Ａ"],
            "in_universe": [True],
            "is_st": [False],
            "listed_days": [3000],
            "delisted": [True],
        }
    )
    repo.save_universe(bad_uni)
    v = check_data_quality(repo, SETTINGS, AS_OF)
    assert "universe_exclusions" in v
    assert any(x["reason"] == "delisted_in_universe" for x in v["universe_exclusions"])


def test_duplicate_dates_detected():
    # daily_bars 有主键，正常写入无法产生重复 (code,date)；这里复刻一张无主键表以验证检测逻辑
    repo = _clean_repo()
    repo.market.execute("DROP TABLE IF EXISTS daily_bars")
    repo.market.execute(
        "CREATE TABLE daily_bars ("
        "code VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, "
        "pre_close DOUBLE, adj_back_close DOUBLE, adj_front_close DOUBLE, vol DOUBLE, amount DOUBLE, source VARCHAR)"
    )
    d0 = AS_OF - dt.timedelta(days=3)
    for price in (100.0, 999.0):  # 同一 (code,date) 两行
        repo.market.execute(
            "INSERT INTO daily_bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ["600519.SH", d0, price, price, price, price, price, price, price, 1e6, 1e8, "s"],
        )
    v = check_data_quality(repo, SETTINGS, AS_OF)
    assert "duplicate_dates" in v


def test_nonpositive_price_detected():
    dates = [AS_OF - dt.timedelta(days=i) for i in range(3, 0, -1)]
    bars = _bars("600519.SH", [100, 101, 0.0], dates)  # 最后一天 close=0
    repo = _make_repo(bars, _clean_repo().load_universe(AS_OF))
    v = check_data_quality(repo, SETTINGS, AS_OF)
    assert "nonpositive_price" in v


def test_future_date_detected():
    dates = [AS_OF - dt.timedelta(days=2), AS_OF - dt.timedelta(days=1), AS_OF + dt.timedelta(days=1)]
    bars = _bars("600519.SH", [100, 101, 102], dates)  # 含未来日期
    repo = _make_repo(bars, _clean_repo().load_universe(AS_OF))
    v = check_data_quality(repo, SETTINGS, AS_OF)
    assert "future_dates" in v


def test_adjust_jump_detected():
    dates = [AS_OF - dt.timedelta(days=i) for i in range(4, 0, -1)]
    # 第 4 天相对第 3 天暴涨 50%（超默认 0.3 阈值）
    bars = _bars("600519.SH", [100, 101, 200, 201], dates)
    repo = _make_repo(bars, _clean_repo().load_universe(AS_OF))
    v = check_data_quality(repo, SETTINGS, AS_OF)
    assert "adjust_jump" in v
