# A 股日频量化分析平台（quant-platform）

> **analysis-first（只分析、不交易）** · A 股 · 日频 / 中低频 · 收盘后批处理。
> 融合 **因子 + 技术 + 情绪 + 预测** 四源信号，产出中文市场分析、信号清单与可解释个股 / 板块 / 因子洞察。

---

## 目录

1. [项目定位](#1-项目定位)
2. [核心特性](#2-核心特性)
3. [方法学红线（已落地）](#3-方法学红线已落地)
4. [系统架构](#4-系统架构)
5. [目录结构](#5-目录结构)
6. [环境要求](#6-环境要求)
7. [安装与部署](#7-安装与部署)
8. [配置说明（.env 与 Kronos 环境变量）](#8-配置说明env-与-kronos-环境变量)
9. [数据更新与每日预测](#9-数据更新与每日预测)
10. [Kronos 预测模型详解](#10-kronos-预测模型详解)
11. [运维监控层（新增）](#11-运维监控层新增)
12. [Web 看板页面说明](#12-web-看板页面说明)
13. [API 端点完整列表](#13-api-端点完整列表)
14. [已知限制与降级项](#14-已知限制与降级项)
15. [故障排查 FAQ](#15-故障排查-faq)
16. [开发指南](#16-开发指南)
17. [安全与免责声明](#17-安全与免责声明)

---

## 1. 项目定位

本平台是一个**研究型**量化分析系统，**明确不交易、不下单、不接券商**。它把多维度信号汇聚成"研究观点"，用于辅助你自己的投资决策，而非自动执行。

设计目标：

- **分析优先（analysis-first）**：先解决"看清楚市场"，再谈别的。信号是观点，不是指令。
- **可解释**：每个信号都拆解成「因子 / 技术 / 情绪 / 预测」四部分贡献，能说清"为什么看多 / 看空"。
- **无前视偏差**：价格计算统一走后复权；标签 point-in-time；回测 walk-forward 样本外。
- **离线可跑**：核心链路零密钥可跑；重型模型（Kronos 等）缺失时优雅降级，不崩。
- **模块化**：数据 / 因子 / 融合 / 回测 / LLM / 前端各自解耦，便于扩展样本域或替换模型。

典型用法：盘后跑一次 `_run_real.py` → 看板查看当日信号 / 板块轮动 / 因子健康 → 结合自己的判断做研究。

---

## 2. 核心特性

| 特性 | 说明 |
|------|------|
| **四源信号融合** | 因子（基本面/量价 Alpha） + 技术（缠论 czsc） + 情绪（量价代理） + 预测（Kronos 时序基础模型） |
| **可投资域约束** | 自动剔除 ST/*ST、次新（<60 日）、长期停牌；保留已退市样本消除生存偏差 |
| **行业 / 市值中性化** | 融合前对因子做回归残差中性化，去除单一风格暴露 |
| **walk-forward 回测** | 滚动样本外 + 基准对照（沪深300 / 中证全指） + Deflated Sharpe，无未来函数 |
| **Kronos 真实预测** | 金融 K 线基础模型（NeoQuasar/Kronos）离线/在线推理，权重由 walk-forward 方向准确率驱动 |
| **运维监控层（新增）** | 数据状态 / 因子健康 / 模型状态 / 管线进度 / 运行历史的实时看板 + Web 一键触发更新 |
| **中文暗色看板** | React + antd v5 + ECharts，6 个页面实时读 API |
| **DuckDB 存储** | 单文件列式库，查询快、可移植（直接拷文件即备份） |

---

## 3. 方法学红线（已落地）

| 红线 | 实现 |
|------|------|
| **后复权计算**（P0-1） | 因子 / 回测只读 `adj_back_close`；`adj_front_close` 仅前端展示，严禁入计算（`sources/adjust.py`） |
| **可投资域**（P0-3） | `sources/universe.py` 剔除 ST/*ST、次新<60 日、长期停牌；保留已退市样本，消除生存偏差 |
| **研究观点非建议**（P2-4） | LLM 输出定位"分析信号 / 研究观点"，置信度取自信号层；全站挂固定免责声明 |
| **walk-forward**（P1-2/3） | `backtest/walk_forward.py` 滚动样本外 + 中证全指 / 沪深300 基准 + Deflated Sharpe |
| **情绪第 4 源**（P0-2） | `factors/sentiment.py` 量价代理情绪（零额外源） |
| **风险中性化**（P1-4） | `factors/risk_neutral.py` 行业 / 市值回归残差法，融合前执行 |
| **A 股回测制度**（P1-1） | `backtest/cost_model.py` 佣金万 2.5 / 印花税千 1 / 滑点 / T+1 / 涨跌停流动性约束 |

---

## 4. 系统架构

### 4.1 数据流（盘后批处理）

```
                ┌─────────────┐
   行情源 akshare ─▶│ step_ingest │── 复权 + 幂等 upsert ──▶ market.duckdb (日K + universe)
                └─────────────┘                                      │
                                                                     ▼
   universe 过滤 ─▶ factors ─▶ sentiment ─▶ predict(Kronos) ─▶ health ─▶ neutralize
   (ST/停牌剔除)   (因子+缠论)  (量价情绪)  (时序模型)      (IC/ICIR)   (行业/市值残差)
                                                                     │
                                                                     ▼
                                          fusion/signal_pool ── 四源加权融合 ──▶ signals
                                                                     │
                        ┌────────────────────────────────────────────┘
                        ▼                      ▼                    ▼
                  sector(板块轮动)      llm(简报/简评)        backtest(walk-forward)
                        │                      │                    │
                        └──────────────────────┴────────────────────┘
                                       ▼
                              analytics.duckdb (全部结果)
                                       ▼
                              FastAPI ──▶ React 暗色看板 (/dashboard /factors /sectors
                                          /stocks /watchlist /monitor)
```

### 4.2 四源信号融合权重

`fusion/signal_pool.py` 默认融合权重（可在 `settings` 调）：

| 信号源 | 默认权重 | 说明 |
|--------|---------|------|
| 因子（factor） | 0.40 | 量价 / 基本面 Alpha 因子 |
| 技术（tech） | 0.20 | czsc 缠论笔段信号 |
| 情绪（sentiment） | 0.15 | 量价代理情绪 |
| 预测（predict） | 0.25 | Kronos 等时序模型；模型内部再按 walk-forward 方向准确率细分权重 |

> 预测源内部权重：每个模型由历史 walk-forward 方向准确率（`predict_health.dir_acc`）决定其占「预测分支」的比重。dir_acc ≤ 0.5（近随机）的模型自动降权到 0。在最新实跑中，Kronos-small 的 dir_acc≈0.632 是唯一拿到正权重的预测源。

### 4.3 分层

```
┌─────────────────────────────────────────────┐
│  Web (React + antd + ECharts)                 │  展示层
├─────────────────────────────────────────────┤
│  API (FastAPI)  api/routers/*                 │  接口层（读 DuckDB，单写者约束）
├─────────────────────────────────────────────┤
│  Scheduler (orchestrator.run_daily)           │  编排层（盘后批处理）
├─────────────────────────────────────────────┤
│  factors / fusion / evaluation / backtest /   │  计算层（信号/融合/回测）
│  llm / sources / storage                       │
└─────────────────────────────────────────────┘
```

---

## 5. 目录结构

```
quant-platform/
├── _run_real.py              # ★ 正式入口：沪深300 样本域 + 真实数据 → 今日信号报告
├── api/
│   ├── main.py               # FastAPI 应用，挂载全部 router
│   ├── run_store.py          # 运行历史 JSONL 读写（避免 DuckDB 单写者冲突）
│   └── routers/
│       ├── admin.py          # 运维控制：触发更新 / 自动运行开关 / 进度（UpdateManager）
│       ├── monitor.py        # 运维监控：跨库只读聚合（数据/因子/模型/管线状态）
│       ├── dashboard.py      # 看板汇总
│       ├── factors.py        # 因子健康 / 因子值
│       ├── sectors.py        # 板块轮动
│       ├── stocks.py         # 个股详情 / K线 / 简评 / 搜索
│       └── watchlist.py      # 自选股记账
├── common/                   # config 加载、统计工具
├── config/                   # settings 默认配置
├── evaluation/               # 因子体检（IC / ICIR / 衰减）
├── factors/
│   ├── factor_calc.py        # 因子 + 技术分计算（含 czsc 缠论）
│   ├── qlib_factors.py       # qlib 因子（缺失时 pandas 兜底）
│   ├── kronos_adapter.py     # Kronos 适配（离线/在线权重、端点分流）
│   ├── darts_adapter.py      # Darts 预测适配（可选）
│   ├── qlib_predict_adapter.py # qlib 预测适配（缺失时 pandas+xgboost 兜底）
│   ├── prediction.py         # 预测编排 + walk-forward 评估 + 检查点续跑
│   ├── risk_neutral.py       # 行业 / 市值中性化
│   ├── sentiment.py          # 量价代理情绪
│   └── czsc_signals.py       # 缠论信号（依赖 czsc）
├── fusion/
│   ├── signal_pool.py        # 四源加权融合 → signals
│   └── sector.py             # 板块轮动 / 强弱
├── llm/
│   ├── client.py             # DeepSeek 客户端（无 key 离线降级）
│   ├── brief_gen.py          # 市场简报生成
│   └── stock_review.py       # 自选股逐只简评
├── backtest/
│   ├── walk_forward.py       # walk-forward 主口径（pandas/scipy 自包含）
│   ├── cost_model.py         # A 股成本模型（佣金/印花税/滑点/T+1）
│   ├── report.py             # 绩效报告（quantstats 懒加载）
│   ├── qlib_backtest.py      # qlib 交叉验证（可选）
│   └── bt_backtest.py        # backtrader 交叉验证（可选）
├── scheduler/
│   └── orchestrator.py       # ★ 每日盘后编排（11 步流水线）
├── sources/
│   ├── akshare_adapter.py    # akshare 新浪财经日 K 适配器（本环境唯一可用源）
│   ├── base.py               # 数据源基类 / 路由
│   ├── market_meta.py        # 行业 / 市值元数据
│   ├── adjust.py             # 复权计算（后复权锚定最早）
│   └── universe.py           # 可投资域过滤
├── storage/
│   └── repository.py         # DuckDB 仓储（读写封装）
├── web/                      # React 前端（详见 §12）
│   └── src/
│       ├── api/client.ts     # API 客户端
│       ├── App.tsx           # 路由
│       └── pages/            # Dashboard / Factors / Sectors / Stocks / Watchlist / Monitor
├── _vendor/Kronos/           # Kronos 官方推理代码（vendor，预测必需）
├── _local_kronos_weights/    # Kronos 离线权重（small + Tokenizer-base）★ gitignore
├── data/                     # DuckDB + 运行缓存 ★ gitignore（可重跑生成）
├── deploy_windows.bat        # Windows 一键部署（建 .venv + 装依赖）
├── run_daily.bat             # Windows 每日运行包装
├── requirements.txt          # Python 依赖
├── pyproject.toml            # 项目元数据
├── .env.example              # 环境变量样例
└── README.md
```

---

## 6. 环境要求

| 资源 | 沪深300（已验证） | 全 A 股（5000+，需扩样本域） |
|------|------|------|
| 内存 | 2–4 GB | 8–16 GB |
| CPU | 近 5 年多核 x86 / Apple Silicon | 同左（多核助数据拉取） |
| 磁盘 | 几 GB | 数十 GB |
| GPU | **不需要** | 不需要（见 §7.5 GPU 说明） |
| 网络 | 拉数据（akshare）+ LLM（DeepSeek）需联网；纯离线需预置 `data/` | 同左 |
| Python | 3.11 / 3.12 | 同左 |
| Node | 22.x（仅前端） | 同左 |

内存随**样本域规模**线性放大，非固定值。

---

## 7. 安装与部署

> 代码层面**可直接迁本地**，与沙箱同一套代码、无架构差异。真正的「无缝」取决于三点：
> ① 带走数据 `data/`（DuckDB 文件可移植）或本地拉取；② 装齐核心依赖（**含 czsc**）；
> ③ 遵守 **DuckDB 单写者**约束（见 §15 FAQ）。

### 7.1 获取代码

```bash
git clone https://github.com/dreamlark/quant-platform.git
cd quant-platform
```

> 仓库不含 110M 的 Kronos 权重（已 gitignore）。预测能力补回方式见 §10.4。

### 7.2 依赖安装（二选一）

**A. conda（推荐数据科学用户）**

```bash
conda create -n quant python=3.11 -y
conda activate quant
pip install -r requirements.txt      # 或 pip install -e .
pip install czsc                      # ⚠️ 必装，否则缠论退化为占位 MA/RSI
# 可选：要预测第 4 源（darts）再装，会顺带拉 torch（较大）
pip install darts
```
> conda 环境里 `pip` 直接可用；不要用 `conda install` 装这些（版本线以 pyproject 为准）。

**B. venv（通用）**

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
pip install -r requirements.txt
pip install czsc
# 可选
pip install darts
```

**依赖分层（装多少自己定）**

| 层 | 包含 | 不装会怎样 |
|----|------|-----------|
| 必装核心 | duckdb / pandas / scipy / statsmodels / sklearn / fastapi / uvicorn / openai / loguru + akshare | — |
| 因子 / 缠论 | **czsc**（必装） | 漏装 → 缠论信号变假（占位 MA/RSI） |
| 预测 [ml] | darts + torch | 仅失「预测第 4 源」；因子 / 技术 / 情绪 / 回测全不受影响 |
| 回测 [backtest] | backtrader / quantstats | **不需要**——回测已用 pandas / scipy 自包含实现替代 |
| 因子 [qlib] | qlib | 不需要——qlib 因子走 pandas 兜底 |

> 结论：最小可用 = 核心 + czsc。torch / darts 是「预测第 4 源」的可选项，非必需。

### 7.3 配置密钥（可选）

```bash
cp .env.example .env
# 编辑 .env 填 DEEPSEEK_API_KEY=（不填则 LLM 离线降级，核心链路仍可跑）
```

### 7.4 Windows 一键部署（推荐 Windows 用户）

直接双击 `deploy_windows.bat`（建 `.venv` + 装依赖 + 校验 Kronos vendor），之后双击 `run_daily.bat` 跑每日更新与预测。

### 7.5 GPU 说明（重要，别被误导）

**本平台 90% 的计算（因子 / czsc 缠论 / walk-forward / 回测 / 融合 / API / 看板）是纯 pandas+numpy+scipy，完全不吃 GPU，有没有卡都一样快。**

仅「预测第 4 源」碰 torch：
- **darts**：模型在本地 `fit`（训练）且 `predict`（推理），底层用 torch。但当前代码**未指定 device**，默认跑 CPU——即使装了 CUDA 版 torch 也不会自动用卡。要真用 GPU，需在 `factors/darts_adapter.py` 的 darts 模型加 `pl_trainer_kwargs={"accelerator":"gpu","devices":1}`（小改动）。
- **qlib**：本地 `fit` 用的是 CPU 学习器（lightgbm / xgboost / 线性），不吃 GPU。
- **Kronos**：走 vendor 的官方 Kronos 包（自回归解码），当前未绑 device，CPU 推理。

**结论**：普通部署**不需要 GPU**。只有当（a）你启用 darts 预测、（b）样本域放大到全 A 股或加多采样、（c）且手动把 darts trainer 指到 GPU 时，GPU 才对「预测模型训练/推理」有边际加速；对核心流水线零加速。

### 7.6 启动

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
浏览器开 `http://localhost:5173` → 6 页实时读 API。前端 `vite` 已配置 `/api` 代理到 `localhost:8000`。

---

## 8. 配置说明（.env 与 Kronos 环境变量）

### 8.1 `.env`（复制到 `.env` 后填写）

| 变量 | 默认 | 说明 |
|------|------|------|
| `DEEPSEEK_API_KEY` | 空 | DeepSeek LLM 密钥；空 → 简报/简评离线降级 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `LLM_TEMPERATURE` | `0.3` | 生成温度 |
| `LLM_MAX_TOKENS` | `2048` | 最大生成长度 |
| `LLM_CACHE_ENABLED` | `true` | 同一请求缓存，省 token |
| `SCHEDULER_ENABLED` | `false` | 是否启用定时调度 |
| `SCHEDULE_CRON` | `30 18 * * 1-5` | 盘后 18:30，周一至周五 |
| `TZ` | `Asia/Shanghai` | 时区 |
| `DATA_DIR` | `./data` | 数据目录（可选覆盖） |
| `MARKET_DB` | `./data/market.duckdb` | 行情库路径（可选覆盖） |
| `ANALYTICS_DB` | `./data/analytics.duckdb` | 分析库路径（可选覆盖） |
| `DATA_SOURCE_PRIORITY` | `mootdx,akshare,baostock` | 多源优先级（本环境实际仅 akshare 可用） |

### 8.2 Kronos 相关环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `KRONOS_LOCAL_DIR` | 未设（走在线） | 离线权重目录（如 `_local_kronos_weights`）。`_run_real.py` 已默认设为该目录。 |
| `KRONOS_MODEL_REPO` | `NeoQuasar/Kronos-base` | **模型 HF id**。⚠️ 见 §10.3 关键坑 |
| `KRONOS_TOK_REPO` | `NeoQuasar/Kronos-Tokenizer-base` | 分词器 HF id |
| `KRONOS_MODEL_ENDPOINT` | 按尺寸自动 | 仅模型权重下载端点 |
| `KRONOS_TOK_ENDPOINT` | `https://hf-mirror.com` | 仅分词器下载端点 |
| `KRONOS_HF_ENDPOINT` | 按尺寸自动 | 全局 HF 端点 |
| `KRONOS_SKIP_DARTS` | `0` | `=1` 跳过 Darts（A 股日收益近白噪声，已知塌缩为 0，且训练慢） |
| `KRONOS_SKIP_QLIB` | `0` | `=1` 跳过 qlib 预测源 |
| `KRONOS_N_EVAL_DATES` | `15` | 每只股票 walk-forward 评估的历史时点数。**⚠️ 见 §9.4 性能** |
| `KRONOS_EVAL_STOCKS` | `0` | 仅评估前 N 只（调试用；0=全部） |

---

## 9. 数据更新与每日预测

### 9.1 一键运行

```bash
python _run_real.py
```

该入口会（基于沪深300 样本域）：

1. 取沪深300 成分（akshare，带 30s 超时 + 本地缓存 + universe 表三级兜底）
2. 取行业 / 市值元数据（中性化用）
3. `step_ingest`：拉取截至今日的日 K（akshare 新浪财经），幂等 upsert 入 `market.duckdb`
4. `run_daily(TARGET)`：跑完整 11 步流水线（universe→因子→情绪→预测→体检→中性化→融合→板块→LLM→回测）
5. 写出 `_today_prediction.md`（中文信号报告）

预期产出（最新一次实跑，TARGET=2026-07-10）：看多 127 / 看空 142 / 中性 31；Kronos-small dir_acc≈0.632，唯一有效预测源。

### 9.2 断点续跑（ingest）

`step_ingest` 支持断点续跑：若某标的库内已含 `end` 当日及之后的数据则跳过重新拉取；每满 50 只即落库一批。环境被掐断重跑时，凭库内 `max(date)` 续跑，不丢已取数据。

### 9.3 预测检查点（续跑防重算）

`factors/prediction.py` 对 Kronos/Darts 的 walk-forward 评估写入原子检查点：

```
_kronos_eval_ckpt_kronos_e{N}_s{N}.json
```

签名含 `(model, n_eval_dates, n_stocks)`。重跑时已完成股票直接跳过，复用既有方向样本与「目标日预测」。沙箱休眠杀进程后重跑可秒级恢复。

### 9.4 性能调优（重要）

默认 `KRONOS_N_EVAL_DATES=15` 意味着每只股票做 3 周期 × 15 = 45 次历史推理，仅用于估计方向准确率权重。在 300 只规模下，**默认配置整轮约需数小时**。

- 若只想快速出今日信号、复用既有评估：设 `KRONOS_N_EVAL_DATES=1`（命中既有 `e1_s0` 检查点可秒级跳过全部推理）。
- 仅调试前 N 只：设 `KRONOS_EVAL_STOCKS=50`。

> 经验值：完整 300 只 + `n_eval_dates=15` 可能数小时；`n_eval_dates=1` + 复用检查点约 2 分钟跑完。

### 9.5 自动调度

- 设 `.env` 中 `SCHEDULER_ENABLED=true`，Web「运维控制」卡片的「自动运行」开关也可在运行时切换（基于 APScheduler，默认 cron `30 18 * * 1-5`）。
- 注意 DuckDB 单写者约束：自动调度与常驻 API 不要长时间重叠写同一库（见 §15 FAQ）。

---

## 10. Kronos 预测模型详解

Kronos 是金融 K 线基础模型（作者 shiyu-coder，arXiv 2508.02739），吃 OHLCV + 时间戳，自回归解码未来 K 线，逆归一化回价格尺度，产出方向预测。

### 10.1 模型尺寸与权重

| 尺寸 | HF id | 权重大小 | 说明 |
|------|-------|---------|------|
| base | `NeoQuasar/Kronos-base` | ~102 MB | 默认最强开源版；推理质量最高 |
| small | `NeoQuasar/Kronos-small` | ~24.7 MB | 轻量；沙箱离线权重即此 |
| mini / large | `NeoQuasar/Kronos-mini` / `-large` | — | 按尺寸自动选端点 |

分词器 `NeoQuasar/Kronos-Tokenizer-base`（base / small 共用）。

### 10.2 端点分流（按尺寸自动）

- `Kronos-small` → Gitee AI（`hf-api.gitee.com`，已验证可绕过 xet CDN 完整下载）
- `Kronos-base` / `-mini` / `-large` → `hf-mirror.com`（Gitee AI 未镜像）
- 分词器恒走 `hf-mirror.com`

### 10.3 ⚠️ 关键坑：默认 base 在无权重时会静默降级

`kronos_adapter` 默认 `KRONOS_MODEL_REPO=NeoQuasar/Kronos-base`。若本地 `KRONOS_LOCAL_DIR` 下**没有 base 权重目录**，适配器会回退在线加载；在**无法访问 hf-mirror 的环境（如本沙箱）会失败并静默降级为 baseline**——你以为跑了 Kronos，实际只有动量基线。

**解决**：要离线用沙箱自带的 small 权重，必须显式指定：

```bash
set KRONOS_MODEL_REPO=NeoQuasar/Kronos-small   # Windows
# 或 Linux/macOS:
export KRONOS_MODEL_REPO=NeoQuasar/Kronos-small
python _run_real.py
```

有外网的机器则无需改——默认 base 会经 hf-mirror 自动下载（质量更好）。

### 10.4 获取权重

| 方式 | 做法 |
|------|------|
| 仓库外带（推荐离线） | 从发布包 `quant-code.tar.gz` 解压 `_local_kronos_weights/` 到项目根；或 `git clone` 后单独拷该目录 |
| 脚本拉取 | `python download_kronos_weights.py`（需联网，支持 Gitee AI / hf-mirror） |
| 在线自动 | 运行时不设 `KRONOS_LOCAL_DIR`，适配器按尺寸自动下载到缓存 |

---

## 11. 运维监控层（新增）

为可观测性新增的运维能力，全部已在 Web UI 落地。

### 11.1 后端

| 模块 | 职责 |
|------|------|
| `api/routers/admin.py` | `UpdateManager`：后台线程触发更新；3 次指数退避重试；幂等 upsert 断点续跑；`BackgroundScheduler` 支持 Web 切换自动运行；运行历史写入 JSONL |
| `api/routers/monitor.py` | `MonitorService`：跨库只读聚合（数据状态 / 因子健康 / 模型状态 / 管线进度 / 运行历史） |
| `api/run_store.py` | 运行历史 JSONL 读写（规避 DuckDB 单写者锁） |

### 11.2 Web UI

- **Dashboard 页「运维控制」卡片**：立即更新按钮（轮询进度）+ 自动运行开关 + 进度条（11 步）+ 当前步 / 上次成功日 / 失败告警。
- **Monitor 页（新增 `/monitor`）**：数据状态卡、因子健康卡、模型状态表（Kronos 高亮）、管线实时进度、运行历史表。每 4s / 8s 轮询。

### 11.3 状态判定

- 数据陈旧阈值 `STALE_DAYS=4`：超过则标记「数据过期」。
- 因子健康：按 `失效 / 有效 / 衰减` 统计 + 平均 ICIR。
- 模型状态：展示各预测源 `dir_acc` 与 `weight`，自动标出主导模型。

---

## 12. Web 看板页面说明

| 路由 | 页面 | 内容 |
|------|------|------|
| `/` | Dashboard | 看板汇总 + **运维控制卡片**（更新触发 / 自动运行 / 进度） |
| `/factors` | Factors | 因子健康（失效/有效/衰减）、因子值下钻 |
| `/sectors` | Sectors | 板块轮动、行业强弱（RS） |
| `/stocks` | Stocks | 个股详情、K 线、信号拆解（因子/技术/情绪/预测贡献）、搜索 |
| `/watchlist` | Watchlist | 自选股记账（成本/持仓/盈亏）、逐只简评 |
| `/monitor` | Monitor | 运维监控（数据/因子/模型/管线/历史） |

所有页面暗色现代风格，实时读 FastAPI。

---

## 13. API 端点完整列表

基础前缀：`http://localhost:8000`，所有业务路由以 `/api` 开头。CORS 当前为 `*`、无鉴权（本地部署可接受；公网部署需自行加鉴权）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/dashboard/summary` | 看板汇总 |
| GET | `/api/factors/health` | 因子健康度 |
| GET | `/api/factors/values` | 因子值 |
| GET | `/api/factors/summary` | 因子汇总 |
| GET | `/api/sectors/rotation` | 板块轮动 |
| GET | `/api/sectors/list` | 板块列表 |
| GET | `/api/stocks/search` | 个股搜索 |
| GET | `/api/stocks/{code}` | 个股详情 |
| GET | `/api/stocks/{code}/bars` | 个股 K 线 |
| GET | `/api/stocks/{code}/review` | 个股简评（LLM） |
| GET | `/api/watchlist` | 自选股列表 |
| POST | `/api/watchlist` | 添加自选股 |
| DELETE | `/api/watchlist/{code}` | 删除自选股 |
| GET | `/api/watchlist/brief` | 自选股简报 |
| POST | `/api/admin/update` | 触发数据更新（运行中返回 409） |
| GET | `/api/admin/status` | 更新状态 / 进度 |
| POST | `/api/admin/auto/start` | 启动自动运行调度 |
| POST | `/api/admin/auto/stop` | 停止自动运行调度 |
| GET | `/api/monitor/overview` | 运维总览（数据/因子/模型/管线） |
| GET | `/api/monitor/history` | 运行历史 |

---

## 14. 已知限制与降级项

| 项 | 状态 | 说明 |
|----|------|------|
| **LLM 简报/简评** | 未联调（D3） | 无 `DEEPSEEK_API_KEY` 时返回离线占位摘要；配 key 后即真实生成 |
| **qlib 因子/回测** | 缺失可降级 | 未装 qlib → 因子走 pandas 兜底，回测交叉验证跳过 |
| **backtrader 交叉验证** | 缺失可跳过 | 未装 backtrader → 仅 walk-forward 主口径 |
| **quantstats 绩效报告** | 缺失可降级 | 未装 → 回退基础指标字典 |
| **Darts 预测** | 可跳过 | `KRONOS_SKIP_DARTS=1`；A 股日收益近白噪声，权重恒 0 |
| **Kronos base 离线** | 受限 | 沙箱无外网取 base；需 `KRONOS_MODEL_REPO=small` 用本地权重（见 §10.3） |
| **数据截止** | 取决于 akshare | 盘中或未收盘日，库内最新为最近已收盘交易日 |
| **analysis-only** | 设计如此 | 无下单 / 券商接口，纯研究信号 |

---

## 15. 故障排查 FAQ

**Q1：跑 `_run_real.py` 很慢 / 几小时没完？**
A：默认 `KRONOS_N_EVAL_DATES=15` 对 300 只做大量历史推理。设 `KRONOS_N_EVAL_DATES=1` 并复用 `_kronos_eval_ckpt_kronos_e1_s0.json` 可秒级跳过（见 §9.4）。

**Q2：Kronos 没生效，预测只有动量？**
A：检查是否命中 §10.3 的 base 静默降级。确认 `KRONOS_MODEL_REPO` 与本地 `KRONOS_LOCAL_DIR` 下的权重目录匹配（离线用 small 必须显式设 `KRONOS_MODEL_REPO=NeoQuasar/Kronos-small`）。

**Q3：DuckDB 报错 "database is locked" / 单写者冲突？**
A：同一份 `*.duckdb` 不要多个写入进程并发。建议每日刷新作为独立一次性进程跑完即退，不要和常驻 API 长时间重叠写同一文件；只读查询（看板）可与写入错峰。

**Q4：缠论信号不对 / 退化为 MA/RSI？**
A：漏装 `czsc`。`pip install czsc` 后重跑。

**Q5：LLM 简报为空 / 显示未生成？**
A：未配 `DEEPSEEK_API_KEY`，预期离线降级，非 bug。配 key 即恢复。

**Q6：akshare 拉数据超时 / 限流？**
A：偶发正常，次日补拉即可；`step_ingest` 断点续跑不会重复全量。

**Q7：前端打不开 / API 404？**
A：确认后端 `uvicorn api.main:app --port 8000` 已起；前端 `vite` 已配 `/api` 代理到 8000。

**Q8：想扩到全 A 股？**
A：改 `_run_real.py` 的 `stock_list` 来源为全市场代码（如 `D:\DMYY\stock-db` 导出）传给 `Orchestrator`；内存按 8–16 GB、磁盘数十 GB 规划（详见 §6 环境要求中的全 A 股列）。

---

## 16. 开发指南

### 16.1 加一个因子

1. 在 `factors/factor_calc.py` 的 `compute()` 中新增因子列（返回长表 `date/code/factor_name/value`）。
2. 因子自动进入融合与 `factor_health` 体检（IC / ICIR）。
3. qlib 专属因子在 `factors/qlib_factors.py`（缺失时 pandas 兜底）。

### 16.2 加一个信号源

- 预测源：实现 `factors/*_adapter.py` 的 `predict()` 接口，在 `factors/prediction.py` 的 `self.models` 列表注册；walk-forward 自动评估并赋权。
- 技术 / 情绪：扩展 `factors/czsc_signals.py` / `factors/sentiment.py`，输出 `tech_score` / `sentiment_score`。

### 16.3 改融合权重

`config/` 下的 `settings` 中调整 `fusion.base_weights`（因子/技术/情绪/预测占比）。

### 16.4 冒烟测试

```bash
python tests/test_smoke.py     # 构造内存假数据，跑通 ingest→...→signals 落 DuckDB
```

---

## 17. 安全与免责声明

- **本项目仅用于量化研究与学习，不提供任何投资建议，不构成买卖依据。**
- 所有信号为「研究观点」，置信度取自信号层；投资决策与风险由使用者自行承担。
- `.env` / 密钥严禁提交进仓库；token 用完即焚（删除 GitHub Personal Access Token）。
- 公网部署请自行加 API 鉴权与访问控制（当前 CORS `*`、无鉴权，仅适合本地）。
- 数据来自 akshare 等公开源，可能存在延迟 / 偏差，以交易所官方数据为准。

---

> 仓库地址：`https://github.com/dreamlark/quant-platform`
> 反馈 / 贡献：提交 Issue 或 PR。
