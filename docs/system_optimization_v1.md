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
> 剩余工作仅为：真机验证 + 配置化 + 文档化 + 偏差日志结构化。

**问题陈述**
`step_ingest` 早期在沙箱里因网络受限临时降级为 akshare Sina 单源。单源既是单点故障，也是限流元凶
（你亲历的痛点）。数据源冗余在最初设计就已纳入（`a-stock-DB` 的 scale 方案），现需把这套
多源路由正式接回生产路径。

**目标与成功指标**
- ingest 走 `DataSourceRouter`，按优先级 `mootdx(1) → akshare(1) → baostock(4)` 回退；主源失败/超时自动降级。
- 单源挂死（如 `baostock.login` 阻塞）有超时护栏，不冻结整条流水线。
- 跨源 `close` 差异超阈值告警，并结构化记录供监控（衔接 P2-3）。

**范围**
- **含**：真机验证三源可达性；把 `source_timeout` / `diff_threshold` 配到 `config/settings.yaml`；
  跨源偏差写 `divergence_log`；README/架构文档更新"已采用多源冗余"。
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
- 真机（有外网/TDX 可达）跑一次 `run_daily`：三源中至少两源成功，日志可见回退与 `source` 标注。
- `config/settings.yaml` 含 `data_sources.timeout` / `diff_threshold`；改值后行为随之变化。
- 故意制造跨源差异 > 阈值 → `divergence_log` 出现记录（衔接 P2-3 告警）。

**风险与缓解**
- 沙箱无法验证 mootdx/baostock 真机可达性。缓解：**本项为"采用既有方案"，真机验证是验收动作而非开发**；
  真机若 mootdx 不可达，akshare 仍兜底，不影响生产。
- 不同源停牌/复权边界差异。缓解：统一不复权接口 + `_cross_check` 偏差告警。

**工作量与依赖**：低（核心已落地）；依赖一次真机验证与文档更新；`config/settings.yaml` 少量扩展。

---

### P1-1 预测源过弱（Weak Prediction Source）

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
- 静态护栏：lint 规则 / pre-commit hook 扫描 `api/**` 下的 `duckdb.connect` / 直接文件 IO，命中即红。
- 运行时护栏：FastAPI 响应中间件或 `BaseSchema` 在序列化前统一调用 `_sanitize_df`/`_sanitize_val`（复用已验证逻辑）。
- 错误统一：`ExceptionMiddleware` 兜底，避免 500 裸奔。

**关键设计**
- 复用现有 `_sanitize_val/_sanitize_df`（dashboard.py 已验证）上提到共享模块（如 `api/serializers.py`）。

**验收标准**
- `grep -rn "duckdb.connect" api/` 为零。
- 新增一个故意返回 inf 的端点测试 → 经中间件后返回 200 且字段为 null。
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
- **含**：GitHub Actions 工作流（lint ruff/flake8、pytest 单元+现有 3 测试、`fetch_resources --check` 对小型 fixture、可选 5 只股票烟雾跑 orchestrator）。
- **不含**：CD 部署、覆盖率门禁（先建基线，后续加）。

**方案与架构**
- `.github/workflows/ci.yml`：matrix python 3.11；venv 缓存；步骤 lint → test → resources-check → (smoke)。
- 小型 fixture：仓库内放一个迷你 duckdb/样例资源，供 `fetch_resources --check` 与烟雾跑使用，避免 CI 依赖外网/大文件。

**关键设计**
- 不依赖 GitHub Release 大资产（用 fixture），CI 自包含、快。
- 烟雾跑用 5 只股票的小宇宙，限制时长。

**验收标准**
- 提交含 lint 错误 → CI 红。
- 引入回归测试失败 → CI 红。
- 基线全绿且耗时可接受（< 10 min）。

**风险与缓解**
- 沙箱/CI 环境差异（czsc/darts 可选依赖）。缓解：CI 装核心+czsc，torch/darts 标 optional。

**工作量与依赖**：低-中；可与 P2-1 护栏规则共用配置。

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
- `common/notify.py`：通道接口 + 多实现；`api/routers/monitor.py` 的检查函数产出事件，事件经 `notify` 分发。
- 阈值（stale 小时数、`dir_acc` 下限、健康失败数）在 `config/settings.yaml`。
- 每日一次 digest，避免刷屏。

**关键设计**
- 通道可插拔、默认关闭（不配置不发），避免泄露到外部。
- 与 P3-1 调度落盘共享"运行事件"来源。

**验收标准**
- 模拟 stale → 对应通道收到通知（用 mock 通道验证）。
- 正常数据 → 无通知。
- 通道/阈值配置生效。

**风险与缓解**
- 误报骚扰。缓解：digest + 去抖 + 阈值保守默认。

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
- orchestrator 每步前后写 `run_log`（step, status, ts, error）。
- 部署单元：`quant-daily.service` + timer（或 cron），调用 `run_daily`。
- Monitor 新增"运行健康"卡：最近成功时间 + 逐步 OK/FAIL。

**关键设计**
- `run_log` 走现有 `repository.analytics`，不引入新存储。
- 失败步骤高亮，与 P2-3 告警联动。

**验收标准**
- 跑一次后 Monitor 显示时间戳 + 每步状态。
- 人为制造某步失败 → 该步标红且可被 P2-3 捕获。

**风险与缓解**
- DuckDB 单写者：调度写 `run_log` 与 API 读需错峰/复用单例。缓解：统一走 `repository` 单例。

**工作量与依赖**：低-中；依赖 P2-1 的边界治理（统一取数）。

---

### P3-2 MLOps 自动化（Resource Release Automation）

**问题陈述**
模型重训 → 打包资产 → 建 Release → bump manifest 全手动。随模型迭代频率上升，手动易错且不可复现。

**目标与成功指标**
- 一条命令完成：重训模型 → 打包 data/models 资产 → 建/更新 Release → 更新 `resources/manifest.json`（版本+sha256）→ 提交 manifest。
- 保留最近 N 个资源版本。

**范围**
- **含**：`tools/release_resources.py` 编排 tar+上传+manifest 更新；版本标签 `resources-YYYY-MM-DD`；保留策略。
- **不含**：模型训练算法本身（训练逻辑在各自模块）。

**方案与架构**
- 编排脚本：① 调用现有导出/重训产出 → ② `tar` 压缩 `data/`、`_local_kronos_weights/` → ③ `gh`/API 上传资产 → ④ 计算 sha256 写 manifest → ⑤ 提交 manifest。
- manifest 版本随日期递增；旧资产按保留数清理。

**关键设计**
- 复用 `tools/fetch_resources.py` 的 manifest 契约，保证上下行一致。
- 上传走已验证的鉴权 API 路径（私有仓库需 token）。

**验收标准**
- 一键产出与线上格式一致的 assets + manifest；`fetch_resources.py --check` 对其通过。
- 重复运行幂等；旧版本保留数可控。

**风险与缓解**
- 大文件上传失败。缓解：断点/重试 + 上传前先校验本地 sha256。

**工作量与依赖**：中；依赖 `tools/fetch_resources.py` 契约、GitHub 鉴权。

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
- 不变量：① universe 内无 ST/*、无已退市、无长期停牌（按 `config` 规则）；② 个股无重复 `date`；③ 交易日历连续性（对比交易所日历或相邻交易日）；④ 复权价相对前收的单调性/无跳变异常。
- 注入坏行 → 测试必红；干净数据 → 通过。

**关键设计**
- 规则（ST 判定、停牌阈值）配置化，避免在测试里硬编码业务。

**验收标准**
- 对当前 `data/` 跑通（反映真实质量）。
- 注入缺失/重复/ST 样本 → 对应断言失败。

**风险与缓解**
- 交易所日历依赖。缓解：用 akshare 交易日历或内置近似日历，允许配置。

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
