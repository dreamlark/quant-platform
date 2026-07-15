# 量化平台 · 第一次系统优化文档（v1 · 待评审）

> **文档状态**：草稿 / 待评审（评审通过后逐项进入 架构→实现→测试）
> **生成日期**：2026-07-15
> **范围**：基于当前仓库实际状态（11 步流水线、四源融合、DuckDB 双库、FastAPI+React、资源分离已落地）梳理的优化项
> **如何使用**：本文档每个优化项含 **PRD（目标/范围/验收）** 与 **方案（架构级设计）**。请在评审时重点确认：① 优先级与分阶段顺序；② Open Questions 中的取舍；③ 是否全部纳入或先挑几项为第一轮。评审通过后再就单项产出实现计划。

---

## 0. 总评与优化哲学

平台已完成"能跑通、分析闭环完整"：ingest → 因子/技术/情绪/预测 → 融合 → 回测 → 看板/监控全链路可用，资源分离也已落地。

但**工程健壮性落后于功能完整性**。近期修复的两个 API Bug 具有代表性：

- **Bug A**（DuckDB 重复开 `read_only` 连接 → `ConnectionException`）：API 层越过了存储边界直连数据库；
- **Bug B**（pydantic 序列化 inf/nan → 500）：序列化清洗没有集中在边界做。

二者同属"**边界泄漏**"类架构债，不是孤例。因此本轮优化哲学是：**先补地基（正确性兜底 + 冗余），再提可信度（模型/回测），最后加护栏（CI/可观测性/运维）**。不急于加新功能。

---

## 1. 优化项总览（优先级矩阵）

| 编号 | 优化项 | 优先级 | 类型 | 工作量 | 核心价值 |
|------|--------|--------|------|--------|----------|
| P0-1 | 前视偏差审计 | P0 | 正确性 | 中 | 结论可信度地基，不做则所有收益存疑 |
| P0-2 | 数据源冗余 | P0 | 可靠性 | 中 | 消除单点故障 + 缓解限流（你亲历的痛点） |
| P1-1 | 预测源过弱 | P1 | 模型质量 | 高 | 让"预测第 4 源"名副其实或诚实降级 |
| P1-2 | regime_adjust 启用 | P1 | 风控 | 低 | 极端行情缩放置信度，收窄回撤 |
| P1-3 | 回测成本 realism | P1 | 可信度 | 低-中 | 剔除以往"纸面盈利"误导 |
| P2-1 | 边界集中治理 | P2 | 架构 | 中 | 系统性消灭 Bug A/B 一类问题 |
| P2-2 | CI 流水线 | P2 | 质量护栏 | 低-中 | 你重视的高质量门槛，目前零护栏 |
| P2-3 | 失效告警 | P2 | 可观测性 | 中 | 数据断更/模型衰减主动发现 |
| P3-1 | 调度落盘 | P3 | 运维 | 低-中 | 每日实跑可靠、失败可见 |
| P3-2 | MLOps 自动化 | P3 | 可复现 | 中 | 模型重训→资产发布的全链路自动化 |
| P3-3 | 数据质量测试 | P3 | 数据治理 | 中 | 信号不被缺失/复权错误/ST 污染 |

---

## 2. 分阶段路线建议

```
Phase 1  地基      P0-1 前视审计  →  P0-2 数据源冗余
Phase 2  可信度    P1-3 成本realism → P1-2 regime → P1-1 预测源
Phase 3  护栏      P2-1 边界治理 → P2-2 CI → P2-3 告警
Phase 4  运维      P3-1 调度 → P3-3 数据质量 → P3-2 MLOps
```

**理由**：P0 两项不动则后续所有"收益数字"都站不住；P1 在 P0 之后才有意义（成本 realism 是 regime/预测对比的公平基准）；P2 护栏应在功能稳定后统一收口；P3 是运维成熟度，可并行于日常。

---

## 3. 逐项 PRD 与方案

> PRD 统一结构：问题陈述 / 目标与成功指标 / 范围（含/不含）/ 方案与架构 / 关键设计 / 验收标准 / 风险与缓解 / 工作量与依赖。

### P0-1 前视偏差审计（Look-ahead Bias Audit）

**问题陈述**
因子/融合/回测若在任何环节使用了 t 时刻之后的信息，整个四源框架的结论即失效。当前 `factors/`、`fusion/signal_pool.py`、`backtest/` 的信号生成未做统一的"时间点隔离"验证。这是量化平台最高危的沉默错误。

**目标与成功指标**
- 对因子计算、融合、回测、walk-forward 评估全链路做时间隔离走查，产出**逐模块 PASS/LEAK 报告**。
- 建立可纳入 CI 的"防泄漏"不变量测试，新增代码不再引入前视。

**范围**
- **含**：审计 `factors/*`、`fusion/signal_pool.py`、`backtest/signal_backtest.py`、`backtest/sentiment_timing.py`、walk-forward 评估；产出检测工具 + 报告。
- **不含**：本项只审计+报告，**不修复**（修复作为后续独立 PRD，避免 scope creep）。

**方案与架构**
- 引入"**时间点封印**"包装层：在因子/融合取数时强制禁止读取 `date > t-1` 的数据；对现有代码注入封印后跑一遍，比对信号是否变化（变化即疑似泄漏）。
- 合成数据泄漏探针：构造一份"未来收益率被故意作为特征"的合成行情，断言该特征**不会**出现在任何 t 时刻信号中。
- 输出 `docs/leakage_audit_report.md`：每模块结论 + 证据。

**关键设计**
- 封印层挂在 `storage/repository.py` 查询接口，而非改动每个因子函数，降低侵入。
- 不变量测试作为 CI 门禁（与 P2-2 衔接）。

**验收标准**
- 报告给出每个模块的明确 verdict；发现的问题附最小复现。
- 封印层 + 合成探针测试合并入测试套件，CI 红灯即泄漏。

**风险与缓解**
- 可能发现真实泄漏 → 触发因子集返工。缓解：本项严格审计-only，返工单列 PRD 与预算。

**工作量与依赖**：中；无前置依赖。

---

### P0-2 数据源冗余（Data Source Redundancy）

> **状态更新（2026-07-15）**：本项**核心代码已落地并验证**，无需新建适配器。
> 原 PRD 的"新建 Eastmoney/Tencent 日线适配器"方案作废——改为**直接采用既有的多源路由**
> （`DataSourceRouter` + `mootdx`/`akshare`/`baostock` 三适配器），该方案源自早期 a-stock-DB
> 的 scale 设计，因沙箱网络受限曾临时降级为单源，现已在生产调度路径中完整跑通（见下方"已实现"）。
> **本会话收尾**：配置化（`source_timeout` / `divergence_log` 已写入 `settings.yaml` 并由 `build_data_router` 透传）、
> 偏差日志结构化（`divergence_log` JSONL 结构化记录 + 单测）、文档化（README §4.6 / §8.3 已补）均已完成。
> 仅**真机验证**为验收动作（沙箱无外网/TDX 不可达，列为验收项而非开发项）。

**问题陈述**
`step_ingest` 早期在沙箱里因网络受限临时降级为 akshare Sina 单源。单源既是单点故障，也是限流元凶
（你亲历的痛点）。数据源冗余在最初设计就已纳入（`a-stock-DB` 的 scale 方案），现需把这套
多源路由正式接回生产路径。

**目标与成功指标**
- ingest 走 `DataSourceRouter`，按优先级 `mootdx(1) → akshare(1) → baostock(4)` 回退；主源失败/超时自动降级。
- 单源挂死（如 `baostock.login` 阻塞）有超时护栏，不冻结整条流水线。
- 跨源 `close` 差异超阈值告警，并结构化记录供监控（衔接 P2-3）。

**范围**
- **含**：真机验证三源可达性（验收动作）；把 `source_timeout` / `diff_threshold` / `divergence_log` 配到 `config/settings.yaml`（已完成）；
  跨源偏差写 `divergence_log` 并结构化（已完成，含单测）；README/架构文档更新"已采用多源冗余"（已完成）。
- **不含**：新建 Eastmoney/Tencent 适配器（已确认不必要）；存储层改动。

**方案与架构（采用既有实现）**
- 统一接口：`sources/base.py::DataSource`（`fetch_daily_bars` 返回不复权原始日 K，复权由 `adjust.py` 统一处理）。
- 三适配器（均已实现）：
  - `MootdxAdapter`（name=`mootdx`, priority=1）：通达信 TCP 7709 直连，**不会被 IP 封禁**，生产首选。
  - `AkshareDailyAdapter`（name=`akshare`, priority=1）：akshare Sina 历史日线，沙箱可用。
  - `BaostockAdapter`（name=`baostock`, priority=4）：baostock，兜底；`login()` 在受限网络会阻塞 → 由超时护栏降级。
  - （附 `tencent` priority=2 为盘中实时快照源，不参与日线回退，仅供 realtime。）
- 路由策略：`DataSourceRouter.fetch` 按 `priority` 升序尝试；每个源 `health_check`+`fetch_daily_bars`
  均经 `_call` 套 `source_timeout`（默认 20s，daemon 线程 + join 超时）护栏；首个成功源返回，
  后续源做 `_cross_check`（差异 > `diff_threshold=0.03` 告警并标记 `source_suspect`）；原始响应落 `data/raw_cache/`。
- 生产装配：`scheduler/jobs.py::build_data_router(settings)` 读 `settings.data_sources.priority`
  （默认 `["mootdx","akshare","baostock"]`）构建路由。

**已实现 & 已验证（本会话生产路径跑通）**
- 生产调度路径（`build_data_router` + `Orchestrator(data_source=router)`）在沙箱跑通：路由构建为
  `[mootdx(1), akshare(1), baostock(4)]`；`baostock` 因 `login` 阻塞触发 >20s 超时 → 自动跳过；
  `mootdx` 在沙箱返回 0 行（沙箱无 TDX 网络，预期）；`akshare` 正常交付全部 825 行 → **冗余降级链路按设计工作**。
- 修复了 3 个阻塞生产路径的缺陷（同批提交）：`jobs.py` 误 import `AkShareAdapter`（应为 `AkshareDailyAdapter`）、
  `source_timeout` 未透传、生产路由未启用。

**关键设计**
- 复权口径统一：所有适配器返回不复权原始价，复权集中在 `adjust.py`，杜绝源间口径错配。
- 超时护栏是真实机上的关键保险：baostock 在部分网络会 `login` 挂死，无护栏则整条 ingest 冻结。

**验收标准**
- 真机（有外网/TDX 可达）跑一次 `run_daily`：三源中至少两源成功，日志可见回退与 `source` 标注（验收动作）。
- `config/settings.yaml` 含 `data_sources.source_timeout` / `diff_threshold` / `divergence_log`；改值后行为随之变化（✅ 已实现）。
- 故意制造跨源差异 > 阈值 → `divergence_log` 出现结构化 JSONL 记录（✅ 已实现 + `tests/test_divergence_log.py` 覆盖）。

**本会话落地补充（2026-07-15）**
- `sources/base.py::DataSourceRouter` 新增 `divergence_log` 参数与 `_record_divergence()`：超阈值分歧写入
  JSONL（字段 `ts/code/date/source_a/source_b/price_a/price_b/diff/threshold`），带锁、写失败不阻断主流程。
- `scheduler/jobs.py::build_data_router` 透传 `source_timeout` / `divergence_log`（路径基于仓库 ROOT）。
- `config/settings.yaml` 显式补 `source_timeout: 20.0` 与 `divergence_log` 路径。
- `tests/test_divergence_log.py`：超阈值写记录（含字段断言）+ 未超阈值不写，2 例全过；全量测试 53 通过。

**风险与缓解**
- 沙箱无法验证 mootdx/baostock 真机可达性。缓解：**本项为"采用既有方案"，真机验证是验收动作而非开发**；
  真机若 mootdx 不可达，akshare 仍兜底，不影响生产。
- 不同源停牌/复权边界差异。缓解：统一不复权接口 + `_cross_check` 偏差告警。

**工作量与依赖**：低（核心已落地）；依赖一次真机验证与文档更新；`config/settings.yaml` 少量扩展。

---

### P1-1 预测源过弱（Weak Prediction Source）

> **状态更新（2026-07-15）**：**方向已定并落地**——采纳「先修两个弱源 + 动态 IC 加权 + 3 窗口闸门」。
> 已实施：
> - P1-1a Darts 训练泄漏修复：`prediction.generate` 中 `darts.fit` 前将 panel 截断到早于最早
>   评估日（`_darts_train_cutoff`），统计量仅来自训练段，杜绝未来信息漏入训练。
> - P1-1b 动态 IC 加权 + 闸门：`predict_health` 新增 `ic`/`rolling_ic`/`dropped`；
>   `_eval_heavy` 算横截面 per-date Spearman IC → 滚动窗口 → `连续 3 窗口 |IC|<eps 自动剔除`；
>   权重由 IC 动态决定（替代静态 dir_acc 门），IC 不可得回退 dir_acc 软加权。
> - `config/settings.yaml` 暴露 `fusion.predict_ic`；`tests/test_prediction_ic.py` 覆盖。
> - QLib 特征工程本就 point-in-time 正确（exclude_tail + 因果特征），无需改，纳入同一 IC 通道。
> 详见 `docs/p1_1_prediction_source_audit.md`。

**问题陈述**
融合中 `predict` 权重 0.25，但内部仅 Kronos `dir_acc≈0.632` 拿到正权，darts/qlib 近随机被降权到 0。结果"预测第 4 源"实际只靠一个模型撑着，名存实亡。

**目标与成功指标**
- 二选一落地：① 救活 darts/qlib（walk-forward `dir_acc > 0.55` 且统计显著）；或 ② 正式砍掉并简化，文档诚实标注 predict=Kronos。
- 可选：引入更干净的 ML 源（如因子矩阵的 XGBoost/LGBM）作为候选。

**范围**
- **含**：审计 darts/qlib 输入特征与目标区间（疑似前视或 horizon 错位）；重训 + 重评估；或给出砍掉方案 + 代码简化 + 文档更新（§4.5 / README）。
- **不含**：更换底层 Kronos 模型本身。

**方案与架构（三选一，待评审定）**
- **方案 A（修）**：修正 darts/qlib 特征工程（严格 t-1 及更早、正确预测 horizon），walk-forward 重评估。
- **方案 B（砍）**：移除 darts/qlib 适配器，融合降为三源，`predict` 仅 Kronos；更新 `fusion.base_weights` 与文档。
- **方案 C（换）**：以滞后因子矩阵训练 XGBoost/LGBM 作为新的 ML 预测源，复用现有 walk-forward 评估框架。

**关键设计**
- 任何方案都必须先过 P0-1 前视审计，否则 `dir_acc` 不可信。

**验收标准**
- 若选 A/C： revived/新模型 `dir_acc > 0.55` 且 walk-forward 显著优于 0.5；否则退回 B。
- 若选 B：代码简化无残留、文档与 §4.5 一致、融合权重自洽。

**风险与缓解**
- A 股日频 ML 可能本质近随机（有效市场）。缓解：设定 0.55 硬阈值，不达标即走 B，不硬凑。

**工作量与依赖**：高（研究密集）；**强依赖 P0-1**。

---

### P1-2 regime_adjust 启用（Market Regime Confidence Scaling）

> **状态更新（2026-07-15）**：**已落地并启用**。核心改动：
> - `factors/market_sentiment.py` 新增 4 态 `regime_state`（bull/neutral/bear/panic）派生：
>   由情绪 thermometer（恐惧/中性/贪婪）+ **指数 N 日回撤**（横截面均价代理，point-in-time）合成。
> - `sentiment_index` 表新增 `regime_state` 列（DDL + `init_schema` 幂等 ALTER 迁移）。
> - `fusion.regime_adjust.enabled` 默认 **true**（安全默认：neutral/bull=1.0 不调节，仅 bear/panic 缩放）；
>   缩放表改为 4 态 `scale: {bull:1.0, neutral:1.0, bear:0.70, panic:0.45}`。
> - 融合层读 `regime_state`（T-1 已落库）做缩放；`compare_regime` 默认 4 态 + 读 `regime_state`。
> - API/前端：MarketSentimentView 新增 `regime_state` / `regime_scale`，Monitor/Dashboard 情绪卡展示状态与缩放系数。
> - 测试：`tests/test_market_regime_state.py`（派生 + 回撤 point-in-time 不变性 + compute 输出）+ `test_regime_adjust.py`/`test_signal_backtest.py` 迁移到 4 态；全量 57 测试通过。

**问题陈述**
`fusion/signal_pool.py` 已实现"极端情绪仅缩放置信度"的 `regime_adjust` 钩子，但默认 OFF。市场极端期的回撤保护未生效。

**目标与成功指标**
- 定义可解释的 regime 状态（bull/neutral/bear/panic），基于 `sentiment_index` + 指数回撤。
- 开启后，熊/恐慌期信号置信度收窄，且**不改变方向**（与现有钩子语义一致）。
- 回测对比 ON vs OFF，确认熊市最大回撤收窄且不过度牺牲收益。

**范围**
- **含**：regime 判定（复用已建的 `sentiment_index`）、钩子默认开启（安全默认）、Monitor 展示当前 regime、回测对比。
- **不含**：改变信号方向逻辑（仅缩放置信度，保持现有设计）。

**方案与架构**
- regime 状态机：`sentiment_index` 低位 + 指数 N 日回撤超阈 → bear/panic；高位 → bull；中间 → neutral。
- 置信度缩放系数 `k(regime)` ∈ (0,1]，panic 最小；写入融合信号元信息，便于回测归因。
- 开关与系数在 `config/settings.yaml` 暴露，默认 ON。

**关键设计**
- regime 信号本身必须过 P0-1（只能用 t-1 及更早）。
- 对比基准先依赖 P1-3 成本 realism，保证公平。

**验收标准**
- 回测：熊市段最大回撤 ON < OFF；整体 excess 降幅在可接受范围（阈值待定）。
- Monitor 实时显示当前 regime 与缩放系数。

**风险与缓解**
- 过度缩放导致牛市踏空。缓解：系数区间设上限，回测择优选参。

**工作量与依赖**：低；依赖 `sentiment_index`（已完成）、P1-3（公平对比）。

---

### P1-3 回测成本 realism（Backtest Cost Realism）

**问题陈述**
T2 择时回测展示 +13.4% 超额，但未确认含交易成本/滑点/涨跌停流动性约束。A 股 T+1 + 涨跌停不可交易是硬约束，忽略会严重高估。

**目标与成功指标**
- 所有回测同时报告 **毛收益** 与 **净收益（含成本）**，净收益作为头条指标。
- 成本模型覆盖佣金、滑点、A 股 T+1、涨跌停不可交易约束。

**范围**
- **含**：在 `backtest/signal_backtest.py` 增加可配置成本模型；重跑 T2/sentiment 回测输出净收益；成本参数入 `config/settings.yaml`。
- **不含**：组合层仓位优化（仍按现有信号驱动）。

**方案与架构**
- 成本模型：`commission`（如 0.03% + 最低 5 元）、`slippage_bps`（可配）、`t_plus_1`（默认 True）、`limit_up_down_illiquid`（涨跌停当日不可成交）。
- 回测产出增加 `gross_excess` / `net_excess` / `max_dd_net` 字段；现有看板/报告读取 net。

**关键设计**
- 成本参数集中在 `settings.yaml`，单测用极端参数验证边界（如 0 成本 = 毛收益）。

**验收标准**
- 同一信号，净收益 ≤ 毛收益；成本=0 时两者相等。
- 涨跌停日不产生成交记录（单测断言）。

**风险与缓解**
- 滑点建模粗糙。缓解：参数化 + 给出敏感性区间，不在本项追求精算级。

**工作量与依赖**：低-中；依赖现有 `backtest/` 模块。

---

### P2-1 边界集中治理（Boundary Centralization）

**问题陈述**
API 端点曾直连 DuckDB（Bug A），序列化清洗缺失（Bug B）。根因是存储访问与序列化没有强制集中在边界。

**目标与成功指标**
- 全量禁止 API 层直连数据库；所有取数走 `storage/repository.py`。
- 序列化消毒（inf/nan/None）集中在 API 边界，新增端点不再各自造轮子。
- 所有边界使用 pydantic DTO。

**范围**
- **含**：pre-commit/CI 规则禁止 `api/` 内 `duckdb.connect`；统一 `sanitize_for_json()` 中间件/基类；统一错误处理器；边界 DTO 化。
- **不含**：重构业务逻辑。

**方案与架构**
- 静态护栏：`tools/check_api_boundary.py` 扫描 `api/**` 下的 `duckdb.connect` / `DuckDBClient(`，命中即非零退出（CI / pre-commit 调用）。
- 运行时护栏（核心机制）：`SanitizedJSONResponse`（`api/middleware.py`，继承 `JSONResponse`）作为 `FastAPI(default_response_class=...)` 的默认响应类。Starlette 0.50 的 `JSONResponse.render` 默认 `allow_nan=False`，路由一旦返回 inf/nan 会在序列化阶段抛 `ValueError` → 500；该子类在序列化前先 `sanitize_obj` 把 inf/nan→None、numpy→原生类型，覆盖全部端点（含 `response_model` 路径）。复用 `api/serializers.py` 的 `sanitize_val/sanitize_obj/sanitize_df`。
- 错误统一：`register_exception_handlers(app)` 注册 `Exception` 处理器，未捕获异常 → 干净 JSON（500 + `detail`/`error`），避免裸栈。

> **实现注记（为什么不用 `BaseHTTPMiddleware` 重序列化）**：曾尝试用响应中间件在边界重序列化，但有两处硬伤被放弃——(a) Starlette 在 `JSONResponse.render` 阶段就因 `allow_nan=False` 拒绝 inf/nan，中间件在 `call_next` 之后才拿到响应，异常早已抛出，永远拦不到；(b) `BaseHTTPMiddleware` 会把端点异常从 `ExceptionMiddleware` 之外重抛，导致注册的 `Exception` 处理器失效（路由 500 变裸 HTML）。故改为「默认响应类 + 异常处理器」两条互不干扰的链路。

**关键设计**
- 复用现有 `_sanitize_val/_sanitize_df`（dashboard.py 已验证）上提到共享模块 `api/serializers.py`；dashboard.py 等端点直接 `from api.serializers import sanitize_df as _sanitize_df, sanitize_val as _sanitize_val`，不再各自内联。
- `sanitize_df` 逐列 `apply(sanitize_val)`：数值列 inf/nan 经 pandas 折叠为 nan（最终由响应类转 None），object 列 inf/nan→None、numpy→原生类型。

**验收标准**
- `grep -rn "duckdb.connect" api/` 为零（已由 `tools/check_api_boundary.py` 静态保证）。
- `tests/test_api_boundary.py`：故意返回 inf/nan 的端点 → 200 且字段为 null；未捕获异常 → 200/500 干净 JSON；`sanitize_obj/sanitize_df` 单元覆盖。
- 全量测试：`python -m pytest -q` 全绿（P2-1 落地后 70 passed）。

> **状态**：✅ 已完成（commit 待提交）。含 `api/serializers.py`、`api/middleware.py`、`api/main.py`（默认响应类 + 异常处理器）、`tools/check_api_boundary.py`、`tests/test_api_boundary.py`，并清理 `api/utils.py` 死导入 `DuckDBClient`、dashboard.py 冗余内联 sanitize。
- 中间件有单测。

**风险与缓解**
- 存量端点改造量。缓解：先加护栏防新增，存量分批迁移。

**工作量与依赖**：中；复用现有 `repository.py` 与 sanitize 逻辑。

---

### P2-2 CI 流水线（CI Pipeline）

**问题陈述**
当前仅 3 个测试文件、12 用例，零 CI；`tools/fetch_resources.py` 无测试。你重视的高质量门槛目前无自动护栏。

**目标与成功指标**
- PR/推送触发 CI：lint + 测试 + fetch_resources 校验全绿才允许合入。
- 建立可重复的质量基线。

**范围**
- **含**：GitHub Actions 工作流（边界护栏 `tools/check_api_boundary.py` + 应用可导入校验、`pytest` 全量、`fetch_resources --check` 资源校验、`tests/test_smoke.py` 内存假数据冒烟跑核心链路）。
- **不含**：CD 部署、覆盖率门禁、ruff/flake8 lint（先建基线，后续加）；当前 lint 以边界护栏 + 导入校验 + 全量测试兜底，不引入额外 lint 依赖。

**方案与架构**
- `.github/workflows/ci.yml`：Python 3.11（pip 缓存）；步骤 lint（边界护栏 + app import）→ resources-check（信息性）→ pytest → smoke。
- 烟雾跑复用现有 `tests/test_smoke.py`：内存 `InMemoryDataSource` 构造 7 只标的（含 1 只 ST 验证可投资域剔除）× 120 交易日，跑通 `ingest→universe→factors→sentiment→predict→health→neutralize→fusion→signals 落库`，无需网络/密钥/重型依赖（qlib/czsc/darts 等懒加载，未装则降级）。

**关键设计**
- 边界护栏与 P2-1 共用 `tools/check_api_boundary.py`，CI 一键扫描 `api/**` 的 `duckdb.connect`/`DuckDBClient(`，命中即红。
- `fetch_resources --check` 仅打印资源完整/缺失状态、不阻断构建（资源为可选，缺失时平台靠 mock/降级运行）；接私有仓库大资产时再升级为硬门禁。
- 烟雾跑即 `python tests/test_smoke.py`，退出码 0 即通过。

**验收标准**
- `api` 层引入 `duckdb.connect` → CI 红（边界护栏）。
- 引入回归使 `pytest` 失败 → CI 红。
- 基线全绿且耗时可接受（< 10 min；当前全量 + 冒烟在沙箱 < 1 min）。

**风险与缓解**
- 沙箱/CI 环境差异（czsc/darts 可选依赖）。缓解：流水线只装 `requirements.txt` 运行时依赖 + pytest，重型依赖懒加载、缺失自动降级，核心链路与全量测试不依赖它们。

> **状态**：✅ 已完成（commit 待提交）。含 `.github/workflows/ci.yml`；本地已逐一验证 5 个步骤（边界护栏 OK、app import OK、`fetch_resources --check` 通过、pytest 70 passed、`test_smoke.py` 退出 0）。

**工作量与依赖**：低-中；与 P2-1 护栏规则共用配置。

---

### P2-3 失效告警（Failure Alerting）

**问题陈述**
Monitor 页面能展示 `is_stale`、因子健康、模型状态，但**无主动通知**。数据断更或模型 `dir_acc` 衰减只能人肉刷页面发现。

**目标与成功指标**
- 数据 stale / 模型 `dir_acc` 跌破阈值 / 因子健康失败 → 主动推送（可配置通道）。
- 正常状态零误报。

**范围**
- **含**：`notify` 模块（可插拔通道：Webhook/SMTP/Server 酱等）、由 monitor 检查触发、阈值配置化、每日摘要。
- **不含**：告警平台的复杂路由/值班。

**方案与架构**
- `common/notify.py`：``Channel`` 抽象 + ``MockChannel``（默认/测试，记录不触网）/ ``ConsoleChannel``（打印日志）/ ``WebhookChannel``（httpx POST JSON）；``Notifier`` 聚合并提供 ``alert()``/``digest()``；``evaluate_health`` 为纯函数阈值评估（不依赖 DB，易测）；``build_digest`` 拼装每日摘要。
- `common/alert_monitor.py`：``monitor_run(repo, settings, notifier)`` 从 Repository 采集健康指标（数据新旧 `data_age_days`、多源分歧 `divergence_count`、被 IC 闸门剔除预测员 `dropped_predictors`、市场温度/状态），经阈值评估后发告警 + 每日摘要；``gather_metrics`` 纯读取、非致命。
- 触发点：``scheduler/orchestrator.run_daily`` 末尾以 ``try/except`` 包裹调用 ``monitor_run``（非致命，默认 Mock 通道不触网），手动与调度运行都覆盖。
- 阈值（`max_data_age_days` / `max_divergence` / `max_dropped_predictors`）在 `config/settings.yaml` 的 `notify.thresholds`；`notify.channels` 留空 → 默认 Mock（安全不触网）。

**关键设计**
- 通道可插拔；微信（Server 酱/企业微信应用）/ 邮件（SMTP）为扩展点，实现对应 ``Channel`` 子类即可，未配置则不发，避免泄露到外部。
- 与 P3-1 调度落盘共享"运行事件"来源（后续可从 `run_log` 取指标，当前从 Repository 现读）。

**验收标准**
- 模拟 stale（data_age_days 超阈值）→ 对应通道收到 critical 告警（``tests/test_notify.py`` 用 Mock 通道验证）。
- 正常数据 → 无告警、仅发每日摘要。
- 通道/阈值配置生效（``Notifier.from_settings``、`evaluate_health`` 单测覆盖）。

**风险与缓解**
- 误报骚扰。缓解：digest + 阈值保守默认（max_data_age_days=3 容忍周末/节假日）。

> **状态**：✅ 已完成（commit 待提交）。含 `common/notify.py`、`common/alert_monitor.py`、`config/settings.yaml` 的 `notify` 块、orchestrator `run_daily` 末尾触发、`tests/test_notify.py`（8 用例）。全量测试 78 passed。

**工作量与依赖**：中；可与 P3-1 共用运行事件。

---

### P3-1 调度落盘（Scheduler Persistence）

**问题陈述**
`scheduler/orchestrator.py` 存在且跑通，但运行记录/可见性不清：一次失败能否被立刻发现？上次成功跑到哪一步？

**目标与成功指标**
- 调度可稳定每日触发（cron/systemd timer）。
- 每次运行落盘：开始/结束时间、每步状态、错误；Monitor 可查"上次运行"。

**范围**
- **含**：`scheduler/run_state.py` 写 `run_log`（入 `analytics.duckdb`）、systemd/cron 单元、Monitor 展示最近运行与逐步状态。
- **不含**：分布式调度、重试编排复杂性。

**方案与架构**
- `scheduler/run_state.py`：`RunState` 上下文管理器，包裹 `run_daily` 的每一步（`rs.step(name, fn, *a, **k)`），逐步计时 + 落盘状态；`__exit__` 写整轮运行记录（含 steps 摘要）。
- 落盘复用现有 `api/run_store` 的 JSONL 机制（`run_history.jsonl` + 新增 `run_steps.jsonl`），**刻意不复用 DuckDB**——与 `run_store` 设计一致，避免与批处理/DuckDB 写者争锁（原方案写 `analytics.duckdb` 的 `run_log` 会引入写者争用，故改为 JSONL）。
- 触发点：`orchestrator.run_daily` 整体包在 `with RunState(...) as rs:` 中，11 步逐一 `rs.step`；步骤异常向上传播（不吞），运行记录标记 fail。
- Monitor：`/api/monitor/batch-run` + overview 的 `batch_run` 字段返回最近一次批处理运行 + 逐步明细；前端「批处理运行健康」卡展示状态与各步 OK/FAIL。

**关键设计**
- 逐步记录与整轮记录分离（`run_steps.jsonl` / `run_history.jsonl`），按 `run_id` 关联，便于取逐步明细。
- 运行记录带 `kind="batch"`，与 UpdateManager 的运行记录区分；失败步骤高亮，与 P2-3 告警互补（告警看"数据/模型健康"，此处看"运行本身成败"）。

**验收标准**
- 跑一次后 Monitor「批处理运行健康」卡显示时间戳 + 每步状态。
- 人为制造某步失败 → 该步标红、运行记录 status=fail、异常向上传播（测试 `tests/test_run_state.py` 覆盖）。

**风险与缓解**
- DuckDB 单写者：改为 JSONL 落盘，完全避开 DuckDB 写者争锁。

> **状态**：✅ 已完成（commit 待提交）。含 `scheduler/run_state.py`、`api/run_store.py`（append_step/load_steps）、`orchestrator.run_daily` 改造、monitor `/batch-run` + overview `batch_run`、`web/src/pages/Monitor.tsx` 运行健康卡、`tests/test_run_state.py`（4 用例）、`web/src/api/client.ts` 类型扩展。全量测试 82 passed；tsc OK。

**工作量与依赖**：低-中；依赖 P2-1 的边界治理（统一取数）。

---

### P3-2 MLOps 自动化（Resource Release Automation） ✅ 已完成（已 commit）

**问题陈述**
模型重训 → 打包资产 → 建 Release → bump manifest 全手动。随模型迭代频率上升，手动易错且不可复现。

**目标与成功指标**
- 一条命令完成：重训模型 → 打包 data/models 资产 → 建/更新 Release → 更新 `resources/manifest.json`（版本+sha256）→ 提交 manifest。
- 保留最近 N 个资源版本。

**范围**
- **含**：`tools/release_resources.py` 编排 tar+上传+manifest 更新；版本标签 `resources-YYYY-MM-DD`；保留策略。
- **不含**：模型训练算法本身（训练逻辑在各自模块）。

**方案与架构**
- 编排脚本 `tools/release_resources.py`，流程：
  ① `build_archive` 按 `RESOURCE_PLAN` 打包 `data/`（market/analytics/verify_snapshot duckdb，排除 raw_cache 等可重生文件）与 `_local_kronos_weights/` 为两个 `tar.gz`；
  ② 计算 `sha256` + `size_bytes`；
  ③ `update_manifest` bump `version(YYYY-MM-DD)`/`updated_at`/`tag`/`base_url`，刷新各资源 `archive`/`sha256`/`size_bytes`/`files`（保留 `name`/`description`/`extract_to`）；
  ④ `retain_releases` **每个资源**本地保留最近 `--keep`（默认 3）个 tar，data/models 独立回滚；
  ⑤ `--upload` 时走 `gh release` best-effort 上传（需 `GITHUB_TOKEN`；失败仅告警不阻断）。
- 幂等：同 version 重跑覆盖本地产物；`--dry-run` 仅预览不写文件。
- CLI：`--all`/`--data`/`--models`（互斥必选）、`--dry-run`、`--no-upload`、`--upload`、`--keep`、`--version`、`--out-dir`。

**关键设计**
- 复用 `tools/fetch_resources.py` 的 manifest 契约，保证上下行一致，`fetch_resources.py --check` 对产出直接通过。
- 上传走 `gh` CLI（best-effort），不阻塞本地产物与 manifest；鉴权缺失时仅告警。
- `retain_releases` 按 `quant-platform-<key>-<version>.tar.gz` 的资源 key 分组，避免跨资源互相挤占保留名额。

**验收标准**
- 一键产出与线上格式一致的 assets + manifest；`fetch_resources.py --check` 对其通过。
- 重复运行幂等；旧版本保留数按资源可控。

**风险与缓解**
- 大文件上传失败。缓解：`gh` best-effort + 上传前先校验本地 sha256；失败不阻断归档与 manifest。

**工作量与依赖**：中；依赖 `tools/fetch_resources.py` 契约、GitHub 鉴权（仅 `--upload` 需要）。

---

### P3-3 数据质量测试（Data Quality Tests）

**问题陈述**
缺失 K 线、复权错误、ST/退市/停牌未显式处理——这些脏数据会直接污染信号，目前无专门测试守护。

**目标与成功指标**
- 建立数据质量测试套件，覆盖：交易日历缺口、复权单调性、重复日期、universe 排除规则（ST/退市/停牌）。
- 套件入 CI（与 P2-2 衔接）。

**范围**
- **含**：`tests/test_data_quality.py` 读 `repository`，断言上述不变量；阈值配置化。
- **不含**：数据修复（发现问题归数据管线修复，本项只检测）。

**方案与架构**
- `evaluation/data_quality.py`：`check_data_quality(repo, settings, as_of)` 只读 Repository，检测五类不变量并返回违规字典（空=通过）：
  ① `universe_exclusions`：可投资域(in_universe=TRUE)不含 ST / 已退市；② `duplicate_dates`：个股无重复 (code,date)；③ `nonpositive_price`：open/high/low/close > 0；④ `future_dates`：daily_bars 无晚于评估日的未来日期；⑤ `adjust_jump`：后复权价日收益 |ret| 超阈值（默认 0.3，可配置 `adjust.quality_jump_threshold`）视为异常跳变。
- `tests/test_data_quality.py`：内存 DuckDB 构建可控样本，注入坏行必红、干净数据通过；覆盖全部五类不变量。
- 入 CI：P2-2 的 `pytest` 步骤已覆盖（testpaths=tests），无需额外配置。

**关键设计**
- 规则（ST 判定、停牌阈值、跳变阈值）配置化，避免在测试里硬编码业务；`adjust_jump` 阈值走 `settings.adjust.quality_jump_threshold`。
- 仅检测不修复；发现问题归数据管线修复。交易日历连续性（依赖外部日历）暂未纳入，后续可加。

**验收标准**
- `tests/test_data_quality.py` 7 用例全绿（干净通过 + 各类坏行必红）。
- 注入缺失/重复/ST/负价/未来日/异常跳变样本 → 对应断言失败。

**风险与缓解**
- 交易所日历依赖。缓解：本版未依赖外部日历，仅做未来日 + 跳变检测，避免日历可用性风险。

> **状态**：✅ 已完成（commit 待提交）。含 `evaluation/data_quality.py`、`tests/test_data_quality.py`（7 用例）。全量测试 89 passed（已随 P2-2 CI 运行）。

**工作量与依赖**：中；与 P2-2 CI 衔接、与 P0-2 数据源交叉校验互补。

---

## 4. 评审要点与待确认问题（Open Questions）

请评审时确认以下取舍，将直接影响 PRD 落地：

1. **范围与顺序**：11 项全做，还是先选第一轮（建议 P0-1 + P0-2 + P1-3）？
2. **P1-1 预测源**：选 A（修）/ B（砍）/ C（换）？我倾向"先审计定生死，不达标即砍"，避免在无 alpha 处耗力。
3. **P2-3 告警通道**：微信（Server 酱/企业微信）/ 邮件 / Webhook，还是先只做通道接口+mock，通道后接？
4. **P0-1 若发现真实泄漏**：是否授权后续单列返工 PRD（可能涉及因子集重写）？
5. **CI 运行环境**：是否接受 CI 仅装核心+`czsc`、`torch/darts` 标 optional（与 README §7.2 一致）？
6. **文档归属**：本文档评审通过后是否提交进 `docs/`（当前未提交，等你确认）？

---

## 5. 附录：PRD 模板说明

每个优化项采用统一结构以便横向对比与评审：

| 小节 | 作用 |
|------|------|
| 问题陈述 | 为什么现在要做 |
| 目标与成功指标 | 做完怎样算成功（可度量） |
| 范围（含/不含） | 划清边界，防 scope creep |
| 方案与架构 | 架构级设计，不含最终代码 |
| 关键设计 | 最容易踩坑的决策点 |
| 验收标准 | 可测试的对账清单 |
| 风险与缓解 | 已知风险与对策 |
| 工作量与依赖 | 估算 + 前置项 |

> 本文档为**规划层**产出。评审通过后，就单项进入 架构细化 → 实现 → 测试，不在此文档内直接写实现代码。
