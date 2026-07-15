"""P3-1 调度落盘单测：RunState 逐步计时 + 整轮运行记录落盘（JSONL，无 DuckDB 争锁）。

用临时 JSONL 路径隔离，验证：
- 每步成功/失败均写逐步记录（status/duration_s/error）。- 整轮结束写一条 kind=batch 的运行记录（含 steps 摘要）。
- 步骤异常向上传播（不吞异常）。
- load_steps 按 run_id 取逐步明细（最新在前）。
"""
from __future__ import annotations

import datetime as dt
import os

from api.run_store import append_step, load_runs, load_steps
from scheduler.run_state import RunState


def _patch_paths(tmp_path, monkeypatch):
    hist = str(tmp_path / "run_history.jsonl")
    steps = str(tmp_path / "run_steps.jsonl")
    monkeypatch.setattr("api.run_store.RUN_HISTORY_PATH", hist)
    monkeypatch.setattr("api.run_store.STEP_HISTORY_PATH", steps)
    return hist, steps


def test_run_state_logs_steps_and_run(monkeypatch, tmp_path):
    _patch_paths(tmp_path, monkeypatch)
    d = dt.date(2024, 6, 14)

    def ok_step(x):
        return x * 2

    def boom():
        raise ValueError("step failed")

    # 失败的步骤：异常应向上传播
    try:
        with RunState(d, trigger="manual") as rs:
            assert rs.step("prepare", ok_step, 21) == 42
            rs.step("broken", boom)
    except ValueError:
        pass
    else:
        raise AssertionError("步骤异常未被传播")

    # 运行记录：kind=batch，含 steps 摘要，状态 fail
    runs = load_runs(10)
    batch = [r for r in runs if r.get("kind") == "batch"]
    assert len(batch) == 1
    rec = batch[0]
    assert rec["status"] == "fail"
    assert rec["error"] == "step failed"
    step_names = [s["step"] for s in rec["steps"]]
    assert "prepare" in step_names and "broken" in step_names
    prepared = next(s for s in rec["steps"] if s["step"] == "prepare")
    assert prepared["status"] == "ok"
    broken = next(s for s in rec["steps"] if s["step"] == "broken")
    assert broken["status"] == "fail"


def test_run_state_success_record(monkeypatch, tmp_path):
    _patch_paths(tmp_path, monkeypatch)
    d = dt.date(2024, 6, 14)
    with RunState(d, trigger="batch") as rs:
        rs.step("a", lambda: 1)
        rs.step("b", lambda: 2)
    runs = load_runs(10)
    rec = next(r for r in runs if r.get("kind") == "batch")
    assert rec["status"] == "ok"
    assert rec["error"] is None
    assert [s["step"] for s in rec["steps"]] == ["a", "b"]


def test_load_steps_by_run_id(monkeypatch, tmp_path):
    _patch_paths(tmp_path, monkeypatch)
    d = dt.date(2024, 6, 14)
    with RunState(d, trigger="manual") as rs:
        rs.step("s1", lambda: None)
        rs.step("s2", lambda: None)
    rid = load_runs(1)[0]["run_id"]
    steps = load_steps(rid)
    assert [s["step"] for s in steps] == ["s2", "s1"]  # 最新在前
    assert all(s["run_id"] == rid for s in steps)
    # 不存在的 run_id → 空
    assert load_steps("nope") == []


def test_append_step_direct(monkeypatch, tmp_path):
    hist, steps = _patch_paths(tmp_path, monkeypatch)
    append_step({"run_id": "r1", "step": "x", "status": "ok", "duration_s": 0.1})
    assert os.path.exists(steps)
    assert load_steps("r1")[0]["step"] == "x"
