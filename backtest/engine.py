"""共享回测引擎（pandas / numpy / scipy 实现，A 股制度）。

供 ``qlib_backtest`` / ``bt_backtest`` 复用，与 ``walk_forward`` 口径一致：
- 仅做多（A 股做空受限）：横截面选 alpha 最高 top_frac 等权；
- 多空：信号 direction=+1 做多、=-1 做空，等权；
- 应用 ``CostModel``（佣金/印花税/滑点/T+1/涨跌停流动性约束）；
- 基准 = 可投资域等权收益；
- 指标：年化、Sharpe、最大回撤、相对基准 alpha/beta（OLS）、Deflated Sharpe。

⚠️ 全部使用 ``adj_back_close``（后复权）。本模块不依赖 qlib / backtrader / quantstats，
用平台已装的 scipy / statsmodels 即可运行（与 walk_forward 同口径），因此即便这些可选
重型依赖未安装，回测也**不再返回 None**。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from backtest.cost_model import CostModel
from backtest.walk_forward import deflated_sharpe
from loguru import logger


def pivot_prices(bars_df: pd.DataFrame, universe_codes: Optional[List[str]] = None):
    """返回 (price, fwd) 宽表（后复权）。price/fwd index=date, columns=code。"""
    price = bars_df.pivot_table(index="date", columns="code", values="adj_back_close")
    fwd = price.shift(-1) / price - 1.0  # 次日收益（point-in-time）
    if universe_codes is not None:
        cols = [c for c in price.columns if c in set(universe_codes)]
        price = price[cols]
        fwd = fwd[cols]
    return price, fwd


def long_only_weights(
    alpha_wide: pd.DataFrame, top_frac: float = 0.2
) -> Dict[dt.date, pd.Series]:
    """由 alpha 宽表（date×code）生成仅做多目标权重：每日选 alpha 最高 top_frac 等权。"""
    out: Dict[dt.date, pd.Series] = {}
    for t, row in alpha_wide.iterrows():
        a = row.dropna()
        if a.empty:
            continue
        k = max(1, int(top_frac * a.notna().sum()))
        longs = a.sort_values(ascending=False).head(k).index
        w = pd.Series(0.0, index=a.index)
        w[longs] = 1.0 / k
        out[t] = w
    return out


def long_short_weights(
    score_wide: pd.DataFrame, top_frac: float = 0.2
) -> Dict[dt.date, pd.Series]:
    """由带符号 score 宽表（date×code，可正可负）生成多空目标权重：
    做多 score 最高 top_frac、做空最低 top_frac，各自等权，总敞口归一到 1。"""
    out: Dict[dt.date, pd.Series] = {}
    for t, row in score_wide.iterrows():
        s = row.dropna()
        if s.empty:
            continue
        k = max(1, int(top_frac * s.notna().sum()))
        longs = s.sort_values(ascending=False).head(k).index
        shorts = s.sort_values(ascending=True).head(k).index
        w = pd.Series(0.0, index=s.index)
        w[longs] = 1.0 / k
        w[shorts] = -1.0 / k
        out[t] = w
    return out


def simulate(
    fwd: pd.DataFrame,
    weights_by_date: Dict[dt.date, pd.Series],
    cost: CostModel,
    limit_close: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """按目标权重逐日模拟组合收益（含 A 股成本）。

    Args:
        fwd: 次日收益宽表（date×code）。
        weights_by_date: 各交易日目标权重（未归一，函数内按总敞口归一）。
        cost: CostModel。
        limit_close: 可选，close 宽表（date×code），用于涨跌停流动性约束。
    """
    dates = [d for d in fwd.index if d in weights_by_date]
    port: List[Tuple[dt.date, float]] = []
    bench: List[Tuple[dt.date, float]] = []
    prev_w: Optional[pd.Series] = None
    for t in dates:
        w = weights_by_date[t]
        if w is None or w.dropna().empty:
            prev_w = None
            continue
        # 涨跌停流动性约束（以当日 close 判定）
        if limit_close is not None and t in limit_close.index:
            close_row = limit_close.loc[t]
            keep = {}
            for code, weight in w.items():
                if code not in close_row.index or pd.isna(close_row.get(code)):
                    keep[code] = weight
                    continue
                pre = _pre_close_lookup(close_row, code, limit_close, t)
                c = float(close_row[code])
                if pre and pre > 0:
                    if weight > 0 and c >= pre * (1.0 + cost.limit_up_pct):
                        continue  # 涨停买不进
                    if weight < 0 and c <= pre * (1.0 - cost.limit_down_pct):
                        continue  # 跌停卖不出
                keep[code] = weight
            w = pd.Series(keep)
        gross = w.abs().sum()
        if gross == 0:
            prev_w = None
            continue
        w = w / gross  # 归一总敞口=1（多空 gross=1 / 仅做多 gross=1）
        if t not in fwd.index:
            prev_w = None
            continue
        r = fwd.loc[t]
        pret = float((w * r).sum())
        turnover = 1.0 if prev_w is None else float((w - prev_w).abs().sum() / 2.0)
        pret -= turnover * cost.round_trip_cost_rate()
        bret = float(r.mean())  # 基准：可投资域等权
        port.append((t, pret))
        bench.append((t, bret))
        prev_w = w
    if not port:
        return pd.DataFrame(columns=["date", "port_ret", "bench_ret"])
    ret = pd.DataFrame(port, columns=["date", "port_ret"])
    ret = ret.merge(pd.DataFrame(bench, columns=["date", "bench_ret"]), on="date")
    return ret


def _pre_close_lookup(close_row, code, limit_close, t):
    """从 limit_close 无法取到 pre_close 时，用前一交易日 close 近似。"""
    # limit_close 实为 close 宽表；pre_close 近似为前一交易日该 code 的 close
    idx = list(limit_close.index)
    if t in idx:
        i = idx.index(t)
        if i > 0:
            prev_t = idx[i - 1]
            try:
                return float(limit_close.loc[prev_t, code])
            except Exception:
                return None
    return None


def compute_metrics(ret_df: pd.DataFrame) -> Dict[str, float]:
    """由收益宽表计算绩效指标（与 walk_forward._metrics 同口径）。"""
    p = ret_df["port_ret"].dropna()
    b = ret_df["bench_ret"].dropna()
    if len(p) < 5:
        return {}
    ann = (1.0 + p.mean()) ** 252 - 1.0 if p.mean() > -1 else float("nan")
    sharpe = p.mean() / p.std(ddof=1) * np.sqrt(252) if p.std(ddof=1) > 0 else 0.0
    bsharpe = b.mean() / b.std(ddof=1) * np.sqrt(252) if b.std(ddof=1) > 0 else 0.0
    cum = (1.0 + p).cumprod()
    mdd = float(((cum - cum.cummax()) / cum.cummax()).min())
    alpha_beta = 0.0
    beta = 0.0
    try:
        from statsmodels.api import OLS
        from statsmodels.tools import add_constant

        df = pd.concat([p.rename("y"), b.rename("x")], axis=1).dropna()
        if len(df) > 5:
            model = OLS(df["y"], add_constant(df["x"])).fit()
            alpha_beta = float(model.params["const"] * 252)
            beta = float(model.params["x"])
    except Exception:  # noqa: BLE001
        pass
    dsr = deflated_sharpe(p)
    return {
        "ann_return": float(ann),
        "sharpe": float(sharpe),
        "bench_sharpe": float(bsharpe),
        "max_drawdown": mdd,
        "alpha_ann": alpha_beta,
        "beta": beta,
        "deflated_sharpe": dsr,
    }


def to_report_rows(
    ret_df: pd.DataFrame,
    metrics: Dict[str, float],
    strategy: str,
    benchmark: str,
) -> pd.DataFrame:
    """把指标字典转为 backtest_report 表结构（date/strategy/metric_name/...）。"""
    date = ret_df["date"].max() if not ret_df.empty else None
    rows = []
    for name, val in metrics.items():
        rows.append(
            {
                "date": date,
                "strategy": strategy,
                "metric_name": name,
                "metric_value": float(val),
                "benchmark": benchmark,
                "sharpe": metrics.get("sharpe", float("nan")),
                "deflated_sharpe": metrics.get("deflated_sharpe", float("nan")),
            }
        )
    return pd.DataFrame(rows)


def combine_factor_alpha(
    factor_long: pd.DataFrame,
    fwd: pd.DataFrame,
    top_frac: float = 0.2,
) -> Tuple[pd.DataFrame, Dict[dt.date, pd.Series]]:
    """由 factor_long 长表构造全样本 IC 加权 alpha 宽表 + 仅做多目标权重。

    权重 = sign(IC)·|IC|（IC 为因子在全部交易日上的平均横截面 spearman 相关）。
    """
    fwide = factor_long.pivot_table(
        index=["date", "code"], columns="factor_name", values="value"
    ).reset_index()
    fwide = fwide.pivot(index="date", columns="code")
    factor_names = [
        c for c in fwide.columns.get_level_values(0).unique() if c != "code"
    ]
    weights: Dict[str, float] = {}
    for fname in factor_names:
        try:
            fmat = fwide[fname]
        except KeyError:
            continue
        ics = []
        for d in fmat.index:
            if d not in fwd.index:
                continue
            fv = fmat.loc[d].dropna()
            rv = fwd.loc[d].reindex(fv.index).dropna()
            idx = fv.index.intersection(rv.index)
            if len(idx) < 5:
                continue
            if fv.loc[idx].nunique() < 2 or rv.loc[idx].nunique() < 2:
                continue
            rho, _ = spearmanr(fv.loc[idx], rv.loc[idx])
            if not np.isnan(rho):
                ics.append(rho)
        if ics:
            ic = float(np.mean(ics))
            weights[fname] = np.sign(ic) * max(0.0, abs(ic))

    if not weights:
        return pd.DataFrame(), {}
    # 构造每日 alpha（各因子 zscore 加权求和）
    alpha = pd.DataFrame(index=fwide.columns.get_level_values(1).unique())
    alpha.index.name = "code"
    alpha_wide = pd.DataFrame(index=fwide.index, columns=alpha.index, dtype=float)
    for fname, wgt in weights.items():
        if wgt == 0:
            continue
        try:
            col = fwide[fname]
        except KeyError:
            continue
        z = (col - col.mean()) / (col.std(ddof=0).replace(0, np.nan))
        alpha_wide = alpha_wide.add(z.fillna(0.0) * wgt, fill_value=0.0)
    alpha_wide = alpha_wide.dropna(how="all")
    weights_by_date = long_only_weights(alpha_wide, top_frac)
    return alpha_wide, weights_by_date


def signal_score_wide(
    signals_df: pd.DataFrame, top_frac: float = 0.2
) -> Dict[dt.date, pd.Series]:
    """由融合信号（含 direction/confidence）构造多空目标权重。

    score = direction × confidence；做多高分包、做空低分包。
    """
    if signals_df is None or signals_df.empty:
        return {}
    need = {"date", "code", "direction", "confidence"}
    if not need.issubset(signals_df.columns):
        return {}
    score = signals_df.copy()
    score["score"] = score["direction"] * score["confidence"].abs()
    wide = score.pivot_table(index="date", columns="code", values="score")
    return long_short_weights(wide, top_frac)


def tech_signal_weights(
    tech_df: pd.DataFrame, top_frac: float = 0.2
) -> Dict[dt.date, pd.Series]:
    """由历史技术分（tech_score ∈ [-1,1]，全历史）构造多空目标权重。

    score = tech_score（带符号）；做多高分、做空低分。对应「技术/缠论源」的
    独立回测验证（backtrader 常用于技术/TA 策略，语义贴合）。
    """
    if tech_df is None or tech_df.empty:
        return {}
    if not {"date", "code", "tech_score"}.issubset(tech_df.columns):
        return {}
    wide = tech_df.pivot_table(index="date", columns="code", values="tech_score")
    return long_short_weights(wide, top_frac)
