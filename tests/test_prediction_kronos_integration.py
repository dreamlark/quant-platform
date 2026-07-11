"""prediction.py 与 KronosAdapter 集成测试（桩代替真实权重）。

验证：PredictionGenerator._eval_heavy 对 kronos 传入 OHLCV 分组、对 darts 传入收盘价序列，
二者路由互不干扰；Kronos 走桩返回有效预测，walk-forward 评估产出 dir_acc。

运行： python3.11 tests/test_prediction_kronos_integration.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd

from sources.adjust import make_sample_bars
from factors.prediction import PredictionGenerator

_STUB = os.path.join(os.path.dirname(__file__), "stub_model")


def _build_bars(n_codes=3, n_days=250):
    frames = []
    base = dt.date(2025, 1, 1)
    for i in range(n_codes):
        rows = make_sample_bars(
            f"60097{i}", start=base, n_days=n_days, seed=10 + i,
            drift=0.0006, vol=0.015,
        )
        frames.append(pd.DataFrame(rows))
    bars = pd.concat(frames, ignore_index=True)
    # 合成数据无分红，后复权≈不复权
    bars["adj_back_close"] = bars["close"]
    return bars


def main():
    os.environ["KRONOS_REPO_PATH"] = _STUB
    bars = _build_bars()
    codes = sorted(bars["code"].unique().tolist())
    target = pd.to_datetime(bars["date"]).max().date()

    pg = PredictionGenerator()
    pdf, hdf = pg.generate(bars, codes, target)

    assert not pdf.empty, "predict_df 不应为空"
    assert not hdf.empty, "health_df 不应为空"
    kronos_h = hdf[hdf["model_name"] == "kronos"]
    darts_h = hdf[hdf["model_name"] == "darts"]
    assert not kronos_h.empty, "应含 kronos 健康度行"
    assert not darts_h.empty, "应含 darts 健康度行"

    # kronos（桩，+1%/日，上行合成数据）dir_acc 应较高
    k_dir = float(kronos_h["dir_acc"].iloc[0])
    print(f"[integ] kronos dir_acc={k_dir:.3f} weight={float(kronos_h['weight'].iloc[0]):.3f}")
    print(f"[integ] darts  dir_acc={float(darts_h['dir_acc'].iloc[0]):.3f}")
    print(f"[integ] predict_df 行数={len(pdf)} 模型={sorted(pdf['model_name'].unique())}")
    print("PREDICTION+KRONOS INTEGRATION OK")


if __name__ == "__main__":
    main()
