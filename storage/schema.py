"""DuckDB 表结构定义（DDL + 元数据）。

集中管理全库 schema，确保跨文件表结构一致（一致性审查项）。
所有价格类因子/回测统一读取 ``adj_back_close``（后复权，P0-1）；
``adj_front_close``（前复权）仅前端展示，严禁入计算。

表清单（对齐架构文档 §3.1）：
    daily_bars / factor_values / factor_health / signals / sector_rotation
    predict_values / predict_health / universe / watchlist
    daily_brief / stock_review / backtest_report / sentiment_index
"""
from __future__ import annotations

from typing import Dict, List

from loguru import logger

# 含日期列的表（read/write 时做 datetime<->date 适配）
DATE_COLUMNS: set[str] = {"date", "created_at"}

# 表名 -> DDL
TABLE_DDL: Dict[str, str] = {
    "daily_bars": """
        CREATE TABLE IF NOT EXISTS daily_bars (
            code            VARCHAR,
            date            DATE,
            open            DOUBLE,
            high            DOUBLE,
            low             DOUBLE,
            close           DOUBLE,
            pre_close       DOUBLE,
            adj_back_close  DOUBLE,   -- 后复权（计算/回测用，严禁用前复权）
            adj_front_close DOUBLE,   -- 前复权（仅前端 K 线展示）
            vol             DOUBLE,
            amount          DOUBLE,
            source          VARCHAR,
            PRIMARY KEY (code, date)
        );
    """,
    "factor_values": """
        CREATE TABLE IF NOT EXISTS factor_values (
            date         DATE,
            code         VARCHAR,
            factor_name  VARCHAR,
            value        DOUBLE,
            PRIMARY KEY (date, code, factor_name)
        );
    """,
    "factor_health": """
        CREATE TABLE IF NOT EXISTS factor_health (
            factor_name  VARCHAR,
            date         DATE,
            ic           DOUBLE,
            icir         DOUBLE,
            rank_return  DOUBLE,
            turnover     DOUBLE,
            status       VARCHAR,   -- 有效 / 衰减 / 失效
            weight       DOUBLE,
            PRIMARY KEY (factor_name, date)
        );
    """,
    "signals": """
        CREATE TABLE IF NOT EXISTS signals (
            date              DATE,
            code              VARCHAR,
            direction         INT,       -- 1 看多 / -1 看空 / 0 中性
            confidence        DOUBLE,    -- 0~1，取自信号层而非 LLM
            source_tags       VARCHAR,   -- 因子/技术/情绪/预测
            factor_contrib    DOUBLE,    -- 已做行业/市值中性化（残差）
            tech_contrib      DOUBLE,
            sentiment_contrib DOUBLE,
            predict_contrib   DOUBLE,
            PRIMARY KEY (date, code)
        );
    """,
    "sector_rotation": """
        CREATE TABLE IF NOT EXISTS sector_rotation (
            date            DATE,
            sector_code     VARCHAR,
            sector_name     VARCHAR,
            change_pct      DOUBLE,
            rs              DOUBLE,
            net_inflow      DOUBLE,
            rotation_signal VARCHAR,   -- 进攻 / 防御 / 切换
            PRIMARY KEY (date, sector_code)
        );
    """,
    "predict_values": """
        CREATE TABLE IF NOT EXISTS predict_values (
            code         VARCHAR,
            date         DATE,
            model_name   VARCHAR,
            horizon      INT,        -- 1(次日)/5/10
            dir_pred     INT,        -- 1 看多 / -1 看空 / 0 中性
            ret_pred     DOUBLE,
            lower        DOUBLE,
            upper        DOUBLE,
            dir_acc_hist DOUBLE,     -- 历史方向准确率（驱动融合权重）
            PRIMARY KEY (code, date, model_name, horizon)
        );
    """,
    "predict_health": """
        CREATE TABLE IF NOT EXISTS predict_health (
            model_name VARCHAR,
            date       DATE,
            mape       DOUBLE,
            dir_acc    DOUBLE,
            weight     DOUBLE,
            ic         DOUBLE,     -- 横截面信息系数（Spearman，预测 vs 实际前向收益）均值
            rolling_ic DOUBLE,     -- 最近滚动窗口 IC（闸门判定用）
            dropped    BOOLEAN,    -- 连续 3 窗口 |IC|≈0 自动剔除标记
            PRIMARY KEY (model_name, date)
        );
    """,
    "universe": """
        CREATE TABLE IF NOT EXISTS universe (
            date         DATE,
            code         VARCHAR,
            name         VARCHAR,
            in_universe  BOOLEAN,   -- 标准可投资域（剔除 ST/次新/停牌后为 true）
            is_st        BOOLEAN,
            listed_days  INT,        -- 上市交易天数（次新过滤）
            delisted     BOOLEAN,    -- 保留已退市用于样本
            PRIMARY KEY (date, code)
        );
    """,
    "watchlist": """
        CREATE TABLE IF NOT EXISTS watchlist (
            code        VARCHAR,
            name        VARCHAR,
            cost_price  DOUBLE,
            shares      DOUBLE,
            created_at  TIMESTAMP,
            PRIMARY KEY (code)
        );
    """,
    "daily_brief": """
        CREATE TABLE IF NOT EXISTS daily_brief (
            date             DATE,
            content          VARCHAR,
            market_temperature INT,
            disclaimer       VARCHAR,
            PRIMARY KEY (date)
        );
    """,
    "stock_review": """
        CREATE TABLE IF NOT EXISTS stock_review (
            date       DATE,
            code       VARCHAR,
            content    VARCHAR,
            action     VARCHAR,    -- 买入/卖出/持有（研究观点，非建议）
            reason     VARCHAR,
            confidence DOUBLE,     -- 取自信号层
            disclaimer VARCHAR,
            PRIMARY KEY (date, code)
        );
    """,
    "backtest_report": """
        CREATE TABLE IF NOT EXISTS backtest_report (
            date         DATE,
            strategy     VARCHAR,
            metric_name  VARCHAR,
            metric_value DOUBLE,
            benchmark    VARCHAR,
            sharpe       DOUBLE,
            deflated_sharpe DOUBLE,
            PRIMARY KEY (date, strategy, metric_name)
        );
    """,
    "sentiment_index": """
        CREATE TABLE IF NOT EXISTS sentiment_index (
            date            DATE,
            index_value     DOUBLE,    -- 市场情绪综合指数 0~100
            sub_volume      DOUBLE,    -- 量能分维度
            sub_price       DOUBLE,    -- 价格分维度
            sub_money       DOUBLE,    -- 资金分维度
            sub_valuation   DOUBLE,    -- 估值分维度
            sub_riskpremium DOUBLE,    -- 风险溢价分维度
            gsisi           DOUBLE,    -- 高 Beta 行业轮动强度
            regime          VARCHAR,   -- 恐惧 / 中性 / 贪婪（温度计情绪态，展示用）
            regime_state    VARCHAR,   -- bull / neutral / bear / panic（情绪+指数回撤派生，regime_adjust 缩放用）
            thermometer     DOUBLE,    -- 华泰温度计 0~100
            signal          VARCHAR,   -- 买入 / 半仓 / 空仓
            PRIMARY KEY (date)
        );
    """,
}

# 表写入顺序（外键无强制约束，仅作落库/初始化顺序参考）
TABLE_ORDER: List[str] = [
    "daily_bars",
    "universe",
    "factor_values",
    "factor_health",
    "predict_values",
    "predict_health",
    "signals",
    "sector_rotation",
    "watchlist",
    "daily_brief",
    "stock_review",
    "backtest_report",
    "sentiment_index",
]


def init_schema(con) -> None:
    """在给定 DuckDB 连接上创建所有表（幂等）。

    Args:
        con: duckdb.DuckDBPyConnection 或 DuckDBClient 实例
    """
    # 兼容传入 DuckDBClient（其内部持有 con）
    connection = getattr(con, "con", con)
    for name in TABLE_ORDER:
        connection.execute(TABLE_DDL[name])
    # 幂等迁移：补齐新增列（已存在的库不重建，仅 ALTER 补列）
    _migrate_add_columns(connection)


def all_tables() -> List[str]:
    """返回全部表名。"""
    return list(TABLE_ORDER)


def _migrate_add_columns(connection) -> None:
    """对可能缺列的旧库做幂等 ALTER（新增列用，缺失才补）。"""
    # sentiment_index 新增 regime_state（bull/neutral/bear/panic）
    try:
        cols = {
            r[1]
            for r in connection.execute("PRAGMA table_info('sentiment_index')").fetchall()
        }
        if "regime_state" not in cols:
            connection.execute(
                "ALTER TABLE sentiment_index ADD COLUMN regime_state VARCHAR"
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"sentiment_index 迁移跳过：{exc}")
    # predict_health 新增 ic / rolling_ic / dropped（动态 IC 加权闸门）
    try:
        cols = {
            r[1]
            for r in connection.execute("PRAGMA table_info('predict_health')").fetchall()
        }
        for col, typ in (
            ("ic", "DOUBLE"),
            ("rolling_ic", "DOUBLE"),
            ("dropped", "BOOLEAN"),
        ):
            if col not in cols:
                connection.execute(f"ALTER TABLE predict_health ADD COLUMN {col} {typ}")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"predict_health 迁移跳过：{exc}")
