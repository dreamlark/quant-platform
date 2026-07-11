"""信号推送预留接口（P2 / F-10，首版仅看板内展示，不主动推送）。

架构决策：MVP 仅看板内展示信号；移动端/邮件推送为 P2 扩展，仅定义干净边界不实现。
后续启用时实现 ``push_daily``（可接企业微信/邮件/Webhook）。
"""
from __future__ import annotations

from typing import List, Optional


class SignalPusher:
    """信号推送接口（预留）。"""

    def __init__(self, cfg: Optional[dict] = None) -> None:
        self.cfg = cfg or {}
        self.enabled = False  # 首版关闭

    def push_daily(self, date, signals: List[dict]) -> dict:
        """预留：将当日信号推送到外部渠道。

        Raises:
            NotImplementedError: 首版未启用。
        """
        raise NotImplementedError(
            "信号推送（移动端/邮件/Webhook）为 P2 预留能力，首版仅看板内展示。"
            "请通过配置开启对应渠道后实现。"
        )
