"""API 辅助函数。"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from storage.repository import Repository


def parse_date(s: Optional[str]) -> Optional[dt.date]:
    if not s:
        return None
    return dt.date.fromisoformat(str(s)[:10])


def latest_bar_date(repo: Repository) -> Optional[dt.date]:
    d = repo.market.execute("SELECT MAX(date) FROM daily_bars").fetchone()[0]
    return d.date() if isinstance(d, dt.datetime) else d


def latest_signal_date(repo: Repository) -> Optional[dt.date]:
    d = repo.analytics.execute("SELECT MAX(date) FROM signals").fetchone()[0]
    return d.date() if isinstance(d, dt.datetime) else d


def resolve_date(repo: Repository, s: Optional[str], which: str = "signal") -> dt.date:
    if s:
        return parse_date(s)
    d = latest_signal_date(repo) if which == "signal" else latest_bar_date(repo)
    if d is None:
        d = latest_bar_date(repo)
    if d is None:
        raise ValueError("暂无数据，请先运行调度/跑通数据链路")
    return d
