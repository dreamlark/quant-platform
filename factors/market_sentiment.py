"""市场级综合情绪指数（融合第 3 源 · T1 市场综合指数 + T2 资金温度计）。

设计（对齐 PRD §4/§7）：
- 五维指标（对齐中信建投/中信方案）：量 / 价 / 资金 / 估值 / 风险溢价。
  * 量、价 两维**直接由本平台 bars 计算**（上涨成交量占比、上涨家数占比），无需外部源；
  * 资金、估值、风险溢价 由 ``sources/sentiment_data`` 的 akshare 外部数据提供（缺失则剔除该维）。
- 合成方法（主方案）：每个维度算**历史分位**（point-in-time，滚动窗口），等权加总 →
  综合情绪指数 ∈ [0,100]；并输出各子指数分位。
- GSISI（国信）：行业 Beta 轮动——高 Beta 行业收益普遍更高 → 乐观；反之悲观。
- 温度计择时（T2，华泰式）：指数映射为 恐惧/中性/贪婪 状态 + 买入/半仓/空仓信号。

全部 analysis-first：输出为市场状态/择时观点，不交易、不下单。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, Optional

import numpy as np
import pandas as pd

from loguru import logger

try:
    from scipy.stats import spearmanr
    _HAS_SPEAR = True
except Exception:  # pragma: no cover
    _HAS_SPEAR = False


class MarketSentiment:
    """市场级综合情绪指数 + 温度计。"""

    def __init__(self, cfg: Optional[Dict] = None) -> None:
        ms = (cfg or {}).get("market_sentiment", {})
        self.pct_window = int(ms.get("percentile_window", 750))  # 历史分位窗口(交易日)
        self.dim_weights = ms.get("dim_weights", {
            "volume": 0.25, "price": 0.25, "money": 0.20,
            "valuation": 0.15, "riskpremium": 0.15,
        })
        self.th = ms.get("thermometer", {"fear": 30, "greed": 70, "buy": 10, "empty": 90})
        self.gsisi_window = int(ms.get("gsisi_window", 60))
        self.gsisi_weeks = int(ms.get("gsisi_weeks", 8))
        # regime_state（bull/neutral/bear/panic）派生参数：情绪 + 指数 N 日回撤
        rs = ms.get("regime_state", {})
        self.drawdown_window = int(rs.get("drawdown_window", 20))
        self.dd_panic = float(rs.get("dd_panic", -0.15))   # 指数回撤超 15% → panic
        self.dd_bear = float(rs.get("dd_bear", -0.08))     # 回撤超 8% → bear
        self.dd_bull = float(rs.get("dd_bull", -0.05))     # 贪婪且回撤优于 -5% → bull

    # ---- 工具 ----
    @staticmethod
    def _rolling_pct(series: pd.Series, target: dt.date, window: int) -> float:
        """target 当日值在截至该日滚动窗口内的历史分位（0-100），point-in-time。"""
        s = series.loc[:target]
        if len(s) < max(20, window // 4):
            return 50.0
        recent = s.tail(window)
        val = float(s.iloc[-1])
        std = float(recent.std())
        if std == 0 or np.isnan(std):
            return 50.0
        return float((recent <= val).mean() * 100)

    def _index_drawdown(self, bars: pd.DataFrame, date: dt.date, window: int) -> Optional[float]:
        """市场代理指数 N 日回撤（point-in-time，仅用 ≤date 数据）。

        代理指数 = 横截面日均价（``adj_back_close`` 优先），等价于等权市场指数。
        返回 ``(level - rolling_peak) / rolling_peak`` ∈ (-1, 0]；数据不足返回 ``None``。
        """
        if bars is None or bars.empty:
            return None
        px = "adj_back_close" if "adj_back_close" in bars.columns else "close"
        if px not in bars.columns:
            return None
        b = bars[["date", px]].copy()
        b = b[b["date"] <= date]
        if b.empty:
            return None
        lvl = b.groupby("date")[px].mean()
        if len(lvl) < window:
            return None
        tail = lvl.tail(window)
        peak = float(tail.max())
        if peak <= 0:
            return None
        return float((float(tail.iloc[-1]) - peak) / peak)

    def _derive_regime_state(self, regime: str, dd: Optional[float]) -> str:
        """由情绪 regime（恐惧/中性/贪婪）+ 指数回撤派生 4 态（point-in-time 安全）。

        - 深度回撤（≤ dd_panic）→ panic；中度回撤（≤ dd_bear）→ bear；
        - 贪婪且市场未深跌（> dd_bull）→ bull；其余 → neutral。
        仅缩放置信度、不改方向；无回撤数据时用情绪直接映射（贪婪→bull，恐惧→bear）。
        """
        if dd is None:
            return {"贪婪": "bull", "中性": "neutral", "恐惧": "bear"}.get(regime, "neutral")
        if dd <= self.dd_panic:
            return "panic"
        if dd <= self.dd_bear:
            return "bear"
        if regime == "贪婪" and dd > self.dd_bull:
            return "bull"
        return "neutral"

    # ---- 维度构建（每日序列）----
    def _dim_volume(self, bars: pd.DataFrame) -> Optional[pd.Series]:
        b = bars.sort_values(["code", "date"]).copy()
        b["dret"] = b.groupby("code")["adj_back_close"].pct_change()
        b["up"] = (b["dret"] > 0).astype(float)
        # 上涨成交额占比：用分组聚合替代 apply（规避弃用告警）
        b["up_vol"] = b["up"] * b["vol"]
        g = b.groupby("date")
        up_vol = g["up_vol"].sum()
        tot_vol = g["vol"].sum()
        ratio = (up_vol / tot_vol).replace([np.inf, -np.inf], np.nan).dropna()
        return ratio if not ratio.empty else None

    def _dim_price(self, bars: pd.DataFrame) -> Optional[pd.Series]:
        b = bars.sort_values(["code", "date"]).copy()
        b["dret"] = b.groupby("code")["adj_back_close"].pct_change()
        ratio = b.groupby("date")["dret"].apply(lambda s: (s > 0).mean())
        ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()
        return ratio if not ratio.empty else None

    def _dim_money(self, external: Dict) -> Optional[pd.Series]:
        parts = []
        for key, col in (("margin", "margin_net_buy"), ("northbound", "net_buy"), ("etf", "net_flow")):
            df = external.get(key)
            if df is None or df.empty or col not in df.columns:
                continue
            s = df.set_index("date")[col].astype(float)
            s = s[~s.index.duplicated(keep="last")].sort_index()
            parts.append(s)
        if not parts:
            return None
        joined = pd.concat(parts, axis=1).fillna(0.0)
        z = joined.apply(lambda c: (c - c.mean()) / (c.std() + 1e-9))
        return z.mean(axis=1)

    def _dim_valuation(self, external: Dict) -> Optional[pd.Series]:
        df = external.get("valuation")
        if df is None or df.empty or "pe" not in df.columns:
            return None
        s = df.set_index("date")["pe"].astype(float)
        return s[~s.index.duplicated(keep="last")].sort_index()

    def _dim_riskpremium(self, external: Dict) -> Optional[pd.Series]:
        val = external.get("valuation")
        bond = external.get("bond")
        if val is None or bond is None:
            return None
        pe = val.set_index("date")["pe"].astype(float)
        yld = bond.set_index("date")["yield_10y"].astype(float)
        pe = pe[~pe.index.duplicated(keep="last")].sort_index()
        yld = yld[~yld.index.duplicated(keep="last")].sort_index()
        m = pd.concat([pe, yld], axis=1).dropna()
        if m.empty:
            return None
        return ((1.0 / m["pe"]) - m["yield_10y"]).sort_index()  # 盈利收益率 - 10Y 国债

    def _gsisi(self, bars: pd.DataFrame, industry_map: Optional[Dict]) -> float:
        """行业 Beta 轮动情绪（国信 GSISI 思路）。高 Beta 行业收益普涨→乐观。"""
        if industry_map is None:
            return 0.0
        try:
            bars = bars.sort_values(["code", "date"])
            ret = bars.pivot(index="date", columns="code", values="adj_back_close").pct_change().dropna(how="all")
            if ret.shape[0] < self.gsisi_window:
                return 0.0
            mkt = ret.mean(axis=1)
            beta: Dict[str, float] = {}
            for code in ret.columns:
                pair = pd.concat([ret[code], mkt], axis=1).dropna()
                if len(pair) < self.gsisi_window:
                    continue
                cov = pair.cov().iloc[0, 1]
                var = pair.iloc[:, 1].var()
                if var > 0:
                    beta[code] = cov / var
            rows = [(industry_map.get(str(c).split(".")[0]) or industry_map.get(c), b)
                    for c, b in beta.items()]
            rows = [(ind, b) for ind, b in rows if ind]
            if not rows:
                return 0.0
            ind_beta = pd.Series({ind: np.mean([b for i, b in rows if i == ind])
                                  for ind in {i for i, _ in rows}})
            ind_ret = bars.copy()
            ind_ret["industry"] = ind_ret["code"].astype(str).map(
                lambda c: industry_map.get(c) or industry_map.get(str(c).split(".")[0])
            )
            ind_ret = ind_ret.dropna(subset=["industry"]).sort_values(["industry", "date"])
            ind_ret["dret"] = ind_ret.groupby("industry")["adj_back_close"].pct_change()
            # 行业周收益：先按 (周, 行业) 透视汇总每日 dret，再按周重采样求和
            ind_ret["_d"] = pd.to_datetime(ind_ret["date"])
            wk = ind_ret.pivot_table(index="_d", columns="industry", values="dret", aggfunc="sum")
            wk = wk.resample("W-FRI").sum()
            common = [c for c in wk.columns if c in ind_beta.index]
            if len(common) < 3:
                return 0.0
            x = ind_beta[common].values
            y = wk[common].tail(self.gsisi_weeks).values
            cors = []
            for t in range(y.shape[0]):
                yt = y[t]
                if np.std(yt) == 0 or np.isnan(np.std(yt)):
                    continue
                if _HAS_SPEAR:
                    r = spearmanr(x, yt)[0]
                else:
                    r = np.corrcoef(pd.Series(x).rank().values, pd.Series(yt).rank().values)[0, 1]
                if np.isfinite(r):
                    cors.append(r)
            return float(np.mean(cors)) if cors else 0.0
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"GSISI 计算失败（降级）：{exc}")
            return 0.0

    # ---- 主入口 ----
    def compute(
        self, date: dt.date, bars: pd.DataFrame,
        external: Optional[Dict] = None, industry_map: Optional[Dict] = None,
    ) -> pd.DataFrame:
        """计算目标日市场综合情绪指数一行（对齐 sentiment_index 表）。"""
        external = external or {}
        if "date" in bars.columns:
            bars = bars[bars["date"] <= date]
        dims = {
            "volume": self._dim_volume(bars),
            "price": self._dim_price(bars),
            "money": self._dim_money(external),
            "valuation": self._dim_valuation(external),
            "riskpremium": self._dim_riskpremium(external),
        }
        sub: Dict[str, Optional[float]] = {}
        acc, wsum = 0.0, 0.0
        for name, series in dims.items():
            if series is None or len(series) == 0:
                sub[name] = None
                continue
            p = self._rolling_pct(series, date, self.pct_window)
            sub[name] = round(p, 2)
            w = self.dim_weights.get(name, 0.0)
            if w > 0:
                acc += w * p
                wsum += w
        index_value = round(acc / wsum, 2) if wsum > 0 else 50.0
        gsisi = round(self._gsisi(bars, industry_map), 4)
        th = index_value
        regime = "恐惧" if th <= self.th["fear"] else ("贪婪" if th >= self.th["greed"] else "中性")
        signal = "买入" if th <= self.th["buy"] else ("空仓" if th >= self.th["empty"] else "半仓")
        dd = self._index_drawdown(bars, date, self.drawdown_window)
        regime_state = self._derive_regime_state(regime, dd)
        row = {
            "date": date,
            "index_value": index_value,
            "sub_volume": sub.get("volume"),
            "sub_price": sub.get("price"),
            "sub_money": sub.get("money"),
            "sub_valuation": sub.get("valuation"),
            "sub_riskpremium": sub.get("riskpremium"),
            "gsisi": gsisi,
            "regime": regime,
            "regime_state": regime_state,
            "thermometer": th,
            "signal": signal,
        }
        return pd.DataFrame([row])
