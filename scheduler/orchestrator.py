"""每日盘后编排（数据→因子→预测→体检→中性化→融合→LLM→看板→回测）。

按架构 §4.1 时序实现。所有价格类计算只读 ``adj_back_close``（后复权，P0-1）；
因子/信号/回测统一限定 ``universe.in_universe=true``（P0-3）；融合前做中性化（P1-4）；
预测/回测 walk-forward + 基准对照（P1-2/3）；LLM 仅生成研究观点，置信度取信号层。

重型模型（qlib/czsc/kronos/darts/backtrader/quantstats）全部懒加载降级，核心链路无密钥可跑。
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger

from factors.factor_calc import FactorCalculator
from factors.prediction import PredictionGenerator
from factors.risk_neutral import RiskNeutralizer
from factors.sentiment import SentimentExtractor
from factors.market_sentiment import MarketSentiment
from factors.text_sentiment import TextSentiment
from sources.sentiment_data import fetch_all as fetch_sentiment_external
from fusion.sector import SectorAnalyzer
from fusion.signal_pool import SignalPool
from llm.brief_gen import BriefGenerator
from llm.client import LLMClient
from llm.stock_review import StockReviewer
from evaluation.health_check import FactorHealth
from backtest.report import generate_report, summarize_metrics
from backtest.walk_forward import WalkForwardBacktester
from backtest.qlib_backtest import run_qlib_backtest
from backtest.bt_backtest import run_backtrader
from backtest.sentiment_timing import SentimentTimingBacktester
from backtest.signal_backtest import compare_regime
from sources.adjust import adjust_prices
from sources.universe import UniverseFilter
from storage.repository import Repository


class Orchestrator:
    """每日盘后编排器。"""

    def __init__(
        self,
        repo: Repository,
        settings: Dict,
        data_source=None,
        stock_list: Optional[pd.DataFrame] = None,
    ) -> None:
        self.repo = repo
        self.settings = settings
        self.source = data_source
        self.stock_list = stock_list
        self.codes: List[str] = (
            stock_list["code"].tolist() if stock_list is not None else []
        )
        self.universe_filter = UniverseFilter(settings)
        self.factor_calc = FactorCalculator(settings)
        self.sentiment_ext = SentimentExtractor(settings)
        self.market_sent = MarketSentiment(settings)
        self.predictor = PredictionGenerator(settings)
        self.health = FactorHealth(settings)
        self.neutralizer = RiskNeutralizer(settings)
        self.signal_pool = SignalPool(settings)
        self.sector_analyzer = SectorAnalyzer(settings)
        self.llm = LLMClient(settings)
        # T3 文本情绪：复用 LLM 客户端（无密钥时门控降级）
        self.text_sent = TextSentiment(settings, self.llm)
        self.brief_gen = BriefGenerator(self.llm, settings.get("llm", {}).get("disclaimer", ""))
        self.reviewer = StockReviewer(self.llm, settings.get("llm", {}).get("disclaimer", ""))
        self.wf = WalkForwardBacktester(settings)

        # 步骤间传递（持久化同时缓存）
        self.factor_long = pd.DataFrame()
        self.tech_df = pd.DataFrame()
        self.sentiment_df = pd.DataFrame()
        self.predict_df = pd.DataFrame()
        self.predict_health = pd.DataFrame()
        self.factor_health = pd.DataFrame()
        self.neutralized = pd.DataFrame()
        # ingest 增量落库批次（断点续跑用）
        self._INGEST_BATCH = 50

    # ---- 步骤 ----------------------------------------------------
    def step_ingest(self, start: dt.date, end: dt.date) -> pd.DataFrame:
        """拉取并复权落库（多源冗余 + 后复权计算价）。

        断点续跑：若某标的在库中已含 ``end`` 当日及之后的数据，则跳过重新拉取
        （避免每轮重跑都重复请求全部历史）；单标的取数异常不影响其余标的。
        增量落库：每满 ``_INGEST_BATCH`` 只即调 ``save_bars``，避免长时运行的进程
        被环境掐断时丢失全部已取数据（重跑时凭库中 max(date) 续跑）。
        """
        if self.source is None:
            raise RuntimeError("未配置数据源，无法 ingest（冒烟可预置 bars 到仓库）")
        # 预查询各标的已入库最大日期，用于跳过已新鲜的标的
        fresh: set = set()
        try:
            md = self.repo.load_bars(codes=self.codes)
            if not md.empty:
                mx = md.groupby("code")["date"].max()
                fresh = set(mx[mx >= end].index)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"ingest 续跑预查询跳过：{exc}")
        batch: List[pd.DataFrame] = []
        skipped = 0
        saved = 0

        def _flush(batch: List[pd.DataFrame]) -> int:
            if not batch:
                return 0
            raw = pd.concat(batch, ignore_index=True)
            raw = adjust_prices(
                raw, jump_detect=self.settings.get("adjust", {}).get("jump_detect", True)
            )
            return self.repo.save_bars(raw)

        for code in self.codes:
            if code in fresh:
                skipped += 1
                continue
            try:
                rows = self.source.fetch(code, start, end)
            except Exception as exc:  # noqa: BLE001 单标容错
                logger.warning(f"ingest {code} 取数失败，跳过：{exc}")
                continue
            if rows:
                batch.append(pd.DataFrame(rows))
                if len(batch) >= self._INGEST_BATCH:
                    saved += _flush(batch)
                    batch = []
        saved += _flush(batch)
        if skipped:
            logger.info(f"ingest 续跑跳过已新鲜标的 {skipped}/{len(self.codes)} 只")
        logger.info(f"ingest 本轮新入库标的 {saved}/{len(self.codes)} 只")
        return pd.DataFrame()

    def step_universe(self, date: dt.date) -> pd.DataFrame:
        bars = self.repo.load_bars(end=date)
        uni = self.universe_filter.build_universe(date, self.stock_list, bars)
        self.repo.save_universe(uni)
        return uni

    def step_factors(self, date: dt.date) -> pd.DataFrame:
        bars = self.repo.load_bars(end=date)
        uni = self.repo.load_universe(date, in_universe=True)
        codes = uni["code"].tolist()
        self.factor_long, self.tech_df = self.factor_calc.compute(bars, codes)
        # 技术分存为 factor_values（审计/下钻）
        if not self.tech_df.empty:
            tech_long = self.tech_df.rename(columns={"tech_score": "value"}).copy()
            tech_long["factor_name"] = "tech_signal"
            self.repo.save_factor_long(tech_long[["date", "code", "factor_name", "value"]])
        self.repo.save_factor_long(self.factor_long)
        return self.factor_long

    def step_sentiment(self, date: dt.date) -> pd.DataFrame:
        bars = self.repo.load_bars(end=date)
        uni = self.repo.load_universe(date, in_universe=True)
        codes = uni["code"].tolist()
        self.sentiment_df = self.sentiment_ext.extract(bars, codes)
        if not self.sentiment_df.empty:
            s_long = self.sentiment_df.rename(columns={"sentiment_score": "value"}).copy()
            s_long["factor_name"] = "sentiment_score"
            self.repo.save_factor_long(s_long[["date", "code", "factor_name", "value"]])
        return self.sentiment_df

    def step_predict(self, date: dt.date) -> pd.DataFrame:
        bars = self.repo.load_bars(end=date)
        uni = self.repo.load_universe(date, in_universe=True)
        codes = uni["code"].tolist()
        self.predict_df, self.predict_health = self.predictor.generate(bars, codes, date)
        if not self.predict_df.empty:
            self.repo.save_predict(self.predict_df)
        if not self.predict_health.empty:
            self.repo.save_predict_health(self.predict_health)
        return self.predict_df

    def step_health(self, date: dt.date) -> pd.DataFrame:
        bars = self.repo.load_bars(end=date)
        self.factor_health, _ = self.health.evaluate(self.factor_long, bars, date)
        if not self.factor_health.empty:
            self.repo.save_health(self.factor_health)
        return self.factor_health

    def step_neutralize(self, date: dt.date) -> pd.DataFrame:
        """行业/市值中性化（回归残差法，P1-4）。"""
        meta = self._build_meta()
        self.neutralized = self.neutralizer.neutralize(self.factor_long, meta)
        return self.neutralized

    def step_fusion(self, date: dt.date) -> pd.DataFrame:
        uni = self.repo.load_universe(date, in_universe=True)
        codes = uni["code"].tolist()
        # regime 调节：使用最近一次（T-1）市场情绪 regime（point-in-time 正确——
        # 当日情绪指数在 step_market_sentiment 之后才落库，不能用于当日信号）。
        regime = self._latest_regime()
        signals = self.signal_pool.fuse(
            self.neutralized,
            self.tech_df,
            self.sentiment_df,
            self.predict_df,
            self.factor_health,
            self.predict_health,
            date,
            codes,
            regime=regime,
        )
        self.repo.save_signals(signals)
        return signals

    def _latest_regime(self) -> Optional[str]:
        """读取最近一次市场状态 regime_state（供融合层 regime 调节用，T-1 已落库）。"""
        try:
            idx = self.repo.load_sentiment_index(latest=True)
            if idx is not None and not idx.empty and "regime_state" in idx.columns:
                return str(idx.iloc[0]["regime_state"])
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"融合层读取 regime_state 失败（降级为无调节）：{exc}")
        return None

    def step_sector(self, date: dt.date) -> pd.DataFrame:
        bars = self.repo.load_bars(end=date)
        uni = self.repo.load_universe(date, in_universe=True)
        # 真实行业分类映射：优先用 stock_list 的 industry 列，否则回退申万一级（网络/缓存）
        industry_map = None
        if self.stock_list is not None and "industry" in self.stock_list.columns:
            m = self.stock_list[["code", "industry"]].copy()
            m["code"] = m["code"].astype(str).str.split(".").str[0]
            m = m[m["industry"].astype(str).str.len() > 0]
            if not m.empty:
                industry_map = dict(zip(m["code"], m["industry"].astype(str)))
        if not industry_map:
            try:
                from sources.market_meta import fetch_industry_map

                industry_map = fetch_industry_map()
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"板块：获取申万行业映射失败，退化为 sectors.yaml：{exc}")
        sector = self.sector_analyzer.analyze(date, bars, uni, industry_map=industry_map)
        if not sector.empty:
            self.repo.save_sector(sector)
        return sector

    def step_market_sentiment(self, date: dt.date) -> pd.DataFrame:
        """市场综合情绪指数（T1/T2）+ 文本情绪（T3，门控降级）。

        T1/T2 五维分位合成 + GSISI + 华泰温度计择时，落库 ``sentiment_index``；
        T3 LLM 文本情绪门控（无密钥/无新闻则跳过，仅日志）。外部数据按需 akshare
        拉取，失败整体降级为空（仅量/价两维仍由本平台 bars 计算）。
        """
        bars = self.repo.load_bars(end=date)
        uni = self.repo.load_universe(date, in_universe=True)
        # 行业映射（与 step_sector 一致，供 GSISI 使用）
        industry_map = None
        if self.stock_list is not None and "industry" in self.stock_list.columns:
            m = self.stock_list[["code", "industry"]].copy()
            m["code"] = m["code"].astype(str).str.split(".").str[0]
            m = m[m["industry"].astype(str).str.len() > 0]
            if not m.empty:
                industry_map = dict(zip(m["code"], m["industry"].astype(str)))
        external: Dict = {}
        try:
            external = fetch_sentiment_external(self.settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"市场情绪：外部数据拉取失败（降级）：{exc}")
        idx_df = self.market_sent.compute(
            date, bars, external=external, industry_map=industry_map
        )
        if not idx_df.empty:
            self.repo.save_sentiment_index(idx_df)
        # T3 文本情绪（门控，不阻断核心链路）
        try:
            self.text_sent.analyze(date, uni["code"].tolist())
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"市场情绪：文本情绪跳过：{exc}")
        return idx_df

    def step_llm(self, date: dt.date) -> None:
        signals = self.repo.load_signals(date)
        sector = self.repo.load_sector(date)
        uni = self.repo.load_universe(date, in_universe=True)
        content, temp = self.brief_gen.generate_market_brief(date, signals, sector, uni)
        self.repo.save_brief(date, content, temp, self.settings.get("llm", {}).get("disclaimer", ""))
        # 自选股逐只简评
        for code in self.repo.load_watch_codes():
            srow = signals[signals["code"] == code]
            sr = srow.iloc[0].to_dict() if not srow.empty else None
            holding = self._holding(code)
            rev = self.reviewer.review(code, code, sr, holding)
            self.repo.save_review(
                date, code, rev.content, rev.action, rev.reason, rev.confidence,
                self.settings.get("llm", {}).get("disclaimer", ""),
            )

    def step_backtest(self, date: dt.date) -> pd.DataFrame:
        bars = self.repo.load_bars(end=date)
        uni = self.repo.load_universe(date, in_universe=True)

        # 1) walk-forward（因子 walk-forward IC 加权 · 仅做多）— 主口径
        ret_df, metrics, wf_rows = self.wf.run(bars, self.neutralized, uni)
        all_rows = []
        if not wf_rows.empty:
            self.repo.save_backtest(wf_rows)
            all_rows.append(wf_rows)
        generate_report(ret_df, metrics, self.settings)

        # 取 walk_forward 实际测试起点（ret_df 的最小日期，即首个样本外测试日），
        # 作为交叉验证引擎的对齐基准（保证三引擎可比）。
        # 注意：wf_rows 的 date 字段是 ret_df 的「最大日期」，不能用于对齐起点。
        wf_start = ret_df["date"].min() if not ret_df.empty else None

        # 2) Qlib 因子回测（全样本 IC 加权 · 仅做多）— 交叉验证 A
        try:
            ql = run_qlib_backtest(
                bars, self.factor_long, uni, self.settings, start_date=wf_start
            )
            if ql is not None:
                _, _, ql_rows = ql
                if not ql_rows.empty:
                    self.repo.save_backtest(ql_rows)
                    all_rows.append(ql_rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"qlib 因子回测交叉验证失败，跳过：{exc}")

        # 3) backtrader 风格（技术/缠论分多空）— 交叉验证 B（验证技术源本身）
        try:
            tech = self.tech_df
            if tech is not None and not tech.empty and uni is not None and not uni.empty:
                codes_u = uni[uni["in_universe"]]["code"].tolist()
                tech = tech[tech["code"].isin(codes_u)]
            if tech is not None and not tech.empty:
                bt = run_backtrader(
                    bars, tech, uni, self.settings, start_date=wf_start
                )
                if bt is not None:
                    _, _, bt_rows = bt
                    if not bt_rows.empty:
                        self.repo.save_backtest(bt_rows)
                        all_rows.append(bt_rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"backtrader 技术分回测交叉验证失败，跳过：{exc}")

        # 4) T2 温度计择时回测（PRD §10 验收硬指标）：情绪信号叠加权益暴露
        try:
            sentiment_idx = self.repo.load_sentiment_index(latest=False)
            if (
                sentiment_idx is not None
                and not sentiment_idx.empty
                and "signal" in sentiment_idx.columns
            ):
                st_bt = SentimentTimingBacktester(self.settings)
                _, _, st_rows = st_bt.run(bars, self.neutralized, uni, sentiment_idx)
                if not st_rows.empty:
                    self.repo.save_backtest(st_rows)
                    all_rows.append(st_rows)
            else:
                logger.debug("T2 温度计择时回测跳过：sentiment_index 历史不足")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"T2 温度计择时回测失败，跳过：{exc}")

        # 5) regime 调节验证（PRD §8 启用门槛）：信号层 ON/OFF 对比，差异仅来自情绪缩放。
        #    需多日信号历史方可回测；数据不足时降级跳过（随每日运行累积后自动生效）。
        try:
            sig_hist = self.repo.load_signals_all()
            if sig_hist is not None and not sig_hist.empty and sig_hist["date"].nunique() >= 20:
                sentiment_idx = self.repo.load_sentiment_index(latest=False)
                rows_off, rows_on, delta = compare_regime(
                    bars, sig_hist, uni, sentiment_idx, self.settings
                )
                if not rows_off.empty:
                    self.repo.save_backtest(rows_off)
                    all_rows.append(rows_off)
                if not rows_on.empty:
                    self.repo.save_backtest(rows_on)
                    all_rows.append(rows_on)
                logger.info(
                    f"regime 调节验证 ON-OFF 差异：年化 {delta['ann_return'] * 100:.2f}%/"
                    f"Sharpe {delta['sharpe']:.3f}/回撤 {delta['max_drawdown'] * 100:.2f}%"
                    f"（正=改善，可据此决定是否开启 fusion.regime_adjust.enabled）"
                )
            else:
                logger.debug("regime 调节验证跳过：信号历史不足 20 日")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"regime 调节验证失败，跳过：{exc}")

        if all_rows:
            return pd.concat(all_rows, ignore_index=True)
        return wf_rows

    # ---- 全量编排 ------------------------------------------------
    def run_daily(self, target_date: dt.date, lookback_days: int = 250) -> Dict:
        start = target_date - dt.timedelta(days=lookback_days)
        if self.source is not None:
            self.step_ingest(start, target_date)
        self.step_universe(target_date)
        self.step_factors(target_date)
        self.step_sentiment(target_date)
        self.step_predict(target_date)
        self.step_health(target_date)
        self.step_neutralize(target_date)
        signals = self.step_fusion(target_date)
        self.step_sector(target_date)
        self.step_market_sentiment(target_date)
        self.step_llm(target_date)
        self.step_backtest(target_date)
        return {"date": target_date, "signals": len(signals)}

    # ---- 工具 ----------------------------------------------------
    def _build_meta(self) -> Optional[pd.DataFrame]:
        if self.stock_list is None:
            return None
        cols = [c for c in ("code", "industry", "mv") if c in self.stock_list.columns]
        if "industry" not in cols or "mv" not in cols:
            return None
        return self.stock_list[cols].copy()

    def _holding(self, code: str) -> Optional[Dict]:
        w = self.repo.list_watch()
        row = w[w["code"] == code]
        if row.empty:
            return None
        r = row.iloc[0]
        bars = self.repo.load_bars(codes=[code])
        price = float(bars.sort_values("date").tail(1)["close"].iloc[0]) if not bars.empty else 0.0
        return {
            "cost_price": float(r["cost_price"]),
            "shares": float(r["shares"]),
            "current_price": price,
        }
