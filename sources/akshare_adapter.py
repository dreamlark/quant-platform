"""akshare 日 K 适配器（冗余源：Sina 历史日 K，免密钥、防封）。

环境适配说明（2026-07-10 排查）：
- 本环境 mootdx 通达信服务器多数失效（TCP 7709 连通但 ``bars()`` 返回 0 行，
  ``bestip`` 亦偶发 ``ResponseHeaderRecvFails``）；
- baostock ``login()`` 在本环境挂死（其服务器不可达）。
故以 akshare ``stock_zh_a_daily``（Sina 后端）作为**主历史日 K 源**，落实架构
§7.4 规划的 akshare/baostock 冗余源。该端点在本环境稳定可用（沪深标的 ~0.3s/次，
含最新交易日）。

⚠️ 单位统一：Sina 返回的 ``volume`` 为「股」，而库内既有 mootdx 数据为「手」
（100 股），归一化时 ``vol = volume / 100``，确保 turnover 类因子口径一致。
⚠️ 边界 ``pre_close``：向后多取 ``lookback_pad`` 天再 ``shift(1)``，保证窗口首日的
昨收来自真实前一交易日（复权跳变检测依赖 ``pre_close``）。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from loguru import logger

from sources.base import DataSource


def _as_date(v: Any) -> dt.date:
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        return v
    return dt.date.fromisoformat(str(v)[:10])


class AkshareDailyAdapter(DataSource):
    """akshare Sina 历史日 K 适配器（冗余主源）。"""

    name = "akshare"
    priority = 1

    def __init__(self, retries: int = 2, lookback_pad: int = 15) -> None:
        self.retries = retries
        self.lookback_pad = lookback_pad
        self._ak = None
        self._healthy: Optional[bool] = None  # 健康探测结果缓存（避免每只标的重复网络探测）

    def _get_ak(self):
        if self._ak is None:
            import akshare as ak  # 懒加载（重型依赖）

            self._ak = ak
        return self._ak

    @staticmethod
    def _to_sym(code: str) -> str:
        """沪深代码 -> Sina 符号（sh/sz 前缀 + 6 位）。"""
        c = code.split(".")[0]
        prefix = "sh" if c.startswith("6") or c.startswith("9") else "sz"
        return prefix + c

    def fetch_daily_bars(
        self, code: str, start: dt.date, end: dt.date
    ) -> List[Dict[str, Any]]:
        ak = self._get_ak()
        sym = self._to_sym(code)
        # 向后多取 lookback_pad 天，确保窗口首日的 pre_close 可经 shift 得到
        ext_start = start - dt.timedelta(days=self.lookback_pad)
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                df = ak.stock_zh_a_daily(
                    symbol=sym,
                    start_date=ext_start.strftime("%Y-%m-%d"),
                    end_date=end.strftime("%Y-%m-%d"),
                    adjust="",
                )
                if df is None or len(df) == 0:
                    return []
                df = df.copy()
                df["date"] = df["date"].astype(str).str[:10]
                df = df.sort_values("date").reset_index(drop=True)
                df["pre_close"] = df["close"].shift(1)  # 昨收补齐前收盘
                result: List[Dict[str, Any]] = []
                for r in df.itertuples(index=False):
                    d = _as_date(r.date)
                    if not (start <= d <= end):
                        continue  # 过滤回窗口 [start, end]
                    vol_raw = float(getattr(r, "volume", 0) or 0)
                    result.append(
                        self.normalize_row(
                            code,
                            {
                                "date": d.isoformat(),
                                "open": float(getattr(r, "open", 0.0) or 0.0),
                                "high": float(getattr(r, "high", 0.0) or 0.0),
                                "low": float(getattr(r, "low", 0.0) or 0.0),
                                "close": float(getattr(r, "close", 0.0) or 0.0),
                                "pre_close": float(getattr(r, "pre_close", 0.0) or 0.0),
                                "vol": vol_raw / 100.0,  # 股 -> 手，与库内 mootdx 口径一致
                                "amount": float(getattr(r, "amount", 0.0) or 0.0),
                            },
                        )
                    )
                return result
            except Exception as exc:  # noqa: BLE001 冗余源降级
                last_exc = exc
                logger.warning(f"akshare 拉取 {code}({sym}) 第{attempt + 1}次失败：{exc}")
        logger.warning(f"akshare 拉取 {code} 最终失败：{last_exc}")
        return []

    def health_check(self) -> bool:
        """轻量健康探测：仅首次真正发网络请求，结果缓存复用。"""
        if self._healthy is None:
            try:
                probe = self.fetch_daily_bars(
                    "000001",
                    dt.date.today() - dt.timedelta(days=10),
                    dt.date.today(),
                )
                self._healthy = len(probe) > 0
            except Exception:  # noqa: BLE001
                self._healthy = False
        return bool(self._healthy)
