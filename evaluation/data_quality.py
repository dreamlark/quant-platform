"""数据质量不变量检测（P3-3）。

只读 Repository，检测并上报违规，**不做修复**（发现问题归数据管线修复）。覆盖：
- 可投资域排除规则：in_universe=TRUE 中不应含 ST / 已退市。
- 个股无重复 (code, date)。
- 价格正值：open/high/low/close 不应 ≤ 0。
- 无未来日期：daily_bars.date 不应晚于评估日。
- 后复权价无异常跳变：|日收益| 超阈值（默认 0.3，可配置）视为异常。

结果结构：``{check_name: [违规行...]}``，空 dict 表示全部通过。套件可直接入 CI（P2-2）。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List


def _as_of(settings: Dict[str, Any], as_of: dt.date) -> dt.date:
    return as_of or dt.date.today()


def check_universe_exclusions(repo: Any, settings: Dict[str, Any]) -> List[dict]:
    """可投资域（in_universe=TRUE）不应含 ST / 已退市。"""
    try:
        con = repo.analytics
        rows = con.execute(
            "SELECT code, name, is_st, delisted FROM universe WHERE in_universe=TRUE"
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    bad: List[dict] = []
    for code, name, is_st, delisted in rows:
        if is_st:
            bad.append({"code": code, "name": name, "reason": "st_in_universe"})
        if delisted:
            bad.append({"code": code, "name": name, "reason": "delisted_in_universe"})
    return bad


def check_duplicate_dates(repo: Any) -> List[dict]:
    """个股不应有重复 (code, date)。"""
    try:
        con = repo.market
        rows = con.execute(
            "SELECT code, date, count(*) c FROM daily_bars GROUP BY code, date HAVING count(*) > 1"
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [{"code": r[0], "date": str(r[1]), "count": r[2]} for r in rows]


def check_nonpositive_price(repo: Any) -> List[dict]:
    """open/high/low/close 不应 ≤ 0。"""
    try:
        con = repo.market
        rows = con.execute(
            "SELECT code, date, open, high, low, close FROM daily_bars "
            "WHERE open<=0 OR high<=0 OR low<=0 OR close<=0"
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [{"code": r[0], "date": str(r[1]), "close": r[5]} for r in rows]


def check_future_dates(repo: Any, as_of: dt.date) -> List[dict]:
    """daily_bars 不应含晚于评估日的未来日期。"""
    try:
        con = repo.market
        rows = con.execute(
            "SELECT code, date FROM daily_bars WHERE date > ?", [as_of]
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [{"code": r[0], "date": str(r[1])} for r in rows]


def check_adjust_jump(repo: Any, settings: Dict[str, Any], as_of: dt.date) -> List[dict]:
    """后复权价日收益 |ret| 超阈值视为异常跳变（默认 0.3，可在 settings.adjust 配置）。"""
    try:
        th = float((settings.get("adjust", {}) or {}).get("quality_jump_threshold", 0.3))
    except Exception:  # noqa: BLE001
        th = 0.3
    try:
        con = repo.market
        rows = con.execute(
            "SELECT code, date, adj_back_close FROM daily_bars ORDER BY code, date"
        ).fetchall()
    except Exception:  # noqa: BLE001
        return []
    bad: List[dict] = []
    last: Dict[str, float] = {}
    for code, date, p in rows:
        if p is None:
            continue
        prev = last.get(code)
        if prev is not None and prev > 0:
            ret = abs(p / prev - 1.0)
            if ret > th:
                bad.append({"code": code, "date": str(date), "ret": round(ret, 4)})
        last[code] = p
    return bad


def check_data_quality(
    repo: Any, settings: Dict[str, Any], as_of: dt.date
) -> Dict[str, list]:
    """运行全部不变量检测，返回非空违规字典（空 dict = 全部通过）。"""
    results = {
        "universe_exclusions": check_universe_exclusions(repo, settings),
        "duplicate_dates": check_duplicate_dates(repo),
        "nonpositive_price": check_nonpositive_price(repo),
        "future_dates": check_future_dates(repo, as_of),
        "adjust_jump": check_adjust_jump(repo, settings, as_of),
    }
    return {k: v for k, v in results.items() if v}
