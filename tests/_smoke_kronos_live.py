"""Kronos 适配器真实推理冒烟测试：合成 OHLCV -> 从 hf-mirror 拉权重 -> 真推理。

运行： python3.11 tests/_smoke_kronos_live.py
（需联网/镜像可达；首跑会下载 Kronos-small + Tokenizer 权重）
"""
import os
import sys
import time
import datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd

from sources.adjust import make_sample_bars
from factors.kronos_adapter import KronosAdapter


def main():
    rows = make_sample_bars(
        "600977", start=dt.date(2025, 1, 1), n_days=250, seed=7, drift=0.0003, vol=0.018
    )
    df = pd.DataFrame(rows)
    print("[smoke] cols:", list(df.columns), "rows:", len(df))

    ad = KronosAdapter(sample_count=1, load_timeout=300.0)

    t0 = time.time()
    out5 = ad.predict(df, 5)
    print(f"[smoke] h=5  predict 耗时 {time.time() - t0:.1f}s -> {out5}")

    for h in (1, 10):
        o = ad.predict(df, h)
        print(f"[smoke] h={h} -> {o}")

    # 再次调用应命中已加载的模型（不应重新下载）
    t1 = time.time()
    o1 = ad.predict(df, 1)
    print(f"[smoke] 复用模型 h=1 耗时 {time.time() - t1:.2f}s -> {o1}")


if __name__ == "__main__":
    main()
