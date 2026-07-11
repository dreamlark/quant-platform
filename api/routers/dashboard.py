"""Dashboard 路由：每日简报聚合（首页落地数据）。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.database import get_repository, get_settings
from api.schemas import BriefOut, DashboardSummary, SectorOut, SignalOut, WatchOut
from api.utils import resolve_date
from storage.repository import Repository

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def dashboard(date: Optional[str] = Query(None)):
    repo = get_repository()
    try:
        target = resolve_date(repo, date, "signal")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    signals = repo.load_signals(target)
    sectors = repo.load_sector(target)
    brief = repo.load_brief(target)

    top = signals.sort_values("confidence", ascending=False).head(10) if not signals.empty else signals
    watch_codes = repo.load_watch_codes()
    alerts = _watchlist_alerts(repo, target, watch_codes)

    summary = DashboardSummary(
        date=str(target),
        market_temperature=int(brief["market_temperature"].iloc[0]) if not brief.empty else 50,
        brief=brief["content"].iloc[0] if not brief.empty else None,
        top_signals=[SignalOut(**r) for _, r in top.iterrows()],
        sectors=[SectorOut(**r) for _, r in sectors.iterrows()] if not sectors.empty else [],
        watchlist_alerts=alerts,
    )
    return summary


@router.get("/brief", response_model=BriefOut)
def brief(date: Optional[str] = Query(None)):
    repo = get_repository()
    try:
        target = resolve_date(repo, date, "signal")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    b = repo.load_brief(target)
    if b.empty:
        raise HTTPException(status_code=404, detail="简报未生成")
    r = b.iloc[0]
    return BriefOut(
        date=str(r["date"]),
        content=r["content"],
        market_temperature=int(r["market_temperature"]),
        disclaimer=r["disclaimer"],
    )


def _watchlist_alerts(repo: Repository, target, watch_codes) -> list[WatchOut]:
    out = []
    if not watch_codes:
        return out
    bars = repo.load_bars(codes=watch_codes, start=target, end=target)
    sig = repo.load_signals(target)
    for code in watch_codes:
        w = repo.list_watch()
        row = w[w["code"] == code]
        if row.empty:
            continue
        r = row.iloc[0]
        cur = bars[bars["code"] == code]["close"]
        price = float(cur.iloc[0]) if not cur.empty else None
        srow = sig[sig["code"] == code]
        direction = int(srow.iloc[0]["direction"]) if not srow.empty else None
        conf = float(srow.iloc[0]["confidence"]) if not srow.empty else None
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
                direction=direction,
                confidence=conf,
            )
        )
    return out
