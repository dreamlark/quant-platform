"""自选股路由（记账持仓盈亏 + 逐只简评，F-09 / T11）。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.database import get_repository
from api.schemas import ReviewOut, WatchIn, WatchOut
from api.utils import resolve_date
from storage.repository import Repository

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchOut])
def list_watchlist():
    repo = get_repository()
    w = repo.list_watch()
    if w.empty:
        return []
    codes = w["code"].tolist()
    bars = repo.load_bars(codes=codes)
    latest = bars.sort_values("date").groupby("code").tail(1) if not bars.empty else bars
    sig = repo.load_signals(resolve_date(repo, None, "signal"))
    out = []
    for _, r in w.iterrows():
        code = r["code"]
        cur = latest[latest["code"] == code]["close"]
        price = float(cur.iloc[0]) if not cur.empty else None
        srow = sig[sig["code"] == code]
        out.append(
            WatchOut(
                code=code,
                name=str(r["name"]),
                cost_price=float(r["cost_price"]),
                shares=float(r["shares"]),
                current_price=price,
                pnl_pct=round((price - float(r["cost_price"])) / float(r["cost_price"]) * 100, 2)
                if price
                else None,
                direction=int(srow.iloc[0]["direction"]) if not srow.empty else None,
                confidence=float(srow.iloc[0]["confidence"]) if not srow.empty else None,
            )
        )
    return out


@router.post("", response_model=WatchOut)
def add_watch(item: WatchIn):
    repo = get_repository()
    repo.upsert_watch(item.code, item.name or item.code, item.cost_price, item.shares)
    return WatchOut(
        code=item.code,
        name=item.name or item.code,
        cost_price=item.cost_price,
        shares=item.shares,
    )


@router.delete("/{code}")
def delete_watch(code: str):
    repo = get_repository()
    repo.delete_watch(code)
    return {"code": code, "deleted": True}


@router.get("/{code}/review", response_model=ReviewOut)
def watch_review(code: str, date: Optional[str] = Query(None)):
    repo = get_repository()
    try:
        target = resolve_date(repo, date, "signal")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    rv = repo.load_review(target, code)
    if rv.empty:
        raise HTTPException(status_code=404, detail="该标的当日无逐只简评")
    r = rv.iloc[0]
    return ReviewOut(
        date=str(r["date"]),
        code=str(r["code"]),
        action=str(r["action"]),
        reason=str(r["reason"]),
        confidence=float(r["confidence"]),
        content=str(r["content"]),
    )
