"""信号融合池（四源加权：因子 + 技术 + 情绪 + 预测）。

融合前因子须已完成**行业/市值中性化**（`factors/risk_neutral.py`），
``factor_contrib`` 记录中性化残差贡献（架构 §3.1 / §7.7 / §7.9）。

各源先做横截面 z，再按健康度/历史准确度加权求和：
``total = w_f·factor + w_t·tech + w_s·sentiment + w_p·predict``
方向 = sign(total)；置信度 = sigmoid(|total|·scale)（**取自信号层，非 LLM 自报**）。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from common.stats import group_zscore, sigmoid
from factors.factor_calc import load_factor_config
from loguru import logger


class SignalPool:
    """四源融合信号池。"""

    def __init__(self, cfg: Optional[Dict] = None) -> None:
        cfg = cfg or {}
        self.cfg = cfg
        fusion = cfg.get("fusion", {})
        bw = fusion.get("base_weights", {})
        self.w_factor = float(bw.get("factor", 0.40))
        self.w_tech = float(bw.get("tech", 0.20))
        self.w_sent = float(bw.get("sentiment", 0.15))
        self.w_pred = float(bw.get("predict", 0.25))
        self.scale = float(fusion.get("confidence_scale", 2.5))
        self.deadzone = 0.05
        self.defs = load_factor_config()
        self.directions: Dict[str, int] = {
            f["name"]: int(f.get("direction", 1)) for f in self.defs
        }

    def fuse(
        self,
        factor_long: pd.DataFrame,
        tech_df: pd.DataFrame,
        sentiment_df: pd.DataFrame,
        predict_df: pd.DataFrame,
        health_df: pd.DataFrame,
        predict_health_df: pd.DataFrame,
        date: dt.date,
        codes: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """融合四源，返回 ``signals`` 表（date 已固定为 ``date``）。"""
        factor_weights = dict(
            zip(health_df["factor_name"], health_df["weight"])
        ) if health_df is not None and not health_df.empty else {}
        pred_weights = dict(
            zip(predict_health_df["model_name"], predict_health_df["weight"])
        ) if predict_health_df is not None and not predict_health_df.empty else {}

        # ---- 因子（已中性化）----
        fwide = self._pivot(factor_long, date)
        factor_contrib = self._factor_score(fwide, factor_weights)

        # ---- 技术 ----
        tech = self._slice(tech_df, date, ["code", "tech_score"])
        tech_contrib = self._zs_col(tech, "tech_score")

        # ---- 情绪 ----
        sent = self._slice(sentiment_df, date, ["code", "sentiment_score"])
        sentiment_contrib = self._zs_col(sent, "sentiment_score")

        # ---- 预测（第 4 源）----
        predict_contrib = self._predict_score(predict_df, date, pred_weights)

        # ---- 对齐到统一 (date, code) ----
        all_codes = set(factor_contrib.index)
        for s in (tech_contrib, sentiment_contrib, predict_contrib):
            all_codes.update(s.index)
        if codes is not None:
            all_codes &= set(codes)
        all_codes = sorted(all_codes)

        rows = []
        for code in all_codes:
            fc = float(factor_contrib.get(code, 0.0) or 0.0)
            tc = float(tech_contrib.get(code, 0.0) or 0.0)
            sc = float(sentiment_contrib.get(code, 0.0) or 0.0)
            pc = float(predict_contrib.get(code, 0.0) or 0.0)

            total = (
                self.w_factor * fc
                + self.w_tech * tc
                + self.w_sent * sc
                + self.w_pred * pc
            )
            direction = 0
            if total > self.deadzone:
                direction = 1
            elif total < -self.deadzone:
                direction = -1
            confidence = float(round(float(sigmoid(abs(total) * self.scale)), 3))

            tags = []
            if abs(fc) > 0.01:
                tags.append("因子")
            if abs(tc) > 0.01:
                tags.append("技术")
            if abs(sc) > 0.01:
                tags.append("情绪")
            if abs(pc) > 0.01:
                tags.append("预测")

            rows.append(
                {
                    "date": date,
                    "code": code,
                    "direction": int(direction),
                    "confidence": confidence,
                    "source_tags": ",".join(tags) if tags else "无",
                    "factor_contrib": round(fc, 4),
                    "tech_contrib": round(tc, 4),
                    "sentiment_contrib": round(sc, 4),
                    "predict_contrib": round(pc, 4),
                }
            )
        logger.info(
            f"信号融合 {date}：{len(rows)} 只；"
            f"权重 因子={self.w_factor} 技术={self.w_tech} "
            f"情绪={self.w_sent} 预测={self.w_pred}"
        )
        return pd.DataFrame(rows)

    # ---- 内部工具 ------------------------------------------------
    @staticmethod
    def _pivot(factor_long: pd.DataFrame, date: dt.date) -> pd.DataFrame:
        if factor_long is None or factor_long.empty:
            return pd.DataFrame(columns=["code"])
        sub = factor_long[factor_long["date"] == date]
        if sub.empty:
            return pd.DataFrame(columns=["code"])
        return sub.pivot_table(index="code", columns="factor_name", values="value").reset_index()

    @staticmethod
    def _slice(df: pd.DataFrame, date, cols) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=cols)
        sub = df[df["date"] == date]
        return sub[cols].copy() if not sub.empty else pd.DataFrame(columns=cols)

    def _factor_score(self, fwide: pd.DataFrame, weights: Dict[str, float]) -> pd.Series:
        if fwide is None or fwide.empty or "code" not in fwide:
            return pd.Series(dtype=float)
        codes = fwide["code"].tolist()
        score = np.zeros(len(codes))
        w_sum = 0.0
        for fname in fwide.columns:
            if fname == "code":
                continue
            col = fwide[fname].to_numpy(dtype=float)
            if np.isnan(col).all():
                continue
            sd = col.std(ddof=0)
            z = (col - col.mean()) / (sd if (sd and not np.isnan(sd)) else 1.0)
            z = np.nan_to_num(z, nan=0.0)
            w = float(weights.get(fname, 1.0))
            score = score + z * self.directions.get(fname, 1) * w
            w_sum += w
        if w_sum > 0:
            score = score / w_sum
        return pd.Series(score, index=codes)

    @staticmethod
    def _zs_col(df: pd.DataFrame, col: str) -> pd.Series:
        if df is None or df.empty or col not in df:
            return pd.Series(dtype=float)
        s = df.set_index("code")[col]
        mu, sd = s.mean(), s.std(ddof=0)
        if sd == 0 or pd.isna(sd):
            return pd.Series(0.0, index=s.index)
        return (s - mu) / sd

    @staticmethod
    def _predict_score(
        predict_df: pd.DataFrame, date: dt.date, pred_weights: Dict[str, float]
    ) -> pd.Series:
        if predict_df is None or predict_df.empty:
            return pd.Series(dtype=float)
        sub = predict_df[(predict_df["date"] == date) & (predict_df["horizon"] == 1)]
        if sub.empty:
            return pd.Series(dtype=float)
        out = {}
        for code, g in sub.groupby("code"):
            num = 0.0
            den = 0.0
            for _, r in g.iterrows():
                w = float(pred_weights.get(r["model_name"], 0.0))
                if w <= 0:
                    continue
                num += float(r["dir_pred"]) * w
                den += w
            out[code] = num / den if den > 0 else 0.0
        s = pd.Series(out)
        mu, sd = s.mean(), s.std(ddof=0)
        if sd == 0 or pd.isna(sd) or len(s) < 2:
            return s
        return (s - mu) / sd
