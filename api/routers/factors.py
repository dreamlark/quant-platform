"""因子页路由：因子健康度 + 单因子明细。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.database import get_repository
from api.schemas import FactorHealthOut
from api.utils import resolve_date
from storage.repository import Repository

router = APIRouter(prefix="/api/factors", tags=["factors"])


@router.get("/health", response_model=list[FactorHealthOut])
def factor_health(date: Optional[str] = Query(None)):
    repo = get_repository()
    try:
        target = resolve_date(repo, date, "signal")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    h = repo.load_health(date=target)
    if h.empty:
        return []
    return [FactorHealthOut(**r) for _, r in h.iterrows()]


@router.get("/list")
def factor_list():
    """可用因子清单（来自 config/factors.yaml）。"""
    from factors.factor_calc import load_factor_config

    return load_factor_config()


@router.get("/values")
def factor_values(date: Optional[str] = Query(None), code: Optional[str] = Query(None)):
    """单日/单标的因子值（用于因子详情下钻）。"""
    repo = get_repository()
    try:
        target = resolve_date(repo, date, "signal")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    codes = [code] if code else None
    fv = repo.load_factor_long(date=target, codes=codes)
    if fv.empty:
        return []
    return fv.to_dict("records")
