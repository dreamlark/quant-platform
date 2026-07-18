# LLM 接入审核 + 实时热点语义分析方案设计

> **文档状态**：待评审
> **日期**：2026-07-17
> **作者**：AI 工程师审核
> **关联系统**：quant-platform 四源融合（因子 0.40 / 技术 0.20 / 情绪 0.15 / 预测 0.25）

---

## 第一部分：LLM 相关代码审核报告

### 1. 审核范围

| 文件 | 职责 |
|------|------|
| `llm/client.py` | LLM 客户端（DeepSeek V3，OpenAI 兼容） |
| `llm/prompts.py` | System Prompt 模板（合规约束内置） |
| `llm/brief_gen.py` | 市场综合简报生成（盘后批量） |
| `llm/stock_review.py` | 自选股逐只简评 |
| `llm/agent_interface.py` | 多 Agent 研判预留接口（未实现） |
| `llm/factor_mining_if.py` | 自动因子挖掘预留接口（未实现） |
| `factors/text_sentiment.py` | LLM 文本情绪（T3，门控降级） |
| `sources/sentiment_data.py` | 情绪外部数据层（含 `load_news`） |
| `config/settings.yaml` | LLM 配置段 |
| `scheduler/orchestrator.py` | 编排器（`step_llm` / `step_market_sentiment`） |

---

### 2. 审核发现

#### 2.1 ✅ 做得好的部分

| 项 | 评价 |
|----|------|
| **降级策略** | `LLMClient._get_client()` 无密钥返回 `None`；`chat()` 捕获异常后降级为离线占位。核心链路无密钥可跑，符合 analysis-first 定位。 |
| **合规红线** | `prompts.py` 内置 `COMPLIANCE_PREFIX`，明确"分析信号/研究观点"定位；`StockReviewer` 中 action 由信号方向映射，confidence 取信号层，禁止 LLM 自报。设计严谨。 |
| **缓存** | MD5(system+user) 做内存缓存，避免重复调用。合理。 |
| **重试** | `tenacity` 3 次指数退避（2-10s），适合 API 偶发抖动。 |
| **配置驱动** | `${ENV:default}` 占位解析，密钥不硬编码。规范。 |
| **预留接口** | `AgentInterface` / `FactorMiningInterface` 干净边界，`NotImplementedError` 明确标注 P2，不污染核心链路。 |

#### 2.2 ⚠️ 需要改进的问题

**P1（重要）—— 影响实时热点语义分析接入**

| # | 文件 | 问题 | 影响 | 建议 |
|---|------|------|------|------|
| 1 | `llm/client.py` | **只有 `chat()` 方法，无 `complete()` 方法**。但 `factors/text_sentiment.py` 第 24 行调用 `self.llm.complete(prompt)`，方法签名不匹配 | TextSentiment 永远走降级跳过路径，LLM 文本情绪功能形同虚设 | 新增 `complete()` 方法或统一为 `chat()` 调用 |
| 2 | `llm/client.py` | **无流式输出（streaming）支持**。`chat()` 一次性返回完整文本 | 实时热点分析需要逐 token 推送前端，无 streaming 则"实时"体验差 | 新增 `chat_stream()` 异步生成器 |
| 3 | `llm/client.py` | **无异步支持**。同步 `openai.OpenAI` 客户端在 FastAPI 中会阻塞事件循环 | 实时热点 API 若走同步路径，并发请求时阻塞 | 新增 `AsyncLLMClient` 或使用 `openai.AsyncOpenAI` |
| 4 | `llm/client.py` | **无 function calling / structured output 支持**。热点分析需结构化输出（实体、情感、关联标的） | 当前只能正则解析自由文本，脆弱 | 支持 `response_format={"type": "json_object"}` 或 function calling |
| 5 | `llm/prompts.py` | **无热点/新闻语义分析 prompt 模板**。仅有简报和个股简评两类 | 新需求需从零编写 prompt | 新增热点语义分析专用 prompt 系列 |
| 6 | `factors/text_sentiment.py` | **实现过于简陋**：将 200 条新闻标题拼接成一个 prompt，让 LLM 输出单个数字。无分标的情感、无实体提取、无主题聚类 | 无法支撑"实时热点语义分析"需求 | 重构为热点语义分析模块 |
| 7 | `sources/sentiment_data.py` | `load_news()` 仅支持单股票代码拉取 akshare 新闻，**无批量/全市场新闻源**，无财经媒体 RSS、无社交媒体数据 | 数据源不足以支撑实时热点 | 新增多源新闻/热点数据采集 |
| 8 | `llm/client.py` | **无 token 用量追踪**。不记录 prompt_tokens / completion_tokens | 无法监控成本和速率限制 | 在 `chat()` 返回中附带 usage 信息 |

**P2（建议改进）**

| # | 文件 | 问题 | 建议 |
|---|------|------|------|
| 9 | `llm/client.py` | 缓存仅内存，进程重启丢失 | 可选落盘缓存（SQLite/文件），与 `cache_ttl` 配置对齐 |
| 10 | `llm/client.py` | `max_tokens=2048` 硬编码默认值偏低，热点分析可能需要更长输出 | 按场景区分 `max_tokens` |
| 11 | `llm/brief_gen.py` | 简报上下文构造仅传文本摘要，未传结构化 JSON | LLM 可能遗漏或误读数据；可改为 JSON 上下文 |
| 12 | `scheduler/orchestrator.py` | `step_llm` 在 `step_market_sentiment` 之后执行，但 `text_sentiment.analyze()` 的结果未回写任何存储 | 文本情绪计算结果丢失，不进融合 | 需定义文本情绪的落库和融合路径 |

#### 2.3 🔴 关键阻塞问题

**`text_sentiment.py` 与 `client.py` 的接口断裂（问题 #1）**

```python
# text_sentiment.py 第 24 行
if self.llm is None or not hasattr(self.llm, "complete"):
    logger.info("文本情绪：LLM 未配置或不支持 complete（离线降级），跳过")
    return pd.DataFrame()

# 但 LLMClient 只有 chat(system, user) 方法，没有 complete(prompt) 方法
# → hasattr(self.llm, "complete") 永远为 False
# → TextSentiment.analyze() 永远返回空 DataFrame
# → T3 文本情绪功能从未真正运行过
```

这是一个**接口一致性 bug**，说明 T3 文本情绪模块虽然写了代码，但由于接口断裂从未被真正测试过。

---

### 3. LLM 接入现状总结

```
LLMClient (DeepSeek V3)
  ├── chat(system, user) → str        ✅ 可用（盘后简报 + 个股简评）
  ├── complete(prompt) → str          ❌ 不存在（TextSentiment 调用失败）
  ├── chat_stream(...) → AsyncGen     ❌ 不存在（无法实时推送）
  ├── structured_output(...) → dict   ❌ 不存在（无法 JSON 结构化）
  └── usage tracking                  ❌ 不存在

实际接入情况：
  ├── BriefGenerator.generate_market_brief()  ✅ 已接入（盘后简报）
  ├── StockReviewer.review()                  ✅ 已接入（个股简评）
  ├── TextSentiment.analyze()                 ❌ 接口断裂，从未运行
  ├── AgentInterface.run_agents()             🔲 预留未实现
  └── FactorMiningInterface.mine_factors()    🔲 预留未实现
```

**结论：LLM 已接入两个盘后批量场景（简报 + 简评），但实时/文本语义分析路径完全断裂。**

---

## 第二部分：实时热点语义分析方案设计

### 1. 需求理解

在现有四源融合基础上，增加**实时热点语义分析**模块，辅助量化投资决策。核心能力：

1. **热点信息搜集**：建立持续运行的多源信息采集系统，实时捕获财经新闻、公告、社交媒体文本流
2. **语义分析**：LLM 提取主题、实体（公司/行业/概念）、情感倾向、影响力评估
3. **标的关联**：将热点语义映射到 A 股标的池
4. **信号融合**：热点语义信号作为情绪源的增强维度接入融合池
5. **实时推送**：前端可通过 SSE 接收实时热点推送

> **关键认知**：热点信息搜集不是一个函数调用，而是一个**持续运行的采集子系统**。
> 它需要独立于盘后批处理流水线，在交易时段实时运转，是整个方案的地基。

### 2. 设计约束（继承项目红线）

- **analysis-first**：只分析不交易，热点产物为"研究观点/语义信号"
- **合规**：LLM 输出定位为分析信号，置信度由信号层传入，禁止自报
- **降级**：无 API Key / 无新闻源时降级为空，不阻断主流水线
- **point-in-time**：热点时间戳精确到分钟，不可有未来信息泄漏
- **成本可控**：LLM 调用需批量化、缓存、速率限制

### 3. 架构设计

```
┌──────────────────────────────────────────────────────────────────────┐
│                   实时热点语义分析子系统                               │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              热点信息搜集系统 (HotspotCollector)               │  │
│  │              sources/hotspot_collector.py (新增)               │  │
│  │                                                               │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │  │
│  │  │ akshare源   │  │ 财联社电报   │  │ 东方财富股吧 │           │  │
│  │  │ stock_news  │  │ RSS/爬虫    │  │ 热帖爬虫     │           │  │
│  │  │ _em         │  │             │  │              │           │  │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬───────┘           │  │
│  │         │                │                │                   │  │
│  │         ▼                ▼                ▼                   │  │
│  │  ┌─────────────────────────────────────────────┐              │  │
│  │  │            统一清洗 + 去重层                  │              │  │
│  │  │  · SimHash 标题去重 (相似度 > 0.85 合并)     │              │  │
│  │  │  · 内容 MD5 精确去重                          │              │  │
│  │  │  · 时间戳归一化 (ISO-8601 + Asia/Shanghai)   │              │  │
│  │  │  · 源标记 + 原始文本保留                      │              │  │
│  │  └────────────────────┬────────────────────────┘              │  │
│  │                       │                                       │  │
│  │                       ▼                                       │  │
│  │              HotspotItem 列表                                  │  │
│  │              {ts, source, title, content, url}                │  │
│  └───────────────────────┬───────────────────────────────────────┘  │
│                          │                                          │
│                          ▼                                          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              预处理 & 批量化调度 (BatchScheduler)              │  │
│  │                                                               │  │
│  │  · 攒批: 每 5-10 条或 30s 触发一次 LLM 分析                    │  │
│  │  · 缓存: 分析结果按内容 hash 缓存 24h                          │  │
│  │  · 速率限制: ≤10 次/min (DeepSeek V3 限额内)                   │  │
│  │  · 优先级队列: 高影响力文本插队                                │  │
│  └───────────────────────┬───────────────────────────────────────┘  │
│                          │                                          │
│                          ▼                                          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              LLM 语义分析引擎 (HotspotAnalyzer)                │  │
│  │              llm/hotspot_analyzer.py (新增)                    │  │
│  │                                                               │  │
│  │  ├── 主题提取 (topic)                                          │  │
│  │  ├── 实体识别 NER (公司/行业/概念)                              │  │
│  │  ├── 情感打分 (sentiment ∈ [-1, 1])                            │  │
│  │  ├── 影响力评估 (impact ∈ [0, 1])                              │  │
│  │  └── 标的关联映射 (related_codes ← 股票池白名单匹配)            │  │
│  │                                                               │  │
│  │  输出: HotspotSignal                                          │  │
│  │    {ts, topic, sentiment, impact, related_codes, ...}         │  │
│  └───────────────────────┬───────────────────────────────────────┘  │
│                          │                                          │
│                          ▼                                          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                      信号消费层                                 │  │
│  │                                                               │  │
│  │  ├── 落库: hotspot_signals 表 (DuckDB)                        │  │
│  │  ├── 融合: 注入 sentiment 分支 (作为情绪增强维度)              │  │
│  │  ├── API: /api/hotspot/* (REST + SSE 推送)                    │  │
│  │  └── 看板: Web 热点卡片 + 标的关联图                           │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### 4. 热点信息搜集系统（核心地基）

> 这是整个方案中最关键的部分——没有持续的高质量文本输入，LLM 语义分析就是无米之炊。

#### 4.1 现状分析

项目现有的文本数据能力：

| 能力 | 文件 | 状态 |
|------|------|------|
| 个股新闻拉取 | `sources/sentiment_data.py:load_news()` | ✅ 可用（akshare `stock_news_em`，但单股票、无增量、无全市场） |
| 行情数据采集 | `sources/akshare_adapter.py` 等 | ✅ 完善（多源冗余 + 路由降级） |
| 行业/市值元数据 | `sources/market_meta.py` | ✅ 可用（申万行业 + 腾讯市值） |
| 全市场新闻/热点采集 | **无** | ❌ **完全缺失** |
| 实时文本流采集 | **无** | ❌ **完全缺失** |
| 文本去重/清洗 | **无** | ❌ **完全缺失** |

**结论**：项目的行情数据采集层很成熟（多源路由 + 冗余降级），但文本/热点信息采集层完全是空白。需要从头构建。

#### 4.2 数据源选型与可行性评估

##### 可用数据源矩阵

| 数据源 | 实时性 | 覆盖面 | 接入方式 | 成本 | 优先级 | 说明 |
|--------|--------|--------|----------|------|--------|------|
| **akshare `stock_news_em`** | 分钟级 | 单股票 | Python API | 免费 | P0 | 已有依赖，零接入成本；但需遍历股票池，效率低 |
| **akshare `news_economic_baidu`** | 分钟级 | 全市场 | Python API | 免费 | P0 | 百度财经新闻，全市场覆盖，无需逐股票拉取 |
| **akshare `stock_info_global_em`** | 分钟级 | 全市场 | Python API | 免费 | P0 | 东方财富全球新闻流 |
| **akshare `stock_info_a_code_name`** | - | 全市场 | Python API | 免费 | P0 | 股票代码名称映射（构建白名单） |
| **财联社电报** | 秒级 | 全市场 | RSS/爬虫 | 免费 | P1 | A 股最快电报源；需自建爬虫或用第三方 RSS |
| **东方财富股吧热帖** | 分钟级 | 单股票 | 爬虫 | 免费 | P2 | 散户情绪代理；需爬虫 + 反爬处理 |
| **巨潮信息公告** | 分钟级 | 全市场 | RSS/API | 免费 | P2 | 官方信源，事件驱动型；akshare 有封装 |
| **新浪财经新闻** | 分钟级 | 全市场 | 爬虫 | 免费 | P3 | 备用源 |
| **Tushare 新闻** | 分钟级 | 全市场 | API | 付费 | P3 | 需 Tushare Pro 积分 |

##### 推荐数据源组合

**P0（立即可用，零额外成本）**：
1. `akshare.news_economic_baidu` — 全市场财经新闻流（百度财经聚合）
2. `akshare.stock_news_em` — 重点个股新闻（补充个股粒度）
3. `akshare.stock_info_global_em` — 东方财富全球新闻流

**P1（第二步，需自建采集器）**：
4. 财联社电报 — A 股实时性最强的信源

**P2（第三步，按需扩展）**：
5. 股吧热帖 — 散户情绪代理
6. 巨潮公告 — 官方事件驱动

#### 4.3 热点信息搜集系统设计：`sources/hotspot_collector.py`（新增）

```python
"""热点信息搜集系统（持续运行的多源文本采集器）。

设计原则：
- 与行情数据源层（DataSource/DataSourceRouter）平级，作为文本数据源层
- 多源并发采集 + 统一清洗去重 + 增量追踪
- 每个源独立降级：任一源失败不阻断其他源
- 采集器可独立运行（实时守护），也可被编排器调用（盘后批量）
- 输出统一的 HotspotItem 格式，供 LLM 分析引擎消费
"""

from __future__ import annotations
import abc
import datetime as dt
import hashlib
import threading
from typing import Any, Dict, List, Optional, Generator
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class HotspotItem:
    """统一热点文本条目（所有数据源的归一化输出）。"""
    ts: dt.datetime           # 发布时间（归一化为 Asia/Shanghai）
    source: str               # 数据来源标识
    title: str                # 标题
    content: str              # 正文内容（可能为空，仅有标题）
    url: str = ""             # 原始链接
    related_codes: List[str] = field(default_factory=list)  # 源端标记的关联股票（可能为空）
    raw: Dict[str, Any] = field(default_factory=dict)       # 原始数据（审计用）


class HotspotSource(abc.ABC):
    """热点数据源抽象基类（与 DataSource 平级，但面向文本流）。"""

    name: str = "base"
    priority: int = 99

    @abc.abstractmethod
    def fetch_since(self, since: dt.datetime, limit: int = 100) -> List[HotspotItem]:
        """拉取指定时间之后的增量热点文本。"""

    def health_check(self) -> bool:
        return True


class BaiduNewsSource(HotspotSource):
    """百度财经全市场新闻流（akshare news_economic_baidu）。"""
    name = "baidu_finance"
    priority = 1

    def fetch_since(self, since: dt.datetime, limit: int = 100) -> List[HotspotItem]:
        import akshare as ak
        # ak.news_economic_baidu返回全市场财经新闻
        # 字段: date, title, content
        # 优点: 全市场覆盖，无需逐股票拉取
        ...


class EastmoneyGlobalSource(HotspotSource):
    """东方财富全球新闻流（akshare stock_info_global_em）。"""
    name = "eastmoney_global"
    priority = 2

    def fetch_since(self, since: dt.datetime, limit: int = 100) -> List[HotspotItem]:
        ...


class StockNewsSource(HotspotSource):
    """个股新闻（akshare stock_news_em，遍历重点股票池）。

    与全市场源互补：全市场源覆盖面广但个股粒度粗；
    个股源逐股票拉取但能拿到精准的 related_codes。
    仅遍历可投资域 top N（如 HS300 成分），控制调用量。
    """
    name = "stock_news"
    priority = 3

    def __init__(self, codes: List[str], per_code_limit: int = 5):
        self.codes = codes
        self.per_code_limit = per_code_limit

    def fetch_since(self, since: dt.datetime, limit: int = 100) -> List[HotspotItem]:
        # 复用已有 sources/sentiment_data.load_news()，但改为批量遍历
        ...


class CLSTelegraphSource(HotspotSource):
    """财联社电报（P1，需自建采集器）。

    财联社电报是 A 股市场实时性最强的文本信源（秒级），
    内容包括重大事件、政策发布、公司公告等。
    采集方式：RSS feed 或网页爬虫（需反爬处理）。
    """
    name = "cls_telegraph"
    priority = 10  # P1，需额外开发

    def fetch_since(self, since: dt.datetime, limit: int = 100) -> List[HotspotItem]:
        # 方案A: 财联社 RSS feed（如果可用）
        # 方案B: 爬虫 + 反爬（requests/httpx + 随机延迟）
        # 方案C: 第三方聚合 RSS（如今日热榜 tophub.today）
        raise NotImplementedError("财联社电报采集器待 P1 阶段实现")


class HotspotCollector:
    """热点信息搜集系统主控（多源并发 + 去重 + 增量追踪）。

    运行模式：
    1. 实时守护模式：后台线程每 60s 轮询所有源，产出增量 HotspotItem
    2. 批量模式：盘后一次性拉取当日全部热点（供 orchestrator 调用）
    3. 被动模式：供 API 按需调用拉取最新热点
    """

    def __init__(
        self,
        sources: List[HotspotSource],
        dedup_threshold: float = 0.85,
        cache_dir: str = "./data/hotspot_cache",
    ):
        self.sources = sorted(sources, key=lambda s: s.priority)
        self.dedup_threshold = dedup_threshold
        self.cache_dir = cache_dir
        self._seen_hashes: set[str] = set()  # 内容 hash 去重
        self._seen_simhashes: List[int] = []  # SimHash 近似去重
        self._lock = threading.Lock()
        self._last_fetch: Dict[str, dt.datetime] = {}  # 每个源的上次拉取时间

    def collect_incremental(self, since: Optional[dt.datetime] = None) -> List[HotspotItem]:
        """增量采集：拉取所有源的增量文本，去重后返回。"""
        all_items: List[HotspotItem] = []
        for src in self.sources:
            if not src.health_check():
                logger.warning(f"热点源 {src.name} 健康检查失败，跳过")
                continue
            try:
                items = src.fetch_since(since or self._last_fetch.get(src.name))
                all_items.extend(items)
                self._last_fetch[src.name] = dt.datetime.now()
            except Exception as exc:
                logger.warning(f"热点源 {src.name} 采集失败（降级）：{exc}")

        # 去重
        unique = self._dedup(all_items)
        logger.info(f"热点采集：{len(all_items)} 条 → 去重后 {len(unique)} 条")
        return unique

    def _dedup(self, items: List[HotspotItem]) -> List[HotspotItem]:
        """双重去重：MD5 精确去重 + SimHash 近似去重。"""
        result = []
        for item in items:
            # 精确去重
            h = hashlib.md5(item.title.encode()).hexdigest()
            if h in self._seen_hashes:
                continue
            # 近似去重（SimHash）
            sh = self._simhash(item.title)
            if self._is_similar(sh, self.dedup_threshold):
                continue
            self._seen_hashes.add(h)
            self._seen_simhashes.append(sh)
            result.append(item)
        return result

    @staticmethod
    def _simhash(text: str) -> int:
        """简化 SimHash：用于标题近似去重。"""
        ...

    def _is_similar(self, sh: int, threshold: float) -> bool:
        """汉明距离判断相似度。"""
        ...

    def run_daemon(self, interval_seconds: int = 60, callback=None):
        """实时守护模式：每 interval_seconds 秒采集一次，通过 callback 推送结果。

        callback 签名: callback(items: List[HotspotItem]) -> None
        用于 SSE 推送场景。
        """
        def _loop():
            while True:
                try:
                    items = self.collect_incremental()
                    if items and callback:
                        callback(items)
                except Exception as exc:
                    logger.error(f"热点采集守护异常：{exc}")
                import time
                time.sleep(interval_seconds)

        t = threading.Thread(target=_loop, daemon=True, name="hotspot-collector")
        t.start()
        return t
```

#### 4.4 与现有数据源架构的关系

```
现有数据源架构（sources/）:

  DataSource (抽象基类)              ← 行情数据
    ├── MootdxDailyAdapter           日 K 线
    ├── AkshareDailyAdapter          日 K 线（冗余）
    ├── BaostockDailyAdapter         日 K 线（冗余）
    └── DataSourceRouter             多源路由 + 降级

  sentiment_data.py                  ← 情绪外部数据（资金/估值/利率）
    ├── load_margin()                融资融券
    ├── load_northbound()            北向资金
    ├── load_index_valuation()       指数估值
    ├── load_bond_yield()            国债收益率
    ├── load_etf_flow()              ETF 流量
    └── load_news()                  个股新闻（单股票，简陋）

  market_meta.py                     ← 市场元数据
    ├── fetch_market_cap()           总市值
    └── fetch_industry_map()         申万行业映射

新增（sources/hotspot_collector.py）:

  HotspotSource (抽象基类)           ← 文本热点数据（与 DataSource 平级）
    ├── BaiduNewsSource              百度财经全市场新闻
    ├── EastmoneyGlobalSource        东方财富全球新闻
    ├── StockNewsSource              个股新闻（遍历重点池）
    ├── CLSTelegraphSource (P1)      财联社电报
    └── HotspotCollector             多源采集主控 + 去重 + 守护
```

**设计要点**：
- `HotspotSource` 与 `DataSource` 平级抽象，但面向文本流而非行情数据
- `HotspotCollector` 类比 `DataSourceRouter`，做多源路由 + 降级 + 去重
- 采集器可独立运行（实时守护线程），也可被编排器调用（盘后批量）
- 与 `sentiment_data.py` 的 `load_news()` 是替代关系：新采集器更通用、更完整

#### 4.5 LLM 语义分析引擎：`llm/hotspot_analyzer.py`（新增）

```python
class HotspotAnalyzer:
    """热点文本 LLM 语义分析引擎。"""

    def __init__(self, llm: LLMClient, stock_universe: list[str]):
        self.llm = llm
        self.stock_map = self._build_stock_map(stock_universe)  # code → name/industry

    async def analyze_batch(self, items: list[HotspotItem]) -> list[HotspotSignal]:
        """批量分析热点文本，返回结构化信号。"""
        # 1. 按 batch_size 分批（建议 5-10 条/批，控制 token）
        # 2. 构造 prompt：系统指令 + 股票映射表 + 新闻批次
        # 3. 调用 LLM with response_format=json_object
        # 4. 解析 + 校验 + 落库

    async def analyze_stream(self, item: HotspotItem) -> AsyncGenerator[str, None]:
        """单条热点的流式分析（用于 SSE 实时推送）。"""
```

**Prompt 设计**（新增到 `llm/prompts.py`）：

```python
SYSTEM_HOTSPOT = (
    COMPLIANCE_PREFIX
    + "你是 A 股市场热点语义分析引擎。对输入的财经新闻/电报文本批次，输出 JSON 数组，"
    "每个元素包含：\n"
    "  - topic: 主题概括（≤20字）\n"
    "  - sentiment: 情感倾向 ∈ {利好, 利空, 中性}\n"
    "  - sentiment_score: 情感分值 ∈ [-1, 1]\n"
    "  - impact: 影响力 ∈ {高, 中, 低}\n"
    "  - impact_score: 影响力分值 ∈ [0, 1]\n"
    "  - related_sectors: 关联板块列表\n"
    "  - related_codes: 关联股票代码列表（从提供的股票池中匹配）\n"
    "  - reasoning: 判断依据（≤50字）\n"
    "严格基于文本内容分析，不得编造未提及的信息。"
)
```

**输出结构**：

```python
@dataclass
class HotspotSignal:
    ts: datetime          # 热点时间戳
    source: str           # 数据来源
    title: str            # 原始标题
    topic: str            # LLM 提取主题
    sentiment: str        # 利好/利空/中性
    sentiment_score: float  # [-1, 1]
    impact: str           # 高/中/低
    impact_score: float   # [0, 1]
    related_sectors: list[str]
    related_codes: list[str]
    reasoning: str
    # 复合信号：sentiment_score × impact_score
    composite_score: float  # [-1, 1]
```

#### 4.6 LLMClient 增强：`llm/client.py`（修改）

需新增以下方法：

```python
class LLMClient:
    # ... 现有代码保持不变 ...

    def chat_json(self, system: str, user: str, use_cache: bool = True) -> dict:
        """结构化 JSON 输出（利用 response_format=json_object）。"""

    async def chat_stream(self, system: str, user: str) -> AsyncGenerator[str, None]:
        """流式输出（用于 SSE 实时推送）。需 AsyncOpenAI 客户端。"""

    def complete(self, prompt: str) -> str:
        """单轮完成（兼容 TextSentiment 旧调用）。内部转为 chat("", prompt)。"""

    @property
    def last_usage(self) -> dict:
        """最近一次调用的 token 用量。"""
```

#### 4.7 存储层：`storage/schema.py`（修改）

新增 `hotspot_signals` 表：

```sql
CREATE TABLE IF NOT EXISTS hotspot_signals (
    ts              TIMESTAMP,     -- 热点时间戳
    source          VARCHAR,       -- 数据来源
    title           VARCHAR,       -- 原始标题
    topic           VARCHAR,       -- LLM 提取主题
    sentiment       VARCHAR,       -- 利好/利空/中性
    sentiment_score DOUBLE,        -- [-1, 1]
    impact          VARCHAR,       -- 高/中/低
    impact_score    DOUBLE,        -- [0, 1]
    related_sectors VARCHAR,       -- 关联板块（逗号分隔）
    related_codes   VARCHAR,       -- 关联股票（逗号分隔）
    reasoning       VARCHAR,       -- 判断依据
    composite_score DOUBLE,        -- 复合信号分值
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts, source, title)
);
```

#### 4.8 融合接入：`fusion/signal_pool.py`（修改）

在 `fuse()` 方法中，将热点语义信号作为情绪源的**增强维度**注入：

```python
# 热点语义增强情绪：
# 1. 按标的聚合当日热点信号：每个 code 的 composite_score 加权汇总
# 2. 与现有 sentiment_score 做加权融合：
#    final_sentiment = α × sentiment_score + (1-α) × hotspot_sentiment
#    α 默认 0.7（保持原有情绪主导，热点为辅）
# 3. 仅影响 sentiment_contrib，不改融合四源权重
```

#### 4.9 API 层：`api/routers/hotspot.py`（新增）

```python
router = APIRouter(prefix="/api/hotspot", tags=["hotspot"])

@router.get("/latest")
async def get_latest(limit: int = 50):
    """获取最近热点信号列表。"""

@router.get("/stream")
async def hotspot_stream():
    """SSE 实时热点推送。"""

@router.get("/by-code/{code}")
async def get_by_code(code: str, days: int = 7):
    """按标的查询关联热点。"""

@router.get("/by-sector/{sector}")
async def get_by_sector(sector: str, days: int = 7):
    """按板块查询关联热点。"""

@router.get("/digest")
async def get_digest(date: str = None):
    """今日热点语义摘要（LLM 生成）。"""
```

#### 4.10 调度层：`scheduler/orchestrator.py`（修改）

在 `run_daily()` 中新增 `step_hotspot` 步骤（位于 `step_market_sentiment` 之后、`step_llm` 之前）：

同时，热点采集器可在 **调度器外独立运行**（实时模式）：

```python
def step_hotspot(self, date: dt.date) -> pd.DataFrame:
    """实时热点语义分析（盘后批量 + 实时增量）。"""
    # 1. 拉取当日增量热点文本
    # 2. LLM 批量语义分析
    # 3. 落库 hotspot_signals
    # 4. 聚合为个股级热点情绪，注入 step_fusion 的 sentiment 分支
```

```python
# scheduler/hotspot_runner.py（新增）
class HotspotRunner:
    """实时热点采集 + 分析守护进程。"""

    def __init__(
        self,
        collector: HotspotCollector,
        analyzer: HotspotAnalyzer,
        repo: Repository,
        poll_interval: int = 60,
    ):
        self.collector = collector
        self.analyzer = analyzer
        self.repo = repo
        self.poll_interval = poll_interval
        self._subscribers: list[asyncio.Queue] = []  # SSE 订阅者

    async def run(self):
        """主循环：每 poll_interval 秒采集 → 分析 → 落库 → 推送。"""
        while True:
            # 1. 采集
            items = self.collector.collect_incremental()
            if not items:
                await asyncio.sleep(self.poll_interval)
                continue
            # 2. LLM 批量分析
            signals = await self.analyzer.analyze_batch(items)
            # 3. 落库
            self.repo.save_hotspot_signals(signals)
            # 4. 推送到 SSE 订阅者
            for q in self._subscribers:
                for s in signals:
                    await q.put(s)
            await asyncio.sleep(self.poll_interval)

    def subscribe(self) -> asyncio.Queue:
        """SSE 端点订阅实时热点推送。"""
        q = asyncio.Queue()
        self._subscribers.append(q)
        return q
```

### 5. 实时推送方案

```
前端 (Web)
  │
  ├── EventSource("/api/hotspot/stream")  ← SSE 长连接
  │
  ▼
FastAPI SSE Endpoint
  │
  ├── 从 DuckDB 读取最新 hotspot_signals
  │
  ▼
HotspotRunner (后台任务)
  │
  ├── 每 60s 轮询多源数据
  ├── LLM 批量分析
  ├── 落库
  └── 通过 asyncio.Queue 推送到 SSE 连接
```

**选择 SSE 而非 WebSocket 的理由**：
- 热点推送是单向（服务端→客户端），SSE 足够
- SSE 自带断线重连，实现更简单
- FastAPI 原生支持 `StreamingResponse`
- 无需双向通信

### 6. 成本控制策略

| 策略 | 说明 |
|------|------|
| **批量分析** | 5-10 条新闻/批，减少 LLM 调用次数 |
| **去重** | 标题 SimHash + 内容 MD5 双重去重，避免重复分析 |
| **缓存** | 同一文本 hash 的分析结果缓存 24h |
| **速率限制** | LLM 调用不超过 10 次/分钟（DeepSeek V3 限额内） |
| **降级** | 无 API Key 时整体跳过，不影响核心链路 |
| **Token 监控** | 记录每次调用的 prompt_tokens / completion_tokens，超阈值告警 |
| **分级处理** | 高影响力热点（impact=高）才触发 LLM 深度分析；中低影响力用规则模板 |

### 7. 实施计划（分阶段）

| 阶段 | 内容 | 改动文件 | 工作量 | 交付物 |
|------|------|----------|--------|--------|
| **H1** | LLMClient 增强 + 修复接口断裂 | `llm/client.py` | 中 | `chat_json()`, `chat_stream()`, `complete()`, `last_usage` |
| **H2** | **热点信息搜集系统**（核心地基） | `sources/hotspot_collector.py` (新) | **高** | 多源采集器 + 去重 + 增量追踪 + 守护模式 |
| **H3** | LLM 热点语义分析引擎 | `llm/hotspot_analyzer.py` (新), `llm/prompts.py` (改) | 中 | `analyze_batch()`, `analyze_stream()` |
| **H4** | 存储 + API + 融合接入 | `storage/schema.py` (改), `api/routers/hotspot.py` (新), `fusion/signal_pool.py` (改) | 中 | 落库 + REST API + SSE + 融合增强 |
| **H5** | 调度编排 + 实时守护 | `scheduler/orchestrator.py` (改), `scheduler/hotspot_runner.py` (新) | 低 | 盘后批量 + 实时轮询守护 |
| **H6** | 前端热点看板 | `web/src/pages/Hotspot.tsx` (新) | 中 | 热点卡片 + 标的关联图 + 实时流 |

**建议顺序**：H1 → H2 → H3 → H4 → H5 → H6

> **H2 是整个方案的关键路径**。热点信息搜集系统的数据质量直接决定 LLM 分析的输出质量。
> 如果 H2 数据源不足或采集不稳定，后续 H3-H6 都是无源之水。

每阶段独立可交付、可测试、可降级。

#### H2 详细拆分

| 子阶段 | 内容 | 数据源 | 验收 |
|--------|------|--------|------|
| H2-a | akshare 全市场新闻源接入 | `news_economic_baidu` + `stock_info_global_em` | 可拉取最近 100 条全市场新闻，输出统一 HotspotItem |
| H2-b | 个股新闻源接入 | `stock_news_em`（遍历 HS300 top 50） | 可拉取重点个股新闻，带 related_codes |
| H2-c | 去重层 | SimHash + MD5 | 重复标题过滤率 > 80%，无误杀 |
| H2-d | 守护模式 + 增量追踪 | 全部 P0 源 | 60s 轮询可稳定产出增量，无遗漏 |
| H2-e | 财联社电报（P1） | RSS/爬虫 | 秒级电报可实时采集（按需开发） |

### 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| **LLM 幻觉**：虚构关联标的 | 严格限定从提供的股票池中匹配；对 LLM 输出的 related_codes 做白名单校验 |
| **数据源不稳定**：akshare 接口限频/变更 | 多源冗余 + 缓存 + 降级，任一源失败不阻断 |
| **成本失控**：热点过多导致 LLM 调用爆炸 | 批量化 + 去重 + 速率限制 + 高影响力才深度分析 |
| **延迟过大**：实时性不足 | SSE 流式推送 + 60s 轮询周期；高影响力热点走单独快速通道 |
| **前视偏差**：热点时间戳不精确 | 严格记录 ts，融合时只用 ≤ 当日收盘的热点 |
| **过拟合**：热点信号噪声大 | composite_score 加权进入情绪分支（α=0.7 主导），不直接改变四源权重 |

### 9. 与现有系统的关系

```
现有四源融合：
  因子(0.40) + 技术(0.20) + 情绪(0.15) + 预测(0.25)
                                    ↑
                          热点语义分析注入此处
                          （作为情绪源的增强维度，
                            不改变四源基础权重）

新增产物：
  hotspot_signals 表       — 热点信号明细
  /api/hotspot/*           — REST + SSE API
  Web 热点看板              — 前端可视化
  HotspotRunner            — 实时守护进程
```

### 10. 验收标准

- [ ] LLMClient 新增 `chat_json()`, `chat_stream()`, `complete()` 方法，通过单元测试
- [ ] 修复 `TextSentiment` 接口断裂 bug
- [ ] **热点搜集系统可从 ≥2 个数据源稳定拉取增量文本**
- [ ] 去重层过滤率 > 80%，无误杀（人工抽检 50 条）
- [ ] 守护模式 60s 轮询可稳定运行 1h+ 无崩溃
- [ ] LLM 语义分析输出结构化 JSON，含 topic/sentiment/impact/related_codes
- [ ] hotspot_signals 表正确落库
- [ ] `/api/hotspot/latest` 返回最近热点列表
- [ ] `/api/hotspot/stream` SSE 连接可实时推送新热点
- [ ] 热点信号注入融合池后，个股情绪得分有合理变化（回归校验）
- [ ] 无 API Key 时全链路降级不报错
- [ ] 无新闻数据时全链路降级不报错
- [ ] LLM 调用有 token 用量记录

---

## 附录：关键代码路径索引

| 关注点 | 文件:行 |
|--------|---------|
| LLM 客户端 | `llm/client.py` |
| LLM Prompt 模板 | `llm/prompts.py` |
| 盘后简报生成 | `llm/brief_gen.py` |
| 个股简评生成 | `llm/stock_review.py` |
| 文本情绪（断裂） | `factors/text_sentiment.py:24` |
| 新闻数据源 | `sources/sentiment_data.py:load_news()` |
| 编排器 LLM 步骤 | `scheduler/orchestrator.py:step_llm()` |
| 编排器市场情绪步骤 | `scheduler/orchestrator.py:step_market_sentiment()` |
| 四源融合 | `fusion/signal_pool.py:fuse()` |
| 信号表 DDL | `storage/schema.py:signals` |
| LLM 配置 | `config/settings.yaml:llm` |
| 环境变量样例 | `.env.example` |
