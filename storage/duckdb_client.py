"""DuckDB 连接 / 读写 / upsert 封装。

设计要点：
- 单一连接封装，建表幂等（见 ``storage.schema``）。
- ``write`` 追加；``upsert`` 按主键删除后插入，保证日频重跑幂等。
- 日期列做 datetime <-> python date 适配，屏蔽 pandas 3.0 与 DuckDB DATE 的差异。
- 不引入任何重型依赖，核心流水线可在沙箱直接跑通。

并发安全（P3-audit 修复）：
- DuckDB 单连接不支持并发结果集；FastAPI 同步端点在线程池并发执行时，
  多请求共享同一连接会游标串扰（``No open result set`` / 列值错位）。
- 因此所有触碰连接的方法串行化到 ``self._lock``；``execute`` 在锁内**急切物化**
  结果（fetchall 成内存列表后立刻释放锁），返回的 ``_Result`` 仅读内存，
  不再持有连接游标。这样「执行 + 取数」整段原子，且即便调用方不 fetch 也不死锁。
"""
from __future__ import annotations

import datetime as dt
import threading
from typing import Iterable, Optional, Sequence

import duckdb
import pandas as pd

from storage.schema import DATE_COLUMNS, init_schema

_DATE_SET = set(DATE_COLUMNS)


def _coerce_dates(df: pd.DataFrame) -> pd.DataFrame:
    """将名为 date/created_at 的列统一转为 python date（对象列），便于 DuckDB DATE。"""
    df = df.copy()
    for col in df.columns:
        if col in _DATE_SET:
            series = df[col]
            if pd.api.types.is_datetime64_any_dtype(series):
                df[col] = series.dt.date
            elif len(series) and isinstance(series.iloc[0], str):
                df[col] = pd.to_datetime(series).dt.date
    return df


def _read_dates(df: pd.DataFrame) -> pd.DataFrame:
    """读取后把 date/created_at 从 datetime 转回 python date，便于 JSON 序列化。"""
    df = df.copy()
    for col in df.columns:
        if col in _DATE_SET and pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.date
    return df


class _Result:
    """连接锁内已物化的结果集（纯内存），对外暴露类游标接口。

    锁在 ``execute`` 返回前已释放，因此后续读取（fetch*/df）不再触碰连接，
    既避免跨请求串扰，也避免「execute 后不 fetch 又 execute」造成的死锁。
    """

    __slots__ = ("_rows", "_columns")

    def __init__(self, rows, columns):
        self._rows = rows
        self._columns = columns

    @property
    def description(self):
        # 兼容 duckdb 的 (name, type, ...) 结构，这里仅提供name
        return [(c,) for c in self._columns]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchmany(self, n: int):
        return self._rows[:n]

    def df(self):
        return pd.DataFrame(self._rows, columns=self._columns)


class DuckDBClient:
    """线程安全的轻量 DuckDB 客户端（连接级串行化，结果急切物化）。"""

    def __init__(self, path: str = ":memory:", read_only: bool = False) -> None:
        self.path = path
        self.con = duckdb.connect(path, read_only=read_only)
        # 串行化单连接的所有访问（DuckDB 连接不支持并发结果集）
        self._lock = threading.Lock()
        if not read_only:
            init_schema(self)

    # ---- 低级接口 -------------------------------------------------
    def execute(self, sql: str, params: Optional[Sequence] = None):
        """执行查询并在锁内急切物化结果；返回内存结果集（不再持有连接游标）。"""
        with self._lock:
            cur = self.con.execute(sql, params or [])
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
        return _Result(rows, cols)

    def close(self) -> None:
        try:
            self._lock.acquire()
            self.con.close()
        finally:
            try:
                self._lock.release()
            except RuntimeError:
                pass

    # ---- 高级接口 -------------------------------------------------
    def read(self, sql: str, params: Optional[Sequence] = None) -> pd.DataFrame:
        """执行查询并返回 DataFrame（日期列做 date 适配）。"""
        df = self.execute(sql, params).df()
        return _read_dates(df)

    def read_all(self, table: str) -> pd.DataFrame:
        return self.read(f"SELECT * FROM {table}")

    def write(self, table: str, df: pd.DataFrame) -> int:
        """追加写入（不查重）。返回写入行数。"""
        if df is None or len(df) == 0:
            return 0
        tmp = _coerce_dates(df)
        cols = ", ".join(f'"{c}"' for c in tmp.columns)
        with self._lock:
            self.con.register("__tmp_write", tmp)
            try:
                self.con.execute(
                    f"INSERT INTO {table} ({cols}) SELECT {cols} FROM __tmp_write"
                )
            finally:
                self.con.unregister("__tmp_write")
        return len(tmp)

    def upsert(self, table: str, df: pd.DataFrame, keys: Sequence[str]) -> int:
        """按 keys 做幂等 upsert：先删后插。返回影响行数（写入行数）。"""
        if df is None or len(df) == 0:
            return 0
        tmp = _coerce_dates(df)
        cols = ", ".join(f'"{c}"' for c in tmp.columns)
        key_cols = ", ".join(keys)
        with self._lock:
            self.con.register("__tmp_upsert", tmp)
            try:
                self.con.execute(
                    f"DELETE FROM {table} WHERE ({key_cols}) IN "
                    f"(SELECT {key_cols} FROM __tmp_upsert)"
                )
                self.con.execute(
                    f"INSERT INTO {table} ({cols}) SELECT {cols} FROM __tmp_upsert"
                )
            finally:
                self.con.unregister("__tmp_upsert")
        return len(tmp)

    def table_exists(self, table: str) -> bool:
        with self._lock:
            try:
                self.con.execute(f"SELECT 1 FROM {table} LIMIT 1")
                return True
            except Exception:
                return False

    def count(self, table: str) -> int:
        if not self.table_exists(table):
            return 0
        with self._lock:
            return int(self.con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
