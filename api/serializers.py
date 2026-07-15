"""API 边界序列化消毒（P2-1 边界集中治理）。

所有 API 响应在边界统一清洗 inf/nan/numpy 特殊值，避免 pydantic v2 / JSON 序列化
拒绝非有限浮点导致 500。复用此前在 dashboard.py 验证过的逻辑，上提为共享模块，
供中间件与各处端点统一调用。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def sanitize_val(v: Any) -> Any:
    """把 inf/nan 转为 None；numpy 标量归一为 Python 原生类型。"""
    if isinstance(v, (float, np.floating)):
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def sanitize_obj(obj: Any) -> Any:
    """递归清洗任意结构（dict/list/标量）中的 inf/nan/numpy 类型。"""
    if isinstance(obj, dict):
        return {k: sanitize_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_obj(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        fv = float(obj)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def sanitize_df(df: pd.DataFrame) -> pd.DataFrame:
    """逐列清洗 inf/nan/numpy 特殊值，避免响应序列化 500。

    对所有列应用 ``sanitize_val``（非浮点/非 numpy 值原样返回，安全无副作用）：
    - 数值列 inf/nan → NaN（float 列无法存 None，最终由 ``SanitizedJSONResponse`` 转 None）；
    - 对象列 inf/nan → None（object 列可保留 None）。
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    for c in out.columns:
        out[c] = out[c].apply(sanitize_val)
    return out
