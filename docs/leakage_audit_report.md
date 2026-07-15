# P0-1 前视偏差审计 · 执行报告（Leakage Audit Report）

> **关联 PRD**：`docs/system_optimization_v1.md` → P0-1 前视偏差审计
> **审计日期**：2026-07-15
> **审计范围**：因子计算 / 四源融合 / 三类回测 / walk-forward 评估 / 情绪温度计 / 编排时序
> **审计性质**：**仅审计 + 报告，不做修复**（修复单列 PRD，避免 scope creep）
> **总体结论**：**PASS（无实质性前视偏差）**，发现 2 项 LOW 级条件性问题（已附处置建议）

---

## 0. 结论速览

| 模块 | 时间点隔离机制 | 结论 | 关键证据 |
|------|----------------|------|----------|
| `factors/qlib_factors.py` | 12 个因子均为 `shift(正)/rolling/diff`，仅读 `adj_back_close` | ✅ PASS | 全局 `grep` 无 `shift(-`；详见 §1.1 |
| `factors/czsc_signals.py` | 缠论笔段为因果计算（仅用历史 K） | ✅ PASS | 输入为 `adj_back_close`；隔离测试实证（§4） |
| `factors/factor_calc.py` | 按 code 委托计算，无全局归一化 | ✅ PASS | 隔离测试实证（§4.1） |
| `factors/prediction.py` | 标签用 `shift(-h)`（**合法的标签**）；评估输入 `≤ t` | ✅ PASS | `_eval_heavy` 用 `prices_full.loc[:t]`（§1.3） |
| `factors/qlib_predict_adapter.py` | 特征 `shift/rolling/diff`；训练剔除末尾 `exclude_tail`；`predict` 取末行 | ✅ PASS | §1.4 |
| `factors/kronos_adapter.py` | 推理取 `df.iloc[-lookback:]`（`≤ t` 窗口） | ✅ PASS | §1.4 |
| `fusion/signal_pool.py` | 按 `date` 切片 + 截面 z（t 日）；regime 为 T-1 | ✅ PASS | §2 |
| `backtest/walk_forward.py` | `fwd = shift(-1)`；train/test 严格 point-in-time | ✅ PASS | §3.1 |
| `backtest/signal_backtest.py` | `fwd = shift(-1)`；`_shift_regime` 做 T-1 偏移 | ✅ PASS | §3.2 |
| `backtest/sentiment_timing.py` | `fwd = shift(-1)`；测试日 `t` 取 `fwd.loc[t]` | ✅ PASS | §3.3 |
| `factors/market_sentiment.py` | `_rolling_pct` 用 `series.loc[:target]`；`bars ≤ date` | ✅ PASS | §1.5 |
| `scheduler/orchestrator.py` | `run_daily` 顺序：fusion(步8) 在 market_sentiment(步10) 之前；融合读 **前一日** regime | ✅ PASS | §2.2 / §4.4 |

**核心不变量（已用合成探针测试固化，见 `tests/test_leakage_invariant.py`）**：

> 在任意时刻 `t`，信号/因子/预测的生成只能读到 `date ≤ t` 的数据；回测在 `t` 的持仓只赚取 `t → t+1` 的收益（次日收益），绝不使用 `t` 当日收益或 `t+1 → t+2` 收益。

---

## 1. 数据源与价格口径（前复权是经典前视源）

**架构红线**：`adj_front_close`（前复权）仅用于前端 K 线展示，**严禁入任何计算**；计算/回测唯一使用 `adj_back_close`（后复权，锚定最早时点）。

- `sources/adjust.py:4-5` 明确："后复权（计算/回测唯一可用）" / "前复权（仅前端展示，严禁用于任何计算）"。
- `storage/schema.py:30-31`：DuckDB 列注释强制此约束。
- `factors/qlib_factors.py:7`：**绝不**使用 `adj_front_close`。
- 全局 `grep "adj_front_close"` 命中均为 API 展示（`api/routers/stocks.py` 仅返回前复权用于画 K 线）与测试（`test_fe_constraints.py` 断言因子不读它）。
- `factors/` 下所有 `shift` 调用均为**正向**（后视）：`shift(1)/shift(5)/shift(20)/shift(60)`；仅**标签**构造使用 `shift(-h)`（合法）。

✅ **结论**：价格口径无前视泄漏，且已有 `test_fe_constraints.py` 守护。

### 1.1 `factors/qlib_factors.py`（12 个 Alpha 因子）
`_FACTOR_REGISTRY` 每个 lambda 接收单标的序列 `g`，全部基于 `g["adj_back_close"]`：
- `f_momentum_5/20` = `close/close.shift(5|20)-1`（后视动量）
- `f_reversal_5` = `close.shift(5)/close-1`（后视反转）
- `f_volatility_20` = `log(close/close.shift(1)).rolling(20).std()`
- `f_rsi_14` / `f_amt_ratio` / `f_turn` / `f_high_low` 等：均 `rolling/diff/shift(正)`

无任何 `shift(-n)` 特征。✅ PASS。

### 1.2 `factors/czsc_signals.py`（缠论技术信号）
以 `adj_back_close/close` 为复权比转换 OHLC（§10 注释 "以 adj_back_close/close 为复权比"），缠论笔段本身为因果算法（按时间顺序处理历史 K 线）。隔离测试（§4.1）实证：篡改未来日价格不改变历史日技术分。

### 1.3 `factors/prediction.py`（预测第 4 源）
- **标签**（合法用未来）：`_build_labels` 用 `pr.shift(-h)/pr-1` 构造 `label_dir_h`（超额收益方向）。标签本就该用未来收益作真值，不回灌信号。
- **评估**（point-in-time）：`_eval_heavy` 在评估时点 `t`：
  ```python
  p_t = prices_full.loc[:t]                 # 仅 ≤ t 的价格
  g_t = g[g["date"] <= t]                    # 仅 ≤ t 的 OHLCV
  out = adapter.predict(kronos_inp, h)       # 在 ≤ t 数据上预测
  dp = sign(out.ret_pred); a = ld.loc[t]     # 与 t 日真实 label 比对
  ```
  预测输入严格 `≤ t`，标签为 `t` 日真实未来方向 → 诚实样本外。
- **目标日预测**：`kronos_inp = g`（全量 `≤ target_date`）→ 用截至目标日的数据预测，正确。
- **baseline**：`pred = pr/pr.shift(5)-1`（5 日动量，纯后视），`dir_acc` 为固定规则在全部历史上的方向准确率（固定规则无过拟合，样本外=样本内）。

✅ PASS。

### 1.4 预测适配器（Kronos / Qlib）
- `kronos_adapter.predict`：`x_df = df.iloc[-lookback:]`，取 `≤ t` 末 `lookback` 行自回归解码未来 K 线 → 仅用历史。
- `qlib_predict_adapter`：
  - `_build_features`：全部 `shift(n)/rolling(n)/diff()`（后视）。
  - `fit`：`labels[h] = c.shift(-h)/c-1`（标签）；`cut = len(g)-exclude_tail` 剔除末尾保留带给评估/目标预测，确保评估落在**训练未见**样本。
  - `predict`：`feats.iloc[[-1]]` 取输入窗**末行**（即 `t` 日特征），不触未来。

✅ PASS。

### 1.5 `factors/market_sentiment.py`（T1/T2 温度计 —— sentiment_timing 的上游）
- `_rolling_pct(series, target, window)`：`s = series.loc[:target]` → 仅 `≤ target`；百分位基于 `recent = s.tail(window)`，point-in-time。
- `compute`：`if "date" in bars: bars = bars[bars["date"] <= date]`（§180）→ GSISI/量价维全部 `≤ date`。
- 外部数据（融资/北向/ETF/估值/利率）在 `_dim_*` 内均 `.sort_index()` 后由 `_rolling_pct` 的 `loc[:target]` 截断，即便外部序列含未来日期也不泄漏。

✅ PASS。

---

## 2. 融合层（`fusion/signal_pool.py`）

- `fuse(...)` 对四源均先做 `df[df["date"] == date]` 精确切片（见 `_pivot`/`_slice`/`_predict_score`），不使用任何 `> date` 数据。
- 各源贡献先做**截面 z**（`(col-col.mean())/col.std()`，同一 `date` 内），无跨期归一化。
- **regime 调节**：`fuse` 接收 `regime`（T-1），仅缩放置信度、不动方向。

### 2.1 regime 的时间点正确性（关键）
`orchestrator.step_fusion`（步 8）通过 `_latest_regime()` 读取 `repo.load_sentiment_index(latest=True)`：
- **当日** `step_market_sentiment`（步 10）在 fusion **之后**才落库，故 fusion 读到的 `latest` 实为**前一日**已落库的 `sentiment_index` → 严格的 T-1 regime。
- 首跑无历史时返回 `None` → 不调节（与默认 `regime_adjust.enabled=False` 一致）。
- 代码注释 §196-197 已明确此设计意图。

✅ PASS（时序正确性由 §4.4 顺序断言守护）。

---

## 3. 回测层（三类回测 + walk-forward）

### 3.1 `backtest/walk_forward.py`（主口径：因子 walk-forward IC 加权）
```python
fwd = price.shift(-1) / price - 1.0          # 次日收益（point-in-time）
...
weights = self._train_weights(fwide, fwd, train_dates)   # IC 用 factor@d vs fwd@d
for t in test_dates:
    alpha = self._alpha(fwide, weights, t)   # factor@t（≤ t）→ 选 top20% 等权
    r = fwd.loc[t]                            # 赚 t→t+1 收益
    pret = (w * r).sum() - cost
```
- 训练 IC：`factor[d]`（≤ d） vs `fwd[d]`（d→d+1），诚实。
- 测试：`alpha` 用 `factor[t]`（≤ t），`r = fwd.loc[t]` 即 `t→t+1`。**正确**。
- `_train_weights`：`spearmanr(fv.loc[idx], rv.loc[idx])` 同一 `d`，无跨期。
- `_alpha`：`z = (col-col.mean())/col.std()` 为 `date` 日截面，无未来。

✅ PASS（point-in-time 由 §4.2 结构断言守护）。

### 3.2 `backtest/signal_backtest.py`（regime 调节验证 ON/OFF）
- `fwd = price.shift(-1)/price-1.0`；测试日 `t` 用 `fwd.loc[t]`。
- `_shift_regime`：对每个目标日 `t` 取 `< t` 的最近 regime（**T-1 偏移**，首日止于 `None` 不缩放）。
- 两口径差异**仅**来自 regime 缩放，干净隔离。

✅ PASS。

### 3.3 `backtest/sentiment_timing.py`（T2 温度计择时）
```python
fwd = price.shift(-1) / price - 1.0
...
for t in test_dates:
    alpha = self.wf._alpha(fwide, weights, t)   # factor@t
    r = fwd.loc[t]                               # t→t+1
    expo = exposure.get(t, default)              # 当日温度计信号（来自 ≤ t 数据）
    timing_ret = expo * base_ret
```
- 择时暴露 `exposure[t]` 由 `sentiment_df` 在 `t` 的信号决定（温度计本身 point-in-time，见 §1.5）。
- 测试日 `t` 用 `fwd.loc[t]`（t→t+1），与因子回测口径一致。

✅ PASS。

---

## 4. 合成前视探针测试（`tests/test_leakage_invariant.py`）

为把"时间点隔离"固化为 CI 门禁，新增 5 个不变量测试（均合成数据、零外部依赖、快速）：

### 4.1 `test_factor_no_lookahead_isolation`（黄金标准）
构造 2 标的 × 150 交易日的合成行情 → 计算因子；将**最后若干日**价格恶意篡改（×100）→ 重新计算。断言除最后一日外，所有 `(code, date)` 的因子值**逐位不变**。直接证明：历史日因子不读取未来日数据。覆盖 `QlibFactorEngine` + `CzscSignals` 全链路。

### 4.2 `test_walk_forward_uses_next_day_return`
构造已知价格路径，手工算 `fwd_exp = price.shift(-1)/price-1`；跑 `WalkForwardBacktester`。断言回测输出中每个测试日 `t` 的 `bench_ret[t] == fwd_exp.loc[t].mean()`（即 `t→t+1` 收益均值），且 `≠` 当日收益（恒 0）/ `≠ t+1→t+2` 收益。结构级证明 point-in-time。

### 4.3 `test_sentiment_rolling_pct_point_in_time`
对 `_rolling_pct` 在 `target` 日的分位，篡改 `target` **之后**的序列值为极值后重算，断言分位不变 → 证明只用 `≤ target`。

### 4.4 `test_run_daily_ordering_fusion_before_market_sentiment`
静态断言 `orchestrator.run_daily` 中 `step_fusion` 出现在 `step_market_sentiment` 之前，确保融合读取的是前一日（已落库）regime，而非当日（尚未落库）regime。

### 4.5 `test_prediction_baseline_uses_past_only`
构造行情，`_baseline_predict` 在 `t` 的动量值，篡改 `t` 之后价格后重算，断言 `t` 不变 → 证明预测基线纯后视（`shift(5)`）。

> 全部用例已运行通过（见提交记录）。

---

## 5. 发现的问题（LOW 级，非阻断）

### F1（LOW / 条件性）`risk_neutral.py` 的 `mv` 协变量可能含未来市值
`neutralize` 逐日横截面回归 `[行业虚拟, log(mv)]`，其中 `mv` 来自 `stock_list` 静态快照（最新市值）。若 `mv` 为"当前/最新"市值，则对**历史日 `t`** 的中性化使用了 `t` 时点的**未来**市值，属于弱协变量前视，同时削弱市值中性化的准确性。
- **影响有限**：① 行业虚拟变量静态且正确；② `mv` 作为每标的单一标量，仅吸收时间不变的规模效应，不构成"用未来收益预测过去"的强前视；③ 当且仅当 `stock_list` 同时含 `industry` 与 `mv` 列时才执行中性化，否则整段跳过（`_build_meta` 控制）——默认 5 只股票清单可能不具备 `mv`，中性化被跳过。
- **建议**：中性化所需 `mv` 应与 `date` 对齐（用 `t` 日市值，可由 `bars` 近似或从基本面源取时间序列）；或在文档明确"中性化要求时间对齐的 mv，否则跳过"。**本项不阻塞，可在 P1-4 中性化增强时一并处理。**

### F2（LOW / 鲁棒性）walk-forward 预热样本不足
`run_daily(lookback_days=250)` 通常只回拨 250 个日历日。因子含 `MA60`/`rolling(20)` 等需较长历史的窗口；数据集**最早若干日**的因子可能因历史不足为 NaN 或在窗口外延前被低估，因子**质量**（非泄漏）受影响。walk-forward 训练窗亦从数据集起点开始，首段 IC 质量取决于此。
- **建议**：ingest 时多回拨 1–2 年作为预热（仅用于因子计算，不计入信号日）；或在因子计算前跳过历史不足的日期。属 P1 类质量增强，不阻塞。

### F3（INFO）预测 baseline 的 `dir_acc` 为全样本内
`_eval_baseline` 的 `dir_acc` 在全部历史（固定动量规则）上计算。固定规则无待估参数，样本外=样本内，不构成泄漏，仅作信息记录。

---

## 6. 处置建议（指向后续 PRD，本项不改代码）

1. **无紧急修复**：当前架构时间点隔离正确，四源结论可信。建议将 `tests/test_leakage_invariant.py` 并入 CI（衔接 P2-2）。
2. **F1**：在 P1-4（风险中性化增强）或数据治理项中，将 `mv` 改为时间对齐；在此之前若 `stock_list` 无 `mv`，中性化自动跳过，行为安全。
3. **F2**：在 P1-3 / 数据治理中增加预热窗口配置。
4. **回归护栏**：任何新增因子/信号/回测，必须先在 `test_leakage_invariant.py` 通过"篡改未来 → 历史不变"隔离测试，方可合入。

---

## 7. 审计方法说明

- **静态走查**：逐文件阅读因子公式、回测收益定义、融合切片、编排时序；全局 `grep` 价格口径与 `shift` 方向。
- **动态实证**：合成数据隔离测试（篡改未来日 → 断言历史日输出不变），覆盖因子全链路与回测 point-in-time 结构。
- **约束**：本项严格 audit-only；不引入修复性代码改动（与 PRD 范围一致），仅新增测试与文档。
