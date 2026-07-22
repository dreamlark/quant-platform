"""股票池（全量候选主表 + 用户自选子集）管理端点。

设计要点：
- ``stock_pool`` 是**全量候选主表**（来自内置源 / 导入 / 手动），``selected`` 标记用户
  当前运行的子集；管线（admin._build_orch）优先用 selected 子集，为空时回退沪深300。
- ``build`` 从内置源（akshare 沪深A + 北交所）拉全量，后台执行，保留已有 selected。
- ``select``/``deselect`` 支持按 codes / 预设（all/none/hs300/创业板/科创板/沪主板/深主板）
  / 行业 选定子集。
- 仅写 stock_pool，不触碰行情/分析库；日期列转字符串兼容 JSON。
"""
from __future__ import annotations

import datetime as dt
import threading
from typing import Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.database import get_repository  # noqa: E402
from loguru import logger  # noqa: E402

router = APIRouter(prefix="/api/pool", tags=["pool"])

_PAGE_SIZE = 200

# 代码前缀预设（创业板/科创板/沪主板/深主板）
PREFIX_PRESETS: Dict[str, tuple] = {
    "cyb": ("300", "301"),       # 创业板
    "kcb": ("688",),             # 科创板
    "sh_main": ("600", "601", "603", "605"),
    "sz_main": ("000", "001"),
}

# 复用 api.database 的单例 Repository（与 master 全进程共用同一 DuckDB 连接，
# 避免重复打开同一库文件触发 DuckDB 单写者约束冲突）
_repo = None


def _get_repo():
    global _repo
    if _repo is None:
        _repo = get_repository()
    return _repo


def _cell(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat() if isinstance(v, dt.datetime) else str(v)
    return v


# —— 构建（后台）状态 ——
_build_state: Dict = {
    "status": "idle",   # idle | running | success | failed
    "message": "",
    "count": None,
    "updated_at": None,
}
_build_lock = threading.Lock()


class PoolSelectBody(BaseModel):
    preset: Optional[str] = None          # all / none / hs300 / cyb / kcb / sh_main / sz_main
    codes: Optional[List[str]] = None     # 显式代码列表（6 位）
    industry: Optional[str] = None        # 按申万一级行业


class PoolAddBody(BaseModel):
    code: str
    name: Optional[str] = None
    industry: Optional[str] = None
    exchange: Optional[str] = None


def _resolve_codes(repo, body: PoolSelectBody) -> List[str]:
    """把 select/deselect 请求解析为具体代码列表（空列表=全部，供 deselect 用）。"""
    if body.codes:
        return [str(c).strip().zfill(6) for c in body.codes if str(c).strip()]
    preset = body.preset
    if preset in (None, "none"):
        # none：用于 deselect=全部；select 时视为非法
        return []
    if preset == "all":
        return [str(c) for c in repo.market.read("SELECT code FROM stock_pool").iloc[:, 0].tolist()]
    if preset == "hs300":
        import akshare as ak

        df = ak.index_stock_cons_csindex(symbol="000300")[["成分券代码"]]
        return [str(c).zfill(6) for c in df["成分券代码"].astype(str).tolist()]
    if preset in PREFIX_PRESETS:
        prefixes = PREFIX_PRESETS[preset]
        all_codes = repo.market.read("SELECT code FROM stock_pool").iloc[:, 0].tolist()
        return [str(c) for c in all_codes if str(c).startswith(prefixes)]
    if body.industry:
        df = repo.market.read(
            "SELECT code FROM stock_pool WHERE industry = ?", [body.industry]
        )
        return [str(c) for c in df.iloc[:, 0].tolist()]
    return []


def _build_worker() -> None:
    global _build_state
    _build_state["status"] = "running"
    _build_state["message"] = "正在从内置源拉取全量 A 股列表..."
    try:
        from sources.market_meta import fetch_all_a_codes

        df = fetch_all_a_codes()
        df["source"] = "akshare"
        df["delisted"] = False

        repo = _get_repo()
        # 保留已有 selected / created_at，避免重建覆盖用户子集选择
        existing = repo.market.read("SELECT code, selected, created_at FROM stock_pool")
        sel_map = dict(zip(existing["code"], existing["selected"])) if not existing.empty else {}
        cre_map = dict(zip(existing["code"], existing["created_at"])) if not existing.empty else {}
        now = dt.datetime.now()
        df["selected"] = df["code"].map(lambda c: bool(sel_map.get(c, False)))
        df["created_at"] = df["code"].map(lambda c: cre_map.get(c, now))
        df["updated_at"] = now

        n = repo.save_pool(df)
        _build_state["status"] = "success"
        _build_state["message"] = f"股票池已构建/更新，共 {n} 只（selected 标记已保留）"
        _build_state["count"] = int(n)
        logger.info(_build_state["message"])
    except Exception as exc:  # noqa: BLE001
        _build_state["status"] = "failed"
        _build_state["message"] = f"{type(exc).__name__}: {exc}"
        logger.error(f"股票池构建失败：{exc}")
    finally:
        _build_state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")


@router.get("/list")
def list_pool(
    selected: Optional[bool] = Query(None, description="仅返回 selected 子集"),
    query: Optional[str] = Query(None, description="按 code/name 模糊搜索"),
    limit: int = Query(_PAGE_SIZE, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """列出股票池（分页 + 筛选）。返回 rows / total / selected_total。"""
    repo = _get_repo()
    df = repo.load_pool(selected=selected, query=query, limit=limit, offset=offset)
    rows = df.to_dict("records") if not df.empty else []
    clean = [{k: _cell(v) for k, v in r.items()} for r in rows]
    return {
        "rows": clean,
        "total": repo.count_pool(),
        "selected_total": repo.count_pool(selected=True),
        "limit": limit,
        "offset": offset,
    }


@router.get("/build/status")
def build_status():
    """构建任务状态。"""
    return _build_state


@router.post("/build")
def build_pool():
    """从内置源（akshare 沪深A + 北交所）构建全量股票池（后台；保留已有 selected）。"""
    with _build_lock:
        if _build_state["status"] == "running":
            raise HTTPException(status_code=409, detail="构建任务正在进行中，请稍候")
        _build_state["status"] = "running"
        threading.Thread(target=_build_worker, daemon=True).start()
    return {"status": "running", "message": "已触发股票池构建"}


@router.post("/select")
def select_pool(body: PoolSelectBody):
    """选定子集：按 codes / 预设 / 行业 将 selected 置 TRUE。"""
    repo = _get_repo()
    codes = _resolve_codes(repo, body)
    if not codes:
        raise HTTPException(status_code=400, detail="未解析到任何股票（请指定 codes / preset / industry）")
    n = repo.set_pool_selected(codes, True)
    return {"selected": n}


@router.post("/deselect")
def deselect_pool(body: PoolSelectBody):
    """取消选定：按 codes / 预设 / 行业 将 selected 置 FALSE；preset=none 取消全部。"""
    repo = _get_repo()
    codes = _resolve_codes(repo, body)
    if not codes:
        # none 或空 → 取消全部
        n = repo.set_pool_selected(
            [str(c) for c in repo.market.read("SELECT code FROM stock_pool").iloc[:, 0].tolist()],
            False,
        )
        return {"deselected": n}
    n = repo.set_pool_selected(codes, False)
    return {"deselected": n}


@router.post("/add")
def add_pool(body: PoolAddBody):
    """手动新增单只股票到池（扩展用）。selected 默认 False。"""
    code = body.code.strip().zfill(6)
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(status_code=400, detail=f"非法代码：{body.code}")
    name = (body.name or code).strip()
    ex = body.exchange or ("sh" if code.startswith("6") else "bj" if code.startswith(("8", "4")) else "sz")
    now = dt.datetime.now()
    df = pd.DataFrame([{
        "code": code,
        "name": name,
        "industry": body.industry or "",
        "exchange": ex,
        "list_date": None,
        "delisted": False,
        "source": "manual",
        "selected": False,
        "created_at": now,
        "updated_at": now,
    }])
    repo = _get_repo()
    n = repo.save_pool(df)
    return {"added": n, "code": code}
