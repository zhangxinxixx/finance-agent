"""Feature snapshot upsert/query helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.analysis import FeatureSnapshot


def _sha256_hex(data: dict[str, Any]) -> str:
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_iso_date(value: str | date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    return date.fromisoformat(text)


def upsert_feature_snapshot(session: Session, payload: dict[str, Any]) -> FeatureSnapshot:
    """Upsert one feature snapshot by stable snapshot_id."""
    snapshot_id = str(payload["snapshot_id"])
    existing = session.scalar(select(FeatureSnapshot).where(FeatureSnapshot.snapshot_id == snapshot_id))

    if existing is None:
        existing = FeatureSnapshot(snapshot_id=snapshot_id)
        session.add(existing)

    core_payload = dict(payload.get("payload") or {})
    existing.domain = str(payload["domain"])
    existing.snapshot_kind = str(payload["snapshot_kind"])
    existing.asset = str(payload.get("asset") or "XAUUSD")
    existing.trade_date = _parse_iso_date(payload["trade_date"])
    existing.run_id = str(payload["run_id"])
    existing.status = str(payload.get("status") or "generated")
    existing.payload = core_payload
    existing.payload_sha256 = _sha256_hex(core_payload)
    existing.artifact_id = _optional_str(payload.get("artifact_id"))
    existing.artifact_path = _optional_str(payload.get("artifact_path"))
    existing.source_refs = list(payload.get("source_refs") or [])
    existing.input_snapshot_ids = dict(payload.get("input_snapshot_ids") or {})
    existing.feature_metadata = dict(payload.get("metadata") or {})
    session.flush()
    return existing


def upsert_feature_snapshots(session: Session, payloads: Iterable[dict[str, Any]]) -> list[FeatureSnapshot]:
    """Upsert a batch of feature snapshots and return the persisted rows."""
    rows = [upsert_feature_snapshot(session, payload) for payload in payloads]
    session.flush()
    return rows


def list_feature_snapshots(
    session: Session,
    *,
    domain: str | None = None,
    snapshot_kind: str | None = None,
    asset: str | None = None,
    run_id: str | None = None,
    trade_date: str | date | None = None,
) -> list[FeatureSnapshot]:
    """List feature snapshots with lightweight filters."""
    stmt = select(FeatureSnapshot)
    if domain is not None:
        stmt = stmt.where(FeatureSnapshot.domain == domain)
    if snapshot_kind is not None:
        stmt = stmt.where(FeatureSnapshot.snapshot_kind == snapshot_kind)
    if asset is not None:
        stmt = stmt.where(FeatureSnapshot.asset == asset)
    if run_id is not None:
        stmt = stmt.where(FeatureSnapshot.run_id == run_id)
    if trade_date is not None:
        stmt = stmt.where(FeatureSnapshot.trade_date == _parse_iso_date(trade_date))
    stmt = stmt.order_by(
        FeatureSnapshot.trade_date.desc(),
        FeatureSnapshot.updated_at.desc(),
        FeatureSnapshot.id.desc(),
    )
    return list(session.scalars(stmt))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
