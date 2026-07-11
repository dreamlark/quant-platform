"""FastAPI 应用入口（零认证、易部署）。

所有 /api/* 路由读取 DuckDB 分析库，供 Web 前端（暗色 ECharts）五页看板消费。
"""
from __future__ import annotations

import os
import sys

# 保证仓库根在 sys.path（绝对导入 storage/api 等）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import dashboard, factors, sectors, stocks, watchlist

app = FastAPI(
    title="A 股日频量化分析平台 API",
    description="analysis-first（只分析不交易）· 因子/技术/情绪/预测四源融合信号",
    version="0.1.0",
)

# 零认证、本地部署，允许前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(factors.router)
app.include_router(sectors.router)
app.include_router(stocks.router)
app.include_router(watchlist.router)


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
