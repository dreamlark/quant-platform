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

    def load_signals_all(self) -> pd.DataFrame:
        """加载全量信号（跨日期，用于 regime 调节样本外验证等历史回测）。"""
        return self._read("signals", "SELECT * FROM signals ORDER BY date")

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
        # 走包装后的 execute 必须消费结果集以释放连接锁（P3-audit 并发修复）
        self.analytics.execute("DELETE FROM watchlist WHERE code = ?", [code]).fetchall()
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

    # ===== 热点信号 hotspot_signals =====
    def save_hotspot_signals(self, df: pd.DataFrame) -> int:
        """落库热点信号（按 ts+source+title upsert）。"""
        return self._upsert("hotspot_signals", df, ["ts", "source", "title"])

    def load_hotspot_signals(
        self,
        date: Optional[dt.date] = None,
        code: Optional[str] = None,
        sector: Optional[str] = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        """查询热点信号。"""
        sql = "SELECT * FROM hotspot_signals WHERE 1=1"
        params: List = []
        if date:
            sql += " AND CAST(ts AS DATE) = ?"
            params.append(date)
        if code:
            sql += " AND related_codes LIKE ?"
            params.append(f"%{code}%")
        if sector:
            sql += " AND related_sectors LIKE ?"
            params.append(f"%{sector}%")
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        return self._read("hotspot_signals", sql, params)

    def load_hotspot_by_date(self, date: dt.date) -> pd.DataFrame:
        """加载指定日期全部热点信号。"""
        return self.load_hotspot_signals(date=date, limit=10000)

    # ===== 热点摘要 hotspot_digest =====
    def save_hotspot_digest(
        self,
        date: dt.date,
        content: str,
        total_count: int,
        positive: int,
        negative: int,
        neutral: int,
    ) -> int:
        df = pd.DataFrame(
            [
                {
                    "date": date,
                    "content": content,
                    "total_count": int(total_count),
                    "positive": int(positive),
                    "negative": int(negative),
                    "neutral": int(neutral),
                }
            ]
        )
        return self._upsert("hotspot_digest", df, ["date"])

    def load_hotspot_digest(self, date: Optional[dt.date] = None) -> pd.DataFrame:
        if date:
            return self._read(
                "hotspot_digest", "SELECT * FROM hotspot_digest WHERE date = ?", [date]
            )
        return self._read(
            "hotspot_digest", "SELECT * FROM hotspot_digest ORDER BY date DESC LIMIT 30"
        )

    def load_sentiment_index_before(self, target_date: dt.date) -> pd.DataFrame:
        """读取严格早于 target_date 的最新一条市场情绪指数（point-in-time T-1）。

        供融合层 regime 调节使用：当日情绪指数在 step_market_sentiment 之后才落库，
        故必须排除当日，严格取 T-1，避免重跑 fusion 时误读当日 regime（P1-2 边界）。
        """
        try:
            d = self.analytics.execute(
                "SELECT MAX(date) FROM sentiment_index WHERE date < ?", [target_date]
            ).fetchone()[0]
            if d is None:
                return pd.DataFrame()
            return self._read(
                "sentiment_index", "SELECT * FROM sentiment_index WHERE date = ?", [d]
            )
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    # ===== 监控聚合（只读，供运维监控层） =====
    # 说明：替代 api/routers/monitor.py 直连 DuckDB 的临时 SQL，统一走仓储层，
    # 保证 schema 演进时与 Repository 同步（P2-1 边界治理）。

    def data_freshness(self, stale_days: int = 4) -> Dict:
        """行情库新鲜度：最新交易日 / 距今天数 / 是否过期 / 标的覆盖 / 可投资域数量。"""
        try:
            row = self.market.execute(
                "SELECT max(date), count(distinct code) FROM daily_bars"
            ).fetchone()
            latest, n_codes = row[0], row[1]
            u = self.market.execute(
                "SELECT count(*) FROM universe WHERE in_universe=TRUE "
                "AND date=(SELECT max(date) FROM universe)"
            ).fetchone()[0]
            days_since = (dt.date.today() - latest).days if latest else None
            is_stale = bool(days_since is not None and days_since > stale_days)
            return {
                "latest_date": str(latest) if latest else None,
                "days_since": days_since,
                "is_stale": is_stale,
                "stock_count": n_codes,
                "universe_count": int(u) if u is not None else 0,
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}

    def factor_health_summary(self) -> Dict:
        """因子体检摘要：最新日、总量、按状态分布、平均 ICIR。"""
        try:
            d = self.analytics.execute("SELECT max(date) FROM factor_health").fetchone()[0]
            if not d:
                return {"latest_date": None, "total": 0, "by_status": {}, "avg_icir": None}
            rows = self.analytics.execute(
                "SELECT status, count(*) FROM factor_health WHERE date=? GROUP BY status", [d]
            ).fetchall()
            avg = self.analytics.execute(
                "SELECT avg(icir) FROM factor_health WHERE date=?", [d]
            ).fetchone()[0]
            by_status = {s: int(c) for s, c in rows}
            return {
                "latest_date": str(d),
                "total": sum(by_status.values()),
                "by_status": by_status,
                "avg_icir": round(float(avg), 4) if avg is not None else None,
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}

    def model_status_summary(self) -> List[Dict]:
        """各预测模型状态：最新日、dir_acc、mape、覆盖率。"""
        try:
            ph = self.analytics.execute(
                "SELECT model_name, max(date) FROM predict_health GROUP BY model_name"
            ).fetchall()
            out: List[Dict] = []
            for name, d in ph:
                acc, mape = self.analytics.execute(
                    "SELECT dir_acc, mape FROM predict_health WHERE model_name=? AND date=?",
                    [name, d],
                ).fetchone()
                cov = self.analytics.execute(
                    "SELECT count(distinct code) FROM predict_values "
                    "WHERE model_name=? AND date=?",
                    [name, d],
                ).fetchone()[0]
                out.append(
                    {
                        "model_name": name,
                        "date": str(d),
                        "dir_acc": round(float(acc), 4) if acc is not None else None,
                        "mape": round(float(mape), 4) if mape is not None else None,
                        "coverage_count": int(cov) if cov is not None else 0,
                    }
                )
            return out
        except Exception as exc:  # noqa: BLE001
            return [{"error": f"{type(exc).__name__}: {exc}"}]

    def other_freshness(self) -> Dict:
        """其它结果表新鲜度：signals / sector_rotation / daily_brief 最新日。"""
        try:
            sig = self.analytics.execute("SELECT max(date) FROM signals").fetchone()[0]
            sec = self.analytics.execute("SELECT max(date) FROM sector_rotation").fetchone()[0]
            brf = self.analytics.execute("SELECT max(date) FROM daily_brief").fetchone()[0]
            return {
                "signals_date": str(sig) if sig else None,
                "sector_date": str(sec) if sec else None,
                "brief_date": str(brf) if brf else None,
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}

    def latest_market_sentiment(self) -> Dict:
        """市场级综合情绪指数最新一行（供运维监控层）。

        复用 load_sentiment_index（统一走仓储层），返回 dict 含 available 标记，
        不再在 API 层直连 DuckDB 拼 SELECT *。
        """
        try:
            df = self.load_sentiment_index(latest=True)
            if df is None or df.empty:
                return {"latest_date": None, "available": False}
            rec = df.iloc[0].to_dict()
            rec["latest_date"] = str(rec["date"]) if "date" in rec else None
            rec["available"] = True
            return rec
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}