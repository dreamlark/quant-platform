"""P2-1 边界治理单元测试。

不依赖真实 DuckDB，用最小 FastAPI 应用验证：

- ``SanitizedJSONResponse``（默认响应类，核心机制）：路由返回 inf/nan 特殊值时，
  在 Starlette 序列化前被清洗为 null，输出恒为合法 JSON（否则 500）。
- ``register_exception_handlers``：未捕获异常 → 干净 JSON（500 + detail/error），不裸奔栈。
- ``sanitize_obj`` / ``sanitize_df``：inf/nan/numpy 特殊值清洗为 null/原生类型（源级复用）。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware import SanitizedJSONResponse, register_exception_handlers
from api.serializers import sanitize_df, sanitize_obj


def _make_app() -> FastAPI:
    app = FastAPI(default_response_class=SanitizedJSONResponse)

    @app.get("/inf")
    def inf():
        return {"a": math.inf, "b": -math.inf, "c": float("nan"), "d": 1.0}

    @app.get("/nested")
    def nested():
        return {"list": [math.inf, float("nan"), 2.0], "obj": {"x": math.inf}}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom-detail")

    register_exception_handlers(app)
    return app


def test_inf_nan_to_null():
    body = TestClient(_make_app()).get("/inf").json()
    assert body["a"] is None
    assert body["b"] is None
    assert body["c"] is None
    assert body["d"] == 1.0


def test_nested_inf_nan_to_null():
    body = TestClient(_make_app()).get("/nested").json()
    assert body["list"] == [None, None, 2.0]
    assert body["obj"]["x"] is None


def test_unhandled_exception_to_clean_json():
    # raise_server_exceptions=False：验证已注册的 Exception 处理器返回干净 JSON，
    # 否则 TestClient 默认会把已处理的服务端异常重新抛出（starlette 文档行为）。
    r = TestClient(_make_app(), raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "RuntimeError"
    assert "kaboom-detail" in body["detail"]


def test_sanitize_obj_numpy_and_inf():
    data = {
        "a": math.inf,
        "b": [float("nan"), {"c": -math.inf}],
        "i": np.int64(7),
        "f": np.float32(1.5),
        "flag": np.bool_(True),
    }
    out = sanitize_obj(data)
    assert out == {"a": None, "b": [None, {"c": None}], "i": 7, "f": 1.5, "flag": True}
    assert isinstance(out["i"], int) and isinstance(out["flag"], bool)


def test_sanitize_df_normalizes_numpy_keeps_strings():
    # 边界安全的真正防线是 SanitizedJSONResponse（dict 路径）；sanitize_df 作为
    # 源级辅助：归一 object 列中的 numpy 标量、保留字符串、遇到 inf 不抛异常
    # （数值列 inf 经 pandas 折叠为 nan，最终由响应类转 None）。
    df = pd.DataFrame(
        {
            "name": ["a", "b"],
            "obj": pd.Series([np.int64(3), "x"], dtype=object),
            "num": pd.Series([1.0, math.inf], dtype=object),
        }
    )
    out = sanitize_df(df)
    assert out["name"].tolist() == ["a", "b"]
    assert out["obj"].tolist() == [3, "x"]
    assert isinstance(out["obj"].iloc[0], int)
    # inf 在数值上下文折叠为 nan，但不抛异常；nan→None 由响应类保证
    assert math.isnan(out["num"].iloc[1])
