"""因子计算引擎（Qlib Alpha158/360 表达式因子，懒加载）。

⚠️ ``qlib`` 为可选重型依赖，仅在 ``_try_qlib`` 内懒加载；未安装时**自动降级**为
内置 pandas 因子库（覆盖 ``config/factors.yaml`` 中全部因子）。核心流水线不依赖 qlib。

方法学红线（P0-1）：所有价格类因子统一读取 ``adj_back_close``（后复权），
**绝不**使用 ``adj_front_close``（前复权，仅前端展示）。

因子命名 ``f_<domain>_<name>``，方向见 ``config/factors.yaml``（1 值越大越看多 / -1 越大越看空）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from loguru import logger


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi.fillna(50.0)


# 单标的因子函数注册表：输入 per-stock DataFrame（含 adj_back_close 等），输出同索引 Series
_FACTOR_REGISTRY = {
    "f_momentum_5": lambda g: g["adj_back_close"] / g["adj_back_close"].shift(5) - 1,
    "f_momentum_20": lambda g: g["adj_back_close"] / g["adj_back_close"].shift(20) - 1,
    "f_reversal_5": lambda g: g["adj_back_close"].shift(5) / g["adj_back_close"] - 1,
    "f_trend_60": lambda g: g["adj_back_close"] / g["adj_back_close"].rolling(60).mean() - 1,
    "f_volatility_20": lambda g: np.log(g["adj_back_close"] / g["adj_back_close"].shift(1)).rolling(20).std(),
    "f_volume_ratio_20": lambda g: g["vol"] / g["vol"].rolling(20).mean(),
    "f_amount_growth_20": lambda g: g["amount"] / g["amount"].rolling(20).mean() - 1,
    "f_amplitude_20": lambda g: (g["high"] - g["low"]).rolling(20).mean() / g["adj_back_close"],
    "f_rsi_14": lambda g: _rsi(g["adj_back_close"], 14),
    "f_high_low_pos_20": lambda g: (
        (g["adj_back_close"] - g["low"].rolling(20).min())
        / (g["high"].rolling(20).max() - g["low"].rolling(20).min()).replace(0, np.nan)
    ),
    "f_breakout_60": lambda g: g["adj_back_close"] / g["high"].rolling(60).max() - 1,
    "f_turnover_trend": lambda g: g["vol"].rolling(5).mean() / g["vol"].rolling(20).mean() - 1,
}


class QlibFactorEngine:
    """因子计算引擎（pandas 实现；可选 qlib 增强）。"""

    def __init__(self, factor_names: list[str] | None = None) -> None:
        self.factor_names = factor_names or list(_FACTOR_REGISTRY.keys())
        self._qlib = self._try_qlib()

    @staticmethod
    def _try_qlib():
        try:
            import qlib  # noqa: F401

            logger.debug("检测到 qlib，可使用 Alpha158/360 表达式因子（当前用 pandas 库兜底）")
            return True
        except ImportError:
            return False

    def compute(self, bars_df: pd.DataFrame) -> pd.DataFrame:
        """计算全部因子，返回长表 (date, code, factor_name, value)。

        Args:
            bars_df: 必须含 ``code`` / ``date`` / ``adj_back_close`` / ``vol`` / ``amount`` /
                ``high`` / ``low`` / ``open`` / ``close``。
        """
        if bars_df is None or bars_df.empty:
            return pd.DataFrame(columns=["date", "code", "factor_name", "value"])

        parts = []
        for code, g in bars_df.groupby("code", sort=False):
            g = g.sort_values("date").reset_index(drop=True)
            for name in self.factor_names:
                func = _FACTOR_REGISTRY.get(name)
                if func is None:
                    logger.warning(f"因子 {name} 无计算实现，跳过")
                    continue
                try:
                    val = func(g)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"因子 {name} 计算失败（{code}）：{exc}")
                    val = pd.Series(np.nan, index=g.index)
                sub = pd.DataFrame(
                    {
                        "date": g["date"].values,
                        "code": code,
                        "factor_name": name,
                        "value": val.values,
                    }
                )
                parts.append(sub)
        if not parts:
            return pd.DataFrame(columns=["date", "code", "factor_name", "value"])
        return pd.concat(parts, ignore_index=True)
