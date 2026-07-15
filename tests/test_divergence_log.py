"""P0-2 多源冗余：超阈值分歧结构化记录（divergence_log）。

验收标准（来自 system_optimization_v1.md → P0-2）：
- 多源同标的收盘差异超 diff_threshold 时，除告警外须写入结构化 JSONL 记录，
  含 code/date/source_a/source_b/price_a/price_b/diff/threshold。
- 差异未超阈值时不写记录。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile

from sources.base import DataSourceRouter, InMemoryDataSource


def _rows(close_map):
    """close_map: date(str) -> close(float)。构造 InMemory 数据源行。"""
    rows = []
    for d, c in close_map.items():
        rows.append(
            {
                "code": "600519.SH",
                "date": dt.date.fromisoformat(d),
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "pre_close": c,
                "vol": 1.0,
                "amount": 1.0,
            }
        )
    return rows


def test_divergence_log_written_on_threshold_breach(tmp_path):
    log_path = str(tmp_path / "divergence_log.jsonl")
    # 源 A 与源 B 在 2023-01-03 收盘差异 10%（远超 0.03）
    a = InMemoryDataSource({"600519.SH": _rows({"2023-01-02": 100.0, "2023-01-03": 100.0})})
    b = InMemoryDataSource({"600519.SH": _rows({"2023-01-02": 100.0, "2023-01-03": 110.0})})
    router = DataSourceRouter(
        [a, b], diff_threshold=0.03, cache_raw=False, divergence_log=log_path
    )
    router.fetch("600519.SH", dt.date(2023, 1, 2), dt.date(2023, 1, 3))

    assert os.path.exists(log_path), "超阈值分歧应写入 divergence_log"
    with open(log_path, encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines) == 1, f"应恰好 1 条分歧记录，得到 {len(lines)}"
    rec = json.loads(lines[0])
    assert rec["code"] == "600519.SH"
    assert rec["date"] == "2023-01-03"
    assert rec["source_a"] == "memory" and rec["source_b"] == "memory"
    assert rec["price_a"] == 100.0 and rec["price_b"] == 110.0
    assert abs(rec["diff"] - 0.1) < 1e-9
    assert rec["threshold"] == 0.03


def test_divergence_log_skipped_when_within_threshold(tmp_path):
    log_path = str(tmp_path / "divergence_log.jsonl")
    a = InMemoryDataSource({"600519.SH": _rows({"2023-01-02": 100.0})})
    b = InMemoryDataSource({"600519.SH": _rows({"2023-01-02": 100.5})})  # 0.5% < 3%
    router = DataSourceRouter(
        [a, b], diff_threshold=0.03, cache_raw=False, divergence_log=log_path
    )
    router.fetch("600519.SH", dt.date(2023, 1, 2), dt.date(2023, 1, 2))

    assert not os.path.exists(log_path), "未超阈值不应写分歧记录"
