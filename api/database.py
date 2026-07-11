"""FastAPI 层共享资源：加载配置、构建 Repository（单例）。"""
from __future__ import annotations

from typing import Optional

from common.config import build_repository, load_settings
from storage.repository import Repository

_SETTINGS: Optional[dict] = None
_REPO: Optional[Repository] = None


def get_settings() -> dict:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = load_settings()
    return _SETTINGS


def get_repository() -> Repository:
    global _REPO
    if _REPO is None:
        _REPO, _SETTINGS = build_repository(get_settings())
    return _REPO
