# A 股日频量化分析平台（quant-platform）

> **analysis-first（只分析、不交易）** · A 股 · 日频 / 中低频 · 收盘后批处理。
> 融合 **因子 + 技术 + 情绪 + 预测** 四源信号，产出中文市场分析、信号清单与可解释个股 / 板块 / 因子洞察。

---

## 目录

1. [项目定位](#1-项目定位)
2. [核心特性](#2-核心特性)
3. [方法学红线（已落地）](#3-方法学红线已落地)
4. [系统架构（分层 / 双数据流 / 依赖 / 存储）](#4-系统架构)
   - 4.0 顶层分层架构（L1–L6）
   - 4.1 盘后批处理数据流
   - 4.2 实时服务数据流
   - 4.3 模块依赖关系
   - 4.4 数据存储角色
   - 4.5 四源信号融合权重
   - 4.6 容错与降级边界
5. [目录结构与逐文件作用](#5-目录结构与逐文件作用)
6. [环境要求](#6-环境要求)
7. [安装与部署](#7-安装与部署)
8. [配置说明与关键参数](#8-配置说明与关键参数)
   - 8.1 `.env` 变量
   - 8.2 Kronos 环境变量
   - 8.3 `config/settings.yaml` 关键参数
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
| **情绪第 4 源**（P0-2） | `factors/sentiment.py`（T0 量价代理：换手异常/振幅/涨停率/收益偏度/breadth_rank/相对强度）+ `factors/market_sentiment.py`（T1 五维分位综合指数 / T2 温度计择时 / GSISI 行业 Beta 轮动）+ `factors/text_sentiment.py`（T3 LLM 文本情绪，门控降级） |
| **风险中性化**（P1-4） | `factors/risk_neutral.py` 行业 / 市值回归残差法，融合前执行 |
| **A 股回测制度**（P1-1） | `backtest/cost_model.py` 佣金万 2.5 / 印花税千 1 / 滑点 / T+1 / 涨跌停流动性约束 |

---

## 4. 系统架构

平台采用**「分层 + 批处理/服务双通道」**架构。盘后跑一次编排流水线把原始行情加工成「信号 / 板块 / 因子 / 简报」，全部落库；常驻 FastAPI 仅做只读服务，避免与批处理写者争锁（DuckDB 单写者约束，见 §4.6）。

### 4.0 顶层分层架构（L1–L6）

```
┌──────────────────────────────────────────────────────────────┐
│ L6 展示层   web/ (React + antd + ECharts) 暗色看板             │
│            /dashboard /factors /sectors /stocks /watchlist    │
│            /monitor —— 纯静态前端，仅经 API 取数              │
├──────────────────────────────────────────────────────────────┤
│ L5 接口层   api/ (FastAPI) —— 只读服务                        │
│            routers/* 聚合 DuckDB 只读查询 + run_store 历史；   │
│            无计算、不写分析库（单写者约束）                    │
├──────────────────────────────────────────────────────────────┤
│ L4 编排层   scheduler/ (Orchestrator + Jobs)                  │
│            run_daily(12 步) 串行编排；Jobs 接 APScheduler     │
│            cron 触发；是唯一合法「写分析库」入口               │
├──────────────────────────────────────────────────────────────┤
│ L3 计算层   factors/ fusion/ evaluation/ backtest/ llm/       │
│            信号计算 → 四源融合 → 因子体检 → 回测 → 简报       │
├──────────────────────────────────────────────────────────────┤
│ L2 存储层   storage/ (DuckDB + JSONL)                         │
│            market.duckdb(原始日K+universe) /                  │
│            analytics.duckdb(全部结果) / run_store.jsonl(历史) │
├──────────────────────────────────────────────────────────────┤
│ L1 数据源层 sources/ (akshare / mootdx / baostock)            │
│            盘后拉取 OHLCV，复权、过滤可投资域                  │
└──────────────────────────────────────────────────────────────┘
```

各层职责与约束一览：

| 层 | 模块 | 职责 | 关键约束 |
|----|------|------|----------|
| L6 展示 | `web/` | 暗色看板、图表、交互 | 无业务逻辑，仅调 API |
| L5 接口 | `api/` | 只读聚合、响应模型 | **禁止写** analytics 库 |
| L4 编排 | `scheduler/` | 12 步流水线、调度 | 唯一写分析库入口；无顶层 try（任一步错即停） |
| L3 计算 | `factors/ fusion/ evaluation/ backtest/ llm/` | 信号/融合/体检/回测/简报 | 纯函数式，依赖 storage 读写 |
| L2 存储 | `storage/` | DuckDB 封装、UPSERT、幂等建表 | 单一连接；后复权为计算基准 |
| L1 数据 | `sources/` | 行情拉取、复权、universe | 冗余三级（mootdx→akshare→baostock），懒加载降级 |

### 4.1 盘后批处理数据流

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
         sector(板块轮动)  market_sentiment(市场情绪)  llm(简报/简评)  backtest(walk-forward)
                        │                      │                    │
                        └──────────────────────┴────────────────────┘
                                       ▼
                              analytics.duckdb (全部结果)
```

> 步骤顺序（`scheduler/orchestrator.py`）：`step_ingest → universe → factors → sentiment → predict → health → neutralize → fusion → sector → market_sentiment → llm → backtest`（共 12 步）。任一步异常会中止整轮（无顶层 try/except），需在 `run_store.jsonl` 查看到达步骤与错误。

### 4.2 实时服务 / 请求数据流

```
浏览器 → web/ (React) ──fetch──▶ api/main.py (FastAPI)
                                      │
                  ┌───────────────────┼───────────────────┐
                  ▼                   ▼                   ▼
            routers/dashboard   routers/factors    routers/stocks ...
                  │                   │                   │
                  └─────────┬─────────┴─────────┬─────────┘
                            ▼                   ▼
                  storage/repository  ◀── analytics.duckdb (只读)
                  api/run_store      ◀── run_store.jsonl  (历史只读)
```

- 服务通道**只读**：所有查询走 `Repository` 的 SELECT；写操作只发生在 L4 编排层。
- `run_store.jsonl` 由编排层追加写、API 层只读，天然避开 DuckDB 写者锁。

### 4.3 模块依赖关系（编译期 / 运行期）

```
_run_real.py ──▶ scheduler.orchestrator
                       │
   ┌───────────┬───────┼───────────┬───────────┐
   ▼           ▼       ▼           ▼           ▼
 sources/*  factors/*  fusion/*  evaluation/* backtest/*
   │           │       │           │           │
   └─────▶ storage/repository ◀────┘           │
              │           │                     │
              ▼           ▼                     ▼
       market.duckdb  analytics.duckdb      llm/* (可选)
                       ▲
                       │
              api/* (只读服务)
```

- **计算层 → 存储层**：全部经 `storage/repository.Repository` 读写，不直接开 DuckDB 连接。
- **重依赖懒加载**：`qlib / alphalens / backtrader / quantstats / mootdx / czsc / darts` 均在方法内 `try/except` 懒加载；缺失时走 pandas/numpy/scipy 兜底，不崩。
- **LLM 可选**：`llm/` 无 key 时返回离线占位，核心链路不受影响。

### 4.4 数据存储角色

| 存储 | 文件 | 角色 | 大小(参考) | 入库 |
|------|------|------|-----------|------|
| 行情库 | `data/market.duckdb` | 原始日 K（后复权 `adj_back_close`）、`universe` 表、行业/市值元数据 | ~60 MB | 否（gitignore，可重跑） |
| 分析库 | `data/analytics.duckdb` | 因子值、信号、板块、体检、回测、简报全部结果 | ~572 MB | 否（gitignore，可重跑） |
| 运行历史 | `data/run_store.jsonl` | 每次更新追加一条（run_id/状态/步骤/耗时/错误），供监控层只读 | 小 | 否 |

> 价格计算统一读取 `adj_back_close`（后复权），`adj_front_close`（前复权）仅供前端展示，严禁入计算（P0-1 红线）。

### 4.5 四源信号融合权重

`fusion/signal_pool.py` 默认融合权重（可在 `settings` 调）：

| 信号源 | 默认权重 | 说明 |
|--------|---------|------|
| 因子（factor） | 0.40 | 量价 / 基本面 Alpha 因子 |
| 技术（tech） | 0.20 | czsc 缠论笔段信号 |
| 情绪（sentiment） | 0.15 | 量价代理情绪 |
| 预测（predict） | 0.25 | Kronos 等时序模型；模型内部再按 walk-forward 方向准确率细分权重 |

> 预测源内部权重：每个模型由历史 walk-forward 方向准确率（`predict_health.dir_acc`）决定其占「预测分支」的比重。`dir_acc ≤ 0.5`（近随机）的模型自动降权到 0。在最新实跑中，Kronos-small 的 `dir_acc≈0.632` 是唯一拿到正权重的预测源。

### 4.6 容错与降级边界

- **单写者约束**：DuckDB 同一库同一时刻仅一个写连接。编排层（L4）是唯一写者；API（L5）常驻只读；自动调度与手工运行不要长时间重叠写同一库。
- **幂等重跑**：`ingest` 按 `max(date)` 续跑；预测检查点 `_kronos_eval_ckpt_*.json` 按签名跳过已算股票。
- **静默降级**：数据源/重模型缺失时降级到基线，不抛顶层异常（各 step 内部已隔离；但编排层无顶层 try，单步未捕获异常会中止整轮）。
- **信号池兜底**：预测源 `dir_acc ≤ 0.5` 自动降权为 0，避免噪声污染融合。
- **多源冗余（L1）**：`DataSourceRouter` 按 `data_sources.priority` 依次尝试（默认 `mootdx→akshare→baostock`），单源挂死经 `source_timeout`（默认 20s，daemon 线程 + join 超时）护栏降级到下一冗余源，不阻塞整条 ingest；多源同标的收盘差异超 `diff_threshold`（默认 0.03）时既告警又写入结构化 `divergence_log`（JSONL，字段含 code/date/source_a/source_b/price_a/price_b/diff/threshold），供监控/告警消费，并把该行 `source` 标为 `*_suspect`。

---

## 5. 目录结构与逐文件作用

### 5.1 完整目录树（已入库 110 文件）

```
quant-platform/
├── _run_real.py                 # ★ 正式批处理入口（沪深300 样本域 → 今日信号报告）
├── bootstrap_kronos.sh          # 拉取 Kronos 离线权重（small + Tokenizer-base）
├── download_kronos_weights.py   # 权重下载脚本（镜像/官方端点）
├── fetch_kronos_weights.py      # 权重下载（备选实现）
├── deploy_windows.bat           # Windows 一键部署（建 .venv + 装依赖）
├── run_daily.bat                # Windows 每日运行包装
├── requirements.txt             # Python 依赖清单
├── pyproject.toml               # 项目元数据 / 构建配置
├── .env.example                 # 环境变量样例（复制为 .env 填写）
├── .gitignore                   # 忽略 data/ / _local_kronos_weights/ / *.log 等
├── README.md                    # 本文件
├── KRONOS_WEIGHTS_GUIDE.md      # Kronos 权重获取与离线部署指南
├── _completion_assessment.md    # 完成度评估（产物说明）
├── docs/                         # 设计文档（含情绪框架 PRD：sentiment_framework_prd.md）
├── _today_prediction.md         # ★ 示例产物：最近一次信号报告（入库作样例）
├── _kronos_eval_ckpt_*.json     # ★ 示例产物：预测评估检查点（入库作样例）
├── api/                         # L5 接口层（FastAPI，只读服务）
├── common/                      # 配置加载 + 统计工具
├── config/                      # settings 默认配置（YAML）
├── evaluation/                  # 因子体检（IC / ICIR / 衰减）
├── factors/                     # L3 信号计算（因子/技术/情绪/预测/中性化）
├── fusion/                      # 四源融合 + 板块轮动 + 推送预留
├── llm/                         # LLM 简报/简评 + 预留接口
├── backtest/                    # walk-forward / 成本模型 / 报告 / 交叉验证
├── scheduler/                   # L4 编排层（Orchestrator + Jobs）
├── sources/                     # L1 数据源（akshare/mootdx/baostock + 复权/universe）
├── storage/                     # L2 存储层（DuckDB 封装）
├── tests/                       # 冒烟 / 单元 / 集成测试
└── web/                         # L6 前端（React + antd + ECharts）
```

> 未入库但运行必需的本地目录：`data/`（DuckDB + 缓存，gitignore，可重跑）、`_local_kronos_weights/`（Kronos 离线权重，gitignore）、`_vendor/Kronos/`（官方推理代码，gitignore）。

### 5.2 顶层入口与部署脚本

| 文件 | 作用 |
|------|------|
| `_run_real.py` | ★ 正式批处理入口：设 `KRONOS_LOCAL_DIR`、`n_eval_dates=1` 跑沪深300 样本域真实数据，写 `_today_prediction.md` |
| `bootstrap_kronos.sh` | 拉取 Kronos 离线权重（small + Tokenizer-base）到 `_local_kronos_weights/` |
| `download_kronos_weights.py` | 权重下载脚本（支持镜像/官方端点切换） |
| `fetch_kronos_weights.py` | 权重下载备选实现 |
| `deploy_windows.bat` | Windows 一键部署：建 `.venv` + 装依赖 + 启动 |
| `run_daily.bat` | Windows 每日运行包装（调用 `_run_real.py`） |
| `requirements.txt` | Python 依赖清单（核心链路边际轻量；重依赖可选） |
| `pyproject.toml` | 项目元数据 / 构建配置 |
| `.env.example` | 环境变量样例，复制为 `.env` 后填写密钥 |
| `.gitignore` | 忽略 `data/`、`_local_kronos_weights/`、`*.log`、开发散文件等 |
| `README.md` | 本说明文档 |
| `KRONOS_WEIGHTS_GUIDE.md` | Kronos 权重获取与离线部署指南（含 §10.3 关键坑） |
| `_completion_assessment.md` | 完成度评估说明（产物） |
| `_today_prediction.md` | ★ 示例产物：最近一次信号报告（入库作样例） |
| `_kronos_eval_ckpt_kronos_e1_s0.json` | ★ 示例产物：Kronos 评估检查点（入库作样例，可秒级复用） |
| `_kronos_eval_ckpt_qlib_e1_s0.json` | ★ 示例产物：qlib 评估检查点（入库作样例） |

### 5.3 后端逐文件作用

#### 5.3.1 `api/`（FastAPI 接口层，只读）

| 文件 | 作用 |
|------|------|
| `api/main.py` | FastAPI 应用入口，挂载全部 router + CORS + 静态前端 |
| `api/database.py` | 共享资源：加载配置、构建 `Repository`（单例） |
| `api/schemas.py` | Pydantic v2 响应模型（看板/因子/个股/板块等） |
| `api/utils.py` | API 辅助函数（日期解析、查询封装等） |
| `api/run_store.py` | 运行历史 JSONL 追加写（避开 DuckDB 写者锁），供监控只读 |
| `api/routers/admin.py` | 运维控制：触发更新 / 自动运行开关 / 进度（UpdateManager） |
| `api/routers/monitor.py` | 运维监控：跨库只读聚合（数据/因子/模型/管线状态） |
| `api/routers/dashboard.py` | 看板汇总端点 |
| `api/routers/factors.py` | 因子健康 / 因子值查询 |
| `api/routers/sectors.py` | 板块轮动查询 |
| `api/routers/stocks.py` | 个股详情 / K线 / 简评 / 搜索 |
| `api/routers/watchlist.py` | 自选股记账读写 |

#### 5.3.2 `common/`

| 文件 | 作用 |
|------|------|
| `common/__init__.py` | 包初始化 |
| `common/config.py` | 配置加载 + `build_repository()`（配置驱动，禁止硬编码密钥） |
| `common/stats.py` | 通用统计 / 横截面工具（零重型依赖，numpy/pandas） |

#### 5.3.3 `config/`

| 文件 | 作用 |
|------|------|
| `config/settings.yaml` | **主配置**：数据源/复权/universe/因子/融合/体检/情绪/回测/LLM/调度（详见 §8.3） |
| `config/factors.yaml` | 因子定义清单（名称/类别/参数），被 `factors/` 读取 |
| `config/sectors.yaml` | 板块/行业分类与轮动参数 |

#### 5.3.4 `evaluation/`

| 文件 | 作用 |
|------|------|
| `evaluation/health_check.py` | 因子体检：IC / ICIR / 衰减 / 失效判定（`valid_ic` `valid_icir` `fail_ic` 等阈值） |

#### 5.3.5 `factors/`（信号计算核心）

| 文件 | 作用 |
|------|------|
| `factors/factor_calc.py` | 因子 + 技术分计算（含 czsc 缠论调用） |
| `factors/qlib_factors.py` | qlib 因子（缺失时 pandas 兜底） |
| `factors/kronos_adapter.py` | Kronos 适配：离线/在线权重、端点分流（按尺寸自动） |
| `factors/darts_adapter.py` | Darts 预测适配（可选，A 股日收益近白噪声，已知塌缩为 0） |
| `factors/qlib_predict_adapter.py` | qlib 预测适配：复刻 Alpha158 特征（pandas），sklearn-API 模型动物园（xgb/lgbm/catb/histgb/gbr/rf/et/ridge）按 walk-forward 方向准确率自动选优；缺失时 pandas+xgboost 兜底 |
| `factors/prediction.py` | 预测编排 + walk-forward 评估 + 检查点续跑（`KRONOS_N_EVAL_DATES` 控制） |
| `factors/risk_neutral.py` | 行业 / 市值中性化（去风格暴露） |
| `factors/sentiment.py` | 量价代理情绪（T0 扩展：换手异常/振幅/涨停率/收益偏度 + breadth_rank 横截面分位 + relative_strength 相对强度） |
| `factors/market_sentiment.py` | 市场级综合情绪指数（T1 五维分位合成：量/价/资金/估值/风险溢价 + T2 华泰温度计择时 + GSISI 行业 Beta 轮动） |
| `factors/text_sentiment.py` | LLM 文本情绪（T3：对财经新闻做语义打分，门控——无 key/无新闻降级） |
| `factors/czsc_signals.py` | 缠论笔段信号（依赖 czsc，懒加载） |

#### 5.3.6 `fusion/`

| 文件 | 作用 |
|------|------|
| `fusion/signal_pool.py` | 四源加权融合 → `signals`（权重见 §4.5，`predict_min_dir_acc` 兜底）；含 `regime_adjust` 钩子（regime_state=bear/panic 时**仅缩放置信度**，默认 ON·安全默认，见 §8.3） |
| `fusion/sector.py` | 板块轮动 / 强弱排名（DuckDB 聚合，零重框架） |
| `fusion/push.py` | 信号推送预留接口（P2，首版仅看板内展示，未实现） |

#### 5.3.7 `llm/`

| 文件 | 作用 |
|------|------|
| `llm/client.py` | DeepSeek 客户端（无 key 离线降级，OpenAI 兼容） |
| `llm/brief_gen.py` | 市场简报生成（聚合四源信号 → 中文简报） |
| `llm/stock_review.py` | 自选股逐只简评 |
| `llm/prompts.py` | LLM System Prompt 模板（内置合规红线，缓存命中） |
| `llm/agent_interface.py` | 多 Agent 研判预留接口（P2，首版不启用） |
| `llm/factor_mining_if.py` | 自动因子挖掘预留接口（P2，首版不启用） |

#### 5.3.8 `scheduler/`（编排层）

| 文件 | 作用 |
|------|------|
| `scheduler/orchestrator.py` | ★ 每日盘后编排：`run_daily(12 步)` 串行流水线（含 `step_market_sentiment`） |
| `scheduler/jobs.py` | APScheduler 定时任务（cron 触发 `run_daily`，生产部署用） |

#### 5.3.9 `sources/`（数据源层）

| 文件 | 作用 |
|------|------|
| `sources/base.py` | 数据源基类 / 路由（多源优先级切换） |
| `sources/akshare_adapter.py` | akshare 新浪财经日 K 适配器（本环境唯一可用源） |
| `sources/mootdx_adapter.py` | mootdx / Tencent 适配器（主源，防封，懒加载降级） |
| `sources/baostock_adapter.py` | baostock 适配器（冗余源，懒加载降级） |
| `sources/adjust.py` | 复权计算（后复权锚定最早，前复权仅展示） |
| `sources/universe.py` | 可投资域过滤（剔 ST / 次新 / 长期停牌，消生存偏差） |
| `sources/market_meta.py` | 行业 / 市值元数据（中性化与板块用） |
| `sources/sentiment_data.py` | 情绪外部数据层（akshare 多源：融资融券/北向/指数估值/10Y 国债/ETF 净流/新闻；本地缓存 + 失败降级） |
| `sources/_sw_industry_cache.json` | 申万行业映射缓存（本地，免重复拉取） |

#### 5.3.10 `storage/`（存储层）

| 文件 | 作用 |
|------|------|
| `storage/duckdb_client.py` | DuckDB 连接 / 读写 / upsert 封装（单一连接，幂等建表） |
| `storage/repository.py` | 仓储层：业务读写接口（含 `save/load_sentiment_index` 等 CRUD，计算层统一经此访问 DB） |
| `storage/schema.py` | 全库 DDL + 元数据（集中管理表结构一致；13 张表含 `sentiment_index`，`adj_back_close` 为计算基准） |

#### 5.3.11 `backtest/`

| 文件 | 作用 |
|------|------|
| `backtest/walk_forward.py` | walk-forward 主口径（pandas/scipy 自包含，样本外） |
| `backtest/engine.py` | 共享回测引擎（多空/仅多、CostModel、基准等权） |
| `backtest/cost_model.py` | A 股成本模型（佣金/印花税/滑点/T+1/涨跌停流动性） |
| `backtest/report.py` | 绩效报告（quantstats 懒加载） |
| `backtest/qlib_backtest.py` | qlib 交叉验证（可选） |
| `backtest/bt_backtest.py` | backtrader 交叉验证（可选） |
| `backtest/sentiment_timing.py` | **T2 温度计择时回测**（PRD §10 验收）：`sentiment_index.signal` 作权益暴露叠加层，滚动样本外验证年化/回撤/超额 |
| `backtest/signal_backtest.py` | **信号层组合回测**（#4 regime 调节验证）：置信度加权多头组合，支持 regime 缩放 ON/OFF 对比（`compare_regime`） |

#### 5.3.12 `tests/`

| 文件 | 作用 |
|------|------|
| `tests/test_smoke.py` | 冒烟测试（核心链路可跑、无 key 降级） |
| `tests/test_api.py` | API 端点测试 |
| `tests/test_api_qa.py` | API 质量/边界测试 |
| `tests/test_fe_constraints.py` | 前端约束测试（暗色/简体中文/无外部依赖） |
| `tests/test_kronos_adapter.py` | Kronos 适配器单测（离线/在线解析） |
| `tests/test_prediction_kronos_integration.py` | 预测+Kronos 集成测试 |
| `tests/test_sentiment_t0.py` | T0 量价代理情绪单测（形状/范围/组件/无前视） |
| `tests/test_market_sentiment.py` | 市场级综合情绪指数单测（五维合成/GSISI/无前视/外部数据） |
| `tests/test_sentiment_timing.py` | T2 温度计择时回测单测（非空气流/三组指标/exposure 映射/降级） |
| `tests/test_signal_backtest.py` | 信号层组合回测 + regime 缩放 ON/OFF 对比单测 |
| `tests/test_regime_adjust.py` | 融合层 regime 调节单测（默认 OFF/极端缩放/方向不变/中性不调） |
| `tests/_dbg_kronos_load.py` | 调试：Kronos 权重加载 |
| `tests/_smoke_kronos_live.py` | 调试：Kronos 实跑冒烟 |
| `tests/stub_model/model/__init__.py` | 测试桩模型（模拟预测源） |

### 5.4 前端 `web/`（React + antd + ECharts）

| 文件 | 作用 |
|------|------|
| `web/index.html` | 前端 HTML 入口 |
| `web/package.json` | 前端依赖与脚本 |
| `web/pnpm-lock.yaml` | 依赖锁文件 |
| `web/tsconfig.json` / `web/tsconfig.node.json` | TypeScript 配置 |
| `web/vite.config.ts` | Vite 构建配置（含 API 代理） |
| `web/src/main.tsx` | 前端入口挂载 |
| `web/src/App.tsx` | 路由与布局 |
| `web/src/index.css` | 全局样式（暗色主题） |
| `web/src/theme.ts` | antd 暗色主题 token |
| `web/src/api/client.ts` | API 客户端（fetch 封装） |
| `web/src/components/charts.tsx` | ECharts 图表封装组件 |
| `web/src/pages/Dashboard.tsx` | 看板汇总页 |
| `web/src/pages/Factors.tsx` | 因子健康页 |
| `web/src/pages/Sectors.tsx` | 板块轮动页 |
| `web/src/pages/Stocks.tsx` | 个股详情页（K线/简评/搜索） |
| `web/src/pages/Watchlist.tsx` | 自选股页 |
| `web/src/pages/Monitor.tsx` | 运维监控页（数据/因子/模型/管线状态/市场情绪指数卡片） |

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

> 仓库**刻意保持精简**：不含行情数据（`data/`）与模型权重（`_local_kronos_weights/`）。二者作为可选「参考数据源」托管在 GitHub Release，按需拉取（见 §7.1.1），避免协作者人人本地全量重拉 akshare 行情导致上游 API 限流报错。

### 7.1.1 可选大资源（数据 / 模型）按需拉取

仓库本体只含**代码 + 资源清单 `resources/manifest.json` + 拉取脚本 `tools/fetch_resources.py`**。大文件（行情 DuckDB、模型权重）以 **GitHub Release 资产**形式分发，拉取时做 **sha256 校验**，clone 后可自行决定要不要拉、拉哪些。

```bash
# 私有仓库：匿名公开下载会 404，需先设置 token（repo 权限即可）
export GITHUB_TOKEN=$(gh auth token)     # 或手动贴 PAT
# 拉全部（数据 + 模型）
python tools/fetch_resources.py --all
# 只拉数据 / 只拉模型
python tools/fetch_resources.py --data
python tools/fetch_resources.py --models
# 仅校验本地已下载文件的 sha256，不下载
python tools/fetch_resources.py --check
# 强制覆盖已存在的文件
python tools/fetch_resources.py --all --force
```

| 资源 | 内容 | 解压位置 | 体积（压缩 / 解压） | 不拉会怎样 |
|------|------|----------|--------------------|-----------|
| `data` | `market.duckdb`（日线行情）+ `analytics.duckdb`（因子/信号/回测/情绪指数）+ `verify_snapshot.duckdb` | `data/` | ~385 MB / ~720 MB | 无本地行情；需自行用 akshare 跑 `step_ingest` 重拉 |
| `models` | `_local_kronos_weights/`（Kronos 等离线权重） | 仓库根 | ~102 MB / ~110 MB | 预测第 4 源自动降级，因子/技术/情绪/回测不受影响 |

> **为什么这样设计**：参考数据源 = 一份可复用快照。协作者 clone 后要么直接拉这份快照（秒级、零上游压力），要么完全本地重跑（自行承担 akshare 限流风险）。仓库公开后匿名下载即生效，无需 token。
> 若想拿**最新** Kronos 权重而非快照，仍可用 `bootstrap_kronos.sh` / `download_kronos_weights.py` 从官方/镜像端点单独拉取。

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

## 8. 配置说明与关键参数

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

### 8.3 `config/settings.yaml` 关键参数

主配置全部走 YAML（由 `common/config.py` 加载），以下为影响行为的关键项。改完无需改代码，热加载取决于部署方式（重启 API / 重跑编排即生效）。

**`app` / `paths`**

| 键 | 默认 | 作用 |
|----|------|------|
| `app.analysis_first` | `true` | 分析优先红线：关闭任何交易/下单相关路径 |
| `app.timezone` | `Asia/Shanghai` | 时区（影响调度与日期边界） |
| `app.version` | `0.1.0` | 版本号 |
| `paths.data_dir` | `./data` | 数据根目录 |
| `paths.market_db` | `./data/market.duckdb` | 行情库路径 |
| `paths.analytics_db` | `./data/analytics.duckdb` | 分析库路径 |
| `paths.raw_cache` | `./data/raw_cache` | 原始拉取缓存 |

**`data_sources` / `adjust` / `universe`**

| 键 | 默认 | 作用 |
|----|------|------|
| `data_sources.priority` | `[mootdx, akshare, baostock]` | 多源优先级；本环境实际仅 akshare 可用 |
| `data_sources.diff_threshold` | `0.03` | 多源价格差异阈值，超阈值告警并写 divergence_log |
| `data_sources.source_timeout` | `20.0` | 单源调用超时护栏（秒）；超时视为该源不可用并降级 |
| `data_sources.divergence_log` | `./data/divergence_log.jsonl` | 超阈值分歧结构化记录路径（JSONL） |
| `data_sources.mootdx.bestip` | `true` | mootdx 自动选最优 IP（防封） |
| `data_sources.mootdx.timeout` | `3.0` | 单源超时（秒） |
| `data_sources.tencent.enable` | `true` | 腾讯源开关 |
| `adjust.back_method` | `back` | 后复权方法（计算基准） |
| `adjust.front_method` | `front` | 前复权方法（仅展示） |
| `adjust.jump_detect` | `true` | 跳空/除权检测 |
| `universe.min_listed_days` | `60` | 剔除上市不足 N 交易日次新 |
| `universe.suspend_max_days` | `20` | 剔除停牌超 N 交易日 |
| `universe.drop_st` | `true` | 剔除 ST / *ST |
| `universe.keep_delisted` | `true` | 退市股是否保留（消生存偏差） |

**`factors` / `fusion`**

| 键 | 默认 | 作用 |
|----|------|------|
| `factors.config_file` | `config/factors.yaml` | 因子定义清单路径 |
| `factors.neutralization` | `true` | 行业/市值中性化开关 |
| `fusion.base_weights.factor` | `0.40` | 因子源权重 |
| `fusion.base_weights.tech` | `0.20` | 技术源权重 |
| `fusion.base_weights.sentiment` | `0.15` | 情绪源权重 |
| `fusion.base_weights.predict` | `0.25` | 预测源权重 |
| `fusion.confidence_scale` | `2.5` | 信号置信度缩放（映射到输出强度） |
| `fusion.predict_min_dir_acc` | `0.52` | 预测源最低方向准确率，低于则降权为 0 |
| `fusion.regime_adjust.enabled` | `true` | **regime 调节总开关（PRD §8 安全默认 ON）**：极端（bear/panic）仅缩放置信度（不动方向）；ON/OFF 差异由 `compare_regime` 持续监控 |
| `fusion.regime_adjust.scale.bull` | `1.0` | 牛市（贪婪且市场未深跌）不调节 |
| `fusion.regime_adjust.scale.neutral` | `1.0` | 中性不调节 |
| `fusion.regime_adjust.scale.bear` | `0.70` | 熊市（指数回撤 8%~15%）置信度 ×0.70 |
| `fusion.regime_adjust.scale.panic` | `0.45` | 恐慌（指数回撤 >15%）置信度 ×0.45（最小，极端保护） |
| `market_sentiment.regime_state.drawdown_window` | `20` | 指数回撤滚动窗口（交易日），用于派生 regime_state |
| `market_sentiment.regime_state.dd_panic` | `-0.15` | 指数回撤 ≤ -15% → panic |
| `market_sentiment.regime_state.dd_bear` | `-0.08` | 指数回撤 ≤ -8% → bear |
| `market_sentiment.regime_state.dd_bull` | `-0.05` | 贪婪且回撤 > -5% → bull |

**`kronos` / `health_check` / `sentiment`**

| 键 | 默认 | 作用 |
|----|------|------|
| `kronos.model_repo` | `NeoQuasar/Kronos-base` | **模型 HF id**；离线 small 须改 `Kronos-small`（见 §10.3） |
| `health_check.ic_window` | `60` | IC 计算回看窗口 |
| `health_check.valid_ic` | `0.02` | 有效因子最低 IC |
| `health_check.valid_icir` | `0.5` | 有效因子最低 ICIR |
| `health_check.decay_ic` | `0.01` | 衰减告警 IC 阈值 |
| `health_check.fail_ic` | `0.005` | 失效 IC 阈值（低于判失效） |
| `sentiment.window` | `20` | 情绪回看窗口 |
| `sentiment.weights.turnover_anomaly` | `0.35` | 换手异常权重 |
| `sentiment.weights.amplitude` | `0.20` | 振幅权重 |
| `sentiment.weights.limit_up_rate` | `0.20` | 涨停率权重 |
| `sentiment.weights.return_skew` | `0.25` | 收益偏度权重 |

**`market_sentiment`（市场级综合情绪，T1/T2/T3）**

| 键 | 默认 | 作用 |
|----|------|------|
| `market_sentiment.percentile_window` | `750` | 五维分位滚动窗口（交易日，约 3 年）；样本不足回退中性 50 |
| `market_sentiment.dim_weights.volume` | `0.25` | 量能分维度权重（上涨成交额占比，由本平台 bars 算） |
| `market_sentiment.dim_weights.price` | `0.25` | 价格分维度权重（上涨家数占比，由本平台 bars 算） |
| `market_sentiment.dim_weights.money` | `0.20` | 资金分维度权重（融资净买/北向净买/ETF 净流 z 值求和） |
| `market_sentiment.dim_weights.valuation` | `0.15` | 估值分维度权重（指数 PE 历史分位） |
| `market_sentiment.dim_weights.riskpremium` | `0.15` | 风险溢价分维度权重（盈利收益率 − 10Y 国债） |
| `market_sentiment.thermometer.fear` | `30` | 综合指数 ≤ 此值 → 恐惧 |
| `market_sentiment.thermometer.greed` | `70` | 综合指数 ≥ 此值 → 贪婪 |
| `market_sentiment.thermometer.buy` | `10` | 综合指数 ≤ 此值 → 买入信号 |
| `market_sentiment.thermometer.empty` | `90` | 综合指数 ≥ 此值 → 空仓信号 |
| `market_sentiment.gsisi_window` | `60` | GSISI 行业 Beta 估计窗口（交易日） |
| `market_sentiment.gsisi_weeks` | `8` | GSISI 取最近 N 周行业周收益与 Beta 排序相关性 |

> 缺失维度自动剔除后权重归一化；量/价两维仅依赖本平台 bars，外部数据（资金/估值/利率/新闻）缺失时整体降级为空，不阻断核心链路。

**情绪回测 / regime 调节验证**（盘后 `step_backtest` 第 4、5 引擎，均 try/except 降级）

| 引擎 | 作用 | 输出 |
|------|------|------|
| 第 4 引擎 `SentimentTimingBacktester` | T2 温度计择时样本外验证（PRD §10 硬指标）：把 `sentiment_index.signal` 作权益暴露叠加在因子 walk-forward 组合上，对照因子满仓 baseline 与等权基准，报告年化/最大回撤/超额 | `backtest_report` 中 `walk_forward_sentiment_timing` / `walk_forward_factor_baseline` |
| 第 5 引擎 `compare_regime` | #4 regime 调节验证：信号层置信度加权多头组合，ON（regime 缩放）/OFF 双跑，差异仅来自情绪缩放 | `backtest_report` 中 `signal_long_only` / `signal_long_only_regime_scaled`，日志打印 ON-OFF 年化/Sharpe/回撤差异（持续监控，正=regime 调节改善风险收益） |

> 第 5 引擎需 ≥20 日信号历史方可回测；随每日运行累积后自动生效（单日运行自动跳过）。

**`backtest`**

| 键 | 默认 | 作用 |
|----|------|------|
| `backtest.initial_capital` | `1000000.0` | 初始资金（绩效展示用） |
| `backtest.benchmark` | `[zz_quan_zhi, hs300]` | 基准（中证全指/沪深300） |
| `backtest.walk_forward.train_window` | `250` | walk-forward 训练窗口（交易日） |
| `backtest.walk_forward.test_window` | `20` | 样本外测试窗口 |
| `backtest.walk_forward.step` | `20` | 滚动步长 |
| `backtest.cost_model.commission` | `0.00025` | 佣金费率 |
| `backtest.cost_model.stamp_duty` | `0.001` | 印花税（卖出） |
| `backtest.cost_model.slippage_bps` | `2.0` | 滑点（bps） |
| `backtest.cost_model.min_commission` | `5.0` | 最低佣金（元） |
| `backtest.cost_model.limit_up_pct` / `limit_down_pct` | `0.10` | 涨跌停限制 |
| `backtest.cost_model.t_plus_one` | `true` | T+1 约束 |

**`llm` / `scheduler`**

| 键 | 默认 | 作用 |
|----|------|------|
| `llm.provider` | `deepseek` | LLM 厂商 |
| `llm.model` | `${DEEPSEEK_MODEL:deepseek-chat}` | 模型（可被 .env 覆盖） |
| `llm.base_url` | `${DEEPSEEK_BASE_URL:https://api.deepseek.com}` | 端点 |
| `llm.api_key_env` | `DEEPSEEK_API_KEY` | 密钥环境变量名 |
| `llm.temperature` | `0.3` | 生成温度 |
| `llm.max_tokens` | `2048` | 最大生成长度 |
| `llm.cache_enabled` | `true` | 请求缓存（省 token） |
| `llm.cache_ttl` | `86400` | 缓存有效期（秒） |
| `scheduler.enabled` | `false` | 定时器开关（生产可开） |
| `scheduler.cron` | `30 18 * * 1-5` | 盘后 18:30 周一至周五 |
| `scheduler.timezone` | `Asia/Shanghai` | 调度时区 |
| `scheduler.run_llm_after` | `18:00` | LLM 简报在此时点后生成 |

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
4. `run_daily(TARGET)`：跑完整 12 步流水线（universe→因子→情绪→预测→体检→中性化→融合→板块→市场情绪→LLM→回测）
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
| `api/routers/monitor.py` | `MonitorService`：跨库只读聚合（数据状态 / 因子健康 / 模型状态 / 管线进度 / 运行历史 / 市场情绪指数） |
| `api/run_store.py` | 运行历史 JSONL 读写（规避 DuckDB 单写者锁） |

### 11.2 Web UI

- **Dashboard 页「运维控制」卡片**：立即更新按钮（轮询进度）+ 自动运行开关 + 进度条（12 步）+ 当前步 / 上次成功日 / 失败告警。
- **Monitor 页（新增 `/monitor`）**：数据状态卡、因子健康卡、模型状态表（Kronos 高亮）、管线实时进度、运行历史表、**市场情绪指数卡**（综合指数/温度计/GSISI/五维分位进度条）。每 4s / 8s 轮询。

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
| GET | `/api/monitor/overview` | 运维总览（数据/因子/模型/管线/市场情绪） |
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
| **市场情绪外部数据** | 缺失可降级 | 融资/北向/估值/10Y 国债/ETF 流接口失败或不可达时，综合指数退化为仅量/价两维；T3 LLM 文本情绪无 key/无新闻自动跳过 |

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
- 技术 / 情绪：扩展 `factors/czsc_signals.py` / `factors/sentiment.py`（个股量价情绪）；市场级综合情绪在 `factors/market_sentiment.py`（五维分位 + 温度计择时 + GSISI），外部数据接入 `sources/sentiment_data.py`。

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
