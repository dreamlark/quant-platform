"""Kronos model 包的离线桩（仅用于测试 KronosAdapter 的接线逻辑，非真实推理）。

它忠实模仿官方 ``model`` 包的接口：
  - ``KronosTokenizer.from_pretrained`` / ``Kronos.from_pretrained``
  - ``KronosPredictor(model, tokenizer, max_context=512)``
  - ``predict(df, x_timestamp, y_timestamp, pred_len, ...)`` ->
    DataFrame[open,high,low,close,volume,amount] indexed by y_timestamp，
    且 close 逐日 +1% 递增，便于断言 ret_pred>0。
真实权重因沙箱无法访问 HF xet CDN（cas-bridge.xethub.hf.co）而无法下载，
故用桩验证适配器接线；真实推理在用户联网环境由 from_pretrained 完成。
"""
import numpy as np  # noqa: F401
import pandas as pd


class KronosTokenizer:
    @classmethod
    def from_pretrained(cls, pretrained_model_name_or_path, **kwargs):
        return cls()


class Kronos:
    @classmethod
    def from_pretrained(cls, pretrained_model_name_or_path, **kwargs):
        return cls()


class KronosPredictor:
    def __init__(self, model, tokenizer, device=None, max_context=512, clip=5):
        self.tokenizer = tokenizer
        self.model = model
        self.max_context = max_context
        self.clip = clip
        self.price_cols = ["open", "high", "low", "close"]
        self.vol_col = "volume"
        self.amt_vol = "amount"

    def predict(
        self, df, x_timestamp, y_timestamp, pred_len,
        T=1.0, top_k=0, top_p=0.9, sample_count=1, verbose=True,
    ):
        last_close = float(df["close"].iloc[-1])
        closes = [last_close * (1.0 + 0.01 * (i + 1)) for i in range(pred_len)]
        idx = pd.to_datetime(list(y_timestamp))
        out = pd.DataFrame(
            {
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
                "volume": [1e6] * pred_len,
                "amount": [1e8] * pred_len,
            },
            index=idx,
        )
        return out
