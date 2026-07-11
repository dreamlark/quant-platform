"""股票页路由：信号拆解下钻（F-11）+ K 线（前复权仅展示）+ 搜索。

注意：``/search`` 必须声明在 ``/{code}`` 之前，否则 ``/search`` 会被
``/{code}`` 路由捕获（code="search"）而 404。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.database import get_repository
from api.schemas import SignalDetailOut
from api.utils import resolve_date
from storage.repository import Repository

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/search")
def stock_search(q: str = Query("", min_length=1)):
    """按代码/名称搜索（来自 universe 表）。"""
    repo = get_repository()
    like = f"%{q.upper()}%"
    # universe 表落在行情库（_MARKET_TABLES），须用 market 连接查询
    df = repo.market.read(
        "SELECT code, name FROM universe WHERE code LIKE ? OR UPPER(name) LIKE ? "
        "GROUP BY code, name ORDER BY code LIMIT 20",
        [like, like],
    )
    return df.to_dict("records")


@router.get("/{code}", response_model=SignalDetailOut)
def stock_detail(code: str, date: Optional[str] = Query(None)):
    repo = get_repository()
    try:
        target = resolve_date(repo, date, "signal")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    detail = repo.load_signal_detail(target, code)
    if detail is None:
        raise HTTPException(status_code=404, detail="该标的当日无信号")
    return SignalDetailOut(**detail)


@router.get("/{code}/bars")
def stock_bars(code: str, limit: int = Query(120, ge=10, le=500)):
    """近期日 K（仅返回前复权 adj_front_close 用于展示，严禁回传计算价）。"""
    repo = get_repository()
    bars = repo.load_bars(codes=[code])
    if bars.empty:
        return []
    bars = bars.sort_values("date").tail(limit)
    return bars[
        ["date", "open", "high", "low", "close", "adj_front_close", "vol", "amount"]
    ].to_dict("records")
