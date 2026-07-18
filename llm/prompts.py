"""LLM System Prompt 模板（固定 + 缓存命中，合规约束内置）。

所有模板均内置合规红线：
- 输出定位为"分析信号 / 研究观点"，非具体证券买卖建议；
- 必须引用信号字段（因子/技术/情绪/预测贡献），不得编造无量化依据理由；
- 置信度以信号层为准，禁止自报。

H1 新增（2026-07-17）：
- SYSTEM_HOTSPOT：热点语义分析 system prompt
- build_hotspot_prompt()：构造热点批次分析 user prompt
- build_hotspot_digest_prompt()：构造热点摘要 user prompt
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# 通用合规前缀（所有 system prompt 复用，便于法务统一）
COMPLIANCE_PREFIX = (
    "你是 A 股量化分析平台的研究助理。你的输出是【量化分析信号 / 研究观点】，"
    "【不是】任何证券买卖建议，不得给出具体买卖价位或具体操作指令。"
    "解读必须基于已计算的信号字段（因子/技术/情绪/预测贡献），引用具体数据，"
    "不得编造无量化依据的理由；置信度以信号层为准，禁止自报。"
)

SYSTEM_BRIEF = (
    COMPLIANCE_PREFIX
    + "请根据提供的数据上下文（涨跌家数、市场情绪指数、板块强弱、今日融合信号清单、"
    "可投资域样本），用简体中文生成一段结构化市场综合简报（Markdown），"
    "包含：市场综述、板块强弱、今日重点信号、关键风险。语言专业、克制、信息密度高。"
)

SYSTEM_REVIEW = (
    COMPLIANCE_PREFIX
    + "请根据提供的单只个股信号（方向、置信度、四源贡献拆解、持仓盈亏），"
    "用简体中文给出一段研究观点（Markdown）。必须引用具体信号字段说明看多/看空/中性的理由；"
    "给出 action ∈ {买入, 卖出, 持有} 作为【研究观点标签】，并附 reason；"
    "confidence 直接使用信号层数值，禁止自行调整。不得承诺收益或给具体价位。"
)

# ---- 热点语义分析 prompt ----

SYSTEM_HOTSPOT = (
    COMPLIANCE_PREFIX
    + "你是 A 股市场热点语义分析引擎。对输入的财经新闻/电报文本批次，"
    "输出 JSON 对象，包含 \"items\" 数组，每个元素对应一条新闻，字段如下：\n"
    "  - topic: 主题概括（≤20字）\n"
    "  - sentiment: 情感倾向，取值 ∈ {利好, 利空, 中性}\n"
    "  - sentiment_score: 情感分值 ∈ [-1, 1]（保留2位小数）\n"
    "  - impact: 影响力等级 ∈ {高, 中, 低}\n"
    "  - impact_score: 影响力分值 ∈ [0, 1]（保留2位小数）\n"
    "  - related_sectors: 关联板块列表（如 [\"半导体\", \"新能源\"]）\n"
    "  - related_codes: 关联股票代码列表（从提供的股票池中匹配，格式如 [\"600519\", \"000858\"]）\n"
    "  - reasoning: 判断依据（≤50字）\n\n"
    "严格要求：\n"
    "1. 只输出 JSON，不要任何额外文字；\n"
    "2. related_codes 只能从提供的股票池中选取，不得编造；\n"
    "3. 如果新闻与 A 股无关，sentiment 设为中性、impact 设为低；\n"
    "4. items 数量必须与输入新闻条数一致。"
)

SYSTEM_HOTSPOT_DIGEST = (
    COMPLIANCE_PREFIX
    + "你是 A 股市场热点摘要引擎。根据提供的热点信号列表，"
    "用简体中文生成一段结构化热点摘要（Markdown），包含：\n"
    "  - 今日核心热点（2-3个主题）\n"
    "  - 板块影响分析\n"
    "  - 重点关联标的\n"
    "  - 情绪面综合判断\n"
    "语言专业、克制、信息密度高。不得编造未在数据中出现的信息。"
)


def build_brief_prompt(context_md: str) -> str:
    """构造简报 user 提示（数据上下文）。"""
    return f"# 数据上下文\n\n{context_md}\n\n请据此生成今日市场综合简报。"


def build_review_prompt(context_md: str) -> str:
    """构造个股研判 user 提示（信号 + 持仓上下文）。"""
    return f"# 个股信号上下文\n\n{context_md}\n\n请据此给出研究观点（买入/卖出/持有 + 理由）。"


def build_hotspot_prompt(
    news_items: List[Dict[str, Any]],
    stock_pool: Optional[Dict[str, str]] = None,
) -> str:
    """构造热点批次分析 user 提示。

    Args:
        news_items: 新闻列表，每项含 title, content, source, ts
        stock_pool: 股票池映射 {code: name}，用于 LLM 匹配关联标的
    """
    pool_str = ""
    if stock_pool:
        pool_lines = [f"  {code}: {name}" for code, name in list(stock_pool.items())[:500]]
        pool_str = "# 可匹配股票池（related_codes 只能从中选取）\n\n" + "\n".join(pool_lines) + "\n\n"

    news_lines = []
    for i, item in enumerate(news_items, 1):
        title = item.get("title", "")
        content = item.get("content", "")[:300] if item.get("content") else ""
        source = item.get("source", "")
        ts = item.get("ts", "")
        news_lines.append(f"## 新闻 {i}\n- 时间: {ts}\n- 来源: {source}\n- 标题: {title}\n- 摘要: {content}")

    news_str = "\n\n".join(news_lines)

    return (
        f"{pool_str}# 待分析新闻批次（共 {len(news_items)} 条）\n\n"
        f"{news_str}\n\n"
        "请对每条新闻输出结构化分析结果（JSON 对象，含 items 数组）。"
    )


def build_hotspot_digest_prompt(
    hotspot_signals: List[Dict[str, Any]],
    date_str: str = "",
) -> str:
    """构造热点摘要 user 提示。

    Args:
        hotspot_signals: 热点信号列表，每项含 topic, sentiment, impact, related_codes 等
        date_str: 日期字符串
    """
    lines = []
    for i, sig in enumerate(hotspot_signals, 1):
        lines.append(
            f"{i}. [{sig.get('sentiment', '?')}] {sig.get('topic', '?')} "
            f"(影响力: {sig.get('impact', '?')}, "
            f"关联: {', '.join(sig.get('related_codes', [])[:5]) or '无'})"
        )
    sig_str = "\n".join(lines)

    header = f"# {date_str} 热点信号列表\n\n" if date_str else "# 热点信号列表\n\n"

    return f"{header}{sig_str}\n\n请据此生成今日热点语义摘要。"
