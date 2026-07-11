# 可复现验证沙箱 · 运行手册（Plan A）

> 目标：**沙箱测试 OK → 本地无缝切换**。验证用「同源输入 + 同管道 + 可控随机」，
> 使沙箱与本地在固定快照上得到**相同的验证裁决（PASS/FAIL）**，而非追求逐位浮点相等。

---

## 1. 三段式保证

| 维度 | 做法 | 作用 |
|------|------|------|
| 同源输入 | 固定快照 `data/verify_snapshot.duckdb`（market.duckdb 冻结于 2026-07-08，58653 行 / 300 只） | 沙箱与本地吃同一份行情，标签横截面基准一致 |
| 同管道 | 直接驱动 `PredictionGenerator._eval_heavy`（即 `Orchestrator.step_predict` 内部调用的同一方法），标签用真实 `_build_labels` | 验证逻辑与生产完全一致，废止 ad-hoc 脚本 |
| 可控随机 | 每次 `KronosAdapter.predict` 前 `torch.manual_seed(SEED)` 复位 + `sample_count` 多样本平均 | 同种子+同输入 → 同预测；跨机浮点差异由容差门吸收 |

**确定性依据**：vendored Kronos 在 `eval` 模式 dropout 关闭（`module.py:348/392`），
推理路径仅两处 `torch.multinomial`（全局 RNG，`module.py:271` / `kronos.py:384`），
前向无量消耗 RNG。故每次预测前复位种子即可完全复现。

---

## 2. 文件清单

| 文件 | 角色 |
|------|------|
| `data/verify_snapshot.duckdb` | **固定验证输入**（只读快照，请勿手改） |
| `_verify_repro.py` | 验证 harness（并行分片 + 合并 + 容差门 + 裁决） |
| `_local_kronos_weights/` | Kronos 离线权重（small 98MB + tokenizer 15MB） |
| `_vendor/Kronos/` | Kronos 官方推理代码（vendor，非 pip） |
| `verify_verdict.json` | 机器可读裁决（含数据/环境指纹 + 指标 + 容差门） |
| `verify_report.md` | 人类可读裁决报告 |
| `_verify_eval_ckpt_s{0..7}.json` | 各分片 checkpoint（运行产物，可删） |

---

## 3. 环境钉死（本地必须一致）

验证对以下环境敏感，本地部署需对齐：

- **Python / torch / transformers / numpy / duckdb** 版本须与 `verify_verdict.json` 的
  `environment_fingerprint` 一致（尤其 torch —— 决定 `multinomial` RNG 实现）。
- **Kronos 权重 SHA256**：`NeoQuasar--Kronos-small/model.safetensors` 与
  `NeoQuasar--Kronos-Tokenizer-base/model.safetensors`。权重不同 → 预测不同。
- 离线环境变量：`KRONOS_LOCAL_DIR`（权重目录）、`KRONOS_REPO_PATH`（vendor 代码目录）。
- 固定参数：`--seed 20260708`、`--sample-count 1`、`--n-eval-dates 5`（默认内置；
  `sample_count=1` 经 4500 样本聚合后 SE≈0.007，已足够稳定，且比 8 快 8 倍）。

> 若本地 torch 版本与沙箱不同，逐位浮点可能略有差异，但 `dir_acc` 应落在同一容差带内 →
> 同裁决。这是设计内的「同裁决而非同浮点」容差。

---

## 4. 运行

```bash
# 沙箱/本地均可（离线，无需联网）
python3 _verify_repro.py                  # 8 片并行，跑完整 300 只
python3 _verify_repro.py --n-shards 16    # 多核机器可加到 16
python3 _verify_repro.py --no-parallel    # 单进程调试（慢，约 8×）
python3 _verify_repro.py --seed 20260708 --sample-count 8
```

退出码：`0` = PASS（可放心切本地）；`1` = FAIL（需排查）；`2` = 环境未就绪。

---

## 5. 容差门（判定 PASS 的硬条件）

参考 300×5 非种子评估（total=0.5744 / H1=0.5567 / H5=0.6407 / H10=0.5260），
按各周期样本标准误（SE≈0.013）留约 2σ 余量，下限取生产阈值 0.52：

| 周期 | 容差带 | 参考值 |
|------|--------|--------|
| total | [0.53, 0.62] | 0.5744 |
| H1 | [0.52, 0.64] | 0.5567 |
| H5 | [0.54, 0.70] | 0.6407 |
| H10 | [0.50, 0.62] | 0.5260 |

**PASS = 四个周期全部落入各自容差带 且 融合权重 > 0。**

> 容差带是「模型确实有效」的 sanity gate，也是跨机浮点噪声的吸收器；
> 不要求精确等于参考值（参考为非种子单次采样，本验证用固定种子，数值会有合理偏移）。

---

## 6. 沙箱 → 本地无缝切换流程

1. 沙箱跑 `python3 _verify_repro.py` 得 **PASS**，记录 `verify_verdict.json` 的
   数据指纹（`content_sha256`）+ 环境指纹 + `dir_acc`。
2. 将 `data/verify_snapshot.duckdb` 与 `_local_kronos_weights/` 拷到本地同路径。
3. 本地设 `KRONOS_LOCAL_DIR` / `KRONOS_REPO_PATH`，对齐 torch 等版本。
4. 本地跑同一命令：`python3 _verify_repro.py --seed 20260708 --sample-count 1`
   （`sample_count` 是契约参数，必须与沙箱裁决文件中的 `sample_count` 一致）。
5. 比对本地 `verify_verdict.json`：数据/环境指纹一致 + `dir_acc` 同处容差带 →
   **同裁决即无缝切换**。随后本地可接入实时数据源（见 §7）跑真实盘后流水线。

---

## 7. 网络边界（重要）

- **验证（本 harness）全程离线**：吃冻结快照，不触发任何行情 API。沙箱/本地均可直接跑。
- **实时盘后流水线（`Orchestrator.run_daily`）需联网取数**：按架构 §8，主源 mootdx（通达信 TCP 7709）
  / Tencent（qt.gtimg.cn），冗余 akshare / baostock。
  **受限海外网络下这些源超时**（mootdx TCP 7709 海外不通、akshare/baostock 被墙），
  属架构预期边界，非代码 bug。
- 因此：**验证在沙箱用快照完成；切本地后在能出网的机器接实时源**。`verify_snapshot.duckdb`
  仅用于「可复现验证」，不参与生产取数。

---

## 8. 已知局限（继承自 300×5 评估）

- 样本非独立（同标的多时点强相关），严格应聚标准误；当前 dir_acc 约 +9.9σ 高于随机，
  但为点估计，未做聚类校正。
- 快照止于 2026-07-08（沙箱无法取到更新数据）；本地接入实时源后可重切更近基准日重跑。
- Kronos 为冻结基础模型，无法用更多历史重新训练；「数据越多越准」仅体现在评估样本量增大
  （置信度提升），不改变单点预测能力。
