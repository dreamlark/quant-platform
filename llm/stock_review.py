"""自选股逐只简评（研究观点，含持仓盈亏；置信度取信号层）。

合规（P2-4 / P2-5）：action ∈ {买入, 卖出, 持有} 仅作【研究观点标签】；
reason 必须引用信号四源贡献；confidence 使用信号层 ``signals.confidence``，禁止 LLM 自报。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

from llm.client import LLMClient
from llm.prompts import SYSTEM_REVIEW, build_review_prompt


@dataclass
class ReviewResult:
    """个股研判结果。"""

    action: str          # 买入 / 卖出 / 持有（研究观点标签）
    reason: str
    confidence: float    # 取自信号层
    content: str         # Markdown 正文（已挂免责声明）


class StockReviewer:
    """自选股逐只简评生成器。"""

    def __init__(self, llm: LLMClient, disclaimer: str = "") -> None:
        self.llm = llm
        self.disclaimer = disclaimer

    def review(
        self,
        code: str,
        name: str,
        signal_row: Optional[Dict],
        holding: Optional[Dict] = None,
    ) -> ReviewResult:
        """生成单只个股研究观点。

        Args:
            code/name: 标的。
            signal_row: signals 表行（含 direction/confidence/四源贡献），可为 None。
            holding: 持仓信息 {cost_price, shares, current_price}，可为 None。
        """
        # 合规：action 由信号方向映射（研究观点标签），confidence 取信号层
        direction = int(signal_row["direction"]) if signal_row else 0
        confidence = float(signal_row["confidence"]) if signal_row else 0.0
        action = {1: "买入", -1: "卖出", 0: "持有"}[direction]

        ctx = self._build_context(code, name, signal_row, holding)
        body = self.llm.chat(SYSTEM_REVIEW, build_review_prompt(ctx), use_cache=True)
        full = f"{body}\n\n---\n\n> {self.disclaimer}" if self.disclaimer else body
        return ReviewResult(
            action=action, reason=ctx, confidence=confidence, content=full
        )

    @staticmethod
    def _build_context(
        code: str,
        name: str,
        signal_row: Optional[Dict],
        holding: Optional[Dict],
    ) -> str:
        lines = [f"标的：{code} {name}", ""]
        if signal_row:
            d = {1: "看多", -1: "看空", 0: "中性"}[int(signal_row["direction"])]
            lines.append(f"融合方向：{d}（信号层置信度 {signal_row['confidence']:.2f}）")
            lines.append(
                "四源贡献："
                f"因子={signal_row.get('factor_contrib'):.3f}，"
                f"技术={signal_row.get('tech_contrib'):.3f}，"
                f"情绪={signal_row.get('sentiment_contrib'):.3f}，"
                f"预测={signal_row.get('predict_contrib'):.3f}"
            )
            lines.append(f"来源标签：{signal_row.get('source_tags')}")
        if holding:
            cost = float(holding.get("cost_price", 0.0))
            price = float(holding.get("current_price", 0.0))
            pnl = (price - cost) / cost if cost > 0 else 0.0
            lines.append(
                f"持仓：成本 {cost:.2f}，现价 {price:.2f}，收益率 {pnl*100:.2f}%"
            )
        return "\n".join(lines)
