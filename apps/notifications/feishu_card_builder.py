from __future__ import annotations

from typing import Any

from apps.notifications.schemas import NotificationRequest

_SEVERITY_LABELS = {
    "info": "INFO",
    "success": "SUCCESS",
    "warning": "WARNING",
    "critical": "CRITICAL",
}

_KIND_LABELS = {
    "test": "测试消息",
    "hourly_report": "小时报告摘要",
    "incident": "异常/阻断通知",
    "sla_completed": "SLA 事件完成",
    "event_sla_completed": "SLA 事件完成",
    "event_sla_partial": "SLA 事件部分完成",
    "event_sla_blocked": "SLA 事件阻断",
    "pre_analysis_readiness": "主分析前就绪检查",
}


def build_test_message(*, message: str = "finance-agent 飞书通知测试", title: str = "Feishu Notification Test") -> NotificationRequest:
    return NotificationRequest(kind="test", title=title, summary=message, severity="info")


def build_hourly_report_summary(*, title: str, summary: str, facts: dict[str, Any] | None = None) -> NotificationRequest:
    return NotificationRequest(kind="hourly_report", title=title, summary=summary, severity="info", facts=facts or {})


def build_incident_notification(*, title: str, summary: str, facts: dict[str, Any] | None = None) -> NotificationRequest:
    return NotificationRequest(kind="incident", title=title, summary=summary, severity="critical", facts=facts or {})


def build_sla_completion_notification(*, title: str, summary: str, facts: dict[str, Any] | None = None) -> NotificationRequest:
    return NotificationRequest(kind="event_sla_completed", title=title, summary=summary, severity="success", facts=facts or {})


def build_sla_partial_notification(*, title: str, summary: str, facts: dict[str, Any] | None = None) -> NotificationRequest:
    return NotificationRequest(kind="event_sla_partial", title=title, summary=summary, severity="warning", facts=facts or {})


def build_sla_blocked_notification(*, title: str, summary: str, facts: dict[str, Any] | None = None) -> NotificationRequest:
    return NotificationRequest(kind="event_sla_blocked", title=title, summary=summary, severity="critical", facts=facts or {})


def render_feishu_message(request: NotificationRequest) -> tuple[str, str]:
    title = request.title.strip() or _KIND_LABELS[request.kind]
    lines = [
        f"[{_SEVERITY_LABELS[request.severity]}] {_KIND_LABELS[request.kind]}",
        "",
        request.summary.strip(),
    ]
    fact_lines = _render_facts(request.facts)
    if fact_lines:
        lines.extend(["", "关键字段:", *fact_lines])
    if request.sections:
        lines.append("")
        lines.extend(section.strip() for section in request.sections if section.strip())
    if request.source_refs:
        lines.extend(["", f"source_refs: {len(request.source_refs)}"])
    return title, "\n".join(line for line in lines if line is not None).strip()


def _render_facts(facts: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in facts.items():
        if value is None:
            continue
        lines.append(f"- {key}: {value}")
    return lines
