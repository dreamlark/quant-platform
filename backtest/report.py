"""绩效报告生成（quantstats 懒加载 + 回退）。

⚠️ ``quantstats`` 为可选依赖，懒加载；未安装时回退为基础指标字典。
报告内容（quantstats 现代依赖、蒙特卡洛）仅展示，不执行交易。
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from loguru import logger


def generate_report(
    returns_df: pd.DataFrame, metrics: Dict[str, float], cfg
) -> Dict:
    """生成绩效报告（优先 quantstats 文本，回退为指标字典）。"""
    try:
        import quantstats as qs  # noqa: F401
    except ImportError:
        logger.debug("quantstats 未安装，绩效报告回退为基础指标字典")
        return {"metrics": metrics, "engine": "builtin"}

    # 真实实现：qs.reports.metrics(returns_series) 等
    logger.info("quantstats 已安装，可生成完整绩效 tear-sheet（此处保留接口）")
    return {"metrics": metrics, "engine": "quantstats"}


def summarize_metrics(metrics: Dict[str, float]) -> str:
    """把指标字典渲染为 Markdown 摘要。"""
    if not metrics:
        return "_（样本不足，未生成回测指标）_"
    lines = ["### 回测绩效（walk-forward，含 A 股成本模型）", ""]
    label = {
        "ann_return": "年化收益(净·头条)",
        "ann_return_gross": "年化收益(毛·未扣成本)",
        "timing_ann_return": "择时年化收益(净)",
        "timing_ann_return_gross": "择时年化收益(毛)",
        "baseline_ann_return": "因子满仓年化(净)",
        "baseline_ann_return_gross": "因子满仓年化(毛)",
        "sharpe": "Sharpe",
        "bench_sharpe": "基准 Sharpe",
        "max_drawdown": "最大回撤",
        "alpha_ann": "年化 Alpha(相对基准)",
        "beta": "Beta",
        "deflated_sharpe": "Deflated Sharpe",
    }
    for k, v in metrics.items():
        if k in label:
            lines.append(f"- {label[k]}：{v:.4f}")
    return "\n".join(lines)
