from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from apps.api.schemas.common import DataStatus
from apps.api.schemas.event_flow import EventFlowActionRequest, EventFlowActionResponse, EventFlowBriefLinkRequest
from apps.api.schemas.source_trace import SourceRef
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep
from database.queries.review import upsert_review_item

_ACTION_IMPACT_MODULES: dict[str, list[str]] = {
    "link": ["event_flow", "reports"],
    "ignore": ["event_flow"],
    "include": ["event_flow", "reports"],
    "exclude": ["event_flow", "reports"],
    "review": ["event_flow"],
}


def register_brief_link(db: Session, brief_id: str, body: EventFlowBriefLinkRequest) -> EventFlowActionResponse:
    source_refs = [
        _entity_source_ref("brief", brief_id, status="requested"),
        _entity_source_ref("event", body.target_event_id, status="target"),
    ]
    return _register_action(
        db,
        entity_type="brief",
        entity_id=brief_id,
        action="link",
        request=body,
        source_refs=source_refs,
        context={"target_event_id": body.target_event_id},
    )


def register_brief_ignore(db: Session, brief_id: str, body: EventFlowActionRequest) -> EventFlowActionResponse:
    return _register_action(
        db,
        entity_type="brief",
        entity_id=brief_id,
        action="ignore",
        request=body,
        source_refs=[_entity_source_ref("brief", brief_id, status="requested")],
    )


def register_report_input_include(db: Session, input_id: str, body: EventFlowActionRequest) -> EventFlowActionResponse:
    return _register_action(
        db,
        entity_type="report_input",
        entity_id=input_id,
        action="include",
        request=body,
        source_refs=[_entity_source_ref("report_input", input_id, status="requested")],
    )


def register_report_input_exclude(db: Session, input_id: str, body: EventFlowActionRequest) -> EventFlowActionResponse:
    return _register_action(
        db,
        entity_type="report_input",
        entity_id=input_id,
        action="exclude",
        request=body,
        source_refs=[_entity_source_ref("report_input", input_id, status="requested")],
    )


def register_event_review(db: Session, event_id: str, body: EventFlowActionRequest) -> EventFlowActionResponse:
    return _register_action(
        db,
        entity_type="event",
        entity_id=event_id,
        action="review",
        request=body,
        source_refs=[_entity_source_ref("event", event_id, status="requested")],
    )


def _register_action(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    request: EventFlowActionRequest,
    source_refs: list[SourceRef],
    context: dict[str, Any] | None = None,
) -> EventFlowActionResponse:
    now = datetime.now(UTC)
    audit_id = _audit_id(entity_type, entity_id, action, request)
    review_id = _review_id(entity_type, entity_id, action, request)
    queued_message = "event flow action registered; executor wiring not implemented"

    run = TaskRun(
        name=f"event_flow:{action}:{entity_type}:{entity_id}",
        task_type="event_flow_action",
        status=TaskStatus.blocked,
        current_stage="review",
        progress=0.0,
        started_at=now,
        error_summary=queued_message,
        error=queued_message,
    )
    db.add(run)
    db.flush()

    step = TaskStep(
        task_run_id=run.id,
        name=f"{action}:{entity_type}:{entity_id}",
        stage="review",
        task_kind=f"event_flow_{action}",
        status=StepStatus.blocked,
        started_at=now,
        source_refs=_dump_refs(source_refs),
        input_json=json.dumps(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
                "request_id": request.request_id,
                "actor": request.actor,
                "reason": request.reason,
                "note": request.note,
                "context": context or {},
            },
            ensure_ascii=True,
        ),
        output_json=json.dumps(
            {
                "status": "accepted",
                "review_id": review_id,
                "audit_id": audit_id,
                "queued": True,
            },
            ensure_ascii=True,
        ),
        error=queued_message,
        error_type="manual_required",
        blocked_reason="awaiting review or future event-flow executor",
        retry_count=0,
        step_order=1,
    )
    db.add(step)
    db.flush()

    upsert_review_item(
        db,
        {
            "review_id": review_id,
            "run_id": str(run.id),
            "source_module": "event_flow",
            "source_step_id": str(step.id),
            "severity": "warning",
            "reason": _review_reason(action, entity_type, entity_id, request),
            "impact_modules": _ACTION_IMPACT_MODULES.get(action, ["event_flow"]),
            "impact_report_ids": [],
            "source_refs": [ref.model_dump(mode="json", exclude_none=True) for ref in source_refs],
            "evidence_refs": [],
            "suggested_action": action,
            "status": "pending",
            "audit_id": audit_id,
            "action_status": "queued_not_implemented",
        },
    )

    db.commit()

    return EventFlowActionResponse(
        status="accepted",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        run_id=str(run.id),
        review_id=review_id,
        audit_id=audit_id,
        data_status=DataStatus.partial,
        source_refs=source_refs,
    )


def _entity_source_ref(entity_type: str, entity_id: str, *, status: str) -> SourceRef:
    return SourceRef(
        source_id=f"event_flow_{entity_type}:{entity_id}",
        source_name=f"event_flow_{entity_type}",
        source_type="event_flow_action",
        status=status,
    )


def _audit_id(entity_type: str, entity_id: str, action: str, request: EventFlowActionRequest) -> str:
    return f"event-flow-action:{entity_type}:{entity_id}:{request.request_id or action}"


def _review_id(entity_type: str, entity_id: str, action: str, request: EventFlowActionRequest) -> str:
    suffix = request.request_id or uuid.uuid4().hex[:10]
    return f"event-flow:{action}:{entity_type}:{entity_id}:{suffix}"


def _review_reason(action: str, entity_type: str, entity_id: str, request: EventFlowActionRequest) -> str:
    base = request.reason or request.note or f"manual event flow {action} request"
    return f"{base} ({entity_type}:{entity_id})"


def _dump_refs(refs: list[SourceRef]) -> str:
    return json.dumps([ref.model_dump(mode="json", exclude_none=True) for ref in refs], ensure_ascii=True)
