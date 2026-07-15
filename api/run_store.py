"""运行历史持久化（JSONL 追加写，避免与 DuckDB 写者争锁）。

- 每次更新（手动/自动）在结束后追加一条记录：run_id / 触发源 / 起止时间 / 状态 /
  目标日 / 到达步骤 / 进度 / 耗时 / 错误。
- 监控层只读此文件，与 UpdateManager 的实时状态机互补：状态机给「现在跑到哪」，
  历史文件给「过去跑过哪些、成败与原因」。
"""
from __future__ import annotations

import json
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUN_HISTORY_PATH = os.path.join(ROOT, "data", "run_history.jsonl")
# P3-1：批处理（orchestrator.run_daily）逐步状态，与 run_history 分开存储，便于按 run_id 取逐步明细
STEP_HISTORY_PATH = os.path.join(ROOT, "data", "run_steps.jsonl")
_lock = threading.Lock()


def append_run(rec: dict) -> None:
    with _lock:
        os.makedirs(os.path.dirname(RUN_HISTORY_PATH), exist_ok=True)
        with open(RUN_HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def append_step(rec: dict) -> None:
    """追加一条逐步状态记录（P3-1 批处理落盘）。"""
    with _lock:
        os.makedirs(os.path.dirname(STEP_HISTORY_PATH), exist_ok=True)
        with open(STEP_HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def load_runs(limit: int = 50) -> list:
    if not os.path.exists(RUN_HISTORY_PATH):
        return []
    with _lock:
        with open(RUN_HISTORY_PATH, "r", encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
    recs = []
    for ln in lines:
        try:
            recs.append(json.loads(ln))
        except Exception:
            pass
    recs.reverse()  # 最新在前
    return recs[:limit]


def load_steps(run_id: str, limit: int = 200) -> list:
    """读取某次运行的逐步状态（最新在前）。"""
    if not os.path.exists(STEP_HISTORY_PATH):
        return []
    with _lock:
        with open(STEP_HISTORY_PATH, "r", encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
    out = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if r.get("run_id") == run_id:
            out.append(r)
    out.reverse()
    return out[:limit]
