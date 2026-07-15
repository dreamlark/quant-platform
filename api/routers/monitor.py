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

from api.routers.admin import mgr  # noqa: E402  # 实时管线状态
from api.run_store import load_runs, load_steps  # noqa: E402

router = APIRouter(prefix="/api/monitor", tags=["monitor"])

# 过期阈值（天）：>4 天可视作错过了一个以上交易日（覆盖周末）
STALE_DAYS = 4


def _data_status() -> dict:
    try:
        from api.database import get_repository

        con = get_repository().market
        row = con.execute("SELECT max(date), count(distinct code) FROM daily_bars").fetchone()
        latest, n_codes = row[0], row[1]
        u = con.execute(
            "SELECT count(*) FROM universe WHERE in_universe=TRUE AND date=(SELECT max(date) FROM universe)"
        ).fetchone()[0]
        days_since = (dt.date.today() - latest).days if latest else None
        is_stale = bool(days_since is not None and days_since > STALE_DAYS)
        return {
            "latest_date": str(latest) if latest else None,
            "days_since": days_since,
            "is_stale": is_stale,
            "stock_count": n_codes,
            "universe_count": u,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _factor_health() -> dict:
    try:
        from api.database import get_repository

        con = get_repository().analytics
        d = con.execute("SELECT max(date) FROM factor_health").fetchone()[0]
        if not d:
            return {"latest_date": None, "total": 0, "by_status": {}, "avg_icir": None}
        rows = con.execute(
            "SELECT status, count(*) FROM factor_health WHERE date=? GROUP BY status", [d]
        ).fetchall()
        avg = con.execute("SELECT avg(icir) FROM factor_health WHERE date=?", [d]).fetchone()[0]
        by_status = {s: c for s, c in rows}
        return {
            "latest_date": str(d),
            "total": sum(by_status.values()),
            "by_status": by_status,
            "avg_icir": round(avg, 4) if avg is not None else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _model_status() -> list:
    try:
        from api.database import get_repository

        con = get_repository().analytics
        ph = con.execute(
            "SELECT model_name, max(date) FROM predict_health GROUP BY model_name"
        ).fetchall()
        out = []
        for name, d in ph:
            acc, mape = con.execute(
                "SELECT dir_acc, mape FROM predict_health WHERE model_name=? AND date=?",
                [name, d],
            ).fetchone()
            cov = con.execute(
                "SELECT count(distinct code) FROM predict_values WHERE model_name=? AND date=?",
                [name, d],
            ).fetchone()[0]
            out.append(
                {
                    "model_name": name,
                    "date": str(d),
                    "dir_acc": round(acc, 4) if acc is not None else None,
                    "mape": round(mape, 4) if mape is not None else None,
                    "coverage_count": cov,
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"{type(exc).__name__}: {exc}"}]


def _other_freshness() -> dict:
    try:
        from api.database import get_repository

        con = get_repository().analytics
        sig = con.execute("SELECT max(date) FROM signals").fetchone()[0]
        sec = con.execute("SELECT max(date) FROM sector_rotation").fetchone()[0]
        brf = con.execute("SELECT max(date) FROM daily_brief").fetchone()[0]
        return {
            "signals_date": str(sig) if sig else None,
            "sector_date": str(sec) if sec else None,
            "brief_date": str(brf) if brf else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _market_sentiment() -> dict:
    """市场级综合情绪指数（sentiment_index 最新一行）。

    复用 repo 既有 analytics 连接读取，避免与仓储读写连接冲突
    （DuckDB 单文件单写者限制：同进程内不可同时存在 read_only 与 read_write 连接）。
    """
    try:
        from api.database import get_repository

        con = get_repository().analytics
        d = con.execute("SELECT max(date) FROM sentiment_index").fetchone()[0]
        if not d:
            return {"latest_date": None, "available": False}
        cur = con.execute("SELECT * FROM sentiment_index WHERE date=?", [d])
        row = cur.fetchone()
        cols = [c[0] for c in cur.description] if cur.description else []
        rec = dict(zip(cols, row)) if row else {}
        rec["latest_date"] = str(d)
        rec["available"] = True
        return rec
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


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
