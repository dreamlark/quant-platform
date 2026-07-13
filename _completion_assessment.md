# 完成度评估与沙箱↔本地一致性审计

> 依据：`量化平台需求文档_PRD.md`、`量化平台架构选型设计文档.md`、`数据接入_a-stock-data选型决策.md`
> 审计对象：`/workspace/quant-platform` 实际代码
> 审计时间：2026-07-10

---

## 0. 先回答你的四个问题（结论在前）

1. **沙箱和真实环境跑的管线不一样吗？**
   - **代码层面：一致**。所有模块（T01–T12）都在，orchestrator 把 11 个 step 全串进了 `run_daily`，腾讯主源也实装了。
   - **但我之前的验证方式不一致**：我用了 **ad-hoc 脚本**（`_eval_kronos_shard.py` / `_kronos_predict_table.py` / `_run_real.py`）+ **静态快照**，绕过了 orchestrator 管线。这是「沙箱感觉不一样」的真正原因，不是架构没建。
   - **沙箱到不了主源是预期的**：架构文档 §8 待明确 #9 明写「mootdx TCP 7709 海外常超时」——沙箱是海外/云环境，主源（mootdx/Tencent）天然拉不到；本地（国内）能拉。所以 live fetch 在沙箱失败是文档已预见的行为，不是 bug。

2. **数据源是通达信+腾讯主源、akshare/baostock 冗余吗？**
   - **是的，且代码已实现**：`sources/mootdx_adapter.py` 内同时含 `MootdxAdapter`（通达信日 K 主源）与 `TencentRealtime`（腾讯 `qt.gtimg.cn`，补 PE/PB/市值/涨跌停等实时维度）；`akshare_adapter.py`、`baostock_adapter.py` 为冗余日 K 源。腾讯实时源只补实时维度、历史日 K 由 mootdx+akshare/baostock 承接，完全符合选型决策文档。

3. **按文档，系统完成度多少？**
   - **结构/代码存在度 ≈ 95%**（架构文件清单逐一对得上）。
   - **功能完成度 ≈ 85%**：核心差异化能力（Kronos 第 4 源）已实测通过（dir_acc=0.574，H1/H5/H10 全过质量门）；但**回测 Qlib/Backtrader 封装是占位**（`return None`，真实实现注释掉），Web/LLM 层结构在但未经功能验证。
   - 详见 §2 完成度矩阵。

4. **沙箱和本地要得到一样的验证结果，怎么做到？**
   - 必须做到三点（当前都缺）：① 验证走 **orchestrator 真实 step**，废止 ad-hoc 脚本；② 提交一份**固定验证数据集（snapshot）**，两端加载同一份输入；③ 控制 **Kronos 采样非确定性**（同源同参也会因 `T=1.0, top_p=0.9, sample_count=1` 而小幅波动）。方案见 §3。

---

## 1. 架构符合性（代码 ↔ 文档 对齐）

| 检查项 | 结果 |
|--------|------|
| 文件清单（T01–T12 全部文件） | ✅ 全部存在 |
| 腾讯主源 | ✅ `mootdx_adapter.py:123 class TencentRealtime`，走 `qt.gtimg.cn` |
| orchestrator 串联 | ✅ `run_daily` 调用 step_ingest/universe/factors/sentiment/predict/health/neutralize/fusion/sector/llm/backtest 共 11 步 |
| 异常 stub 扫描 | ✅ 仅 3 处 `NotImplementedError` 且均为 **P2 预留接口**（`llm/agent_interface`、`llm/factor_mining_if`、`fusion/push`），与文档「⏸ 仅接口不启用」一致 |
| 复权方法学（P0-1） | ✅ `daily_bars` 含 `adj_back_close`(计算)/`adj_front_close`(展示) 双列；`adjust.py` 实装 |
| 可投资域（P0-3） | ✅ `sources/universe.py` 实装（剔除 ST/次新/停牌，保留退市） |
| walk-forward 验证（P1-5） | ✅ `backtest/walk_forward.py`(259行) 实装，本次 Kronos 评估即用此法 |

> 结论：**系统是按最早确定的架构建立的**，结构与文档高度一致。问题不在「架构没落地」，而在「验证没走架构管道」+「沙箱网络到不了主源」。

---

## 2. 完成度矩阵（按 P0/P1/P2，实测）

| 任务 | 架构标记 | 实测 | 说明 |
|------|---------|------|------|
| T01 基础设施/配置 | ✅ | ✅ | config/*、storage/*、sources/base.py 在 |
| T02 多源接入 | ✅ | ✅ | mootdx(含腾讯实时)+akshare+baostock+adjust 在 |
| T03 因子引擎 | ✅ | ✅（czsc 缠论已真接入：单级别 CZSC 笔结构打分，2026-07-11 端到端验证通过；此前为占位 MA/RSI） | qlib_factors/czsc_signals/factor_calc 在 |
| T03b 量价情绪(第4源v1) | ✅ | ✅ | sentiment.py 在 |
| T03c 可投资域 | ✅ | ✅ | universe.py 在 |
| **T04 预测(Kronos第4源)** | ✅ | ✅ **已验证** | dir_acc=0.574，H1/H5/H10 全过质量门 |
| T05 体检+融合 | ✅ | ✅结构 | health_check/signal_pool/sector 在 |
| T05b 风险中性 | ✅ | ✅ | risk_neutral.py 在 |
| T06 LLM 简报/简评 | ✅ | ✅结构 / 未功能验证 | brief_gen/stock_review 在；agent_interface/factor_mining_if 正确占位 |
| **T07 回测(Qlib/Backtrader)** | ✅ | ✅ **真实（2026-07-11 补齐）** | qlib_backtest(全样本 IC 加权·仅做多) / bt_backtest(技术分多空) 已真实实现，与 walk_forward 构成三引擎交叉验证；`start_date` 对齐使测试窗口一致，落库 21 行（3 策略×7 指标） |
| T07b 成本模型+walk-forward | ✅ | ✅(walk_forward真实) | walk_forward.py(259行)+cost_model.py 真实 |
| T08 API 层 | ✅ | ✅ | main/schemas/5 路由 在；修复 `stocks/search` 误查 analytics 库（universe 在 market 库）|
| T09 Web 五页 | ✅ | ✅ **真实（2026-07-11 验证）** | `pnpm build` 编译通过；5 页均消费真实数据：Dashboard(10 信号/26 板块/温度)、Factors(12 因子体检)、Sectors(26 申万一级行业)、Stocks(搜索+详情+120 K线)、Watchlist(空，待用户加持仓) |
| T10 调度 | ✅ | ✅ | orchestrator(11 step)+jobs 在 |
| T11 自选股+信号拆解 | ✅ | ✅ | watchlist 路由 + Stocks.tsx 在 |
| T12 P2 预留 | ⏸ | ⏸ 正确 | push/agent_interface/factor_mining_if 正确 NotImplementedError |

**总体**：结构存在度 ≈ 95%；功能完成度 ≈ 95%（T07 回测、T09 看板均已补齐并验证；剩余 = LLM 简报/简评功能验证 + P2 预留接口 push/agent/factor-mining）。**核心壁垒 Kronos 第 4 源已实测通过**，回测三引擎交叉验证与五页看板均已真实可用。

---

## 3. 沙箱↔本地「一致验证」落地方案（无缝切换前提）

要让「沙箱测试 OK → 本地无缝切换」，必须满足**同源输入 + 同管道 + 可控随机**：

1. **废止 ad-hoc 脚本，验证走 orchestrator 真实 step**
   - 删除/归档 `_eval_kronos_shard.py`、`_kronos_predict_table.py`、`_run_real.py` 这类临时脚本。
   - 验证入口 = `Orchestrator.run_daily(date)` 或其单步组合（step_ingest→step_factors→step_predict→step_health→step_fusion→step_backtest），与本地完全一致。

2. **提交固定验证数据集（snapshot）**
   - 把 `data/market.duckdb` 在固定日期（如 2026-07-08）导出为 `data/verify_snapshot.duckdb` 并提交/固定存放。
   - 沙箱与本地都 **load 同一份 snapshot** → 输入字节级一致 → 计算结果一致。
   - 文档 §8 #9 已预见沙箱拉不到主源：沙箱验证用 snapshot；本地可用 live fetch（但验证必须用同一 snapshot 才可比）。

3. **控制 Kronos 采样非确定性**（当前最大隐患）
   - `kronos_adapter.predict` 用 `T=1.0, top_p=0.9, sample_count=1` → 同源同参每次 dir_acc 小幅波动（本次 0.574 是单次抽样）。
   - 修复：评估时 `sample_count≥N`（如 8）取平均，或固定随机种子；或在验证门上设**容差带**（如 dir_acc ∈ [0.52, 0.62] 即视为通过），两端都按同一带判定 → 「一致的通过/不通过」结论。

4. **文档化网络边界**
   - 在 README/运维说明写明：live fetch 需国内网络/代理（mootdx TCP 7709 海外超时）；CI/沙箱验证统一用 snapshot；本地生产用 live。

> 完成以上 4 点后，沙箱与本地跑同一份代码、同一份输入、同一套判定门槛，验证结论即可对齐，满足「沙箱 OK 即无缝切本地」。

---

## 4. 我之前的具体偏差（必须如实记录）

- 用 `_eval_kronos_shard.py` 等临时脚本直接读 `/tmp/market_snap.duckdb` 跑 Kronos 评估，**未经过 orchestrator**；评估逻辑（_eval_heavy）虽在 `factors/prediction.py` 内、与架构一致，但触发方式绕开了管线。
- 评估基于**静态快照**（截止 2026-07-08），未在跑前触发 `step_ingest`，且沙箱网络拉不到主源，故无法补 07-09——这是环境限制，不是架构缺陷。
- 评估中修掉的 3 个 Bug（逐周期评估日 / 全样本标签基准 / 平盘标签过滤）均在 `factors/prediction.py` 内修正，属架构内修复，无越界。

---

## 5. 建议下一步（按你拍板）

- **A**（推荐）：我按 §3 搭一套**可复现验证 harness**——固定 snapshot + orchestrator step 入口 + Kronos 容差门，先在沙箱跑通，你本地拉同一 snapshot 即得一致结论。
- **B**：先补 **T07 回测占位**（把 qlib_backtest/bt_backtest 真实实现接上 walk_forward/cost_model），让「回测验证」从占位变可用。
- **C**：仅输出本报告，不动代码，由你决定后续。

---

## 6. 本轮（2026-07-11）交付记录（Request G：回测 + 看板）

### 6.1 回测三引擎可比性对齐（T07 收尾）
- `backtest/qlib_backtest.py` / `backtest/bt_backtest.py` 新增 `start_date` 形参；`scheduler/orchestrator.py:step_backtest` 取 `walk_forward` 实际测试起点（`ret_df["date"].min()`）下传，三引擎统一覆盖 `2025-12-22 .. 2026-07-10`。
- 修复：`wf_start` 曾误用 `wf_rows["date"].min()`（该字段是 ret_df 最大日期），导致交叉验证引擎起点错配为 TARGET；改为 `ret_df["date"].min()`。
- 验证：三引擎各产出非空 ret_df，区间一致；`step_backtest` 落库 21 行（walk_forward_factor / qlib_factor_long / tech_long_short × 7 指标）。

### 6.2 看板功能验证 + 两处 bug 修复（T09）
- `web/` 前端 `pnpm install` + `pnpm build` 通过（修 2 处 antd v5 DatePicker onChange 类型：`string | string[]` → 取字符串）。
- 后端实跑 5 类接口，全部返回真实数据：
  - `/api/dashboard/summary`：10 信号 / 26 板块 / 市场温度 48
  - `/api/factors/health`：12 因子体检
  - `/api/sectors/rotation`：26 个真实申万一级行业（此前因 `sectors.yaml` 仅登记 20 只样例股，全部落入「其他」→ 仅 1 行）
  - `/api/stocks/search|/{code}|/{code}/bars`：搜索（代码+名称）、信号拆解（10 因子明细 + 9 预测明细）、120 根 K 线
  - `/api/watchlist`：空（待用户添加持仓）
- **修复 1**：`api/routers/stocks.py` 的 `search` 误用 `repo.analytics.read` 查 `universe` 表（universe 在 **market** 库）→ 改为 `repo.market.read`，搜索恢复。
- **修复 2**：`fusion/sector.py:analyze` 仅按 `sectors.yaml` 样例映射板块 → 新增 `industry_map` 参数（真实申万一级行业），`orchestrator.step_sector` 优先用 `stock_list.industry`、回退 `fetch_industry_map()`；已为 2026-07-10 重新生成 26 个真实行业板块。

### 6.3 Kronos 模型切换为 base（Request K：最强开源版）
- `factors/kronos_adapter.py`：默认模型由 `Kronos-small` 改为 **`Kronos-base`**（约 102MB，官方示例 `prediction_cn_markets_day.py` 同款）；分词器仍共用 `Kronos-Tokenizer-base`。
- **端点按尺寸自动分流**（关键）：small 走 Gitee AI（已验证绕过 xet CDN），base/mini/large 走 `hf-mirror.com`（Gitee 未镜像，会 404）。新增 `_default_model_endpoint(repo)`；`_resolve` 模型分支改用之。
- **可配置化**：优先级 `KRONOS_MODEL_REPO` 环境变量 > `settings.yaml` 的 `kronos.model_repo` > 类默认 base；`factors/prediction.py` 读取 settings 传入 `KronosAdapter(model_repo=...)`。`config/settings.yaml` 新增 `kronos.model_repo: "NeoQuasar/Kronos-base"`。
- **日志修正**：提前解析端点再打印，日志显示真实下载端点（base→hf-mirror），不再误显示 Gitee；线程内不再重复解析、去掉全局 env 改动的隐患。
- **离线搬运脚本同步**：`download_kronos_weights.py` 默认 `--repo` 改 base（hf-mirror）；`bootstrap_kronos.sh` 默认下载 base，受限网络仅 Gitee 可达时回退 small 并自动 `export KRONOS_MODEL_REPO=small`；`fetch_kronos_weights.py` 明确为 small 专用回退；`KRONOS_WEIGHTS_GUIDE.md` 全量更新（base 默认、尺寸-端点表、base 离线命令）。
- **验证**：单元回归 `tests/test_kronos_adapter.py` 全 PASS；`_default_model_endpoint` 对 small/base/mini/large 端点断言通过；base+stub 端到端接线 + 端点透传通过。沙箱内因 hf-mirror/HF 官方被网络策略拦截，base 会**优雅降级 baseline**（预期行为，不崩溃）；本地完整外网可正常拉取 base。

### 6.4 自动更新 + Web 控制（Request P：断点续跑 + 运维按钮）
- **问题**：原管线 `scheduler/orchestrator.py:run_daily` 是裸顺序 step 链，**无错误处理、无重试、无状态机**；前端 5 页全是纯展示，**没有任何触发更新的按钮**，后端也**无任何控制端点**（除 watchlist 增删）。
- **新增后端控制面** `api/routers/admin.py`（前缀 `/api/admin`，与既有路由一致）：
  - `UpdateManager`：① 后台**守护线程**异步跑更新，不阻塞 API；② 每步**失败自动重试 3 次**（指数退避 3/6/9s），整轮仍失败置 `failed`；③ **断点续跑**——各 step 幂等 upsert，重跑从断点补完（已落库数据不丢、不重复拉源），前端提示「可再次点击立即更新从断点续跑」；④ 状态机 `idle/running/success/failed` + 进度 `progress/total`。
  - `_build_orch()` 复用 `_run_real.py` 的**沪深300域 + akshare 主源**逻辑（`index_stock_cons_csindex`，失败兜底 `universe` 表）；先 `step_ingest` 拉最新日K，再据 `max(date)` 定目标日并置 `orch.source=None`，后续步骤不再重复 ingest。
  - **Web 可控自动运行**：API 进程内嵌 `BackgroundScheduler`（非 Blocking，不卡 API），cron 取自 `settings.yaml`（`scheduler.cron` 默认 `"30 18 * * 1-5"`，工作日 18:30，Asia/Shanghai），由 Web 开关启停；`next_run` 经 `job.next_run_time` 计算。
  - 端点：`POST /api/admin/update`（运行中返回 409）、`GET /api/admin/status`、`POST /api/admin/auto/start`、`POST /api/admin/auto/stop`。
- **接线**：`api/main.py` 新增 `from api.routers import admin` 并 `app.include_router(admin.router)`。
- **前端适配** `web/src/api/client.ts` + `web/src/pages/Dashboard.tsx`：
  - `client.ts` 新增 `UpdateStatus` 接口与 `triggerUpdate / getUpdateStatus / startAuto / stopAuto` 四个调用。
  - `Dashboard.tsx` 顶部新增**运维控制卡片**：「立即更新」按钮（POST 后轮询状态）、「自动运行」Switch（POST start/stop 切换）、状态 Tag + `Progress`（steps=11）进度条、当前步骤/最近成功目标日/失败原因 Alert、操作后提示。更新中每 2s 轮询 `/api/admin/status`，结束自动停。
- **验证**：① 后端 `py_compile` 通过；② 前端 `tsc && vite build` 通过（TS 校验新增类型与调用无误）；③ 进程内验证——4 个 `/api/admin/*` 路由均注册成功，`start_auto/stop_auto` 逻辑正确（`next_run` 算到下一个工作日 `2026-07-14T18:30:00+08:00`）。
- **使用提示**：自动运行依赖 API 进程常驻（每次重启 `auto_enabled` 归位 False，需在 Web 上重新开启）。本地 Windows 部署见 `deploy_windows.bat`；手动单次跑见 `run_daily.bat`。

### 6.5 运维监控层（Request：数据状态 / 健康度 / 模型状态 / 管线进度 + 运行记录）
- **动机**：Request P 把更新改成后台异步跑后，缺少可见性——数据是否过期、Kronos 预测是否静默失败、自动运行凌晨失败为何，都无从得知。监控层 = 只读观测 + 运行历史持久化。
- **新增后端**：
  - `api/run_store.py`：运行历史 JSONL 追加写（`data/run_history.jsonl`）。选 JSONL 而非 DuckDB 表，避免与更新写者争单写锁；线程安全（锁保护）。
  - `api/routers/monitor.py`（前缀 `/api/monitor`）：`MonitorService` 跨两库**只读**聚合——
    - `data`：行情库 `daily_bars` 最新交易日 / 距今天数 / 是否过期（>4 天启发式）/ 股票数 / 可投资域数。
    - `factors`：分析库 `factor_health` 按状态（有效/衰减/失效）分布 + 平均 ICIR。
    - `models`：分析库 `predict_health`（含 Kronos）逐模型最新日 dir_acc / `predict_values` 覆盖率 / 日期。
    - `freshness`：`signals`/`sector_rotation`/`daily_brief` 最新日。
    - `pipeline`：直接引用 `admin.mgr.state`（实时跑到哪一步）。`last_run` + `history_count` 来自 JSONL。
    - 端点：`GET /api/monitor/overview`（一次拉全）、`GET /api/monitor/history`。
    - 每分块独立 try/except 降级（单库不可达仅该分块报 error，不影响其他）。
  - `api/routers/admin.py` 扩展：`UpdateManager` 每次运行生成 `run_id`，`_worker` 结束后落一条历史（触发源 manual/auto、起止、耗时、状态、目标日、到达步骤、进度、错误）；自动调度触发源标 `auto`。
- **前端**：新增 `web/src/pages/Monitor.tsx`（菜单「运维监控」+ 路由 `/monitor`）：
  - 数据状态卡、因子健康卡、模型状态表（高亮 Kronos）、管线运行实时卡（复用 Progress steps + 状态 Tag）、其他数据新鲜度、运行记录表（时间/触发/状态/目标日/到达步骤/进度/耗时/错误）。
  - 轮询：`overview` 每 4s、`history` 每 8s（观测层轻量只读）。
- **接线**：`api/main.py` 注册 `monitor.router`；`client.ts` 新增 `MonitorOverview/RunRecord/...` 接口与 `getMonitorOverview/getMonitorHistory`。
- **验证**：① 后端 `py_compile` 通过；② 前端 `tsc && vite build` 通过；③ 进程内实跑 `monitor.overview()` 返回真实数据（data=2026-07-10/新鲜/300 股；factors=12 因子 失效3·有效3·衰减6/avg_icir 0.1205；models kronos 0.632/覆盖300、qlib 0.416、baseline 0.512、darts 0.0；freshness 全 2026-07-10）；`append_run`+`load_runs` 联动正确；两路由注册成功。测试用历史记录已清理。
