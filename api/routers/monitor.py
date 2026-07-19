"""运维监控（只读观测层）。

聚合四类可观测信号，供「运维监控」页一次性拉取：
- 数据状态：行情库最新交易日、距今天数、是否过期、股票/可投资域覆盖
- 健康度：因子体检（有效/衰减/失效分布 + 平均 ICIR）、各预测模型（含 Kronos）dir_acc 与覆盖率
- 管线运行：UpdateManager 实时状态机（当前跑到哪一步、进度）
- 运行记录：持久化历史（JSONL），含成败/耗时/失败步骤/错误

全部为只读查询，与更新写者解耦；任一库不可达时该分块降级为 error 字段，不影响其他分块。
"""
from __future__ import annotations

import datetime as dt
import os
import sys

from fastapi import APIRouter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from api.database import get_repository  # noqa: E402
from api.routers.admin import mgr  # noqa: E402  # 实时管线状态
from api.run_store import load_runs, load_steps  # noqa: E402

router = APIRouter(prefix="/api/monitor", tags=["monitor"])

# 过期阈值（天）：>4 天可视作错过了一个以上交易日（覆盖周末）
STALE_DAYS = 4


def _data_status() -> dict:
    # 统一走仓储层（P2-1 边界治理），不再直连 DuckDB 拼 SQL
    return get_repository().data_freshness(stale_days=STALE_DAYS)


def _factor_health() -> dict:
    return get_repository().factor_health_summary()


def _model_status() -> list:
    return get_repository().model_status_summary()


def _other_freshness() -> dict:
    return get_repository().other_freshness()


def _market_sentiment() -> dict:
    """市场级综合情绪指数（sentiment_index 最新一行），统一走仓储层。"""
    return get_repository().latest_market_sentiment()


@router.get("/overview")
def overview():
    """运维总览：数据状态 + 健康度 + 模型状态 + 实时管线 + 最近一次运行。"""
    runs = load_runs(1)
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "data": _data_status(),
        "factors": _factor_health(),
        "models": _model_status(),
        "freshness": _other_freshness(),
        "market_sentiment": _market_sentiment(),
        "pipeline": mgr.state,
        "last_run": runs[0] if runs else None,
        "batch_run": _batch_run(),
        "auto": {"enabled": mgr.state["auto_enabled"], "next_run": mgr.state["next_run"]},
        "history_count": len(load_runs(1000)),
    }


@router.get("/batch-run")
def batch_run():
    """批处理（orchestrator.run_daily）最近一次运行 + 逐步状态（P3-1 落盘）。"""
    return _batch_run()


@router.get("/history")
def history(limit: int = 50):
    """运行历史记录（最新在前）。"""
    return {"runs": load_runs(limit)}


def _batch_run() -> dict:
    """从运行历史取最近一次批处理运行及其逐步明细（P3-1）。"""
    try:
        for r in load_runs(1000):
            if r.get("kind") == "batch":
                run_id = r.get("run_id")
                steps = load_steps(run_id) if run_id else []
                return {"run": r, "steps": steps}
        return {"run": None, "steps": []}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
