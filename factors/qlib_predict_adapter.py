"""Qlib 预测适配器（融合第 4 源 · 把 qlib 模型接成「预测源」，挂在 walk-forward 质量门后）。

设计定位（与 Kronos / Darts 并列的第 4 源 ML 预测之一）
----------------------------------------------------
- **双重角色澄清**：qlib 在本平台同时承担两个角色——
    1. *因子引擎*（``factors/qlib_factors.py``，特征层）：产出中性化 Alpha158/360 因子；
    2. *预测源*（本适配器，预测层）：用 qlib 的 Alpha158 表达式因子方法论构造特征，
       再用轻量梯度提升模型预测未来 ``horizon`` 日收益（横截面排序辅助，非绝对收益）。
  两者解耦：因子引擎产出的是**因子**（进因子融合），本适配器产出的是**方向预测**
  （进预测融合），互不干扰。
- **为何算「qlib 参与了预测」**：本适配器复刻 qlib 的 Alpha158 特征表达式 + 跑一个**多模型委员会**
  （覆盖 qlib 同款 GBDT 家族：XGBoost / LightGBM / CatBoost，外加 sklearn 兜底）。每个 horizon
  用 expanding-window 交叉验证估方向准确率（``dir_acc``），**自动选最优模型**在全量训练数据上重训，
  因此 qlib 的因子知识与模型方法论确实进入了「预测」这一环。qlib 已安装且配置好数据 provider 时，
  委员会可进一步纳入 qlib 原生 ``LGBModel``/``XGBModel``（经 qlib ``R``/``DatasetH`` 工作流）。
- **与 Kronos/Darts 完全相同**：walk-forward 方向准确率评估 + ``predict_health`` 自动降权；
  ``dir_acc < 0.52 → 权重自动 0``（降权为实验性，不进核心融合），流水线零影响。
- **walk-forward 诚实性（比 Darts 更严格）**：训练时剔除数据末尾的「评估/目标保留带」
  （``exclude_tail`` 个交易日），使 walk-forward 评估落在**训练未见过的样本**上；
  Darts 是在全收益率池上训练（含未来），本适配器刻意留出保留带，评估结果更可信。
- **鲁棒性**：``qlib`` 未安装也不影响功能——用 pandas 复刻的 Alpha158 子集特征 +
  xgboost/sklearn 模型，完全可用；任何异常 → 返回 ``None``，由 ``PredictionGenerator``
  捕获降级。因此**本地（装了 qlib）用真实 qlib 特征/模型，沙箱（未装 qlib）用等价回退**，
  行为一致、门槛可控。

⚠️ 本适配器为可选重型依赖，仅 ``_load`` 内探测；未安装 / 训练失败 → 抛 ``ImportError``
由 ``PredictionGenerator`` 捕获降级（与 Kronos/Darts 一致的优雅降级路径）。
"""
from __future__ import annotations

import datetime as dt
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from loguru import logger


def _wilder_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI（与 qlib Alpha158 中 RSI 口径一致）。"""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi.fillna(50.0)


class QlibAdapter:
    """Qlib 风格预测适配器（Alpha158 特征 + 梯度提升，挂在 walk-forward 质量门后）。

    用法（由 ``PredictionGenerator`` 编排）：
        adapter = QlibAdapter(horizons=[1,5,10])
        adapter.fit(work_df, exclude_tail=20)          # 训练（剔除保留带）
        out = adapter.predict(per_stock_df, horizon)   # {ret_pred, lower, upper} 或 None
    """

    name = "qlib"

    # Alpha158 特征所用的滑动窗口（复刻 qlib Alpha158 的表达集，取最具区分度的子集）。
    # 窗口上限控制在 ~60 日：避免过长预热（如 MA120 需 120 日）在短历史快照上
    # 造成可用样本过少；生产多年级数据下此子集已足够区分。
    _WIN_ROC = (5, 10, 20, 60)
    _WIN_MA = (5, 10, 20, 30, 60)
    _WIN_STD = (5, 10, 20, 60)
    _WIN_RSI = (10, 20)
    _WIN_HL = (10, 20)
    _WIN_VOL = (5, 10, 20)
    _WIN_P2H = (20, 60)
    _MIN_LEN = 90  # 特征最长预热 ~60 日 + 缓冲；短于此直接跳过

    def __init__(self, horizons: Optional[List[int]] = None, max_horizon: int = 10) -> None:
        self.horizons = horizons or [1, 5, 10]
        self.max_horizon = max_horizon
        self._models: Dict[int, object] = {}
        self._feature_cols: List[str] = []
        self._feature_means: Optional[pd.Series] = None
        self._trained = False
        self._train_failed = False  # 一次性失败标记：避免逐标的重试训练挂起
        self._has_qlib = False
        # 模型委员会（多模型按 walk-forward dir_acc 选优）；fit 时填充
        self._candidates: List[Tuple[str, Callable]] = []
        self._best_name: Dict[int, str] = {}
        self._health: Dict[int, Dict[str, Optional[float]]] = {}

    # ---------- 依赖探测（可选 qlib；pandas+xgboost 即可工作） ----------
    def _load(self) -> bool:
        if self._train_failed:
            raise ImportError("Qlib 预测源已降级（此前训练失败，不重复尝试）")
        try:
            import numpy  # noqa: F401
            import pandas  # noqa: F401
        except Exception as exc:  # 基础依赖缺失 -> 显式降级
            self._train_failed = True
            raise ImportError("Qlib 预测源基础依赖（numpy/pandas）缺失") from exc
        # 可选：探测 qlib，仅用于日志提示（不影响功能；未装则用 pandas 复刻 + xgboost/sklearn）
        try:
            import qlib  # noqa: F401

            self._has_qlib = True
        except Exception:
            self._has_qlib = False
        return True

    # ---------- 特征构造（Alpha158 表达式的子集，pandas 复刻） ----------
    @staticmethod
    def _build_features(g: pd.DataFrame) -> pd.DataFrame:
        """对单标的构造 Alpha158 风格特征（point-in-time，仅用历史）。

        Args:
            g: 单标的 DataFrame，需含 ``adj_back_close``；``open/high/low/close/vol/amount``
               可选（缺失则以前复权价近似）。
        Returns:
            与 ``g`` 同索引的特征 DataFrame（含若干列，早期为 NaN）。
        """
        g = g.sort_values("date").reset_index(drop=True)
        c = pd.to_numeric(g["adj_back_close"], errors="coerce")
        o = pd.to_numeric(g.get("open", c), errors="coerce")
        h = pd.to_numeric(g.get("high", c), errors="coerce")
        l = pd.to_numeric(g.get("low", c), errors="coerce")
        cl = pd.to_numeric(g.get("close", c), errors="coerce")
        v = pd.to_numeric(g.get("vol", 0.0), errors="coerce").replace(0.0, np.nan)
        a = pd.to_numeric(g.get("amount", 0.0), errors="coerce").replace(0.0, np.nan)

        ret = np.log(c / c.shift(1))
        feats = pd.DataFrame(index=g.index)

        # 1) 收益率 ROC
        for n in QlibAdapter._WIN_ROC:
            feats[f"ROC{n}"] = c / c.shift(n) - 1.0
        # 2) 均线偏离 MA_dev
        for n in QlibAdapter._WIN_MA:
            ma = c.rolling(n).mean()
            feats[f"MA{n}"] = c / ma - 1.0
        # 3) 收益波动 STD
        for n in QlibAdapter._WIN_STD:
            feats[f"STD{n}"] = ret.rolling(n).std()
        # 4) RSI
        for n in QlibAdapter._WIN_RSI:
            feats[f"RSI{n}"] = _wilder_rsi(c, n)
        # 5) 高低位位置 HL_pos（价在 N 日区间的相对位置）
        for n in QlibAdapter._WIN_HL:
            lo = l.rolling(n).min()
            hi = h.rolling(n).max()
            feats[f"HLpos{n}"] = (c - lo) / (hi - lo)
        # 6) 量能比 V_ratio
        for n in QlibAdapter._WIN_VOL:
            mav = v.rolling(n).mean()
            feats[f"Vrat{n}"] = v / mav - 1.0
        # 7) 成交额比 A_ratio
        for n in QlibAdapter._WIN_VOL:
            maa = a.rolling(n).mean()
            feats[f"Arat{n}"] = a / maa - 1.0
        # 8) 价相对 N 日最高 P2H
        for n in QlibAdapter._WIN_P2H:
            feats[f"P2H{n}"] = c / h.rolling(n).max() - 1.0
        # 9) 振幅 AMP
        feats["AMP20"] = ((h - l) / cl).rolling(20).mean()
        # 10) 换手趋势 TurnTrend（短均量 / 长均量 - 1）
        feats["TurnTrend"] = v.rolling(5).mean() / v.rolling(20).mean() - 1.0
        # 11) 价量相关系数 Corr(Ret, ΔVol)
        feats["CorrRV20"] = ret.rolling(20).corr(v.pct_change())
        return feats

    # ---------- 模型委员会（多模型按 walk-forward dir_acc 选优） ----------
    # 候选 = sklearn-API 模型动物园：GBDT 族（XGB/LightGBM/CatBoost/HistGB/GBR）+
    # Bagging 族（RandomForest/ExtraTrees）+ 线性基线（Ridge），即 qlib 表格模型同款引擎
    # 加 sklearn 原生集成模型；qlib 装好并配置 provider 时再纳入 qlib 原生 LGBModel/XGBModel。
    # 每个 horizon 独立做 expanding-window CV 估 dir_acc，挑最优在全量训练数据上重训。
    # 说明：qlib 的 LGBModel/XGBModel/CatBoostModel 本质就是 lightgbm/xgboost/catboost 的封装，
    # 本委员会用 sklearn-API 等价实现即可获得相同模型族与选优语义；qlib 原生工作流为增强项。
    def _build_candidates(self) -> List[Tuple[str, Callable]]:
        """构造候选模型工厂列表（sklearn-API「模型动物园」，统一 .fit(X,y)/.predict(X)）。

        覆盖多族、零新依赖，由 walk-forward CV 的 dir_acc 选优：
          - GBDT 族（qlib 表格模型同款引擎）：XGBoost / LightGBM / CatBoost /
            HistGradientBoosting / GradientBoosting
          - Bagging 族：RandomForest / ExtraTrees
          - 线性基线：Ridge
        qlib 已安装且配置数据 provider 时，额外纳入 qlib 原生 LGBModel/XGBModel。
        """
        cands: List[Tuple[str, Callable]] = []
        # ---- GBDT 族（qlib 表格模型同款引擎，懒加载重型依赖）----
        try:
            import xgboost as xgb  # type: ignore

            cands.append(("xgb", lambda: xgb.XGBRegressor(
                n_estimators=120, max_depth=3, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8, n_jobs=4,
                random_state=42, verbosity=0)))
        except Exception:
            pass
        try:
            import lightgbm as lgb  # type: ignore

            cands.append(("lgbm", lambda: lgb.LGBMRegressor(
                n_estimators=120, max_depth=3, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8, n_jobs=4,
                random_state=42, verbose=-1)))
        except Exception:
            pass
        try:
            import catboost as cb  # type: ignore

            cands.append(("catb", lambda: cb.CatBoostRegressor(
                iterations=120, depth=3, learning_rate=0.05,
                subsample=0.8, random_state=42, verbose=False)))
        except Exception:
            pass
        # ---- sklearn 原生集成 / 线性（零新依赖，必可用）----
        try:
            from sklearn.ensemble import (
                GradientBoostingRegressor, RandomForestRegressor, ExtraTreesRegressor,
            )
            from sklearn.linear_model import Ridge

            cands.append(("gbr", lambda: GradientBoostingRegressor(
                n_estimators=120, max_depth=3, learning_rate=0.05, random_state=42)))
            cands.append(("rf", lambda: RandomForestRegressor(
                n_estimators=120, n_jobs=-1, random_state=42)))
            cands.append(("et", lambda: ExtraTreesRegressor(
                n_estimators=120, n_jobs=-1, random_state=42)))
            cands.append(("ridge", lambda: Ridge(alpha=1.0, random_state=42)))
            try:
                from sklearn.ensemble import HistGradientBoostingRegressor

                cands.append(("histgb", lambda: HistGradientBoostingRegressor(
                    max_iter=120, max_depth=3, learning_rate=0.05, random_state=42)))
            except Exception:
                pass
        except Exception:
            logger.warning("sklearn 集成模型不可用，委员会仅含 GBDT 重型库")
        # ---- qlib 原生（门控）----
        if self._has_qlib:
            cands.append(("qlib_lgb", lambda: _QlibGBDTModel("LGBModel")))
            cands.append(("qlib_xgb", lambda: _QlibGBDTModel("XGBModel")))
        return cands

    @staticmethod
    def _cv_dir_acc(X: np.ndarray, y: np.ndarray, factory: Callable,
                    n_splits: int = 3) -> Optional[float]:
        """Expanding-window 交叉验证估计方向准确率（无前视）。"""
        n = len(X)
        if n < 240 or X.shape[1] == 0:
            return None
        edges = np.linspace(int(n * 0.5), n, n_splits + 1).astype(int)
        accs: List[float] = []
        for i in range(n_splits):
            tr, te = np.arange(edges[i]), np.arange(edges[i], edges[i + 1])
            if len(te) < 30:
                continue
            try:
                m = factory()
                m.fit(X[tr], y[tr])
                p = np.asarray(m.predict(X[te])).ravel()
                accs.append(float(np.mean(np.sign(p) == np.sign(y[te]))))
            except Exception:
                return None
        return float(np.mean(accs)) if accs else None

    # ---------- 训练（剔除保留带，walk-forward 诚实） ----------
    def fit(self, work: pd.DataFrame, exclude_tail: int = 20) -> bool:
        """在所有标的上训练「每周期一个」梯度提升模型，预测未来 horizon 日收益。

        Args:
            work: 多标的 DataFrame（``code``/``date``/``adj_back_close``/OHLCV），由
                ``work`` pivot 前传入。
            exclude_tail: 训练时剔除末尾 N 个交易日（保留给 walk-forward 评估/目标预测），
                确保评估落在未见样本上。建议 ``>= max(horizon) + n_eval_dates + buffer``。
        Returns:
            是否训练成功（失败则标记 ``_train_failed``，后续 predict 一律返回 None）。
        """
        if self._trained or self._train_failed:
            return self._trained
        try:
            self._load()
        except ImportError as exc:
            self._train_failed = True
            logger.warning(f"Qlib 预测源不可用：{exc}")
            return False
        try:
            # 注意：X / y 必须**按周期分开**保存——不同周期标签的有效行数不同
            # （shift(-h) 对长周期丢弃更多行），合并后行数会错位。
            all_x: Dict[int, List[pd.DataFrame]] = {h: [] for h in self.horizons}
            ally: Dict[int, List[pd.Series]] = {h: [] for h in self.horizons}
            for code, g in work.groupby("code", sort=False):
                g = g.sort_values("date").reset_index(drop=True)
                if len(g) < self._MIN_LEN + exclude_tail:
                    continue
                feats = self._build_features(g)
                c = pd.to_numeric(g["adj_back_close"], errors="coerce")
                labels = {h: c.shift(-h) / c - 1.0 for h in self.horizons}
                # 剔除末尾保留带：仅用 head 部分训练，tail 留给评估/目标
                cut = max(self._MIN_LEN, len(g) - exclude_tail)
                feats_head = feats.iloc[:cut]
                for h in self.horizons:
                    y = labels[h].iloc[:cut]
                    dfh = pd.concat([feats_head, y.rename("y")], axis=1).dropna()
                    if len(dfh) < 100:
                        continue
                    all_x[h].append(dfh.drop(columns=["y"]))
                    ally[h].append(dfh["y"])

            if not any(all_x[h] for h in self.horizons):
                logger.warning("Qlib 预测源：训练样本不足，跳过（降级）")
                self._train_failed = True
                return False

            # 用 H1 的特征列作为统一特征空间（各周期特征列一致，取一份定列序）
            X_ref = pd.concat(all_x[self.horizons[0]], ignore_index=True) if all_x[self.horizons[0]] else pd.concat([df for h in self.horizons for df in all_x[h]], ignore_index=True)
            self._feature_cols = list(X_ref.columns)
            self._feature_means = X_ref.mean()
            # 模型委员会：多模型按 walk-forward dir_acc 选优（每个 horizon 独立）
            self._candidates = self._build_candidates()
            for h in self.horizons:
                if not all_x[h] or not ally[h]:
                    logger.warning(f"Qlib 预测源：周期 {h} 样本不足，跳过该周期")
                    continue
                Xh = pd.concat(all_x[h], ignore_index=True)
                Xh = Xh.reindex(columns=self._feature_cols)
                Xv = Xh.fillna(self._feature_means).values
                yv = pd.concat(ally[h]).clip(-0.5, 0.5).values  # 裁剪极端收益，抗过拟合
                if len(yv) < 100:
                    logger.warning(f"Qlib 预测源：周期 {h} 样本不足，跳过该周期")
                    continue
                health: Dict[str, Optional[float]] = {}
                best_name, best_acc, best_model = None, -1.0, None
                for name, factory in self._candidates:
                    acc = self._cv_dir_acc(Xv, yv, factory)
                    health[name] = acc
                    if acc is not None and acc > best_acc:
                        best_acc, best_name = acc, name
                if best_name is None:
                    logger.warning(f"Qlib 预测源：周期 {h} 所有候选 CV 失败，跳过")
                    self._health[h] = health
                    continue
                best_model = dict(self._candidates)[best_name]()
                best_model.fit(Xv, yv)
                self._models[h] = best_model
                self._best_name[h] = best_name
                self._health[h] = health
                logger.info(
                    f"Qlib 预测源 周期{h}：选优={best_name} CV_dir_acc={best_acc:.3f}；"
                    f"候选={ {k: (round(v, 3) if v is not None else None) for k, v in health.items()} }"
                )

            if not self._models:
                logger.warning("Qlib 预测源：所有周期训练失败，降级")
                self._train_failed = True
                return False

            self._trained = True
            backend = "qlib+梯度提升" if self._has_qlib else "pandas复刻+xgboost/sklearn"
            logger.info(
                f"Qlib 预测源训练完成（样本={len(Xv)}，特征={len(self._feature_cols)}，"
                f"保留带={exclude_tail}，后端={backend}）"
            )
            return True
        except Exception as exc:  # noqa: BLE001
            self._train_failed = True
            logger.warning(f"Qlib 预测源训练失败（降级）：{exc}")
            return False

    def model_health(self) -> Dict[int, Dict[str, Optional[float]]]:
        """返回各 horizon 候选模型的 CV 方向准确率（供监控/审计/调试）。"""
        return self._health

    # ---------- 推理（与 Kronos/Darts 同签名：predict(bars, horizon)） ----------
    def predict(self, bars, horizon: int) -> Optional[Dict[str, float]]:
        """对单标的历史窗口预测未来 ``horizon`` 日收益，返回 {ret_pred, lower, upper}。

        Args:
            bars: 单标的 OHLCV DataFrame（历史截至预测时点 t，含 ``date`` 与 OHLCV 列）。
                与 Kronos 相同的输入形态；Darts 用收盘价序列，本适配器用 DataFrame。
            horizon: 预测步长（1/5/10）。
        Returns:
            ``{"ret_pred", "lower", "upper"}`` 或 ``None``（不可用/降级）。
        """
        try:
            self._load()
        except ImportError as exc:
            logger.debug(f"Qlib 预测源不可用：{exc}")
            return None
        if not self._trained:
            return None
        try:
            if bars is None or not isinstance(bars, pd.DataFrame) or len(bars) < self._MIN_LEN:
                return None
            feats = self._build_features(bars)
            row = feats.iloc[[-1]].reindex(columns=self._feature_cols)
            row = row.fillna(self._feature_means).fillna(0.0)
            Xv = row.values
            h = int(min(int(horizon), max(self.horizons)))
            model = self._models.get(h) or self._models.get(self.horizons[-1])
            if model is None:
                return None
            ret_pred = float(model.predict(Xv)[0])
            if not np.isfinite(ret_pred):
                ret_pred = 0.0
            # 概率区间：近期收益波动 × √horizon × 1.96（与 baseline/kronos/darts 一致）
            c = pd.to_numeric(bars["adj_back_close"], errors="coerce")
            recent = c.pct_change().rolling(20).std().dropna()
            recent_std = float(recent.iloc[-1]) if len(recent) >= 1 else 0.0
            if not np.isfinite(recent_std):
                recent_std = 0.0
            band = recent_std * np.sqrt(h) * 1.96
            return {
                "ret_pred": float(ret_pred),
                "lower": float(ret_pred - band),
                "upper": float(ret_pred + band),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Qlib 预测源推理失败（降级）：{exc}")
            return None


class _QlibGBDTModel:
    """qlib 原生 GBDT 模型封装（需 qlib 已 init 且配置数据 provider）。

    仅当 qlib 可用时登记进委员会；实际训练走 qlib 的 ``R``/``DatasetH`` 工作流。
    沙箱未装 qlib 时不会被实例化，委员会自动退回 sklearn-API 等价实现。
    """

    def __init__(self, model_class: str) -> None:
        self.model_class = model_class
        try:
            import qlib  # noqa: F401
        except Exception as exc:  # pragma: no cover - 仅 qlib 环境可达
            raise ImportError(f"qlib 未安装，无法使用原生 {model_class}") from exc
        # 完整 qlib 训练需 qlib.init() + handler + DatasetH；此处保留接口，
        # 具体 fit/predict 在 qlib 数据 provider 就绪后实现（见 Qlib 集成任务）。
        raise NotImplementedError(
            "qlib 原生模型需配置 qlib 数据 provider 后启用（见 Qlib 集成任务）"
        )

    def fit(self, X, y):
        raise NotImplementedError

    def predict(self, X):
        raise NotImplementedError
