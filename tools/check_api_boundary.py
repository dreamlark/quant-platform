"""静态检查：API 边界治理（P2-1）。

禁止 ``api/`` 层在请求路径上直接打开 DuckDB 连接（必须经 ``storage.repository``）。
CI 与 pre-commit 调用，命中即非零退出。

用法::

    python tools/check_api_boundary.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "api"

# api 层禁止出现的“直接打开 DB” 模式（边界治理：统一经 Repository）
FORBIDDEN = (
    "duckdb.connect",
    "DuckDBClient(",
)

EXCLUDE = {"__pycache__"}


def main() -> int:
    if not API_DIR.exists():
        print(f"[check_api_boundary] 未找到 {API_DIR}", file=sys.stderr)
        return 0
    hits: list[tuple[Path, int, str]] = []
    for p in sorted(API_DIR.rglob("*.py")):
        if any(part in EXCLUDE for part in p.parts):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if any(bad in line for bad in FORBIDDEN):
                hits.append((p, i, line.strip()))
    if not hits:
        print("[check_api_boundary] OK：api 层无直接打开 DuckDB 连接")
        return 0
    print("[check_api_boundary] 违规：api 层不得直接打开 DuckDB 连接", file=sys.stderr)
    for p, i, line in hits:
        print(f"  {p.relative_to(ROOT)}:{i}: {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
