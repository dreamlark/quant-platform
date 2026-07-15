"""P2-3 失效告警单测：可插拔通道 + 阈值评估 + 监控触发（Mock 通道，无网络）。

用 duck-typed 的 FakeRepo 隔离 DB，覆盖：
- MockChannel 记录消息；Notifier.from_settings 默认回退 Mock（不触网）。
- evaluate_health 按阈值触发数据断更/分歧/预测员剔除告警。
- monitor_run 采集指标 → 发告警 + 每日摘要，返回含告警的运行摘要。
- count_divergences 解析分歧日志（按日过滤）。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile

import pandas as pd

from common.alert_monitor import count_divergences, monitor_run
from common.notify import (
    CRITICAL,
    INFO,
    WARNING,
    MockChannel,
    Notifier,
    build_digest,
    evaluate_health,
)


def _today() -> dt.date:
    return dt.date(2024, 6, 14)


class FakeRepo:
    def __init__(self, latest_signal_date, dropped=0, temp=50, regime=None, has_signals=True):
        self._latest = latest_signal_date
        self._dropped = dropped
        self._temp = temp
        self._regime = regime
        self._has = has_signals

    def load_signals_all(self):
        if not self._has:
            return None
        return pd.DataFrame({"date": [self._latest], "code": ["600519.SH"]})

    def load_predict_health(self, latest=True):
        if self._dropped <= 0:
            return pd.DataFrame(columns=["dropped"])
        return pd.DataFrame({"dropped": [True] * self._dropped})

    def load_sentiment_index(self, latest=True):
        if self._regime is None:
            return pd.DataFrame({"market_temperature": [self._temp]})
        return pd.DataFrame({"market_temperature": [self._temp], "regime_state": [self._regime]})


def test_mock_channel_records():
    ch = MockChannel()
    n = Notifier([ch])
    assert n.alert("标题", "正文", level=WARNING) is True
    assert len(ch.sent) == 1
    assert ch.sent[0]["title"] == "标题"
    assert ch.sent[0]["level"] == WARNING


def test_from_settings_default_mock():
    n = Notifier.from_settings({})
    assert len(n.channels) == 1
    assert isinstance(n.channels[0], MockChannel)


def test_evaluate_data_age():
    # 超过阈值 → critical
    a = evaluate_health({"data_age_days": 5}, {"max_data_age_days": 3})
    assert len(a) == 1 and a[0].level == CRITICAL
    # 默认阈值内 → 无告警
    assert evaluate_health({"data_age_days": 1}) == []
    # 缺失指标 → 不触发
    assert evaluate_health({}) == []


def test_evaluate_divergence_and_dropped():
    a = evaluate_health({"divergence_count": 25}, {"max_divergence": 20})
    assert len(a) == 1 and a[0].level == WARNING
    assert evaluate_health({"divergence_count": 5}) == []
    b = evaluate_health({"dropped_predictors": 3}, {"max_dropped_predictors": 2})
    assert len(b) == 1 and b[0].level == WARNING
    assert evaluate_health({"dropped_predictors": 1}) == []


def test_count_divergences(tmp_path):
    p = tmp_path / "div.jsonl"
    day = _today().isoformat()
    rows = [
        {"date": day, "code": "A", "price_a": 1.0, "price_b": 1.01},
        {"date": day, "code": "B", "price_a": 2.0, "price_b": 2.02},
        {"date": "2024-01-01", "code": "C", "price_a": 3.0, "price_b": 3.03},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert count_divergences(str(p), _today()) == 2
    assert count_divergences(str(p)) == 3  # 不传 as_of → 全部
    assert count_divergences(str(p) + ".missing") == 0


def test_monitor_run_sends_alert_and_digest(tmp_path):
    # 数据断更 5 天 + 剔除 3 个预测员 → 应触发 critical + warning，并发送每日摘要
    repo = FakeRepo(latest_signal_date=_today() - dt.timedelta(days=5), dropped=3, regime="bear")
    ch = MockChannel()
    notifier = Notifier([ch])
    settings = {
        "notify": {"thresholds": {"max_data_age_days": 3, "max_divergence": 20, "max_dropped_predictors": 2}},
        "data_sources": {"divergence_log": str(tmp_path / "div.jsonl")},
    }
    summary = monitor_run(repo, settings, notifier=notifier, as_of=_today())

    assert summary["dropped_predictors"] == 3
    assert summary["regime_state"] == "bear"
    assert len(summary["alerts"]) >= 2  # 数据断更 + 预测员剔除

    levels = {m["level"] for m in ch.sent}
    assert WARNING in levels
    assert CRITICAL in levels
    # 每日摘要（info）
    assert any(m["level"] == INFO for m in ch.sent)


def test_monitor_run_healthy_no_alert(tmp_path):
    repo = FakeRepo(latest_signal_date=_today(), dropped=0, regime="bull")
    ch = MockChannel()
    notifier = Notifier([ch])
    settings = {
        "notify": {"thresholds": {"max_data_age_days": 3, "max_divergence": 20, "max_dropped_predictors": 2}},
        "data_sources": {"divergence_log": str(tmp_path / "div.jsonl")},
    }
    summary = monitor_run(repo, settings, notifier=notifier, as_of=_today())
    assert summary["alerts"] == []
    # 仍发送每日摘要
    assert any(m["level"] == INFO for m in ch.sent)


def test_build_digest_renders():
    text = build_digest({"date": "2024-06-14", "signal_count": 6, "divergence_count": 0,
                         "dropped_predictors": 0, "market_temperature": 55, "regime_state": "bull"})
    assert "2024-06-14" in text
    assert "bull" in text
    assert "信号数：6" in text
