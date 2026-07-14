"""量价代理情绪因子（融合第 3 源 · v1 量价版，零额外源）+ T0 扩展。

P0-2 修正：v1 用市场微观结构量价指标构造情绪，**不依赖任何额外新闻/股吧源**。
T0 扩展（纯 OHLCV，无新数据）：在原有 4 个微观结构指标基础上，增加
- ``breadth_rank``：个股日收益的横截面分位（宽度/参与度代理，越靠前越乐观）
- ``relative_strength``：个股 N 日超额收益（相对等权市场，相对强度代理）
GSISI 行业 Beta 轮动作为**市场级**情绪另见 ``factors/market_sentiment.py``。

各指标先做横截面 z（每日），再按 ``config/sentiment.weights`` 加权合成
``sentiment_score`` ∈ [-1,1]。AkShare 新闻/股吧情绪为 P2 可选增强。

读取 ``adj_back_close`` 与 ``high``/``low``/``vol``/``close``/``pre_close`` 计算。
落 ``factor_values``（factor_name='sentiment_score' 及子成分）供审计与下钻。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from common.stats import clip, group_zscore
from loguru import logger


class SentimentExtractor:
    """量价代理情绪提取器（v1 + T0 扩展）。"""

    # 子指标默认权重（config/sentiment.weights 可覆盖；缺失子指标自动跳过）
    DEFAULT_WEIGHTS: Dict[str, float] = {
        "turnover_anomaly": 0.30,
        "amplitude": 0.15,
        "limit_up_rate": 0.15,
        "return_skew": 0.20,
        "breadth_rank": 0.10,
        "relative_strength": 0.10,
    }
    RS_WINDOW = 20  # 相对强度窗口

    def __init__(self, cfg: Optional[Dict] = None, window: int = 20) -> None:
        cfg = cfg or {}
        s = cfg.get("sentiment", {})
        self.window = int(s.get("window", window))
        self.weights: Dict[str, float] = {**self.DEFAULT_WEIGHTS, **(s.get("weights", {}) or {})}

    def _components(self, bars_df: pd.DataFrame,
                    universe_codes: Optional[List[str]] = None) -> pd.DataFrame:
        """计算全部子指标（原始值），返回长表（date, code, <comp>...）。"""
        if bars_df is None or bars_df.empty:
            return pd.DataFrame()
        work = bars_df
        if universe_codes is not None:
            work = bars_df[bars_df["code"].isin(universe_codes)].copy()
        work = work.sort_values(["code", "date"]).reset_index(drop=True)
        win = self.window
        # 等权市场日收益（横截面均值），用于相对强度
        mkt = work.groupby("date")["adj_back_close"].apply(lambda s: s.pct_change().mean())
        frames = []
        for code, g in work.groupby("code", sort=False):
            g = g.sort_values("date").reset_index(drop=True)
            pr = g["adj_back_close"]
            ret = pr.pct_change()
            vol_ratio = g["vol"] / g["vol"].rolling(win).mean()
            turnover_anomaly = (vol_ratio - 1.0).fillna(0.0)
            amplitude = ((g["high"] - g["low"]) / pr).rolling(win).mean().fillna(0.0)
            limit_up = (g["close"] >= g["pre_close"] * 1.095).rolling(win).mean().fillna(0.0)
            return_skew = ret.rolling(win).skew().fillna(0.0)
            # 按位置对齐（mkt.reindex 后为 DatetimeIndex，需 reset 成 RangeIndex 与 pr 同序）
            mkt_g = mkt.reindex(g["date"]).reset_index(drop=True)
            rs = (pr / pr.shift(self.RS_WINDOW) - 1.0) - mkt_g.shift(self.RS_WINDOW).fillna(0.0)
            relative_strength = rs.fillna(0.0)
            sub = pd.DataFrame({
                "date": g["date"].values,
                "code": code,
                "turnover_anomaly": turnover_anomaly.values,
                "amplitude": amplitude.values,
                "limit_up_rate": limit_up.values,
                "return_skew": return_skew.values,
                "breadth_rank": ret.fillna(0.0).values,  # 占位，concat 后改每日横截面分位
                "relative_strength": relative_strength.values,
            })
            frames.append(sub)
        raw = pd.concat(frames, ignore_index=True)
        # breadth_rank 改为「每日横截面收益分位」（宽度/参与度代理）
        raw["breadth_rank"] = raw.groupby("date")["breadth_rank"].rank(pct=True).fillna(0.5)
        return raw

    def extract(
        self, bars_df: pd.DataFrame, universe_codes: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """返回 (date, code, sentiment_score) 长表（已存为 factor_name 在落库层处理）。"""
        raw = self._components(bars_df, universe_codes)
        if raw.empty:
            return pd.DataFrame(columns=["date", "code", "sentiment_score"])
        for col in list(self.weights.keys()):
            if col in raw.columns:
                raw[col + "_z"] = group_zscore(raw, col, group_col="date")
            else:
                logger.warning(f"情绪子指标 {col} 未计算，跳过")
        score = np.zeros(len(raw))
        for k, w in self.weights.items():
            col = k + "_z"
            if col in raw.columns:
                score = score + w * raw[col].fillna(0.0).to_numpy()
        raw["sentiment_score"] = clip(score)
        return raw[["date", "code", "sentiment_score"]]

    def extract_components(
        self, bars_df: pd.DataFrame, universe_codes: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """返回全部子指标（原始值 + z），供审计/下钻。"""
        raw = self._components(bars_df, universe_codes)
        if raw.empty:
            return raw
        for col in list(self.weights.keys()):
            if col in raw.columns:
                raw[col + "_z"] = group_zscore(raw, col, group_col="date")
        return raw
