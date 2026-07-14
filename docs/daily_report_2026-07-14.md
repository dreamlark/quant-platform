# 今日任务总结报告（2026-07-14）

> 项目：A 股日频量化分析平台（quant-platform）· analysis-first（只分析不交易）
> 主题：**市场级综合情绪框架（T0/T1/T2/T3）全链路落地 + 关键 bug 修复 + README 同步 + 提交**

---

## 一、任务总览

| 任务 | 状态 | 说明 |
|------|------|------|
| 修复「400 input length too long」编辑错误 | ✅ 完成 | 拆分大编辑为两次小编辑，绕开工具输入上限 |
| 情绪框架按 PRD 全链路集成 | ✅ 完成 | T0 个股情绪 / T1 市场综合指数 / T2 温度计择时 / T3 LLM 文本情绪 |
| 修复集成中暴露的 3 个真实 bug | ✅ 完成 | T0 索引错位、GSISI 行业键不匹配、GSISI 重采样/形状 |
| 补充单元测试 | ✅ 完成 | `test_sentiment_t0.py` / `test_market_sentiment.py`（共 8 用例） |
| 更新 README 架构文档 | ✅ 完成 | 架构图/步骤数/文件作用表/配置参数/监控/API/限制 |
| 提交改动（commit + push） | ✅ 完成 | 推送到 `dreamlark/quant-platform` master |

---

## 二、详细改动（按模块）

### 1. 数据层（storage）
- `storage/schema.py`
  - 新增 `sentiment_index` 表 DDL（11 字段：综合指数/五维分位/GSISI/regime/thermometer/signal）。
  - `TABLE_ORDER` 追加 `"sentiment_index"`；`init_schema` 现建 **13 张表**。
- `storage/repository.py`
  - `_ANALYTICS_TABLES` 加入 `sentiment_index`。
  - 新增 `save_sentiment_index` / `load_sentiment_index`（按 `date` 幂等 upsert / 读最新）。

### 2. 计算层（factors / sources）
- `factors/sentiment.py`（T0 扩展，重构）
  - 子指标增至 6 个：原 4 个（换手异常/振幅/涨停率/收益偏度）+ **breadth_rank**（横截面收益分位）+ **relative_strength**（N 日超额收益）。
  - 修复 `relative_strength` 索引错位 bug（见 §三）。
- `factors/market_sentiment.py`（**新增**，T1/T2 核心）
  - T1 五维历史分位合成（量/价/资金/估值/风险溢价，缺失维度自动剔除后归一化）→ 综合指数 ∈ [0,100]。
  - T2 华泰温度计择时：恐惧/中性/贪婪 + 买入/半仓/空仓信号。
  - GSISI（国信）行业 Beta 轮动强度。
- `factors/text_sentiment.py`（**新增**，T3）
  - LLM 对财经新闻做语义打分（−1~1）；无 `DEEPSEEK_API_KEY` / 无新闻时门控降级。
- `sources/sentiment_data.py`（**新增**）
  - akshare 多源外部数据：融资融券 / 北向 / 指数估值 / 10Y 国债 / ETF 净流 / 新闻。
  - 本地缓存（`data/raw_cache/sent_*.csv`）+ 失败整体降级为空，不阻断核心链路。

### 3. 编排层（scheduler）
- `scheduler/orchestrator.py`
  - 实例化 `MarketSentiment` / `TextSentiment`。
  - 新增 `step_market_sentiment(date)`：加载外部数据 → 计算综合指数 → 落 `sentiment_index` → 跑 T3 文本情绪（门控）。
  - `run_daily` 步骤 **11 → 12**，顺序：`…→ sector → market_sentiment → llm → backtest`。
- `api/routers/admin.py`
  - `_STEPS` 与 `step_fns` 加入 `market_sentiment`（位于 `sector` 与 `llm` 之间），总步数 12。

### 4. 服务层（api）与前端（web）
- `api/routers/monitor.py`
  - 新增 `_market_sentiment()`，在 `/monitor/overview` 返回市场情绪块（失败降级为 error 字段）。
- `config/settings.yaml`
  - 新增 `market_sentiment` 配置块（分位窗口 / 五维权重 / 温度计阈值 / GSISI 窗口）。
- `web/src/api/client.ts` + `web/src/pages/Monitor.tsx`
  - 类型 `MarketSentimentView`；运维页新增「市场情绪指数」卡片（综合指数/温度计/GSISI/五维分位进度条）。

### 5. 测试（tests）
- `tests/test_sentiment_t0.py`（4 用例）：形状/分数范围/组件完整性/无前视/空输入。
- `tests/test_market_sentiment.py`（4 用例）：结构/五维合成/无前视/GSISI/外部数据齐全路径。

---

## 三、修复的真实 bug（非纯集成）

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| 1 | `factors/sentiment.py` `relative_strength` | `pr`(RangeIndex) 减 `mkt.reindex`(DatetimeIndex) 触发笛卡尔积，长度由 120 变为 240 → 抛 `ValueError` | 改为 `mkt.reindex(...).reset_index(drop=True)` 按位置对齐 |
| 2 | `factors/market_sentiment.py` `_gsisi` | `industry_map` 键带 `.SH/.SZ` 后缀，而内部先 `.str.split('.')[0]` 再去后缀 → 全部落空退化为 0 | `map` 时同时尝试「去后缀 / 不去后缀」两种键匹配 |
| 3 | `factors/market_sentiment.py` `_gsisi` | `bars.date` 是 `datetime.date`（非 DatetimeIndex）导致 `resample` 失败；且 `groupby.apply` 直接返回「行业×周」DataFrame 后再 `.unstack(level=0)` 破坏结构 | 改用 `pivot_table` + `resample("W-FRI")`；顺带消除 groupby.apply 弃用告警 |

---

## 四、验证结果

- **单元/集成测试**：`pytest tests/test_sentiment_t0.py tests/test_market_sentiment.py tests/test_api_qa.py` → **10 passed**。
- **冒烟测试**：`tests/test_smoke.py` 核心链路（ingest→…→signals）通过，Deflated Sharpe 正常产出。
- **端到端集成**：内存库 + 编排器 `step_market_sentiment` 落库读回正常，返回 1 行；`init_schema` 建 13 张表。
- **降级验证**：无密钥 / akshare 接口名差异时，外部数据整体降级为空、T3 文本情绪跳过，仅量/价两维仍由本平台 bars 计算（综合指数回退中性 50.0，符合不足 750 日分位窗口的预期）。
- **编译**：全部改动 Python 文件 `py_compile` 通过；`settings.yaml` 可被 `load_settings` 正常加载。

---

## 五、提交信息

- 分支：`master` → 推送到 `origin/master`
- 类型：`feat`（情绪框架）+ 同步 `docs`（`README` 更新）、`test`
- 范围：13 个改动文件 + 6 个新增文件（未纳入 3 个 `_kronos_eval_ckpt_*.json` 评估产物，按 `.gitignore` 口径保持仓库干净）

---

## 六、风险与后续

- **外部数据可用性**：融资/北向/ETF 等 akshare 接口名与可达性随环境波动，已做降级；生产环境建议接入更稳定的数据源并补充缓存命中校验。
- **分位窗口**：默认 `percentile_window=750`（约 3 年），需足够历史；样本不足时综合指数回退中性 50，属预期行为。
- **T3 LLM 文本情绪**：当前仅产出聚合得分、未持久化进 `sentiment_index`（PRD 定位为辅助下行预警）。如需落库，需在表结构中加 `text_sentiment` 列并在 `step_market_sentiment` 合并写入。
- **GSISI**：依赖行业映射与 ≥3 个行业的周收益，单行业或样本不足时返回 0.0（不影响主指数）。

---

> 生成时间：2026-07-14 · 由 WorkBuddy 整理
