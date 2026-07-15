"""失效告警监控触发（P2-3）。

从 Repository 采集健康指标（数据新旧、多源分歧、预测员剔除），经阈值评估后通过
``Notifier`` 发送告警与每日摘要。与 ``common/notify.py`` 配合；可在编排 ``run_daily``
末尾以 try/except 包裹调用（非致命，默认 Mock 通道不触网）。
"""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Dict, List, Optional

from common.notify import (
    CRITICAL,
    WARNING,
    Notifier,
    build_digest,
    evaluate_health,
)


def _resolve_divergence_log(settings: Dict[str, Any]) -> str:
    ds = settings.get("data_sources", {}) or {}
    path = ds.get("divergence_log") or "./data/divergence_log.jsonl"
    return path


def count_divergences(log_path: str, as_of: Optional[dt.date] = None) -> int:
    """统计分歧日志条数；as_of 给定时只计该日，否则计全部（文件不存在返回 0）。"""
    if not log_path or not os.path.exists(log_path):
        return 0
    as_of_str = as_of.isoformat() if as_of else None
    n = 0
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if as_of_str is None or rec.get("date") == as_of_str:
                n += 1
    return n


def gather_metrics(
    repo: Any,
    settings: Dict[str, Any],
    as_of: Optional[dt.date] = None,
) -> Dict[str, Any]:
    """从 Repository 采集健康指标（纯读取，不写）。"""
    as_of = as_of or dt.date.today()
    metrics: Dict[str, Any] = {
        "data_age_days": None,
        "divergence_count": count_divergences(_resolve_divergence_log(settings), as_of),
        "dropped_predictors": 0,
        "signal_count": 0,
        "market_temperature": None,
        "regime_state": None,
    }

    # 最新信号日期 → 数据新旧
    try:
        sig = repo.load_signals_all()
        if sig is not None and not sig.empty and "date" in sig.columns:
            latest = sig["date"].max()
            if hasattr(latest, "date"):
                latest = latest.date()
            metrics["signal_count"] = int(len(sig))
            metrics["data_age_days"] = (as_of - latest).days
    except Exception:  # noqa: BLE001
        metrics["data_age_days"] = None

    # 被 IC 闸门剔除的预测员数
    try:
        ph = repo.load_predict_health(latest=True)
        if ph is not None and not ph.empty and "dropped" in ph.columns:
            dropped = ph["dropped"]
            if hasattr(dropped, "fillna"):
                dropped = dropped.fillna(False)
            metrics["dropped_predictors"] = int(dropped.astype(bool).sum())
    except Exception:  # noqa: BLE001
        pass

    # 市场温度 / 状态（供摘要；来自最新 sentiment_index）
    try:
        si = repo.load_sentiment_index(latest=True)
        if si is not None and not si.empty:
            if "market_temperature" in si.columns:
                metrics["market_temperature"] = si["market_temperature"].iloc[0]
            if "regime_state" in si.columns:
                metrics["regime_state"] = si["regime_state"].iloc[0]
    except Exception:  # noqa: BLE001
        pass

    return metrics


def monitor_run(
    repo: Any,
    settings: Dict[str, Any],
    notifier: Optional[Notifier] = None,
    as_of: Optional[dt.date] = None,
) -> Dict[str, Any]:
    """采集指标 → 阈值评估 → 发告警 + 每日摘要。返回运行摘要（含触发的告警）。

    非致命：任意读取失败只让对应指标缺失，不影响整体。
    """
    as_of = as_of or dt.date.today()
    notifier = notifier or Notifier.from_settings(settings)
    th_cfg = (settings.get("notify", {}) or {}).get("thresholds")

    metrics = gather_metrics(repo, settings, as_of)
    alerts = evaluate_health(metrics, th_cfg)

    for a in alerts:
        notifier.alert(a.title, a.body, level=a.level)

    summary = {
        "date": as_of.isoformat(),
        "signal_count": metrics.get("signal_count"),
        "divergence_count": metrics.get("divergence_count"),
        "dropped_predictors": metrics.get("dropped_predictors"),
        "market_temperature": metrics.get("market_temperature"),
        "regime_state": metrics.get("regime_state"),
        "alerts": [a.render() for a in alerts],
    }
    notifier.digest(build_digest(summary))
    return summary
