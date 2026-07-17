"""预测信号计算（融合第 4 源 · F-18 核心差异化能力）。

标签定义（P1-5）：``label = 次日超额收益方向（相对中证全指/等权基准）+ 5/10 日收益``，
``horizon`` 显式（1/5/10）。预测定位为**横截面排序辅助**而非绝对收益。

模型：Kronos / Darts / QLib（懒加载，零样本跨域）→ 效果经 walk-forward + ``predict_health``
自动降权；未安装或效果差则**降级为实验性、不进核心融合权重**（P1-5 降级机制）。
v1 内置 ``baseline_xsec_momentum`` 作为始终可用的兜底预测（横截面动量基线）。
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from factors.darts_adapter import DartsAdapter
from factors.kronos_adapter import KronosAdapter
from factors.qlib_predict_adapter import QlibAdapter
from loguru import logger

try:
    from scipy.stats import spearmanr  # noqa: F401

    _HAS_SPEAR = True
except Exception:  # pragma: no cover
    _HAS_SPEAR = False


class PredictionGenerator:
    """预测编排器。"""

    def __init__(self, cfg: Optional[Dict] = None, model_order: Optional[List[str]] = None) -> None:
        self.cfg = cfg or {}
        # 预测源顺序：baseline（横截面动量兜底）+ Kronos + Darts + QLib（均为可选/可降级）。
        # QLib 在此作为「预测源」（与 factors/qlib_factors.py 的「因子引擎」角色解耦）。
        self.models = model_order or ["baseline_xsec_momentum", "kronos", "darts", "qlib"]
        fusion = self.cfg.get("fusion", {})
        self.base_predict_weight = fusion.get("base_weights", {}).get("predict", 0.25)
        self.min_dir_acc = float(fusion.get("predict_min_dir_acc", 0.52))
        # 动态 IC 加权（P1-1b）：权重由横截面 IC 决定，替代静态 dir_acc 二值门；
        # 连续 predict_ic_gate_windows 个滚动窗口 |IC|<predict_ic_eps → 自动剔除（dropped）。
        pred_cfg = fusion.get("predict_ic", {})
        self.ic_window = int(pred_cfg.get("rolling_window", 3))        # 每滚动窗口含评估日数
        self.ic_eps = float(pred_cfg.get("eps", 0.02))                 # |IC| 低于此视为 ≈0
        self.ic_ref = float(pred_cfg.get("ref", 0.05))                 # 参考“良好”IC，用于权重归一
        self.ic_gate_windows = int(pred_cfg.get("gate_windows", 3))    # 连续 N 窗口 ≈0 → 剔除
        self.horizons = [1, 5, 10]
        # Kronos 模型尺寸：settings.yaml kronos.model_repo（默认 base）；
        # 环境变量 KRONOS_MODEL_REPO 优先级最高（适配器内已处理）
        kronos_cfg = self.cfg.get("kronos", {})
        kronos_model_repo = kronos_cfg.get("model_repo")
        self.kronos = KronosAdapter(model_repo=kronos_model_repo)
        self.darts = DartsAdapter()
        self.qlib = QlibAdapter(horizons=self.horizons)

    # ---- 公开入口 ------------------------------------------------
    def generate(
        self,
        bars_df: pd.DataFrame,
        universe_codes: Optional[List[str]] = None,
        target_date: Optional[dt.date] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """生成 ``predict_values`` 与 ``predict_health``。

        Returns:
            (predict_df, health_df)
        """
        if bars_df is None or bars_df.empty:
            return pd.DataFrame(), pd.DataFrame()

        work = bars_df
        if universe_codes is not None:
            work = bars_df[bars_df["code"].isin(universe_codes)].copy()
        work = work.sort_values(["code", "date"]).reset_index(drop=True)

        # 1) 计算基准（等权）日收益，构造超额标签
        label = self._build_labels(work)  # (date, code, horizon) -> label_dir/excess_ret
        # 2) baseline 预测（横截面动量）
        base_pred = self._baseline_predict(work)  # (date, code) -> pred_score, band
        # 3) 各模型预测 + 健康度
        # 评估窗口参数（Darts 截断与 QLib 保留带共用）
        n_eval = int(os.environ.get("KRONOS_N_EVAL_DATES", "15"))
        max_date = work["date"].max()

        # Darts 需先在所有标的收益率 pool 上训练一次（Kronos 无需）。
        # P1-1a 前视修复：仅用「早于最早评估日」的 trailing window 训练，确保模型
        # 不含任何评估点（最近 n_eval 日）的未来信息；z-score 统计量仅来自该训练段。
        # KRONOS_SKIP_DARTS=1 可跳过 Darts 预训练与评估（已知 A 股白噪声上塌缩为 0、
        # 训练耗时长、易被环境休眠打断）——跳过则本项不参与融合，仅 Kronos/QLib/baseline。
        skip_darts = bool(int(os.environ.get("KRONOS_SKIP_DARTS", "0") or 0))
        try:
            if not skip_darts:
                panel = work.pivot(index="date", columns="code", values="adj_back_close")
                # 评估点 ≈ 最近 n_eval 日（各周期独立取最近 N 个，最早约在
                # max_date 前 (n_eval + max_horizon - 1) 个交易日）；训练截断到该点之前。
                cutoff = self._darts_train_cutoff(max_date, n_eval, max(self.horizons))
                piv = panel.copy()
                piv.index = pd.to_datetime(piv.index)
                piv_train = piv.loc[:cutoff]
                if len(piv_train) >= 30:
                    self.darts.fit(piv_train)
                else:
                    logger.info("Darts 训练数据不足（截断后），跳过（降级）")
            else:
                logger.info("Darts 预训练跳过（KRONOS_SKIP_DARTS=1）：已知 A 股白噪声上塌缩为 0")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Darts 预训练跳过：{exc}")

        # QLib 预测源：在所有标的上训练「每周期梯度提升模型」（剔除保留带，walk-forward 诚实）。
        # KRONOS_SKIP_QLIB=1 可跳过：本地未装 qlib 时回退 pandas+xgboost 仍可用，
        # 但若想完全禁用则设此标志。保留带长度由 KRONOS_QLIB_EXCLUDE_TAIL 控制
        # （建议 >= max(horizon) + n_eval_dates + buffer，默认 20）。
        skip_qlib = bool(int(os.environ.get("KRONOS_SKIP_QLIB", "0") or 0))
        try:
            if not skip_qlib:
                exclude_tail = int(os.environ.get("KRONOS_QLIB_EXCLUDE_TAIL",
                                                  str(max(20, max(self.horizons) + n_eval + 5))))
                self.qlib.fit(work, exclude_tail=exclude_tail)
            else:
                logger.info("QLib 预测源跳过（KRONOS_SKIP_QLIB=1）")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"QLib 预测源训练跳过：{exc}")

        predict_rows: List[Dict] = []
        health_rows: List[Dict] = []

        for model in self.models:
            if model == "baseline_xsec_momentum":
                pdf, hdf = self._eval_baseline(base_pred, label)
            elif skip_darts and model == "darts":
                logger.warning("预测模型 darts 跳过（KRONOS_SKIP_DARTS=1）")
                continue
            elif skip_qlib and model == "qlib":
                logger.warning("预测模型 qlib 跳过（KRONOS_SKIP_QLIB=1）")
                continue
            else:
                pdf, hdf = self._eval_heavy(model, work, label, target_date)
            if pdf is None or pdf.empty:
                logger.warning(f"预测模型 {model} 不可用，跳过（降级）")
                continue
            predict_rows.append(pdf)
            health_rows.append(hdf)
            logger.info(
                f"预测模型 {model}：dir_acc={hdf['dir_acc'].iloc[0]:.3f} "
                f"weight={hdf['weight'].iloc[0]:.3f}"
            )

        predict_df = (
            pd.concat(predict_rows, ignore_index=True) if predict_rows else pd.DataFrame()
        )
        health_df = (
            pd.concat(health_rows, ignore_index=True) if health_rows else pd.DataFrame()
        )
        return predict_df, health_df

    # ---- 标签 & baseline -----------------------------------------
    def _build_labels(self, work: pd.DataFrame) -> pd.DataFrame:
        """构造超额收益方向标签（point-in-time）。"""
        frames = []
        for code, g in work.groupby("code", sort=False):
            g = g.sort_values("date").reset_index(drop=True)
            pr = g["adj_back_close"]
            rec = {"date": g["date"].values, "code": code}
            for h in self.horizons:
                fwd = pr.shift(-h) / pr - 1.0
                rec[f"fwd_{h}"] = fwd.values
            frames.append(pd.DataFrame(rec))
        df = pd.concat(frames, ignore_index=True)

        # 横截面均值（等权基准代理）
        mean = df.groupby("date")[[f"fwd_{h}" for h in self.horizons]].transform("mean")
        for h in self.horizons:
            excess = df[f"fwd_{h}"] - mean[f"fwd_{h}"]
            df[f"excess_{h}"] = excess
            df[f"label_dir_{h}"] = np.sign(excess).fillna(0).astype(int)
        return df

    @staticmethod
    def _baseline_predict(work: pd.DataFrame) -> pd.DataFrame:
        """横截面动量基线：pred_score = 5 日动量（shift，无前视）。"""
        frames = []
        for code, g in work.groupby("code", sort=False):
            g = g.sort_values("date").reset_index(drop=True)
            pr = g["adj_back_close"]
            ret = pr.pct_change()
            pred = pr / pr.shift(5) - 1.0  # 5 日动量
            band = ret.rolling(20).std().fillna(ret.std())
            frames.append(
                pd.DataFrame(
                    {
                        "date": g["date"].values,
                        "code": code,
                        "pred_score": pred.values,
                        "band": band.values,
                    }
                )
            )
        return pd.concat(frames, ignore_index=True)

    def _eval_baseline(
        self, base_pred: pd.DataFrame, label: pd.DataFrame
    ) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        merged = label.merge(base_pred, on=["date", "code"], how="inner")
        rows: List[Dict] = []
        dir_accs: List[float] = []
        mapes: List[float] = []
        for h in self.horizons:
            pred = merged["pred_score"]
            ret_pred = pred * np.sqrt(h)
            band = merged["band"].fillna(merged["band"].mean())
            lower = ret_pred - 1.96 * band * np.sqrt(h)
            upper = ret_pred + 1.96 * band * np.sqrt(h)
            dir_pred = np.sign(pred.fillna(0.0)).astype(int)
            actual = merged[f"excess_{h}"]
            mask = pred.notna() & actual.notna() & (actual != 0)
            if mask.sum() > 0:
                acc = float((np.sign(pred[mask]) == np.sign(actual[mask])).mean())
                mape = float((pred[mask] - actual[mask]).abs().mean())
            else:
                acc, mape = float("nan"), float("nan")
            dir_accs.append(acc)
            mapes.append(mape)
            for i in range(len(merged)):
                rows.append(
                    {
                        "code": merged["code"].iloc[i],
                        "date": merged["date"].iloc[i],
                        "model_name": "baseline_xsec_momentum",
                        "horizon": h,
                        "dir_pred": int(dir_pred.iloc[i]),
                        "ret_pred": float(ret_pred.iloc[i]),
                        "lower": float(lower.iloc[i]),
                        "upper": float(upper.iloc[i]),
                        "dir_acc_hist": acc,
                    }
                )
        pdf = pd.DataFrame(rows)
        acc_mean = float(np.nanmean(dir_accs)) if dir_accs else float("nan")
        mape_mean = float(np.nanmean(mapes)) if mapes else float("nan")
        weight = self._weight(acc_mean)
        hdf = pd.DataFrame(
            [
                {
                    "model_name": "baseline_xsec_momentum",
                    "date": merged["date"].max(),
                    "mape": mape_mean,
                    "dir_acc": acc_mean,
                    "weight": weight,
                }
            ]
        )
        return pdf, hdf

    # ---- 重型模型（懒加载，walk-forward 验证） -------------------
    def _eval_heavy(
        self,
        model: str,
        work: pd.DataFrame,
        label: pd.DataFrame,
        target_date: Optional[dt.date] = None,
        n_eval_dates: int = int(os.environ.get("KRONOS_N_EVAL_DATES", "15")),
    ) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """重型模型（Kronos/Darts）真实推理 + walk-forward 方向准确率评估。

        关键点（修正前视偏差）：
        - **历史窗口评估**：对每只标的取标签非 NaN 的最后 ``n_eval_dates`` 个历史时点，
          用「截至该时点的价格」预测，与该时点的真实 ``label_dir`` 比对，得到样本外
          方向准确率（绝不使用未来信息）。
        - **目标日预测**：用全量价格对 ``target_date`` 产出预测，供信号融合（当
          dir_acc >= 阈值时按权重进入核心融合；否则自动降权为实验性）。
        """
        adapter = (
            self.kronos if model == "kronos"
            else self.darts if model == "darts"
            else self.qlib
        )
        # 样本量限制（调试/快速验证用）：仅取前 N 只标的做 walk-forward 评估，
        # 目标日预测同样只覆盖这 N 只。不影响算法逻辑，仅缩小评估规模。
        n_stocks = int(os.environ.get("KRONOS_EVAL_STOCKS", "0") or 0)
        if n_stocks > 0:
            keep = list(work["code"].drop_duplicates().head(n_stocks))
            work = work[work["code"].isin(keep)].copy()
            logger.info(f"重型模型 {model}：评估样本限制为前 {n_stocks} 只标的")
        try:
            import json as _json

            def _row_ser(row):
                r = dict(row)
                d = r.get("date")
                if isinstance(d, (dt.date, dt.datetime, pd.Timestamp)):
                    r["date"] = pd.Timestamp(d).date().isoformat()
                return r

            def _row_deser(row):
                r = dict(row)
                if isinstance(r.get("date"), str):
                    try:
                        r["date"] = dt.date.fromisoformat(r["date"])
                    except Exception:  # noqa: BLE001
                        pass
                return r

            # ---- 检查点（断点续跑）：应对沙箱休眠杀进程 ----
            # 文件名含 (model, n_eval_dates, n_stocks) 签名，避免不同配置互相污染。
            sig = f"{model}_e{n_eval_dates}_s{n_stocks}"
            ckpt_path = os.environ.get("KRONOS_EVAL_CKPT") or (
                f"_kronos_eval_ckpt_{sig}.json"
            )
            ckpt = {"sig": sig, "done_codes": [], "pairs": [], "target_rows": []}
            if os.path.exists(ckpt_path):
                try:
                    with open(ckpt_path, "r", encoding="utf-8") as _fh:
                        _old = _json.load(_fh)
                    if _old.get("sig") == sig:
                        ckpt = _old
                        logger.info(
                            f"重型模型 {model}：载入检查点，已完成 {len(ckpt['done_codes'])} 只，"
                            f"累计 {len(ckpt['pairs'])} 个方向样本"
                        )
                    else:
                        logger.warning(f"检查点签名不符（{_old.get('sig')}≠{sig}），忽略重新开始")
                except Exception:  # noqa: BLE001
                    logger.warning("检查点读取失败，重新开始")

            done_codes = set(ckpt.get("done_codes", []))
            all_pairs = list(ckpt.get("pairs", []))          # [[dir_pred, label], ...] 跨运行累计
            ckpt_target_rows = [_row_deser(r) for r in ckpt.get("target_rows", [])]
            new_target_rows: List[Dict] = []
            # 在外层初始化并在循环内累计（断点续跑时若全部标的已 done，循环体不进入
            # 也不会触发 UnboundLocalError；同时让 IC 覆盖全部标的而非仅最后一只）
            ic_pairs: List[Dict] = []  # (date, code, ret_pred, actual_fwd_ret) 用于 IC

            def _save_ckpt() -> None:
                _tmp = ckpt_path + ".tmp"
                _payload = {
                    "sig": sig,
                    "done_codes": sorted(done_codes),
                    "pairs": all_pairs,
                    "target_rows": [_row_ser(r) for r in (ckpt_target_rows + new_target_rows)],
                }
                with open(_tmp, "w", encoding="utf-8") as _fh:
                    _json.dump(_payload, _fh)
                os.replace(_tmp, ckpt_path)  # 原子替换，防写坏

            eval_rows: List[Dict] = []
            for code, g in work.groupby("code", sort=False):
                if code in done_codes:
                    continue  # 已评估，跳过（断点续跑）
                g = g.sort_values("date").reset_index(drop=True)
                prices_full = g.set_index("date")["adj_back_close"]
                lab = label[label["code"] == code].set_index("date")
                if lab.empty or len(prices_full) < 30:
                    done_codes.add(code)  # 无效标的也标记完成，避免反复尝试
                    _save_ckpt()
                    continue
                # 1) 历史 walk-forward 评估时点（每周期独立选取各自标签非 NaN 的最近 N 个）
                #    关键修正：H5/H10 需要未来 5/10 日数据，若与 H1 共用「贴近数据末尾的
                #    最近 N 个时点」，则末端时点无足够未来数据 → 标签 NaN→0，被 a!=0 过滤，
                #    导致 H5/H10 实际零样本、无法评估。改为每周期用自身的有效时点。
                #    由此 pairs 顺序变为 [H1×N, H5×N, H10×N]（按周期外层、时点的内层）。
                stock_new_pairs: List[List[int]] = []
                # ic_pairs 在外层声明并跨股票累计（见循环前初始化），此处不再重置
                for h in self.horizons:
                    ld = lab[f"label_dir_{h}"]
                    # 关键：label_dir 对「无未来数据」的时点是 fillna(0)（非 NaN），
                    # dropna 过滤不掉；须用 !=0 排除这些无效时点，否则会选到数据末尾
                    # H5/H10 全为 0 的时点，导致长周期零样本。
                    cand = list(lab[lab[f"label_dir_{h}"] != 0].index)
                    eval_dates_h = cand[-n_eval_dates:]
                    for t in eval_dates_h:
                        p_t = prices_full.loc[:t]
                        if len(p_t) < 30:
                            continue
                        # Kronos / QLib 吃 OHLCV 分组（截至 t 的历史窗），
                        # Darts 吃后复权收盘价序列
                        g_t = g[g["date"] <= t] if model in ("kronos", "qlib") else None
                        kronos_inp = g_t if model in ("kronos", "qlib") else p_t
                        if t not in ld.index or ld.loc[t] == 0:
                            continue
                        actual = lab[f"fwd_{h}"].loc[t]
                        try:
                            out = adapter.predict(kronos_inp, h)
                        except Exception:  # noqa: BLE001
                            out = None
                        if out is None:
                            continue
                        rp = out.get("ret_pred", 0.0)
                        dp = int(np.sign(rp)) if np.isfinite(rp) else 0
                        a = int(ld.loc[t])
                        stock_new_pairs.append([dp, a])
                        # IC 样本（需预测与实际前向收益均有效）
                        if np.isfinite(rp) and actual is not None and np.isfinite(float(actual)):
                            ic_pairs.append(
                                {"date": t, "code": code, "ret_pred": float(rp), "actual": float(actual)}
                            )
                        eval_rows.append(
                            {
                                "code": code,
                                "date": t,
                                "model_name": model,
                                "horizon": h,
                                "dir_pred": dp,
                                "ret_pred": float(out["ret_pred"]),
                                "lower": float(out["lower"]),
                                "upper": float(out["upper"]),
                                "dir_acc_hist": float("nan"),
                            }
                        )
                # 2) 目标日预测（供融合；权重由历史评估决定）
                if target_date is not None:
                    kronos_inp = g if model in ("kronos", "qlib") else prices_full
                    for h in self.horizons:
                        try:
                            out = adapter.predict(kronos_inp, h)
                        except Exception:  # noqa: BLE001
                            out = None
                        if out is None:
                            continue
                        rp = out.get("ret_pred", 0.0)
                        dp = int(np.sign(rp)) if np.isfinite(rp) else 0
                        new_target_rows.append(
                            {
                                "code": code,
                                "date": target_date,
                                "model_name": model,
                                "horizon": h,
                                "dir_pred": dp,
                                "ret_pred": float(out["ret_pred"]),
                                "lower": float(out["lower"]),
                                "upper": float(out["upper"]),
                                "dir_acc_hist": float("nan"),
                            }
                        )
                # 提交本只股票的检查点（原子落盘）
                all_pairs.extend(stock_new_pairs)
                done_codes.add(code)
                _save_ckpt()
                logger.debug(
                    f"重型模型 {model}：{code} 完成（累计 {len(done_codes)} 只，"
                    f"{len(all_pairs)} 样本）"
                )
            # 方向准确率（仅统计标签非 0 的样本，跨运行累计）
            valid = [(d, a) for d, a in all_pairs if a != 0]
            acc = (
                float(np.mean([1 if d == a else 0 for d, a in valid]))
                if valid
                else float("nan")
            )
            # P1-1b 动态 IC 加权：横截面 per-date Spearman IC → 滚动窗口 → 闸门
            ic_val, rolling_ic, dropped = self._compute_ic_and_gate(ic_pairs)
            weight = self._dynamic_weight(ic_val, dropped, acc)
            hdf = pd.DataFrame(
                [
                    {
                        "model_name": model,
                        "date": target_date,
                        "mape": float("nan"),
                        "dir_acc": acc,
                        "weight": weight,
                        "ic": ic_val,
                        "rolling_ic": rolling_ic,
                        "dropped": bool(dropped),
                    }
                ]
            )
            # predict_df 以目标日预测为主（供融合），历史评估行仅用于诊断
            target_rows = ckpt_target_rows + new_target_rows
            pdf = pd.DataFrame(target_rows if target_rows else eval_rows)
            return pdf, hdf
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"重型模型 {model} 评估失败（降级）：{exc}")
            return None, None

    # ---- 训练数据截断（P1-1a 前视修复） ---------------------------
    @staticmethod
    def _darts_train_cutoff(max_date, n_eval: int, max_horizon: int) -> "pd.Timestamp":
        """Darts 训练窗口截止日：早于最早评估日，确保模型不含任何评估点未来信息。

        评估点最早约在 ``max_date`` 前 ``(n_eval + max_horizon - 1)`` 个交易日，
        再留 10 日缓冲，对 max_date 向前偏移 BusinessDay。
        """
        return pd.to_datetime(max_date) - pd.tseries.offsets.BusinessDay(
            n_eval + max_horizon + 10
        )

    # ---- 健康度 -> 融合权重 ---------------------------------------
    def _weight(self, dir_acc: float) -> float:
        """由方向准确率推导融合权重；低于阈值 -> 0（实验性，不进核心）。

        仅作为 baseline（横截面动量，无 IC 统计）的兜底权重函数；重型模型改走
        ``_dynamic_weight``（基于 IC，P1-1b）。
        """
        if dir_acc is None or (isinstance(dir_acc, float) and np.isnan(dir_acc)):
            return 0.0
        if dir_acc < self.min_dir_acc:
            return 0.0
        return float(self.base_predict_weight * max(0.0, (dir_acc - 0.5) * 2.0))

    # ---- P1-1b 动态 IC 加权 + 闸门 ---------------------------------
    @staticmethod
    def _per_date_ic(ic_pairs: List[Dict]) -> List[Tuple[dt.date, float]]:
        """横截面 per-date Spearman IC（预测 vs 实际前向收益），跨标的。"""
        if not ic_pairs:
            return []
        df = pd.DataFrame(ic_pairs)
        out: List[Tuple[dt.date, float]] = []
        for d, grp in df.groupby("date"):
            if len(grp) < 3:
                continue  # 样本过少不估 IC
            try:
                if _HAS_SPEAR:
                    from scipy.stats import spearmanr

                    r = spearmanr(grp["ret_pred"], grp["actual"])[0]
                else:
                    pr = grp["ret_pred"].rank()
                    ar = grp["actual"].rank()
                    r = float(np.corrcoef(pr.values, ar.values)[0, 1])
                if np.isfinite(r):
                    out.append((d, float(r)))
            except Exception:  # noqa: BLE001
                continue
        return out

    def _compute_ic_and_gate(
        self, ic_pairs: List[Dict]
    ) -> Tuple[float, float, bool]:
        """由 IC 样本推导（均值 IC, 最近滚动窗口 IC, 是否连续 N 窗口 ≈0 剔除）。

        Returns:
            (ic_mean, rolling_ic_last, dropped)
        """
        per_date = self._per_date_ic(ic_pairs)
        if not per_date:
            return float("nan"), float("nan"), False
        ics = [v for _, v in per_date]
        ic_mean = float(np.mean(ics))
        # 滚动窗口（按日期升序，每 ic_window 个评估日一窗）
        dates = [d for d, _ in per_date]
        from pandas import Series

        s = Series([v for _, v in per_date], index=dates).sort_index()
        roll = s.rolling(window=self.ic_window, min_periods=self.ic_window).mean().dropna()
        rolling_list = roll.tolist()
        rolling_last = float(rolling_list[-1]) if rolling_list else float("nan")
        # 闸门：最近 ic_gate_windows 个滚动窗口全部 |IC| < eps → 剔除
        dropped = (
            len(rolling_list) >= self.ic_gate_windows
            and all(abs(w) < self.ic_eps for w in rolling_list[-self.ic_gate_windows:])
        )
        return ic_mean, rolling_last, bool(dropped)

    def _dynamic_weight(
        self, ic_val: float, dropped: bool, dir_acc: float
    ) -> float:
        """动态 IC 权重（P1-1b）：权重 ∝ 均值 IC（相对参考 IC 归一），剔除时为 0；
        IC 不可得时回退 dir_acc 软加权。"""
        if dropped:
            return 0.0
        if ic_val is not None and np.isfinite(ic_val):
            if ic_val <= self.ic_eps:
                return 0.0
            frac = max(0.0, min(1.0, (ic_val - self.ic_eps) / max(1e-6, (self.ic_ref - self.ic_eps))))
            return float(self.base_predict_weight * frac)
        # IC 不可得（样本不足/标的少）→ 回退 dir_acc 软加权
        return self._weight(dir_acc)
