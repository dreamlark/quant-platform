"""FastAPI 响应模型（Pydantic v2）。"""
from __future__ import annotations

import datetime as _dt
from typing import Annotated, List, Optional

from pydantic import BaseModel, BeforeValidator, Field

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
    cost_price: float = Field(gt=0, description="成本价，必须大于 0")
    shares: float = Field(ge=0, description="持仓数量，不可为负")


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


class MarketSentimentView(BaseModel):
    """市场综合情绪指数视图（Monitor / Dashboard 双卡共用）。"""
    available: bool = False
    latest_date: Optional[str] = None
    index_value: Optional[float] = None
    sub_volume: Optional[float] = None
    sub_price: Optional[float] = None
    sub_money: Optional[float] = None
    sub_valuation: Optional[float] = None
    sub_riskpremium: Optional[float] = None
    gsisi: Optional[float] = None
    regime: Optional[str] = None  # 恐惧 / 中性 / 贪婪（温度计情绪态）
    regime_state: Optional[str] = None  # bull / neutral / bear / panic（缩放用）
    regime_scale: Optional[float] = None  # 当前 regime_state 对应的置信度缩放系数
    thermometer: Optional[float] = None
    signal: Optional[str] = None  # 买入 / 半仓 / 空仓
    error: Optional[str] = None


class DashboardSummary(BaseModel):
    date: DateStr
    market_temperature: int
    brief: Optional[str] = None
    top_signals: List[SignalOut] = []
    sectors: List[SectorOut] = []
    watchlist_alerts: List[WatchOut] = []
    market_sentiment: Optional[MarketSentimentView] = None  # 市场情绪指数卡（PRD §8 双卡）
