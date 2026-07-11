"""mootdx / Tencent 适配器（主源，防封，懒加载）。

⚠️ ``mootdx`` 为重型可选依赖，模块顶层**不**无条件 import；仅在方法内
try/except 懒加载。未安装时该源降级（抛 ImportError 由 router 切换冗余源），
不影响其他模块运行。

数据源决策见 ``数据接入_a-stock-data选型决策.md``：抽取 mootdx K 线 + 腾讯实时维度，
直连底层、TCP 7709 永不封 IP。
"""
from __future__ import annotations

import datetime as dt
import socket
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from sources.base import DataSource

# 通达信行情服务器（取自 a-stock-data 决策文档，可扩充）
_TDX_SERVERS: List[Tuple[str, int]] = [
    ("119.97.185.59", 7709),
    ("124.70.133.119", 7709),
    ("203.175.13.50", 7709),
    ("113.105.142.138", 7709),
    ("117.184.140.60", 7709),
]


def _tdx_client(market: str = "std", bestip: bool = True, timeout: float = 3.0):
    """懒加载 mootdx 并选取可用服务器；失败抛 ImportError。"""
    try:
        from mootdx.quotes import Quotes
    except ImportError as exc:  # 重型依赖未装 -> 显式降级
        raise ImportError(
            "mootdx 未安装（可选重型依赖）。可通过 `pip install mootdx` 启用主源；"
            "当前由 akshare/baostock 冗余源承接。"
        ) from exc

    for ip, port in _TDX_SERVERS:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return Quotes.factory(market=market, server=(ip, port))
        except Exception:  # noqa: BLE001
            continue
    if bestip:
        return Quotes.factory(market=market, bestip=True)
    raise ConnectionError("无法连接任意通达信行情服务器")


class MootdxAdapter(DataSource):
    """mootdx 日 K 主源适配器（懒加载 mootdx）。"""

    name = "mootdx"
    priority = 1

    def __init__(
        self,
        market: str = "std",
        bestip: bool = True,
        timeout: float = 3.0,
        offset: int = 800,
    ) -> None:
        self.market = market
        self.bestip = bestip
        self.timeout = timeout
        self.offset = offset
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = _tdx_client(self.market, self.bestip, self.timeout)
        return self._client

    def fetch_daily_bars(
        self, code: str, start: dt.date, end: dt.date
    ) -> List[Dict[str, Any]]:
        client = self._get_client()
        sym = code.split(".")[0]
        try:
            df = client.bars(symbol=sym, frequency=9, offset=self.offset)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"mootdx 拉取 {code} 失败：{exc}")
            return []
        if df is None or len(df) == 0:
            return []
        # mootdx 返回 pandas.DataFrame，列含 open/close/high/low/vol/amount/datetime；
        # 注意：日 K 不含 pre_close，需用昨收（前一日收盘）补齐，除权日有偏差，
        # 因子层统一以后复权 adj_back_close 修正。
        df = df.copy()
        df["date"] = df["datetime"].astype(str).str[:10]
        df = df.sort_values("date").reset_index(drop=True)
        df["pre_close"] = df["close"].shift(1)  # 昨收补齐前收盘
        result: List[Dict[str, Any]] = []
        for r in df.itertuples(index=False):
            result.append(
                self.normalize_row(
                    code,
                    {
                        "date": str(r.date)[:10],
                        "open": getattr(r, "open", 0.0),
                        "high": getattr(r, "high", 0.0),
                        "low": getattr(r, "low", 0.0),
                        "close": getattr(r, "close", 0.0),
                        "pre_close": getattr(r, "pre_close", 0.0) or 0.0,
                        "vol": getattr(r, "vol", 0.0),
                        "amount": getattr(r, "amount", 0.0),
                    },
                )
            )
        # 过滤到 [start, end]
        return [x for x in result if start <= _as_date(x["date"]) <= end]

    def health_check(self) -> bool:
        try:
            self._get_client()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"mootdx 不可用：{exc}")
            return False


class TencentRealtime(DataSource):
    """腾讯实时/收盘快照（HTTP 无封禁，补 PE/PB/市值/涨跌停价）。"""

    name = "tencent"
    priority = 2

    def fetch_realtime(self, codes: List[str]) -> List[Dict[str, Any]]:
        try:
            import requests
        except ImportError:
            logger.debug("requests 未安装，腾讯实时源降级")
            return []
        out: List[Dict[str, Any]] = []
        for code in codes:
            sym = code.replace(".", "")
            try:
                url = f"https://qt.gtimg.cn/q={sym}"
                resp = requests.get(url, timeout=5)
                resp.encoding = "gbk"
                # 解析 qt.gtimg.cn 返回（简单解析，生产可细化）
                text = resp.text
                out.append({"code": code, "raw": text})
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"腾讯实时 {code} 失败：{exc}")
        return out

    def fetch_daily_bars(self, code: str, start: dt.date, end: dt.date):
        # 腾讯实时源不提供历史日 K，由 mootdx/akshare 承接
        return []


def _as_date(v: Any) -> dt.date:
    return dt.date.fromisoformat(str(v)[:10])
