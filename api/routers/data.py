"""通用数据浏览（只读）：列出数据表 + 按表查阅明细。

定位：把「数据管理」页从「展示 + 假按钮」升级为真正的数据操作台的第一步——
先提供「查阅明细」能力（覆盖 market / analytics 两库全部表）。后续可在其上叠加
增量更新 / 单条修改 / 删除等写操作。

安全边界（P2-1 边界治理）：
- 表名走运行时白名单校验（取自 DuckDB ``SHOW TABLES``），不接受任意表名；
- 列过滤仅允许已知维度列（``code`` / ``date``），列名来自库内可信元数据；
- 所有值参数化（``?`` 占位），杜绝 SQL 注入。
"""
from __future__ import annotations

import datetime as dt
import io
import re

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from typing import List, Optional

from api.database import get_repository
from api.serializers import sanitize_obj
from storage.repository import Repository
from storage.schema import TABLE_DDL

router = APIRouter(prefix="/api/data", tags=["data"])


def _table_names(con) -> List[str]:
    """读取某库全部表名（来自 DuckDB SHOW TABLES，可信）。"""
    try:
        df = con.read("SHOW TABLES")
        return [str(v) for v in df.iloc[:, 0].tolist()]
    except Exception:  # noqa: BLE001
        return []


def _columns(con, table: str) -> List[str]:
    """读取某表字段名（取 LIMIT 0 查询的 schema，可信）。"""
    try:
        return [str(c) for c in con.read(f'SELECT * FROM "{table}" LIMIT 0').columns]
    except Exception:  # noqa: BLE001
        return []


def _all_tables(repo: Repository) -> List[dict]:
    """列出 market + analytics 两库所有表元信息（库/表名/行数/字段/最新日期）。"""
    out: List[dict] = []
    for db, probe in (("market", "daily_bars"), ("analytics", "signals")):
        try:
            con = repo._client(probe)
        except Exception:  # noqa: BLE001
            continue
        for t in _table_names(con):
            try:
                cnt = int(con.read(f'SELECT COUNT(*) FROM "{t}"').iloc[0, 0])
            except Exception:  # noqa: BLE001
                cnt = None
            cols = _columns(con, t)
            latest = None
            if "date" in cols:
                try:
                    latest = str(con.read(f'SELECT MAX(date) FROM "{t}"').iloc[0, 0])
                except Exception:  # noqa: BLE001
                    latest = None
            out.append(
                {
                    "db": db,
                    "name": t,
                    "rows": cnt,
                    "columns": cols,
                    "latest_date": latest,
                }
            )
    return out


@router.get("/tables")
def list_tables() -> dict:
    """列出所有数据表元信息（库 / 表名 / 行数 / 字段 / 最新日期）。"""
    return {"tables": _all_tables(get_repository())}


@router.get("/query")
def query_table(
    table: str = Query(..., description="表名（须为已知表，见 /tables）"),
    code: Optional[str] = Query(None, description="按 code 过滤（表需含 code 列）"),
    date: Optional[str] = Query(None, description="按 date 过滤 YYYY-MM-DD（表需含 date 列）"),
    limit: int = Query(200, ge=1, le=2000, description="每页行数"),
    offset: int = Query(0, ge=0, description="偏移量"),
) -> dict:
    """查阅某表明细，支持按 code / date 过滤 + 分页。

    返回列名、行数据（inf/nan 已清洗为 None）、总数与分页参数。
    """
    repo = get_repository()
    allowed = {t["name"] for t in _all_tables(repo)}
    if table not in allowed:
        raise HTTPException(status_code=404, detail=f"未知数据表：{table}")

    con = repo._client(table)
    cols = _columns(con, table)
    wheres: List[str] = []
    params: List[str] = []
    if code is not None and "code" in cols:
        wheres.append("code = ?")
        params.append(code)
    if date is not None and "date" in cols:
        wheres.append("date = ?")
        params.append(date)
    where = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    order = (
        "ORDER BY date DESC"
        if "date" in cols
        else ("ORDER BY code" if "code" in cols else "")
    )

    # 明细（参数化，分页）
    df = con.read(
        f'SELECT * FROM "{table}" {where} {order} LIMIT ? OFFSET ?',
        params + [limit, offset],
    )
    rows = df.to_dict("records") if not df.empty else []
    rows = sanitize_obj(rows)  # inf/nan/numpy 特殊值 → 合法 JSON
    columns = list(df.columns) if not df.empty else cols

    # 总数（同过滤条件，不含分页）
    total = int(con.read(f'SELECT COUNT(*) FROM "{table}" {where}', params).iloc[0, 0])

    return {
        "table": table,
        "columns": columns,
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# 数据导入 / 导出（CSV / Parquet）—— 在「查阅明细」之上叠加真正的写操作
# ---------------------------------------------------------------------------
def _pk_cols(table: str) -> List[str]:
    """从 schema DDL 解析主键列（小写）。"""
    ddl = TABLE_DDL.get(table, "")
    m = re.search(r"PRIMARY\s+KEY\s*\(([^)]+)\)", ddl, re.IGNORECASE)
    if not m:
        return []
    return [c.strip().strip('"').lower() for c in m.group(1).split(",")]


def _prep_parquet(df: pd.DataFrame) -> pd.DataFrame:
    """Parquet 不支持 python date 对象，转为 datetime64。"""
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_object_dtype(df[c]):
            sample = df[c].dropna()
            if len(sample) and isinstance(sample.iloc[0], dt.date):
                df[c] = pd.to_datetime(df[c])
    return df


def _parse_ddl_types(table: str) -> dict:
    """从 schema DDL 解析 列名(小写) -> SQL 类型(大写)。"""
    ddl = TABLE_DDL.get(table, "")
    types: dict = {}
    for line in ddl.splitlines():
        m = re.match(r"\s*([a-zA-Z_]\w*)\s+([A-Za-z]+)", line)
        if not m:
            continue
        name = m.group(1).lower()
        if name in ("primary", "key", "constraint", "unique", "foreign"):
            continue
        types[name] = m.group(2).upper()
    return types


_TRUE_SET = {"true", "1", "yes", "y", "是"}
_FALSE_SET = {"false", "0", "no", "n", "否", ""}


def _to_bool(series: pd.Series) -> pd.Series:
    """宽松布尔化：true/1/yes/是 -> True；false/0/no/否/空 -> False；其余 NA。"""

    def conv(v):
        if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)):
            return pd.NA
        s = str(v).strip().lower()
        if s in _TRUE_SET:
            return True
        if s in _FALSE_SET:
            return False
        return pd.NA

    return series.map(conv).astype("boolean")


def _coerce_to_schema(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """按目标表 DDL 把 DataFrame 列强制成与 DuckDB 列一致的类型。

    - VARCHAR -> pandas 可空字符串（NA 映射为 NULL，绝不变 BIGINT）
    - DATE    -> python date 对象
    - TIMESTAMP -> datetime64
    - BOOLEAN -> 可空布尔
    - DOUBLE/FLOAT -> float64（含 NA 容错）
    - INT/BIGINT  -> Int64（可空整数，保留大数）
    """
    types = _parse_ddl_types(table)
    df = df.copy()
    for col, typ in types.items():
        if col not in df.columns:
            continue
        if typ == "VARCHAR":
            df[col] = df[col].astype("string")
        elif typ == "DATE":
            s = df[col]
            df[col] = (
                s.dt.date
                if pd.api.types.is_datetime64_any_dtype(s)
                else pd.to_datetime(s, errors="coerce").dt.date
            )
        elif typ == "TIMESTAMP":
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif typ == "BOOLEAN":
            df[col] = _to_bool(df[col])
        elif typ in ("DOUBLE", "FLOAT", "REAL"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        elif typ in ("INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


@router.get("/export")
def export_table(
    table: str = Query(..., description="表名（须为已知表，见 /tables）"),
    format: str = Query("csv", description="csv | parquet"),
):
    """导出整表为 CSV / Parquet 文件流（供下载分享）。"""
    repo = get_repository()
    con = repo._client(table)
    if not con.table_exists(table):
        raise HTTPException(status_code=404, detail=f"未知数据表：{table}")
    fmt = format.lower()
    if fmt not in ("csv", "parquet"):
        raise HTTPException(status_code=400, detail="format 仅支持 csv / parquet")

    df = con.read(f'SELECT * FROM "{table}"')
    buf = io.BytesIO()
    if fmt == "parquet":
        _prep_parquet(df).to_parquet(buf, index=False)
        media = "application/octet-stream"
    else:
        df.to_csv(buf, index=False)
        media = "text/csv"
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{table}.{fmt}"'},
    )


@router.post("/import")
async def import_table(
    file: UploadFile = File(...),
    table: str = Form(..., description="目标表名（须为已知表，见 /tables）"),
    mode: str = Form("upsert", description="upsert(幂等) | replace(清空后全量写入)"),
):
    """导入 CSV/Parquet 到指定表（支持 daily_bars / stock_pool / universe 等已知表）。

    - mode=upsert：按主键幂等 upsert（推荐，重复导入不丢已有数据）。
    - mode=replace：先清空该表再全量写入（用于导入完整快照）。
    """
    repo = get_repository()
    con = repo._client(table)
    if not con.table_exists(table):
        raise HTTPException(status_code=404, detail=f"未知数据表：{table}")
    if mode not in ("upsert", "replace"):
        raise HTTPException(status_code=400, detail="mode 仅支持 upsert / replace")

    filename = (file.filename or "").lower()
    content = await file.read()
    try:
        if filename.endswith(".parquet"):
            df = pd.read_parquet(io.BytesIO(content))
        else:
            # 全部按字符串读入，避免数值代码（如 000001）被推断成 int 而丢精度，
            # 也避免 VARCHAR 列被推断成 BIGINT 导致 upsert IN 比较报
            # "Cannot compare values of type VARCHAR and BIGINT"。
            ddl_types = _parse_ddl_types(table)
            str_cols = [
                c for c, t in ddl_types.items()
                if t in ("VARCHAR", "BOOLEAN", "DATE", "TIMESTAMP")
            ]
            dtype = {c: str for c in str_cols} if str_cols else str
            df = pd.read_csv(io.BytesIO(content), dtype=dtype)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"文件解析失败：{exc}")

    # 列名校验：归一小写；主键必须存在；不得含未知列
    df.columns = [str(c).lower() for c in df.columns]
    tbl_cols = [str(c).lower() for c in con.read(
        f'SELECT * FROM "{table}" LIMIT 0'
    ).columns.tolist()]
    pk = _pk_cols(table)
    missing_pk = [c for c in pk if c not in df.columns]
    if missing_pk:
        raise HTTPException(status_code=400, detail=f"缺少主键列：{missing_pk}")
    stray = [c for c in df.columns if c not in tbl_cols]
    if stray:
        raise HTTPException(status_code=400, detail=f"文件含未知列（不在表中）：{stray}")

    # 按目标表 schema 强制类型（关键：VARCHAR 代码列强制为字符串，杜绝 BIGINT 不匹配）
    df = _coerce_to_schema(df, table)

    if mode == "replace":
        con.execute(f'DELETE FROM "{table}"')
        n = con.write(table, df)
    else:
        n = con.upsert(table, df, pk)
    return {"imported": int(n), "table": table, "mode": mode}
