"""仓储层：行情 / 因子 / 信号 / 简报 / 回测 CRUD。

路由：``daily_bars`` / ``universe`` 落行情库；其余落分析库（架构 §2）。
所有写操作按主键 upsert，保证日频重跑幂等。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import pandas as pd

from storage.duckdb_client import DuckDBClient

# 行情库表
_MARKET_TABLES = {"daily_bars", "universe"}
# 分析库表
_ANALYTICS_TABLES = {
    "factor_values",
    "factor_health",
    "signals",
    "sector_rotation",
    "predict_values",
    "predict_health",
    "watchlist",
    "daily_brief",
    "stock_review",
    "backtest_report",
    "sentiment_index",
}


class Repository:
    """统一数据访问层。"""

    def __init__(
        self,
        market: DuckDBClient,
        analytics: Optional[DuckDBClient] = None,
    ) -> None:
        self.market = market
        self.analytics = analytics or market

    # ---- 内部 ------------------------------------------------
    def _client(self, table: str) -> DuckDBClient:
        return self.market if table in _MARKET_TABLES else self.analytics

    def _upsert(self, table: str, df: pd.DataFrame, keys: List[str]) -> int:
        if df is None or len(df) == 0:
            return 0
        return self._client(table).upsert(table, df, keys)

    def _write(self, table: str, df: pd.DataFrame) -> int:
        return self._client(table).write(table, df)

    def _read(self, table: str, sql: str, params=None) -> pd.DataFrame:
        return self._client(table).read(sql, params)

    # ===== 行情 daily_bars =====
    def save_bars(self, df: pd.DataFrame) -> int:
        return self._upsert("daily_bars", df, ["code", "date"])

    def load_bars(
        self,
        codes: Optional[List[str]] = None,
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
    ) -> pd.DataFrame:
        sql = "SELECT * FROM daily_bars WHERE 1=1"
        params: List = []
        if codes:
            if len(codes) == 1:
                sql += " AND code = ?"
                params.append(codes[0])
            else:
                sql += f" AND code IN ({','.join(['?'] * len(codes))})"
                params.extend(codes)
        if start:
            sql += " AND date >= ?"
            params.append(start)
        if end:
            sql += " AND date <= ?"
            params.append(end)
        sql += " ORDER BY code, date"
        return self._read("daily_bars", sql, params)

    # ===== 可投资域 universe =====
    def save_universe(self, df: pd.DataFrame) -> int:
        return self._upsert("universe", df, ["date", "code"])

    def load_universe(
        self, date: dt.date, in_universe: Optional[bool] = True
    ) -> pd.DataFrame:
        sql = "SELECT * FROM universe WHERE date = ?"
        params: List = [date]
        if in_universe is not None:
            sql += " AND in_universe = ?"
            params.append(in_universe)
        return self._read("universe", sql, params)

    # ===== 因子 factor_values (long) =====
    def save_factor_long(self, df: pd.DataFrame) -> int:
        return self._upsert("factor_values", df, ["date", "code", "factor_name"])

    def load_factor_long(
        self, date: Optional[dt.date] = None, codes: Optional[List[str]] = None
    ) -> pd.DataFrame:
        sql = "SELECT * FROM factor_values WHERE 1=1"
        params: List = []
        if date:
            sql += " AND date = ?"
            params.append(date)
        if codes:
            sql += f" AND code IN ({','.join(['?'] * len(codes))})"
            params.extend(codes)
        return self._read("factor_values", sql, params)

    def load_factor_wide(self, date: dt.date) -> pd.DataFrame:
        """透视宽表 (date, code, f1..fn)，便于计算/回测。"""
        long_df = self.load_factor_long(date=date)
        if long_df.empty:
            return pd.DataFrame()
        wide = long_df.pivot_table(
            index=["date", "code"], columns="factor_name", values="value"
        ).reset_index()
        return wide

    # ===== 因子体检 factor_health =====
    def save_health(self, df: pd.DataFrame) -> int:
        return self._upsert("factor_health", df, ["factor_name", "date"])

    def load_health(self, latest: bool = True, date: Optional[dt.date] = None):
        if date:
            return self._read("factor_health", "SELECT * FROM factor_health WHERE date = ?", [date])
        if latest:
            d = self._client("factor_health").execute(
                "SELECT MAX(date) FROM factor_health"
            ).fetchone()[0]
            if d is None:
                return pd.DataFrame()
            return self._read("factor_health", "SELECT * FROM factor_health WHERE date = ?", [d])
        return self._read("factor_health", "SELECT * FROM factor_health")

    # ===== 信号 signals =====
    def save_signals(self, df: pd.DataFrame) -> int:
        return self._upsert("signals", df, ["date", "code"])

    def load_signals(self, date: dt.date) -> pd.DataFrame:
        return self._read("signals", "SELECT * FROM signals WHERE date = ?", [date])

    def load_signal_detail(self, date: dt.date, code: str) -> Optional[Dict]:
        """信号拆解下钻（F-11/T11）：四源贡献 + 因子明细 + 预测明细。"""
        sig = self._read(
            "signals",
            "SELECT * FROM signals WHERE date = ? AND code = ?",
            [date, code],
        )
        if sig.empty:
            return None
        base = sig.iloc[0].to_dict()
        # 因子明细（取该 code/date 所有因子值，按 |value| 降序给 top10）
        fv = self.load_factor_long(date=date, codes=[code])
        if not fv.empty:
            fv = fv.copy()
            fv["abs_v"] = fv["value"].abs()
            fv = fv.sort_values("abs_v", ascending=False).head(10)
            base["factor_detail"] = fv[["factor_name", "value"]].to_dict("records")
        # 预测明细
        pv = self._read(
            "predict_values",
            "SELECT * FROM predict_values WHERE date = ? AND code = ?",
            [date, code],
        )
        base["predict_detail"] = pv.to_dict("records") if not pv.empty else []
        return base

    # ===== 板块 sector_rotation =====
    def save_sector(self, df: pd.DataFrame) -> int:
        return self._upsert("sector_rotation", df, ["date", "sector_code"])

    def load_sector(self, date: dt.date) -> pd.DataFrame:
        return self._read("sector_rotation", "SELECT * FROM sector_rotation WHERE date = ?", [date])

    # ===== 预测 predict_values / predict_health =====
    def save_predict(self, df: pd.DataFrame) -> int:
        return self._upsert(
            "predict_values", df, ["code", "date", "model_name", "horizon"]
        )

    def load_predict(self, date: dt.date, codes: Optional[List[str]] = None) -> pd.DataFrame:
        sql = "SELECT * FROM predict_values WHERE date = ?"
        params: List = [date]
        if codes:
            sql += f" AND code IN ({','.join(['?'] * len(codes))})"
            params.extend(codes)
        return self._read("predict_values", sql, params)

    def save_predict_health(self, df: pd.DataFrame) -> int:
        return self._upsert("predict_health", df, ["model_name", "date"])

    def load_predict_health(self, latest: bool = True):
        if latest:
            d = self._client("predict_health").execute(
                "SELECT MAX(date) FROM predict_health"
            ).fetchone()[0]
            if d is None:
                return pd.DataFrame()
            return self._read("predict_health", "SELECT * FROM predict_health WHERE date = ?", [d])
        return self._read("predict_health", "SELECT * FROM predict_health")

    # ===== 简报 daily_brief / stock_review =====
    def save_brief(self, date: dt.date, content: str, temp: int, disclaimer: str) -> int:
        df = pd.DataFrame(
            [
                {
                    "date": date,
                    "content": content,
                    "market_temperature": int(temp),
                    "disclaimer": disclaimer,
                }
            ]
        )
        return self._upsert("daily_brief", df, ["date"])

    def load_brief(self, date: Optional[dt.date] = None) -> pd.DataFrame:
        if date:
            return self._read("daily_brief", "SELECT * FROM daily_brief WHERE date = ?", [date])
        return self._read("daily_brief", "SELECT * FROM daily_brief ORDER BY date DESC")

    def save_review(
        self,
        date: dt.date,
        code: str,
        content: str,
        action: str,
        reason: str,
        confidence: float,
        disclaimer: str,
    ) -> int:
        df = pd.DataFrame(
            [
                {
                    "date": date,
                    "code": code,
                    "content": content,
                    "action": action,
                    "reason": reason,
                    "confidence": float(confidence),
                    "disclaimer": disclaimer,
                }
            ]
        )
        return self._upsert("stock_review", df, ["date", "code"])

    def load_review(self, date: dt.date, code: Optional[str] = None) -> pd.DataFrame:
        if code:
            return self._read(
                "stock_review",
                "SELECT * FROM stock_review WHERE date = ? AND code = ?",
                [date, code],
            )
        return self._read("stock_review", "SELECT * FROM stock_review WHERE date = ?", [date])

    # ===== 自选股 watchlist =====
    def upsert_watch(
        self, code: str, name: str, cost_price: float, shares: float
    ) -> int:
        df = pd.DataFrame(
            [
                {
                    "code": code,
                    "name": name,
                    "cost_price": float(cost_price),
                    "shares": float(shares),
                    "created_at": dt.datetime.now(),
                }
            ]
        )
        return self._upsert("watchlist", df, ["code"])

    def list_watch(self) -> pd.DataFrame:
        return self._read("watchlist", "SELECT * FROM watchlist ORDER BY code")

    def load_watch_codes(self) -> List[str]:
        df = self.list_watch()
        return df["code"].tolist() if not df.empty else []

    def delete_watch(self, code: str) -> int:
        self.analytics.execute("DELETE FROM watchlist WHERE code = ?", [code])
        return 1

    # ===== 回测 backtest_report =====
    def save_backtest(self, df: pd.DataFrame) -> int:
        return self._upsert(
            "backtest_report", df, ["date", "strategy", "metric_name"]
        )

    def load_backtest(self, strategy: Optional[str] = None) -> pd.DataFrame:
        if strategy:
            return self._read(
                "backtest_report", "SELECT * FROM backtest_report WHERE strategy = ?", [strategy]
            )
        return self._read("backtest_report", "SELECT * FROM backtest_report")

    # ===== 市场情绪指数 sentiment_index =====
    def save_sentiment_index(self, df: pd.DataFrame) -> int:
        """落库单日市场情绪综合指数（一行一日期，按 date upsert）。"""
        return self._upsert("sentiment_index", df, ["date"])

    def load_sentiment_index(
        self, date: Optional[dt.date] = None, latest: bool = True
    ) -> pd.DataFrame:
        if date:
            return self._read(
                "sentiment_index", "SELECT * FROM sentiment_index WHERE date = ?", [date]
            )
        if latest:
            d = self._client("sentiment_index").execute(
                "SELECT MAX(date) FROM sentiment_index"
            ).fetchone()[0]
            if d is None:
                return pd.DataFrame()
            return self._read(
                "sentiment_index", "SELECT * FROM sentiment_index WHERE date = ?", [d]
            )
        return self._read("sentiment_index", "SELECT * FROM sentiment_index ORDER BY date")
