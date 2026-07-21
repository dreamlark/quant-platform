"""系统设置端点：LLM Token / 主题 / 数据路径 / 调度等运行时配置读写。

设计要点：
- 读取：直接返回 settings.yaml 的安全子集（脱敏 API Key）
- 保存：合并补丁到 settings.yaml，热重载到内存单例
- LLM Key 测试：发送一条简单 chat 请求验证连通性
- 主题/前端偏好：独立 localStorage 即可，但统一通过此 API 持久化到 yaml
"""
from __future__ import annotations

import os
import sys
import datetime as dt
from typing import Any, Dict, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.config import load_settings, resolve_path, _DEFAULT_SETTINGS  # noqa: E402

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---- 请求模型 ----
class LLMSettings(BaseModel):
    provider: Optional[str] = None        # deepseek / openai / custom
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None         # 明文传入，后端写入环境变量 + yaml
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    cache_enabled: Optional[bool] = None


class PathSettings(BaseModel):
    data_dir: Optional[str] = None
    market_db: Optional[str] = None
    analytics_db: Optional[str] = None
    raw_cache: Optional[str] = None


class SchedulerSettings(BaseModel):
    enabled: Optional[bool] = None
    cron: Optional[str] = None
    timezone: Optional[str] = None


class HotspotSettings(BaseModel):
    enabled: Optional[bool] = None
    batch_size: Optional[int] = None
    daemon_interval: Optional[int] = None
    simhash_threshold: Optional[int] = None


class FusionSettings(BaseModel):
    hotspot_alpha: Optional[float] = None
    regime_adjust_enabled: Optional[bool] = None


class UIPreferences(BaseModel):
    theme: Optional[str] = None           # dark / light / compact
    chart_up_color: Optional[str] = None  # A股红涨绿跌或国际绿涨红跌
    language: Optional[str] = None        # zh / en


class SettingsPatch(BaseModel):
    llm: Optional[LLMSettings] = None
    paths: Optional[PathSettings] = None
    scheduler: Optional[SchedulerSettings] = None
    hotspot: Optional[HotspotSettings] = None
    fusion: Optional[FusionSettings] = None
    ui: Optional[UIPreferences] = None


# ---- 工具函数 ----
def _deep_merge(base: dict, patch: dict) -> dict:
    """递归合并 patch 到 base（patch 覆盖 base）。"""
    for k, v in patch.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _strip_none(d: dict) -> dict:
    """移除 None 值。"""
    return {k: v for k, v in d.items() if v is not None}


def _read_yaml_raw() -> dict:
    with open(_DEFAULT_SETTINGS, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _write_yaml_raw(data: dict) -> None:
    with open(_DEFAULT_SETTINGS, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _mask_key(key: Optional[str]) -> str:
    """API Key 脱敏显示。"""
    if not key:
        return ""
    if len(key) <= 8:
        return key[:2] + "***"
    return key[:4] + "***" + key[-4:]


# ---- 端点 ----
@router.get("")
def get_settings_safe():
    """读取当前设置（API Key 脱敏）。"""
    cfg = load_settings()
    llm_cfg = cfg.get("llm", {})
    api_key_env = llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY")
    actual_key = os.environ.get(api_key_env, "")

    # ui 偏好（持久化在 yaml 的 _ui 段，不在正式配置中）
    ui_cfg = cfg.get("_ui", {})

    return {
        "llm": {
            "provider": llm_cfg.get("provider", "deepseek"),
            "model": llm_cfg.get("model", ""),
            "base_url": llm_cfg.get("base_url", ""),
            "api_key_masked": _mask_key(actual_key),
            "api_key_env": api_key_env,
            "temperature": llm_cfg.get("temperature", 0.3),
            "max_tokens": llm_cfg.get("max_tokens", 2048),
            "cache_enabled": llm_cfg.get("cache_enabled", True),
            "is_configured": bool(actual_key),
        },
        "paths": cfg.get("paths", {}),
        "scheduler": cfg.get("scheduler", {}),
        "hotspot": cfg.get("hotspot", {}),
        "fusion": {
            "hotspot_alpha": cfg.get("fusion", {}).get("hotspot_alpha", 0.3),
            "regime_adjust_enabled": cfg.get("fusion", {}).get("regime_adjust", {}).get("enabled", True),
        },
        "ui": ui_cfg,
        "app": cfg.get("app", {}),
    }


@router.put("")
def update_settings(patch: SettingsPatch):
    """更新设置（合并写入 settings.yaml + 热更新内存）。"""
    raw = _read_yaml_raw()
    changed_sections = []

    if patch.llm:
        llm_patch = _strip_none(patch.llm.model_dump())
        # API Key 特殊处理：写入环境变量，不落盘 yaml（安全）
        if "api_key" in llm_patch and llm_patch["api_key"]:
            key_val = llm_patch.pop("api_key")
            env_var = raw.get("llm", {}).get("api_key_env", "DEEPSEEK_API_KEY")
            os.environ[env_var] = key_val
        if llm_patch:
            raw.setdefault("llm", {})
            _deep_merge(raw["llm"], llm_patch)
            changed_sections.append("llm")

    if patch.paths:
        paths_patch = _strip_none(patch.paths.model_dump())
        if paths_patch:
            raw.setdefault("paths", {})
            _deep_merge(raw["paths"], paths_patch)
            changed_sections.append("paths")

    if patch.scheduler:
        sched_patch = _strip_none(patch.scheduler.model_dump())
        if sched_patch:
            raw.setdefault("scheduler", {})
            _deep_merge(raw["scheduler"], sched_patch)
            changed_sections.append("scheduler")

    if patch.hotspot:
        hp_patch = _strip_none(patch.hotspot.model_dump())
        if hp_patch:
            raw.setdefault("hotspot", {})
            _deep_merge(raw["hotspot"], hp_patch)
            changed_sections.append("hotspot")

    if patch.fusion:
        fusion_patch = _strip_none(patch.fusion.model_dump())
        if fusion_patch:
            raw.setdefault("fusion", {})
            if "hotspot_alpha" in fusion_patch:
                raw["fusion"]["hotspot_alpha"] = fusion_patch["hotspot_alpha"]
            if "regime_adjust_enabled" in fusion_patch:
                raw.setdefault("fusion", {}).setdefault("regime_adjust", {})
                raw["fusion"]["regime_adjust"]["enabled"] = fusion_patch["regime_adjust_enabled"]
            changed_sections.append("fusion")

    if patch.ui:
        ui_patch = _strip_none(patch.ui.model_dump())
        if ui_patch:
            raw["_ui"] = raw.get("_ui", {})
            _deep_merge(raw["_ui"], ui_patch)
            changed_sections.append("ui")

    if changed_sections:
        _write_yaml_raw(raw)
        # 热更新内存单例（重载 settings）
        from api.database import get_settings as _get_settings
        import api.database as _db_mod
        _db_mod._SETTINGS = load_settings()

    return {
        "status": "ok",
        "changed_sections": changed_sections,
        "message": f"已更新 {len(changed_sections)} 个配置段" if changed_sections else "无变更",
    }


@router.post("/llm/test")
def test_llm_connection():
    """测试 LLM 连接（发送一条简单消息验证连通性）。"""
    from llm.client import LLMClient

    settings = load_settings()
    client = LLMClient(settings)

    if not client.is_available:
        return {
            "success": False,
            "message": f"LLM 未配置：环境变量 {settings.get('llm', {}).get('api_key_env', 'DEEPSEEK_API_KEY')} 未设置",
        }

    try:
        import time
        t0 = time.time()
        response = client.chat(
            system="",
            user="请回复'连接成功'四个字。",
            max_tokens=20,
        )
        elapsed = time.time() - t0
        return {
            "success": True,
            "message": f"连接成功，响应：{response[:50]}",
            "latency_ms": round(elapsed * 1000),
            "usage": client.last_usage,
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"连接失败：{type(exc).__name__}: {exc}",
        }


@router.get("/paths/info")
def get_paths_info():
    """获取数据存储路径信息（是否存在、大小）。"""
    cfg = load_settings()
    paths = cfg.get("paths", {})

    result = {}
    for key, rel_path in paths.items():
        abs_path = resolve_path(rel_path)
        info = {
            "configured": rel_path,
            "absolute": abs_path,
            "exists": os.path.exists(abs_path),
        }
        if os.path.isfile(abs_path):
            info["size_mb"] = round(os.path.getsize(abs_path) / 1024 / 1024, 2)
        elif os.path.isdir(abs_path):
            try:
                total = 0
                for dirpath, _, filenames in os.walk(abs_path):
                    for fn in filenames:
                        fp = os.path.join(dirpath, fn)
                        if os.path.isfile(fp):
                            total += os.path.getsize(fp)
                info["size_mb"] = round(total / 1024 / 1024, 2)
            except Exception:
                info["size_mb"] = None
        result[key] = info

    return result


@router.post("/paths/migrate")
def migrate_paths(new_data_dir: str):
    """迁移数据目录（移动 DuckDB 文件 + 更新配置）。

    ⚠️ 危险操作：会移动数据文件，需前端二次确认。
    """
    cfg = load_settings()
    old_paths = cfg.get("paths", {})
    old_data_dir = resolve_path(old_paths.get("data_dir", "./data"))

    new_data_dir_abs = os.path.abspath(new_data_dir)
    os.makedirs(new_data_dir_abs, exist_ok=True)

    moved = []
    for key in ["market_db", "analytics_db", "raw_cache"]:
        old_rel = old_paths.get(key, "")
        if not old_rel:
            continue
        old_abs = resolve_path(old_rel)
        new_abs = os.path.join(new_data_dir_abs, os.path.basename(old_abs))

        if os.path.exists(old_abs) and old_abs != new_abs:
            import shutil
            shutil.move(old_abs, new_abs)
            moved.append({"key": key, "from": old_abs, "to": new_abs})

    # 更新配置
    raw = _read_yaml_raw()
    raw["paths"]["data_dir"] = new_data_dir
    for key in ["market_db", "analytics_db", "raw_cache"]:
        old_rel = old_paths.get(key, "")
        if old_rel:
            raw["paths"][key] = os.path.join(new_data_dir, os.path.basename(old_rel))
    _write_yaml_raw(raw)

    return {
        "status": "ok",
        "moved": moved,
        "new_data_dir": new_data_dir,
        "message": f"已迁移 {len(moved)} 个文件到 {new_data_dir}",
    }
