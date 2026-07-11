# 可复现验证裁决报告（Plan A）

- **裁决**：✅ PASS
- **生成时间**：2026-07-10T15:32:34
- **契约**：沙箱验证 PASS 即代表本地用相同快照/种子/采样数可得相同裁决

## 指标 vs 容差门

| 周期 | dir_acc | 容差带 | 判定 |
|------|---------|--------|------|
| total | 0.5711 | (0.53, 0.62) | ✓ |
| H1 | 0.5327 | (0.52, 0.64) | ✓ |
| H5 | 0.6473 | (0.54, 0.7) | ✓ |
| H10 | 0.5333 | (0.5, 0.62) | ✓ |
| 融合权重 | 0.0356 | >0 | ✓ |

样本对：4500（有效 4500），完成标的：300 只

## 数据指纹（同源输入）

- 快照：data/verify_snapshot.duckdb
- 截止日：2026-07-08
- 行数 / 标的数：58653 / 300
- 内容 SHA256：edcd3a5afc64b875ac7864e6075c31d8a2e001bd7e8320b455e2c22f81c478ff

## 环境指纹（同管道 + 可控随机）

- python=3.11.1 torch=2.10.0+cu128 transformers=5.1.0 numpy=2.3.5 duckdb=1.5.4
- 种子 seed=20260708 sample_count=1 n_eval_dates=5
- Kronos 模型权重 SHA256：b082dfcbd8e8c142a725c8bbb99781802f38fec81210e13479effb32b3c3e020
- Kronos 分词器权重 SHA256：59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee
- vendor 路径：/workspace/quant-platform/_vendor/Kronos

## 参考（非种子 300×5 评估，仅对照）

- total=0.5744 H1=0.5567 H5=0.6407 H10=0.526

## 失败原因

- 无

## 本地复现步骤（沙箱 OK 后无缝切换）

1. 拷贝 `data/verify_snapshot.duckdb` 与 `_local_kronos_weights/` 到本地同路径
2. 设置 `KRONOS_LOCAL_DIR` / `KRONOS_REPO_PATH` 指向本地权重与 vendor
3. `python3 _verify_repro.py --seed 20260708 --sample-count 1`
4. 比对本地 `verify_verdict.json` 的 data/环境指纹与 dir_acc 是否与沙箱一致 -> 同裁决即无缝切换
