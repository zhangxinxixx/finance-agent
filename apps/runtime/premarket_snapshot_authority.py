"""Transactional authority contract for canonical premarket snapshots.

The writer stages all three authority rows in the caller's transaction.  The
general reader resolves one exact successful run.  A separate Gold daily-report
reader may resolve one explicitly scoped blocked run.  Both fail closed on every
mismatch and never infer authority from filesystem recency.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.runtime.artifact_registry import register_artifact
from database.models.analysis import AnalysisSnapshot
from database.models.execution import RunArtifact
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep
from database.queries.analysis import upsert_analysis_snapshot

AuthorityStatus = Literal["found", "missing", "ambiguous", "unavailable", "invalid"]
_ASSET = "XAUUSD"
_TASK_NAME = "premarket"
_ARTIFACT_TYPE = "feature_json"
_ARTIFACT_NAME = "premarket_snapshot.json"
_STRATEGY_CARD_STEP = "strategy_card"
_GOLD_DAILY_REPORT_AUTHORITY_SCHEMA = "gold_daily_report_premarket_authority.v1"
_GOLD_DAILY_REPORT_AUTHORITY_SCOPE = "gold_daily_report_only"
_GOLD_DAILY_REPORT_BLOCK_REASONS = frozenset(
    {
        "downstream_full_analysis_blocked",
        "downstream_readiness_not_ready",
    }
)


@dataclass(frozen=True)
class PremarketSnapshotAuthority:
    status: AuthorityStatus
    reason_code: str
    snapshot_path: Path | None = None
    run_id: str | None = None
    snapshot_id: str | None = None


def canonicalize_premarket_snapshot_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the exact JSON-domain object used by files, hashes, DB rows, and downstream ops."""
    if not isinstance(snapshot, dict):
        raise ValueError("premarket snapshot payload must be an object")
    try:
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        payload = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("premarket snapshot payload must be canonical JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("premarket snapshot payload must be an object")
    return payload


def stage_premarket_snapshot_authority(
    db: Session,
    *,
    run_id: str,
    snapshot: dict[str, Any],
    snapshot_path: Path,
    storage_root: Path,
) -> AnalysisSnapshot:
    """Stage canonical snapshot authority without committing the transaction."""
    snapshot = canonicalize_premarket_snapshot_payload(snapshot)
    run_uuid = _parse_uuid(run_id)
    run = db.get(TaskRun, run_uuid)
    if run is None:
        raise ValueError(f"premarket authority run missing: {run_id}")
    if not _is_canonical_premarket_run(run) or run.status != TaskStatus.running:
        raise ValueError("premarket authority requires a running canonical premarket TaskRun")

    trade_date = _snapshot_trade_date(snapshot)
    snapshot_id = _snapshot_identity(snapshot, run_id=run_id, trade_date=trade_date)
    expected_path = _expected_snapshot_path(
        storage_root=storage_root,
        trade_date=trade_date,
        run_id=run_id,
    )
    persisted_path = str(expected_path)
    supplied_path = Path(snapshot_path)
    if supplied_path.absolute() != expected_path.absolute():
        raise ValueError(f"premarket snapshot path mismatch: expected {expected_path}")
    _validate_file_path(expected_path, storage_root=storage_root)

    raw = expected_path.read_bytes()
    file_payload = _decode_json_object(raw)
    if file_payload != snapshot:
        raise ValueError("premarket snapshot file payload mismatch")

    input_snapshot_ids = snapshot.get("input_snapshot_ids", {})
    source_refs = snapshot.get("source_refs", [])
    if not isinstance(input_snapshot_ids, dict):
        raise ValueError("premarket snapshot input_snapshot_ids must be an object")
    if not isinstance(source_refs, list) or any(not isinstance(item, dict) for item in source_refs):
        raise ValueError("premarket snapshot source_refs must be a list of objects")
    if run.trade_date not in {None, trade_date} or run.snapshot_id not in {None, snapshot_id}:
        raise ValueError("premarket TaskRun authority conflict")

    existing = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == snapshot_id))
    if existing is not None:
        _validate_snapshot_row(
            existing,
            asset=_ASSET,
            trade_date=trade_date,
            run_id=run_id,
            snapshot_id=snapshot_id,
            persisted_path=persisted_path,
            payload=snapshot,
        )

    staged = upsert_analysis_snapshot(
        db,
        {
            "snapshot_id": snapshot_id,
            "asset": _ASSET,
            "trade_date": trade_date,
            "run_id": run_id,
            "snapshot_time": snapshot.get("snapshot_time"),
            "status": "success",
            "input_snapshot_ids": input_snapshot_ids,
            "source_refs": source_refs,
            "macro": snapshot.get("macro"),
            "options": snapshot.get("options"),
            "positioning": snapshot.get("positioning"),
            "news": snapshot.get("news"),
            "technical": snapshot.get("technical"),
            "payload": snapshot,
        },
        persisted_path,
    )
    _validate_snapshot_row(
        staged,
        asset=_ASSET,
        trade_date=trade_date,
        run_id=run_id,
        snapshot_id=snapshot_id,
        persisted_path=persisted_path,
        payload=snapshot,
    )

    run.trade_date = trade_date
    run.snapshot_id = snapshot_id
    file_sha256 = hashlib.sha256(raw).hexdigest()
    artifact = register_artifact(
        db,
        run_id=run_id,
        artifact_type=_ARTIFACT_TYPE,
        file_path=persisted_path,
        sha256=file_sha256,
        content_type="application/json",
        byte_size=len(raw),
        source_refs=source_refs,
        input_snapshot_ids={**input_snapshot_ids, "analysis_snapshot": snapshot_id},
        metadata={
            "authority_kind": "premarket_snapshot",
            "asset": _ASSET,
            "trade_date": trade_date,
            "snapshot_id": snapshot_id,
        },
        require_canonical_path=False,
    )
    if artifact is None:
        raise RuntimeError("premarket authority requires the run_artifacts table")
    _validate_artifact_row(
        artifact,
        run_uuid=run_uuid,
        persisted_path=persisted_path,
        file_sha256=file_sha256,
        byte_size=len(raw),
        snapshot_id=snapshot_id,
        trade_date=trade_date,
        source_refs=source_refs,
        input_snapshot_ids=input_snapshot_ids,
    )
    db.flush()
    return staged


def resolve_authoritative_premarket_snapshot(
    db: Session,
    *,
    storage_root: Path,
    trade_date: str,
    asset: str = _ASSET,
) -> PremarketSnapshotAuthority:
    """Resolve one exact DB-backed premarket snapshot authority."""
    if asset != _ASSET:
        return _result("invalid", "unsupported_asset")
    try:
        parsed_date = date.fromisoformat(trade_date)
    except (TypeError, ValueError):
        return _result("invalid", "invalid_trade_date")
    if parsed_date.isoformat() != trade_date:
        return _result("invalid", "invalid_trade_date")

    try:
        runs = list(
            db.scalars(
                select(TaskRun).where(
                    TaskRun.name == _TASK_NAME,
                    TaskRun.task_type == _TASK_NAME,
                    TaskRun.status == TaskStatus.success,
                    TaskRun.trade_date == trade_date,
                )
            ).all()
        )
    except Exception:
        return _result("unavailable", "authority_database_unavailable")
    if not runs:
        return _result("missing", "successful_premarket_run_missing")
    if len(runs) != 1:
        return _result("ambiguous", "multiple_successful_premarket_runs")
    return _resolve_exact_run_authority(
        db,
        run=runs[0],
        storage_root=storage_root,
        trade_date=trade_date,
        parsed_date=parsed_date,
        asset=asset,
        found_reason="authoritative_premarket_snapshot_found",
    )


def resolve_gold_daily_report_premarket_snapshot(
    db: Session,
    *,
    storage_root: Path,
    trade_date: str,
    asset: str = _ASSET,
) -> PremarketSnapshotAuthority:
    """Resolve universal success authority or one explicitly limited Gold daily-report authority."""
    universal = resolve_authoritative_premarket_snapshot(
        db,
        storage_root=storage_root,
        trade_date=trade_date,
        asset=asset,
    )
    if universal.status != "missing":
        return universal
    if asset != _ASSET:
        return _result("invalid", "unsupported_asset")
    try:
        parsed_date = date.fromisoformat(trade_date)
    except (TypeError, ValueError):
        return _result("invalid", "invalid_trade_date")
    if parsed_date.isoformat() != trade_date:
        return _result("invalid", "invalid_trade_date")

    try:
        blocked_runs = list(
            db.scalars(
                select(TaskRun).where(
                    TaskRun.name == _TASK_NAME,
                    TaskRun.task_type == _TASK_NAME,
                    TaskRun.status == TaskStatus.blocked,
                    TaskRun.trade_date == trade_date,
                )
            ).all()
        )
        eligible: list[TaskRun] = []
        for run in blocked_runs:
            receipt_state = _gold_daily_report_receipt_state(db, run=run, trade_date=trade_date)
            if receipt_state == "invalid":
                return _result(
                    "invalid",
                    "gold_daily_report_authority_receipt_invalid",
                    run_id=str(run.id),
                    snapshot_id=run.snapshot_id,
                )
            if receipt_state == "eligible":
                eligible.append(run)
    except Exception:
        return _result("unavailable", "authority_database_unavailable")

    if not eligible:
        return universal
    if len(eligible) != 1:
        return _result("ambiguous", "multiple_gold_daily_report_premarket_runs")
    return _resolve_exact_run_authority(
        db,
        run=eligible[0],
        storage_root=storage_root,
        trade_date=trade_date,
        parsed_date=parsed_date,
        asset=asset,
        found_reason="authoritative_gold_daily_report_premarket_snapshot_found",
    )


def _gold_daily_report_receipt_state(db: Session, *, run: TaskRun, trade_date: str) -> str:
    steps = list(
        db.scalars(
            select(TaskStep).where(
                TaskStep.task_run_id == run.id,
                TaskStep.name == _STRATEGY_CARD_STEP,
            )
        ).all()
    )
    if len(steps) != 1:
        return "invalid" if len(steps) > 1 else "ineligible"
    step = steps[0]
    if not step.output_json:
        return "ineligible"
    try:
        output = json.loads(step.output_json)
    except (TypeError, json.JSONDecodeError):
        return "ineligible"
    if not isinstance(output, dict):
        return "ineligible"
    receipt = output.get("gold_daily_report_authority")
    if receipt is None:
        return "ineligible"
    if not isinstance(receipt, dict):
        return "invalid"

    expected_snapshot_id = f"{_ASSET}:{trade_date}:{run.id}"
    expected_source_ref = f"monitoring/{trade_date}/downstream_readiness.json"
    reason_code = receipt.get("reason_code")
    readiness = receipt.get("readiness")
    valid = (
        step.status == StepStatus.blocked
        and output.get("output_mode") == "blocked"
        and output.get("publish_allowed") is False
        and output.get("reason_code") == reason_code
        and receipt.get("schema_version") == _GOLD_DAILY_REPORT_AUTHORITY_SCHEMA
        and receipt.get("authority_scope") == _GOLD_DAILY_REPORT_AUTHORITY_SCOPE
        and receipt.get("run_id") == str(run.id)
        and receipt.get("snapshot_id") == expected_snapshot_id
        and receipt.get("trade_date") == trade_date
        and receipt.get("readiness_decision") == "block"
        and reason_code in _GOLD_DAILY_REPORT_BLOCK_REASONS
        and readiness in {"blocked", "partial", "ready"}
        and receipt.get("can_run_daily_report") is True
        and receipt.get("can_run_full_analysis") is False
        and receipt.get("publish_allowed") is False
        and receipt.get("source_ref") == expected_source_ref
        and _is_iso_datetime(receipt.get("observed_at"))
        and run.snapshot_id == expected_snapshot_id
        and run.error_summary == reason_code
        and step.blocked_reason == reason_code
    )
    return "eligible" if valid else "invalid"


def _is_iso_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _resolve_exact_run_authority(
    db: Session,
    *,
    run: TaskRun,
    storage_root: Path,
    trade_date: str,
    parsed_date: date,
    asset: str,
    found_reason: str,
) -> PremarketSnapshotAuthority:
    run_id = str(run.id)
    expected_path = _expected_snapshot_path(
        storage_root=storage_root,
        trade_date=trade_date,
        run_id=run_id,
    )
    persisted_path = str(expected_path)
    try:
        snapshots = list(
            db.scalars(
                select(AnalysisSnapshot).where(
                    AnalysisSnapshot.asset == asset,
                    AnalysisSnapshot.trade_date == parsed_date,
                    AnalysisSnapshot.run_id == run_id,
                    AnalysisSnapshot.status == "success",
                )
            ).all()
        )
        artifacts = list(
            db.scalars(
                select(RunArtifact).where(
                    RunArtifact.run_id == run.id,
                    RunArtifact.artifact_type == _ARTIFACT_TYPE,
                    RunArtifact.file_path == persisted_path,
                )
            ).all()
        )
    except Exception:
        return _result("unavailable", "authority_database_unavailable", run_id=run_id)
    if len(snapshots) != 1:
        return _result("invalid", "analysis_snapshot_not_unique", run_id=run_id)
    if len(artifacts) != 1:
        return _result("invalid", "run_artifact_not_unique", run_id=run_id)
    snapshot_row = snapshots[0]
    artifact = artifacts[0]
    snapshot_id = snapshot_row.snapshot_id

    try:
        expected_snapshot_id = f"{asset}:{trade_date}:{run_id}"
        if run.snapshot_id != expected_snapshot_id or snapshot_id != expected_snapshot_id:
            raise ValueError("snapshot identity mismatch")
        if run.trade_date != trade_date:
            raise ValueError("run trade_date mismatch")
        _validate_snapshot_row(
            snapshot_row,
            asset=asset,
            trade_date=trade_date,
            run_id=run_id,
            snapshot_id=expected_snapshot_id,
            persisted_path=persisted_path,
            payload=snapshot_row.payload,
        )
        _validate_file_path(expected_path, storage_root=storage_root)
        raw = expected_path.read_bytes()
        if not artifact.sha256 or hashlib.sha256(raw).hexdigest() != artifact.sha256:
            raise ValueError("artifact file hash mismatch")
        if artifact.byte_size is not None and artifact.byte_size != len(raw):
            raise ValueError("artifact byte size mismatch")
        file_payload = _decode_json_object(raw)
        if file_payload != snapshot_row.payload:
            raise ValueError("snapshot payload mismatch")
        if (
            file_payload.get("asset") != asset
            or file_payload.get("trade_date") != trade_date
            or file_payload.get("run_id") != run_id
            or file_payload.get("snapshot_id") != expected_snapshot_id
        ):
            raise ValueError("snapshot file identity mismatch")
        _validate_artifact_row(
            artifact,
            run_uuid=run.id,
            persisted_path=persisted_path,
            file_sha256=hashlib.sha256(raw).hexdigest(),
            byte_size=len(raw),
            snapshot_id=expected_snapshot_id,
            trade_date=trade_date,
            source_refs=snapshot_row.source_refs,
            input_snapshot_ids=snapshot_row.input_snapshot_ids,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _result(
            "invalid",
            "authority_integrity_invalid",
            run_id=run_id,
            snapshot_id=snapshot_id,
        )
    return _result(
        "found",
        found_reason,
        snapshot_path=expected_path,
        run_id=run_id,
        snapshot_id=snapshot_id,
    )


def _is_canonical_premarket_run(run: TaskRun) -> bool:
    return run.name == _TASK_NAME and run.task_type == _TASK_NAME


def _parse_uuid(run_id: str) -> uuid.UUID:
    try:
        parsed = uuid.UUID(run_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid premarket run_id: {run_id}") from exc
    if str(parsed) != run_id.lower():
        raise ValueError(f"invalid canonical premarket run_id: {run_id}")
    return parsed


def _snapshot_trade_date(snapshot: dict[str, Any]) -> str:
    if snapshot.get("asset") != _ASSET:
        raise ValueError("premarket snapshot asset must be XAUUSD")
    raw = snapshot.get("trade_date")
    if not isinstance(raw, str):
        raise ValueError("premarket snapshot trade_date must be an ISO date")
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("premarket snapshot trade_date must be an ISO date") from exc
    if parsed.isoformat() != raw:
        raise ValueError("premarket snapshot trade_date must be canonical ISO date")
    return raw


def _snapshot_identity(snapshot: dict[str, Any], *, run_id: str, trade_date: str) -> str:
    if snapshot.get("run_id") != run_id:
        raise ValueError("premarket snapshot run_id mismatch")
    snapshot_id = snapshot.get("snapshot_id")
    expected = f"{_ASSET}:{trade_date}:{run_id}"
    if snapshot_id != expected:
        raise ValueError(f"premarket snapshot_id mismatch: expected {expected}")
    return expected


def _expected_snapshot_path(*, storage_root: Path, trade_date: str, run_id: str) -> Path:
    relative = Path("features") / "snapshots" / _ASSET / trade_date / run_id / _ARTIFACT_NAME
    return Path(storage_root) / relative


def _validate_file_path(path: Path, *, storage_root: Path) -> None:
    root = Path(storage_root).absolute()
    candidate = path.absolute()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("premarket snapshot path escapes storage_root") from exc
    current = root
    if current.is_symlink():
        raise ValueError("premarket snapshot storage_root must not be a symlink")
    for part in candidate.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("premarket snapshot path must not contain symlinks")
    if not candidate.is_file():
        raise ValueError("premarket snapshot file is missing")
    resolved_root = root.resolve(strict=True)
    resolved_path = candidate.resolve(strict=True)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("premarket snapshot resolved path escapes storage_root") from exc


def _decode_json_object(raw: bytes) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("premarket snapshot file must contain a JSON object")
    return payload


def _canonical_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_snapshot_row(
    row: AnalysisSnapshot,
    *,
    asset: str,
    trade_date: str,
    run_id: str,
    snapshot_id: str,
    persisted_path: str,
    payload: dict[str, Any],
) -> None:
    if (
        row.asset != asset
        or row.trade_date.isoformat() != trade_date
        or row.run_id != run_id
        or row.snapshot_id != snapshot_id
        or row.status != "success"
        or row.artifact_path != persisted_path
        or row.payload != payload
        or row.payload_sha256 != _canonical_payload_sha256(payload)
        or row.input_snapshot_ids != payload.get("input_snapshot_ids", {})
        or row.source_refs != payload.get("source_refs", [])
        or row.macro != payload.get("macro")
        or row.options != payload.get("options")
        or row.positioning != payload.get("positioning")
        or row.news != payload.get("news")
        or row.technical != payload.get("technical")
    ):
        raise ValueError("premarket AnalysisSnapshot authority conflict")


def _validate_artifact_row(
    row: RunArtifact,
    *,
    run_uuid: uuid.UUID,
    persisted_path: str,
    file_sha256: str,
    byte_size: int,
    snapshot_id: str,
    trade_date: str,
    source_refs: list[dict[str, Any]],
    input_snapshot_ids: dict[str, Any],
) -> None:
    metadata = row.artifact_metadata if isinstance(row.artifact_metadata, dict) else {}
    input_ids = metadata.get("input_snapshot_ids")
    expected_input_ids = {**input_snapshot_ids, "analysis_snapshot": snapshot_id}
    if (
        row.run_id != run_uuid
        or row.task_id is not None
        or row.artifact_type != _ARTIFACT_TYPE
        or row.file_path != persisted_path
        or row.sha256 != file_sha256
        or row.byte_size != byte_size
        or row.content_type != "application/json"
        or not isinstance(input_ids, dict)
        or input_ids != expected_input_ids
        or row.source_refs_data != source_refs
        or metadata.get("authority_kind") != "premarket_snapshot"
        or metadata.get("asset") != _ASSET
        or metadata.get("trade_date") != trade_date
        or metadata.get("snapshot_id") != snapshot_id
    ):
        raise ValueError("premarket RunArtifact authority conflict")


def _result(
    status: AuthorityStatus,
    reason_code: str,
    *,
    snapshot_path: Path | None = None,
    run_id: str | None = None,
    snapshot_id: str | None = None,
) -> PremarketSnapshotAuthority:
    return PremarketSnapshotAuthority(
        status=status,
        reason_code=reason_code,
        snapshot_path=snapshot_path,
        run_id=run_id,
        snapshot_id=snapshot_id,
    )
