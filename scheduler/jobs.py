"""定时调度任务（APScheduler，盘后批处理 18:00 后）。

生产部署：由 ``start()`` 构建数据源路由 + 股票主表 + Orchestrator，按 cron 触发
``run_daily``。沙箱/冒烟无需调度，直接调用 Orchestrator 步骤即可。
"""
from __future__ import annotations

import datetime as dt
import os
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# 仓库根加入路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import build_repository, load_settings  # noqa: E402
from scheduler.orchestrator import Orchestrator  # noqa: E402
from sources.akshare_adapter import AkshareDailyAdapter  # noqa: E402
from sources.base import DataSourceRouter  # noqa: E402
from sources.baostock_adapter import BaostockAdapter  # noqa: E402
from sources.mootdx_adapter import MootdxAdapter  # noqa: E402

# 股票主表样例（生产应由基本面源/AkShare 行业接口提供；此处给最小可用骨架）
DEFAULT_STOCK_LIST = [
    {"code": "600519.SH", "name": "贵州茅台", "listed_date": "2001-08-27", "industry": "I02", "mv": 2.0e12},
    {"code": "000858.SZ", "name": "五粮液", "listed_date": "1998-04-27", "industry": "I02", "mv": 5.0e11},
    {"code": "600036.SH", "name": "招商银行", "listed_date": "2002-04-09", "industry": "I01", "mv": 8.0e11},
    {"code": "000725.SZ", "name": "京东方A", "listed_date": "2001-01-12", "industry": "I03", "mv": 1.5e11},
    {"code": "601012.SH", "name": "隆基绿能", "listed_date": "2012-04-11", "industry": "I04", "mv": 1.2e11},
]


def build_data_router(settings: dict) -> DataSourceRouter:
    cfg = settings.get("data_sources", {})
    priority = cfg.get("priority", ["mootdx", "akshare", "baostock"])
    m = cfg.get("mootdx", {})
    sources = []
    for name in priority:
        if name == "mootdx":
            sources.append(MootdxAdapter(market=m.get("market", "std"), bestip=m.get("bestip", True)))
        elif name == "akshare":
            sources.append(AkshareDailyAdapter())
        elif name == "baostock":
            sources.append(BaostockAdapter())
    return DataSourceRouter(
        sources,
        diff_threshold=cfg.get("diff_threshold", 0.03),
        cache_raw=cfg.get("cache_raw", True),
        cache_dir=os.path.join(ROOT, cfg.get("raw_cache", "./data/raw_cache")),
        source_timeout=cfg.get("source_timeout", 20.0),
        divergence_log=os.path.join(ROOT, cfg.get("divergence_log", "./data/divergence_log.jsonl")),
    )


def build_scheduler(settings: dict, stock_list=None):
    sched = BlockingScheduler(
        timezone=settings.get("scheduler", {}).get("timezone", "Asia/Shanghai")
    )
    cron = settings.get("scheduler", {}).get("cron", "30 18 * * 1-5")
    parts = cron.split()
    minute, hour, _, _, dow = (parts + ["*", "*", "*", "*", "*"])[:5]
    trigger = CronTrigger(
        minute=int(minute), hour=int(hour),
        day_of_week=dow if dow != "*" else None,
    )
    repo, _ = build_repository(settings)
    router = build_data_router(settings)
    sl = stock_list or DEFAULT_STOCK_LIST
    import pandas as pd

    sl_df = pd.DataFrame(sl)
    orch = Orchestrator(repo, settings, data_source=router, stock_list=sl_df)

    sched.add_job(
        lambda: orch.run_daily(dt.date.today()),
        trigger,
        id="daily_pipeline",
        max_instances=1,
        coalesce=True,
    )
    return sched, orch


def main() -> None:
    settings = load_settings()
    if not settings.get("scheduler", {}).get("enabled", False):
        print("调度未启用（scheduler.enabled=false）。如需启动请设为 true。")
        print("单次运行示例：python -c \"from scheduler.orchestrator import *; ...\"")
        return
    sched, _ = build_scheduler(settings)
    print("调度器启动，cron =", settings.get("scheduler", {}).get("cron"))
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("调度器已停止")


if __name__ == "__main__":
    main()
