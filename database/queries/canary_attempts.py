"""Durable lifecycle operations for scoped canary sidecar attempts."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models.analysis_state import CanaryAttempt


class CanaryAttemptError(RuntimeError):
    """An attempt is missing, mismatched, or in an invalid lifecycle state."""


def create_or_resume_canary_attempt(
    session: Session,
    *,
    run_id: str,
    approval_id: str,
    approval_hash: str,
    attempt_no: int,
    asset: str,
    state_scope: str,
    trade_date: date,
    requested_canonical_state_id: str | None,
    expected_head_version: int | None,
    started_at: datetime,
) -> CanaryAttempt:
    """Create one logical attempt or return the exact existing identity."""

    normalized_run_id = _required(run_id, field="run_id")
    if isinstance(attempt_no, bool) or attempt_no not in {0, 1}:
        raise CanaryAttemptError("attempt_no must be 0 or 1")
    existing = session.scalar(
        select(CanaryAttempt).where(
            CanaryAttempt.run_id == normalized_run_id,
            CanaryAttempt.attempt_no == attempt_no,
        )
    )
    expected = {
        "approval_id": _required(approval_id, field="approval_id"),
        "approval_hash": _sha256(approval_hash, field="approval_hash"),
        "asset": _required(asset, field="asset"),
        "state_scope": _required(state_scope, field="state_scope"),
        "trade_date": trade_date,
        "requested_canonical_state_id": _optional(requested_canonical_state_id),
        "expected_head_version": expected_head_version,
    }
    if existing is not None:
        _validate_identity(existing, expected)
        return existing
    if attempt_no == 1:
        predecessor = session.scalar(
            select(CanaryAttempt).where(
                CanaryAttempt.run_id == normalized_run_id,
                CanaryAttempt.attempt_no == 0,
            )
        )
        if predecessor is None or predecessor.status != "recompute_authorized":
            raise CanaryAttemptError("attempt 1 requires attempt 0 recompute authorization")
        if predecessor.approval_id != expected["approval_id"] or predecessor.approval_hash != expected["approval_hash"]:
            raise CanaryAttemptError("attempt 1 approval does not match attempt 0")
    attempt = CanaryAttempt(
        attempt_id=str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"finance-agent:analysis-state-canary-attempt:{normalized_run_id}:{attempt_no}",
            )
        ),
        run_id=normalized_run_id,
        attempt_no=attempt_no,
        started_at=_aware(started_at, field="started_at"),
        status="started",
        **expected,
    )
    try:
        with session.begin_nested():
            session.add(attempt)
            session.flush()
        return attempt
    except IntegrityError:
        # A deterministic PK plus (run_id, attempt_no) uniqueness serializes
        # concurrent starters. The savepoint keeps the caller transaction usable.
        session.expire_all()
        winner = session.scalar(
            select(CanaryAttempt).where(
                CanaryAttempt.run_id == normalized_run_id,
                CanaryAttempt.attempt_no == attempt_no,
            )
        )
        if winner is None:
            raise CanaryAttemptError("concurrent canary attempt winner is not visible") from None
        _validate_identity(winner, expected)
        return winner


def load_canary_attempt(session: Session, *, run_id: str, attempt_no: int) -> CanaryAttempt | None:
    """Load one logical attempt by its unique run/ordinal identity."""

    return session.scalar(
        select(CanaryAttempt).where(
            CanaryAttempt.run_id == _required(run_id, field="run_id"),
            CanaryAttempt.attempt_no == attempt_no,
        )
    )


def mark_canary_attempt_audit_persisted(
    session: Session,
    *,
    attempt_id: str,
    context_bundle_id: str,
    context_bundle_hash: str,
    authority_hash: str,
    artifact_path: str,
    artifact_sha256: str,
    updated_at: datetime,
) -> CanaryAttempt:
    """Bind a content-addressed audit exactly once; exact retries are idempotent."""

    attempt = _required_attempt(session, attempt_id)
    values = {
        "context_bundle_id": _required(context_bundle_id, field="context_bundle_id"),
        "context_bundle_hash": _sha256(context_bundle_hash, field="context_bundle_hash"),
        "authority_hash": _sha256(authority_hash, field="authority_hash"),
        "audit_artifact_path": _required(artifact_path, field="artifact_path"),
        "audit_artifact_sha256": _sha256(artifact_sha256, field="artifact_sha256"),
    }
    if attempt.status in {"audit_persisted", "recompute_authorized", "terminal"}:
        _validate_fields(attempt, values, message="attempt audit identity changed")
        return attempt
    if attempt.status != "started":
        raise CanaryAttemptError(f"cannot persist audit from status {attempt.status}")
    for field, value in values.items():
        setattr(attempt, field, value)
    attempt.status = "audit_persisted"
    attempt.updated_at = _aware(updated_at, field="updated_at")
    session.flush()
    return attempt


def authorize_canary_recompute(
    session: Session,
    *,
    attempt_id: str,
    updated_at: datetime,
) -> CanaryAttempt:
    """Durably authorize the sole attempt-1 creation after CAS conflict."""

    attempt = _required_attempt(session, attempt_id)
    if attempt.attempt_no != 0:
        raise CanaryAttemptError("only attempt 0 may authorize recompute")
    if attempt.status == "recompute_authorized":
        return attempt
    if attempt.status != "audit_persisted":
        raise CanaryAttemptError(f"cannot authorize recompute from status {attempt.status}")
    attempt.status = "recompute_authorized"
    attempt.updated_at = _aware(updated_at, field="updated_at")
    session.flush()
    return attempt


def mark_canary_attempt_terminal(
    session: Session,
    *,
    attempt_id: str,
    terminal_status: str,
    artifact_path: str,
    artifact_sha256: str,
    updated_at: datetime,
) -> CanaryAttempt:
    """Reconcile a terminal result only after its owning transaction committed."""

    attempt = _required_attempt(session, attempt_id)
    values = {
        "terminal_status": _required(terminal_status, field="terminal_status"),
        "terminal_artifact_path": _required(artifact_path, field="artifact_path"),
        "terminal_artifact_sha256": _sha256(artifact_sha256, field="artifact_sha256"),
    }
    if attempt.status == "terminal":
        _validate_fields(attempt, values, message="attempt terminal identity changed")
        return attempt
    if attempt.status not in {"audit_persisted", "recompute_authorized"}:
        raise CanaryAttemptError(f"cannot mark terminal from status {attempt.status}")
    for field, value in values.items():
        setattr(attempt, field, value)
    attempt.status = "terminal"
    attempt.updated_at = _aware(updated_at, field="updated_at")
    session.flush()
    return attempt


def mark_canary_attempt_failed(
    session: Session,
    *,
    attempt_id: str,
    failure_code: str,
    failure_detail: str | None,
    updated_at: datetime,
) -> CanaryAttempt:
    """Persist a stable fail-closed outcome before any further model execution."""

    attempt = _required_attempt(session, attempt_id)
    code = _required(failure_code, field="failure_code")[:128]
    detail = _optional(failure_detail)
    if attempt.status == "failed":
        _validate_fields(
            attempt,
            {"failure_code": code, "failure_detail": detail},
            message="attempt failure identity changed",
        )
        return attempt
    if attempt.status == "terminal":
        raise CanaryAttemptError("terminal attempt cannot become failed")
    attempt.status = "failed"
    attempt.failure_code = code
    attempt.failure_detail = detail[:1000] if detail is not None else None
    attempt.updated_at = _aware(updated_at, field="updated_at")
    session.flush()
    return attempt


def _required_attempt(session: Session, attempt_id: str) -> CanaryAttempt:
    attempt = session.get(CanaryAttempt, _required(attempt_id, field="attempt_id"))
    if attempt is None:
        raise CanaryAttemptError("canary attempt does not exist")
    return attempt


def _validate_identity(attempt: CanaryAttempt, expected: dict[str, object]) -> None:
    _validate_fields(attempt, expected, message="canary attempt resume identity mismatch")


def _validate_fields(attempt: CanaryAttempt, expected: dict[str, object], *, message: str) -> None:
    for field, value in expected.items():
        if getattr(attempt, field) != value:
            raise CanaryAttemptError(f"{message}: {field}")


def _aware(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryAttemptError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _required(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CanaryAttemptError(f"{field} is required")
    return normalized


def _optional(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _sha256(value: object, *, field: str) -> str:
    normalized = _required(value, field=field).lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise CanaryAttemptError(f"{field} must be a SHA256 hex digest")
    return normalized
