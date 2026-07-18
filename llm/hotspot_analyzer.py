"""LLM 热点语义分析引擎。

消费 HotspotCollector 采集的文本条目，通过 LLM 进行：
- 主题提取
- 实体识别（公司/行业/概念）
- 情感打分
- 影响力评估
- 标的关联映射

输出结构化 HotspotSignal，供存储/融合/API 消费。

合规约束：LLM 输出定位为"分析信号"，related_codes 只能从提供的股票池中匹配。
"""
from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger

from llm.client import LLMClient
from llm.prompts import (
    SYSTEM_HOTSPOT,
    SYSTEM_HOTSPOT_DIGEST,
    build_hotspot_prompt,
    build_hotspot_digest_prompt,
)
from sources.hotspot_collector import HotspotItem


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class HotspotSignal:
    """热点语义信号（LLM 分析结果的归一化输出）。"""

    ts: dt.datetime               # 热点时间戳
    source: str                   # 数据来源
    title: str                    # 原始标题
    topic: str                    # LLM 提取主题
    sentiment: str                # 利好/利空/中性
    sentiment_score: float        # [-1, 1]
    impact: str                   # 高/中/低
    impact_score: float           # [0, 1]
    related_sectors: List[str]    # 关联板块
    related_codes: List[str]      # 关联股票代码
    reasoning: str                # 判断依据

    @property
    def composite_score(self) -> float:
        """复合信号：sentiment_score × impact_score ∈ [-1, 1]。"""
        return round(self.sentiment_score * self.impact_score, 4)

    def to_dict(self) -> Dict[str, Any]:
        """转为字典（落库/API 用）。"""
        return {
            "ts": self.ts.isoformat(),
            "source": self.source,
            "title": self.title,
            "topic": self.topic,
            "sentiment": self.sentiment,
            "sentiment_score": self.sentiment_score,
            "impact": self.impact,
            "impact_score": self.impact_score,
            "related_sectors": ",".join(self.related_sectors),
            "related_codes": ",".join(self.related_codes),
            "reasoning": self.reasoning,
            "composite_score": self.composite_score,
        }


# ============================================================================
# 热点语义分析引擎
# ============================================================================

class HotspotAnalyzer:
    """热点文本 LLM 语义分析引擎。"""

    def __init__(
        self,
        llm: LLMClient,
        stock_pool: Optional[Dict[str, str]] = None,
        batch_size: int = 8,
        max_tokens: int = 4096,
    ) -> None:
        """
        Args:
            llm: LLM 客户端
            stock_pool: 股票池映射 {code: name}，用于 LLM 匹配关联标的
            batch_size: 每批分析的新闻条数
            max_tokens: LLM 最大输出 token 数
        """
        self.llm = llm
        self.stock_pool = stock_pool or {}
        self.batch_size = batch_size
        self.max_tokens = max_tokens

    def analyze_batch(self, items: List[HotspotItem]) -> List[HotspotSignal]:
        """批量分析热点文本，返回结构化信号列表。

        将 items 按 batch_size 分批，每批调用 LLM chat_json() 获取结构化结果。
        无 LLM 时返回空列表（降级）。
        """
        if not items:
            return []

        if not self.llm.is_available:
            logger.info("热点分析：LLM 不可用（离线降级），跳过")
            return []

        all_signals: List[HotspotSignal] = []

        # 分批处理
        for i in range(0, len(items), self.batch_size):
            batch = items[i: i + self.batch_size]
            try:
                signals = self._analyze_one_batch(batch)
                all_signals.extend(signals)
            except Exception as exc:
                logger.warning(f"热点分析批次 {i // self.batch_size} 失败（降级）：{exc}")
                # 降级：为该批生成简单信号
                for item in batch:
                    all_signals.append(self._fallback_signal(item))

        logger.info(f"热点分析：{len(items)} 条 → {len(all_signals)} 个信号")
        return all_signals

    def _analyze_one_batch(self, batch: List[HotspotItem]) -> List[HotspotSignal]:
        """分析一批热点文本。"""
        # 构造 LLM 输入
        news_items = [
            {
                "title": item.title,
                "content": item.content[:300],
                "source": item.source,
                "ts": item.ts.strftime("%Y-%m-%d %H:%M"),
            }
            for item in batch
        ]

        user_prompt = build_hotspot_prompt(news_items, self.stock_pool)
        result = self.llm.chat_json(
            system=SYSTEM_HOTSPOT,
            user=user_prompt,
            max_tokens=self.max_tokens,
        )

        if "error" in result and result.get("error") not in (None, "", "offline"):
            logger.warning(f"热点分析 LLM 返回错误：{result.get('error')}")

        # 解析 LLM 输出
        items_data = result.get("items", [])
        if not isinstance(items_data, list):
            items_data = []

        signals: List[HotspotSignal] = []
        for i, item_data in enumerate(items_data):
            if i >= len(batch):
                break
            original = batch[i]
            signal = self._parse_signal(original, item_data)
            if signal:
                signals.append(signal)

        # 如果解析出的信号数少于批次数，用降级信号补齐
        while len(signals) < len(batch):
            signals.append(self._fallback_signal(batch[len(signals)]))

        return signals

    def _parse_signal(
        self,
        original: HotspotItem,
        data: Dict[str, Any],
    ) -> Optional[HotspotSignal]:
        """解析单条 LLM 输出为 HotspotSignal。"""
        try:
            sentiment = str(data.get("sentiment", "中性")).strip()
            if sentiment not in ("利好", "利空", "中性"):
                sentiment = "中性"

            sentiment_score = float(data.get("sentiment_score", 0))
            sentiment_score = max(-1.0, min(1.0, sentiment_score))

            impact = str(data.get("impact", "低")).strip()
            if impact not in ("高", "中", "低"):
                impact = "低"

            impact_score = float(data.get("impact_score", 0))
            impact_score = max(0.0, min(1.0, impact_score))

            related_sectors = data.get("related_sectors", [])
            if isinstance(related_sectors, str):
                related_sectors = [s.strip() for s in related_sectors.split(",") if s.strip()]
            elif not isinstance(related_sectors, list):
                related_sectors = []

            related_codes = data.get("related_codes", [])
            if isinstance(related_codes, str):
                related_codes = [c.strip() for c in related_codes.split(",") if c.strip()]
            elif not isinstance(related_codes, list):
                related_codes = []

            # 白名单校验：只保留股票池中的代码
            if self.stock_pool:
                related_codes = [c for c in related_codes if c in self.stock_pool]

            # 合并源端标记的关联代码
            if original.related_codes:
                for code in original.related_codes:
                    if code not in related_codes:
                        related_codes.append(code)

            return HotspotSignal(
                ts=original.ts,
                source=original.source,
                title=original.title,
                topic=str(data.get("topic", original.title[:20])).strip(),
                sentiment=sentiment,
                sentiment_score=round(sentiment_score, 2),
                impact=impact,
                impact_score=round(impact_score, 2),
                related_sectors=related_sectors,
                related_codes=related_codes,
                reasoning=str(data.get("reasoning", "")).strip(),
            )
        except Exception as exc:
            logger.debug(f"热点信号解析失败：{exc}")
            return None

    @staticmethod
    def _fallback_signal(item: HotspotItem) -> HotspotSignal:
        """降级信号（LLM 不可用或解析失败时）。"""
        return HotspotSignal(
            ts=item.ts,
            source=item.source,
            title=item.title,
            topic=item.title[:20],
            sentiment="中性",
            sentiment_score=0.0,
            impact="低",
            impact_score=0.0,
            related_sectors=[],
            related_codes=item.related_codes,
            reasoning="LLM 不可用或解析失败，降级为中性",
        )

    async def analyze_stream(self, item: HotspotItem) -> AsyncGenerator[str, None]:
        """单条热点的流式分析（用于 SSE 实时推送）。

        逐 token 推送 LLM 分析结果。
        """
        if not self.llm.is_available:
            yield self._fallback_signal(item).to_dict().__str__()
            return

        news_items = [{
            "title": item.title,
            "content": item.content[:300],
            "source": item.source,
            "ts": item.ts.strftime("%Y-%m-%d %H:%M"),
        }]
        user_prompt = build_hotspot_prompt(news_items, self.stock_pool)

        async for chunk in self.llm.chat_stream(
            system=SYSTEM_HOTSPOT,
            user=user_prompt,
            max_tokens=self.max_tokens,
        ):
            yield chunk

    def generate_digest(
        self,
        signals: List[HotspotSignal],
        date_str: str = "",
    ) -> str:
        """生成热点语义摘要（Markdown 文本）。

        Args:
            signals: 热点信号列表
            date_str: 日期字符串

        Returns:
            Markdown 格式的热点摘要
        """
        if not signals:
            return "今日无热点信号。"

        if not self.llm.is_available:
            # 离线降级：简单统计摘要
            return self._offline_digest(signals, date_str)

        signal_dicts = [s.to_dict() for s in signals]
        user_prompt = build_hotspot_digest_prompt(signal_dicts, date_str)

        return self.llm.chat(
            system=SYSTEM_HOTSPOT_DIGEST,
            user=user_prompt,
            max_tokens=self.max_tokens,
        )

    @staticmethod
    def _offline_digest(signals: List[HotspotSignal], date_str: str) -> str:
        """离线降级摘要（简单统计）。"""
        total = len(signals)
        positive = sum(1 for s in signals if s.sentiment == "利好")
        negative = sum(1 for s in signals if s.sentiment == "利空")
        neutral = total - positive - negative
        high_impact = [s for s in signals if s.impact == "高"]

        lines = [
            f"# {date_str} 热点摘要（离线降级）\n",
            f"共 {total} 条热点信号。",
            f"- 利好: {positive} | 利空: {negative} | 中性: {neutral}\n",
        ]
        if high_impact:
            lines.append("## 高影响力热点\n")
            for s in high_impact[:5]:
                lines.append(f"- **{s.topic}** [{s.sentiment}] — {s.title}")
        return "\n".join(lines)


# ============================================================================
# 聚合工具：将热点信号聚合为个股级情绪
# ============================================================================

def aggregate_by_code(
    signals: List[HotspotSignal],
    date: Optional[dt.date] = None,
) -> Dict[str, float]:
    """将热点信号按标的聚合为个股级热点情绪得分。

    对每个 code：
    - 取所有 related_codes 包含该 code 的信号
    - 按 impact_score 加权平均 composite_score
    - 输出 [-1, 1] 的热点情绪得分

    Args:
        signals: 热点信号列表
        date: 可选日期过滤

    Returns:
        {code: hotspot_sentiment_score} 映射
    """
    if date:
        signals = [s for s in signals if s.ts.date() == date]

    code_scores: Dict[str, List[float]] = {}
    for sig in signals:
        if not sig.related_codes:
            continue
        weight = sig.impact_score if sig.impact_score > 0 else 0.1
        for code in sig.related_codes:
            code_scores.setdefault(code, []).append(sig.composite_score * weight)

    result: Dict[str, float] = {}
    for code, scores in code_scores.items():
        if scores:
            result[code] = round(sum(scores) / len(scores), 4)
    return result
