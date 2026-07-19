"""运维控制端点：手动/自动数据更新、运行状态、失败自动重试、断点续跑。

设计要点：
- 更新在**后台线程**异步执行，不阻塞 API；前端轮询 /admin/status 看进度。
- 每一步失败**自动重试 3 次**（指数退避）；整轮仍失败则标记 failed，可再次触发
  （各 step 幂等 upsert，重跑即从断点补完，不重复拉源、不丢已落库数据）。
- 自动运行：API 进程内嵌 BackgroundScheduler（工作日 18:30，可在 Web 上开关），
  到点自动调用更新；关闭则停止。
- 更新期间看板仍可查（旧快照），DuckDB 读写连接并发时偶发稍慢属正常。
"""
from __future__ import annotations

import datetime as dt
import hmac
import os
import sys
import threading
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import load_settings  # noqa: E402
from api.database import get_repository  # noqa: E402
from api.run_store import append_run  # noqa: E402

router = APIRouter(prefix="/api/admin", tags=["admin"])

# 运维端点鉴权开关：仅当显式设置 ADMIN_TOKEN 时才启用，本地默认不鉴权（README §17）。
ADMIN_TOKEN = (os.getenv("ADMIN_TOKEN") or "").strip()


def require_admin(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(None),
) -> None:
    """运维端点鉴权依赖。

    - ADMIN_TOKEN 未设置（本地默认）：放行，保持向后兼容。
    - ADMIN_TOKEN 已设置：必须在请求头提供正确令牌，否则 401。
      支持 ``X-Admin-Token: <token>`` 或 ``Authorization: Bearer <token>``。
    公网部署务必设置该环境变量（README §17）。
    """
    if not ADMIN_TOKEN:
        return
    provided = x_admin_token
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1]
    if not provided or not hmac.compare_digest(provided, ADMIN_TOKEN):
        raise HTTPException(
            status_code=401,
            detail="未授权：请提供正确的管理员令牌（X-Admin-Token 或 Authorization Bearer）",
        )

# 一轮更新的步骤（顺序固定；ingest 在最前拉最新行情）
_STEPS = [
    ("ingest", "拉取最新日K"),
    ("universe", "更新可投资域"),
    ("factors", "计算因子"),
    ("sentiment", "量价情绪"),
    ("predict", "预测(Kronos/Darts)"),
    ("health", "因子体检"),
    ("neutralize", "中性化"),
    ("fusion", "四源融合"),
    ("sector", "板块轮动"),
    ("market_sentiment", "市场情绪指数"),
    ("llm", "LLM简报"),
    ("backtest", "回测"),
]


class UpdateManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = {
            "status": "idle",          # idle | running | success | failed
            "progress": 0,             # 已完成步骤数
            "total": len(_STEPS),
            "current_step": "",
            "started_at": None,
            "finished_at": None,
            "last_success_date": None,
            "last_error": None,
            "message": "尚未运行",
            "auto_enabled": False,
            "next_run": None,
        }
        self._scheduler = None
        self._thread: threading.Thread | None = None
        self._run_meta: dict = {"run_id": None, "started_at": None, "trigger": "manual"}
        # —— 实时运行日志缓冲（前端轮询展示）——
        self._log_lock = threading.Lock()
        self._logs: list[dict] = []
        self._log_max = 500  # 滚动保留最近 500 条

    def _log(self, level: str, message: str, step: str = "", step_label: str = "") -> None:
        """线程安全追加一条运行日志（带时间戳 + 步骤标识）。"""
        ts = dt.datetime.now().strftime("%H:%M:%S")
        entry = {
            "ts": ts,
            "level": level,        # info | success | warn | error
            "step": step,
            "step_label": step_label,
            "message": message,
        }
        with self._log_lock:
            self._logs.append(entry)
            if len(self._logs) > self._log_max:
                self._logs = self._logs[-self._log_max:]

    def get_logs(self) -> list[dict]:
        """返回当前运行日志副本（前端轮询用）。"""
        with self._log_lock:
            return list(self._logs)

    # -------- 构造编排器（复用 API 单例 Repository，避免重复打开 DuckDB 连接）--------
    def _build_orch(self):
        from scheduler.jobs import build_data_router
        from scheduler.orchestrator import Orchestrator
        from sources.market_meta import build_market_meta

        settings = load_settings()
        # 复用 api.database 的单例 Repository，不再重复 build_repository 打开同一 DuckDB 文件
        repo = get_repository()

        # 沪深300 成分（akshare，失败兜底 universe 表）
        codes, names = [], []
        try:
            import akshare as ak

            df = ak.index_stock_cons_csindex(symbol="000300")[
                ["成分券代码", "成分券名称"]
            ].rename(columns={"成分券代码": "code", "成分券名称": "name"})
            codes = df["code"].astype(str).str.zfill(6).tolist()
            names = df["name"].astype(str).tolist()
        except Exception:
            rows = repo.market.execute(
                "SELECT DISTINCT code, name FROM universe WHERE in_universe=TRUE"
            ).fetchall()
            codes = [str(r[0]).zfill(6) for r in rows]
            names = [str(r[1]) for r in rows]

        meta = build_market_meta(codes, names)
        stock_list = meta[["code", "name", "industry", "mv"]]
        # 多源冗余路由（mootdx→akshare→baostock，与 README / scheduler 一致）
        src = build_data_router(settings)
        orch = Orchestrator(repo=repo, settings=settings, data_source=src, stock_list=stock_list)
        return orch, repo, stock_list

    # -------- 长步骤心跳：在耗时操作期间定期写入进度日志 --------
    def _run_with_heartbeat(self, fn, step_name: str, step_label: str) -> None:
        """在线程中执行 fn()，同时每隔 HEARTBEAT_INTERVAL 秒写一条心跳日志，
        让前端实时看到步骤仍在执行及已耗时。"""
        import threading as _th

        result_holder: list[None | BaseException] = [None]
        elapsed = [0.0]
        stopped = [False]
        HEARTBEAT_INTERVAL = 20  # 每 20 秒报一次心跳

        def _heartbeat():
            while not stopped[0]:
                time.sleep(HEARTBEAT_INTERVAL)
                if not stopped[0]:
                    elapsed[0] += HEARTBEAT_INTERVAL
                    mins = int(elapsed[0] // 60)
                    secs = int(elapsed[0] % 60)
                    self._log(
                        "info",
                        f"{step_label} 执行中… 已耗时 {mins}分{secs:02d}秒",
                        step_name,
                        step_label,
                    )

        hb_thread = _th.Thread(target=_heartbeat, daemon=True)
        hb_thread.start()
        try:
            fn()
        except Exception as e:
            result_holder[0] = e
        finally:
            stopped[0] = True
            hb_thread.join(timeout=2)
        if result_holder[0] is not None:
            raise result_holder[0]

    # -------- 跑一轮（每步自动重试）--------
    def _run_once(self) -> None:
        orch, repo, _ = self._build_orch()
        today = dt.date.today()
        start = today - dt.timedelta(days=300)
        step_fns = {
            "ingest": lambda: orch.step_ingest(start, today),
            "universe": lambda: orch.step_universe(today),
            "factors": lambda: orch.step_factors(today),
            "sentiment": lambda: orch.step_sentiment(today),
            "predict": lambda: orch.step_predict(today),
            "health": lambda: orch.step_health(today),
            "neutralize": lambda: orch.step_neutralize(today),
            "fusion": lambda: orch.step_fusion(today),
            "sector": lambda: orch.step_sector(today),
            "market_sentiment": lambda: orch.step_market_sentiment(today),
            "llm": lambda: orch.step_llm(today),
            "backtest": lambda: orch.step_backtest(today),
        }

        # 标记已知耗时的步骤（这些步骤使用 _run_with_heartbeat 注入心跳日志）
        SLOW_STEPS = {"ingest", "factors", "predict", "llm", "backtest"}

        # 1) 先拉最新行情（确定目标日），完成后立即更新进度
        self.state["current_step"] = "ingest"
        self.state["message"] = "正在拉取行情数据..."
        self._log("info", "开始拉取最新日K行情（全量 300+ 股票，预计需数分钟）...", "ingest", "拉取最新日K")
        try:
            self._run_with_heartbeat(step_fns["ingest"], "ingest", "拉取最新日K")
        except Exception as exc:
            self._log("error", f"拉取行情失败：{exc}", "ingest", "拉取最新日K")
            raise RuntimeError(f"步骤「ingest」拉取行情失败：{exc}") from exc
        target = repo.market.execute("SELECT max(date) FROM daily_bars").fetchone()[0]
        orch.source = None  # 后续不再重复 ingest
        self.state["progress"] = 1  # ingest 完成，进度从 0→1
        self.state["last_success_date"] = str(target)
        self._log("success", f"行情拉取完成，目标日 {target}", "ingest", "拉取最新日K")

        # 2) 依次跑其余步骤，每步最多重试 3 次
        done = 1  # ingest 已完成
        for name, label in _STEPS[1:]:
            self.state["current_step"] = name
            self.state["message"] = f"正在执行：{label}..."
            self._log("info", f"步骤开始：{label}", name, label)
            last_err: Exception | None = None
            runner = self._run_with_heartbeat if name in SLOW_STEPS else (lambda f, n, l: f())
            for attempt in range(3):
                try:
                    runner(step_fns[name], name, label)
                    last_err = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    if attempt < 2:
                        self._log("warn", f"{label} 第{attempt+1}次失败，{3*(attempt+1)}s 后重试：{exc}", name, label)
                        time.sleep(3 * (attempt + 1))  # 退避 3/6/9s
                    else:
                        self._log("error", f"{label} 第3次失败：{exc}", name, label)
            if last_err is not None:
                raise RuntimeError(f"步骤「{name}」重试 3 次仍失败：{last_err}")
            done += 1
            self.state["progress"] = done
            self._log("success", f"步骤完成：{label}（{done}/{len(_STEPS)}）", name, label)

        self.state["status"] = "success"
        self.state["last_success_date"] = str(target)
        self.state["last_error"] = None
        self.state["message"] = f"更新完成，目标日 {target}"
        self._log("success", f"全部步骤完成，目标日 {target}", "", "完成")

    # -------- 触发（防并发）--------
    def trigger(self, source: str = "manual") -> bool:
        with self._lock:
            if self.state["status"] == "running":
                return False
            self.state["status"] = "running"
            self.state["progress"] = 0
            self.state["started_at"] = dt.datetime.now().isoformat(timespec="seconds")
            self.state["last_error"] = None
            self.state["message"] = "开始更新..."
            self.state["current_step"] = "ingest"
            # 新一轮：清空旧日志，从本次运行开始记录
            with self._log_lock:
                self._logs = []
            self._log("info", f"触发数据更新（来源：{source}）", "", "开始")
            self._run_meta = {
                "run_id": uuid.uuid4().hex[:12],
                "started_at": self.state["started_at"],
                "trigger": source,
            }
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()
            return True

    def _worker(self) -> None:
        finished_at = None
        try:
            self._run_once()
        except Exception as exc:  # noqa: BLE001
            self.state["status"] = "failed"
            self.state["last_error"] = f"{type(exc).__name__}: {exc}"
            self.state["message"] = "更新失败——可再次点击「立即更新」从断点续跑"
            self._log("error", f"更新失败：{type(exc).__name__}: {exc}", "", "失败")
        else:
            self._log("success", "更新轮次成功结束", "", "完成")
        finally:
            finished_at = dt.datetime.now().isoformat(timespec="seconds")
            self.state["finished_at"] = finished_at
            self.state["current_step"] = ""
        # 落运行历史（与 DuckDB 写者解耦，独立 JSONL）
        try:
            started = dt.datetime.fromisoformat(self._run_meta["started_at"])
            ended = dt.datetime.fromisoformat(finished_at)
            rec = {
                "run_id": self._run_meta["run_id"],
                "trigger": self._run_meta["trigger"],
                "started_at": self._run_meta["started_at"],
                "finished_at": finished_at,
                "duration_sec": round((ended - started).total_seconds(), 1),
                "status": self.state["status"],
                "target_date": self.state["last_success_date"],
                "reached_step": self.state["current_step"] or "完成",
                "progress": self.state["progress"],
                "total": self.state["total"],
                "error": self.state["last_error"],
            }
            append_run(rec)
        except Exception:
            pass

    # -------- 自动调度（内嵌 BackgroundScheduler，Web 开关控制）--------
    def start_auto(self, hour: int = 18, minute: int = 30) -> None:
        if self._scheduler is not None and self._scheduler.running:
            return
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        settings = load_settings()
        sched_cfg = settings.get("scheduler", {})
        tz = sched_cfg.get("timezone", "Asia/Shanghai")
        # 优先使用用户传入的时间，否则回退配置文件
        self._auto_hour = hour
        self._auto_minute = minute
        self._scheduler = BackgroundScheduler(timezone=tz)
        self._scheduler.add_job(
            lambda: self.trigger("auto"),
            CronTrigger(
                minute=self._auto_minute,
                hour=self._auto_hour,
                day_of_week="1-5",  # 工作日
            ),
            id="auto_update",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        self.state["auto_enabled"] = True
        job = self._scheduler.get_job("auto_update")
        self.state["next_run"] = job.next_run_time.isoformat(timespec="seconds") if job else None

    def stop_auto(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        self.state["auto_enabled"] = False
        self.state["next_run"] = None


mgr = UpdateManager()


@router.post("/update")
def update(_: None = Depends(require_admin)):
    """触发一轮数据更新与预测（异步）。已在运行时返回 409。"""
    ok = mgr.trigger()
    if not ok:
        raise HTTPException(status_code=409, detail="已有更新任务在运行中，请稍候")
    return {"status": "running", "message": "已触发数据更新"}


@router.get("/status")
def status():
    """当前更新/调度状态。"""
    return mgr.state


@router.get("/logs")
def logs():
    """实时运行日志（前端轮询展示，含每步开始/完成/重试/失败）。"""
    return {"logs": mgr.get_logs(), "status": mgr.state["status"]}


@router.post("/auto/start")
def auto_start(
    hour: int = 18,
    minute: int = 30,
    _: None = Depends(require_admin),
):
    """启动 Web 可控的自动运行（工作日指定时间自动更新，默认 18:30）。"""
    mgr.start_auto(hour=hour, minute=minute)
    return {
        "auto_enabled": True,
        "next_run": mgr.state["next_run"],
        "schedule_time": f"{hour:02d}:{minute:02d}",
    }


@router.post("/auto/stop")
def auto_stop(_: None = Depends(require_admin)):
    """停止自动运行。"""
    mgr.stop_auto()
    return {"auto_enabled": False}
