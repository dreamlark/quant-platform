"""热点语义分析 API 路由。

提供：
- GET /api/hotspot/latest     — 最近热点信号列表
- GET /api/hotspot/by-code    — 按标的查询关联热点
- GET /api/hotspot/by-sector  — 按板块查询关联热点
- GET /api/hotspot/digest     — 今日热点语义摘要
- GET /api/hotspot/stream     — SSE 实时热点推送
- POST /api/hotspot/collect   — 手动触发采集（管理用）
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from api.database import get_repository as get_repo

router = APIRouter(prefix="/api/hotspot", tags=["hotspot"])


@router.get("/latest")
async def get_latest(
    limit: int = Query(50, ge=1, le=500),
    date: Optional[str] = Query(None, description="指定日期 YYYY-MM-DD"),
):
    """获取最近热点信号列表。"""
    repo = get_repo()
    target_date = None
    if date:
        try:
            target_date = dt.date.fromisoformat(date)
        except ValueError:
            pass
    df = repo.load_hotspot_signals(date=target_date, limit=limit)
    if df.empty:
        return {"items": [], "total": 0}
    # 按时间倒序
    df = df.sort_values("ts", ascending=False)
    items = df.to_dict("records")
    # 序列化处理
    for item in items:
        for k, v in item.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            elif not isinstance(v, (str, int, float, bool, type(None))):
                item[k] = str(v)
    return {"items": items, "total": len(items)}


@router.get("/by-code/{code}")
async def get_by_code(
    code: str,
    days: int = Query(7, ge=1, le=90),
):
    """按标的查询关联热点。"""
    repo = get_repo()
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    df = repo.load_hotspot_signals(date=None, code=code, limit=500)
    if df.empty:
        return {"items": [], "total": 0}
    # 过滤日期范围
    if "ts" in df.columns:
        df["ts_date"] = df["ts"].dt.date
        df = df[(df["ts_date"] >= start) & (df["ts_date"] <= end)]
        df = df.drop(columns=["ts_date"])
    df = df.sort_values("ts", ascending=False)
    items = df.to_dict("records")
    for item in items:
        for k, v in item.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            elif not isinstance(v, (str, int, float, bool, type(None))):
                item[k] = str(v)
    return {"items": items, "total": len(items)}


@router.get("/by-sector/{sector}")
async def get_by_sector(
    sector: str,
    days: int = Query(7, ge=1, le=90),
):
    """按板块查询关联热点。"""
    repo = get_repo()
    df = repo.load_hotspot_signals(sector=sector, limit=500)
    if df.empty:
        return {"items": [], "total": 0}
    # 过滤日期范围
    if "ts" in df.columns:
        cutoff = dt.date.today() - dt.timedelta(days=days)
        df["ts_date"] = df["ts"].dt.date
        df = df[df["ts_date"] >= cutoff]
        df = df.drop(columns=["ts_date"])
    df = df.sort_values("ts", ascending=False)
    items = df.to_dict("records")
    for item in items:
        for k, v in item.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            elif not isinstance(v, (str, int, float, bool, type(None))):
                item[k] = str(v)
    return {"items": items, "total": len(items)}


@router.get("/digest")
async def get_digest(
    date: Optional[str] = Query(None, description="指定日期 YYYY-MM-DD"),
):
    """获取热点语义摘要。"""
    repo = get_repo()
    target_date = None
    if date:
        try:
            target_date = dt.date.fromisoformat(date)
        except ValueError:
            pass
    df = repo.load_hotspot_digest(date=target_date)
    if df.empty:
        return {"content": "", "date": date or dt.date.today().isoformat()}
    row = df.iloc[0].to_dict()
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            row[k] = v.isoformat()
    return row


@router.get("/stream")
async def hotspot_stream(request: Request):
    """SSE 实时热点推送。

    客户端通过 EventSource 连接，每隔 30s 发送心跳，
    有新热点时推送 JSON 数据。

    使用方式（前端）:
        const es = new EventSource('/api/hotspot/stream');
        es.onmessage = (e) => { console.log(JSON.parse(e.data)); };
    """
    repo = get_repo()

    async def event_generator():
        last_ts: Optional[dt.datetime] = None
        while True:
            # 检查客户端是否断开
            if await request.is_disconnected():
                logger.debug("SSE 热点推送：客户端已断开")
                break

            # 查询最新热点
            try:
                df = repo.load_hotspot_signals(limit=10)
                if not df.empty:
                    df = df.sort_values("ts", ascending=False)
                    latest = df.iloc[0]
                    latest_ts = latest["ts"]
                    if last_ts is None or latest_ts > last_ts:
                        last_ts = latest_ts
                        # 推送最新热点
                        item = latest.to_dict()
                        for k, v in item.items():
                            if hasattr(v, "isoformat"):
                                item[k] = v.isoformat()
                            elif not isinstance(v, (str, int, float, bool, type(None))):
                                item[k] = str(v)
                        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            except Exception as exc:
                logger.debug(f"SSE 热点推送查询失败：{exc}")

            # 心跳
            yield f": heartbeat {dt.datetime.now().isoformat()}\n\n"
            await asyncio.sleep(30)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stats")
async def get_stats(
    days: int = Query(7, ge=1, le=90),
):
    """获取热点统计（按日聚合）。"""
    repo = get_repo()
    end = dt.date.today()
    start = end - dt.timedelta(days=days)

    df = repo.load_hotspot_signals(limit=10000)
    if df.empty:
        return {"daily_stats": [], "total": 0}

    # 按日聚合
    df["ts_date"] = df["ts"].dt.date
    df = df[(df["ts_date"] >= start) & (df["ts_date"] <= end)]

    daily_stats = (
        df.groupby("ts_date")
        .agg(
            total=("title", "count"),
            positive=("sentiment", lambda x: (x == "利好").sum()),
            negative=("sentiment", lambda x: (x == "利空").sum()),
            neutral=("sentiment", lambda x: (x == "中性").sum()),
            high_impact=("impact", lambda x: (x == "高").sum()),
            avg_score=("composite_score", "mean"),
        )
        .reset_index()
        .to_dict("records")
    )

    for row in daily_stats:
        if hasattr(row.get("ts_date"), "isoformat"):
            row["ts_date"] = row["ts_date"].isoformat()
        if "avg_score" in row and row["avg_score"] is not None:
            row["avg_score"] = round(float(row["avg_score"]), 4)

    return {
        "daily_stats": daily_stats,
        "total": len(df),
    }
