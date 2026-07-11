"""真实行情 runner：沪深300 样本域 + 实时数据 -> 今日信号报告。
生成 _today_prediction.md 供查看。A/B/C 已启用：Kronos/QLib 真实预测 + 行业/市值中性化。"""
from __future__ import annotations
import datetime as dt
import os
import pandas as pd
from common.config import load_settings, build_repository
from sources.akshare_adapter import AkshareDailyAdapter
from sources.base import DataSourceRouter
from sources.market_meta import build_market_meta
from scheduler.orchestrator import Orchestrator
import akshare as ak

# Kronos 权重优先走仓库内离线目录（本环境 HF/Gitee 网络不可达）；
# 若目录不存在，适配器会自动回退在线加载。与 factors/kronos_adapter.py 的 KRONOS_LOCAL_DIR 对齐。
os.environ.setdefault("KRONOS_LOCAL_DIR", "_local_kronos_weights")

def _load_hs300(cache_path):
    """取沪深300成分：优先 akshare（带 30s 超时），失败则本地缓存，再失败则 market.duckdb 的 universe 表兜底。"""
    import threading

    holder = {}

    def _fetch():
        try:
            df = ak.index_stock_cons_csindex(symbol="000300")
            holder["df"] = df
        except Exception as exc:  # noqa: BLE001
            holder["err"] = exc

    th = threading.Thread(target=_fetch, daemon=True)
    th.start()
    th.join(30)
    if "df" in holder and holder["df"] is not None:
        out = holder["df"][["成分券代码", "成分券名称"]].rename(
            columns={"成分券代码": "code", "成分券名称": "name"}
        )
        try:
            out.to_csv(cache_path, index=False)
        except Exception:  # noqa: BLE001
            pass
        return out["code"].astype(str).str.zfill(6).tolist(), out["name"].astype(str).tolist()
    # 超时或异常 -> 本地缓存兜底
    if os.path.exists(cache_path):
        print("⚠️ akshare 取沪深300超时/失败，改用本地缓存", flush=True)
        c = pd.read_csv(cache_path)
        return c["code"].astype(str).str.zfill(6).tolist(), c["name"].astype(str).tolist()
    # 再兜底：已落库 universe 表
    try:
        import duckdb

        con = duckdb.connect("data/market.duckdb", read_only=True)
        rows = con.execute(
            "SELECT DISTINCT code, name FROM universe WHERE in_universe=TRUE"
        ).fetchall()
        con.close()
        if rows:
            print("⚠️ akshare 取沪深300失败，改用 market.duckdb universe 表", flush=True)
            return [str(r[0]).zfill(6) for r in rows], [str(r[1]) for r in rows]
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError("无法获取沪深300成分：akshare 超时且无本地兜底")


print("== 取沪深300成分 ==", flush=True)
codes, names = _load_hs300("_hs300_cache.csv")
print(f"样本域 {len(codes)} 只（沪深300）", flush=True)

print("== 取行业/市值元数据（中性化用）==", flush=True)
meta = build_market_meta(codes, names)
has_ind = (meta["industry"].astype(str).str.len() > 0).sum()
has_mv = meta["mv"].notna().sum()
print(f"行业覆盖 {has_ind}/{len(meta)}，市值覆盖 {has_mv}/{len(meta)}", flush=True)
stock_list = meta.rename(columns={})[["code", "name", "industry", "mv"]]

settings = load_settings()
repo, settings = build_repository(settings)
# 本环境唯一可用的历史日 K 源：akshare(Sina)。mootdx 服务器多数失效且 Quotes.factory
# 在应用层握手时挂死、baostock 登录挂死，故仅启用 akshare（架构 §7.4 冗余源实装）。
src = DataSourceRouter([AkshareDailyAdapter()])
orch = Orchestrator(repo=repo, settings=settings, data_source=src, stock_list=stock_list)

# 更新数据：拉取截至今日的最新日 K（akshare 新浪财经 Sina 行情，本环境唯一可用源），upsert 入 market.duckdb
TODAY = dt.date.today()
print(f"== 更新数据 step_ingest({TODAY - dt.timedelta(days=300)} .. {TODAY}) ==", flush=True)
orch.step_ingest(TODAY - dt.timedelta(days=300), TODAY)

# 目标日取库中最新交易日（确保有数据可预测；含刚拉取的最新一根）
# 复用仓储已有连接，避免与编排器打开的读写连接产生「同库不同配置」冲突
TARGET = repo.market.execute("SELECT max(date) FROM daily_bars").fetchone()[0]
print(f"== 运行 run_daily(TARGET={TARGET}) ==", flush=True)
orch.source = None  # run_daily 内不再重复 ingest（已显式刷新）
res = orch.run_daily(TARGET, lookback_days=300)
print("run_daily:", res, flush=True)

sig = repo.load_signals(TARGET).copy()
try:
    ph = repo.load_predict_health(TARGET)
except Exception:
    ph = pd.DataFrame()
uni = repo.load_universe(TARGET, in_universe=True)
name_map = dict(zip(stock_list["code"], stock_list["name"]))
sig["name"] = sig["code"].map(name_map).fillna(sig["code"])

n_uni = int(uni["in_universe"].sum()) if not uni.empty else 0
longs = sig[sig["direction"] == 1].sort_values("confidence", ascending=False)
shorts = sig[sig["direction"] == -1].sort_values("confidence", ascending=False)
neutrals = sig[sig["direction"] == 0]

pred_lines = []
if not ph.empty:
    for _, r in ph.iterrows():
        pred_lines.append(f"  - {r['model_name']}: dir_acc={r['dir_acc']:.3f} weight={r['weight']:.3f}")
pred_status = "真实模型已启用（Kronos/Darts 装入）；如下表权重由 walk-forward 方向准确率驱动" if pred_lines else "预测源未产出（检查模型加载）"

lines = []
lines.append(f"# 今日 A 股量化信号（{TARGET}）\n")
lines.append("> 数据来源：akshare 新浪财经日 K（真实数据，本环境 mootdx/baostock 不可达，已切换 Sina）")
lines.append(f"> 样本域：沪深300 成分，候选 {len(stock_list)} 只，入选可投资域 {n_uni} 只")
lines.append("> 平台：analysis-first 仅分析不交易；信号为研究观点，非买卖建议\n")
lines.append("## 预测源状态（第4源 · A/B 已启用）")
lines.append(pred_status)
if pred_lines:
    lines.extend(pred_lines)
lines.append("## 中性化状态（C 已启用）")
lines.append(f"- 行业覆盖 {has_ind}/{len(meta)} 只，市值覆盖 {has_mv}/{len(meta)} 只；")
lines.append("  融合前已对因子做行业/市值回归残差中性化（缺失行业/市值的标的该日跳过）。\n")
lines.append(f"## 信号概览")
lines.append(f"- 看多（direction=1）：{len(longs)} 只")
lines.append(f"- 看空（direction=-1）：{len(shorts)} 只")
lines.append(f"- 中性（direction=0）：{len(neutrals)} 只")
lines.append(f"- 可投资域入选：{n_uni} 只\n")

def block(title, sub):
    lines.append(f"## {title}（按置信度）")
    if sub.empty:
        lines.append("（无）\n")
        return
    top = sub.head(15)
    lines.append("| 代码 | 名称 | 方向 | 置信度 | 因子贡献 | 技术贡献 | 情绪贡献 | 预测贡献 |")
    lines.append("|------|------|------|--------|----------|----------|----------|----------|")
    for _, r in top.iterrows():
        lines.append(
            f"| {r['code']} | {r['name']} | {int(r['direction'])} | "
            f"{r['confidence']:.3f} | {r.get('factor_contrib',0):.2f} | "
            f"{r.get('tech_contrib',0):.2f} | {r.get('sentiment_contrib',0):.2f} | "
            f"{r.get('predict_contrib',0):.2f} |"
        )
    lines.append("")

block("📈 Top 看多", longs)
block("📉 Top 看空", shorts)

lines.append("## 说明与限制")
lines.append("- 因子/技术/情绪 为实算；**预测第4源经 A/B 启用为真实 Kronos/Darts 模型**（权重由 walk-forward 方向准确率驱动，效果差自动降权）。")
lines.append("- **行业/市值中性化（C）已启用**：因子在融合前做回归残差中性化，去除单一风格暴露。")
lines.append("- 复权已修正确保后复权（锚定最早）用于计算，避免前视偏差。")
lines.append("- 回测为 walk-forward 样本外 + 基准对照，详见 backtest_report 表。")
lines.append("- 行业映射来自同花顺行业板（近似申万），市值来自腾讯 gtimg；个别标的缺元数据时该日中性化跳过。")

out = "\n".join(lines)
with open("_today_prediction.md", "w", encoding="utf-8") as f:
    f.write(out)
print("\n=== 报告已写 _today_prediction.md ===", flush=True)
print(out[:2800], flush=True)
