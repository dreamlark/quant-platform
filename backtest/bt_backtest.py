"""backtrader 风格回测（技术/缠论源交叉验证引擎）。

基于**历史技术分（tech_score ∈ [-1,1]，全历史）**构造多空组合：做多高分、做空低分，
应用 A 股成本模型，与 ``walk_forward``（因子 walk-forward IC 加权）/ ``qlib_backtest``
（因子全样本 IC 加权）构成交叉验证。这是**对「技术/缠论源」本身**的回测——验证 czsc 笔
结构技术分是否真有超额。

> 注：融合信号表（``signals``）仅存当日信号（point-in-time 日频），无历史序列，无法直接
> 回测；而 ``tech_score`` 以 ``factor_values(tech_signal)`` 形式全历史落库，故本引擎回测技术分。
> backtrader 本就常用于技术/TA 策略，语义贴合。

⚠️ ``backtrader`` 为可选重型依赖（GPL），仅运行时懒加载；本引擎用平台已装的
scipy / statsmodels 即可运行，**不依赖 backtrader 是否安装**。若未来需 backtrader 的
``Cerebro`` 事件驱动口径，可在 ``_run_cerebro`` 内接入（A 股制度约束需自定义 Commission 类）。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd

from backtest.cost_model import CostModel
from backtest.engine import (
    compute_metrics,
    pivot_prices,
    tech_signal_weights,
    simulate,
    to_report_rows,
)
from loguru import logger


def run_backtrader(
    bars_df: pd.DataFrame,
    tech_df: pd.DataFrame,
    universe_df: pd.DataFrame,
    cfg,
    warmup: int = 250,
    start_date=None,
) -> Optional[Tuple[pd.DataFrame, Dict[str, float], pd.DataFrame]]:
    """技术/缠论分多空回测（backtrader 风格交叉验证）。

    Args:
        tech_df: 历史技术分长表 (date, code, tech_score)，全历史。
        warmup: 跳过前 warmup 个交易日再统计（start_date 未指定时的回退对齐）。
        start_date: 强制测试起点（与 walk_forward 实际测试起点对齐，使三引擎基准可比）。
    Returns:
        (returns_df, metrics, report_rows) 或 None（输入不足时）。
    """
    if bars_df is None or bars_df.empty or tech_df is None or tech_df.empty:
        return None
    try:
        import backtrader  # noqa: F401

        logger.debug("检测到 backtrader（当前交叉验证走平台自包含引擎，结果一致）")
    except ImportError:
        pass  # 平台自包含引擎不依赖 backtrader

    codes = None
    if universe_df is not None and not universe_df.empty:
        codes = universe_df[universe_df.get("in_universe", True)]["code"].unique().tolist()

    price, fwd = pivot_prices(bars_df, codes)
    close_wide = bars_df.pivot_table(index="date", columns="code", values="close")
    if codes is not None:
        close_wide = close_wide[[c for c in close_wide.columns if c in set(codes)]]

    weights_by_date = tech_signal_weights(tech_df, top_frac=0.2)
    if not weights_by_date:
        logger.warning("backtrader 回测：无有效技术分权重，跳过")
        return None

    # 对齐：优先用 start_date（与 walk_forward 实际测试起点一致）；否则回退 warmup
    if start_date is not None:
        weights_by_date = {d: w for d, w in weights_by_date.items() if d >= start_date}
        logger.debug(f"backtrader 技术分回测对齐测试起点：start_date={start_date}")
    elif warmup and len(weights_by_date) > warmup:
        cut = sorted(weights_by_date.keys())[warmup]
        weights_by_date = {d: w for d, w in weights_by_date.items() if d >= cut}

    cost = CostModel(cfg)
    ret_df = simulate(fwd, weights_by_date, cost, limit_close=close_wide)
    if ret_df.empty:
        return None
    metrics = compute_metrics(ret_df)
    report_rows = to_report_rows(ret_df, metrics, "tech_long_short", "zz_quan_zhi,hs300")
    logger.info(
        f"backtrader（技术分多空）回测完成：样本外 {len(ret_df)} 日，"
        f"年化 {metrics.get('ann_return', 0) * 100:.1f}%，Sharpe {metrics.get('sharpe', 0):.2f}"
    )
    return ret_df, metrics, report_rows
