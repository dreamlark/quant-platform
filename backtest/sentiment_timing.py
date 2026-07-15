"""T2 温度计择时信号「样本外」验证（PRD §10 验收硬指标）。

用市场综合情绪指数（``sentiment_index.signal``：买入 / 半仓 / 空仓）作为**权益暴露叠加层**，
叠加在因子 walk-forward 组合之上，做滚动样本外回测：

- 买入 → 满仓（因子 top20% 等权多头）
- 半仓 → 半仓（因子 top20% 等权多头 × 0.5，余现金）
- 空仓 → 空仓（全现金）

对照口径：
- baseline：因子 walk-forward 始终满仓（即 ``WalkForwardBacktester`` 主口径）——验证「择时是否增量」；
- benchmark：可投资域等权（中证全指代理）——验证「相对大盘是否超额」。

报告（PRD §10）：年化收益 / 最大回撤 / 相对超额。

全部 analysis-first：仅评估温度计择时观点，不交易、不下单。复用 ``WalkForwardBacktester`` 的
训练权重（IC 加权）、打分与指标口径，保证与因子回测可比。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from backtest.cost_model import CostModel
from backtest.walk_forward import WalkForwardBacktester, deflated_sharpe
from loguru import logger

# 温度计信号 → 权益暴露（0-1）
EXPOSURE_MAP: Dict[str, float] = {"买入": 1.0, "半仓": 0.5, "空仓": 0.0}


class SentimentTimingBacktester:
    """T2 温度计择时「样本外」回测器。"""

    def __init__(self, cfg: Optional[Dict] = None) -> None:
        cfg = cfg or {}
        self.wf = WalkForwardBacktester(cfg)
        self.cost = CostModel(cfg)
        self.exposure_map = EXPOSURE_MAP
        self.default_exposure = 0.5  # 无信号日期退化为半仓（中性假设）

    # ---- 主入口 -------------------------------------------------
    def run(
        self,
        bars_df: pd.DataFrame,
        factor_long: pd.DataFrame,
        universe_df: pd.DataFrame,
        sentiment_df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, Dict[str, float], pd.DataFrame]:
        """执行 T2 温度计择时回测。

        Args:
            bars_df: 日线行情（含 adj_back_close）。
            factor_long: 中性化因子宽表（date, code, factor_name, value）。
            universe_df: 可投资域（含 in_universe）。
            sentiment_df: 市场情绪指数表（至少含 date, signal 两列）。

        Returns:
            (returns_df, metrics, report_rows)
            returns_df 列：date, port_ret(择时), bench_ret(等权), base_ret(因子满仓)
        """
        if bars_df is None or bars_df.empty:
            return pd.DataFrame(), {}, pd.DataFrame()
        if factor_long is None or factor_long.empty:
            return pd.DataFrame(), {}, pd.DataFrame()

        # 行情宽表（后复权）+ 次日收益（point-in-time）
        price = bars_df.pivot_table(index="date", columns="code", values="adj_back_close")
        fwd = price.shift(-1) / price - 1.0
        # 涨跌停流动性约束所需（P1-3）：交易日 t 的 close / pre_close
        # 缺列则降级为不做涨跌停拦截（tradable_buy 返回 True）
        close_px = (
            bars_df.pivot_table(index="date", columns="code", values="close")
            if "close" in bars_df.columns
            else pd.DataFrame()
        )
        pre_close_px = (
            bars_df.pivot_table(index="date", columns="code", values="pre_close")
            if "pre_close" in bars_df.columns
            else pd.DataFrame()
        )

        # 限定可投资域
        if universe_df is not None and not universe_df.empty:
            inv = universe_df[universe_df["in_universe"]]["code"].unique()
            keep = [c for c in price.columns if c in inv]
            price = price[keep]
            fwd = fwd[keep]
            close_px = close_px[keep]
            pre_close_px = pre_close_px[keep]

        # 因子宽表
        fwide = factor_long.pivot_table(
            index=["date", "code"], columns="factor_name", values="value"
        ).reset_index()
        fwide = fwide.pivot(index="date", columns="code")

        # 情绪暴露序列（date -> 暴露 0/0.5/1）
        exposure = self._build_exposure(sentiment_df, list(price.index))

        dates = list(price.index)
        n = len(dates)
        if n < self.wf.train_window + self.wf.test_window:
            self.wf.train_window = max(20, n // 3)
            self.wf.test_window = n - self.wf.train_window

        rows: list = []  # (date, timing_ret, bench_ret, base_ret, timing_gross, base_gross)
        prev_w: Optional[pd.Series] = None  # 择时组合权重（eq*expo）
        prev_b: Optional[pd.Series] = None  # baseline 组合权重（eq）
        start = 0
        while start + self.wf.train_window + 1 <= n:
            train_dates = dates[start : start + self.wf.train_window]
            test_dates = dates[
                start + self.wf.train_window : start + self.wf.train_window + self.wf.test_window
            ]
            if not test_dates:
                break
            weights = self.wf._train_weights(fwide, fwd, train_dates)
            for t in test_dates:
                if t not in fwd.index:
                    continue
                alpha = self.wf._alpha(fwide, weights, t)
                if alpha is None or alpha.dropna().empty:
                    prev_w, prev_b = None, None
                    continue
                # 选 alpha 最高的 top_frac 等权多头
                k = max(1, int(self.wf.top_frac * alpha.notna().sum()))
                longs = alpha.dropna().sort_values(ascending=False).head(k).index
                # P1-3 涨跌停约束：剔除当日涨停不可买入之名
                longs = [
                    c
                    for c in longs
                    if self.cost.tradable_buy(
                        close_px[c].get(t) if c in close_px.columns else None,
                        pre_close_px[c].get(t) if c in pre_close_px.columns else None,
                    )
                ]
                if not longs:
                    prev_w, prev_b = None, None
                    continue
                eq = pd.Series(0.0, index=alpha.index)
                eq[longs] = 1.0 / len(longs)
                # 当日收益向量（t 持仓赚 t->t+1）
                r = fwd.loc[t]
                base_gross = float((eq * r).sum())  # 因子满仓组合（毛）
                expo = exposure.get(t, self.default_exposure)
                timing_gross = expo * base_gross  # 叠加权益暴露（毛）
                bench_ret = float(r.mean())  # 等权基准

                # 成本（换手）：权重向量 = eq*expo（择时）/ eq（baseline）
                w_t = eq * expo
                cost_t = self._turnover_cost(w_t, prev_w)
                cost_b = self._turnover_cost(eq, prev_b)
                timing_ret = timing_gross - cost_t
                base_ret = base_gross - cost_b

                rows.append((t, timing_ret, bench_ret, base_ret, timing_gross, base_gross))
                prev_w = w_t
                prev_b = eq
            start += self.wf.step

        if not rows:
            return pd.DataFrame(), {}, pd.DataFrame()
        ret_df = pd.DataFrame(
            rows, columns=["date", "port_ret", "bench_ret", "base_ret", "port_gross", "base_gross"]
        )
        metrics = self._metrics(ret_df)
        report_rows = self._report(ret_df, metrics)
        logger.info(
            f"T2 温度计择时回测完成：样本外 {len(ret_df)} 日，"
            f"择时年化 {metrics.get('timing_ann_return', 0) * 100:.1f}%，"
            f"基准年化 {metrics.get('baseline_ann_return', 0) * 100:.1f}%，"
            f"超额 {metrics.get('excess_ann_return', 0) * 100:.1f}%，"
            f"最大回撤 {metrics.get('timing_max_drawdown', 0) * 100:.1f}%"
        )
        return ret_df, metrics, report_rows

    # ---- 工具 --------------------------------------------------
    def _build_exposure(self, sentiment_df: pd.DataFrame, dates_index: list) -> Dict[dt.date, float]:
        """构建 date -> 权益暴露 映射；无信号日期回填默认暴露。"""
        if sentiment_df is None or sentiment_df.empty or "signal" not in sentiment_df.columns:
            return {}
        s = sentiment_df[["date", "signal"]].copy()
        s["date"] = pd.to_datetime(s["date"]).dt.date
        wanted = set(dates_index)
        s = s[s["date"].isin(wanted)]
        if s.empty:
            return {}
        exp = s.set_index("date")["signal"].map(self.exposure_map)
        return {d: float(v) for d, v in exp.fillna(self.default_exposure).items()}

    def _turnover_cost(self, cur: pd.Series, prev: Optional[pd.Series]) -> float:
        """换手成本（与 WalkForwardBacktester 口径一致）。"""
        if prev is None:
            turnover = 1.0  # 首次建仓
        else:
            idx = cur.index.union(prev.index)
            c = cur.reindex(idx).fillna(0.0)
            p = prev.reindex(idx).fillna(0.0)
            turnover = float((c - p).abs().sum() / 2.0)
        return turnover * self.cost.round_trip_cost_rate()

    # ---- 指标 --------------------------------------------------
    def _metrics(self, ret_df: pd.DataFrame) -> Dict[str, float]:
        from statsmodels.api import OLS
        from statsmodels.tools import add_constant

        timing = ret_df["port_ret"].dropna()
        base = ret_df["base_ret"].dropna()
        bench = ret_df["bench_ret"].dropna()
        if len(timing) < 5:
            return {}
        out: Dict[str, float] = {}
        out.update(self._block(timing, bench, "timing_"))
        out.update(self._block(base, bench, "baseline_"))
        # 毛收益年化（P1-3：与净收益对照）
        timing_g = ret_df["port_gross"].dropna() if "port_gross" in ret_df.columns else timing
        base_g = ret_df["base_gross"].dropna() if "base_gross" in ret_df.columns else base
        out["timing_ann_return_gross"] = (
            float((1.0 + timing_g.mean()) ** 252 - 1.0)
            if (len(timing_g) >= 5 and timing_g.mean() > -1)
            else float("nan")
        )
        out["baseline_ann_return_gross"] = (
            float((1.0 + base_g.mean()) ** 252 - 1.0)
            if (len(base_g) >= 5 and base_g.mean() > -1)
            else float("nan")
        )
        # 择时相对因子满仓的增量
        out["excess_ann_return"] = out["timing_ann_return"] - out["baseline_ann_return"]
        out["excess_max_drawdown"] = out["timing_max_drawdown"] - out["baseline_max_drawdown"]
        out["excess_sharpe"] = out["timing_sharpe"] - out["baseline_sharpe"]
        return out

    @staticmethod
    def _block(ret: pd.Series, bench: pd.Series, prefix: str) -> Dict[str, float]:
        """单组合指标块（年化 / Sharpe / 最大回撤 / DeflatedSharpe / alpha-beta）。"""
        ann = (1.0 + ret.mean()) ** 252 - 1.0 if ret.mean() > -1 else float("nan")
        sd = ret.std(ddof=1)
        sharpe = ret.mean() / sd * np.sqrt(252) if sd > 0 else 0.0
        cum = (1.0 + ret).cumprod()
        mdd = float(((cum - cum.cummax()) / cum.cummax()).min())
        alpha_ann = 0.0
        beta = 0.0
        try:
            df = pd.concat([ret.rename("y"), bench.rename("x")], axis=1).dropna()
            if len(df) > 5:
                model = OLS(df["y"], add_constant(df["x"])).fit()
                alpha_ann = float(model.params["const"] * 252)
                beta = float(model.params["x"])
        except Exception:  # noqa: BLE001
            pass
        return {
            f"{prefix}ann_return": float(ann),
            f"{prefix}sharpe": float(sharpe),
            f"{prefix}max_drawdown": mdd,
            f"{prefix}deflated_sharpe": deflated_sharpe(ret),
            f"{prefix}alpha_ann_vs_bench": alpha_ann,
            f"{prefix}beta_vs_bench": beta,
        }

    @staticmethod
    def _report(ret_df: pd.DataFrame, metrics: Dict[str, float]) -> pd.DataFrame:
        date = ret_df["date"].max() if not ret_df.empty else None
        benchmarks = "zz_quan_zhi,hs300"
        rows = []
        for name, val in metrics.items():
            # 区分策略：excess_* 归到择时策略；否则按前缀归类
            if name.startswith("timing_"):
                strat = "walk_forward_sentiment_timing"
            elif name.startswith("baseline_"):
                strat = "walk_forward_factor_baseline"
            else:
                strat = "walk_forward_sentiment_timing"  # excess_* 附在择时策略下
            rows.append(
                {
                    "date": date,
                    "strategy": strat,
                    "metric_name": name,
                    "metric_value": float(val),
                    "benchmark": benchmarks,
                    "sharpe": metrics.get("timing_sharpe", float("nan")),
                    "deflated_sharpe": metrics.get("timing_deflated_sharpe", float("nan")),
                }
            )
        return pd.DataFrame(rows)
