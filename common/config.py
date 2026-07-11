"""配置加载与存储客户端构建（配置驱动，禁止硬编码密钥）。"""
from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

import yaml

from storage.duckdb_client import DuckDBClient
from storage.repository import Repository

# 仓库根目录（common/ -> 上级）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEFAULT_SETTINGS = os.path.join(ROOT, "config", "settings.yaml")


def load_settings(path: Optional[str] = None) -> Dict:
    """读取 config/settings.yaml，路径相对仓库根解析。"""
    path = path or _DEFAULT_SETTINGS
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_path(p: str) -> str:
    """把配置中的相对路径解析为仓库根下的绝对路径。"""
    if os.path.isabs(p):
        return p
    return os.path.join(ROOT, p)


def build_repository(settings: Optional[Dict] = None) -> Tuple[Repository, Dict]:
    """构建行情库/分析库客户端与 Repository。"""
    settings = settings or load_settings()
    paths = settings.get("paths", {})
    data_dir = resolve_path(paths.get("data_dir", "./data"))
    os.makedirs(data_dir, exist_ok=True)
    market_db = resolve_path(paths.get("market_db", "./data/market.duckdb"))
    analytics_db = resolve_path(paths.get("analytics_db", "./data/analytics.duckdb"))
    market = DuckDBClient(market_db)
    analytics = DuckDBClient(analytics_db)
    repo = Repository(market, analytics)
    return repo, settings
