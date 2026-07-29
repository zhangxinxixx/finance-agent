"""Pure, point-in-time official-event snapshots for the Gold policy seam.

This module intentionally consumes only structured event candidates and market
reaction records.  It does not inspect news prose or infer a causal story.
"""

from __future__ import annotations

import math
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FreshnessStatus = Literal["fresh", "stale", "missing"]
QualityStatus = Literal["accepted", "observe", "blocked"]
AlignmentStatus = Literal["aligned", "misaligned", "unknown"]
Readiness = Literal["ready", "observe", "blocked"]
ReactionStatus = Literal["confirmed", "observe", "unconfirmed"]

_CONFIRMED_WINDOW = timedelta(minutes=30)


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OfficialEventSourceReference(_Frozen):
    """A typed archival reference shared by event and market evidence."""

    source: str = Field(min_length=1)
    source_type: str | None = None
    reference: str = Field(min_length=1)
    raw_path: str | None = None
    retrieved_at: datetime

    @model_validator(mode="after")
    def _require_aware_retrieval(self) -> "OfficialEventSourceReference":
        if not _is_aware(self.retrieved_at):
            raise ValueError("source reference retrieved_at must be timezone-aware")
        return self


class OfficialEventCandleReference(OfficialEventSourceReference):
    """One exact market candle bound to its reaction-window role."""

    role: Literal["baseline", "after"]
    asset: Literal["XAUUSD"]
    timeframe: Literal["1m"]
    open_time: datetime
    retrieval_basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def _require_aware_open_time(self) -> "OfficialEventCandleReference":
        if not _is_aware(self.open_time):
            raise ValueError("candle open_time must be timezone-aware")
        return self


class OfficialEvent(_Frozen):
    event_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    occurred_at: datetime
    reaction_baseline_time: datetime | None = None
    reaction_after_time: datetime | None = None
    reaction_window_end: datetime | None = None
    reaction_summary: str | None = None
    reaction_asset: Literal["XAUUSD"] | None = None
    reaction_return_pct: float | None = None
    reaction_status: ReactionStatus
    source_refs: tuple[OfficialEventSourceReference, ...] = Field(min_length=1)
    reaction_source_refs: tuple[OfficialEventCandleReference, ...] = ()

    @model_validator(mode="after")
    def _require_complete_confirmed_reaction(self) -> "OfficialEvent":
        if not _is_aware(self.occurred_at):
            raise ValueError("event occurred_at must be timezone-aware")
        if self.reaction_window_end is not None and not _is_aware(self.reaction_window_end):
            raise ValueError("reaction_window_end must be timezone-aware")
        if self.reaction_status == "confirmed":
            if (
                self.reaction_window_end is None
                or self.reaction_baseline_time is None
                or self.reaction_after_time is None
                or self.reaction_asset != "XAUUSD"
                or self.reaction_return_pct is None
                or not math.isfinite(self.reaction_return_pct)
                or not self.reaction_summary
                or not self.reaction_source_refs
            ):
                raise ValueError("confirmed events require a complete XAUUSD reaction and candle references")
            expected_end = self.occurred_at + _CONFIRMED_WINDOW
            if (
                self.reaction_window_end != expected_end
                or not (
                    self.reaction_baseline_time
                    <= self.occurred_at
                    < self.reaction_after_time
                    <= expected_end
                )
            ):
                raise ValueError("confirmed events require an exact bounded 30-minute window")
            refs_by_role = {ref.role: ref for ref in self.reaction_source_refs}
            if len(self.reaction_source_refs) != 2 or set(refs_by_role) != {"baseline", "after"} or (
                refs_by_role["baseline"].open_time != self.reaction_baseline_time
                or refs_by_role["after"].open_time != self.reaction_after_time
            ):
                raise ValueError("confirmed candle references must match their baseline/after times")
        return self


class OfficialEventSnapshot(_Frozen):
    """The formal, immutable official-event input contract."""

    schema_version: Literal["official_event_snapshot.v1"] = "official_event_snapshot.v1"
    as_of: datetime
    readiness: Readiness
    freshness_status: FreshnessStatus
    quality_status: QualityStatus
    alignment_status: AlignmentStatus
    events: tuple[OfficialEvent, ...]
    source_refs: tuple[OfficialEventSourceReference, ...] = Field(min_length=1)
    rejected_source_refs: tuple[OfficialEventSourceReference, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_snapshot(self) -> "OfficialEventSnapshot":
        if not _is_aware(self.as_of):
            raise ValueError("snapshot as_of must be timezone-aware")
        expected = _readiness(self.quality_status, self.alignment_status)
        if self.readiness != expected:
            raise ValueError(f"snapshot readiness must be {expected}")
        return self


def build_official_event_snapshot(
    *,
    candidates: Iterable[Mapping[str, Any]],
    reactions: Iterable[Mapping[str, Any]],
    as_of: datetime,
) -> OfficialEventSnapshot:
    """Select official, released events and confirm only exact 30-minute reactions.

    A normal no-event day is deliberately represented by an empty ``observe``
    snapshot with a query reference.  Point-in-time violations and malformed or
    pseudo-official records instead fail closed.
    """

    point_in_time = _aware_utc(as_of)
    rows = tuple(dict(row) for row in candidates if isinstance(row, Mapping))
    reaction_index = _reaction_index(reactions)
    events: list[OfficialEvent] = []
    invalid_input = False
    rejected_refs: list[OfficialEventSourceReference] = []
    reason_codes: set[str] = set()

    for row in rows:
        candidate = _candidate(row, as_of=point_in_time)
        if candidate is None:
            # A non-qualifying candidate is ordinary noise unless it claims to
            # be official/released or violates the point-in-time boundary.
            reason = _blocking_candidate_reason(row, as_of=point_in_time)
            invalid_input = invalid_input or reason is not None
            if reason is not None:
                reason_codes.add(reason)
                rejected_refs.extend(_references(row.get("source_refs"), as_of=point_in_time))
            continue
        event_id, title, occurred_at, refs = candidate
        reaction = reaction_index.get(event_id)
        result = _reaction_for_event(reaction, occurred_at=occurred_at, as_of=point_in_time)
        if result.blocking:
            invalid_input = True
            reason_codes.update(result.reason_codes)
            rejected_refs.extend(result.rejected_source_refs)
        events.append(
            OfficialEvent(
                event_id=event_id,
                title=title,
                occurred_at=occurred_at,
                reaction_baseline_time=result.baseline_time,
                reaction_after_time=result.after_time,
                reaction_window_end=result.window_end,
                reaction_summary=result.summary,
                reaction_asset="XAUUSD" if result.confirmed else None,
                reaction_return_pct=result.return_pct if result.confirmed else None,
                reaction_status=result.status,
                source_refs=refs,
                reaction_source_refs=result.source_refs,
            )
        )

    events = sorted(events, key=lambda item: (item.occurred_at, item.event_id))
    evidence_refs = [
        ref
        for event in events
        for ref in (*event.source_refs, *event.reaction_source_refs)
    ]
    evidence_refs.extend(
        ref for ref in rejected_refs if ref.retrieved_at <= point_in_time
    )
    if invalid_input:
        events = [_demote_event(event) for event in events]
    all_refs = _dedupe_refs(
        [_base_source_ref(ref) for ref in evidence_refs]
        or [_query_ref(point_in_time)]
    )
    if invalid_input:
        quality: QualityStatus = "blocked"
        alignment: AlignmentStatus = "misaligned"
    elif not events or any(event.reaction_status != "confirmed" for event in events):
        quality = "observe"
        alignment = "aligned"
    else:
        quality = "accepted"
        alignment = "aligned"
    return OfficialEventSnapshot(
        as_of=point_in_time,
        readiness=_readiness(quality, alignment),
        freshness_status="fresh",
        quality_status=quality,
        alignment_status=alignment,
        events=tuple(events),
        source_refs=all_refs,
        rejected_source_refs=_dedupe_refs(
            [_base_source_ref(ref) for ref in rejected_refs]
        ),
        reason_codes=tuple(sorted(reason_codes)),
    )


def archive_official_event_snapshot(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    snapshot: OfficialEventSnapshot,
) -> str:
    """Persist the immutable formal contract beside the news feature artifacts."""

    target = (
        storage_root
        / "features"
        / "news"
        / retrieved_date
        / run_id
        / "official_event_snapshot.v1.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            snapshot.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return target.relative_to(storage_root).as_posix()


def _candidate(
    row: Mapping[str, Any], *, as_of: datetime
) -> tuple[str, str, datetime, tuple[OfficialEventSourceReference, ...]] | None:
    if row.get("verification_status") != "official_confirmed" or row.get("event_status") == "scheduled":
        return None
    event_id = _text(row.get("event_id"))
    occurred_at = _parse_time(row.get("event_time"))
    refs = _references(row.get("source_refs"), as_of=as_of)
    if not event_id or occurred_at is None or occurred_at > as_of or not refs:
        return None
    if not any(ref.source_type == "official" and ref.raw_path for ref in refs):
        return None
    title = _text(row.get("title")) or _text(row.get("event_type")) or event_id
    return event_id, title, occurred_at, refs


def _blocking_candidate_reason(row: Mapping[str, Any], *, as_of: datetime) -> str | None:
    verification = row.get("verification_status")
    event_status = row.get("event_status")
    event_time = _parse_time(row.get("event_time"))
    refs = row.get("source_refs")
    # Ordinary wire/supplemental candidates are excluded but do not make a
    # normal no-event day missing.  A valid future scheduled release is also a
    # normal observation and is simply ineligible for the occurred-event
    # snapshot.  False official claims and malformed point-in-time assertions
    # fail closed.
    if verification == "official_confirmed":
        refs = _references(row.get("source_refs"), as_of=as_of)
        has_official_raw = any(ref.source_type == "official" and ref.raw_path for ref in refs)
        if event_status == "scheduled" and event_time is not None and event_time > as_of and has_official_raw:
            return None
        if event_time is None:
            return "OFFICIAL_EVENT_TIME_INVALID"
        if event_time > as_of:
            return "OFFICIAL_EVENT_AFTER_AS_OF"
        if not has_official_raw:
            return "OFFICIAL_EVENT_SOURCE_UNVERIFIABLE"
        if not _candidate(row, as_of=as_of):
            return "OFFICIAL_EVENT_CANDIDATE_INVALID"
        return None
    if verification == "multi_source":
        return "MULTI_SOURCE_EVENT_LINEAGE_MISSING" if not isinstance(refs, (list, tuple)) or not refs else None
    return None


def _demote_event(event: OfficialEvent) -> OfficialEvent:
    payload = event.model_dump(mode="python")
    payload.update(
        reaction_baseline_time=None,
        reaction_after_time=None,
        reaction_window_end=None,
        reaction_summary=None,
        reaction_asset=None,
        reaction_return_pct=None,
        reaction_status="observe",
        reaction_source_refs=(),
    )
    return OfficialEvent.model_validate(payload)


class _ReactionResult:
    def __init__(
        self,
        *,
        status: ReactionStatus,
        confirmed: bool = False,
        blocking: bool = False,
        window_end: datetime | None = None,
        baseline_time: datetime | None = None,
        after_time: datetime | None = None,
        return_pct: float | None = None,
        summary: str | None = None,
        source_refs: tuple[OfficialEventSourceReference, ...] = (),
        rejected_source_refs: tuple[OfficialEventSourceReference, ...] = (),
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        self.status = status
        self.confirmed = confirmed
        self.blocking = blocking
        self.window_end = window_end
        self.baseline_time = baseline_time
        self.after_time = after_time
        self.return_pct = return_pct
        self.summary = summary
        self.source_refs = source_refs
        self.rejected_source_refs = rejected_source_refs
        self.reason_codes = reason_codes


def _reaction_index(reactions: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for reaction in reactions:
        if not isinstance(reaction, Mapping):
            continue
        event_id = _text(reaction.get("event_id"))
        if event_id and event_id not in indexed:
            indexed[event_id] = reaction
    return indexed


def _reaction_for_event(reaction: Mapping[str, Any] | None, *, occurred_at: datetime, as_of: datetime) -> _ReactionResult:
    if reaction is None:
        return _ReactionResult(status="unconfirmed")
    status = str(reaction.get("status") or "")
    window = _xauusd_30m_window(reaction)
    if status != "available" or window is None:
        return _ReactionResult(status="observe")
    baseline = _parse_time(window.get("baseline_time"))
    after = _parse_time(window.get("after_time"))
    pct_change = _finite_number(window.get("pct_change"))
    window_end = occurred_at + _CONFIRMED_WINDOW
    window_pit_violation = any(
        value is not None and value > as_of
        for value in (baseline, after)
    ) or window_end > as_of
    exact_window = (
        baseline is not None
        and after is not None
        and baseline <= occurred_at < after <= window_end <= as_of
    )
    baseline_raw_refs = window.get("baseline_candle_refs")
    after_raw_refs = window.get("after_candle_refs")
    future_ref_violation = _has_future_reference(
        baseline_raw_refs,
        as_of=as_of,
    ) or _has_future_reference(after_raw_refs, as_of=as_of)
    pit_violation = window_pit_violation or future_ref_violation
    baseline_refs = _candle_references(
        baseline_raw_refs,
        as_of=as_of,
        expected_role="baseline",
        expected_open_time=baseline,
    )
    after_refs = _candle_references(
        after_raw_refs,
        as_of=as_of,
        expected_role="after",
        expected_open_time=after,
    )
    candles_complete = bool(baseline_refs and after_refs)
    confirmed = bool(exact_window and pct_change is not None and window.get("threshold_hit") is True and candles_complete)
    return _ReactionResult(
        status="confirmed" if confirmed else "observe",
        confirmed=confirmed,
        blocking=pit_violation,
        window_end=window_end if confirmed else None,
        baseline_time=baseline if confirmed else None,
        after_time=after if confirmed else None,
        return_pct=pct_change if confirmed else None,
        summary=f"XAUUSD 30m reaction {pct_change:+.4f}%" if confirmed else None,
        source_refs=_dedupe_refs([*baseline_refs, *after_refs]),
        rejected_source_refs=_dedupe_refs(
            [
                *_future_references(baseline_raw_refs, as_of=as_of),
                *_future_references(after_raw_refs, as_of=as_of),
            ]
        ),
        reason_codes=tuple(
            code
            for code, active in (
                ("REACTION_WINDOW_AFTER_AS_OF", window_pit_violation),
                ("REACTION_CANDLE_RETRIEVED_AFTER_AS_OF", future_ref_violation),
            )
            if active
        ),
    )


def _xauusd_30m_window(reaction: Mapping[str, Any]) -> Mapping[str, Any] | None:
    windows = reaction.get("windows")
    if not isinstance(windows, Mapping):
        return None
    window = windows.get("30m")
    return window.get("XAUUSD") if isinstance(window, Mapping) and isinstance(window.get("XAUUSD"), Mapping) else None


def _references(value: Any, *, as_of: datetime) -> tuple[OfficialEventSourceReference, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    refs: list[OfficialEventSourceReference] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        source = _text(item.get("source"))
        source_type = _text(item.get("source_type"))
        raw_path = _text(item.get("raw_path"))
        reference = _text(item.get("reference")) or _text(item.get("source_url")) or _text(item.get("source_ref"))
        retrieved_at = _parse_time(item.get("retrieved_at"))
        if not all((source, reference)) or retrieved_at is None or retrieved_at > as_of:
            continue
        refs.append(OfficialEventSourceReference(source=source, source_type=source_type, reference=reference, raw_path=raw_path, retrieved_at=retrieved_at))
    return _dedupe_refs(refs)


def _candle_references(
    value: Any,
    *,
    as_of: datetime,
    expected_role: Literal["baseline", "after"],
    expected_open_time: datetime | None,
) -> tuple[OfficialEventCandleReference, ...]:
    if not isinstance(value, (list, tuple)) or expected_open_time is None:
        return ()
    refs: list[OfficialEventCandleReference] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        retrieved_at = _parse_time(item.get("retrieved_at"))
        open_time = _parse_time(item.get("open_time"))
        source = _text(item.get("source"))
        reference = _text(item.get("reference")) or _text(item.get("source_url"))
        retrieval_basis = _text(item.get("retrieval_basis"))
        if (
            item.get("role") != expected_role
            or item.get("asset") != "XAUUSD"
            or item.get("timeframe") != "1m"
            or open_time != expected_open_time
            or retrieved_at is None
            or retrieved_at > as_of
            or not source
            or not reference
            or not retrieval_basis
        ):
            continue
        refs.append(
            OfficialEventCandleReference(
                source=source,
                source_type=_text(item.get("source_type")),
                reference=reference,
                raw_path=_text(item.get("raw_path")),
                retrieved_at=retrieved_at,
                role=expected_role,
                asset="XAUUSD",
                timeframe="1m",
                open_time=open_time,
                retrieval_basis=retrieval_basis,
            )
        )
    return tuple(refs)


def _has_future_reference(value: Any, *, as_of: datetime) -> bool:
    if not isinstance(value, (list, tuple)):
        return False
    return any(
        isinstance(item, Mapping)
        and (retrieved_at := _parse_time(item.get("retrieved_at"))) is not None
        and retrieved_at > as_of
        for item in value
    )


def _future_references(
    value: Any,
    *,
    as_of: datetime,
) -> tuple[OfficialEventSourceReference, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    refs: list[OfficialEventSourceReference] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        retrieved_at = _parse_time(item.get("retrieved_at"))
        source = _text(item.get("source"))
        reference = _text(item.get("reference")) or _text(item.get("source_url"))
        if retrieved_at is None or retrieved_at <= as_of or not source or not reference:
            continue
        refs.append(
            OfficialEventSourceReference(
                source=source,
                source_type=_text(item.get("source_type")),
                reference=reference,
                raw_path=_text(item.get("raw_path")),
                retrieved_at=retrieved_at,
            )
        )
    return _dedupe_refs(refs)


def _query_ref(as_of: datetime) -> OfficialEventSourceReference:
    return OfficialEventSourceReference(
        source="official_event_snapshot_query",
        source_type="query",
        reference="query://official-event-candidate-eligibility",
        raw_path="query://official-event-candidate-eligibility",
        retrieved_at=as_of,
    )


def _base_source_ref(ref: OfficialEventSourceReference) -> OfficialEventSourceReference:
    return OfficialEventSourceReference(
        source=ref.source,
        source_type=ref.source_type,
        reference=ref.reference,
        raw_path=ref.raw_path,
        retrieved_at=ref.retrieved_at,
    )


def _dedupe_refs(refs: Iterable[OfficialEventSourceReference]) -> tuple[OfficialEventSourceReference, ...]:
    unique = {
        (
            ref.source,
            ref.source_type or "",
            ref.reference,
            ref.raw_path or "",
            ref.retrieved_at.astimezone(UTC),
            getattr(ref, "role", ""),
            getattr(ref, "asset", ""),
            getattr(ref, "timeframe", ""),
            getattr(ref, "open_time", "").isoformat()
            if isinstance(getattr(ref, "open_time", None), datetime)
            else "",
        ): ref
        for ref in refs
    }
    return tuple(unique[key] for key in sorted(unique))


def _readiness(quality: QualityStatus, alignment: AlignmentStatus) -> Readiness:
    return "blocked" if quality == "blocked" or alignment == "misaligned" else "observe" if quality == "observe" or alignment == "unknown" else "ready"


def _aware_utc(value: datetime) -> datetime:
    if not _is_aware(value):
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC)


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.astimezone(UTC) if _is_aware(parsed) else None


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
