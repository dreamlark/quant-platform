"""Darts 概率时间序列预测适配器（Apache 2.0，懒加载，真实可训练）。

实现（A 任务）：在所有标的的**收益率 pool** 上训练一个轻量 NBEATS（跨标的收益率尺度一致、
可迁移），对单标的预测未来 ``horizon`` 日收益及概率区间（lower/upper）。作为预测第 4 源的
方向/区间辅助（横截面排序辅助，非绝对收益）。同 Kronos，零样本跨域，须 walk-forward 验证 +
``predict_health`` 自动降权（P1-5）。

为规避"模型坍缩到均值（预测恒为 0）"：训练在跨标的收益率池上进行（样本量充足），并对收益率做
z-score 标准化（预测后再反标准化），使模型学到非平凡动态而非退化为常数。
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from loguru import logger


class DartsAdapter:
    """Darts 概率预测适配器（真实训练版）。"""

    name = "darts"

    def __init__(self, model_name: str = "NBEATS", horizon: int = 1, max_horizon: int = 10) -> None:
        self.model_name = model_name
        self.horizon = horizon
        self.max_horizon = max_horizon
        self._model = None
        self._trained = False
        self._train_failed = False  # 一次性训练失败标记：避免逐标的重试训练挂起
        self._mean = 0.0
        self._std = 1.0

    def _load(self):
        if self._train_failed:
            raise ImportError("Darts 已降级（此前训练失败，不重复尝试）")
        try:
            import darts  # noqa: F401
            import torch  # noqa: F401
        except ImportError as exc:  # 重型依赖未装 -> 显式降级
            self._train_failed = True
            raise ImportError(
                "darts/torch 未安装（可选重型依赖）。"
                "可通过 `pip install darts torch pytorch_lightning` 启用；当前降级 baseline。"
            ) from exc
        return True

    def fit(self, panel: pd.DataFrame) -> bool:
        """在所有标的收益率 pool 上训练全局 NBEATS。

        ``panel``: index=date, columns=code, values=adj_back_close（由 ``work`` pivot 而来）。
        训练一次后缓存，后续预测直接推理（迁移学习）。
        """
        if self._trained or self._train_failed:
            return self._trained
        try:
            self._load()
            from darts import TimeSeries
            from darts.models import NBEATSModel

            # 跨标的收益率池（截面 stack），去掉极端值避免训练不稳定
            rets = panel.pct_change().dropna().stack()
            rets = rets[rets.abs() < 0.5]
            if len(rets) < 200:
                logger.warning("Darts: 训练样本不足，跳过（降级）")
                self._train_failed = True
                return False
            self._mean = float(rets.mean())
            self._std = float(rets.std()) or 1.0
            # 池化收益率展平为单索引序列（darts 接受 RangeIndex；freq 仅为占位）
            z = ((rets - self._mean) / self._std).clip(-5.0, 5.0).reset_index(drop=True)
            ts = TimeSeries.from_series(z, freq="B")
            logger.info("Darts(NBEATS) 训练全局模型（收益率 pool，CPU）...")
            model = NBEATSModel(
                input_chunk_length=30,
                output_chunk_length=self.max_horizon,
                num_stacks=2,
                num_blocks=1,
                num_layers=3,
                layer_widths=[48, 48],
                n_epochs=20,
                batch_size=64,
                random_state=42,
                pl_trainer_kwargs={"accelerator": "cpu", "enable_progress_bar": False, "logger": False},
            )
            model.fit(ts)
            self._model = model
            self._trained = True
            logger.info("Darts(NBEATS) 训练完成")
            return True
        except Exception as exc:  # noqa: BLE001
            self._train_failed = True
            logger.warning(f"Darts 训练失败（降级）：{exc}")
            return False

    def predict(self, prices: pd.Series, horizon: int) -> Optional[Dict[str, float]]:
        """对单标的后复权价序列做概率预测，返回 {ret_pred, lower, upper}。

        实现：价格 -> 收益率 -> z-score 标准化 -> NBEATS 预测 -> 反标准化得收益率。
        需先 ``fit``；未训练则返回 None（由调用方降级）。
        """
        try:
            self._load()
        except ImportError as exc:
            logger.debug(f"Darts 不可用：{exc}")
            return None
        if not self._trained:
            return None
        try:
            from darts import TimeSeries

            r = prices.pct_change().dropna()
            if len(r) < 30:
                logger.debug("Darts: 序列过短，跳过")
                return None
            z = ((r - self._mean) / self._std).clip(-5.0, 5.0)
            s = z.copy()
            try:
                s.index = pd.to_datetime(s.index)
            except Exception:  # noqa: BLE001
                s = s.reset_index(drop=True)
            ts = TimeSeries.from_series(s, freq="B")
            pred = self._model.predict(n=self.max_horizon, series=ts)
            pv = pred.values().flatten()
            h = int(min(horizon, self.max_horizon))
            z_pred = float(pv[h - 1]) if h <= len(pv) else float(pv[-1])
            ret_pred = z_pred * self._std + self._mean  # 反标准化
            # 概率区间：近期收益率波动 × √horizon × 1.96
            recent_std = float(r.rolling(20).std().dropna().iloc[-1]) if len(r) >= 20 else 0.0
            if not np.isfinite(ret_pred):
                ret_pred = 0.0
            if not np.isfinite(recent_std):
                recent_std = 0.0
            band = recent_std * np.sqrt(h) * 1.96
            return {
                "ret_pred": ret_pred,
                "lower": ret_pred - band,
                "upper": ret_pred + band,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Darts 推理失败（降级）：{exc}")
            return None
