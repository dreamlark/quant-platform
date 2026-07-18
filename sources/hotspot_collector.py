"""热点信息搜集系统（持续运行的多源文本采集器）。

设计原则：
- 与行情数据源层（DataSource/DataSourceRouter）平级，作为文本数据源层
- 多源并发采集 + 统一清洗去重 + 增量追踪
- 每个源独立降级：任一源失败不阻断其他源
- 采集器可独立运行（实时守护），也可被编排器调用（盘后批量）
- 输出统一的 HotspotItem 格式，供 LLM 分析引擎消费

数据源优先级：
- P0（立即可用）：akshare 全市场新闻（百度财经/东方财富）+ 个股新闻
- P1（需自建采集器）：财联社电报
- P2（按需扩展）：股吧热帖、巨潮公告
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class HotspotItem:
    """统一热点文本条目（所有数据源的归一化输出）。"""

    ts: dt.datetime           # 发布时间（归一化为 Asia/Shanghai）
    source: str               # 数据来源标识
    title: str                # 标题
    content: str = ""         # 正文内容（可能为空，仅有标题）
    url: str = ""             # 原始链接
    related_codes: List[str] = field(default_factory=list)  # 源端标记的关联股票
    raw: Dict[str, Any] = field(default_factory=dict)       # 原始数据（审计用）

    @property
    def content_hash(self) -> str:
        """内容 MD5 hash（精确去重用）。"""
        return hashlib.md5(self.title.encode("utf-8")).hexdigest()


# ============================================================================
# 数据源抽象基类
# ============================================================================

class HotspotSource(abc := type("abc", (), {"abstractmethod": staticmethod(lambda f: f)})):
    """热点数据源抽象基类（与 DataSource 平级，但面向文本流）。"""

    name: str = "base"
    priority: int = 99

    def fetch_since(self, since: Optional[dt.datetime], limit: int = 100) -> List[HotspotItem]:
        """拉取指定时间之后的增量热点文本。"""
        raise NotImplementedError

    def health_check(self) -> bool:
        """数据源可用性探测，默认 True。"""
        return True


# 用标准库 abc 重写
import abc as _abc


class _HotspotSourceMeta(_abc.ABCMeta):
    pass


class HotspotSourceBase(metaclass=_HotspotSourceMeta):
    """热点数据源抽象基类。"""

    name: str = "base"
    priority: int = 99

    @_abc.abstractmethod
    def fetch_since(self, since: Optional[dt.datetime], limit: int = 100) -> List[HotspotItem]:
        """拉取指定时间之后的增量热点文本。"""
        ...

    def health_check(self) -> bool:
        return True


# ============================================================================
# P0 数据源：akshare 全市场新闻
# ============================================================================

class BaiduNewsSource(HotspotSourceBase):
    """百度财经全市场新闻流（akshare news_economic_baidu）。

    akshare 接口返回全市场财经新闻，覆盖面广，无需逐股票拉取。
    字段通常包含: date, title, content, source 等。
    """

    name = "baidu_finance"
    priority = 1

    def __init__(self, per_page: int = 100) -> None:
        self.per_page = per_page
        self._ak = None
        self._healthy: Optional[bool] = None

    def _get_ak(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def fetch_since(self, since: Optional[dt.datetime] = None, limit: int = 100) -> List[HotspotItem]:
        try:
            ak = self._get_ak()
            if not hasattr(ak, "news_economic_baidu"):
                logger.debug("akshare 无 news_economic_baidu 接口")
                return []
            df = ak.news_economic_baidu()
            if df is None or df.empty:
                return []

            # 归一化列名
            col_map = self._guess_columns(df.columns)
            items: List[HotspotItem] = []
            for _, row in df.iterrows():
                ts = self._parse_ts(row.get(col_map.get("date", "")))
                if ts is None:
                    continue
                if since and ts < since:
                    continue
                title = str(row.get(col_map.get("title", ""), "")).strip()
                if not title:
                    continue
                content = str(row.get(col_map.get("content", ""), "")).strip()
                source = str(row.get(col_map.get("source", "baidu"), "百度财经")).strip()

                items.append(HotspotItem(
                    ts=ts,
                    source=self.name,
                    title=title,
                    content=content[:500] if content else "",
                    url=str(row.get(col_map.get("url", ""), "")).strip(),
                    raw={k: str(v) for k, v in row.items()},
                ))
                if len(items) >= limit:
                    break
            logger.info(f"热点源 {self.name}: 采集 {len(items)} 条")
            return items
        except Exception as exc:
            logger.warning(f"热点源 {self.name} 采集失败：{exc}")
            return []

    @staticmethod
    def _guess_columns(cols) -> Dict[str, str]:
        """猜测列名映射。"""
        mapping: Dict[str, str] = {}
        for c in cols:
            cl = str(c).lower()
            if "date" in cl or "时间" in cl or "time" in cl:
                mapping["date"] = c
            elif "title" in cl or "标题" in cl or "新闻" in cl:
                mapping["title"] = c
            elif "content" in cl or "内容" in cl or "摘要" in cl:
                mapping["content"] = c
            elif "source" in cl or "来源" in cl:
                mapping["source"] = c
            elif "url" in cl or "链接" in cl:
                mapping["url"] = c
        return mapping

    @staticmethod
    def _parse_ts(val: Any) -> Optional[dt.datetime]:
        """解析时间戳，归一化为 datetime。"""
        if val is None:
            return None
        try:
            if isinstance(val, dt.datetime):
                return val
            if isinstance(val, dt.date):
                return dt.datetime.combine(val, dt.time())
            s = str(val).strip()
            # 尝试多种格式
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M",
                "%Y/%m/%d",
            ):
                try:
                    return dt.datetime.strptime(s, fmt)
                except ValueError:
                    continue
            # 尝试 pandas
            import pandas as pd
            return pd.to_datetime(s, errors="coerce").to_pydatetime()
        except Exception:
            return None

    def health_check(self) -> bool:
        if self._healthy is None:
            try:
                items = self.fetch_since(limit=1)
                self._healthy = len(items) > 0
            except Exception:
                self._healthy = False
        return bool(self._healthy)


class EastmoneyGlobalSource(HotspotSourceBase):
    """东方财富全球新闻流（akshare stock_info_global_em）。

    提供东方财富网的全球财经新闻流，覆盖面广。
    """

    name = "eastmoney_global"
    priority = 2

    def __init__(self) -> None:
        self._ak = None
        self._healthy: Optional[bool] = None

    def _get_ak(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def fetch_since(self, since: Optional[dt.datetime] = None, limit: int = 100) -> List[HotspotItem]:
        try:
            ak = self._get_ak()
            if not hasattr(ak, "stock_info_global_em"):
                return []
            df = ak.stock_info_global_em()
            if df is None or df.empty:
                return []

            col_map = BaiduNewsSource._guess_columns(df.columns)
            items: List[HotspotItem] = []
            for _, row in df.iterrows():
                ts = BaiduNewsSource._parse_ts(row.get(col_map.get("date", "")))
                if ts is None:
                    continue
                if since and ts < since:
                    continue
                title = str(row.get(col_map.get("title", ""), "")).strip()
                if not title:
                    continue
                content = str(row.get(col_map.get("content", ""), "")).strip()

                items.append(HotspotItem(
                    ts=ts,
                    source=self.name,
                    title=title,
                    content=content[:500] if content else "",
                    url=str(row.get(col_map.get("url", ""), "")).strip(),
                    raw={k: str(v) for k, v in row.items()},
                ))
                if len(items) >= limit:
                    break
            logger.info(f"热点源 {self.name}: 采集 {len(items)} 条")
            return items
        except Exception as exc:
            logger.warning(f"热点源 {self.name} 采集失败：{exc}")
            return []

    def health_check(self) -> bool:
        if self._healthy is None:
            try:
                items = self.fetch_since(limit=1)
                self._healthy = len(items) > 0
            except Exception:
                self._healthy = False
        return bool(self._healthy)


class StockNewsSource(HotspotSourceBase):
    """个股新闻（akshare stock_news_em，遍历重点股票池）。

    与全市场源互补：全市场源覆盖面广但个股粒度粗；
    个股源逐股票拉取但能拿到精准的 related_codes。
    仅遍历可投资域 top N（如 HS300 成分），控制调用量。
    """

    name = "stock_news"
    priority = 3

    def __init__(self, codes: List[str], per_code_limit: int = 5, batch_size: int = 20) -> None:
        self.codes = codes
        self.per_code_limit = per_code_limit
        self.batch_size = batch_size
        self._ak = None
        self._healthy: Optional[bool] = None

    def _get_ak(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def fetch_since(self, since: Optional[dt.datetime] = None, limit: int = 100) -> List[HotspotItem]:
        try:
            ak = self._get_ak()
            items: List[HotspotItem] = []
            fetched = 0
            for code in self.codes:
                if fetched >= limit:
                    break
                try:
                    symbol = code.split(".")[0] if "." in code else code
                    df = ak.stock_news_em(symbol=symbol)
                    if df is None or df.empty:
                        continue
                    col_map = BaiduNewsSource._guess_columns(df.columns)
                    for _, row in df.iterrows():
                        ts = BaiduNewsSource._parse_ts(row.get(col_map.get("date", "")))
                        if ts is None:
                            continue
                        if since and ts < since:
                            continue
                        title = str(row.get(col_map.get("title", ""), "")).strip()
                        if not title:
                            continue
                        content = str(row.get(col_map.get("content", ""), "")).strip()
                        items.append(HotspotItem(
                            ts=ts,
                            source=self.name,
                            title=title,
                            content=content[:500] if content else "",
                            url=str(row.get(col_map.get("url", ""), "")).strip(),
                            related_codes=[symbol],
                            raw={k: str(v) for k, v in row.items()},
                        ))
                        fetched += 1
                        if fetched >= limit:
                            break
                    # 限制请求频率
                    time.sleep(0.3)
                except Exception as exc:
                    logger.debug(f"热点源 {self.name}: 个股 {code} 新闻拉取失败：{exc}")
                    continue
            logger.info(f"热点源 {self.name}: 采集 {len(items)} 条（遍历 {len(self.codes)} 只标的）")
            return items
        except Exception as exc:
            logger.warning(f"热点源 {self.name} 采集失败：{exc}")
            return []

    def health_check(self) -> bool:
        if self._healthy is None:
            try:
                ak = self._get_ak()
                symbol = self.codes[0].split(".")[0] if self.codes else "000001"
                df = ak.stock_news_em(symbol=symbol)
                self._healthy = df is not None and not df.empty
            except Exception:
                self._healthy = False
        return bool(self._healthy)


# ============================================================================
# SimHash 近似去重
# ============================================================================

class SimHashDedup:
    """SimHash 近似去重器（用于标题去重）。

    使用简化的 SimHash 算法：
    1. 对文本分词（按字符二元组）
    2. 每个 token hash 后加权累加
    3. 最终取符号位得到 64 位指纹
    4. 汉明距离 ≤ 3 视为相似
    """

    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self._fingerprints: List[int] = []

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """字符二元组分词（适合中文，无需分词库）。"""
        text = re.sub(r"\s+", "", text)
        if len(text) < 2:
            return [text] if text else []
        return [text[i:i + 2] for i in range(len(text) - 1)]

    @staticmethod
    def _hash64(token: str) -> int:
        """64 位 hash（MD5 取前 16 位 hex 转 int）。"""
        h = hashlib.md5(token.encode("utf-8")).hexdigest()[:16]
        return int(h, 16)

    def compute(self, text: str) -> int:
        """计算文本的 SimHash 指纹。"""
        tokens = self._tokenize(text)
        if not tokens:
            return 0
        v = [0] * 64
        for token in tokens:
            h = self._hash64(token)
            for i in range(64):
                if h & (1 << i):
                    v[i] += 1
                else:
                    v[i] -= 1
        result = 0
        for i in range(64):
            if v[i] > 0:
                result |= (1 << i)
        return result

    @staticmethod
    def hamming_distance(a: int, b: int) -> int:
        """计算两个指纹的汉明距离。"""
        return bin(a ^ b).count("1")

    def is_duplicate(self, text: str) -> bool:
        """检查文本是否与已存在指纹重复。"""
        fp = self.compute(text)
        for existing in self._fingerprints:
            if self.hamming_distance(fp, existing) <= self.threshold:
                return True
        self._fingerprints.append(fp)
        return False

    def reset(self) -> None:
        """重置指纹库。"""
        self._fingerprints.clear()


# ============================================================================
# 热点采集主控
# ============================================================================

class HotspotCollector:
    """热点信息搜集系统主控（多源并发 + 去重 + 增量追踪）。

    运行模式：
    1. 实时守护模式：后台线程每 60s 轮询所有源，产出增量 HotspotItem
    2. 批量模式：盘后一次性拉取当日全部热点（供 orchestrator 调用）
    3. 被动模式：供 API 按需调用拉取最新热点
    """

    def __init__(
        self,
        sources: List[HotspotSourceBase],
        dedup_simhash_threshold: int = 3,
        cache_dir: str = "./data/hotspot_cache",
    ) -> None:
        self.sources = sorted(sources, key=lambda s: s.priority)
        self.simhash = SimHashDedup(threshold=dedup_simhash_threshold)
        self.cache_dir = cache_dir
        self._seen_hashes: set[str] = set()
        self._lock = threading.Lock()
        self._last_fetch: Dict[str, dt.datetime] = {}
        self._running = False
        self._daemon_thread: Optional[threading.Thread] = None
        os.makedirs(cache_dir, exist_ok=True)

    def collect_incremental(
        self,
        since: Optional[dt.datetime] = None,
        limit_per_source: int = 100,
    ) -> List[HotspotItem]:
        """增量采集：拉取所有源的增量文本，去重后返回。

        Args:
            since: 拉取此时间之后的文本（None 表示拉取最新）
            limit_per_source: 每个源的拉取上限
        """
        all_items: List[HotspotItem] = []

        for src in self.sources:
            if not src.health_check():
                logger.warning(f"热点源 {src.name} 健康检查失败，跳过")
                continue
            try:
                effective_since = since or self._last_fetch.get(src.name)
                items = src.fetch_since(effective_since, limit=limit_per_source)
                all_items.extend(items)
                self._last_fetch[src.name] = dt.datetime.now()
            except Exception as exc:
                logger.warning(f"热点源 {src.name} 采集失败（降级）：{exc}")

        # 去重
        unique = self._dedup(all_items)
        logger.info(
            f"热点采集：{len(all_items)} 条 → 去重后 {len(unique)} 条"
            f"（来源：{', '.join(s.name for s in self.sources)}）"
        )
        return unique

    def collect_batch(self, date: dt.date) -> List[HotspotItem]:
        """批量采集：拉取指定日期的全部热点（盘后模式）。"""
        start = dt.datetime.combine(date, dt.time(0, 0))
        end = dt.datetime.combine(date, dt.time(23, 59, 59))
        items = self.collect_incremental(since=start)
        # 过滤当日
        return [item for item in items if start <= item.ts <= end]

    def _dedup(self, items: List[HotspotItem]) -> List[HotspotItem]:
        """双重去重：MD5 精确去重 + SimHash 近似去重。"""
        result: List[HotspotItem] = []
        with self._lock:
            for item in items:
                # 精确去重
                if item.content_hash in self._seen_hashes:
                    continue
                # 近似去重
                if self.simhash.is_duplicate(item.title):
                    continue
                self._seen_hashes.add(item.content_hash)
                result.append(item)
        return result

    def reset_dedup(self) -> None:
        """重置去重缓存（批量模式每次调用前重置）。"""
        with self._lock:
            self._seen_hashes.clear()
            self.simhash.reset()

    def run_daemon(
        self,
        interval_seconds: int = 60,
        callback: Optional[Callable[[List[HotspotItem]], None]] = None,
        max_items_per_poll: int = 50,
    ) -> threading.Thread:
        """实时守护模式：每 interval_seconds 秒采集一次，通过 callback 推送结果。

        Args:
            interval_seconds: 轮询间隔（秒）
            callback: 回调函数，签名 callback(items: List[HotspotItem]) -> None
            max_items_per_poll: 每次轮询每个源的最大条数

        Returns:
            守护线程对象（daemon=True）
        """
        if self._running:
            logger.warning("热点采集守护已在运行")
            return self._daemon_thread

        self._running = True

        def _loop():
            logger.info(f"热点采集守护启动，轮询间隔 {interval_seconds}s")
            while self._running:
                try:
                    items = self.collect_incremental(limit_per_source=max_items_per_poll)
                    if items and callback:
                        callback(items)
                except Exception as exc:
                    logger.error(f"热点采集守护异常：{exc}")
                time.sleep(interval_seconds)
            logger.info("热点采集守护已停止")

        self._daemon_thread = threading.Thread(
            target=_loop, daemon=True, name="hotspot-collector"
        )
        self._daemon_thread.start()
        return self._daemon_thread

    def stop_daemon(self) -> None:
        """停止守护模式。"""
        self._running = False
        if self._daemon_thread and self._daemon_thread.is_alive():
            self._daemon_thread.join(timeout=5)
        logger.info("热点采集守护已请求停止")


# ============================================================================
# 工厂函数
# ============================================================================

def create_collector(
    stock_codes: Optional[List[str]] = None,
    enable_stock_news: bool = True,
    cache_dir: str = "./data/hotspot_cache",
) -> HotspotCollector:
    """创建热点采集器（默认启用所有 P0 源）。

    Args:
        stock_codes: 个股新闻源的股票代码列表（None 则不启用个股源）
        enable_stock_news: 是否启用个股新闻源
        cache_dir: 缓存目录

    Returns:
        HotspotCollector 实例
    """
    sources: List[HotspotSourceBase] = [
        BaiduNewsSource(),
        EastmoneyGlobalSource(),
    ]
    if enable_stock_news and stock_codes:
        sources.append(StockNewsSource(codes=stock_codes))

    return HotspotCollector(sources=sources, cache_dir=cache_dir)
