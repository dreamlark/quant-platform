"""情绪相关外部数据层（akshare 多源，懒加载 + 本地缓存 + 失败降级）。

提供市场级情绪所需的「资金 / 估值 / 利率 / ETF 流 / 新闻」五类数据源。
全部为**可选**依赖：任一接口失败/缺失均返回 ``None``，由上层 ``factors/market_sentiment``
剔除该维度、不阻断主流水线。缓存写入 ``paths.raw_cache``（默认 ./data/raw_cache）。

注意：本环境仅 akshare 可用；部分接口（公募仓位、CDS 利差）无干净免费源，文档已标注省略。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from loguru import logger


def _cache_dir(cfg: Optional[Dict] = None) -> str:
    d = "./data/raw_cache"
    try:
        if cfg:
            d = cfg.get("paths", {}).get("raw_cache", d)
    except Exception:
        pass
    os.makedirs(d, exist_ok=True)
    return d


def _load_cache(name: str, cfg: Optional[Dict] = None) -> Optional[pd.DataFrame]:
    p = os.path.join(_cache_dir(cfg), f"sent_{name}.csv")
    if os.path.exists(p):
        try:
            return pd.read_csv(p, parse_dates=["date"])
        except Exception:
            return None
    return None


def _save_cache(name: str, df: pd.DataFrame, cfg: Optional[Dict] = None) -> None:
    try:
        df.to_csv(os.path.join(_cache_dir(cfg), f"sent_{name}.csv"), index=False)
    except Exception:
        pass


def load_margin(cfg: Optional[Dict] = None) -> Optional[pd.DataFrame]:
    """融资融券汇总（沪+深）：date, margin_balance, margin_net_buy。"""
    try:
        cached = _load_cache("margin", cfg)
        if cached is not None and not cached.empty:
            return cached
        import akshare as ak  # type: ignore

        rows = []
        for fn in (ak.stock_margin_sh, ak.stock_margin_sz):
            df = fn()
            if df is None or df.empty:
                continue
            # 兼容不同列名：余额/买入额/净买入
            bal = next((c for c in df.columns if "balance" in c.lower() or "余额" in c), None)
            net = next((c for c in df.columns if "net" in c.lower() or "净" in c), None)
            dtcol = next((c for c in df.columns if "date" in c.lower()), None)
            if bal is None or dtcol is None:
                continue
            sub = df[[dtcol, bal]].copy()
            sub[dtcol] = pd.to_datetime(sub[dtcol]).dt.normalize()
            sub[bal] = pd.to_numeric(sub[bal], errors="coerce")
            if net:
                sub[net] = pd.to_numeric(df[net], errors="coerce")
            sub = sub.rename(columns={dtcol: "date", bal: "margin_balance"})
            if net:
                sub = sub.rename(columns={net: "margin_net_buy"})
            rows.append(sub)
        if not rows:
            return None
        out = pd.concat(rows, ignore_index=True)
        out = out.groupby("date").agg({
            "margin_balance": "sum",
            "margin_net_buy": "sum" if "margin_net_buy" in out.columns else "first",
        }).reset_index()
        _save_cache("margin", out, cfg)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"情绪数据：融资融券获取失败（降级）：{exc}")
        return None


def load_northbound(cfg: Optional[Dict] = None) -> Optional[pd.DataFrame]:
    """北向（沪深港通）净买入：date, net_buy。"""
    try:
        cached = _load_cache("northbound", cfg)
        if cached is not None and not cached.empty:
            return cached
        import akshare as ak  # type: ignore

        df = ak.stock_hsgt_north_net_flow_in_em()
        if df is None or df.empty:
            return None
        dtcol = next((c for c in df.columns if "date" in c.lower()), None)
        net = next((c for c in df.columns if "net" in c.lower() or "净" in c), None)
        if dtcol is None or net is None:
            return None
        out = df[[dtcol, net]].copy()
        out[dtcol] = pd.to_datetime(out[dtcol]).dt.normalize()
        out[net] = pd.to_numeric(out[net], errors="coerce")
        out = out.rename(columns={dtcol: "date", net: "net_buy"})
        _save_cache("northbound", out, cfg)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"情绪数据：北向净买入获取失败（降级）：{exc}")
        return None


def load_index_valuation(cfg: Optional[Dict] = None) -> Optional[pd.DataFrame]:
    """指数估值（PE/PB）：date, pe, pb。尝试 akshare 指数估值接口，失败返回 None。"""
    try:
        cached = _load_cache("valuation", cfg)
        if cached is not None and not cached.empty:
            return cached
        import akshare as ak  # type: ignore

        for fn in ("stock_index_pe_lg", "index_pe_lg", "stock_a_indicator_lg"):
            if not hasattr(ak, fn):
                continue
            df = getattr(ak, fn)()
            if df is None or df.empty:
                continue
            dtcol = next((c for c in df.columns if "date" in c.lower()), None)
            pe = next((c for c in df.columns if "pe" in c.lower() or "市盈率" in c), None)
            pb = next((c for c in df.columns if "pb" in c.lower() or "市净率" in c), None)
            if dtcol is None or (pe is None and pb is None):
                continue
            cols = [dtcol] + ([pe] if pe else []) + ([pb] if pb else [])
            out = df[cols].copy()
            out[dtcol] = pd.to_datetime(out[dtcol]).dt.normalize()
            out = out.rename(columns={dtcol: "date"})
            if pe:
                out["pe"] = pd.to_numeric(out[pe], errors="coerce")
            if pb:
                out["pb"] = pd.to_numeric(out[pb], errors="coerce")
            _save_cache("valuation", out, cfg)
            return out
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"情绪数据：指数估值获取失败（降级）：{exc}")
        return None


def load_bond_yield(cfg: Optional[Dict] = None) -> Optional[pd.DataFrame]:
    """10Y 国债收益率：date, yield_10y。"""
    try:
        cached = _load_cache("bond", cfg)
        if cached is not None and not cached.empty:
            return cached
        import akshare as ak  # type: ignore

        df = ak.bond_china_yield()
        if df is None or df.empty:
            return None
        dtcol = next((c for c in df.columns if "date" in c.lower()), None)
        ycol = next((c for c in df.columns if "10" in str(c) and ("y" in str(c).lower() or "收益" in str(c))), None)
        if dtcol is None or ycol is None:
            return None
        out = df[[dtcol, ycol]].copy()
        out[dtcol] = pd.to_datetime(out[dtcol]).dt.normalize()
        out[ycol] = pd.to_numeric(out[ycol], errors="coerce")
        out = out.rename(columns={dtcol: "date", ycol: "yield_10y"})
        _save_cache("bond", out, cfg)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"情绪数据：国债收益率获取失败（降级）：{exc}")
        return None


def load_etf_flow(cfg: Optional[Dict] = None) -> Optional[pd.DataFrame]:
    """ETF 净流量（资金结构代理）：date, net_flow。"""
    try:
        cached = _load_cache("etf", cfg)
        if cached is not None and not cached.empty:
            return cached
        import akshare as ak  # type: ignore

        df = ak.fund_etf_net_buy_em()
        if df is None or df.empty:
            return None
        dtcol = next((c for c in df.columns if "date" in c.lower()), None)
        net = next((c for c in df.columns if "net" in c.lower() or "净" in c), None)
        if dtcol is None or net is None:
            return None
        out = df[[dtcol, net]].copy()
        out[dtcol] = pd.to_datetime(out[dtcol]).dt.normalize()
        out[net] = pd.to_numeric(out[net], errors="coerce")
        out = out.rename(columns={dtcol: "date", net: "net_flow"})
        _save_cache("etf", out, cfg)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"情绪数据：ETF 净流量获取失败（降级）：{exc}")
        return None


def load_news(symbol: str, cfg: Optional[Dict] = None, limit: int = 20) -> List[str]:
    """个股新闻文本（T3 LLM 文本情绪用）。失败返回空列表。"""
    try:
        import akshare as ak  # type: ignore

        df = ak.stock_news_em(symbol=symbol)
        if df is None or df.empty:
            return []
        col = next((c for c in df.columns if "content" in c.lower() or "新闻" in c or "标题" in c), None)
        if col is None:
            return []
        texts = df[col].dropna().astype(str).head(limit).tolist()
        return texts
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"情绪数据：新闻获取失败 {symbol}：{exc}")
        return []


def fetch_all(cfg: Optional[Dict] = None) -> Dict[str, Optional[pd.DataFrame]]:
    """一次性拉取全部外部维度；任一失败返回 None。"""
    return {
        "margin": load_margin(cfg),
        "northbound": load_northbound(cfg),
        "valuation": load_index_valuation(cfg),
        "bond": load_bond_yield(cfg),
        "etf": load_etf_flow(cfg),
    }
