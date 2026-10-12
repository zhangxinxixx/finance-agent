"""Pure D1 market producers for existing canonical XAUUSD levels."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from apps.analysis.gold_policy.key_level_controls import KeyLevelControlsInput
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelAuthorityStatus,
    KeyLevelComparator,
    KeyLevelEvent,
    KeyLevelEventType,
    KeyLevelEvidenceFactor,
    KeyLevelLifecycle,
    KeyLevelPublicationStatus,
    KeyLevelQualificationClass,
    KeyLevelQualificationReceiptInput,
    KeyLevelReadModel,
    KeyLevelRole,
    KeyLevelSourceInstrument,
    KeyLevelSourceRole,
    _build_key_level_qualification_receipt,
    build_key_level_event,
)
from apps.analysis.gold_policy.schemas import SourceReference
from apps.features.market_data.source_role_policy import qualify_market_source


_DAY = timedelta(days=1)
_LIVE_LIFECYCLES = frozenset(
    {
        KeyLevelLifecycle.ACTIVE,
        KeyLevelLifecycle.TESTED,
        KeyLevelLifecycle.HOLDING,
        KeyLevelLifecycle.RECLAIMED,
    }
)
_BREAK_ROLES = frozenset({KeyLevelRole.SUPPORT, KeyLevelRole.RESISTANCE})


class GoldKeyLevelMarketEventProduction(BaseModel):
    """Immutable result, including explicit missingness when no event qualifies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["gold_key_level_market_event_production.v1"] = (
        "gold_key_level_market_event_production.v1"
    )
    controls_input: KeyLevelControlsInput
    reason_codes: tuple[str, ...]


class _D1Bar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    asset: Literal["XAUUSD"]
    timeframe: Literal["1d"]
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    source: str
    raw_path: str
    source_ref: Mapping[str, Any]
    retrieved_at: datetime
    snapshot_id: str
    source_reference: str
    raw_reference: str
    qualification_reference: str


def produce_gold_key_level_market_events(
    *,
    previous_states: Iterable[KeyLevelReadModel],
    candidates: Iterable[Mapping[str, Any]],
    decision_as_of: datetime,
) -> GoldKeyLevelMarketEventProduction:
    """Produce only D1 ``BREAK_CONFIRMED`` events for existing live levels.

    The function performs no I/O and never discovers, confirms, or activates a
    level. Invalid or incomplete market input fails closed while preserving the
    supplied valid state set in the controls input.
    """

    cutoff = _aware_utc(decision_as_of)
    states = tuple(sorted(tuple(previous_states), key=lambda item: item.spec.level_id))
    controls_without_events = KeyLevelControlsInput(
        decision_as_of=cutoff,
        scope="daily_close",
        previous_states=states,
    )
    if not states:
        return _production(controls_without_events, "NO_PREVIOUS_KEY_LEVEL_STATES")
    window, reasons = _validated_window(candidates, cutoff=cutoff)
    if window is None:
        return _production(controls_without_events, *reasons)
    previous_bar, current_bar = window

    events: list[KeyLevelEvent] = []
    state_reasons: list[str] = []
    for state in states:
        reason = _state_rejection_reason(state, cutoff=cutoff, window_end=current_bar.close_time)
        if reason is not None:
            state_reasons.append(reason)
            continue
        if not _window_breaks_level(state, window):
            state_reasons.append("KEY_LEVEL_BREAK_NOT_CONFIRMED")
            continue
        events.append(_build_break_event(state, window=window, cutoff=cutoff))

    event_roles = {event.spec.role for event in events}
    if len(event_roles) > 1:
        return _production(controls_without_events, "KEY_LEVEL_BREAK_DIRECTION_AMBIGUOUS")
    if not events:
        reasons = tuple(sorted(set(state_reasons))) or ("NO_ELIGIBLE_KEY_LEVEL_BREAK",)
        return GoldKeyLevelMarketEventProduction(
            controls_input=controls_without_events,
            reason_codes=reasons,
        )

    ordered_events = tuple(sorted(events, key=lambda item: (item.evidence.as_of, item.event_id)))
    return GoldKeyLevelMarketEventProduction(
        controls_input=KeyLevelControlsInput(
            decision_as_of=cutoff,
            scope="daily_close",
            previous_states=states,
            ordered_events=ordered_events,
        ),
        reason_codes=("KEY_LEVEL_BREAK_EVENTS_PRODUCED",),
    )


def produce_gold_key_level_lifecycle_events(
    *,
    previous_states: Iterable[KeyLevelReadModel],
    candidates: Iterable[Mapping[str, Any]],
    decision_as_of: datetime,
) -> GoldKeyLevelMarketEventProduction:
    """Produce one eligible D1 lifecycle event per existing XAUUSD level.

    Candidate and confirmed levels may advance by exactly one step. Existing
    live levels retain the legacy break behavior; no level discovery or
    authority initialization occurs here. Invalid market input rejects the
    complete production run so callers cannot combine qualified and degraded
    rows.
    """

    cutoff = _aware_utc(decision_as_of)
    states = tuple(sorted(tuple(previous_states), key=lambda item: item.spec.level_id))
    if not states or all(state.lifecycle in _LIVE_LIFECYCLES for state in states):
        return produce_gold_key_level_market_events(
            previous_states=states,
            candidates=candidates,
            decision_as_of=cutoff,
        )

    controls_without_events = KeyLevelControlsInput(
        decision_as_of=cutoff,
        scope="daily_close",
        previous_states=states,
    )
    window, reasons = _validated_window(candidates, cutoff=cutoff)
    if window is None:
        return _production(controls_without_events, *reasons)

    events: list[KeyLevelEvent] = []
    break_events: list[KeyLevelEvent] = []
    state_reasons: list[str] = []
    for state in states:
        if state.lifecycle in _LIVE_LIFECYCLES:
            rejection = _state_rejection_reason(
                state,
                cutoff=cutoff,
                window_end=window[1].close_time,
            )
            if rejection is not None:
                state_reasons.append(rejection)
            elif _window_breaks_level(state, window):
                event = _build_break_event(state, window=window, cutoff=cutoff)
                events.append(event)
                break_events.append(event)
            else:
                state_reasons.append("KEY_LEVEL_BREAK_NOT_CONFIRMED")
            continue

        rejection = _lifecycle_state_rejection_reason(
            state,
            cutoff=cutoff,
            window=window,
        )
        if rejection is not None:
            state_reasons.append(rejection)
            continue
        if state.lifecycle is KeyLevelLifecycle.CANDIDATE:
            if not _window_has_repeated_reaction(state, window):
                state_reasons.append("KEY_LEVEL_REPEATED_REACTION_NOT_CONFIRMED")
                continue
            events.append(
                _build_lifecycle_event(
                    state,
                    window=window,
                    cutoff=cutoff,
                    event_type=KeyLevelEventType.CONFIRM,
                    factors=(
                        KeyLevelEvidenceFactor.PRICE_STRUCTURE,
                        KeyLevelEvidenceFactor.REPEATED_REACTION,
                    ),
                )
            )
            continue
        if state.lifecycle is KeyLevelLifecycle.CONFIRMED:
            if not _window_is_activation_side(state, window):
                state_reasons.append("KEY_LEVEL_ACTIVATION_SIDE_NOT_CONFIRMED")
                continue
            events.append(
                _build_lifecycle_event(
                    state,
                    window=window,
                    cutoff=cutoff,
                    event_type=KeyLevelEventType.ACTIVATE,
                    factors=(
                        KeyLevelEvidenceFactor.OFFICIAL_CLOSE,
                        KeyLevelEvidenceFactor.PRICE_STRUCTURE,
                    ),
                )
            )

    if len({event.spec.role for event in break_events}) > 1:
        return _production(controls_without_events, "KEY_LEVEL_BREAK_DIRECTION_AMBIGUOUS")
    if not events:
        reasons = tuple(sorted(set(state_reasons))) or ("NO_ELIGIBLE_KEY_LEVEL_LIFECYCLE_EVENT",)
        return GoldKeyLevelMarketEventProduction(
            controls_input=controls_without_events,
            reason_codes=reasons,
        )

    ordered_events = tuple(sorted(events, key=lambda item: (item.evidence.as_of, item.event_id)))
    return GoldKeyLevelMarketEventProduction(
        controls_input=KeyLevelControlsInput(
            decision_as_of=cutoff,
            scope="daily_close",
            previous_states=states,
            ordered_events=ordered_events,
        ),
        reason_codes=("KEY_LEVEL_LIFECYCLE_EVENTS_PRODUCED",),
    )


def _validated_window(
    candidates: Iterable[Mapping[str, Any]],
    *,
    cutoff: datetime,
) -> tuple[tuple[_D1Bar, _D1Bar] | None, tuple[str, ...]]:
    raw_rows = tuple(candidates)
    if not raw_rows:
        return None, ("D1_MARKET_CANDIDATES_MISSING",)

    bars: list[_D1Bar] = []
    rejection_codes: list[str] = []
    for candidate in raw_rows:
        bar, reason = _validated_bar(candidate, cutoff=cutoff)
        if bar is None:
            rejection_codes.append(reason)
        else:
            bars.append(bar)
    if rejection_codes:
        return None, tuple(rejection_codes)

    window, reason = _select_window(tuple(bars), cutoff=cutoff)
    if window is None:
        return None, (reason,)
    return window, ()


def _validated_bar(
    candidate: Mapping[str, Any],
    *,
    cutoff: datetime,
) -> tuple[_D1Bar | None, str]:
    if not isinstance(candidate, Mapping):
        return None, "D1_MARKET_ROW_NOT_STRUCTURED"
    row = dict(candidate)
    asset = str(row.get("asset") or "").strip().upper()
    if asset != "XAUUSD":
        return None, "D1_MARKET_ASSET_NOT_CANONICAL_XAUUSD"
    if str(row.get("timeframe") or "").strip().lower() != "1d":
        return None, "D1_MARKET_TIMEFRAME_INVALID"
    source = str(row.get("source") or "").strip()
    if not source:
        return None, "D1_MARKET_SOURCE_MISSING"
    source_ref_value = row.get("source_ref")
    if not isinstance(source_ref_value, Mapping):
        return None, "D1_MARKET_SOURCE_REF_MISSING"
    try:
        source_ref = _json_mapping(source_ref_value)
    except (TypeError, ValueError):
        return None, "D1_MARKET_SOURCE_REF_INVALID"
    qualification = qualify_market_source(asset=asset, source=source, source_ref=source_ref)
    if qualification.quality_status != "accepted" or qualification.normalized_role != "market_primary":
        return None, "D1_MARKET_SOURCE_UNQUALIFIED"
    for declaration in (row, source_ref):
        if (
            "quality_status" in declaration
            and str(declaration["quality_status"]).strip().lower() != "accepted"
        ):
            return None, "D1_MARKET_QUALITY_NOT_ACCEPTED"
        if (
            "freshness_status" in declaration
            and str(declaration["freshness_status"]).strip().lower() != "fresh"
        ):
            return None, "D1_MARKET_FRESHNESS_NOT_FRESH"
        if (
            "alignment_status" in declaration
            and str(declaration["alignment_status"]).strip().lower() != "aligned"
        ):
            return None, "D1_MARKET_ALIGNMENT_NOT_ALIGNED"

    open_time = _parse_time(row.get("open_time"))
    close_time = _parse_time(row.get("close_time"))
    retrieved_at = _parse_time(source_ref.get("retrieved_at") or row.get("retrieved_at"))
    if open_time is None or close_time is None:
        return None, "D1_MARKET_WINDOW_TIME_INVALID"
    if retrieved_at is None:
        return None, "D1_MARKET_RETRIEVAL_TIME_MISSING"
    if close_time - open_time != _DAY:
        return None, "D1_MARKET_BAR_DURATION_INVALID"
    if close_time > cutoff:
        return None, "D1_MARKET_BAR_UNCLOSED_AT_CUTOFF"
    if retrieved_at < close_time:
        return None, "D1_MARKET_RETRIEVED_BEFORE_CLOSE"
    if retrieved_at > cutoff:
        return None, "D1_MARKET_FUTURE_SOURCE_REF"
    nested_retrievals = _source_ref_retrieval_times(source_ref)
    if nested_retrievals is None:
        return None, "D1_MARKET_SOURCE_REF_INVALID"
    if any(item > cutoff for item in nested_retrievals):
        return None, "D1_MARKET_FUTURE_SOURCE_REF"

    values: dict[str, Decimal] = {}
    for field_name in ("open", "high", "low", "close"):
        value = _positive_decimal(row.get(field_name))
        if value is None:
            return None, "D1_MARKET_OHLC_INVALID"
        values[field_name] = value
    if (
        values["low"] > values["high"]
        or values["high"] < max(values["open"], values["close"])
        or values["low"] > min(values["open"], values["close"])
    ):
        return None, "D1_MARKET_OHLC_INVALID"

    raw_path = str(row.get("raw_path") or source_ref.get("raw_path") or "").strip()
    if not raw_path:
        return None, "D1_MARKET_RAW_LINEAGE_MISSING"
    source_reference = str(
        source_ref.get("reference") or source_ref.get("source_url") or raw_path
    ).strip()
    if not source_reference:
        return None, "D1_MARKET_SOURCE_REFERENCE_MISSING"
    row_payload = {
        "asset": asset,
        "timeframe": "1d",
        "open_time": open_time.isoformat(),
        "close_time": close_time.isoformat(),
        **{name: str(value) for name, value in values.items()},
        "source": source,
        "raw_path": raw_path,
        "source_ref": source_ref,
    }
    snapshot_hash = _hash_payload(row_payload)
    qualification_hash = _hash_payload(
        {
            "asset": asset,
            "source": source,
            "source_ref": source_ref,
            "quality_status": qualification.quality_status,
            "reason_code": qualification.reason_code,
            "normalized_role": qualification.normalized_role,
        }
    )
    declared_raw_hash = source_ref.get("sha256") or source_ref.get("content_hash")
    raw_hash = str(declared_raw_hash).strip().lower() if declared_raw_hash is not None else None
    if raw_hash is not None and (
        len(raw_hash) != 64 or any(character not in "0123456789abcdef" for character in raw_hash)
    ):
        return None, "D1_MARKET_RAW_HASH_INVALID"
    return (
        _D1Bar(
            asset="XAUUSD",
            timeframe="1d",
            open_time=open_time,
            close_time=close_time,
            open=values["open"],
            high=values["high"],
            low=values["low"],
            close=values["close"],
            source=source,
            raw_path=raw_path,
            source_ref=source_ref,
            retrieved_at=retrieved_at,
            snapshot_id=f"market_candle.v1:{snapshot_hash}",
            source_reference=source_reference,
            raw_reference=f"{raw_path}#sha256={raw_hash}" if raw_hash is not None else raw_path,
            qualification_reference=f"market_source_qualification.v1:{qualification_hash}",
        ),
        "D1_MARKET_ROW_ACCEPTED",
    )


def _select_window(
    bars: tuple[_D1Bar, ...],
    *,
    cutoff: datetime,
) -> tuple[tuple[_D1Bar, _D1Bar] | None, str]:
    if len(bars) < 2:
        return None, "D1_MARKET_WINDOW_INCOMPLETE"
    ordered = tuple(sorted(bars, key=lambda item: (item.open_time, item.close_time, item.snapshot_id)))
    time_keys = [(bar.open_time, bar.close_time) for bar in ordered]
    if len(set(time_keys)) != len(time_keys):
        return None, "D1_MARKET_WINDOW_DUPLICATE_OR_CONFLICTING"
    providers = {
        (
            bar.source.lower(),
            str(bar.source_ref.get("provider_symbol") or "").upper(),
            str(bar.source_ref.get("instrument_type") or "").lower(),
            str(bar.source_ref.get("source_role") or bar.source_ref.get("provider_role") or "").lower(),
        )
        for bar in ordered
    }
    if len(providers) != 1:
        return None, "D1_MARKET_PROVIDER_AMBIGUOUS"
    previous_bar, current_bar = ordered[-2:]
    if previous_bar.close_time != current_bar.open_time:
        return None, "D1_MARKET_WINDOW_GAPPED"
    age = cutoff - current_bar.close_time
    if age < timedelta(0):
        return None, "D1_MARKET_BAR_UNCLOSED_AT_CUTOFF"
    if age >= _DAY:
        return None, "D1_MARKET_WINDOW_EXPIRED"
    return (previous_bar, current_bar), "D1_MARKET_WINDOW_READY"


def _state_rejection_reason(
    state: KeyLevelReadModel,
    *,
    cutoff: datetime,
    window_end: datetime,
) -> str | None:
    spec = state.spec
    activation = state.activation_event
    if spec.scope.value != "daily_close" or spec.role not in _BREAK_ROLES:
        return "KEY_LEVEL_STATE_NOT_SUPPORT_OR_RESISTANCE"
    if (
        state.lifecycle not in _LIVE_LIFECYCLES
        or state.authority_status is not KeyLevelAuthorityStatus.CANONICAL_XAUUSD_VALIDATED
        or state.quality_status != "accepted"
        or activation is None
        or activation.event_type is not KeyLevelEventType.ACTIVATE
        or activation.spec != spec
        or activation.evidence.source_role is not KeyLevelSourceRole.OFFICIAL_MARKET
        or activation.evidence.source_instrument is not KeyLevelSourceInstrument.XAUUSD_SPOT
        or activation.evidence.quality_status != "accepted"
        or activation.evidence.freshness_status != "fresh"
        or activation.evidence.alignment_status != "aligned"
    ):
        return "KEY_LEVEL_STATE_NOT_CANONICAL_LIVE"
    if not spec.effective_from <= cutoff < spec.expires_at:
        return "KEY_LEVEL_STATE_EXPIRED_OR_NOT_EFFECTIVE"
    if state.as_of >= cutoff or activation.evidence.as_of > cutoff:
        return "KEY_LEVEL_STATE_AFTER_DECISION_CUTOFF"
    if window_end <= state.as_of:
        return "D1_MARKET_WINDOW_NOT_NEWER_THAN_STATE"
    return None


def _lifecycle_state_rejection_reason(
    state: KeyLevelReadModel,
    *,
    cutoff: datetime,
    window: tuple[_D1Bar, _D1Bar],
) -> str | None:
    spec = state.spec
    expected_comparator = {
        KeyLevelRole.SUPPORT: KeyLevelComparator.ABOVE_OR_EQUAL,
        KeyLevelRole.RESISTANCE: KeyLevelComparator.BELOW_OR_EQUAL,
    }
    if spec.scope.value != "daily_close" or spec.role not in _BREAK_ROLES:
        return "KEY_LEVEL_STATE_NOT_SUPPORT_OR_RESISTANCE"
    if spec.comparator is not expected_comparator[spec.role]:
        return "KEY_LEVEL_STATE_ROLE_COMPARATOR_MISMATCH"
    if (
        spec.origin_instrument is not KeyLevelSourceInstrument.XAUUSD_SPOT
        or spec.origin_source_role
        in {KeyLevelSourceRole.CME_OPTIONS_MODEL, KeyLevelSourceRole.CME_LARGE_OI}
        or spec.origin_contract_id is not None
    ):
        return "KEY_LEVEL_STATE_ORIGIN_NOT_XAUUSD"
    expected_authority = {
        KeyLevelLifecycle.CANDIDATE: KeyLevelAuthorityStatus.CANDIDATE_ONLY,
        KeyLevelLifecycle.CONFIRMED: KeyLevelAuthorityStatus.FORMALLY_CONFIRMED,
    }
    if (
        state.lifecycle not in expected_authority
        or state.authority_status is not expected_authority[state.lifecycle]
        or state.quality_status != "accepted"
        or state.activation_event is not None
        or state.strategy_eligible
    ):
        return "KEY_LEVEL_STATE_NOT_ACCEPTED_LIFECYCLE_HEAD"
    if not spec.effective_from <= cutoff < spec.expires_at:
        return "KEY_LEVEL_STATE_EXPIRED_OR_NOT_EFFECTIVE"
    if state.as_of >= cutoff:
        return "KEY_LEVEL_STATE_AFTER_DECISION_CUTOFF"
    if window[0].open_time < state.as_of or window[1].close_time <= state.as_of:
        return "D1_MARKET_WINDOW_NOT_FULLY_NEWER_THAN_STATE"
    return None


def _window_breaks_level(
    state: KeyLevelReadModel,
    window: tuple[_D1Bar, _D1Bar],
) -> bool:
    spec = state.spec
    boundary = (
        spec.reference_price
        if spec.reference_price is not None
        else spec.band_lower
        if spec.role is KeyLevelRole.SUPPORT
        else spec.band_upper
    )
    if boundary is None:
        return False
    closes = tuple(bar.close for bar in window)
    if spec.role is KeyLevelRole.SUPPORT:
        return all(close < boundary for close in closes)
    return all(close > boundary for close in closes)


def _level_boundaries(state: KeyLevelReadModel) -> tuple[Decimal, Decimal] | None:
    spec = state.spec
    lower = spec.reference_price if spec.reference_price is not None else spec.band_lower
    upper = spec.reference_price if spec.reference_price is not None else spec.band_upper
    if lower is None or upper is None:
        return None
    return lower, upper


def _window_has_repeated_reaction(
    state: KeyLevelReadModel,
    window: tuple[_D1Bar, _D1Bar],
) -> bool:
    boundaries = _level_boundaries(state)
    if boundaries is None:
        return False
    lower, upper = boundaries
    anchor = state.spec.reference_price or (lower + upper) / 2
    tolerance = anchor * state.spec.rule_set.reaction_tolerance_bps / 10_000
    reaction_count = sum(
        1
        for bar in window
        if lower - tolerance <= bar.close <= upper + tolerance
    )
    return reaction_count >= state.spec.rule_set.repeated_reaction_min_count


def _window_is_activation_side(
    state: KeyLevelReadModel,
    window: tuple[_D1Bar, _D1Bar],
) -> bool:
    boundaries = _level_boundaries(state)
    if boundaries is None:
        return False
    lower, upper = boundaries
    if state.spec.role is KeyLevelRole.SUPPORT:
        return all(bar.close >= lower for bar in window)
    if state.spec.role is KeyLevelRole.RESISTANCE:
        return all(bar.close <= upper for bar in window)
    return False


def _build_break_event(
    state: KeyLevelReadModel,
    *,
    window: tuple[_D1Bar, _D1Bar],
    cutoff: datetime,
) -> KeyLevelEvent:
    return _build_market_event(
        state,
        window=window,
        cutoff=cutoff,
        event_type=KeyLevelEventType.BREAK_CONFIRMED,
        factors=(
            KeyLevelEvidenceFactor.OFFICIAL_CLOSE,
            KeyLevelEvidenceFactor.BREAK_WINDOW,
        ),
        rule_code="break",
        window_schema_version="canonical_xauusd_d1_break_window.v1",
    )


def _build_lifecycle_event(
    state: KeyLevelReadModel,
    *,
    window: tuple[_D1Bar, _D1Bar],
    cutoff: datetime,
    event_type: Literal[KeyLevelEventType.CONFIRM, KeyLevelEventType.ACTIVATE],
    factors: tuple[KeyLevelEvidenceFactor, KeyLevelEvidenceFactor],
) -> KeyLevelEvent:
    return _build_market_event(
        state,
        window=window,
        cutoff=cutoff,
        event_type=event_type,
        factors=factors,
        rule_code="price_structure",
        window_schema_version="canonical_xauusd_d1_lifecycle_window.v1",
    )


def _build_market_event(
    state: KeyLevelReadModel,
    *,
    window: tuple[_D1Bar, _D1Bar],
    cutoff: datetime,
    event_type: KeyLevelEventType,
    factors: tuple[KeyLevelEvidenceFactor, KeyLevelEvidenceFactor],
    rule_code: Literal["price_structure", "break"],
    window_schema_version: str,
) -> KeyLevelEvent:
    previous_bar, current_bar = window
    window_hash = _hash_payload(
        {
            "schema_version": window_schema_version,
            "snapshot_ids": [previous_bar.snapshot_id, current_bar.snapshot_id],
            "window_start": previous_bar.open_time.isoformat(),
            "window_end": current_bar.close_time.isoformat(),
            "provider": current_bar.source,
        }
    )
    market_refs = _market_refs(window, window_hash=window_hash)
    issued_at = max(bar.retrieved_at for bar in window)
    receipt = _build_key_level_qualification_receipt(
        KeyLevelQualificationReceiptInput(
            source_role=KeyLevelSourceRole.OFFICIAL_MARKET,
            source_instrument=KeyLevelSourceInstrument.XAUUSD_SPOT,
            qualification_class=KeyLevelQualificationClass.CANONICAL_MARKET,
            scope="daily_close",
            subject_level_id=state.spec.level_id,
            publication_status=KeyLevelPublicationStatus.NOT_APPLICABLE,
            calculation_method="price_candle",
            qualified_factors=factors,
            qualified_snapshot_ids=(previous_bar.snapshot_id, current_bar.snapshot_id),
            current_snapshot_id=current_bar.snapshot_id,
            previous_snapshot_id=previous_bar.snapshot_id,
            current_snapshot_as_of=current_bar.close_time,
            previous_snapshot_as_of=previous_bar.close_time,
            issued_at=issued_at,
            source_refs=market_refs,
        )
    )
    evidence_refs = _dedupe_refs(
        (
            *market_refs,
            SourceReference(
                source="qualification_receipt",
                reference=receipt.receipt_id,
                retrieved_at=issued_at,
            ),
        )
    )
    evidence_id = "key_level_evidence.v1:" + _hash_payload(
        {
            "event_type": event_type.value,
            "level_id": state.spec.level_id,
            "decision_as_of": cutoff.isoformat(),
            "window_hash": window_hash,
            "receipt_id": receipt.receipt_id,
            "source_refs": [ref.model_dump(mode="json") for ref in evidence_refs],
        }
    )
    return build_key_level_event(
        {
            "event_type": event_type,
            "spec": state.spec,
            "evidence": {
                "evidence_id": evidence_id,
                "qualification_receipt": receipt,
                "factors": factors,
                "timeframe": "1d",
                "window_start": previous_bar.open_time,
                "window_end": current_bar.close_time,
                "price_fact": {
                    "snapshot_id": current_bar.snapshot_id,
                    "open": previous_bar.open,
                    "high": max(previous_bar.high, current_bar.high),
                    "low": min(previous_bar.low, current_bar.low),
                    "close": current_bar.close,
                    "window_closes": (previous_bar.close, current_bar.close),
                    "window_start": previous_bar.open_time,
                    "window_end": current_bar.close_time,
                    "window_complete": True,
                    "rule_code": rule_code,
                },
                "quality_status": "accepted",
                "freshness_status": "fresh",
                "alignment_status": "aligned",
                "as_of": cutoff,
                "source_refs": evidence_refs,
            },
        }
    )


def _market_refs(
    window: tuple[_D1Bar, _D1Bar],
    *,
    window_hash: str,
) -> tuple[SourceReference, ...]:
    refs: list[SourceReference] = []
    for bar in window:
        refs.extend(
            (
                SourceReference(
                    source="input_snapshot",
                    reference=bar.snapshot_id,
                    retrieved_at=bar.retrieved_at,
                ),
                SourceReference(
                    source=bar.source,
                    reference=bar.source_reference,
                    retrieved_at=bar.retrieved_at,
                ),
                SourceReference(
                    source="raw_market_artifact",
                    reference=bar.raw_reference,
                    retrieved_at=bar.retrieved_at,
                ),
                SourceReference(
                    source="market_source_qualification",
                    reference=bar.qualification_reference,
                    retrieved_at=bar.retrieved_at,
                ),
            )
        )
    refs.append(
        SourceReference(
            source="canonical_xauusd_d1_window",
            reference=f"canonical_xauusd_d1_window.v1:{window_hash}",
            retrieved_at=max(bar.retrieved_at for bar in window),
        )
    )
    return _dedupe_refs(tuple(refs))


def _dedupe_refs(refs: tuple[SourceReference, ...]) -> tuple[SourceReference, ...]:
    unique = {
        (ref.source, ref.reference, ref.retrieved_at.astimezone(UTC)): ref
        for ref in refs
    }
    return tuple(unique[key] for key in sorted(unique))


def _production(
    controls_input: KeyLevelControlsInput,
    *reason_codes: str,
) -> GoldKeyLevelMarketEventProduction:
    return GoldKeyLevelMarketEventProduction(
        controls_input=controls_input,
        reason_codes=tuple(sorted(set(reason_codes))),
    )


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision_as_of must be timezone-aware")
    return value.astimezone(UTC)


def _positive_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def _json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(item) for key, item in value.items()}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("non-finite source reference value")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite source reference value")
        return str(value)
    if isinstance(value, datetime):
        normalized = _parse_time(value)
        if normalized is None:
            raise ValueError("naive source reference time")
        return normalized.isoformat()
    if isinstance(value, Mapping):
        return _json_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError("source reference values must be JSON-compatible")


def _source_ref_retrieval_times(value: Any) -> tuple[datetime, ...] | None:
    times: list[datetime] = []

    def visit(item: Any) -> bool:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if str(key) == "retrieved_at":
                    parsed = _parse_time(nested)
                    if parsed is None:
                        return False
                    times.append(parsed)
                elif not visit(nested):
                    return False
        elif isinstance(item, (list, tuple)):
            for nested in item:
                if not visit(nested):
                    return False
        return True

    return tuple(times) if visit(value) else None


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _json_mapping(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
