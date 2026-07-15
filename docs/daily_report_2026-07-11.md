# 每日任务总结报告 · 2026-07-11

> 主题：#6 T2 温度计择时回测验证 + #4 regime 调节 + #5 Dashboard 情绪卡
> 对应 PRD：`docs/sentiment_framework_prd.md`（§8 双卡 / §10 验收硬指标）
> 状态：**已完成实现 + 测试 + README，待人工 review（按约定不自动提交）**

---

## 1. 任务总览

| 编号 | 任务 | 交付物 | 对应 PRD | 状态 |
|------|------|--------|----------|------|
| #6 | T2 温度计择时「样本外」回测验证 | `backtest/sentiment_timing.py` + 编排接入 | §10 验收硬指标（年化/回撤/超额） | ✅ |
| #4 | regime 调节（融合层，默认 OFF） | `fusion/signal_pool.py` 钩子 + 配置 + 验证引擎 | §8 启用前门槛 | ✅ |
| #5 | Dashboard 情绪卡（前端双卡） | API + schema + 前端卡 | §8 双卡 | ✅ |

三项把情绪从「能算」推进到「能用于择时 / 融合」，且 #6 直接对齐 PRD §10 验收硬指标。

---

## 2. 模块改动清单

### 2.1 新增：`backtest/sentiment_timing.py`（#6）
- `SentimentTimingBacktester.run(bars, factor_long, universe, sentiment_df)`：
  - 复用 `WalkForwardBacktester` 的训练权重（IC 加权）/ 打分 / 成本模型，保证与因子回测可比；
  - 把 `sentiment_index.signal` 映射为**权益暴露**：买入=1.0 / 半仓=0.5 / 空仓=0.0，叠加在因子 top20% 等权多头之上；
  - 对照两口径：**baseline**（因子始终满仓，即原 walk-forward 主口径）+ **benchmark**（可投资域等权）；
  - 指标块：年化 / Sharpe / 最大回撤 / DeflatedSharpe / alpha-beta，外加 `excess_*`（择时 − 因子满仓）；
  - 无信号日期退化为半仓（中性假设），不崩溃。

### 2.2 新增：`backtest/signal_backtest.py`（#4 验证引擎）
- `SignalBacktester.run(bars, signals, universe, regime_series, scale_map)`：把融合 `signals` 直接做成**置信度加权多头组合**；
- `compare_regime(...)`：对同一信号做 ON（regime 缩放）/ OFF 双跑，差异**仅来自情绪缩放**（共享再平衡频率与成本），返回 ON/OFF 报告行 + delta（年化/Sharpe/回撤差异）；
- regime 自动 **T-1 偏移**（与在线融合一致：用前一日 regime 调节当日信号，无前视）。

### 2.3 改动：`fusion/signal_pool.py`（#4 钩子）
- `SignalPool.__init__` 读取 `fusion.regime_adjust`（默认关闭）；
- `fuse(..., regime=None)`：当 `enabled` 且 `regime` 在缩放表内时，**仅缩放置信度**（不动方向），置信度 = `sigmoid(|total|·scale) × regime_scale`；
- 默认 `enabled: false` → 任何 regime 均不调节（合规 PRD §8 默认 OFF）。

### 2.4 改动：`config/settings.yaml`
- `fusion` 下新增 `regime_adjust`：`enabled: false` / `fear_scale: 0.75` / `greed_scale: 0.75` / `neutral_scale: 1.0`。

### 2.5 改动：`scheduler/orchestrator.py`
- `step_fusion`：新增 `_latest_regime()`，读取**最近一次（T-1）** `sentiment_index.regime` 传入 `fuse`（point-in-time 正确：当日情绪在 `step_market_sentiment` 之后才落库）；
- `step_backtest`：新增第 4、5 引擎（均 try/except 降级）：
  - 第 4：`SentimentTimingBacktester` → 落库 `walk_forward_sentiment_timing` / `walk_forward_factor_baseline`；
  - 第 5：`compare_regime` → 落库 `signal_long_only` / `signal_long_only_regime_scaled`，日志打印 ON-OFF 差异。

### 2.6 改动：`storage/repository.py`
- 新增 `load_signals_all()`（跨日期全量信号，供 #4 历史验证）。

### 2.7 改动：API + 前端（#5 双卡）
- `api/schemas.py`：新增 `MarketSentimentView`；`DashboardSummary.market_sentiment` 字段；
- `api/routers/dashboard.py`：`/api/dashboard/summary` 注入 `market_sentiment`（新增 `_market_sentiment()`，读 `sentiment_index` 最新行）；
- `web/src/api/client.ts`：`DashboardSummary.market_sentiment: MarketSentimentView`；
- `web/src/pages/Dashboard.tsx`：新增「市场情绪指数（T1/T2/T3）」卡（指数/regime/signal/温度计/GSISI + 五维进度条），镜像 Monitor 卡，补齐 PRD §8 双卡。

---

## 3. 测试与验证

新增 3 个测试文件（共 12 用例，全部通过）+ 冒烟 `__main__`：

| 测试 | 覆盖 |
|------|------|
| `tests/test_sentiment_timing.py` | 非空气流 / 三组指标齐全 / exposure 映射 / 缺失信号降级 / 空输入降级 |
| `tests/test_signal_backtest.py` | OFF 非空 / ON 极端日持仓收敛（≤OFF）/ `compare_regime` delta / 空输入降级 |
| `tests/test_regime_adjust.py` | 默认 OFF 不缩放 / 开启后极端缩放且方向不变 / 中性不调 |

回归：既有 `test_sentiment_t0.py` + `test_market_sentiment.py` 仍全绿（情绪相关共 20 用例通过）。

冒烟（`tests/test_sentiment_timing.py` 等 `__main__`，合成数据）：
- T2 择时：样本外 200 日，择时年化 −25.3% vs 因子满仓 −41.6%，**超额 +16.3%**，最大回撤 −22.7%（半仓/空仓有效削峰）；
- regime 缩放 ON-OFF：delta 年化 +0.16 / Sharpe +2.00 / 回撤 +0.13（合成数据仅验证结构与方向，真实结论以实盘历史回测为准）。

---

## 4. 关键设计决策

1. **#6 暴露叠加而非独立择时**：温度计信号直接映射为因子组合的权益暴露（1/0.5/0），与 walk-forward 主口径共享训练/打分/成本，确保「择时增量」可干净隔离（baseline=因子满仓）。
2. **#4 仅缩置信度、不动方向**（PRD §8 明示）：保守口径——极端情绪下降本，降低综合 conviction；下游阈值/展示随之收敛。
3. **#4 默认 OFF + 验证门槛**：启用前需 `compare_regime` 在真实历史信号上跑出正向 delta（年化/回撤改善）方可开启，避免主观拍脑袋。
4. **T-1 regime 偏移**：融合与验证均用前一日 regime，杜绝当日收盘信息前视。
5. **#5 双卡对齐**：Dashboard 卡与 Monitor 卡共用同一 `sentiment_index` 字段与展示结构，保证运维/看板两侧一致。

---

## 5. 风险与后续

- **#4 仍未启用**：`regime_adjust.enabled=false`。建议累积 ≥20 日真实信号后，观察 `step_backtest` 第 5 引擎日志的 ON-OFF 差异，正向再开。
- **#6 阈值固定**：当前用 `thermometer.buy=10 / empty=90` 硬阈值，尚未做阈值参数寻优（属 PRD §10 后续增强）。
- **合成数据结论不可外推**：冒烟仅验证管线正确，真实样本外表现须在实盘历史上复跑。
- **仍未完成（来自此前 pending 清单）**：#1 T2 PCR/IV 维度、#2 T3 HMM/Transformer 研究、#3 Baker-Wurgler PCA；平台级 #7 LLM D3 联调 / #8 push.py / #9 agent_interface / #10 编排步骤评估；验证级 #11 mootdx 沙箱 / #12 watchlist 空。

---

## 6. 提交状态

- 未提交（按约定待 review）。改动文件：
  - 新增：`backtest/sentiment_timing.py`、`backtest/signal_backtest.py`、`tests/test_sentiment_timing.py`、`tests/test_signal_backtest.py`、`tests/test_regime_adjust.py`
  - 修改：`fusion/signal_pool.py`、`config/settings.yaml`、`scheduler/orchestrator.py`、`storage/repository.py`、`api/schemas.py`、`api/routers/dashboard.py`、`web/src/api/client.ts`、`web/src/pages/Dashboard.tsx`、`README.md`
