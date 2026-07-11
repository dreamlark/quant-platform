"""市场元数据抓取（行业 / 市值），用于风险中性化（P1-4）。

数据源（均经沙箱实测可达）：
- 市值：腾讯 gtimg 实时快照（批量 q=sz000001,sh600000,...，单请求取全样本），idx 44 = 总市值(亿)。
- 行业：申万一级行业（akshare ``sw_index_first_info`` 取 31 个一级行业代码 + 乐咕乐股
  ``legulegu.com`` 成分页）。乐咕乐股有局部限流，已加重试退避 + 本地缓存跨 run 累积。

产出 ``DataFrame[code, name, industry, mv]``，缺值处 industry/mv 留空（中性化模块对缺值日跳过）。
"""
from __future__ import annotations

import time
import os
import json
from typing import Dict, List, Optional

import pandas as pd
import requests

from loguru import logger

_CACHE_FILE = os.path.join(os.path.dirname(__file__), "_sw_industry_cache.json")


def _load_cache() -> Dict[str, str]:
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_cache(m: Dict[str, str]) -> None:
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def fetch_market_cap(codes: List[str]) -> Dict[str, float]:
    """批量取总市值（亿元）。腾讯 gtimg 支持逗号批量。"""
    if not codes:
        return {}
    def sym(c: str) -> str:
        c = c.split(".")[0]
        return ("sh" if c.startswith("6") else "sz") + c
    syms = [sym(c) for c in codes]
    out: Dict[str, float] = {}
    # 分批（每批 <= 50）避免 URL 过长
    for i in range(0, len(syms), 50):
        batch = syms[i : i + 50]
        url = "https://qt.gtimg.cn/q=" + ",".join(batch)
        try:
            r = requests.get(url, timeout=10)
            r.encoding = "gbk"
            for piece in r.text.split(";"):
                piece = piece.strip()
                if "=" not in piece:
                    continue
                key, val = piece.split("=", 1)
                code6 = key.replace("v_", "").strip()
                # 还原为 A 股代码（6 位）
                code = code6[2:] if code6.startswith(("sh", "sz")) else code6
                parts = val.strip('"').split("~")
                if len(parts) > 44 and parts[44]:
                    try:
                        out[code] = float(parts[44])  # 总市值(亿)
                    except ValueError:
                        out[code] = float("nan")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"gtimg 市值批次失败：{exc}")
        time.sleep(0.2)
    return out


# 申万一级行业（2021 版，31 个，代码稳定不变）——硬编码以摆脱 akshare 接口抽风
_SW_FIRST = [
    ("801010", "农林牧渔"), ("801030", "基础化工"), ("801040", "钢铁"),
    ("801050", "有色金属"), ("801080", "电子"), ("801110", "家用电器"),
    ("801120", "食品饮料"), ("801130", "纺织服饰"), ("801140", "轻工制造"),
    ("801150", "医药生物"), ("801160", "公用事业"), ("801170", "交通运输"),
    ("801180", "房地产"), ("801200", "商贸零售"), ("801210", "社会服务"),
    ("801230", "综合"), ("801710", "建筑材料"), ("801720", "建筑装饰"),
    ("801730", "电力设备"), ("801740", "国防军工"), ("801750", "计算机"),
    ("801760", "传媒"), ("801770", "通信"), ("801780", "银行"),
    ("801790", "非银金融"), ("801800", "汽车"), ("801890", "机械设备"),
    ("801950", "煤炭"), ("801960", "石油石化"), ("801970", "环保"),
    ("801980", "美容护理"),
]


def fetch_industry_map(codes: Optional[List[str]] = None) -> Dict[str, str]:
    """构建 code -> 申万一级行业 映射（akshare ``index_stock_cons`` + 硬编码申万一级代码）。

    经沙箱实测，``index_stock_cons(symbol="801010")`` 等申万一级行业指数成分接口稳定可达
    （非东财/非 legulegu 限流源），返回 {品种代码, 品种名称}。配合本地缓存加速。

    返回 {code(6位): 申万一级行业名}；全部失败则降级为无行业中性化（仅市值中性化生效）。
    """
    out = _load_cache()  # 预载历史缓存
    try:
        import akshare as ak

        for sym, name in _SW_FIRST:
            try:
                cons = ak.index_stock_cons(symbol=sym)
                for c in cons["品种代码"].astype(str).str.zfill(6).tolist():
                    if c:
                        out.setdefault(c, name)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"申万行业 {name}({sym}) 成分失败：{exc}")
            time.sleep(0.1)
        logger.info(f"申万一级行业映射：{len(out)} 只（含缓存）")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"行业映射获取失败（降级无行业中性化）：{exc}")
    _save_cache(out)
    return out


def build_market_meta(
    codes: List[str], names: Optional[List[str]] = None
) -> pd.DataFrame:
    """汇总 code/name/industry/mv。"""
    names = names or codes
    name_map = dict(zip([c.split(".")[0] for c in codes], names))
    cap = fetch_market_cap(codes)
    ind = fetch_industry_map(codes)
    rows = []
    for c in codes:
        c6 = c.split(".")[0]
        rows.append(
            {
                "code": c6,
                "name": name_map.get(c6, c6),
                "industry": ind.get(c6, ""),
                "mv": cap.get(c6, float("nan")),
            }
        )
    return pd.DataFrame(rows)
