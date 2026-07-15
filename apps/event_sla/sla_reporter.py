from __future__ import annotations

from dataclasses import asdict
from typing import Any

from apps.event_sla.schemas import EventSnapshot
from apps.notifications.schemas import NotificationRequest


EVENT_SLA_STEP_NAMES = (
    "detect_update",
    "create_event_snapshot",
    "collect_raw",
    "parse_content",
    "run_quality_gate",
    "build_analysis_conclusion",
    "build_trading_strategy",
    "write_live_strategy_recompute_request",
    "build_sla_report",
    "write_notification_request",
    "record_sla_result",
)


def event_step_outcomes(*, event: EventSnapshot, status: str) -> dict[str, dict[str, str]]:
    outcomes = {
        name: {"status": "success", "execution_mode": "executed"}
        for name in EVENT_SLA_STEP_NAMES
    }
    if status == "failed":
        return {
            name: {"status": "failed", "execution_mode": "executed"}
            for name in EVENT_SLA_STEP_NAMES
        }
    if event.raw_refs:
        outcomes["collect_raw"] = {"status": "skipped", "execution_mode": "reused_existing_artifact"}
    else:
        outcomes["collect_raw"] = {"status": "skipped", "execution_mode": "not_required"}
    if event.parsed_refs:
        outcomes["parse_content"] = {"status": "skipped", "execution_mode": "reused_existing_artifact"}
    else:
        outcomes["parse_content"] = {"status": "blocked", "execution_mode": "blocked_by_missing_input"}
    if status == "partial_success":
        outcomes["build_trading_strategy"] = {"status": "blocked", "execution_mode": "blocked_by_quality_gate"}
    elif status == "blocked":
        outcomes["build_trading_strategy"] = {"status": "blocked", "execution_mode": "blocked_by_quality_gate"}
    return outcomes


def event_step_statuses(*, event: EventSnapshot, status: str) -> dict[str, str]:
    return {name: outcome["status"] for name, outcome in event_step_outcomes(event=event, status=status).items()}


def evidence_level(event: EventSnapshot) -> str:
    scope = str(event.content_access.get("content_scope") or "unknown")
    body_complete = bool(event.content_access.get("body_complete"))
    vip_locked = bool(event.content_access.get("vip_locked"))
    if scope == "full" and body_complete and not vip_locked:
        return "full"
    if scope == "preview" or vip_locked:
        return "preview"
    return "partial"


def event_status(*, event: EventSnapshot, quality_gate: dict[str, Any] | None) -> str:
    level = evidence_level(event)
    if event.event_type == "cme_bulletin" and not event.parsed_refs:
        return "blocked"
    if level != "full":
        return "partial_success"
    if quality_gate and quality_gate.get("readiness") == "blocked" and event.event_type != "jin10_report":
        return "blocked"
    return "success"


def build_analysis_report(*, event: EventSnapshot, status: str, strategy: dict[str, Any], quality_gate: dict[str, Any] | None) -> str:
    conclusion = _conclusion(event)
    lines = [
        "# Event SLA Analysis Report",
        "",
        f"- Event: {event.title}",
        f"- Source: {event.source_key}",
        f"- Status: {status}",
        f"- Evidence level: {strategy.get('evidence_level')}",
        "",
        "## 一句话结论",
        conclusion,
        "",
        "## 核心变量 / 结构",
    ]
    lines.extend(f"- {item}" for item in _variables(event))
    lines.extend(
        [
            "",
            "## 交易含义",
            f"- Bias: {strategy.get('bias')}",
            f"- Mode: {strategy.get('strategy_mode')}",
            f"- Confidence: {strategy.get('confidence')}",
            "",
            "## 允许 / 禁止输出",
            f"- Allowed: {', '.join((quality_gate or {}).get('allowed_outputs', [])) or '-'}",
            f"- Blocked: {', '.join((quality_gate or {}).get('blocked_outputs', [])) or '-'}",
            "",
            "## 不能下结论的部分",
        ]
    )
    if strategy.get("evidence_level") != "full":
        lines.append("- 正文不完整或权限受限，禁止输出确定性策略结论。")
    elif status == "blocked":
        lines.append("- 质量闸门阻断，禁止输出 full analysis。")
    else:
        lines.append("- 仍需结合实时价格、美元、利率和资金流确认。")
    return "\n".join(lines).rstrip() + "\n"


def build_notification_request(*, event: EventSnapshot, status: str, sla: dict[str, Any], analysis_report_path: str) -> dict[str, Any]:
    severity = "success" if status == "success" else ("warning" if status == "partial_success" else "critical")
    request = NotificationRequest(
        kind=_notification_kind(status),
        title=f"Event SLA {status}: {event.title}",
        summary=f"{event.source_key} status={status}; elapsed={float(sla['end_to_end_sla_minutes']):.1f}m",
        severity=severity,  # type: ignore[arg-type]
        facts={
            "event_id": event.event_id,
            "source_key": event.source_key,
            "status": status,
            **sla,
            "sla_minutes": 30,
            "analysis_report": analysis_report_path,
        },
        source_refs=[
            {
                "source": event.source_key,
                "source_ref": f"event:{event.event_id}",
                "data_date": event.trade_date,
            }
        ],
        trade_date=event.trade_date,
    )
    return asdict(request)


def _notification_kind(status: str) -> str:
    if status == "success":
        return "event_sla_completed"
    if status == "partial_success":
        return "event_sla_partial"
    return "event_sla_blocked"


def build_sla_trace(
    *,
    event: EventSnapshot,
    status: str,
    sla: dict[str, Any],
    artifacts: dict[str, str],
) -> dict[str, Any]:
    step_outcomes = event_step_outcomes(event=event, status=status)
    return {
        "task_type": "event_sla_analysis",
        "event_id": event.event_id,
        "source_key": event.source_key,
        "status": status,
        **sla,
        "sla_minutes": 30,
        "within_sla": float(sla["end_to_end_sla_minutes"]) <= 30,
        "artifacts": artifacts,
        "steps": [
            {
                "name": name,
                **step_outcomes[name],
                **(
                    {
                        "output_refs": [
                            {
                                "artifact_type": "live_strategy_recompute_request",
                                "path": artifacts["live_strategy_recompute_request"],
                            }
                        ]
                    }
                    if name == "write_live_strategy_recompute_request"
                    else {}
                ),
            }
            for name in EVENT_SLA_STEP_NAMES
        ],
    }


def _conclusion(event: EventSnapshot) -> str:
    if event.source_key == "cme_gold_options_bulletin":
        return str(event.payload.get("summary") or "CME 黄金期权结构已更新，需关注主要 OG 期权墙。")
    return str(event.payload.get("one_line_conclusion") or event.payload.get("summary") or "Jin10 报告已更新，需结合质量闸门做事件分析。")


def _variables(event: EventSnapshot) -> list[str]:
    if event.source_key == "cme_gold_options_bulletin":
        levels = event.payload.get("key_levels") if isinstance(event.payload.get("key_levels"), list) else []
        return [f"OG option wall: {level}" for level in levels] or ["OG option structure"]
    variables = event.payload.get("key_variables") if isinstance(event.payload.get("key_variables"), list) else []
    result = []
    for item in variables:
        if isinstance(item, dict):
            result.append(f"{item.get('name')}: {item.get('meaning') or item.get('observation') or ''}".strip())
    return result or ["报告主题与关键变量待人工复核"]
