"""API 边界治理（P2-1）。

两层机制，保证任意端点输出恒为合法 JSON、未捕获异常转为干净 JSON：

1. ``SanitizedJSONResponse``（默认响应类，核心机制）
   Starlette 0.50 的 ``JSONResponse.render`` 默认 ``allow_nan=False``，路由一旦返回
   inf/nan，序列化阶段即抛 ``ValueError`` → 500。该子类在序列化前先用 ``sanitize_obj``
   把 inf/nan→None，保证所有端点（含 ``response_model`` 路径）的输出在边界恒为合法 JSON。
   作为 ``FastAPI(default_response_class=SanitizedJSONResponse)`` 生效，覆盖全部路由，
   新增端点无需各自造轮子。

   > 注：曾尝试用 ``BaseHTTPMiddleware`` 在响应边界重序列化，但有两处硬伤被放弃——
   > (a) Starlette 在 ``JSONResponse.render`` 阶段就因 ``allow_nan=False`` 拒绝 inf/nan，
   >     中间件在 ``call_next`` 后才拿到响应，异常早已抛出，永远拦不到；
   > (b) ``BaseHTTPMiddleware`` 会把端点异常从 ``ExceptionMiddleware`` 之外重抛，
   >     导致下方注册的 ``Exception`` 处理器失效（路由 500 变裸 HTML）。
   > 故改为默认响应类 + 异常处理器两条互不干扰的链路。

2. ``register_exception_handlers``
   统一未捕获异常 → 干净 JSON（含错误类型与消息），避免 500 裸奔栈。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.serializers import sanitize_obj


class SanitizedJSONResponse(JSONResponse):
    """默认响应类：序列化前统一清洗 inf/nan/numpy 特殊值 → 合法 JSON（杜绝 500）。"""

    def render(self, content: Any) -> bytes:
        try:
            clean = sanitize_obj(content)
        except Exception:  # noqa: BLE001
            # 极端情况下无法清洗则退回原始行为（与 starlette 默认一致）
            clean = content
        return json.dumps(
            clean,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


def register_exception_handlers(app: FastAPI) -> None:
    """统一未捕获异常处理：返回干净 JSON（含错误类型与消息），避免裸 500/栈暴露。

    注意：本函数依赖 FastAPI 的 ``ExceptionMiddleware`` 生效；不要在外层再用
    ``BaseHTTPMiddleware`` 包裹，否则异常会被重抛至 ``ServerErrorMiddleware`` 而绕过本处理器。
    """

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "error": type(exc).__name__},
        )
