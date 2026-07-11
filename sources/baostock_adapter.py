"""baostock 适配器（冗余源，懒加载）。

⚠️ ``baostock`` 为可选依赖，仅在方法内 try/except 懒加载；未安装时该冗余源降级，
由 router 切换到其他源，不影响核心流水线。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List

from loguru import logger

from sources.base import DataSource


class BaostockAdapter(DataSource):
    """baostock 日 K 冗余源。"""

    name = "baostock"
    priority = 4

    def __init__(self) -> None:
        self._bs = None

    def _login(self):
        if self._bs is not None:
            return self._bs
        try:
            import baostock as bs
        except ImportError as exc:  # 可选依赖未装 -> 降级
            logger.debug("baostock 未安装，冗余源降级")
            raise ImportError("baostock 未安装") from exc
        self._bs = bs
        bs.login()
        return bs

    def fetch_daily_bars(
        self, code: str, start: dt.date, end: dt.date
    ) -> List[Dict[str, Any]]:
        try:
            bs = self._login()
        except ImportError:
            return []
        # baostock 代码形如 sh.600519
        sym = f"{'sh' if code.endswith('.SH') else 'sz'}.{code.split('.')[0]}"
        try:
            rs = bs.query_history_k_data_plus(
                sym,
                "date,open,high,low,close,preclose,volume,amount",
                start_date=start.strftime("%Y-%m-%d"),
                end_date=end.strftime("%Y-%m-%d"),
                frequency="d",
                adjustflag="3",  # 3=不复权
            )
            out: List[Dict[str, Any]] = []
            while (row := rs.next()) is not None:  # type: ignore[assignment]
                out.append(
                    self.normalize_row(
                        code,
                        {
                            "date": row[0],
                            "open": row[1],
                            "high": row[2],
                            "low": row[3],
                            "close": row[4],
                            "pre_close": row[5],
                            "vol": row[6],
                            "amount": row[7],
                        },
                    )
                )
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"baostock 拉取 {code} 失败：{exc}")
            return []

    def health_check(self) -> bool:
        try:
            import baostock  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False
