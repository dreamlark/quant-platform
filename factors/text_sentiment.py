"""文本情绪（融合第 3 源 · T3 LLM 文本情绪，门控）。

利用 LLM 对财经新闻/股吧文本做语义解析，输出市场文本情绪得分（负面=下行预警，
对齐东吴证券发现：负面情绪是未来下跌的强预警）。无 DEEPSEEK_API_KEY（LLM 离线降级）
或无可读新闻时返回空，不进核心。

H1 修复（2026-07-17）：
- 修复接口断裂：LLMClient 新增 complete() 方法，TextSentiment 不再永远跳过
- 增加结果返回，供 orchestrator 落库
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

import pandas as pd

from loguru import logger
from sources import sentiment_data as sd


class TextSentiment:
    """LLM 文本情绪（门控）。"""

    def __init__(self, cfg: Optional[Dict] = None, llm=None) -> None:
        self.cfg = cfg or {}
        self.llm = llm

    def analyze(self, date: dt.date, codes: List[str], top_n: int = 30) -> pd.DataFrame:
        """对 top_n 只标的新闻做文本情绪打分，返回市场级聚合一行。

        H1 修复：使用 ``self.llm.complete()`` 方法（LLMClient 已新增兼容接口）。
        """
        if self.llm is None:
            logger.info("文本情绪：LLM 未配置（离线降级），跳过")
            return pd.DataFrame()
        try:
            sample = codes[:top_n]
            texts: List[str] = []
            for code in sample:
                texts.extend(sd.load_news(code, self.cfg, limit=10))
            if not texts:
                logger.info("文本情绪：无可读新闻，跳过")
                return pd.DataFrame()
            digest = "\n".join(t[:200] for t in texts[:200])
            prompt = (
                "你是量化情绪分析师。下面是一批A股近期新闻标题/摘要。"
                "请只输出一个 -1 到 1 之间的数字表示整体市场文本情绪"
                "（负值=偏悲观/利空，正值=偏乐观/利多），不要解释：\n" + digest
            )
            out = self.llm.complete(prompt)
            score = self._parse(out)
            if score is None:
                logger.warning("文本情绪：LLM 输出无法解析为数字")
                return pd.DataFrame()
            logger.info(f"文本情绪：date={date} score={score:.3f}（基于 {len(texts)} 条新闻）")
            return pd.DataFrame([{"date": date, "text_sentiment": score}])
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"文本情绪计算失败（降级）：{exc}")
            return pd.DataFrame()

    @staticmethod
    def _parse(text: str) -> Optional[float]:
        for x in re.findall(r"-?\d+(?:\.\d+)?", text or ""):
            v = float(x)
            if -1.0 <= v <= 1.0:
                return v
        return None
