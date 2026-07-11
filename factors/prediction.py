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
        self.horizons = [1, 5, 10]
        self.kronos = KronosAdapter()
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
        # Darts 需先在所有标的收益率 pool 上训练一次（Kronos 无需）
        # KRONOS_SKIP_DARTS=1 可跳过 Darts 预训练与评估：A 股日收益近似白噪声，
        # NBEATS 实测 dir_acc→0、权重恒为 0，且训练耗时长、易被环境休眠打断。
        skip_darts = bool(int(os.environ.get("KRONOS_SKIP_DARTS", "0") or 0))
        try:
            if not skip_darts:
                panel = work.pivot(index="date", columns="code", values="adj_back_close")
                self.darts.fit(panel)
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
                n_eval = int(os.environ.get("KRONOS_N_EVAL_DATES", "15"))
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
            weight = self._weight(acc)
            hdf = pd.DataFrame(
                [
                    {
                        "model_name": model,
                        "date": target_date,
                        "mape": float("nan"),
                        "dir_acc": acc,
                        "weight": weight,
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

    # ---- 健康度 -> 融合权重 ---------------------------------------
    def _weight(self, dir_acc: float) -> float:
        """由方向准确率推导融合权重；低于阈值 -> 0（实验性，不进核心）。"""
        if dir_acc is None or (isinstance(dir_acc, float) and np.isnan(dir_acc)):
            return 0.0
        if dir_acc < self.min_dir_acc:
            return 0.0
        return float(self.base_predict_weight * max(0.0, (dir_acc - 0.5) * 2.0))
