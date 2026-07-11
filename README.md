# A 股日频量化分析平台（quant-platform）

> **analysis-first（只分析、不交易）** · A 股 · 日频 / 中低频 · 收盘后批处理。
> 融合 **因子 + 技术 + 情绪 + 预测** 四源信号，产出中文市场分析、信号清单与可解释个股/板块/因子洞察。

## 方法学红线（已落地）

| 红线 | 实现 |
|------|------|
| **后复权计算**（P0-1） | 因子/回测只读 `adj_back_close`；`adj_front_close` 仅前端展示，严禁入计算（`sources/adjust.py`） |
| **可投资域**（P0-3） | `sources/universe.py` 剔除 ST/*ST、次新<60日、长期停牌；保留已退市样本，消除生存偏差 |
| **研究观点非建议**（P2-4） | LLM 输出定位"分析信号/研究观点"，置信度取自信号层；全站挂固定免责声明 |
| **walk-forward**（P1-2/3） | `backtest/walk_forward.py` 滚动样本外 + 中证全指/沪深300 基准 + Deflated Sharpe |
| **情绪第4源**（P0-2） | `factors/sentiment.py` 量价代理情绪（零额外源） |
| **风险中性化**（P1-4） | `factors/risk_neutral.py` 行业/市值回归残差法，融合前执行 |
| **A股回测制度**（P1-1） | `backtest/cost_model.py` 佣金万2.5/印花税千1/滑点/T+1/涨跌停流动性约束 |

## 快速开始

```bash
# 1) 安装必装依赖（重型可选依赖见 [ml]/[factors]/[backtest]）
pip install -e .            # 或 pip install -r requirements.txt

# 2) 配置密钥（可选；不配则 LLM 离线降级，核心链路仍可跑）
cp .env.example .env && vim .env   # 填入 DEEPSEEK_API_KEY

# 3) 冒烟测试（构造内存假数据，跑通 ingest→...→signals 落 DuckDB）
python tests/test_smoke.py

# 4) 启动后端 API
uvicorn api.main:app --port 8000 --reload

# 5) 启动前端（另开终端）
cd web && npm install && npm run dev   # http://localhost:5173
```

## 任务映射（T01–T12）

`T01` 基础设施/配置 · `T02` 多源接入/复权 · `T03c` 可投资域 · `T03` 因子计算 ·
`T03b` 情绪 · `T04` 预测(Kronos/Darts 懒加载+baseline) · `T05` 体检/四源融合 ·
`T05b` 中性化 · `T06` LLM 洞察 · `T07` 回测 · `T07b` 成本模型/walk-forward ·
`T08` 后端 API · `T09` Web 前端 · `T10` 调度 · `T11` 自选股记账/信号拆解 · `T12` 预留接口。

## 懒加载降级

`qlib` / `czsc` / `kronos` / `darts` / `backtrader` / `quantstats` / `alphalens` 等重型依赖
**仅在对应模块内 try/except 懒加载**，未安装时自动降级（pandas 回退 / baseline / 跳过），
不影响核心流水线。沙箱默认未装重型包，冒烟测试仍可通过。

## 目录结构

见架构文档 §2（严格对齐）。关键模块：`sources/`（接入/复权/可投资域）、`factors/`（因子/情绪/预测/中性化）、
`fusion/`（融合/板块）、`evaluation/`（体检）、`backtest/`（回测/walk-forward）、`llm/`（洞察）、
`storage/`（DuckDB）、`api/`（FastAPI）、`web/`（React 暗色看板）、`scheduler/`（编排）。

---

## 部署（本地电脑）

> 代码层面**可直接迁本地**，与沙箱同一套代码、无架构差异。真正的「无缝」取决于三点：
> ① 带走数据 `data/`（DuckDB 文件可移植）或本地拉取；② 装齐核心依赖（**含 czsc**）；
> ③ 遵守 **DuckDB 单写者**约束（见 §6 坑）。

### 1. 硬件要求（按样本域规模）

| 资源 | 沪深300（已验证） | 全 A 股（5000+，需改样本域） |
|------|------|------|
| 内存 | 2–4 GB | 8–16 GB |
| CPU | 近 5 年多核 x86 / Apple Silicon | 同左（多核助数据拉取） |
| 磁盘 | 几 GB | 数十 GB |
| GPU | **不需要** | 不需要（见 §5 GPU 说明） |
| 网络 | 拉数据(akshare)+LLM(DeepSeek) 需联网；纯离线需预置 `data/` | 同左 |
| Python | 3.11 / 3.12 | 同左 |
| Node | 22.x（仅前端） | 同左 |

内存随**样本域规模**线性放大，非固定值。

### 2. 最短路径：复制代码 + 数据（推荐）

```bash
# 代码
git clone <你的仓库> quant-platform
cd quant-platform

# 数据（DuckDB 文件直接拷，最稳；也可用 _run_real.py 本地拉）
cp -r <沙箱>/quant-platform/data ./data

# 依赖（见 §3）
pip install -r requirements.txt
pip install czsc                 # ⚠️ 必装，否则缠论退化为占位 MA/RSI

# 密钥（不填则简报/简评跳过，信号照常出）
cp .env.example .env
#   编辑 .env 填 DEEPSEEK_API_KEY=

# 跑起来（见 §4）
```

### 3. 依赖安装（Windows / macOS / Linux 通用）

**A. venv（通用）**
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
pip install -r requirements.txt
pip install czsc
# 可选：要预测第4源(darts)再装；会顺带拉 torch（较大）
pip install darts
```

**B. conda（替代 venv，推荐数据科学用户）**
```bash
conda create -n quant python=3.11 -y
conda activate quant
pip install -r requirements.txt      # 或：pip install -e .
pip install czsc
# 可选
pip install darts
```
> conda 环境里 `pip` 直接可用；不要用 `conda install` 装这些（版本线以 pyproject 为准）。

**依赖分层（装多少自己定）**

| 层 | 包含 | 不装会怎样 |
|----|------|-----------|
| 必装核心 | duckdb/pandas/scipy/statsmodels/sklearn/fastapi/uvicorn/openai/loguru + akshare | — |
| 因子/缠论 | **czsc**（必装） | 漏装→缠论信号变假（占位 MA/RSI） |
| 预测[ml] | darts + torch | 仅失「预测第4源」；因子/技术/情绪/回测全不受影响 |
| 回测[backtest] | backtrader/quantstats | **不需要**——回测已用 pandas/scipy 自包含实现替代 |
| 因子[qlib] | qlib | 不需要——qlib 因子走 pandas 兜底 |

> 结论：最小可用 = 核心 + czsc。torch/darts 是「预测第4源」的可选项，非必需。

### 4. 启动

```bash
# 后端（另开终端，常驻）
uvicorn api.main:app --port 8000 --reload

# 前端（另开终端）
cd web
pnpm install          # 首次
pnpm dev              # 开发：http://localhost:5173
# 或生产构建后静态托管：
pnpm build && pnpm preview
```
浏览器开 `http://localhost:5173` → 5 页实时读 API。前端 `vite` 已配置 `/api` 代理到 `localhost:8000`。

### 5. GPU 说明（重要，别被误导）

**本平台 90% 的计算（因子 / czsc 缠论 / walk-forward / 回测 / 融合 / API / 看板）是纯 pandas+numpy+scipy，完全不吃 GPU，有没有卡都一样快。**

仅「预测第4源」碰 torch：
- **darts**：模型在本地 `fit`（训练）且 `predict`（推理），底层用 torch。但当前代码**未指定 device**，默认跑 CPU——即使装了 CUDA 版 torch 也不会自动用卡。要真用 GPU，需在 `factors/darts_adapter.py` 的 darts 模型加 `pl_trainer_kwargs={"accelerator":"gpu","devices":1}`（小改动）。
- **qlib**：本地 `fit` 用的是 CPU 学习器（lightgbm/xgboost/线性），不吃 GPU。
- **Kronos**：走 vendor 的官方 Kronos 包（自回归解码），当前未绑 device，CPU 推理。

**结论**：普通部署**不需要 GPU**。只有当（a）你启用 darts 预测、（b）样本域放大到全 A 股或加多采样、（c）且手动把 darts trainer 指到 GPU 时，GPU 才对「预测模型训练/推理」有边际加速；对核心流水线零加速。

### 6. 日常使用与维护

| 事项 | 做法 |
|------|------|
| 每日刷新 | 盘后跑 `python _run_real.py`（拉新 K → 因子 → 融合 → 回测全链路）；或设 `.env` 中 `SCHEDULER_ENABLED=true` 走 APScheduler（默认 cron `30 18 * * 1-5`，周一至周五 18:30） |
| 看板日常 | 浏览器开 `localhost:5173`，5 页实时读 API |
| 加自选股 | 看板「自选股」页 → 添加持仓（落 `watchlist` 表，自动算盈亏） |
| 数据备份 | 定期备份 `data/market.duckdb` + `data/analytics.duckdb`，即全部状态 |
| 监控 | 看 uvicorn 日志；akshare 偶有限流/超时属正常，次日补拉即可 |

**必须注意的坑**
1. **DuckDB 单写者锁**：同一份 `*.duckdb` 不要同时跑多个写入进程。API 常驻只读为主，但「添加自选股」会写；调度 ingest 也会写。建议每日刷新作为**独立一次性进程**跑完即退，不要和常驻 API 24h 重叠写同一文件。
2. **czsc 必装**（见 §3），漏装静默退化。
3. **LLM key 缺失不报错但简报为空**：Dashboard 显示「简报未生成（无 LLM 密钥）」，预期降级，非 bug。
4. **analysis-only 不交易**：整套是 research 信号，无任何下单/券商接口。

### 7. 全 A 股模式（扩样本域）资源配置

当前 `_run_real.py` 默认沪深300。要接全 A 股：
- 改 `stock_list` 来源为全市场代码（如你的 `D:\DMYY\stock-db` 导出），传给 `Orchestrator(stock_list=...)`；
- 内存按 8–16 GB 规划（czsc 逐只建笔 + 回测全样本 + factor_values 长表膨胀）；
- `analytics.duckdb` 会显著变大（因子值长表 × 全市场 × 历史），预留数十 GB 磁盘；
- 数据拉取耗时随标的数放大，建议增量 ingest（模块已支持 `step_ingest` 断点续跑）；
- 单机 CPU 串行回测对 5000 只可能较慢，可考虑分批或只跑 walk-forward 主口径。
