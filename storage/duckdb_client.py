"""DuckDB 连接 / 读写 / upsert 封装。

设计要点：
- 单一连接封装，建表幂等（见 ``storage.schema``）。
- ``write`` 追加；``upsert`` 按主键删除后插入，保证日频重跑幂等。
- 日期列做 datetime <-> python date 适配，屏蔽 pandas 3.0 与 DuckDB DATE 的差异。
- 不引入任何重型依赖，核心流水线可在沙箱直接跑通。
"""
from __future__ import annotations

import datetime as dt
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
            elif isinstance(series.iloc[0] if len(series) else None, str):
                df[col] = pd.to_datetime(series).dt.date
    return df


def _read_dates(df: pd.DataFrame) -> pd.DataFrame:
    """读取后把 date/created_at 从 datetime 转回 python date，便于 JSON 序列化。"""
    df = df.copy()
    for col in df.columns:
        if col in _DATE_SET and pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.date
    return df


class DuckDBClient:
    """轻量 DuckDB 客户端。"""

    def __init__(self, path: str = ":memory:", read_only: bool = False) -> None:
        self.path = path
        self.con = duckdb.connect(path, read_only=read_only)
        if not read_only:
            init_schema(self)

    # ---- 低级接口 -------------------------------------------------
    def execute(self, sql: str, params: Optional[Sequence] = None):
        return self.con.execute(sql, params or [])

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass

    # ---- 高级接口 -------------------------------------------------
    def read(self, sql: str, params: Optional[Sequence] = None) -> pd.DataFrame:
        """执行查询并返回 DataFrame（日期列做 date 适配）。"""
        df = self.con.execute(sql, params or []).df()
        return _read_dates(df)

    def read_all(self, table: str) -> pd.DataFrame:
        return self.read(f"SELECT * FROM {table}")

    def write(self, table: str, df: pd.DataFrame) -> int:
        """追加写入（不查重）。返回写入行数。"""
        if df is None or len(df) == 0:
            return 0
        tmp = _coerce_dates(df)
        cols = ", ".join(f'"{c}"' for c in tmp.columns)
        self.con.register("__tmp_write", tmp)
        try:
            self.con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM __tmp_write")
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
        try:
            self.con.execute(f"SELECT 1 FROM {table} LIMIT 1")
            return True
        except Exception:
            return False

    def count(self, table: str) -> int:
        if not self.table_exists(table):
            return 0
        return int(self.con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
