"""Dashboard 路由：每日简报聚合（首页落地数据）。"""
from __future__ import annotations

import math
import os
from typing import Optional

import numpy as np
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, Query

from api.database import get_repository, get_settings
from api.schemas import (
    BriefOut,
    DashboardSummary,
    MarketSentimentView,
    SectorOut,
    SignalOut,
    WatchOut,
)
from api.utils import resolve_date
from storage.repository import Repository

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


from api.serializers import sanitize_df as _sanitize_df
from api.serializers import sanitize_val as _sanitize_val

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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

    # 清洗 inf/nan（pydantic v2 的 json 序列化拒绝非有限浮点，否则 500）
    signals = _sanitize_df(signals)
    sectors = _sanitize_df(sectors)

    top = signals.sort_values("confidence", ascending=False).head(10) if not signals.empty else signals
    watch_codes = repo.load_watch_codes()
    alerts = _watchlist_alerts(repo, target, watch_codes)

    # 查询行情库最新交易日（可能与信号/简报日期不一致：ingest 可能已拉新数据但后续步骤未完成）
    try:
        market_row = repo.market.execute("SELECT max(date) as mdate FROM daily_bars").fetchone()
        market_latest = str(market_row[0]) if market_row and market_row[0] else None
    except Exception:
        market_latest = None

    summary = DashboardSummary(
        date=str(target),
        market_latest_date=market_latest,
        market_temperature=int(brief["market_temperature"].iloc[0]) if not brief.empty else 50,
        brief=brief["content"].iloc[0] if not brief.empty else None,
        top_signals=[SignalOut(**r) for _, r in top.iterrows()],
        sectors=[SectorOut(**r) for _, r in sectors.iterrows()] if not sectors.empty else [],
        watchlist_alerts=alerts,
        market_sentiment=_market_sentiment(repo),
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


def _market_sentiment(repo: Repository) -> MarketSentimentView:
    """市场级综合情绪指数（sentiment_index 最新一行），供 Dashboard 情绪卡。

    复用 repo 既有 analytics 连接读取，避免与仓储读写连接冲突
    （DuckDB 单文件单写者限制：同进程内不可同时存在 read_only 与 read_write 连接）。
    """
    try:
        df = repo.load_sentiment_index(latest=True)
        if df is None or df.empty:
            return MarketSentimentView(available=False)
        row = df.iloc[0].to_dict()
        row["latest_date"] = str(row.get("date"))
        row["available"] = True
        clean = {k: _sanitize_val(v) for k, v in row.items() if k in MarketSentimentView.model_fields}
        # 计算当前 regime_state 对应的置信度缩放系数（Monitor/前端展示）
        ra = get_settings().get("fusion", {}).get("regime_adjust", {})
        state = clean.get("regime_state")
        scale = 1.0
        if ra.get("enabled", False) and state:
            sm = ra.get("scale")
            if isinstance(sm, dict) and state in sm:
                scale = float(sm[state])
            elif not isinstance(sm, dict):
                legacy = {
                    "恐惧": ra.get("fear_scale", 0.75),
                    "中性": ra.get("neutral_scale", 1.0),
                    "贪婪": ra.get("greed_scale", 0.75),
                }
                scale = float(legacy.get(state, 1.0))
        clean["regime_scale"] = scale
        return MarketSentimentView(**clean)
    except Exception as exc:  # noqa: BLE001
        return MarketSentimentView(available=False, error=f"{type(exc).__name__}: {exc}")


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
