"""DeepSeek V3 LLM 客户端（OpenAI 兼容，懒加载 + 缓存 + 重试 + 离线降级）。

⚠️ ``openai`` 为运行时依赖（已列入必装），但密钥缺失/不可达时**不阻断流水线**：
返回离线占位文本 + 固定免责声明，保证 analysis-first 平台在无 LLM 时仍可跑通核心链路。

合规红线（P2-4 / P2-5）：LLM 输出定位"研究观点/分析信号"，置信度由信号层传入，
禁止 LLM 自报；所有文本挂固定免责声明（由调用方拼接）。

H1 增强（2026-07-17）：
- 新增 ``complete()`` 方法：兼容 TextSentiment 旧调用，内部转为 chat()
- 新增 ``chat_json()`` 方法：结构化 JSON 输出（response_format=json_object）
- 新增 ``chat_stream()`` 异步生成器：流式输出（用于 SSE 实时推送）
- 新增 ``last_usage`` 属性：token 用量追踪
- ``max_tokens`` 支持按调用覆盖
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any, AsyncGenerator, Dict, Optional

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
        self._cache_json: Dict[str, dict] = {}
        self._client = None
        self._async_client = None
        # token 用量追踪
        self._last_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._total_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    @property
    def last_usage(self) -> Dict[str, int]:
        """最近一次调用的 token 用量。"""
        return self._last_usage

    @property
    def total_usage(self) -> Dict[str, int]:
        """累计 token 用量。"""
        return self._total_usage

    @property
    def is_available(self) -> bool:
        """LLM 是否可用（有 API Key 且客户端初始化成功）。"""
        return self._get_client() is not None

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

    def _get_async_client(self):
        if not self.api_key:
            return None
        if self._async_client is not None:
            return self._async_client
        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.warning("openai 未安装，LLM 异步模式不可用")
            return None
        self._async_client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._async_client

    def _track_usage(self, usage: Any) -> None:
        """记录 token 用量。"""
        if usage is None:
            return
        self._last_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }
        for k, v in self._last_usage.items():
            self._total_usage[k] = self._total_usage.get(k, 0) + v

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=False,
    )
    def chat(
        self,
        system: str,
        user: str,
        use_cache: bool = True,
        max_tokens: Optional[int] = None,
    ) -> str:
        """对话；返回 Markdown 文本。无密钥时返回离线占位。

        Args:
            system: System prompt
            user: User prompt
            use_cache: 是否使用缓存
            max_tokens: 覆盖默认 max_tokens
        """
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
                    max_tokens=max_tokens or self.max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                text = resp.choices[0].message.content or ""
                self._track_usage(getattr(resp, "usage", None))
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"LLM 调用失败，降级离线：{exc}")
                text = self._offline(system, user)

        if self.cache_enabled:
            self._cache[key] = text
        return text

    def complete(self, prompt: str, use_cache: bool = True) -> str:
        """单轮完成（兼容 TextSentiment 旧调用）。

        内部转为 chat(system="", user=prompt)，保持接口兼容。
        """
        return self.chat("", prompt, use_cache=use_cache)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=False,
    )
    def chat_json(
        self,
        system: str,
        user: str,
        use_cache: bool = True,
        max_tokens: Optional[int] = None,
    ) -> dict:
        """结构化 JSON 输出（利用 response_format=json_object）。

        无密钥时返回 ``{"error": "offline", "items": []}``。
        """
        key = self._cache_key("json", system, user)
        if use_cache and self.cache_enabled and key in self._cache_json:
            return self._cache_json[key]

        client = self._get_client()
        if client is None:
            result = {"error": "offline", "items": []}
        else:
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=max_tokens or self.max_tokens,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                raw = resp.choices[0].message.content or "{}"
                self._track_usage(getattr(resp, "usage", None))
                result = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError as exc:
                logger.warning(f"LLM JSON 解析失败：{exc}，原始：{raw[:200]}")
                result = {"error": "json_parse", "items": [], "raw": raw[:500]}
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"LLM JSON 调用失败，降级：{exc}")
                result = {"error": str(exc), "items": []}

        if self.cache_enabled:
            self._cache_json[key] = result
        return result

    async def chat_stream(
        self,
        system: str,
        user: str,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """流式输出（用于 SSE 实时推送）。需 AsyncOpenAI 客户端。

        无密钥时 yield 离线占位文本。
        """
        client = self._get_async_client()
        if client is None:
            yield self._offline(system, user)
            return
        try:
            stream = await client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                stream=True,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"LLM 流式调用失败：{exc}")
            yield self._offline(system, user)

    def _cache_key(self, *parts: str) -> str:
        return hashlib.md5("||".join(parts).encode()).hexdigest()

    @staticmethod
    def _offline(system: str, user: str) -> str:
        """离线占位：明确标注未接入 LLM，便于冒烟/无密钥环境跑通。"""
        return (
            "> ⚠️ 当前环境未配置 LLM API Key（或未联网），以下为离线占位摘要。\n\n"
            f"**上下文摘要**\n\n{user}\n\n"
            "_（接入 DeepSeek V3 后将生成自然语言市场解读；本研究观点不构成投资建议。）_"
        )
