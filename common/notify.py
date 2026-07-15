"""失效告警通知层（P2-3）。

可插拔通道（Channel）+ 阈值评估 + 每日摘要。与 ``fusion/push.py``（信号推送）解耦：
本模块只负责**系统健康/失效**类的告警（数据断更、多源分歧、预测员被剔除、模型衰减等）。

通道（可插拔）：
- ``MockChannel``：默认/测试，记录发出的消息，不触网。
- ``ConsoleChannel``：打印到日志（便于容器/stdout 采集）。
- ``WebhookChannel``：httpx POST JSON 到外部地址（企业微信/飞书/自定义）。
- 微信（Server 酱/企业微信应用）/ 邮件（SMTP）为扩展点，实现对应 Channel 子类即可。

阈值评估 ``evaluate_health`` 为纯函数（不依赖 DB），便于单测。
"""
from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 默认阈值（可被 settings["notify"]["thresholds"] 覆盖）
DEFAULT_THRESHOLDS: Dict[str, Any] = {
    "max_data_age_days": 3,      # 最新信号距“今天/评估日”的最大天数（容忍周末+节假日）
    "max_divergence": 20,        # 单轮（评估窗口内）多源分歧条数上限
    "max_dropped_predictors": 2, # 最新一批被 IC 闸门剔除的预测员数量上限
}

# 告警级别
CRITICAL = "critical"
WARNING = "warning"
INFO = "info"


@dataclass
class Alert:
    """一条触发的告警。"""

    level: str
    title: str
    body: str

    def render(self) -> str:
        return f"[{self.level.upper()}] {self.title}\n{self.body}"


class Channel(abc.ABC):
    """通知通道抽象。"""

    name: str = "base"

    @abc.abstractmethod
    def send(self, title: str, body: str, level: str) -> bool:
        """发送一条消息，返回是否成功。"""
        raise NotImplementedError


class MockChannel(Channel):
    """默认/测试通道：记录消息，不触网。"""

    name = "mock"

    def __init__(self) -> None:
        self.sent: List[Dict[str, str]] = []

    def send(self, title: str, body: str, level: str) -> bool:
        self.sent.append({"title": title, "body": body, "level": level})
        return True


class ConsoleChannel(Channel):
    """打印到 stdout（容器日志采集友好）。"""

    name = "console"

    def send(self, title: str, body: str, level: str) -> bool:
        print(f"[alert:{level}] {title}\n{body}")
        return True


class WebhookChannel(Channel):
    """Webhook 通道：POST JSON 到外部地址（企业微信/飞书/自定义）。失败不抛。"""

    name = "webhook"

    def __init__(self, url: str, timeout: float = 10.0) -> None:
        self.url = url
        self.timeout = timeout

    def send(self, title: str, body: str, level: str) -> bool:
        try:
            import httpx
        except Exception:  # noqa: BLE001
            return False
        try:
            resp = httpx.post(
                self.url,
                json={"title": title, "body": body, "level": level},
                timeout=self.timeout,
            )
            return resp.status_code < 400
        except Exception:  # noqa: BLE001
            return False


class Notifier:
    """聚合多个通道；提供 alert()/digest()。"""

    def __init__(self, channels: Optional[List[Channel]] = None) -> None:
        self.channels: List[Channel] = list(channels) if channels else [MockChannel()]

    def alert(self, title: str, body: str, level: str = WARNING) -> bool:
        if not self.channels:
            return False
        return all(ch.send(title, body, level) for ch in self.channels)

    def digest(self, text: str, title: str = "每日运行摘要") -> bool:
        return self.alert(title, text, level=INFO)

    @classmethod
    def from_settings(cls, settings: Dict[str, Any]) -> "Notifier":
        """由 settings["notify"]["channels"] 构造；无配置则默认 Mock（安全不触网）。"""
        cfg = settings.get("notify", {}) or {}
        channels: List[Channel] = []
        for ch in cfg.get("channels", []) or []:
            kind = (ch.get("type") or "").lower()
            if kind == "console":
                channels.append(ConsoleChannel())
            elif kind == "webhook":
                url = ch.get("url")
                if url:
                    channels.append(WebhookChannel(url, float(ch.get("timeout", 10))))
            elif kind == "mock":
                channels.append(MockChannel())
            # wechat/email 等扩展点：未实现子类则跳过
        if not channels:
            channels.append(MockChannel())  # 默认安全：不触网
        return cls(channels)


def evaluate_health(
    metrics: Dict[str, Any],
    thresholds: Optional[Dict[str, Any]] = None,
) -> List[Alert]:
    """纯函数：依据指标与阈值产出触发的告警列表（不依赖 DB，便于单测）。

    metrics 支持键：data_age_days / divergence_count / dropped_predictors。
    """
    th = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        th.update(thresholds)

    alerts: List[Alert] = []

    age = metrics.get("data_age_days")
    if age is not None and age > int(th["max_data_age_days"]):
        alerts.append(
            Alert(
                level=CRITICAL,
                title="数据断更告警",
                body=f"最新信号距评估日已 {age} 天（阈值 {th['max_data_age_days']} 天），"
                f"可能数据源中断或调度未跑。",
            )
        )

    div = metrics.get("divergence_count")
    if div is not None and div > int(th["max_divergence"]):
        alerts.append(
            Alert(
                level=WARNING,
                title="多源分歧超阈值",
                body=f"评估窗口内多源收盘分歧 {div} 条（阈值 {th['max_divergence']} 条），"
                f"请检查 divergence_log。",
            )
        )

    dropped = metrics.get("dropped_predictors")
    if dropped is not None and dropped > int(th["max_dropped_predictors"]):
        alerts.append(
            Alert(
                level=WARNING,
                title="预测员被大量剔除",
                body=f"最新一批被 IC 闸门剔除的预测员 {dropped} 个（阈值 "
                f"{th['max_dropped_predictors']} 个），预测源可能整体失效。",
            )
        )

    return alerts


def build_digest(summary: Dict[str, Any]) -> str:
    """由运行状态摘要拼装每日摘要文本。"""
    lines = [
        f"日期：{summary.get('date')}",
        f"信号数：{summary.get('signal_count', summary.get('signals', '?'))}",
        f"多源分歧：{summary.get('divergence_count', 0)} 条",
        f"被剔除预测员：{summary.get('dropped_predictors', 0)} 个",
        f"市场温度：{summary.get('market_temperature', '?')}",
    ]
    if summary.get("regime_state"):
        lines.append(f"市场状态：{summary['regime_state']}")
    notes = summary.get("notes") or []
    if notes:
        lines.append("备注：")
        lines.extend(f"  - {n}" for n in notes)
    return "\n".join(lines)
