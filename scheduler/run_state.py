"""批处理运行落盘（P3-1）：orchestrator.run_daily 的每次运行 + 每步状态持久化。

复用 ``api.run_store`` 的 JSONL 机制（避免与 DuckDB 写者争锁）：
- 每步开始/结束写一条逐步记录到 ``run_steps.jsonl``（含 status / duration_s / error）。
- 整轮结束写一条运行记录到 ``run_history.jsonl``（含 steps 摘要），Monitor 直接可见。

用法::

    with RunState(target_date, trigger="manual") as rs:
        rs.step("ingest", self.step_ingest, start, target_date)
        signals = rs.step("fusion", self.step_fusion, target_date)
    # __exit__ 自动落盘运行记录（status=ok/fail，异常回传）
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any, Callable, Optional

from api.run_store import append_run, append_step


class RunState:
    """编排运行上下文：逐步计时落盘 + 整轮运行记录。"""

    def __init__(self, date: dt.date, trigger: str = "manual") -> None:
        self.date = date
        self.trigger = trigger
        self.run_id = f"batch_{date.isoformat()}_{int(time.time() * 1000)}"
        self.start_ts = dt.datetime.now()
        self.steps: list[dict] = []

    def __enter__(self) -> "RunState":
        return self

    def step(self, name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """执行一步并落盘其状态；失败时记录后原样抛出。"""
        t0 = time.time()
        status = "ok"
        err: Optional[str] = None
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            status = "fail"
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            dur = round(time.time() - t0, 3)
            rec = {
                "run_id": self.run_id,
                "step": name,
                "status": status,
                "ts": dt.datetime.now().isoformat(timespec="seconds"),
                "duration_s": dur,
                "error": err,
            }
            append_step(rec)
            self.steps.append(rec)

    def __exit__(self, exc_type, exc, tb) -> bool:
        end_ts = dt.datetime.now()
        status = "ok" if exc_type is None else "fail"
        append_run(
            {
                "kind": "batch",  # 与 UpdateManager 的运行记录区分
                "run_id": self.run_id,
                "date": self.date.isoformat(),
                "trigger": self.trigger,
                "start_ts": self.start_ts.isoformat(timespec="seconds"),
                "end_ts": end_ts.isoformat(timespec="seconds"),
                "duration_s": round((end_ts - self.start_ts).total_seconds(), 3),
                "status": status,
                "error": str(exc) if exc else None,
                "steps": [
                    {"step": s["step"], "status": s["status"], "duration_s": s["duration_s"]}
                    for s in self.steps
                ],
            }
        )
        return False  # 不吞异常，交给上层
