"""热点实时守护调度器。

在盘后批量模式（Orchestrator.step_hotspot）之外，提供交易时段内的准实时热点采集：
- 每 N 分钟轮询所有热点源
- 采集到新热点后立即调用 LLM 分析
- 结果落库 + 可选 SSE 推送到 API 层

运行模式：
1. 独立进程模式：python -m scheduler.hotspot_daemon
2. 嵌入模式：由 Orchestrator 启动后台线程

合规约束：热点信号为"分析信号"，不触发交易。
"""
from __future__ import annotations

import datetime as dt
import signal
import sys
import threading
import time
from typing import Callable, List, Optional

from loguru import logger

from llm.client import LLMClient
from llm.hotspot_analyzer import HotspotAnalyzer, aggregate_by_code
from sources.hotspot_collector import HotspotCollector, create_collector
from storage.repository import Repository


class HotspotDaemon:
    """热点实时守护进程/线程。"""

    def __init__(
        self,
        repo: Repository,
        settings: dict,
        stock_codes: Optional[List[str]] = None,
        stock_pool: Optional[dict] = None,
        interval_seconds: int = 300,
        max_items_per_poll: int = 30,
    ) -> None:
        """
        Args:
            repo: 数据仓储层
            settings: 全局配置
            stock_codes: 个股新闻源的股票代码列表
            stock_pool: 股票池映射 {code: name}
            interval_seconds: 轮询间隔（秒），默认 5 分钟
            max_items_per_poll: 每次轮询每个源的最大条数
        """
        self.repo = repo
        self.settings = settings
        self.interval = interval_seconds
        self.max_items = max_items_per_poll

        self.llm = LLMClient(settings)
        self.collector = create_collector(
            stock_codes=stock_codes[:50] if stock_codes else None,
            enable_stock_news=bool(stock_codes),
            cache_dir=settings.get("paths", {}).get("hotspot_cache", "./data/hotspot_cache"),
        )
        self.analyzer = HotspotAnalyzer(
            llm=self.llm,
            stock_pool=stock_pool or {},
            batch_size=int(settings.get("hotspot", {}).get("batch_size", 8)),
            max_tokens=int(settings.get("hotspot", {}).get("max_tokens", 4096)),
        )

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_new_signals: Optional[Callable] = None
        self._total_collected = 0
        self._total_analyzed = 0

    def set_callback(self, callback: Callable) -> None:
        """设置新信号回调函数，签名 callback(signals: List[HotspotSignal]) -> None。"""
        self._on_new_signals = callback

    def start(self, daemon: bool = True) -> threading.Thread:
        """启动守护线程。"""
        if self._running:
            logger.warning("热点守护已在运行")
            return self._thread

        self._running = True

        def _loop():
            logger.info(
                f"热点实时守护启动，轮询间隔 {self.interval}s，"
                f"LLM 可用={self.llm.is_available}"
            )
            while self._running:
                try:
                    self._poll_once()
                except Exception as exc:
                    logger.error(f"热点守护轮询异常：{exc}")
                time.sleep(self.interval)
            logger.info("热点实时守护已停止")

        self._thread = threading.Thread(
            target=_loop, daemon=daemon, name="hotspot-daemon"
        )
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        """停止守护。"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def _poll_once(self) -> None:
        """单次轮询：采集 → 分析 → 落库 → 回调。"""
        # 1. 增量采集
        items = self.collector.collect_incremental(limit_per_source=self.max_items)
        if not items:
            return

        self._total_collected += len(items)

        # 2. LLM 分析
        signals = self.analyzer.analyze_batch(items)
        if not signals:
            return

        self._total_analyzed += len(signals)

        # 3. 落库
        import pandas as pd
        sig_df = pd.DataFrame([s.to_dict() for s in signals])
        sig_df["ts"] = pd.to_datetime(sig_df["ts"])
        self.repo.save_hotspot_signals(sig_df)

        # 4. 回调通知
        if self._on_new_signals:
            try:
                self._on_new_signals(signals)
            except Exception as exc:
                logger.warning(f"热点守护回调失败：{exc}")

        logger.info(
            f"热点守护轮询完成：采集 {len(items)} 条 → "
            f"分析 {len(signals)} 个信号"
            f"（累计：采集 {self._total_collected} / 分析 {self._total_analyzed}）"
        )

    @property
    def stats(self) -> dict:
        """运行统计。"""
        return {
            "running": self._running,
            "total_collected": self._total_collected,
            "total_analyzed": self._total_analyzed,
            "llm_available": self.llm.is_available,
            "interval_seconds": self.interval,
        }


def run_standalone(repo: Repository, settings: dict) -> None:
    """独立进程模式入口。

    用法：
        python -m scheduler.hotspot_daemon
    """
    # 从 settings 获取股票池
    stock_codes = []
    stock_pool = {}
    try:
        from sources.universe import UniverseFilter
        import pandas as pd
        uni_filter = UniverseFilter(settings)
        # 加载最近交易日 universe
        today = dt.date.today()
        bars = repo.load_bars(end=today)
        stock_list = settings.get("_stock_list")
        if stock_list is not None:
            uni = uni_filter.build_universe(today, stock_list, bars)
            stock_codes = uni["code"].tolist()
            for _, row in stock_list.iterrows():
                code = str(row.get("code", "")).split(".")[0]
                name = str(row.get("name", ""))
                if code:
                    stock_pool[code] = name
    except Exception as exc:
        logger.warning(f"热点守护：加载股票池失败，降级为空池：{exc}")

    daemon = HotspotDaemon(
        repo=repo,
        settings=settings,
        stock_codes=stock_codes,
        stock_pool=stock_pool,
        interval_seconds=int(settings.get("hotspot", {}).get("daemon_interval", 300)),
        max_items_per_poll=int(settings.get("hotspot", {}).get("daemon_max_items", 30)),
    )

    # 优雅退出
    def _signal_handler(signum, frame):
        logger.info(f"收到信号 {signum}，正在停止热点守护...")
        daemon.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    daemon.start(daemon=False)
    # 主线程保持运行
    try:
        while daemon._thread and daemon._thread.is_alive():
            daemon._thread.join(timeout=1)
    except KeyboardInterrupt:
        daemon.stop()


if __name__ == "__main__":
    from api.database import get_repository, get_settings

    settings = get_settings()
    repo = get_repository(settings)
    run_standalone(repo, settings)
