"""多 Agent 研判预留接口（P2 / F-13，首版不启用）。

架构决策：首版仅 DeepSeek V3 单模型；TradingAgents-CN 式多 Agent 仅定义干净边界，
不实现（避免多 Agent 高成本与专有许可风险）。后续启用时实现 ``run_agents`` 即可。
"""
from __future__ import annotations

from typing import List, Optional


class AgentInterface:
    """多 Agent 研判接口（预留）。"""

    def __init__(self, cfg: Optional[dict] = None) -> None:
        self.cfg = cfg or {}
        self.enabled = False  # 首版关闭

    def run_agents(self, tickers: List[str], date) -> dict:
        """预留：多 Agent 协同研判入口。

        Raises:
            NotImplementedError: 首版未启用。
        """
        raise NotImplementedError(
            "多 Agent 研判（TradingAgents-CN）为 P2 预留能力，首版未启用。"
            "请通过 feature flag 开启并在配置中接入对应运行时。"
        )
