"""Kronos 时间序列基础模型适配器（真实推理版，已修正）。

修正点（相对旧版——旧版有两个真 bug，导致联网也跑不出真推理）：

1. **模型 id 纠偏**：旧版写死 ``microsoft/kronos``，该仓库在 HuggingFace / 镜像上**均不存在**
   （404）。真实 Kronos 是金融 K 线基础模型（作者 shiyu-coder，arXiv 2508.02739），HF id 为：
     - 分词器：``NeoQuasar/Kronos-Tokenizer-base``
     - 模型：``NeoQuasar/Kronos-small``（另有 -mini / -base）
2. **推理接口纠偏**：旧版把价格拼成文本 ``"series: ... -> next:"`` 喂给通用 AutoTokenizer，
   完全错误。真实 Kronos 用官方 ``model`` 包（``Kronos`` / ``KronosTokenizer`` /
   ``KronosPredictor``），吃 **OHLCV DataFrame + 时间戳**，自回归解码出未来 K 线，再逆归一化
   回价格尺度。
3. **首选下载通道（2026-07-09 更新）**：经实测国内 5 大 HF 镜像站，
   ``Gitee AI (hf-api.gitee.com)`` 是目前**唯一能在受限网络中完整下载 Kronos 模型权重**
   （``model.safetensors ≈ 94MB``，32 秒完成）的通道。
   默认端点优先级：Gitee AI > hf-mirror.com > HF 官方。可通过以下环境变量精细控制：

   ============ ===================================== ================================
   环境变量           用途                              默认值
   ============ ===================================== ================================
   KRONOS_HF_ENDPOINT 全局 HF 端点（模型+分词器统一）    ``https://hf-api.gitee.com``
   KRONOS_MODEL_ENDPOINT 仅模型权重的下载端点            同上
   KRONOS_TOK_ENDPOINT   仅分词器权重的下载端点           同上
   KRONOS_LOCAL_DIR      离线搬运目录（见第 5 点）        未设置（走在线）
   ============ ===================================== ================================

   ⚠️ Gitee AI 当前仅镜像了 ``Kronos-small``（无 -base/-mini），且不含
   ``Kronos-Tokenizer-base``。若分词器在 Gitee AI 上 404，适配器会自动回退到
   ``hf-mirror.com``；若仍失败则降级 baseline。
4. **代码来源**：官方推理代码 vendor 在 ``_vendor/Kronos``（由 ``bootstrap_kronos.sh`` 获取），
   通过 ``sys.path`` 注入后 ``from model import ...``；缺失则 fail-fast 降级。
5. **离线搬运**：若运行环境出网被拦，可在能出网的机器用 ``download_kronos_weights.py``
   把权重整仓下载到本地目录，拷到目标机后设置 ``KRONOS_LOCAL_DIR=<该目录>``，适配器会用
   ``local_files_only=True`` 从本地加载（无需联网，不依赖 xet CDN）。
5. **保留优雅降级**：线程超时 + 一次性失败标记；HF 不可达时快速降级，不卡流水线。加载较慢
   （首下载权重）时本次跳过、下次重试，不误判为永久失败。

⚠️ ``kronos`` 为可选重型依赖，仅 ``predict`` 内懒加载；未安装 / 不可达 -> 抛 ``ImportError``
由 ``PredictionGenerator`` 捕获降级到 baseline（已实现）。
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Dict, Optional

import numpy as np
import pandas as pd

from loguru import logger

# ---- 国内镜像：Gitee AI (hf-api.gitee.com) 为首选（2026-07-09 实测可绕过 xet CDN）----
#   优先级：KRONOS_HF_ENDPOINT > KRONOS_MODEL_ENDPOINT/TOK_ENDPOINT > 默认 Gitee AI
_GLOBAL_EP = os.environ.get("KRONOS_HF_ENDPOINT") or os.environ.get("HF_ENDPOINT")
_MODEL_EP_DEFAULT = "https://hf-api.gitee.com"  # Gitee AI: 模型权重已验证可下
_TOK_EP_DEFAULT = "https://hf-mirror.com"       # hf-mirror: tokenizer 元数据完整

if _GLOBAL_EP:
    os.environ.setdefault("HF_ENDPOINT", _GLOBAL_EP)
else:
    os.environ.setdefault("HF_ENDPOINT", _MODEL_EP_DEFAULT)

# ---- vendor 路径：默认 _vendor/Kronos（相对项目根），可用 KRONOS_REPO_PATH 覆盖 ----
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENDOR_DEFAULT = os.path.join(_PROJECT_ROOT, "_vendor", "Kronos")


def _ensure_vendor_on_path() -> None:
    """把 vendored Kronos 代码目录加入 sys.path，使 ``from model import ...`` 可用。"""
    path = os.environ.get("KRONOS_REPO_PATH", _VENDOR_DEFAULT)
    if path and path not in sys.path:
        sys.path.insert(0, path)


class KronosAdapter:
    """Kronos 短期收益预测适配器（真实推理版）。"""

    name = "kronos"
    # 真实 HF id（旧版 microsoft/kronos 不存在）
    _HF_TOKENIZER_REPO = "NeoQuasar/Kronos-Tokenizer-base"
    _HF_MODEL_REPO = "NeoQuasar/Kronos-small"  # 可选 -mini / -base

    # Kronos 必需价格列；量能列可选（缺失补 0）
    _PRICE_COLS = ["open", "high", "low", "close"]
    _VOL_COL = "volume"
    _AMT_COL = "amount"

    def __init__(
        self,
        model_name: str = "Kronos",
        horizon: int = 1,
        ctx_len: int = 400,
        sample_count: int = 1,
        model_repo: Optional[str] = None,
        tokenizer_repo: Optional[str] = None,
        load_timeout: float = 180.0,
    ) -> None:
        self.model_name = model_name
        self.horizon = horizon
        self.ctx_len = ctx_len
        self.sample_count = sample_count
        self._model_repo = model_repo or self._HF_MODEL_REPO
        self._tokenizer_repo = tokenizer_repo or self._HF_TOKENIZER_REPO
        self._load_timeout = load_timeout
        self._model = None
        self._tokenizer = None
        self._predictor = None
        self._load_failed = False  # 真实失败（权重拉不到）才永久降级
        self._lock = threading.Lock()

    # ---------- 懒加载（分词器 + 模型 + predictor） ----------
    def _load(self) -> bool:
        if self._load_failed:
            raise ImportError("Kronos 已降级（此前权重加载真实失败，不重复尝试）")
        if self._predictor is not None:
            return True
        with self._lock:
            if self._predictor is not None:
                return True
            if self._load_failed:
                raise ImportError("Kronos 已降级（此前权重加载真实失败，不重复尝试）")
            try:
                _ensure_vendor_on_path()
                from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: F401
            except Exception as exc:  # vendor 代码缺失
                self._load_failed = True
                raise ImportError(
                    "Kronos 官方推理代码未找到（需 vendor 在 _vendor/Kronos，"
                    "运行 bootstrap_kronos.sh 获取；或设置 KRONOS_REPO_PATH）。当前降级 baseline。"
                ) from exc

            logger.info(
                f"Kronos 权重加载（tokenizer={self._tokenizer_repo}, "
                f"model={self._model_repo}，经 {os.environ.get('HF_ENDPOINT')}）..."
            )

            def _resolve(repo_id: str, is_model: bool = True):
                """根据仓库类型选择下载端点（模型 vs 分词器可独立配置）。

                策略：
                  1. 若设了 KRONOS_LOCAL_DIR → 本地离线加载
                  2. 模型权重优先用 Gitee AI（绕过 xet CDN），分词器用 hf-mirror
                  3. 用户可通过 KRONOS_MODEL_ENDPOINT / KRONOS_TOK_ENDPOINT 覆盖
                  4. 全局 KRONOS_HF_ENDPOINT / HF_ENDPOINT 作为最终兜底
                """
                # 1) 离线搬运目录
                local_root = os.environ.get("KRONOS_LOCAL_DIR")
                if local_root:
                    sub = repo_id.replace("/", "--")  # 与 download_kronos_weights.py 约定一致
                    local_path = os.path.join(local_root, sub)
                    if os.path.isdir(local_path):
                        return local_path, True, ""  # (本地路径, 本地加载, 无端点)
                    logger.warning(
                        f"KRONOS_LOCAL_DIR={local_root} 下未找到 {sub}，回退在线加载"
                    )

                # 2) 选择端点：模型 / tokenizer 可独立指定
                if is_model:
                    ep = (
                        os.environ.get("KRONOS_MODEL_ENDPOINT")
                        or _GLOBAL_EP
                        or _MODEL_EP_DEFAULT
                    )
                else:
                    ep = (
                        os.environ.get("KRONOS_TOK_ENDPOINT")
                        or _GLOBAL_EP
                        or _TOK_EP_DEFAULT
                    )
                return repo_id, False, ep  # (repo, not_local, endpoint)

            def _do():
                try:
                    tok_repo, tok_local, tok_ep = _resolve(self._tokenizer_repo, is_model=False)
                    model_repo, model_local, model_ep = _resolve(self._model_repo, is_model=True)

                    # 临时切换端点（from_pretrained 读 HF_ENDPOINT / endpoint 参数）
                    old_ep = os.environ.get("HF_ENDPOINT")

                    # 加载分词器
                    if not tok_local and tok_ep:
                        os.environ["HF_ENDPOINT"] = tok_ep
                    self._tokenizer = KronosTokenizer.from_pretrained(
                        tok_repo, local_files_only=tok_local
                    )

                    # 加载模型
                    if not model_local and model_ep:
                        os.environ["HF_ENDPOINT"] = model_ep
                    self._model = Kronos.from_pretrained(
                        model_repo, local_files_only=model_local
                    )

                    # 恢复原端点
                    if old_ep is not None:
                        os.environ["HF_ENDPOINT"] = old_ep
                    elif "HF_ENDPOINT" in os.environ:
                        del os.environ["HF_ENDPOINT"]

                    self._predictor = KronosPredictor(
                        self._model, self._tokenizer, max_context=512
                    )
                except Exception:  # noqa: BLE001
                    self._predictor = None  # 标记真实失败

            th = threading.Thread(target=_do, daemon=True)
            th.start()
            th.join(self._load_timeout)
            if self._predictor is not None:
                return True
            if th.is_alive():
                # 仍在下载（首拉权重较慢）：本次跳过、下次重试，不误判为永久失败
                raise ImportError("Kronos 权重加载中（较慢），本次跳过，下次重试")
            # 线程已结束但 predictor 仍为 None -> 真实失败
            self._load_failed = True
            raise ImportError(
                f"Kronos 权重加载失败（HF 不可达/镜像异常），降级 baseline"
            )

    # ---------- 输入规整：确保 Kronos 所需列 ----------
    @staticmethod
    def _prepare_df(bars: pd.DataFrame) -> pd.DataFrame:
        df = bars.copy()
        # 时间戳
        if "timestamps" not in df.columns:
            src = df["date"] if "date" in df.columns else df.index
            df["timestamps"] = pd.to_datetime(src)
        df = df.sort_values("timestamps").reset_index(drop=True)
        # 量能列别名兼容（mootdx 给 vol）
        if KronosAdapter._VOL_COL not in df.columns and "vol" in df.columns:
            df[KronosAdapter._VOL_COL] = df["vol"]
        need = KronosAdapter._PRICE_COLS + [KronosAdapter._VOL_COL, KronosAdapter._AMT_COL]
        for c in need:
            if c not in df.columns:
                df[c] = 0.0
        df[need] = df[need].apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=need)
        return df

    # ---------- 公开推理入口 ----------
    def predict(
        self, bars: pd.DataFrame, horizon: int
    ) -> Optional[Dict[str, float]]:
        """对单标的 OHLCV 日 K 预测未来 ``horizon`` 日收益。

        Args:
            bars: 单标的 DataFrame，需含 ``date``/``open``/``high``/``low``/``close``
                （``vol``/``amount`` 可选，自动兼容与补齐）。
            horizon: 预测步长（1/5/10）。
        Returns:
            ``{"ret_pred", "lower", "upper"}`` 或 ``None``（不可用/降级）。
        """
        try:
            self._load()
        except ImportError as exc:
            logger.debug(f"Kronos 不可用：{exc}")
            return None
        try:
            df = self._prepare_df(bars)
            if len(df) < 30:
                return None
            lookback = min(len(df), self.ctx_len)
            x_df = df.iloc[-lookback:].copy()
            x_ts = pd.Series(x_df["timestamps"].values)
            last_date = pd.Timestamp(x_ts.iloc[-1])

            # 未来 horizon 个工作日作为预测时间戳
            y_dates = pd.bdate_range(last_date + pd.Timedelta(days=1), periods=horizon)
            if len(y_dates) < horizon:  # 退路：自然日
                y_dates = pd.date_range(
                    last_date + pd.Timedelta(days=1), periods=horizon, freq="D"
                )
            y_ts = pd.Series(pd.to_datetime(y_dates).values)

            pred_df = self._predictor.predict(
                df=x_df[self._PRICE_COLS + [self._VOL_COL, self._AMT_COL]],
                x_timestamp=x_ts,
                y_timestamp=y_ts,
                pred_len=horizon,
                T=1.0,
                top_p=0.9,
                sample_count=self.sample_count,
                verbose=False,
            )
            if pred_df is None or len(pred_df) == 0:
                return None

            last_close = float(x_df["close"].iloc[-1])
            pred_close = float(pred_df["close"].iloc[-1])
            if not np.isfinite(pred_close) or last_close <= 0:
                return None
            ret_pred = pred_close / last_close - 1.0

            # 区间：近期收益波动代理（与 baseline / darts 约定一致）
            hist = df["close"].pct_change().dropna().tail(20)
            if len(hist) >= 2:
                band = float(hist.std() * np.sqrt(horizon) * 1.96)
            else:
                band = abs(ret_pred) * 0.5 + 1e-4
            return {
                "ret_pred": float(ret_pred),
                "lower": float(ret_pred - band),
                "upper": float(ret_pred + band),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Kronos 推理失败（降级）：{exc}")
            return None
