"""板块页路由：板块轮动/强弱排名。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.database import get_repository
from api.schemas import SectorOut
from api.utils import resolve_date
from storage.repository import Repository

router = APIRouter(prefix="/api/sectors", tags=["sectors"])


@router.get("/rotation", response_model=list[SectorOut])
def sector_rotation(date: Optional[str] = Query(None)):
    repo = get_repository()
    try:
        target = resolve_date(repo, date, "signal")
    except ValueError:
        # 首次/无数据：返回空列表（HTTP 200），避免 404 导致板块轮动页白屏
        return []
    s = repo.load_sector(target)
    if s.empty:
        return []
    return [SectorOut(**r) for _, r in s.iterrows()]
