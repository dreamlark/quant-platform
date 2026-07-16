# 生产环境实跑审计（prod_audit_run）

> 目的：在沙箱内按**生产环境**真实跑一遍最终代码，验证 12 步盘后流水线端到端可用，
> 并产出可供审核的过程日志、运行产物与看板截图。
> 运行时间：2026-07-16 09:34 起（沙箱 UTC+8）。

## 1. 运行方式（生产入口）

按 README §9.1，**正式批处理入口 = `_run_real.py`**（沪深300 样本域 → `step_ingest` → `run_daily(TARGET)` 完整 12 步 → 写 `_today_prediction.md`）。

启动命令（后台常驻，日志落盘）：

```bash
cd /workspace/quant-platform
KRONOS_MODEL_REPO=NeoQuasar/Kronos-small \
KRONOS_N_EVAL_DATES=1 \
KRONOS_SKIP_DARTS=1 \
nohup python3.11 -u _run_real.py > prod_audit_run/prod_run.log 2>&1 &
```

### 环境关键决策（为何这样设）

| 变量 | 值 | 理由 |
|------|-----|------|
| `KRONOS_MODEL_REPO` | `NeoQuasar/Kronos-small` | **沙箱离线必需**。默认 base 在沙箱无外网取不到 hf-mirror 权重 → 静默降级成动量基线（README §10.3 明确警告的坑）。本地 `_local_kronos_weights/NeoQuasar--Kronos-small` 存在，设 small 才真跑 Kronos。 |
| `KRONOS_N_EVAL_DATES` | `1` | README §9.4 推荐的"快速出今日信号"生产路径：每只股票做 1 个历史评估时点估算方向准确率，预测步骤**完整执行**（非跳过）。 |
| `KRONOS_SKIP_DARTS` | `1` | Darts 在 A 股日收益近白噪声上塌缩为 0、训练慢，README §14 标注为"可跳过"；`_run_real_sandbox.py` 亦默认跳过。预测步骤仍跑 baseline + Kronos + QLib。 |

### 为何"新鲜重算"而非复用旧检查点

旧 `_kronos_eval_ckpt_kronos_e1_s0.json` 等检查点已挪到 `/tmp/ckpt_bak/`，强制本次做**真实** walk-forward 评估。
原因：检查点的 `target_rows` 绑定旧目标日；若直接复用，今天(2026-07-15 为库内最新交易日)的信号会接不到今天的 Kronos 预测 → 静默丢失第 4 源。
（已验证旧检查点来源可靠：其 `dir_acc≈0.632` 与 README"Kronos-small dir_acc≈0.632"一致，确为真实 small 跑；但为拿到"今天"的预测必须新鲜重算。）

## 2. 12 步流水线（README §4.1）

`step_ingest → step_universe → step_factors → step_sentiment → step_predict → step_health → step_neutralize → step_fusion → step_sector → step_market_sentiment → step_llm → step_backtest`

> 注：`_run_real.py` 内部 `run_daily` 将 `step_universe` 等 11 步串行编排（README 称 12 步含 `step_ingest`）。编排层无顶层 try，单步异常即中止（设计如此）。

## 3. 数据来源（真实）

- 行情：`akshare` 新浪财经日 K（`sources/akshare_adapter.py`），拉取截至今日，幂等 upsert 入 `market.duckdb`。
- 成分：沪深300（`akshare.index_stock_cons_csindex`，30s 超时 + `_hs300_cache.csv` 兜底）。
- 本次实跑 `step_ingest` 新入库 **58357 根**日 K（300 只 × 约 300 天）。

## 4. 产出物（审核用）

| 文件 | 说明 |
|------|------|
| `prod_audit_run/prod_run.log` | **完整过程日志**（逐步 INFO + Kronos 逐只评估进度）。 |
| `data/run_store.jsonl` | 编排层追加的运行记录（run_id / 状态 / 步骤 / 耗时 / 错误），监控层只读。 |
| `_today_prediction.md` | 今日信号报告（看多/看空/中性 + Top 个股四源贡献）。 |
| `data/market.duckdb` / `data/analytics.duckdb` | 行情库 / 分析库（因子/信号/板块/回测/情绪指数全部结果）。 |
| `prod_audit_run/screenshots/*.png` | 看板 5 页（Dashboard/Factors/Sectors/Stocks/Monitor）真实渲染截图。 |
| `_kronos_eval_ckpt_kronos_e1_s0.json`（新生成） | 本次真实 Kronos-small walk-forward 评估检查点（复算 dir_acc）。 |

## 5. 实时进度

- 09:34 启动；取沪深300 300 只；行业覆盖 269/300、市值 300/300。
- `step_ingest` 新入库 58357 根日 K。
- `run_daily(TARGET=2026-07-15)`：可投资域入选 300（无 ST/停牌剔除）；因子作用域 305 只；czsc 真实缠论已启用；Darts 跳过。
- `step_predict`：QLib 预测源逐周期训练（周期1 rf CV_dir_acc=0.528、周期5 et CV_dir_acc=0.560）；Kronos 300 只逐只 walk-forward 推理进行中（约 4.2 只/分钟，预计 ~11:00 完成全量评估）。
- 后续：`step_health → neutralize → fusion → sector → market_sentiment → llm → backtest`，随后写 `_today_prediction.md`。

## 6. 收尾动作（审计后）

- 新生成的 `_kronos_eval_ckpt_kronos_e1_s0.json` / `_kronos_eval_ckpt_qlib_e1_s0.json` 是本次审计**真实** walk-forward 产物（Kronos dir_acc≈0.621），作为 genuine 工件保留在仓库根目录（未跟踪）。
- `/tmp/ckpt_bak/` 中的旧检查点（`*_e15_s0` 及旧 `*_e1_s0`）为审计前快照，属被本审计 superseded 的陈旧工件，**不再移回仓库**（移回会重新引入过期检查点，且与本次 N=1 生产配置产生的 `e1_s0` 并存会混淆来源）。`/tmp` 备份保留作安全留底，不在 git 内。
- `_today_prediction.md` 为生产真实产出；审计后按需要 `git checkout` 恢复原样例。

---

## 7. 生产服务层审计（API + Web 看板，本轮新增）

流水线跑通后，按生产部署方式启动 FastAPI（`uvicorn api.main:app --port 8000`）+ vite 看板（`web/`，`:5173`），
对 5 个看板页做真实渲染截图。**截图暴露出 3 个生产级 bug，均已在审计中定位根因并修复。**

### 7.1 Bug A — API DuckDB 连接并发串扰（后端，已修复）

- **现象**：`/api/monitor/overview` 的 `models` 字段返回 `InvalidInputException: No open result set`；
  `/api/stocks/600519` 返回 `invalid date field format: "baseline_xsec_momentum"`（因子列名串进 DATE 列）。
- **根因**：`get_repository()` 是单例，`Repository` 只持一个 `market` + 一个 `analytics` **读写** DuckDB 连接；
  FastAPI 同步端点在**线程池**并发执行，SPA 的监控页并行打多个接口 → 多请求共用同一连接，
  DuckDB 单连接不支持并发结果集 → 游标串扰（`No open result set`）与列值错位（"baseline_xsec_momentum" 出现在日期列）。
- **修复**：`storage/duckdb_client.py` 给连接加 `threading.Lock`；`execute()` 在**锁内急切物化**结果
  （`fetchall` 成内存列表后立刻释放锁），返回内存 `_Result`（仅读内存，不再持有连接游标）。
  这样「执行 + 取数」整段原子、杜绝跨请求串扰；且即便调用方 `execute` 后不 `fetch` 再 `execute` 也**不死锁**
  （初版 `_LockedCursor` 方案因非可重入锁在此场景死锁，已在测试回归中发现并改为急切物化）。
  同时修掉 `table_exists`、watchlist `delete_watch` 中 `execute` 后不 `fetch` 的隐患；`repository.py` 的 `delete_watch` 改为 `.fetchall()`。
- **验证**：8 线程 × 200 次嵌套 execute 压测 0 错误；重启 API 后 30 并发请求 0 错误；
  `monitor/overview.models` 正常返回 qlib/baseline/kronos/darts 四个模型（"baseline_xsec_momentum" 正确作为模型名出现）。

### 7.2 Bug B — 运维监控页整页崩溃（前端，已修复）

- **现象**：访问 `/monitor`，`#root` 完全空白（截图仅 6.9K）。控制台：`Uncaught TypeError: Cannot read properties of undefined (reading 'replace')`，错误发生在 `<Cell2>`（运行记录表格单元格）。
- **根因**：`web/src/pages/Monitor.tsx` 的 `runColumns` 按旧手动运行 schema 渲染 `started_at`：`render: (v) => v.replace('T',' ')`。
  但 `/monitor/history` 把**两套 schema** 混在同一数组返回：手动运行（`started_at`/`duration_sec`/`target_date`/…）与
  批处理运行（`start_ts`/`duration_s`/`date`/`steps`，由 P3-1 `RunState` 写入）。batch 记录的 `started_at` 为 `undefined` → `.replace` 崩溃；
  React 18 无 error boundary，未捕获异常整树卸载 → 空白。
- **修复**：`runColumns` 改为兼容两套 schema（`started_at||start_ts`、`duration_sec??duration_s`、`target_date||date`、`progress??'-'` 等），防御性取值。
- **验证**：修复后 `/monitor` 正常渲染（含数据状态/因子健康/模型状态/管线/批处理/情绪/运行记录 7 张卡片），截图升至 122K。

### 7.3 Bug C — 个股页不支持深链（前端，已修复）

- **现象**：直接访问 `/stocks/600519`，`<main>` 空白（截图仅 30K），无报错。
- **根因**：`App.tsx` 仅有 `<Route path="/stocks">`，**无 `/stocks/:code` 路由**；`Stocks.tsx` 也未用 `useParams()` 读取 `:code`
  （`code` 状态初始为空，只能经搜索框 `onSelect` 设值）。直接访问个股 URL 不匹配任何路由 → 渲染空。
- **修复**：`Stocks.tsx` 增加 `useParams()`，`code` 初值取自 `paramCode || ''` 并以 `useEffect` 同步；
  `App.tsx` 增加 `<Route path="/stocks/:code" element={<Stocks />} />`。
- **验证**：修复后 `/stocks/600519` 正常渲染（方向/置信度/来源标签 + 四源贡献拆解 + K线 + 因子明细），截图升至 81K。

### 7.4 修复后看板截图（全部 5 页正常）

| 页面 | 修复前 | 修复后 | 状态 |
|------|--------|--------|------|
| Dashboard | 149K | 149K | 正常 |
| Factors | 101K | 101K | 正常 |
| Sectors | 131K | 131K | 正常 |
| Monitor | 6.9K（空白崩溃） | 122K | **已修复** |
| Stocks/600519 | 30K（路由空白） | 81K | **已修复** |

> 截图路径：`prod_audit_run/screenshots/{dashboard,factors,sectors,monitor,stocks_600519}.png`
> 改动文件：`storage/duckdb_client.py`、`storage/repository.py`、`web/src/pages/Monitor.tsx`、`web/src/pages/Stocks.tsx`、`web/src/App.tsx`（均未提交，待审核后 commit）。

### 7.5 测试回归

- 修复后运行 `pytest tests/ -q` 全量回归：**93 passed in 7.71s**（含 `test_data_quality`/`test_api`/`test_fe_constraints` 等）。
  初版锁方案曾使 `test_data_quality::test_duplicate_dates_detected` 死锁（execute 后不 fetch 又 execute），改为急切物化后消除。
- 并发压测：8 线程 × 200 次嵌套 execute，`monitor/overview` + `stocks/600519` 各并行 15 次，均 0 错误。
