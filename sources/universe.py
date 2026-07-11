"""可投资域 / 股票池过滤（P0-3，消除生存偏差）。

``UniverseFilter`` 构建标准可投资域快照（``universe`` 表）：
- 剔除 ST / *ST；
- 剔除上市 < ``min_listed_days``（默认 60 交易日）次新；
- 剔除长期停牌（连续停牌 > ``suspend_max_days``）；
- **保留已退市**标注（``delisted=True``）用于回测样本，避免生存偏差。

因子 / 信号 / 回测统一以 ``universe.in_universe = true`` 为作用域（架构 §7.8）。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional

import pandas as pd

from loguru import logger


class UniverseFilter:
    """标准可投资域过滤器。"""

    def __init__(self, cfg: Optional[Dict] = None) -> None:
        cfg = cfg or {}
        u = cfg.get("universe", {})
        self.min_listed_days: int = int(u.get("min_listed_days", 60))
        self.suspend_max_days: int = int(u.get("suspend_max_days", 20))
        self.drop_st: bool = bool(u.get("drop_st", True))
        self.keep_delisted: bool = bool(u.get("keep_delisted", True))

    # ---- 公开方法 -------------------------------------------------
    def build_universe(
        self,
        date: dt.date,
        stock_list: pd.DataFrame,
        bars_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """构建某日可投资域快照。

        Args:
            date: 快照日。
            stock_list: 候选标的，列 ``code`` / ``name`` / ``listed_date``(可选) /
                ``delisted``(可选)。
            bars_df: 当日（及近期）行情，用于停牌检测；为空则跳过停牌检测。

        Returns:
            universe 表结构 DataFrame。
        """
        rows = []
        for _, s in stock_list.iterrows():
            code = str(s["code"])
            name = str(s.get("name", code))
            is_st = self._is_st(name)
            listed_days = self._listed_days(s.get("listed_date"), date)
            delisted = bool(s.get("delisted", False))
            suspended = self._is_suspended(code, bars_df, date)

            in_universe = True
            if self.drop_st and is_st:
                in_universe = False
            if listed_days < self.min_listed_days:
                in_universe = False
            if suspended:
                in_universe = False
            if delisted:
                # 已退市：保留样本但不在可交易域（避免生存偏差）
                in_universe = False

            rows.append(
                {
                    "date": date,
                    "code": code,
                    "name": name,
                    "in_universe": bool(in_universe),
                    "is_st": bool(is_st),
                    "listed_days": int(listed_days),
                    "delisted": bool(delisted),
                }
            )
        result = pd.DataFrame(rows)
        kept = int(result["in_universe"].sum()) if len(result) else 0
        logger.info(
            f"可投资域快照 {date}：候选 {len(result)} 只，入选 {kept} 只"
            f"（剔除ST={int(result['is_st'].sum())}，次新/停牌="
            f"{int((~result['in_universe']).sum() - result['is_st'].sum())}）"
        )
        return result

    @staticmethod
    def stock_list_from_bars(bars_df: pd.DataFrame) -> pd.DataFrame:
        """从行情表推断候选股票列表（无名称/上市日信息时使用）。"""
        codes = bars_df["code"].drop_duplicates().tolist()
        return pd.DataFrame(
            {
                "code": codes,
                "name": codes,
                "listed_date": pd.NaT,
                "delimited": False,
            }
        )

    # ---- 内部判定 -------------------------------------------------
    @staticmethod
    def _is_st(name: str) -> bool:
        n = (name or "").upper().replace("*", "")
        return "ST" in n

    @staticmethod
    def _listed_days(listed_date, date: dt.date) -> int:
        if listed_date is None or pd.isna(listed_date):
            # 未知上市日 -> 视为老股（足够上市天数）
            return 9999
        if isinstance(listed_date, str):
            listed_date = dt.date.fromisoformat(str(listed_date)[:10])
        if isinstance(listed_date, dt.datetime):
            listed_date = listed_date.date()
        # 用工作日近似交易日
        cal = pd.bdate_range(listed_date, date)
        return max(len(cal) - 1, 0)

    def _is_suspended(
        self, code: str, bars_df: Optional[pd.DataFrame], date: dt.date
    ) -> bool:
        if bars_df is None or bars_df.empty:
            return False
        sub = bars_df[bars_df["code"] == code]
        if sub.empty:
            return True
        last = sub["date"].max()
        if isinstance(last, dt.datetime):
            last = last.date()
        gap_cal = (date - last).days
        # 停牌阈值按自然日近似（交易日约为 1.5 倍）
        return gap_cal > self.suspend_max_days * 1.5
