"""自动因子挖掘预留接口（P2 / F-16，首版不启用）。

架构决策：RD-Agent 强依赖 Docker + 算力，首版仅定义干净边界不实现。
后续启用时实现 ``mine_factors``（需 Docker 运行时 + 评估后注入信号池）。
"""
from __future__ import annotations

from typing import List, Optional


class FactorMiningInterface:
    """自动因子挖掘接口（预留）。"""

    def __init__(self, cfg: Optional[dict] = None) -> None:
        self.cfg = cfg or {}
        self.enabled = False  # 首版关闭

    def mine_factors(self, target_metric: str = "ic") -> List[dict]:
        """预留：自动挖掘并评估新因子入口。

        Raises:
            NotImplementedError: 首版未启用。
        """
        raise NotImplementedError(
            "自动因子挖掘（RD-Agent）为 P2 预留能力，首版未启用。"
            "请接入 Docker 运行时后实现，并经过因子体检（alphalens）评估再注入信号池。"
        )
