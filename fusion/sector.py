"""板块轮动 / 强弱排名（基于 DuckDB 聚合，零重框架）。

聚合可投资域内个股日收益为板块涨跌幅、相对强弱（RS）、资金净流入（代理）、
轮动信号（进攻/防御/切换）。基准为全可投资域等权收益（中证全指/沪深300 代理）。
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

from loguru import logger

_DEFAULT_SECTORS_YAML = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "sectors.yaml"
)


def load_sector_map(
    path: Optional[str] = None,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """读取 config/sectors.yaml，返回 (code->sector_code, sector_code->sector_name)。"""
    path = path or _DEFAULT_SECTORS_YAML
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    code2sec: Dict[str, str] = {}
    sec2name: Dict[str, str] = {}
    for ind in cfg.get("industries", []):
        sec2name[ind["code"]] = ind["name"]
        for c in ind.get("members", []):
            code2sec[c] = ind["code"]
    return code2sec, sec2name


class SectorAnalyzer:
    """板块轮动分析。"""

    def __init__(self, cfg: Optional[Dict] = None, sectors_yaml: Optional[str] = None) -> None:
        self.cfg = cfg or {}
        self.code2sec, self.sec2name = load_sector_map(sectors_yaml)

    def analyze(
        self,
        date: dt.date,
        bars_df: pd.DataFrame,
        universe_df: Optional[pd.DataFrame] = None,
        industry_map: Optional[Dict[str, str]] = None,
    ) -> pd.DataFrame:
        """计算当日板块轮动快照。

        Args:
            industry_map: 可选，code(6位) -> 行业名 的**真实行业分类**映射（如申万一级）。
                提供时优先用真实行业聚合板块（覆盖 ``config/sectors.yaml`` 的样例映射），
                使板块页展示真实行业轮动而非退化的「其他」。
        """
        if bars_df is None or bars_df.empty:
            return pd.DataFrame(
                columns=[
                    "date",
                    "sector_code",
                    "sector_name",
                    "change_pct",
                    "rs",
                    "net_inflow",
                    "rotation_signal",
                ]
            )
        work = bars_df.copy()
        if universe_df is not None and not universe_df.empty:
            u = universe_df[universe_df["in_universe"]]
            work = work[work["code"].isin(u["code"])]

        # 日收益（后复权）
        work = work.sort_values(["code", "date"])
        work["ret"] = work.groupby("code")["adj_back_close"].pct_change()

        prev_day = work[work["date"] < date]["date"].max()
        day = work[work["date"] == date][["code", "ret", "amount"]].copy()
        if prev_day is not None:
            prev = work[work["date"] == prev_day][["code", "amount"]].rename(
                columns={"amount": "prev_amt"}
            )
            day = day.merge(prev, on="code", how="left")
        else:
            day["prev_amt"] = np.nan

        # 板块映射：优先真实行业分类（industry_map），否则用 sectors.yaml，未命中 -> OTHER
        if industry_map:
            day["sector_code"] = day["code"].map(lambda c: industry_map.get(c, "OTHER"))
            sec2name = dict(industry_map)
            sec2name["OTHER"] = "其他"
        else:
            day["sector_code"] = day["code"].map(self.code2sec).fillna("OTHER")
            sec2name = dict(self.sec2name)
            if "OTHER" not in sec2name:
                sec2name["OTHER"] = "其他"

        universe_mean = day["ret"].mean()

        rows = []
        for sec, g in day.groupby("sector_code"):
            change = float(g["ret"].mean())
            rs = float(change - universe_mean) if not np.isnan(universe_mean) else 0.0
            # 资金净流入代理：当日成交额相对前一交易日变化之和
            net_inflow = float((g["amount"].fillna(0) - g["prev_amt"].fillna(0)).sum())
            if rs > 0.005:
                rotation = "进攻"
            elif rs < -0.005:
                rotation = "防御"
            else:
                rotation = "切换"
            rows.append(
                {
                    "date": date,
                    "sector_code": sec,
                    "sector_name": sec2name.get(sec, sec),
                    "change_pct": round(change, 4),
                    "rs": round(rs, 4),
                    "net_inflow": round(net_inflow, 2),
                    "rotation_signal": rotation,
                }
            )
        result = pd.DataFrame(rows).sort_values("rs", ascending=False)
        logger.info(f"板块轮动 {date}：{len(result)} 个板块")
        return result
