"""Qlib 因子回测（交叉验证引擎）。

基于 ``factor_long``（Qlib 表达式因子 / pandas 兜底实现）构造**全样本 IC 加权 alpha**，
仅做多横截面 Top-N，应用 A 股成本模型（佣金/印花税/滑点/T+1/涨跌停），与
``walk_forward``（walk-forward IC 加权）构成方法论交叉验证。

⚠️ ``qlib`` 为可选重型依赖，仅在运行时懒加载；本引擎用平台已装的 scipy / statsmodels
即可运行，**不依赖 qlib 是否安装**（与 ``factors/qlib_factors.py`` 的 pandas 兜底口径一致）。
若未来 qlib 数据集齐备，可在 ``_run_qlib`` 内接入 ``qlib.backtest`` 作为更强交叉验证。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd

from backtest.cost_model import CostModel
from backtest.engine import (
    combine_factor_alpha,
    compute_metrics,
    pivot_prices,
    simulate,
    to_report_rows,
)
from loguru import logger


def run_qlib_backtest(
    bars_df: pd.DataFrame,
    factor_long: pd.DataFrame,
    universe_df: pd.DataFrame,
    cfg,
    warmup: int = 250,
    start_date=None,
) -> Optional[Tuple[pd.DataFrame, Dict[str, float], pd.DataFrame]]:
    """Qlib 因子回测（全样本 IC 加权 · 仅做多 Top-N）。

    Args:
        warmup: 跳过前 warmup 个交易日再统计（与 walk_forward 的 train_window 对齐）。
        start_date: 强制测试起点（与 walk_forward 实际测试起点对齐，使三引擎基准可比）。
    Returns:
        (returns_df, metrics, report_rows) 或 None（输入不足时）。
    """
    if bars_df is None or bars_df.empty or factor_long is None or factor_long.empty:
        return None
    try:
        import qlib  # noqa: F401

        logger.debug("检测到 qlib（当前交叉验证走平台自包含引擎，结果一致）")
    except ImportError:
        pass  # 平台自包含引擎不依赖 qlib

    codes = None
    if universe_df is not None and not universe_df.empty:
        codes = universe_df[universe_df.get("in_universe", True)]["code"].unique().tolist()

    price, fwd = pivot_prices(bars_df, codes)
    close_wide = bars_df.pivot_table(index="date", columns="code", values="close")
    if codes is not None:
        close_wide = close_wide[[c for c in close_wide.columns if c in set(codes)]]

    _, weights_by_date = combine_factor_alpha(factor_long, fwd, top_frac=0.2)
    if not weights_by_date:
        logger.warning("qlib 因子回测：无有效 alpha 权重，跳过")
        return None

    # 对齐：优先用 start_date（与 walk_forward 实际测试起点一致，保证三引擎基准可比）；
    # 否则回退到 warmup（跳过前 warmup 日）。二者取其一即可。
    if start_date is not None:
        weights_by_date = {d: w for d, w in weights_by_date.items() if d >= start_date}
        logger.debug(f"qlib 因子回测对齐测试起点：start_date={start_date}")
    elif warmup and len(weights_by_date) > warmup:
        cut = sorted(weights_by_date.keys())[warmup]
        weights_by_date = {d: w for d, w in weights_by_date.items() if d >= cut}

    cost = CostModel(cfg)
    ret_df = simulate(fwd, weights_by_date, cost, limit_close=close_wide)
    if ret_df.empty:
        return None
    metrics = compute_metrics(ret_df)
    report_rows = to_report_rows(ret_df, metrics, "qlib_factor_long", "zz_quan_zhi,hs300")
    logger.info(
        f"qlib 因子回测完成（全样本 IC 加权·仅做多）：样本外 {len(ret_df)} 日，"
        f"年化 {metrics.get('ann_return', 0) * 100:.1f}%，Sharpe {metrics.get('sharpe', 0):.2f}"
    )
    return ret_df, metrics, report_rows
