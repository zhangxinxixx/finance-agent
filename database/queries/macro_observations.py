"""Macro observation upsert/query helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.analysis import MacroObservation


def _parse_iso_date(value: str | date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    elif " " in text:
        text = text.split(" ", 1)[0]
    return date.fromisoformat(text)


def _parse_iso_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def upsert_macro_observation(session: Session, payload: dict[str, Any]) -> MacroObservation:
    """Upsert one macro observation by source/symbol/date."""
    source_key = str(payload["source_key"])
    symbol = str(payload["symbol"])
    observation_date = _parse_iso_date(payload["observation_date"])

    existing = session.scalar(
        select(MacroObservation).where(
            MacroObservation.source_key == source_key,
            MacroObservation.symbol == symbol,
            MacroObservation.observation_date == observation_date,
        )
    )

    if existing is None:
        existing = MacroObservation(
            source_key=source_key,
            symbol=symbol,
            observation_date=observation_date,
        )
        session.add(existing)

    existing.value = _optional_float(payload.get("value"))
    existing.unit = _optional_str(payload.get("unit"))
    existing.frequency = _optional_str(payload.get("frequency"))
    existing.source_url = _optional_str(payload.get("source_url"))
    existing.raw_path = _optional_str(payload.get("raw_path"))
    existing.raw_artifact_id = _optional_str(payload.get("raw_artifact_id"))
    existing.parsed_artifact_id = _optional_str(payload.get("parsed_artifact_id"))
    existing.retrieved_at = _parse_iso_datetime(payload.get("retrieved_at"))
    existing.run_id = _optional_str(payload.get("run_id"))
    existing.source_refs = list(payload.get("source_refs") or [])
    existing.observation_metadata = dict(payload.get("metadata") or {})
    session.flush()
    return existing


def upsert_macro_observations(session: Session, payloads: Iterable[dict[str, Any]]) -> list[MacroObservation]:
    """Upsert a batch of macro observations and return the persisted rows."""
    rows = [upsert_macro_observation(session, payload) for payload in payloads]
    session.flush()
    return rows


def list_macro_observations(
    session: Session,
    *,
    source_key: str | None = None,
    symbol: str | None = None,
    run_id: str | None = None,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
) -> list[MacroObservation]:
    """List macro observations with lightweight filters."""
    stmt = select(MacroObservation)
    if source_key is not None:
        stmt = stmt.where(MacroObservation.source_key == source_key)
    if symbol is not None:
        stmt = stmt.where(MacroObservation.symbol == symbol)
    if run_id is not None:
        stmt = stmt.where(MacroObservation.run_id == run_id)
    if start_date is not None:
        stmt = stmt.where(MacroObservation.observation_date >= _parse_iso_date(start_date))
    if end_date is not None:
        stmt = stmt.where(MacroObservation.observation_date <= _parse_iso_date(end_date))
    stmt = stmt.order_by(
        MacroObservation.observation_date.desc(),
        MacroObservation.source_key.asc(),
        MacroObservation.symbol.asc(),
    )
    return list(session.scalars(stmt))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
