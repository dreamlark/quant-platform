"""DeepSeek V3 LLM 客户端（OpenAI 兼容，懒加载 + 缓存 + 重试 + 离线降级）。

⚠️ ``openai`` 为运行时依赖（已列入必装），但密钥缺失/不可达时**不阻断流水线**：
返回离线占位文本 + 固定免责声明，保证 analysis-first 平台在无 LLM 时仍可跑通核心链路。

合规红线（P2-4 / P2-5）：LLM 输出定位"研究观点/分析信号"，置信度由信号层传入，
禁止 LLM 自报；所有文本挂固定免责声明（由调用方拼接）。
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, Optional

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential


class LLMClient:
    """LLM 客户端（DeepSeek V3 单模型）。"""

    def __init__(self, cfg: Optional[Dict] = None) -> None:
        cfg = cfg or {}
        self.cfg = cfg.get("llm", {})
        self.api_key_env = self.cfg.get("api_key_env", "DEEPSEEK_API_KEY")
        self.api_key = os.getenv(self.api_key_env, "")
        self.model = self._resolve(self.cfg.get("model", "deepseek-chat"))
        self.base_url = self._resolve(
            self.cfg.get("base_url", "https://api.deepseek.com")
        )
        self.temperature = float(self.cfg.get("temperature", 0.3))
        self.max_tokens = int(self.cfg.get("max_tokens", 2048))
        self.cache_enabled = bool(self.cfg.get("cache_enabled", True))
        self._cache: Dict[str, str] = {}
        self._client = None

    @staticmethod
    def _resolve(val: str) -> str:
        # 支持 ${ENV:default} 占位
        if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
            inner = val[2:-1]
            name, _, default = inner.partition(":")
            return os.getenv(name, default)
        return val

    def _get_client(self):
        if not self.api_key:
            return None
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai 未安装，LLM 降级离线模式")
            return None
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=False,
    )
    def chat(self, system: str, user: str, use_cache: bool = True) -> str:
        """对话；返回 Markdown 文本。无密钥时返回离线占位。"""
        key = self._cache_key(system, user)
        if use_cache and self.cache_enabled and key in self._cache:
            return self._cache[key]

        client = self._get_client()
        if client is None:
            text = self._offline(system, user)
        else:
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                text = resp.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"LLM 调用失败，降级离线：{exc}")
                text = self._offline(system, user)

        if self.cache_enabled:
            self._cache[key] = text
        return text

    def _cache_key(self, system: str, user: str) -> str:
        return hashlib.md5(f"{system}||{user}".encode()).hexdigest()

    @staticmethod
    def _offline(system: str, user: str) -> str:
        """离线占位：明确标注未接入 LLM，便于冒烟/无密钥环境跑通。"""
        return (
            "> ⚠️ 当前环境未配置 LLM API Key（或未联网），以下为离线占位摘要。\n\n"
            f"**上下文摘要**\n\n{user}\n\n"
            "_（接入 DeepSeek V3 后将生成自然语言市场解读；本研究观点不构成投资建议。）_"
        )
