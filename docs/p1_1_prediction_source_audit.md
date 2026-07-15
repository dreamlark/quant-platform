# P1-1 预测源过弱 —— 诊断与方向建议

> 状态：诊断完成（2026-07-15）；**方向已定：先修两个弱源 + 动态 IC 加权 + 3 窗口闸门，仍近随机再剔除**（用户评审决定，非单纯砍）。
> 依赖：P0-1 前视审计已通过（特征工程 point-in-time 正确性已确认），可安全评估预测源。

## 1. 现状

融合第 4 源 `predict` 由三个适配器组成，权重由 `predict_health.dir_acc`（walk-forward
方向准确率）自动决定；`dir_acc ≤ 0.52` 权重降为 0（实验性，不进核心权重）：

| 适配器 | 实测 dir_acc | 是否进核心权重 | 结论 |
|--------|-------------|---------------|------|
| Kronos | ≈0.632 | ✅ 是 | 唯一有真实预测力的源 |
| qlib（xgboost 回退） | ≈0.5（近随机） | ❌ 降权 0 | 真近似随机 |
| darts（NBEATS 池化） | ≈0.5（近随机） | ❌ 降权 0 | 真近似随机 + 训练泄漏 |

**结果**：`predict` 实际只有 Kronos 在撑，"四源融合"中预测第 4 源名存实亡。

## 2. 特征工程 point-in-time 审计

### 2.1 QlibAdapter —— 正确，无需修
- 标签 `c.shift(-h)/c - 1`（未来 h 日收益），合法前视（目标本就该用未来）。
- 特征全部因果：`ROC/MA/STD/RSI/HLpos/Vrat/Arat/P2H/AMP/TurnTrend/CorrRV20`，
  均为历史滚动窗口，无当日未来信息。
- 训练 `exclude_tail`（默认 20 日）剔除末尾保留带，walk-forward 评估落在未见样本；
  `_cv_dir_acc` 用 expanding-window CV 选优。
- **近随机是 A 股日频有效市场的真实难度，非实现缺陷。**

### 2.2 DartsAdapter —— 有训练泄漏，且设计上弱
- `fit(panel)` 中 `panel = work.pivot(index=date, columns=code, values=adj_back_close)`，
  而 `work` 是**截至 target_date 的全量历史**（`prediction.py:60-77`）。
  → 模型在**训练期就看到了每个评估点 t 之后的未来收益**，walk-forward 评估被污染。
- 即使剔除泄漏，Darts 是把**所有标的收益率池化成一个序列**做单变量 NBEATS 预测，
  预测的是"市场平均收益方向"，再套用到个股 → 对个股方向近随机。
- 当前 dir_acc≈0.5 在泄漏下仍近随机，说明即使含未来信息也学不到个股方向。

### 2.3 Kronos —— 正常
- 零样本跨域大模型，dir_acc≈0.632 为真实信号；无前视问题（P0-1 已审计）。

## 3. 当前缓解（已生效）
`predict_health` 自动降权：`qlib`/`darts` 的 dir_acc ≤ 0.52 → 权重 0。
故**线上 `predict` ≈ Kronos**，功能不受影响，但代码仍维护两个近随机适配器，且
Darts 存在训练泄漏（虽结果近随机，但属脏代码，审计上不干净）。

## 4. 方向选项（三选一，待评审定）

- **方案 A（修 darts/qlib）**：修正 darts 训练泄漏 → 改 per-stock / walk-forward 训练，
  但本质仍是池化预测器，预期 dir_acc 仍难破 0.55；qlib 已正确，无需改。
  投入中等，**预期收益低**（A 股日频方向预测本质近随机）。
- **方案 B（砍，推荐）**：移除 darts/qlib 适配器，`predict` = Kronos；更新
  `fusion.base_weights.predict` 说明与文档（§4.5/README）诚实标注
  "预测源 = Kronos（dir_acc≈0.63）"。代码最简、最诚实、消除 darts 泄漏脏代码。
- **方案 C（换）**：以滞后因子矩阵训练 XGBoost/LGBM 作新 ML 预测源 —— **但 QlibAdapter
  本质已是"Alpha158 特征 + XGBoost 委员会"**，即方案 C 已落地；其 dir_acc 仍近随机，
  故 C 并不比现状更好，除非换特征/标签工程（投入大、前景不确定）。

## 5. 建议
> **推荐方案 B**：A 股日频方向预测近随机是公认事实，继续维护两个近随机适配器
> （其中一个还带训练泄漏）性价比极低。砍掉后 `predict` 退化为单模型 Kronos，
> 反而更诚实、更可维护、更可解释。若日后确需增强预测，再单独评估新特征/新标签
> （真正的 C），而非保留现状。
>
> 注：砍掉后 `predict_health` 质量门仍可保留（仅监控 Kronos），不丢失护栏能力。

## 6. 落地下一步（视决策）
- B：删除 `factors/darts_adapter.py` + `qlib_predict_adapter.py` 及 `prediction.py`
  中对应装配；`predict` 仅走 Kronos；更新文档；补"predict=Kronos only"单测。
- A：修 darts `fit` 为 walk-forward（per-stock 或时间窗切分），保留委员会。
- C：在 qlib 基础上换特征/标签重训，重测 dir_acc > 0.55 方采纳。

## 7. 落地实现（2026-07-15，采纳「先修 + 动态 IC + 闸门」）

用户决策：**不急于只留 Kronos**；先修正两个弱源让其有公平贡献机会，再用动态 IC
加权取代静态 dir_acc 门，并以"连续 3 个滚动窗口 IC≈0 才剔除"为硬闸门。

### 7.1 Darts 训练泄漏修复（P1-1a，已完成）
- 根因：`generate()` 中 `darts.fit(panel)` 用截至 target_date 的全量 `work`（含未来）训练，
  而 `_eval_heavy` 在每个评估点 t 用 `prices_full.loc[:t]` 推理 → 模型见过 t 之后数据。
- 修复：`prediction.py` 在 `darts.fit` 前将 panel 截断到 `_darts_train_cutoff(max_date, n_eval, max_horizon)`
  （早于最早评估日约 `n_eval + max_horizon + 10` 个业务日），且仅用该 trailing window 训练，
  z-score 统计量仅来自该段（训练集内）。评估点 t 均晚于 cutoff → 无前视。
- 说明：Darts 本质仍是"池化均值收益"预测器，对个股近随机；修复使其评估诚实，
  是否真有信号交由下方 IC 闸门判定（而非靠泄漏虚高）。

### 7.2 动态 IC 加权 + 3 窗口闸门（P1-1b，已完成）
- `predict_health` 表新增 `ic` / `rolling_ic` / `dropped` 列（DDL + `init_schema` 幂等迁移）。
- `_eval_heavy` 收集每评估点 `(date, code, ret_pred, actual_fwd_ret)`，计算横截面 per-date
  Spearman IC（≥3 标的/日），按 `rolling_window`（默认 3 日）滚动求窗口 IC。
- `_compute_ic_and_gate`：返回（均值 IC, 最近窗口 IC, 是否剔除）；剔除条件 =
  最近 `gate_windows`（默认 3）个滚动窗口全部 `|IC| < eps`（默认 0.02）。
- `_dynamic_weight`：权重 = `base_predict_weight × (ic - eps)/(ref - eps)`（ref 默认 0.05，
  归一化），剔除时 0；IC 不可得（样本/标的不足）回退 dir_acc 软加权。
- `config/settings.yaml` 暴露 `fusion.predict_ic: {rolling_window, eps, ref, gate_windows}`。
- `tests/test_prediction_ic.py`：截断 cutoff / IC 计算 / 闸门 / 动态权重（含回退）全覆盖。

### 7.3 QLib（已 point-in-time 正确，无需改）
- `exclude_tail` + 全因果特征，walk-forward 诚实；近随机是 A 股日频固有难度，非实现缺陷。
  纳入同一 IC 通道后，若其 IC 持续 ≈0 也会被闸门剔除；若有信号则公平贡献。

### 7.4 效果预期与后续
- Kronos（dir_acc≈0.63）应给出正 IC → 保留并加权；darts/qlib 经诚实评估后，IC 近随机
  → 闸门自动剔除（dropped），与"直接砍"等效但不浪费既有特征逻辑，且避免单预测员失效风险。
- 真机长周期运行后观察 `predict_health.dropped`：若 darts/qlib 连续 3 窗口 IC≈0 被剔除，
  可再评估是否彻底移除适配器（方案 B 收口）。
