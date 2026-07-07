from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.governance.artifact_io import update_json_atomically, write_json_atomically

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def persist_prompt_evaluation_cases(
    *,
    cases: list[Any],
    storage_root: Path | str = "storage",
    trade_date: str | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    now = _ensure_utc(observed_at or datetime.now(timezone.utc))
    day = trade_date or now.date().isoformat()
    _validate_trade_date(day)
    root = Path(storage_root)
    base = root / "governance" / "prompt_evolution" / day
    base.mkdir(parents=True, exist_ok=True)

    case_payloads = [_case_payload(item) for item in cases]
    cases_path = base / "prompt_evaluation_cases.json"
    _write_json(
        cases_path,
        {
            "trade_date": day,
            "observed_at": now.isoformat(),
            "count": len(case_payloads),
            "cases": case_payloads,
        },
    )
    return {
        "trade_date": day,
        "observed_at": now.isoformat(),
        "case_count": len(case_payloads),
        "artifacts": {
            "prompt_evaluation_cases": _rel(cases_path, root),
        },
    }


def persist_prompt_ab_validation_result(
    *,
    validation: Any,
    storage_root: Path | str = "storage",
    trade_date: str | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    now = _ensure_utc(observed_at or datetime.now(timezone.utc))
    day = trade_date or now.date().isoformat()
    _validate_trade_date(day)
    root = Path(storage_root)
    base = root / "governance" / "prompt_evolution" / day
    base.mkdir(parents=True, exist_ok=True)

    validation_payload = _payload(validation)
    validation_path = base / "prompt_ab_validation_result.json"
    _write_json(
        validation_path,
        {
            "trade_date": day,
            "observed_at": now.isoformat(),
            "validation": validation_payload,
        },
    )
    return {
        "trade_date": day,
        "observed_at": now.isoformat(),
        "validation_status": validation_payload.get("validation_status"),
        "improvement_count": validation_payload.get("improvement_count", 0),
        "regression_count": validation_payload.get("regression_count", 0),
        "artifacts": {
            "prompt_ab_validation_result": _rel(validation_path, root),
        },
    }


def persist_prompt_release_record(
    *,
    storage_root: Path | str = "storage",
    trade_date: str | None = None,
    observed_at: datetime | None = None,
    agent_name: str,
    action: str,
    active_prompt_version_id: str | None = None,
    candidate_prompt_version_id: str | None = None,
    validation_artifact: str | None = None,
    review_approved_by: str | None = None,
    test_result: str | None = None,
    rollback_reason: str | None = None,
    rolled_back_from: str | None = None,
    rolled_back_to: str | None = None,
    affected_agents: list[str] | None = None,
) -> dict[str, Any]:
    now = _ensure_utc(observed_at or datetime.now(timezone.utc))
    day = trade_date or now.date().isoformat()
    _validate_trade_date(day)
    root = Path(storage_root)
    base = root / "governance" / "prompt_evolution" / day
    base.mkdir(parents=True, exist_ok=True)

    records_path = base / "prompt_release_records.json"
    rollback_from = rolled_back_from if rolled_back_from is not None else active_prompt_version_id
    rollback_to = rolled_back_to if rolled_back_to is not None else candidate_prompt_version_id
    record = {
        "agent_name": agent_name,
        "action": action,
        "active_prompt_version_id": active_prompt_version_id,
        "candidate_prompt_version_id": candidate_prompt_version_id,
        "validation_artifact": validation_artifact,
        "review_approved_by": review_approved_by,
        "test_result": test_result,
        "rollback_reason": rollback_reason,
        "rolled_back_from": rollback_from if action == "rolled_back" else None,
        "rolled_back_to": rollback_to if action == "rolled_back" else None,
        "affected_agents": affected_agents or [agent_name],
        "recorded_at": now.isoformat(),
        "activated_prompt": False,
    }

    def append_record(existing: dict[str, Any]) -> dict[str, Any]:
        records = existing.get("records") if isinstance(existing.get("records"), list) else []
        next_records = [*records, record]
        return {
            "trade_date": day,
            "observed_at": now.isoformat(),
            "count": len(next_records),
            "records": next_records,
        }

    payload = update_json_atomically(records_path, append_record)
    return {
        "trade_date": day,
        "observed_at": now.isoformat(),
        "record_count": payload["count"],
        "record": record,
        "artifacts": {
            "prompt_release_records": _rel(records_path, root),
        },
    }


def _case_payload(item: Any) -> dict[str, Any]:
    return _payload(item)


def _payload(item: Any) -> dict[str, Any]:
    if hasattr(item, "to_dict"):
        payload = item.to_dict()
        return payload if isinstance(payload, dict) else {}
    return dict(item) if isinstance(item, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json_atomically(path, payload)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_trade_date(value: str) -> None:
    if not _DATE_RE.fullmatch(value):
        raise ValueError("trade_date must use YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("trade_date must use a valid YYYY-MM-DD date") from exc


def _rel(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
