from __future__ import annotations

import json
from dataclasses import replace

import httpx

from apps.notifications.feishu_card_builder import (
    build_hourly_report_summary,
    build_incident_notification,
    build_sla_completion_notification,
    build_sla_partial_notification,
    build_sla_blocked_notification,
    build_test_message,
    render_feishu_message,
)
from apps.notifications.feishu_client import FeishuWebhookClient
from apps.notifications.notification_agent import FeishuNotificationAgent
from apps.notifications.schemas import FeishuNotificationConfig


class FakeRecorder:
    def __init__(self, calls: list[dict]):
        self.calls = calls
        self.steps: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.calls.append({"exit_exc_type": exc_type.__name__ if exc_type else None})
        return False

    def run_id(self) -> str:
        return "run-feishu-1"

    def step(self, step_name: str, **kwargs):
        self.steps.append({"step_name": step_name, **kwargs})
        self.calls.append({"step_name": step_name, **kwargs})
        return "step-feishu-1"


def _recorder_factory(calls: list[dict]):
    def factory(**kwargs):
        calls.append({"recorder": kwargs})
        return FakeRecorder(calls)

    return factory


def test_card_builder_supports_required_notification_kinds() -> None:
    requests = [
        build_test_message(message="hello"),
        build_hourly_report_summary(title="小时报告", summary="ok", facts={"allowed_outputs": 3}),
        build_incident_notification(title="阻断", summary="missing raw"),
        build_sla_completion_notification(title="SLA完成", summary="analysis ready"),
        build_sla_partial_notification(title="SLA部分完成", summary="preview only"),
        build_sla_blocked_notification(title="SLA阻断", summary="missing parsed"),
    ]

    rendered = [render_feishu_message(request) for request in requests]

    assert "测试消息" in rendered[0][1]
    assert "小时报告摘要" in rendered[1][1]
    assert "异常/阻断通知" in rendered[2][1]
    assert "SLA 事件完成" in rendered[3][1]
    assert "SLA 事件部分完成" in rendered[4][1]
    assert "SLA 事件阻断" in rendered[5][1]


def test_dry_run_builds_payload_preview_without_leaking_secret() -> None:
    client = FeishuWebhookClient(FeishuNotificationConfig(enabled=True, webhook_url="https://example.test/hook", secret="top-secret"))
    request = replace(build_test_message(message="hello"), dry_run=True)

    result = client.send(request, rendered_title="Test", rendered_message="hello")

    serialized = json.dumps(result.to_dict(), ensure_ascii=False)
    assert result.ok is True
    assert result.status == "dry_run"
    assert result.payload_preview["has_sign"] is True
    assert "top-secret" not in serialized
    assert "https://example.test/hook" not in serialized


def test_notification_agent_records_feishu_notification_task_for_disabled_send() -> None:
    calls: list[dict] = []
    agent = FeishuNotificationAgent(
        client=FeishuWebhookClient(FeishuNotificationConfig(enabled=False)),
        recorder_factory=_recorder_factory(calls),
    )

    result = agent.send(build_test_message(message="hello"))

    assert result.status == "disabled"
    assert result.run_id == "run-feishu-1"
    assert calls[0]["recorder"]["task_type"] == "feishu_notification"
    assert calls[1]["step_name"] == "send_feishu"
    assert calls[1]["status"] == "skipped"
    assert calls[2]["exit_exc_type"] is None
    assert "FEISHU_ENABLE" in (result.error or "")


def test_notification_agent_sends_via_feishu_webhook_and_records_success() -> None:
    calls: list[dict] = []
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content.decode()))
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    agent = FeishuNotificationAgent(
        client=FeishuWebhookClient(FeishuNotificationConfig(enabled=True, webhook_url="https://open.feishu.cn/hook/token")),
        recorder_factory=_recorder_factory(calls),
    )

    result = agent.send(
        build_hourly_report_summary(title="小时报告", summary="3 个输出可用", facts={"allowed_outputs": 3}),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert result.ok is True
    assert result.status == "sent"
    assert result.run_id == "run-feishu-1"
    assert seen[0]["msg_type"] == "post"
    assert calls[0]["recorder"]["task_type"] == "feishu_notification"
    assert calls[1]["status"] == "success"
    assert calls[2]["exit_exc_type"] is None


def test_notification_agent_marks_task_failed_when_feishu_send_fails() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 19024, "msg": "sign match fail"})

    agent = FeishuNotificationAgent(
        client=FeishuWebhookClient(FeishuNotificationConfig(enabled=True, webhook_url="https://open.feishu.cn/hook/token")),
        recorder_factory=_recorder_factory(calls),
    )

    result = agent.send(
        build_test_message(message="hello"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert result.ok is False
    assert result.status == "failed"
    assert result.run_id == "run-feishu-1"
    assert result.error == "sign match fail"
    assert calls[1]["status"] == "failed"
    assert calls[2]["exit_exc_type"] == "_NotificationFailed"
