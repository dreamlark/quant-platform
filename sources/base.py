"""数据源抽象基类 + 多源路由/降级。

设计要点（架构 §7.4 多源冗余与降级约定）：
- ``DataSource`` 定义统一接口；各适配器（mootdx/akshare/baostock）实现之。
- ``DataSourceRouter`` 按优先级依次尝试，主源失败自动切换冗余源；
  多源同标的差异超阈值则告警并标记 ``source`` 可疑。
- 每次原始响应缓存到 ``data/raw_cache/`` 供降级比对。
- ``InMemoryDataSource`` 用于单元测试 / 冒烟测试（构造假数据，零网络）。
"""
from __future__ import annotations

import abc
import datetime as dt
import hashlib
import json
import os
import threading
from typing import Any, Dict, List, Optional

from loguru import logger


class DataSource(abc.ABC):
    """数据源适配器抽象基类。

    所有方法返回**不复权**原始日 K（复权由 ``sources/adjust.py`` 统一处理）。
    """

    name: str = "base"
    priority: int = 99

    @abc.abstractmethod
    def fetch_daily_bars(
        self, code: str, start: dt.date, end: dt.date
    ) -> List[Dict[str, Any]]:
        """拉取单标的日 K（不复权），返回 dict 列表。

        每行字段：code, date, open, high, low, close, pre_close, vol, amount
        """

    def fetch_realtime(self, codes: List[str]) -> List[Dict[str, Any]]:
        """盘后/盘中快照（PE/PB/市值/涨跌停价等），默认返回空。"""
        return []

    def fetch_fundamentals(self, code: str) -> Dict[str, Any]:
        """基本面快照（F10/财报），默认返回空。"""
        return {}

    def health_check(self) -> bool:
        """数据源可用性探测，默认 True。"""
        return True

    # ---- 工具：归一化为统一 schema ----
    @staticmethod
    def normalize_row(code: str, row: Dict[str, Any]) -> Dict[str, Any]:
        """把异构返回归一化为标准日 K 行（不含复权列）。"""
        return {
            "code": code,
            "date": row.get("date"),
            "open": float(row.get("open", 0.0) or 0.0),
            "high": float(row.get("high", 0.0) or 0.0),
            "low": float(row.get("low", 0.0) or 0.0),
            "close": float(row.get("close", 0.0) or 0.0),
            "pre_close": float(row.get("pre_close", 0.0) or 0.0),
            "vol": float(row.get("vol", 0.0) or 0.0),
            "amount": float(row.get("amount", 0.0) or 0.0),
        }


class DataSourceRouter:
    """多源路由：按优先级尝试，失败降级；多源差异校验。"""

    def __init__(
        self,
        sources: List[DataSource],
        diff_threshold: float = 0.03,
        cache_raw: bool = True,
        cache_dir: str = "./data/raw_cache",
        source_timeout: float = 20.0,
        divergence_log: str = "./data/divergence_log.jsonl",
    ) -> None:
        self.sources = sorted(sources, key=lambda s: s.priority)
        self.diff_threshold = diff_threshold
        self.cache_raw = cache_raw
        self.cache_dir = cache_dir
        self.source_timeout = source_timeout
        self.divergence_log = divergence_log
        self._div_lock = threading.Lock()
        if self.cache_raw:
            os.makedirs(self.cache_dir, exist_ok=True)

    def fetch(
        self, code: str, start: dt.date, end: dt.date
    ) -> List[Dict[str, Any]]:
        """按优先级拉取；返回首个成功的源结果，并做多源交叉校验。

        每个源的 ``health_check`` / ``fetch_daily_bars`` 均经 ``_call`` 套上
        ``source_timeout`` 超时护栏：单源挂死（如 baostock.login 在网络受限环境
        阻塞）不会拖垮整条 ingest，超时被当作该源不可用并自动降级到下一冗余源。
        """
        last_err: Optional[Exception] = None
        primary: Optional[List[Dict[str, Any]]] = None
        primary_src = ""
        for src in self.sources:
            healthy = self._call(src.health_check, f"{src.name}.health")
            if healthy is not True:
                continue
            rows = self._call(
                lambda s=src: s.fetch_daily_bars(code, start, end),
                f"{src.name}.fetch",
            )
            if rows is None:
                last_err = RuntimeError(f"{src.name} 返回空或超时")
                continue
            if rows:
                if self.cache_raw:
                    self._cache(code, src.name, rows)
                if primary is None:
                    primary, primary_src = rows, src.name
                else:
                    self._cross_check(primary, rows, primary_src, src.name)
        if primary is None:
            raise RuntimeError(
                f"所有数据源均不可用（{code}）：{last_err}"
            ) from last_err
        for r in primary:
            r["source"] = primary_src
        return primary

    def _call(self, fn, label: str):
        """带超时的源调用（daemon 线程 + join 超时），避免单源挂死阻塞整条流水线。

        超时或异常均返回 ``None``，由 ``fetch`` 视为该源不可用并降级；
        daemon 线程保证挂死源不阻塞进程退出。
        """
        box: List[Any] = [None]
        err: List[Any] = [None]

        def _run() -> None:
            try:
                box[0] = fn()
            except Exception as exc:  # noqa: BLE001
                err[0] = exc

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(self.source_timeout)
        if t.is_alive():
            logger.warning(f"源调用超时（>{self.source_timeout}s）：{label}")
            return None
        if err[0] is not None:
            logger.warning(f"源调用异常：{label}：{err[0]}")
            return None
        return box[0]

    def _cross_check(
        self,
        a: List[Dict[str, Any]],
        b: List[Dict[str, Any]],
        sa: str,
        sb: str,
    ) -> None:
        """多源同标的收盘差异校验，超阈值告警并标记可疑。"""
        try:
            map_b = {str(r["date"]): r for r in b}
            for r in a:
                rb = map_b.get(str(r["date"]))
                if not rb:
                    continue
                ca, cb = float(r.get("close", 0) or 0), float(rb.get("close", 0) or 0)
                if ca <= 0 or cb <= 0:
                    continue
                if abs(ca - cb) / ca > self.diff_threshold:
                    rec = self._record_divergence(
                        code=str(r.get("code", "")),
                        date=str(r.get("date", "")),
                        sa=sa,
                        sb=sb,
                        ca=ca,
                        cb=cb,
                    )
                    logger.warning(
                        f"多源差异超阈值 {self.diff_threshold}："
                        f"{r['code']} {r['date']} {sa}={ca} vs {sb}={cb} "
                        f"(记录于 {rec})"
                    )
                    r["source"] = f"{r.get('source', sa)}_suspect"
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"交叉校验跳过：{exc}")

    def _record_divergence(
        self,
        code: str,
        date: str,
        sa: str,
        sb: str,
        ca: float,
        cb: float,
    ) -> str:
        """把一次超阈值多源差异写成结构化 JSONL 记录，供监控/告警消费。

        返回写入的文件路径；写失败仅记 debug 不影响主流程。
        """
        record = {
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "code": code,
            "date": date,
            "source_a": sa,
            "source_b": sb,
            "price_a": ca,
            "price_b": cb,
            "diff": abs(ca - cb) / ca if ca else 0.0,
            "threshold": self.diff_threshold,
        }
        path = self.divergence_log
        with self._div_lock:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"分歧记录写盘失败：{exc}")
        return path

    def _cache(self, code: str, src_name: str, rows: List[Dict[str, Any]]) -> None:
        try:
            digest = hashlib.md5(code.encode()).hexdigest()[:8]
            path = os.path.join(self.cache_dir, f"{src_name}_{digest}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {"source": src_name, "code": code, "rows": rows},
                    f,
                    ensure_ascii=False,
                    default=str,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"原始缓存失败：{exc}")


class InMemoryDataSource(DataSource):
    """内存假数据源，用于测试 / 冒烟（零网络，返回合成日 K）。"""

    name = "memory"
    priority = 0

    def __init__(self, data: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> None:
        # data: code -> list of raw rows (不复权)
        self._data = data or {}

    def add(self, code: str, rows: List[Dict[str, Any]]) -> None:
        self._data[code] = rows

    def fetch_daily_bars(
        self, code: str, start: dt.date, end: dt.date
    ) -> List[Dict[str, Any]]:
        rows = self._data.get(code, [])
        return [
            r for r in rows if start <= _as_date(r["date"]) <= end
        ]

    def health_check(self) -> bool:
        return True


def _as_date(v: Any) -> dt.date:
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        return v
    return dt.date.fromisoformat(str(v)[:10])
