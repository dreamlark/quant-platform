"""FastAPI 响应模型（Pydantic v2）。"""
from __future__ import annotations

import datetime as _dt
from typing import Annotated, List, Optional

from pydantic import BaseModel, BeforeValidator

# 仓库读出的 date 列通常为 datetime.date 对象，统一在序列化前转为 ISO 字符串，
# 避免 Pydantic 对 str 字段的严格校验报错（一处修复，所有响应模型受益）。
def _coerce_date(v):
    if v is None:
        return None
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()[:10]
    return str(v)


DateStr = Annotated[str, BeforeValidator(_coerce_date)]


class SignalOut(BaseModel):
    date: DateStr
    code: str
    direction: int
    confidence: float
    source_tags: str
    factor_contrib: float
    tech_contrib: float
    sentiment_contrib: float
    predict_contrib: float


class SignalDetailOut(BaseModel):
    date: DateStr
    code: str
    direction: int
    confidence: float
    source_tags: str
    factor_contrib: float
    tech_contrib: float
    sentiment_contrib: float
    predict_contrib: float
    factor_detail: List[dict] = []
    predict_detail: List[dict] = []


class FactorHealthOut(BaseModel):
    factor_name: str
    date: DateStr
    ic: float
    icir: float
    rank_return: float
    turnover: float
    status: str
    weight: float


class SectorOut(BaseModel):
    date: DateStr
    sector_code: str
    sector_name: str
    change_pct: float
    rs: float
    net_inflow: float
    rotation_signal: str


class BriefOut(BaseModel):
    date: DateStr
    content: str
    market_temperature: int
    disclaimer: str


class ReviewOut(BaseModel):
    date: DateStr
    code: str
    action: str
    reason: str
    confidence: float
    content: str


class WatchIn(BaseModel):
    code: str
    name: str = ""
    cost_price: float
    shares: float


class WatchOut(BaseModel):
    code: str
    name: str
    cost_price: float
    shares: float
    current_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    direction: Optional[int] = None
    confidence: Optional[float] = None


class BacktestOut(BaseModel):
    date: Optional[str]
    strategy: str
    metric_name: str
    metric_value: float
    benchmark: str
    sharpe: float
    deflated_sharpe: float


class DashboardSummary(BaseModel):
    date: DateStr
    market_temperature: int
    brief: Optional[str] = None
    top_signals: List[SignalOut] = []
    sectors: List[SectorOut] = []
    watchlist_alerts: List[WatchOut] = []
