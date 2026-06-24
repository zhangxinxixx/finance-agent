"""Persisted daily source-health snapshot queries."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from database.models.analysis import DailySourceHealthItem, DailySourceHealthSnapshot


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _item_payload(item: DailySourceHealthItem) -> dict[str, Any]:
    payload = dict(item.payload or {})
    payload.setdefault("source_key", item.source_key)
    payload.setdefault("source_name", item.source_name)
    payload.setdefault("data_status", item.data_status)
    if item.source_group is not None:
        payload.setdefault("source_group", item.source_group)
    if item.freshness_status is not None:
        payload.setdefault("freshness_status", item.freshness_status)
    if item.raw_status is not None:
        payload.setdefault("raw_status", item.raw_status)
    if item.parsed_status is not None:
        payload.setdefault("parsed_status", item.parsed_status)
    if item.feature_status is not None:
        payload.setdefault("feature_status", item.feature_status)
    if item.analysis_status is not None:
        payload.setdefault("analysis_status", item.analysis_status)
    if item.latest_health_at is not None:
        payload.setdefault("latest_health_at", item.latest_health_at.isoformat())
    return payload


def _snapshot_payload(snapshot: DailySourceHealthSnapshot) -> dict[str, Any]:
    payload = dict(snapshot.payload or {})
    payload.update(
        {
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "as_of": snapshot.as_of.isoformat(),
            "overall_status": snapshot.overall_status,
            "counts": snapshot.counts,
            "stale_sources": snapshot.stale_sources,
            "items": [_item_payload(item) for item in sorted(snapshot.items, key=lambda row: row.source_key)],
        }
    )
    return payload


def get_data_source_health_snapshot(session: Session, snapshot_date: str | date) -> dict[str, Any] | None:
    """Return one persisted source-health snapshot by date."""
    day = _parse_date(snapshot_date)
    snapshot = session.scalar(
        select(DailySourceHealthSnapshot)
        .options(selectinload(DailySourceHealthSnapshot.items))
        .where(DailySourceHealthSnapshot.snapshot_date == day)
    )
    if snapshot is None:
        return None
    return _snapshot_payload(snapshot)


def list_data_source_health_history(session: Session, source_key: str, *, limit: int = 30) -> dict[str, Any]:
    """Return persisted daily health rows for one source, newest snapshot first."""
    safe_limit = max(1, min(int(limit or 30), 365))
    rows = session.scalars(
        select(DailySourceHealthItem)
        .join(DailySourceHealthItem.snapshot)
        .options(selectinload(DailySourceHealthItem.snapshot))
        .where(DailySourceHealthItem.source_key == source_key)
        .order_by(desc(DailySourceHealthSnapshot.snapshot_date))
        .limit(safe_limit)
    ).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        payload = _item_payload(row)
        payload.update(
            {
                "snapshot_date": row.snapshot.snapshot_date.isoformat(),
                "as_of": row.snapshot.as_of.isoformat(),
                "overall_status": row.snapshot.overall_status,
            }
        )
        items.append(payload)
    return {
        "source_key": source_key,
        "total": len(items),
        "items": items,
    }


def upsert_data_source_health_snapshot(session: Session, payload: dict[str, Any]) -> DailySourceHealthSnapshot:
    """Persist one daily source-health snapshot and replace its item rows."""
    snapshot_date = _parse_date(payload["snapshot_date"])
    as_of = _parse_datetime(payload["as_of"])
    snapshot = session.scalar(
        select(DailySourceHealthSnapshot)
        .options(selectinload(DailySourceHealthSnapshot.items))
        .where(DailySourceHealthSnapshot.snapshot_date == snapshot_date)
    )
    if snapshot is None:
        snapshot = DailySourceHealthSnapshot(snapshot_date=snapshot_date, as_of=as_of)
        session.add(snapshot)
        session.flush()

    snapshot.as_of = as_of
    snapshot.overall_status = str(payload.get("overall_status") or "UNAVAILABLE")
    snapshot.counts = dict(payload.get("counts") or {})
    snapshot.stale_sources = list(payload.get("stale_sources") or [])
    snapshot.payload = {
        key: value
        for key, value in payload.items()
        if key not in {"items", "snapshot_date", "as_of", "overall_status", "counts", "stale_sources"}
    }
    snapshot.items.clear()
    session.flush()

    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        source_key = str(item.get("source_key") or "").strip()
        if not source_key:
            continue
        snapshot.items.append(
            DailySourceHealthItem(
                source_key=source_key,
                source_name=str(item.get("source_name") or source_key),
                source_group=item.get("source_group"),
                data_status=str(item.get("data_status") or "unavailable"),
                freshness_status=item.get("freshness_status"),
                raw_status=item.get("raw_status"),
                parsed_status=item.get("parsed_status"),
                feature_status=item.get("feature_status"),
                analysis_status=item.get("analysis_status"),
                latest_health_at=_parse_datetime(item["latest_health_at"]) if item.get("latest_health_at") else None,
                payload=dict(item),
            )
        )
    session.flush()
    return snapshot
