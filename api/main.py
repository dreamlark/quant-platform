"""FastAPI 应用入口（零认证、易部署）。

所有 /api/* 路由读取 DuckDB 分析库，供 Web 前端（暗色 ECharts）五页看板消费。
"""
from __future__ import annotations

import os
import sys

# 加载 .env 环境变量（python-dotenv 声明为必装依赖，但需显式调用方能生效）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 保证仓库根在 sys.path（绝对导入 storage/api 等）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware import (
    SanitizedJSONResponse,
    register_exception_handlers,
)
from api.routers import admin, dashboard, factors, hotspot, monitor, sectors, settings, stocks, watchlist

app = FastAPI(
    title="A 股日频量化分析平台 API",
    description="analysis-first（只分析不交易）· 因子/技术/情绪/预测四源融合信号",
    version="0.1.0",
    # P2-1 边界治理核心机制：所有端点（含 response_model 路径）在序列化前统一消毒
    # inf/nan/numpy 特殊值 → 合法 JSON，杜绝 500。
    default_response_class=SanitizedJSONResponse,
)

# 零认证、本地部署，允许前端跨域（无凭据，不设 allow_credentials）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# P2-1 边界治理：默认响应类（SanitizedJSONResponse）已在序列化边界统一消毒 inf/nan；
# 统一异常处理：未捕获异常 → 干净 JSON，避免 500 裸奔。
register_exception_handlers(app)

app.include_router(dashboard.router)
app.include_router(factors.router)
app.include_router(sectors.router)
app.include_router(stocks.router)
app.include_router(watchlist.router)
app.include_router(admin.router)
app.include_router(monitor.router)
app.include_router(hotspot.router)
app.include_router(settings.router)


@app.get("/")
def root():
    return {
        "service": "A 股日频量化分析平台 API",
        "version": "0.1.0",
        "docs": "/docs",
        "disclaimer": "本平台内容仅为量化分析信号与研究观点，不构成任何证券买卖建议。",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
