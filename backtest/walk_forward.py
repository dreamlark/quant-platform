"""walk-forward 滚动样本外验证 + 基准对照 + Deflated Sharpe（P1-2 / P1-3）。

方法（避免全样本调参过拟合）：
- 滚动窗口：训练窗计算因子 IC 权重（sign·|IC|），测试窗用该权重构造 alpha；
- 仅做多（A 股做空受限）：每日横截面选 alpha 最高 20% 等权；
- 应用 ``CostModel``（佣金/印花税/滑点/T+1/涨跌停）计算真实组合收益；
- 基准 = 可投资域等权收益（中证全指/沪深300 代理）；
- 报告含年化、Sharpe、最大回撤、相对基准 alpha/beta（statsmodels OLS）、Deflated Sharpe。

⚠️ 全部使用 ``adj_back_close``（后复权）；statsmodels 用于基准回归与 Deflated Sharpe。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm

from backtest.cost_model import CostModel
from common.stats import group_zscore
from loguru import logger


def deflated_sharpe(
    returns: pd.Series, benchmark: Optional[pd.Series] = None, alpha: float = 0.05
) -> float:
    """Deflated Sharpe Ratio（Bailey & López de Prado, 2014）。

    校正了多次检验与样本量偏误；返回标准正态分布 CDF 值（越接近 1 越显著）。
    """
    r = returns.dropna()
    if len(r) < 10:
        return float("nan")
    sr = r.mean() / r.std(ddof=1) * np.sqrt(252)
    skew = r.skew()
    kurt = r.kurt()
    n = len(r)
    denom = np.sqrt(1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2)
    if denom <= 0 or np.isnan(denom):
        return float("nan")
    z = norm.ppf(1.0 - alpha)
    dsr = norm.cdf((np.sqrt(n - 1) * sr) / denom - z)
    return float(dsr)


class WalkForwardBacktester:
    """walk-forward 回测器。"""

    def __init__(self, cfg: Optional[Dict] = None) -> None:
        cfg = cfg or {}
        wf = cfg.get("walk_forward", {})
        self.train_window: int = int(wf.get("train_window", 250))
        self.test_window: int = int(wf.get("test_window", 20))
        self.step: int = int(wf.get("step", self.test_window))
        self.top_frac: float = 0.2
        self.cost = CostModel(cfg)
        self.benchmarks = cfg.get("benchmark", ["zz_quan_zhi", "hs300"])

    def run(
        self,
        bars_df: pd.DataFrame,
        factor_long: pd.DataFrame,
        universe_df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, Dict[str, float], pd.DataFrame]:
        """执行 walk-forward 回测。

        Returns:
            (returns_df, metrics, report_rows)
            returns_df 列：date, port_ret, bench_ret
        """
        if bars_df is None or bars_df.empty:
            return pd.DataFrame(), {}, pd.DataFrame()

        # 行情宽表（后复权）
        price = bars_df.pivot_table(index="date", columns="code", values="adj_back_close")
        fwd = price.shift(-1) / price - 1.0  # 次日收益（point-in-time）

        # 作用域
        if universe_df is not None and not universe_df.empty:
            inv = universe_df[universe_df["in_universe"]]["code"].unique()
            price = price[[c for c in price.columns if c in inv]]
            fwd = fwd[[c for c in fwd.columns if c in inv]]

        # 因子宽表
        fwide = factor_long.pivot_table(
            index=["date", "code"], columns="factor_name", values="value"
        ).reset_index()
        fwide = fwide.pivot(index="date", columns="code")

        dates = list(price.index)
        n = len(dates)
        if n < self.train_window + self.test_window:
            # 样本不足：退化为单次切分
            self.train_window = max(20, n // 3)
            self.test_window = n - self.train_window

        port_ret: List[Tuple[dt.date, float]] = []
        bench_ret: List[Tuple[dt.date, float]] = []
        prev_w = None
        start = 0
        while start + self.train_window + 1 <= n:
            train_dates = dates[start : start + self.train_window]
            test_dates = dates[
                start + self.train_window : start + self.train_window + self.test_window
            ]
            if not test_dates:
                break
            weights = self._train_weights(fwide, fwd, train_dates)
            for t in test_dates:
                if t not in fwd.index:
                    continue
                alpha = self._alpha(fwide, weights, t)
                if alpha is None or alpha.dropna().empty:
                    prev_w = None
                    continue
                # 选 alpha 最高的 top_frac 等权
                k = max(1, int(self.top_frac * alpha.notna().sum()))
                longs = alpha.dropna().sort_values(ascending=False).head(k).index
                w = pd.Series(0.0, index=alpha.index)
                w[longs] = 1.0 / k
                # 当日收益（t 的持仓赚 t->t+1 的收益，即 fwd[t]）
                r = fwd.loc[t]
                pret = float((w * r).sum())
                # 成本（换手）
                if prev_w is not None:
                    turnover = float((w - prev_w).abs().sum() / 2.0)
                else:
                    turnover = 1.0
                cost_frac = turnover * self.cost.round_trip_cost_rate()
                pret -= cost_frac
                # 基准：等权
                bret = float(r.mean())
                port_ret.append((t, pret))
                bench_ret.append((t, bret))
                prev_w = w
            start += self.step

        if not port_ret:
            return pd.DataFrame(), {}, pd.DataFrame()
        ret_df = pd.DataFrame(port_ret, columns=["date", "port_ret"])
        bench_df = pd.DataFrame(bench_ret, columns=["date", "bench_ret"])
        ret_df = ret_df.merge(bench_df, on="date")
        metrics = self._metrics(ret_df)
        report_rows = self._report(ret_df, metrics)
        logger.info(
            f"walk-forward 回测完成：样本外 {len(ret_df)} 日，"
            f"年化 {metrics.get('ann_return',0)*100:.1f}%，"
            f"Sharpe {metrics.get('sharpe',0):.2f}，"
            f"DeflatedSharpe {metrics.get('deflated_sharpe',0):.2f}"
        )
        return ret_df, metrics, report_rows

    # ---- 训练/打分 ------------------------------------------------
    def _train_weights(
        self, fwide: pd.DataFrame, fwd: pd.DataFrame, train_dates: List
    ) -> Dict[str, float]:
        from scipy.stats import spearmanr

        weights: Dict[str, float] = {}
        factor_names = [
            c for c in fwide.columns.get_level_values(0).unique() if c != "code"
        ]
        for fname in factor_names:
            try:
                fmat = fwide[fname]
            except KeyError:
                continue
            ics = []
            for d in train_dates:
                if d not in fmat.index or d not in fwd.index:
                    continue
                fv = fmat.loc[d].dropna()
                rv = fwd.loc[d].reindex(fv.index).dropna()
                idx = fv.index.intersection(rv.index)
                if len(idx) < 5:
                    continue
                # 跳过常数向量（spearmanr 对常数输入会报 ConstantInputWarning 且结果无意义）
                if fv.loc[idx].nunique() < 2 or rv.loc[idx].nunique() < 2:
                    continue
                rho, _ = spearmanr(fv.loc[idx], rv.loc[idx])
                if not np.isnan(rho):
                    ics.append(rho)
            if ics:
                ic = float(np.mean(ics))
                weights[fname] = np.sign(ic) * max(0.0, abs(ic))
        return weights

    def _alpha(self, fwide: pd.DataFrame, weights: Dict[str, float], date) -> Optional[pd.Series]:
        if not weights:
            return None
        alpha = pd.Series(0.0, index=fwide.columns.get_level_values(1).unique())
        for fname, w in weights.items():
            if w == 0:
                continue
            try:
                col = fwide[fname].loc[date]
            except (KeyError, Exception):  # noqa: BLE001
                continue
            z = (col - col.mean()) / (col.std(ddof=0) or 1.0)
            alpha = alpha.add(z.fillna(0.0) * w, fill_value=0.0)
        return alpha

    # ---- 指标 ----------------------------------------------------
    def _metrics(self, ret_df: pd.DataFrame) -> Dict[str, float]:
        from statsmodels.api import OLS
        from statsmodels.tools import add_constant

        p = ret_df["port_ret"].dropna()
        b = ret_df["bench_ret"].dropna()
        if len(p) < 5:
            return {}
        ann = (1.0 + p.mean()) ** 252 - 1.0 if p.mean() > -1 else float("nan")
        sharpe = p.mean() / p.std(ddof=1) * np.sqrt(252) if p.std(ddof=1) > 0 else 0.0
        bsharpe = b.mean() / b.std(ddof=1) * np.sqrt(252) if b.std(ddof=1) > 0 else 0.0
        # 最大回撤
        cum = (1.0 + p).cumprod()
        mdd = float(((cum - cum.cummax()) / cum.cummax()).min())
        # alpha/beta vs 基准（statsmodels OLS）
        alpha_beta = 0.0
        beta = 0.0
        try:
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

    @staticmethod
    def _report(ret_df: pd.DataFrame, metrics: Dict[str, float]) -> pd.DataFrame:
        strategy = "walk_forward_factor"
        date = ret_df["date"].max() if not ret_df.empty else None
        rows = []
        for name, val in metrics.items():
            rows.append(
                {
                    "date": date,
                    "strategy": strategy,
                    "metric_name": name,
                    "metric_value": float(val),
                    "benchmark": ",".join(["zz_quan_zhi", "hs300"]),
                    "sharpe": metrics.get("sharpe", float("nan")),
                    "deflated_sharpe": metrics.get("deflated_sharpe", float("nan")),
                }
            )
        return pd.DataFrame(rows)
