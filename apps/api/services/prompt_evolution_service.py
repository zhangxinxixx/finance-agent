from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from apps.analysis.agents.prompt_evolution import build_prompt_evolution_proposal
from apps.governance.prompt_evolution_workflow import persist_prompt_release_record
from database.models.analysis import AgentOutput, PromptFeedback, PromptVersion, ReviewItem

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_STORAGE_ROOT = _PROJECT_ROOT / "storage"
_PROMPT_RELEASE_ACTIONS = {"release_approved", "rolled_back"}


@dataclass(frozen=True)
class PromptActivationDecision:
    ready: bool
    blocking_reasons: tuple[str, ...]
    release_approval_artifact: str | None = None
    validation_artifact: str | None = None


def get_prompt_evolution_latest(*, storage_root: Path | str = _STORAGE_ROOT, date: str | None = None) -> dict[str, Any]:
    root = Path(storage_root)
    trade_date = date or _latest_date(root)
    base = _artifact_dir(root, trade_date)
    cases = _read_json(base / "prompt_evaluation_cases.json")
    validation = _read_json(base / "prompt_ab_validation_result.json")
    release_records = _read_json(base / "prompt_release_records.json")
    validation_payload = validation.get("validation") if isinstance(validation.get("validation"), dict) else {}
    release_items = _default_items(release_records, "records")
    return {
        "trade_date": trade_date,
        "artifacts": _artifact_refs(root, trade_date),
        "cases": _default_items(cases, "cases"),
        "validation": validation_payload,
        "release_records": release_items,
        "release_readiness": _release_readiness(validation_payload, release_items["items"]),
    }


def build_prompt_evolution_preview(
    db: Session,
    *,
    agent_id: str,
    recent_limit: int = 10,
) -> dict[str, Any]:
    current_prompt, prompt_source = _current_prompt(db=db, agent_id=agent_id)
    recent_outputs = _recent_agent_outputs(db=db, agent_id=agent_id, limit=recent_limit)
    agent_output_ids = [str(row.id) for row in recent_outputs]
    feedback_rows = _prompt_feedback(db=db, agent_id=agent_id, limit=recent_limit)
    review_rows = _review_gate_findings(db=db, agent_output_ids=agent_output_ids, limit=recent_limit)
    proposal = build_prompt_evolution_proposal(
        agent_name=agent_id,
        current_prompt=current_prompt,
        recent_runs=[_agent_output_to_recent_run(row) for row in recent_outputs],
        review_gate_findings=[_review_item_to_finding(row) for row in review_rows],
        manual_feedback=[_feedback_to_finding(row) for row in feedback_rows],
        failed_test_cases=[],
        schema_version=_schema_version(current_prompt),
        data_source_health={},
    ).to_dict()
    return {
        "source": "prompt_evolution_preview",
        "agent_id": agent_id,
        "proposal_only": True,
        "current_prompt_source": prompt_source,
        "recent_run_count": len(recent_outputs),
        "feedback_count": len(feedback_rows),
        "review_gate_finding_count": len(review_rows),
        "input_refs": {
            "agent_output_ids": agent_output_ids,
            "feedback_ids": [row.feedback_id for row in feedback_rows],
            "review_ids": [row.review_id for row in review_rows],
        },
        "proposal": proposal,
        "writes": [],
    }


def record_prompt_release_action(
    request: Any,
    *,
    storage_root: Path | str = _STORAGE_ROOT,
) -> dict[str, Any]:
    payload = _request_payload(request)
    action = str(payload.get("action") or "").strip()
    if action not in _PROMPT_RELEASE_ACTIONS:
        raise ValueError(f"Invalid prompt release action: {action}")
    agent_name = str(payload.get("agent_name") or "").strip()
    if not agent_name:
        raise ValueError("agent_name is required")
    if action == "release_approved":
        if not str(payload.get("review_approved_by") or "").strip():
            raise ValueError("review_approved_by is required for release_approved")
        if not str(payload.get("validation_artifact") or "").strip():
            raise ValueError("validation_artifact is required for release_approved")
        candidate_prompt_version_id = str(payload.get("candidate_prompt_version_id") or "").strip()
        if not candidate_prompt_version_id:
            raise ValueError("candidate_prompt_version_id is required for release_approved")
        validation_reasons, _ = _validate_prompt_ab_artifact(
            storage_root=Path(storage_root),
            validation_artifact=str(payload["validation_artifact"]),
            agent_name=agent_name,
            candidate_prompt_version_id=candidate_prompt_version_id,
        )
        if validation_reasons:
            raise ValueError("candidate prompt release approval blocked: " + ", ".join(validation_reasons))
    if action == "rolled_back" and not str(payload.get("rollback_reason") or "").strip():
        raise ValueError("rollback_reason is required for rolled_back")

    result = persist_prompt_release_record(
        storage_root=storage_root,
        trade_date=_optional_str(payload.get("trade_date")),
        agent_name=agent_name,
        action=action,
        active_prompt_version_id=_optional_str(payload.get("active_prompt_version_id")),
        candidate_prompt_version_id=_optional_str(payload.get("candidate_prompt_version_id")),
        validation_artifact=_optional_str(payload.get("validation_artifact")),
        review_approved_by=_optional_str(payload.get("review_approved_by")),
        test_result=_optional_str(payload.get("test_result")),
        rollback_reason=_optional_str(payload.get("rollback_reason")),
        rolled_back_from=_optional_str(payload.get("rolled_back_from")),
        rolled_back_to=_optional_str(payload.get("rolled_back_to")),
        affected_agents=_optional_str_list(payload.get("affected_agents")),
    )
    artifact = result["artifacts"]["prompt_release_records"]
    return {
        **result,
        "source": "prompt_evolution_release_action",
        "status": "recorded",
        "activated_prompt": False,
        "writes": [artifact],
    }


def has_prompt_release_approval(
    *,
    agent_name: str,
    candidate_prompt_version_id: str,
    storage_root: Path | str = _STORAGE_ROOT,
    release_approval_artifact: str | None = None,
) -> bool:
    """Compatibility wrapper for callers that only need a readiness boolean."""
    return evaluate_prompt_activation_readiness(
        agent_name=agent_name,
        candidate_prompt_version_id=candidate_prompt_version_id,
        storage_root=storage_root,
        release_approval_artifact=release_approval_artifact,
    ).ready


def evaluate_prompt_activation_readiness(
    *,
    agent_name: str,
    candidate_prompt_version_id: str,
    storage_root: Path | str = _STORAGE_ROOT,
    release_approval_artifact: str | None = None,
) -> PromptActivationDecision:
    """Evaluate the latest effective governance state for one prompt candidate."""
    root = Path(storage_root)
    if release_approval_artifact:
        explicit_paths = _release_record_paths(root, release_approval_artifact)
        if not explicit_paths:
            return PromptActivationDecision(False, ("release_approval_artifact_not_allowed",))
        if not _contains_candidate_release(
            explicit_paths[0],
            agent_name=agent_name,
            candidate_prompt_version_id=candidate_prompt_version_id,
        ):
            return PromptActivationDecision(False, ("release_approval_not_found_in_artifact",))

    paths = _release_record_paths(root, None)

    matching_records: list[tuple[Path, int, dict[str, Any]]] = []
    for path in paths:
        records = _read_json(path).get("records")
        if not isinstance(records, list):
            continue
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            if record.get("agent_name") != agent_name:
                continue
            action = record.get("action")
            if action == "release_approved" and record.get("candidate_prompt_version_id") == candidate_prompt_version_id:
                matching_records.append((path, index, record))
            elif action == "rolled_back" and _rollback_source(record) == candidate_prompt_version_id:
                matching_records.append((path, index, record))

    if not matching_records:
        return PromptActivationDecision(False, ("missing_release_approval",))

    latest_path, _, latest_record = max(matching_records, key=_governance_record_order)
    if latest_record.get("action") == "rolled_back":
        return PromptActivationDecision(
            False,
            ("candidate_rolled_back",),
            release_approval_artifact=_rel(latest_path, root),
        )

    validation_artifact = str(latest_record.get("validation_artifact") or "").strip()
    reasons, validation_path = _validate_prompt_ab_artifact(
        storage_root=root,
        validation_artifact=validation_artifact,
        agent_name=agent_name,
        candidate_prompt_version_id=candidate_prompt_version_id,
    )
    return PromptActivationDecision(
        not reasons,
        tuple(reasons),
        release_approval_artifact=_rel(latest_path, root),
        validation_artifact=_rel(validation_path, root) if validation_path is not None else None,
    )


def _governance_record_order(item: tuple[Path, int, dict[str, Any]]) -> tuple[int, datetime, str, int]:
    path, index, record = item
    recorded_at = str(record.get("recorded_at") or "").strip()
    try:
        observed_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    except ValueError:
        observed_at = datetime.min.replace(tzinfo=timezone.utc)
        has_timestamp = 0
    else:
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        else:
            observed_at = observed_at.astimezone(timezone.utc)
        has_timestamp = 1
    return has_timestamp, observed_at, path.as_posix(), index


def _contains_candidate_release(
    path: Path,
    *,
    agent_name: str,
    candidate_prompt_version_id: str,
) -> bool:
    records = _read_json(path).get("records")
    if not isinstance(records, list):
        return False
    return any(
        isinstance(record, dict)
        and record.get("action") == "release_approved"
        and record.get("agent_name") == agent_name
        and record.get("candidate_prompt_version_id") == candidate_prompt_version_id
        for record in records
    )


def _current_prompt(*, db: Session, agent_id: str) -> tuple[dict[str, Any], str]:
    row = (
        db.query(PromptVersion)
        .filter(PromptVersion.agent_id == agent_id, PromptVersion.status == "active", PromptVersion.enabled.is_(True))
        .order_by(desc(PromptVersion.created_at))
        .first()
    )
    if row is not None:
        return dict(row.prompt_template or {}), f"prompt_versions:{row.id}:{row.version}"

    from apps.analysis.agents.registry import get_agent_registry

    agent = get_agent_registry(agent_id)
    prompt = (agent or {}).get("prompt") if isinstance(agent, dict) else {}
    template = prompt.get("template") if isinstance(prompt, dict) else {}
    return dict(template or {"agent_id": agent_id}), "agent_registry"


def _recent_agent_outputs(*, db: Session, agent_id: str, limit: int) -> list[AgentOutput]:
    return list(
        db.query(AgentOutput)
        .filter(AgentOutput.agent_name == agent_id)
        .order_by(desc(AgentOutput.created_at))
        .limit(max(1, min(limit, 50)))
        .all()
    )


def _prompt_feedback(*, db: Session, agent_id: str, limit: int) -> list[PromptFeedback]:
    return list(
        db.query(PromptFeedback)
        .filter(PromptFeedback.agent_id == agent_id)
        .order_by(desc(PromptFeedback.created_at))
        .limit(max(1, min(limit, 50)))
        .all()
    )


def _review_gate_findings(*, db: Session, agent_output_ids: list[str], limit: int) -> list[ReviewItem]:
    if not agent_output_ids:
        return []
    return list(
        db.query(ReviewItem)
        .filter(ReviewItem.agent_output_id.in_(agent_output_ids))
        .order_by(desc(ReviewItem.created_at))
        .limit(max(1, min(limit, 50)))
        .all()
    )


def _agent_output_to_recent_run(row: AgentOutput) -> dict[str, Any]:
    payload = dict(row.payload or {})
    return {
        "agent_output_id": str(row.id),
        "run_id": row.run_id,
        "status": row.status,
        "summary": row.summary,
        "quality_issues": _quality_issues(payload),
        "review_gate": payload.get("review_gate") if isinstance(payload.get("review_gate"), dict) else {},
        "prompt_version_id": row.prompt_version_id,
    }


def _quality_issues(payload: dict[str, Any]) -> list[Any]:
    issues: list[Any] = []
    for key in ("quality_issues", "failure_patterns", "warnings", "blocking_issues"):
        value = payload.get(key)
        if isinstance(value, list):
            issues.extend(value)
    return issues


def _feedback_to_finding(row: PromptFeedback) -> dict[str, Any]:
    suggested = row.suggested_changes if isinstance(row.suggested_changes, dict) else {}
    issue_code = suggested.get("issue_code") or suggested.get("pattern_id") or row.category
    description = row.comment or suggested.get("description") or row.category
    return {
        "id": row.feedback_id,
        "issue_code": issue_code,
        "description": description,
        "likely_root_cause": suggested.get("likely_root_cause") or _root_cause_from_feedback(row),
        "rating": row.rating,
        "status": row.status,
    }


def _review_item_to_finding(row: ReviewItem) -> dict[str, Any]:
    return {
        "id": row.review_id,
        "issue_code": row.source_step_id or row.claim_id or row.source_module,
        "description": row.reason,
        "likely_root_cause": _root_cause_from_review(row),
        "severity": row.severity,
        "status": row.status,
    }


def _root_cause_from_feedback(row: PromptFeedback) -> str:
    if row.category in {"analysis_error", "prompt_quality"}:
        return "prompt"
    if row.category == "missing_context":
        return "data_missing"
    return "unknown"


def _root_cause_from_review(row: ReviewItem) -> str:
    text = f"{row.source_module} {row.reason} {row.suggested_action or ''}".lower()
    if "schema" in text:
        return "schema"
    if "source" in text or "p0" in text or "data" in text:
        return "data_missing"
    if "dag" in text or "trace" in text:
        return "dag"
    return "prompt"


def _schema_version(current_prompt: dict[str, Any]) -> str | None:
    value = current_prompt.get("schema_version")
    if value is None:
        value = current_prompt.get("output_schema_version")
    return str(value) if value not in {None, ""} else None


def _request_payload(request: Any) -> dict[str, Any]:
    if hasattr(request, "model_dump"):
        payload = request.model_dump(mode="json", exclude_none=True)
        return payload if isinstance(payload, dict) else {}
    return dict(request) if isinstance(request, dict) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_str_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    items = [str(item).strip() for item in value]
    return [item for item in items if item] or None


def _release_readiness(validation: dict[str, Any], records: list[Any]) -> dict[str, Any]:
    blocking_reasons: list[str] = []
    validation_status = str(validation.get("validation_status") or "").strip()
    if not validation_status:
        blocking_reasons.append("missing_ab_validation")
    elif validation_status != "pass":
        blocking_reasons.append(f"validation_status:{validation_status}")
    if validation_status:
        regression_reason = _regression_count_reason(validation.get("regression_count"))
        if regression_reason:
            blocking_reasons.append(regression_reason)

    validation_blocked = bool(blocking_reasons)
    latest_governance = _latest_governance_record(records)
    latest_rollback = _latest_record_action(records, "rolled_back")
    latest_release_action = latest_governance.get("action") if latest_governance else None
    latest_rollback_reason = latest_rollback.get("rollback_reason") if latest_rollback else None
    rolled_back = latest_release_action == "rolled_back"
    approved = latest_release_action == "release_approved"
    if rolled_back:
        blocking_reasons.append("latest_release_rolled_back")

    if validation_blocked:
        status = "blocked"
    elif rolled_back:
        status = "rolled_back"
    elif approved:
        status = "approved"
    else:
        status = "awaiting_review_approval"

    return {
        "status": status,
        "can_request_release_approval": not blocking_reasons and not approved,
        "can_activate_after_review": not blocking_reasons and approved,
        "can_record_rollback": not blocking_reasons and approved,
        "blocking_reasons": blocking_reasons,
        "latest_release_action": latest_release_action,
        "latest_rollback_reason": latest_rollback_reason,
    }


def _latest_governance_record(records: list[Any]) -> dict[str, Any] | None:
    for item in reversed(records):
        if isinstance(item, dict) and item.get("action") in _PROMPT_RELEASE_ACTIONS:
            return item
    return None


def _latest_record_action(records: list[Any], action: str) -> dict[str, Any] | None:
    for item in reversed(records):
        if isinstance(item, dict) and item.get("action") == action:
            return item
    return None


def _artifact_refs(storage_root: Path, trade_date: str) -> dict[str, str | None]:
    refs = {}
    for key, filename in (
        ("prompt_evaluation_cases", "prompt_evaluation_cases.json"),
        ("prompt_ab_validation_result", "prompt_ab_validation_result.json"),
        ("prompt_release_records", "prompt_release_records.json"),
    ):
        path = _artifact_dir(storage_root, trade_date) / filename
        refs[key] = _rel(path, storage_root) if path.is_file() else None
    return refs


def _default_items(payload: dict[str, Any], key: str) -> dict[str, Any]:
    items = payload.get(key) if isinstance(payload.get(key), list) else []
    return {"count": len(items), "items": items}


def _artifact_dir(storage_root: Path, trade_date: str) -> Path:
    return storage_root / "governance" / "prompt_evolution" / trade_date


def _latest_date(storage_root: Path) -> str:
    root = storage_root / "governance" / "prompt_evolution"
    if not root.exists():
        return ""
    dates = sorted(path.name for path in root.iterdir() if path.is_dir())
    return dates[-1] if dates else ""


def _validate_prompt_ab_artifact(
    *,
    storage_root: Path,
    validation_artifact: str,
    agent_name: str,
    candidate_prompt_version_id: str,
) -> tuple[list[str], Path | None]:
    path = _resolve_prompt_artifact(
        storage_root,
        validation_artifact,
        expected_filename="prompt_ab_validation_result.json",
    )
    if path is None:
        return ["validation_artifact_not_allowed"], None
    if not path.is_file():
        return ["validation_artifact_missing"], path

    payload = _read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else None
    if validation is None:
        return ["validation_artifact_invalid"], path

    reasons: list[str] = []
    if validation.get("agent_name") != agent_name:
        reasons.append("validation_agent_mismatch")

    validation_status = str(validation.get("validation_status") or "").strip()
    if validation_status != "pass":
        reasons.append(f"validation_status:{validation_status or 'missing'}")

    regression_reason = _regression_count_reason(validation.get("regression_count"))
    if regression_reason:
        reasons.append(regression_reason)

    candidate = validation.get("candidate_prompt_result")
    candidate_refs: set[str] = set()
    if isinstance(candidate, dict):
        for key in ("id", "prompt_version_id", "candidate_prompt_version_id"):
            value = str(candidate.get(key) or "").strip()
            if value:
                candidate_refs.add(value)
    if candidate_prompt_version_id not in candidate_refs:
        reasons.append("validation_candidate_mismatch")
    return reasons, path


def _regression_count_reason(value: Any) -> str | None:
    if value is None:
        return "validation_regression_count_missing"
    if isinstance(value, bool):
        return "validation_regression_count_invalid"
    if isinstance(value, int):
        return None if value == 0 else "validation_has_regressions"
    if isinstance(value, float):
        return "validation_has_regressions" if value != 0 else "validation_regression_count_invalid"
    return "validation_regression_count_invalid"


def _rollback_source(record: dict[str, Any]) -> str:
    return str(record.get("rolled_back_from") or record.get("active_prompt_version_id") or "").strip()


def _resolve_prompt_artifact(
    storage_root: Path,
    artifact_ref: str,
    *,
    expected_filename: str,
) -> Path | None:
    artifact = Path(artifact_ref)
    path = artifact if artifact.is_absolute() else storage_root / artifact
    resolved = path.resolve()
    allowed_root = (storage_root / "governance" / "prompt_evolution").resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError:
        return None
    return resolved if resolved.name == expected_filename else None


def _release_record_paths(storage_root: Path, release_approval_artifact: str | None) -> list[Path]:
    if release_approval_artifact:
        path = _resolve_prompt_artifact(
            storage_root,
            release_approval_artifact,
            expected_filename="prompt_release_records.json",
        )
        return [path] if path is not None and path.is_file() else []

    root = storage_root / "governance" / "prompt_evolution"
    if not root.exists():
        return []
    return sorted(root.glob("*/prompt_release_records.json"))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _rel(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
