"""A 股交易成本与制度模型（P1-1）。

建模 A 股真实交易制度：
- 双边佣金（万 2.5，单笔最低 5 元）
- 印花税（卖出千 1）
- 滑点（bp 级）
- T+1（当日买入次交易日方可卖出）
- 涨跌停流动性约束（涨停不买、跌停不卖）

回测中「close 成交」假设在涨停/跌停日会失真，本模型予以纠正。
"""
from __future__ import annotations

from typing import Dict, Optional


class CostModel:
    """A 股交易成本与制度模型。"""

    def __init__(self, cfg: Optional[Dict] = None) -> None:
        cfg = (cfg or {}).get("cost_model", {})
        self.commission: float = float(cfg.get("commission", 0.00025))
        self.stamp_duty: float = float(cfg.get("stamp_duty", 0.001))
        self.slippage_bps: float = float(cfg.get("slippage_bps", 2.0))
        self.min_commission: float = float(cfg.get("min_commission", 5.0))
        self.limit_up_pct: float = float(cfg.get("limit_up_pct", 0.10))
        self.limit_down_pct: float = float(cfg.get("limit_down_pct", 0.10))
        self.t_plus_one: bool = bool(cfg.get("t_plus_one", True))

    # ---- 流动性约束 ----------------------------------------------
    def can_trade(self, side: str, price: float, pre_close: float) -> bool:
        """涨跌停流动性约束：涨停不买、跌停不卖。"""
        if pre_close <= 0 or price <= 0:
            return False
        limit_up = pre_close * (1.0 + self.limit_up_pct)
        limit_down = pre_close * (1.0 - self.limit_down_pct)
        if side == "buy":
            return price < limit_up  # 涨停买不进
        if side == "sell":
            return price > limit_down  # 跌停卖不出
        return True

    # ---- 成本计算 ------------------------------------------------
    def commission_of(self, value: float) -> float:
        if value <= 0:
            return 0.0
        return max(value * self.commission, self.min_commission)

    def slippage_of(self, value: float) -> float:
        return value * self.slippage_bps / 1e4

    def stamp_of(self, value: float) -> float:
        return value * self.stamp_duty

    def cost(self, side: str, price: float, value: float) -> float:
        """单边交易成本（元）。value = 成交金额。"""
        c = self.commission_of(value) + self.slippage_of(value)
        if side == "sell":
            c += self.stamp_of(value)
        return c

    def round_trip_cost_rate(self) -> float:
        """往返（买+卖）成本率近似（不含滑点/最低佣金），用于快速估算。"""
        return 2.0 * self.commission + self.stamp_duty + 2.0 * self.slippage_bps / 1e4
