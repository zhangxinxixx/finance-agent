"""Deterministic AnalysisSnapshot projection for state+delta shadow input."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from apps.analysis.context_bundle.schemas import EvidenceItem


_MACRO_METRICS: dict[str, tuple[str, str]] = {
    "DXY": ("dxy", "index"),
    "DGS2": ("us02y", "percent"),
    "DGS10": ("us10y", "percent"),
    "DFII10": ("real10y", "percent"),
    "REAL10Y": ("real10y", "percent"),
    "T10YIE": ("breakeven10y", "percent"),
    "DCOILWTICO": ("oil", "usd"),
    "WTI": ("oil", "usd"),
}
_SOURCE_REF_KEYS = frozenset(
    {
        "article_id",
        "date",
        "event_id",
        "figure_fact_id",
        "raw_file_id",
        "raw_file_sha256",
        "raw_path",
        "report_date",
        "run_id",
        "sha256",
        "snapshot_id",
        "source",
        "source_url",
        "status",
        "symbol",
        "trade_date",
    }
)
SNAPSHOT_PASSPORT_METADATA_KEY = "analysis_snapshot_passport"


@dataclass(frozen=True, slots=True)
class _Snapshot:
    payload: dict[str, Any]
    snapshot_id: str
    asset: str
    run_id: str
    business_time: datetime
    ingested_at: datetime
    source_refs: tuple[dict[str, Any], ...]
    snapshot_passport: dict[str, str]


def build_state_shadow_input(
    *,
    previous_snapshot: Mapping[str, Any] | Any,
    current_snapshot: Mapping[str, Any] | Any,
    canonical_state: Mapping[str, Any] | Any,
) -> dict[str, Any]:
    """Project two persisted snapshots into ``prepare_composite_state_shadow`` input.

    The adapter only emits evidence supported by both snapshots (or, for a new
    material event, by an identity absent from the previous snapshot). Missing
    values and untraceable sources are omitted rather than inferred.
    """

    previous = _snapshot(previous_snapshot)
    current = _snapshot(current_snapshot)
    state_id, state_payload = _canonical_state(canonical_state)
    state_asset = _required_text(state_payload.get("asset"), "canonical_state.asset")
    state_scope = str(state_payload.get("state_scope") or "daily_close").strip()
    if previous.asset != current.asset or current.asset != state_asset:
        raise ValueError("snapshot and canonical state assets must match")
    if previous.business_time > current.business_time:
        raise ValueError("previous snapshot must not be newer than current snapshot")
    if previous.snapshot_id == current.snapshot_id:
        raise ValueError("previous and current snapshots must have distinct identities")

    evidence = [
        *_macro_evidence(previous, current),
        *_key_level_evidence(previous, current, state_payload),
        *_options_evidence(previous, current),
        *_material_event_evidence(previous, current),
    ]
    evidence = sorted(evidence, key=lambda item: (item.ingested_at, item.evidence_id, item.source))
    session = str(state_payload.get("session") or state_scope).strip()
    if not session:
        raise ValueError("canonical state session must not be blank")
    return {
        "state_scope": state_scope,
        "canonical_state_id": state_id,
        "canonical_state": state_payload,
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "evidence_cursors": dict(state_payload.get("evidence_cursors") or {}),
        "cutoff_at": current.ingested_at.isoformat(),
        "assembled_at": current.ingested_at.isoformat(),
        "expected_session": session,
    }


def project_snapshot_evidence(
    *,
    previous_snapshot: Mapping[str, Any] | Any,
    current_snapshot: Mapping[str, Any] | Any,
    canonical_state: Mapping[str, Any] | Any,
) -> list[EvidenceItem]:
    """Return only the validated evidence portion of ``build_state_shadow_input``."""

    shadow_input = build_state_shadow_input(
        previous_snapshot=previous_snapshot,
        current_snapshot=current_snapshot,
        canonical_state=canonical_state,
    )
    return [EvidenceItem.model_validate(item) for item in shadow_input["evidence"]]


def _snapshot(value: Mapping[str, Any] | Any) -> _Snapshot:
    if isinstance(value, Mapping):
        record = dict(value)
        nested = record.get("payload")
        payload = dict(nested) if isinstance(nested, Mapping) else dict(record)

        def field(name: str, default: Any = None) -> Any:
            return record.get(name, default)
    else:
        nested = getattr(value, "payload", None)
        if not isinstance(nested, Mapping):
            raise TypeError("AnalysisSnapshot must expose a payload mapping")
        payload = dict(nested)

        def field(name: str, default: Any = None) -> Any:
            return getattr(value, name, default)
    snapshot_id = _required_text(field("snapshot_id") or payload.get("snapshot_id"), "snapshot_id")
    asset = _required_text(field("asset") or payload.get("asset"), "asset")
    run_id = _required_text(field("run_id") or payload.get("run_id"), "run_id")
    business_time = _datetime(
        field("snapshot_time") or payload.get("snapshot_time") or payload.get("trade_date"),
        "snapshot_time",
    )
    ingested_at = _datetime(
        field("created_at") or field("updated_at") or payload.get("snapshot_time"),
        "created_at",
    )
    raw_refs = field("source_refs") or payload.get("source_refs") or []
    refs = tuple(_safe_ref(item) for item in raw_refs if isinstance(item, Mapping))
    raw_input_ids = field("input_snapshot_ids") or payload.get("input_snapshot_ids") or {}
    snapshot_passport = _flatten_snapshot_ids(raw_input_ids)
    snapshot_passport["analysis_snapshot"] = snapshot_id
    database_id = str(field("id") or "").strip()
    if database_id:
        snapshot_passport["analysis_snapshot_db_id"] = database_id
    if len(snapshot_passport) > 80:
        raise ValueError("AnalysisSnapshot passport exceeds ContextBundle mapping limit")
    return _Snapshot(
        payload=payload,
        snapshot_id=snapshot_id,
        asset=asset,
        run_id=run_id,
        business_time=business_time,
        ingested_at=ingested_at,
        source_refs=refs,
        snapshot_passport=dict(sorted(snapshot_passport.items())),
    )


def _canonical_state(value: Mapping[str, Any] | Any) -> tuple[str, dict[str, Any]]:
    if isinstance(value, Mapping):
        record = dict(value)
        nested = record.get("payload")
        payload = dict(nested) if isinstance(nested, Mapping) else dict(record)
        state_id = record.get("id") or record.get("state_id") or record.get("canonical_state_id")
        for key in ("id", "state_id", "canonical_state_id"):
            if nested is None:
                payload.pop(key, None)
    else:
        nested = getattr(value, "payload", None)
        if not isinstance(nested, Mapping):
            raise TypeError("canonical AnalysisState must expose a payload mapping")
        payload = dict(nested)
        state_id = getattr(value, "id", None)
    return _required_text(state_id, "canonical_state_id"), payload


def _macro_evidence(previous: _Snapshot, current: _Snapshot) -> list[EvidenceItem]:
    prior = _section_data(previous.payload, "macro")
    latest = _section_data(current.payload, "macro")
    prior_indicators = prior.get("indicators") if isinstance(prior, dict) else None
    latest_indicators = latest.get("indicators") if isinstance(latest, dict) else None
    if not isinstance(prior_indicators, Mapping) or not isinstance(latest_indicators, Mapping):
        return []
    result: list[EvidenceItem] = []
    for symbol, (metric, unit) in _MACRO_METRICS.items():
        old_row = _mapping(prior_indicators.get(symbol))
        new_row = _mapping(latest_indicators.get(symbol))
        old_value = _number(old_row.get("value"))
        new_value = _number(new_row.get("value"))
        ref = _source_ref(current, symbol=symbol, section=latest)
        if old_value is None or new_value is None or ref is None:
            continue
        observed_at = _datetime_or_none(new_row.get("date") or latest.get("as_of")) or current.business_time
        source = _required_text(ref.get("source"), "macro source")
        result.append(
            _item(
                current=current,
                source=source,
                kind=f"macro:{metric}",
                business_time=observed_at,
                source_ref=_lineage_ref(ref, previous, current),
                payload={
                    "evidence_type": "macro_metric",
                    "asset": current.asset,
                    "source_quality": _source_quality(source),
                    "metric": metric,
                    "current_value": new_value,
                    "previous_value": old_value,
                    "unit": unit,
                    "metadata": {"symbol": symbol},
                },
            )
        )
    return result


def _key_level_evidence(
    previous: _Snapshot,
    current: _Snapshot,
    state: dict[str, Any],
) -> list[EvidenceItem]:
    old_technical = _section_data(previous.payload, "technical")
    new_technical = _section_data(current.payload, "technical")
    old_price = _number(old_technical.get("price"))
    new_price = _number(new_technical.get("price"))
    ref = _source_ref(current, symbol="XAUUSD", section=new_technical)
    levels = state.get("key_levels")
    if old_price is None or new_price is None or ref is None or not isinstance(levels, list):
        return []
    result: list[EvidenceItem] = []
    for raw_level in levels:
        if not isinstance(raw_level, Mapping):
            continue
        level = _number(raw_level.get("value", raw_level.get("price")))
        role = _level_role(raw_level.get("role"))
        event = _level_event(previous=old_price, current=new_price, level=level, role=role)
        if level is None or role is None or event is None:
            continue
        level_source = str(raw_level.get("source") or ref.get("source") or "").strip()
        level_id = _stable_id("level", role, level_source, level)
        result.append(
            _item(
                current=current,
                source=_required_text(ref.get("source"), "key level source"),
                kind=f"key-level:{level_id}:{event}",
                business_time=current.business_time,
                source_ref=_lineage_ref(ref, previous, current),
                payload={
                    "evidence_type": "key_level_event",
                    "asset": current.asset,
                    "source_quality": _source_quality(str(ref.get("source"))),
                    "level_id": level_id,
                    "level_role": role,
                    "level_value": level,
                    "observed_value": new_price,
                    "event": event,
                    "confirmation_status": "confirmed",
                    "metadata": {"canonical_level_source": level_source},
                },
            )
        )
    return result


def _options_evidence(previous: _Snapshot, current: _Snapshot) -> list[EvidenceItem]:
    prior = _section_data(previous.payload, "options")
    latest = _section_data(current.payload, "options")
    old_gamma = _nested_number(prior, "gex", "netgex_aggregate", "gamma_zero", "price")
    new_gamma = _nested_number(latest, "gex", "netgex_aggregate", "gamma_zero", "price")
    if old_gamma is None or new_gamma is None or old_gamma == 0 or old_gamma == new_gamma:
        return []
    ref = _source_ref(current, source_prefix="cme", section=latest)
    if ref is None:
        return []
    source_status = str(_mapping(latest.get("data_source")).get("status") or "").upper()
    return [
        _item(
            current=current,
            source=_required_text(ref.get("source"), "options source"),
            kind="options:front-month-gamma-zero",
            business_time=_datetime_or_none(latest.get("trade_date") or latest.get("as_of"))
            or current.business_time,
            source_ref=_lineage_ref(ref, previous, current),
            payload={
                "evidence_type": "options_regime",
                "asset": current.asset,
                "source_quality": "exchange",
                "regime_id": "front_month_gamma_zero",
                "event": "gamma_zero_migration",
                "previous_value": old_gamma,
                "current_value": new_gamma,
                "change_pct": ((new_gamma - old_gamma) / abs(old_gamma)) * 100.0,
                "confirmation_status": "confirmed" if source_status == "FINAL" else "unconfirmed",
                "metadata": {"data_status": source_status or "unknown"},
            },
        )
    ]


def _material_event_evidence(previous: _Snapshot, current: _Snapshot) -> list[EvidenceItem]:
    prior = _section_data(previous.payload, "news")
    latest = _section_data(current.payload, "news")
    old_events = {
        _event_identity(item)
        for item in prior.get("recent_events", [])
        if isinstance(item, Mapping) and _event_identity(item) is not None
    }
    ref = _source_ref(current, source_prefix="jin10", section=latest)
    if ref is None:
        return []
    source = _required_text(ref.get("source"), "event source")
    result: list[EvidenceItem] = []
    rows = latest.get("recent_events")
    if not isinstance(rows, list):
        return []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        identity = _event_identity(raw)
        star = _integer(raw.get("star"))
        observed_at = _datetime_or_none(raw.get("pub_time"))
        if identity is None or identity in old_events or star is None or observed_at is None:
            continue
        title, published = identity
        event_id = _stable_id("event", title, published)
        score = float(max(0, min(star, 5)) * 20)
        risk_level = "high" if star >= 4 else "medium" if star >= 3 else "low"
        result.append(
            _item(
                current=current,
                source=source,
                kind=f"material-event:{event_id}",
                business_time=observed_at,
                source_ref=_lineage_ref(ref, previous, current),
                payload={
                    "evidence_type": "material_event",
                    "asset": current.asset,
                    "source_quality": _source_quality(source),
                    "event_id": event_id,
                    "cluster_key": _stable_id("event-cluster", title.casefold(), published[:10]),
                    "event_type": "economic_calendar",
                    "claim": title,
                    "materiality_score": score,
                    "risk_level": risk_level,
                    "recompute_eligible": star >= 4,
                    "confirmation_status": "confirmed",
                    "metadata": {"star": star, "published_at": published},
                },
            )
        )
    return result


def _item(
    *,
    current: _Snapshot,
    source: str,
    kind: str,
    business_time: datetime,
    source_ref: dict[str, Any],
    payload: dict[str, Any],
) -> EvidenceItem:
    resolved_payload = dict(payload)
    metadata = _mapping(resolved_payload.get("metadata"))
    metadata[SNAPSHOT_PASSPORT_METADATA_KEY] = dict(current.snapshot_passport)
    resolved_payload["metadata"] = metadata
    return EvidenceItem(
        source=source,
        evidence_id=_stable_id("snapshot-evidence", current.snapshot_id, kind),
        business_time=business_time,
        ingested_at=current.ingested_at,
        session=None,
        payload=resolved_payload,
        source_ref=source_ref,
    )


def _section_data(payload: dict[str, Any], name: str) -> dict[str, Any]:
    section = payload.get(name)
    if not isinstance(section, Mapping) or section.get("status") != "available":
        return {}
    data = section.get("data")
    return dict(data) if isinstance(data, Mapping) else {}


def _source_ref(
    snapshot: _Snapshot,
    *,
    symbol: str | None = None,
    source_prefix: str | None = None,
    section: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    section_refs = section.get("source_refs") if isinstance(section, Mapping) else None
    if isinstance(section_refs, list):
        candidates.extend(_safe_ref(item) for item in section_refs if isinstance(item, Mapping))
    candidates.extend(snapshot.source_refs)
    for ref in candidates:
        source = str(ref.get("source") or "").strip()
        if not source:
            continue
        if symbol is not None and str(ref.get("symbol") or "").upper() != symbol.upper():
            continue
        if source_prefix is not None and not source.casefold().startswith(source_prefix.casefold()):
            continue
        return dict(ref)
    return None


def _safe_ref(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): item
        for key, item in sorted(value.items())
        if key in _SOURCE_REF_KEYS and item is not None and isinstance(item, (str, int, float, bool))
    }


def _lineage_ref(
    ref: Mapping[str, Any], previous: _Snapshot, current: _Snapshot
) -> dict[str, Any]:
    return {
        **_safe_ref(ref),
        "previous_snapshot_id": previous.snapshot_id,
        "current_snapshot_id": current.snapshot_id,
        "current_run_id": current.run_id,
    }


def _source_quality(source: str) -> str:
    normalized = source.casefold()
    if normalized.startswith(("fred", "federal_reserve", "treasury")):
        return "official"
    if normalized.startswith("cme"):
        return "exchange"
    if normalized.startswith(("jin10", "reuters")):
        return "supplemental" if normalized.startswith("jin10") else "primary"
    if normalized.startswith(("cnbc", "yahoo", "twelve", "tradingview")):
        return "primary"
    return "unverified"


def _level_role(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    aliases = {
        "support": "support",
        "resistance": "resistance",
        "invalidation": "invalidation",
        "gamma_zero": "gamma_zero",
        "option_wall": "option_wall",
        "call_wall": "option_wall",
        "put_wall": "option_wall",
    }
    return aliases.get(normalized)


def _level_event(
    *, previous: float, current: float, level: float | None, role: str | None
) -> str | None:
    if level is None or role is None or previous == current:
        return None
    if current == level and previous != level:
        return "touch"
    crossed_up = previous < level < current
    crossed_down = previous > level > current
    if role == "support":
        return "confirmed_break" if crossed_down else "confirmed_reclaim" if crossed_up else None
    if role == "resistance":
        return "confirmed_break" if crossed_up else "confirmed_reclaim" if crossed_down else None
    if crossed_up or crossed_down:
        return "confirmed_break"
    return None


def _event_identity(value: Mapping[str, Any]) -> tuple[str, str] | None:
    title = str(value.get("title") or "").strip()
    published = str(value.get("pub_time") or "").strip()
    return (title, published) if title and published else None


def _nested_number(value: Mapping[str, Any], *path: str) -> float | None:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return _number(current)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _flatten_snapshot_ids(value: Any, *, prefix: str = "") -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for raw_key, raw_value in sorted(value.items(), key=lambda item: str(item[0])):
        key = str(raw_key).strip()
        if not key:
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(raw_value, Mapping):
            result.update(_flatten_snapshot_ids(raw_value, prefix=path))
            continue
        if isinstance(raw_value, str) and raw_value.strip():
            result[path] = raw_value.strip()
    return result


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in {float("inf"), float("-inf")} else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


def _datetime(value: Any, field: str) -> datetime:
    parsed = _datetime_or_none(value)
    if parsed is None:
        raise ValueError(f"{field} must be an ISO date or datetime")
    return parsed


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=UTC)
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed_date = date.fromisoformat(text[:10])
            except ValueError:
                return None
            parsed = datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC)
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    return normalized


def _stable_id(*parts: Any) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "snapshot_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]
