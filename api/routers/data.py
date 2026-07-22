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

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from api.database import get_repository
from api.serializers import sanitize_obj
from storage.repository import Repository

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
