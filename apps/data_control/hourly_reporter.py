from __future__ import annotations

from dataclasses import asdict
from typing import Any

from apps.notifications.schemas import NotificationRequest


def build_hourly_report(
    *,
    trade_date: str,
    observed_at: str,
    hour: str,
    availability_snapshot: dict[str, Any],
    collection_plan: dict[str, Any],
    processing_plan: dict[str, Any],
    dispatch_plan: dict[str, Any],
) -> dict[str, Any]:
    status = _status(availability_snapshot=availability_snapshot, processing_plan=processing_plan)
    readiness = processing_plan.get("quality_gate") if isinstance(processing_plan.get("quality_gate"), dict) else {}
    quality_gate_evaluation = (
        processing_plan.get("quality_gate_evaluation")
        if isinstance(processing_plan.get("quality_gate_evaluation"), dict)
        else {"status": "missing", "reason_code": "downstream_readiness_missing"}
    )
    allowed_outputs = readiness.get("allowed_outputs") or []
    blocked_outputs = readiness.get("blocked_outputs") or []
    capabilities = readiness.get("capabilities") if isinstance(readiness.get("capabilities"), dict) else None
    if quality_gate_evaluation.get("status") != "current":
        main_readiness = "blocked"
        knowledge_readiness = "blocked"
    elif capabilities is not None:
        main_readiness = _readiness_label(capabilities.get("full_daily_analysis"))
        knowledge_readiness = _readiness_label(capabilities.get("knowledge_distillation"))
    else:
        main_readiness = "ready" if readiness.get("can_run_full_analysis") else ("limited" if allowed_outputs else "blocked")
        if "full analysis" in blocked_outputs:
            main_readiness = "blocked"
        knowledge_readiness = "ready" if readiness.get("can_run_research_distillation") else "blocked"
    notification_request = _notification_request(
        trade_date=trade_date,
        hour=hour,
        status=status,
        main_readiness=main_readiness,
        knowledge_readiness=knowledge_readiness,
        collection_plan=collection_plan,
        processing_plan=processing_plan,
    )
    return {
        "trade_date": trade_date,
        "observed_at": observed_at,
        "hour": hour,
        "timezone": "UTC",
        "status": status,
        "main_analysis_readiness": main_readiness,
        "knowledge_distillation_readiness": knowledge_readiness,
        "availability": availability_snapshot,
        "collection": _collection_summary(collection_plan),
        "processing": _processing_summary(processing_plan),
        "dispatch": dispatch_plan.get("summary") or {},
        "quality_gate": readiness,
        "quality_gate_evaluation": quality_gate_evaluation,
        "allowed_outputs": allowed_outputs,
        "blocked_outputs": blocked_outputs,
        "next_hour_plan": _next_hour_plan(collection_plan=collection_plan, processing_plan=processing_plan),
        "notification_request": asdict(notification_request),
    }


def _readiness_label(state: Any) -> str:
    if state == "allowed":
        return "ready"
    if state == "degraded":
        return "limited"
    return "blocked"


def render_hourly_report_markdown(report: dict[str, Any]) -> str:
    collection = report.get("collection") if isinstance(report.get("collection"), dict) else {}
    processing = report.get("processing") if isinstance(report.get("processing"), dict) else {}
    lines = [
        "# 每小时采集加工报告",
        "",
        "## 1. 当前小时结论",
        f"- 状态：{report.get('status')}",
        f"- 主分析：{report.get('main_analysis_readiness')}",
        f"- 知识蒸馏：{report.get('knowledge_distillation_readiness')}",
        "",
        "## 2. 采集状态",
        f"- 可用：{', '.join(collection.get('available', [])) or '-'}",
        f"- 等待：{', '.join(collection.get('waiting', [])) or '-'}",
        f"- 过期：{', '.join(collection.get('stale', [])) or '-'}",
        f"- 缺失：{', '.join(collection.get('missing', [])) or '-'}",
        f"- 阻断：{', '.join(collection.get('blocked', [])) or '-'}",
        "",
        "## 3. 加工状态",
        f"- 可执行：{', '.join(processing.get('ready_steps', [])) or '-'}",
        f"- 缺失 artifact：{len(processing.get('missing_artifacts', []))}",
        f"- 阻断步骤：{len(processing.get('blocked_steps', []))}",
        "",
        "## 4. 派发计划",
        f"- 可派发：{(report.get('dispatch') or {}).get('ready', 0)}",
        f"- 待 Worker：{(report.get('dispatch') or {}).get('planned', 0)}",
        f"- 人工处理：{(report.get('dispatch') or {}).get('manual_required', 0)}",
        "",
        "## 5. 下游影响",
        f"- 允许输出：{', '.join(report.get('allowed_outputs', [])) or '-'}",
        f"- 禁止输出：{', '.join(report.get('blocked_outputs', [])) or '-'}",
        "",
        "## 6. 下一小时计划",
    ]
    lines.extend(f"- {item}" for item in report.get("next_hour_plan", []))
    return "\n".join(lines).rstrip() + "\n"


def _status(*, availability_snapshot: dict[str, Any], processing_plan: dict[str, Any]) -> str:
    if processing_plan.get("status") == "blocked":
        return "blocked"
    overall_state = str(availability_snapshot.get("overall_state") or "normal")
    if overall_state == "blocked":
        return "blocked"
    if overall_state == "degraded":
        return "degraded"
    if overall_state == "waiting":
        return "waiting"
    if processing_plan.get("status") == "partial":
        return "partial"
    return "normal"


def _collection_summary(collection_plan: dict[str, Any]) -> dict[str, list[str]]:
    grouped = {state: [] for state in ("available", "waiting", "missing", "stale", "blocked")}
    for item in collection_plan.get("actions", []):
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "")
        if state in grouped and item.get("source_key"):
            grouped[state].append(str(item["source_key"]))
    return grouped


def _processing_summary(processing_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "ready_steps": processing_plan.get("ready_steps") or [],
        "missing_artifacts": processing_plan.get("missing_artifacts") or [],
        "blocked_steps": processing_plan.get("blocked_steps") or [],
    }


def _next_hour_plan(*, collection_plan: dict[str, Any], processing_plan: dict[str, Any]) -> list[str]:
    plan: list[str] = []
    for item in collection_plan.get("actions", []):
        if not isinstance(item, dict):
            continue
        source_key = item.get("source_key")
        action = item.get("action")
        if action == "refresh":
            plan.append(f"refresh {source_key}")
        elif action == "collect":
            plan.append(f"collect {source_key}")
        elif action == "wait":
            plan.append(f"wait for {source_key} publication window")
        elif action == "manual_review":
            plan.append(f"manual review {source_key}")
    if processing_plan.get("blocked_steps"):
        plan.append("re-run data quality monitor before full analysis")
    return plan


def _notification_request(
    *,
    trade_date: str,
    hour: str,
    status: str,
    main_readiness: str,
    knowledge_readiness: str,
    collection_plan: dict[str, Any],
    processing_plan: dict[str, Any],
) -> NotificationRequest:
    severity = "critical" if status == "blocked" else ("warning" if status in {"partial", "degraded"} else "info")
    return NotificationRequest(
        kind="hourly_report",
        title=f"Data control hourly report {trade_date} {hour}:00",
        summary=f"status={status}; main_analysis={main_readiness}; knowledge_distillation={knowledge_readiness}",
        severity=severity,  # type: ignore[arg-type]
        facts={
            "trade_date": trade_date,
            "hour": hour,
            "status": status,
            "collection_status": collection_plan.get("status"),
            "processing_status": processing_plan.get("status"),
            "main_analysis_readiness": main_readiness,
            "knowledge_distillation_readiness": knowledge_readiness,
        },
        source_refs=[{"source": "data_control_agent", "trade_date": trade_date, "hour": hour}],
        trade_date=trade_date,
    )
