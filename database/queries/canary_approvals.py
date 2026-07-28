"""Persistent, fail-closed authority for scoped AnalysisState canaries."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.models.analysis_state import CanaryApproval


CANARY_APPROVAL_SCHEMA_VERSION = "canary_approval.v1"
CANARY_APPROVER_ROLES = frozenset({"analysis_admin", "canary_approver"})


class CanaryApprovalError(ValueError):
    """An approval is absent, invalid, unavailable, or bound elsewhere."""


class CanaryApprovalConsumptionError(RuntimeError):
    """An active approval could not be consumed exactly once."""


def compute_canary_approval_hash(
    *,
    approval_id: str,
    asset: str,
    state_scope: str,
    trade_date: date | None,
    run_id: str | None,
    approved_by: str,
    approved_role: str,
    approved_at: datetime,
    expires_at: datetime,
) -> str:
    """Hash only immutable grant content, excluding mutable lifecycle fields."""

    payload = {
        "schema_version": CANARY_APPROVAL_SCHEMA_VERSION,
        "approval_id": _required_text(approval_id, field="approval_id"),
        "asset": _required_text(asset, field="asset"),
        "state_scope": _required_text(state_scope, field="state_scope"),
        "trade_date": trade_date.isoformat() if trade_date is not None else None,
        "run_id": _optional_text(run_id),
        "approved_by": _required_text(approved_by, field="approved_by"),
        "approved_role": _required_text(approved_role, field="approved_role"),
        "approved_at": _aware_utc(approved_at, field="approved_at").isoformat(),
        "expires_at": _aware_utc(expires_at, field="expires_at").isoformat(),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def issue_canary_approval(
    session: Session,
    *,
    asset: str,
    state_scope: str,
    approved_by: str,
    approved_role: str,
    approved_at: datetime,
    expires_at: datetime,
    trade_date: date | None = None,
    run_id: str | None = None,
    approval_id: str | None = None,
) -> CanaryApproval:
    """Create a server-side approval record; callers own the surrounding commit."""

    identity = _required_text(approval_id or str(uuid.uuid4()), field="approval_id")
    normalized_asset = _required_text(asset, field="asset")
    normalized_scope = _required_text(state_scope, field="state_scope")
    normalized_run_id = _optional_text(run_id)
    normalized_approved_by = _required_text(approved_by, field="approved_by")
    normalized_role = _required_text(approved_role, field="approved_role")
    issued_at = _aware_utc(approved_at, field="approved_at")
    expiry = _aware_utc(expires_at, field="expires_at")
    if trade_date is None and normalized_run_id is None:
        raise CanaryApprovalError("approval must bind trade_date or run_id")
    if expiry <= issued_at:
        raise CanaryApprovalError("approval expires_at must be later than approved_at")
    if normalized_role not in CANARY_APPROVER_ROLES:
        raise CanaryApprovalError("approved_role is not authorized for canary approval")
    approval_hash = compute_canary_approval_hash(
        approval_id=identity,
        asset=normalized_asset,
        state_scope=normalized_scope,
        trade_date=trade_date,
        run_id=normalized_run_id,
        approved_by=normalized_approved_by,
        approved_role=normalized_role,
        approved_at=issued_at,
        expires_at=expiry,
    )
    approval = CanaryApproval(
        approval_id=identity,
        asset=normalized_asset,
        state_scope=normalized_scope,
        trade_date=trade_date,
        run_id=normalized_run_id,
        approved_by=normalized_approved_by,
        approved_role=normalized_role,
        approved_at=issued_at,
        expires_at=expiry,
        approval_hash=approval_hash,
        status="active",
    )
    session.add(approval)
    session.flush()
    return approval


def load_canary_approval(
    session: Session,
    *,
    approval_id: str,
    asset: str,
    state_scope: str,
    trade_date: date,
    run_id: str,
    now: datetime,
    allow_consumed_by_same_run: bool = False,
) -> CanaryApproval:
    """Load and revalidate one exact approval before any canary model execution."""

    identity = _required_text(approval_id, field="approval_id")
    approval = session.get(CanaryApproval, identity)
    if approval is None:
        raise CanaryApprovalError("canary approval does not exist")
    _validate_approval_hash(approval)
    if approval.asset != _required_text(asset, field="asset"):
        raise CanaryApprovalError("canary approval asset does not match run")
    if approval.state_scope != _required_text(state_scope, field="state_scope"):
        raise CanaryApprovalError("canary approval state_scope does not match run")
    normalized_run_id = _required_text(run_id, field="run_id")
    if approval.trade_date is not None and approval.trade_date != trade_date:
        raise CanaryApprovalError("canary approval trade_date does not match run")
    if approval.run_id is not None and approval.run_id != normalized_run_id:
        raise CanaryApprovalError("canary approval run_id does not match run")
    if approval.approved_role not in CANARY_APPROVER_ROLES:
        raise CanaryApprovalError("canary approval role is not authorized")
    checked_at = _aware_utc(now, field="now")
    approved_at = _db_utc(approval.approved_at)
    expires_at = _db_utc(approval.expires_at)
    if checked_at < approved_at:
        raise CanaryApprovalError("canary approval is not yet active")
    if checked_at >= expires_at:
        raise CanaryApprovalError("canary approval has expired")
    if approval.status == "consumed" and allow_consumed_by_same_run:
        if approval.consumed_by_run_id == normalized_run_id:
            return approval
        raise CanaryApprovalError("canary approval was consumed by another run")
    if approval.status != "active":
        raise CanaryApprovalError(f"canary approval status is {approval.status}")
    if approval.consumed_at is not None or approval.consumed_by_run_id is not None:
        raise CanaryApprovalError("active canary approval has inconsistent consumption metadata")
    return approval


def consume_canary_approval(
    session: Session,
    *,
    approval_id: str,
    expected_approval_hash: str,
    run_id: str,
    consumed_at: datetime,
) -> CanaryApproval:
    """Atomically consume one active, unexpired approval inside the caller transaction."""

    identity = _required_text(approval_id, field="approval_id")
    expected_hash = _required_text(expected_approval_hash, field="expected_approval_hash")
    normalized_run_id = _required_text(run_id, field="run_id")
    consumed = _aware_utc(consumed_at, field="consumed_at")
    approval = session.scalar(
        select(CanaryApproval)
        .where(CanaryApproval.approval_id == identity)
        .with_for_update()
    )
    if approval is None:
        raise CanaryApprovalConsumptionError("canary approval does not exist at consumption")
    _validate_approval_hash(approval)
    if approval.approval_hash != expected_hash:
        raise CanaryApprovalConsumptionError("canary approval grant changed before consumption")
    result = session.execute(
        update(CanaryApproval)
        .where(
            CanaryApproval.approval_id == identity,
            CanaryApproval.approval_hash == expected_hash,
            CanaryApproval.status == "active",
            CanaryApproval.approved_at <= consumed,
            CanaryApproval.expires_at > consumed,
            CanaryApproval.consumed_at.is_(None),
            CanaryApproval.consumed_by_run_id.is_(None),
        )
        .values(
            status="consumed",
            consumed_at=consumed,
            consumed_by_run_id=normalized_run_id,
            updated_at=consumed,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise CanaryApprovalConsumptionError("canary approval active-to-consumed update failed")
    session.flush()
    session.expire_all()
    approval = session.get(CanaryApproval, identity)
    if approval is None:  # pragma: no cover - protected by the conditional update
        raise CanaryApprovalConsumptionError("consumed canary approval disappeared")
    _validate_approval_hash(approval)
    return approval


def revoke_canary_approval(
    session: Session,
    *,
    approval_id: str,
    revoked_at: datetime,
) -> CanaryApproval:
    """Revoke only an active approval; intended for trusted service-layer use."""

    identity = _required_text(approval_id, field="approval_id")
    timestamp = _aware_utc(revoked_at, field="revoked_at")
    result = session.execute(
        update(CanaryApproval)
        .where(CanaryApproval.approval_id == identity, CanaryApproval.status == "active")
        .values(status="revoked", updated_at=timestamp)
    )
    if result.rowcount != 1:
        raise CanaryApprovalError("canary approval revoke requires active status")
    session.flush()
    session.expire_all()
    approval = session.get(CanaryApproval, identity)
    if approval is None:  # pragma: no cover - protected by update
        raise CanaryApprovalError("revoked canary approval disappeared")
    return approval


def _validate_approval_hash(approval: CanaryApproval) -> None:
    expected = compute_canary_approval_hash(
        approval_id=approval.approval_id,
        asset=approval.asset,
        state_scope=approval.state_scope,
        trade_date=approval.trade_date,
        run_id=approval.run_id,
        approved_by=approval.approved_by,
        approved_role=approval.approved_role,
        approved_at=_db_utc(approval.approved_at),
        expires_at=_db_utc(approval.expires_at),
    )
    if approval.approval_hash != expected:
        raise CanaryApprovalError("canary approval hash is invalid")


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CanaryApprovalError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _db_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_text(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CanaryApprovalError(f"{field} is required")
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
