"""量价代理情绪因子（融合第 3 源 · v1 量价版，零额外源）。

P0-2 修正：v1 用市场微观结构量价指标构造情绪，**不依赖任何额外新闻/股吧源**：
- 换手率异常 ``turnover_anomaly``：量比相对均值偏离
- 振幅 ``amplitude``：日内振幅
- 封板率 ``limit_up_rate``：近窗涨停占比（涨停 fever）
- 涨跌幅分布 ``return_skew``：日收益偏度（恐慌=负偏）

各指标先做横截面 z，再按 ``config/sentiment.weights`` 加权合成 ``sentiment_score`` ∈ [-1,1]。
AkShare 新闻/股吧情绪为 P2 可选增强，不进 v1 核心。

读取 ``adj_back_close``（后复权）与 ``high``/``low``/``vol`` 计算。结果同时落
``factor_values``（factor_name='sentiment_score'）用于审计与下钻。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from common.stats import clip, group_zscore
from loguru import logger


class SentimentExtractor:
    """量价代理情绪提取器。"""

    def __init__(self, cfg: Optional[Dict] = None, window: int = 20) -> None:
        cfg = cfg or {}
        s = cfg.get("sentiment", {})
        self.window = int(s.get("window", window))
        self.weights: Dict[str, float] = s.get(
            "weights",
            {
                "turnover_anomaly": 0.35,
                "amplitude": 0.20,
                "limit_up_rate": 0.20,
                "return_skew": 0.25,
            },
        )

    def extract(
        self, bars_df: pd.DataFrame, universe_codes: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """返回 (date, code, sentiment_score) 长表（已存为 factor_name 在落库层处理）。"""
        if bars_df is None or bars_df.empty:
            return pd.DataFrame(columns=["date", "code", "sentiment_score"])

        work = bars_df
        if universe_codes is not None:
            work = bars_df[bars_df["code"].isin(universe_codes)].copy()
        work = work.sort_values(["code", "date"]).reset_index(drop=True)

        win = self.window
        frames = []
        for code, g in work.groupby("code", sort=False):
            g = g.sort_values("date").reset_index(drop=True)
            pr = g["adj_back_close"]
            ret = pr.pct_change()
            vol_ratio = g["vol"] / g["vol"].rolling(win).mean()
            turnover_anomaly = (vol_ratio - 1.0).fillna(0.0)
            amplitude = ((g["high"] - g["low"]) / pr).rolling(win).mean().fillna(0.0)
            # 涨停判定：收盘 >= 昨收*1.095（近似 10% 涨停）
            limit_up = (g["close"] >= g["pre_close"] * 1.095).rolling(win).mean().fillna(0.0)
            ret_skew = ret.rolling(win).skew().fillna(0.0)

            sub = pd.DataFrame(
                {
                    "date": g["date"].values,
                    "code": code,
                    "turnover_anomaly": turnover_anomaly.values,
                    "amplitude": amplitude.values,
                    "limit_up_rate": limit_up.values,
                    "return_skew": ret_skew.values,
                }
            )
            frames.append(sub)
        raw = pd.concat(frames, ignore_index=True)

        # 横截面 z（每日）
        for col in ["turnover_anomaly", "amplitude", "limit_up_rate", "return_skew"]:
            raw[col + "_z"] = group_zscore(raw, col, group_col="date")

        score = np.zeros(len(raw))
        for k, w in self.weights.items():
            col = k + "_z"
            if col in raw.columns:
                score = score + w * raw[col].fillna(0.0).to_numpy()
        raw["sentiment_score"] = clip(score)
        return raw[["date", "code", "sentiment_score"]]
