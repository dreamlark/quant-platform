"""市场综合简报生成（盘后批量，DeepSeek V3 单模型）。

合规（P2-4 / P2-5）：简报为"研究观点/分析信号"；置信度取信号层；正文挂固定免责声明。
无 LLM 密钥时返回离线占位（不阻断流水线）。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import pandas as pd

from llm.client import LLMClient
from llm.prompts import SYSTEM_BRIEF, build_brief_prompt


class BriefGenerator:
    """市场综合简报生成器。"""

    def __init__(self, llm: LLMClient, disclaimer: str = "") -> None:
        self.llm = llm
        self.disclaimer = disclaimer

    def generate_market_brief(
        self,
        date: dt.date,
        signals_df: pd.DataFrame,
        sector_df: pd.DataFrame,
        universe_df: pd.DataFrame,
        sentiment_index: Optional[float] = None,
    ) -> tuple[str, int]:
        """生成简报正文与 市场温度计(0-100)。

        Args:
            signals_df: 当日 signals 表。
            sector_df: 当日 sector_rotation 表。
            universe_df: 当日 universe 表（用于涨跌家数统计）。
            sentiment_index: 情绪指数（0-100），缺省由 signals 推导。
        """
        ctx = self._build_context(date, signals_df, sector_df, universe_df)
        temp = self._market_temperature(signals_df, sentiment_index)

        body = self.llm.chat(SYSTEM_BRIEF, build_brief_prompt(ctx), use_cache=True)
        # 挂固定免责声明
        full = f"{body}\n\n---\n\n> {self.disclaimer}" if self.disclaimer else body
        return full, temp

    # ---- 上下文构造 ----------------------------------------------
    def _build_context(
        self,
        date: dt.date,
        signals_df: pd.DataFrame,
        sector_df: pd.DataFrame,
        universe_df: pd.DataFrame,
    ) -> str:
        lines: List[str] = [f"日期：{date}", ""]
        if universe_df is not None and not universe_df.empty:
            inv = universe_df[universe_df["in_universe"]]
            n = len(inv)
            lines.append(f"可投资域样本数：{n} 只")
        if signals_df is not None and not signals_df.empty:
            bull = int((signals_df["direction"] == 1).sum())
            bear = int((signals_df["direction"] == -1).sum())
            flat = int((signals_df["direction"] == 0).sum())
            lines.append(f"融合信号：看多 {bull} / 看空 {bear} / 中性 {flat}")
            top = signals_df.sort_values("confidence", ascending=False).head(8)
            lines.append("\n**今日重点信号（按置信度）**：")
            for _, r in top.iterrows():
                d = {1: "看多", -1: "看空", 0: "中性"}[int(r["direction"])]
                lines.append(
                    f"- {r['code']}：{d}（置信度 {r['confidence']:.2f}，"
                    f"来源 {r['source_tags']}）"
                )
        if sector_df is not None and not sector_df.empty:
            lines.append("\n**板块强弱（按 RS 降序）**：")
            for _, r in sector_df.head(8).iterrows():
                lines.append(
                    f"- {r['sector_name']}：涨跌 {r['change_pct']*100:.2f}% "
                    f"RS {r['rs']*100:.2f}（{r['rotation_signal']}）"
                )
        return "\n".join(lines)

    @staticmethod
    def _market_temperature(
        signals_df: pd.DataFrame, sentiment_index: Optional[float]
    ) -> int:
        if sentiment_index is not None:
            return int(max(0, min(100, round(sentiment_index))))
        if signals_df is None or signals_df.empty:
            return 50
        net = (signals_df["direction"] * signals_df["confidence"]).sum()
        total = signals_df["confidence"].sum()
        score = 50 + 50 * (net / total) if total > 0 else 50
        return int(max(0, min(100, round(score))))
