"""Fail-closed adapter from legacy analysis snapshots to FeatureSnapshot v2."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse

from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.schemas import FeatureSnapshotV2, SourceReference
from apps.features.news.formal_events import OfficialEventSnapshot as FormalOfficialEventSnapshot
from apps.features.positioning.formal_snapshot import COTSnapshot


_OBSERVATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("us02y", "US02Y", "US02Y", "yield", "percent"),
    ("us10y", "US10Y", "US10Y", "yield", "percent"),
    ("us30y", "US30Y", "US30Y", "yield", "percent"),
    ("t10yie", "T10YIE", "T10YIE", "breakeven_inflation", "percent"),
    ("broad_dollar", "BROAD_DOLLAR", "DTWEXBGS", "broad_dollar", "index"),
)

_MACRO_SOURCE_SYMBOLS: dict[str, str] = {
    "US02Y": "DGS2",
    "US10Y": "DGS10",
    "US30Y": "DGS30",
    "T10YIE": "T10YIE",
    "REAL10Y": "DFII10",
    "BROAD_DOLLAR": "DTWEXBGS",
}

_OPTIONAL: tuple[tuple[str, str, str, str], ...] = (
    ("gc_futures", "GC_FUTURES", "futures", "price"),
    ("wti", "WTI", "oil", "usd_per_bbl"),
    ("brent", "BRENT", "oil", "usd_per_bbl"),
    ("etf_flow", "GOLD_ETF_FLOW", "flow", "tonnes"),
    ("cot", "GOLD_COT", "positioning", "contracts"),
    ("cme_options_regime", "CME_GC_OPTIONS_REGIME", "options_regime", "score"),
)


def build_feature_snapshot_from_analysis_snapshot(snapshot: Mapping[str, Any]) -> FeatureSnapshotV2:
    """Adapt only verifiable structured legacy fields, otherwise explicitly block.

    This boundary intentionally has no I/O and does not inspect prose.  It is a
    compatibility adapter, not a recovery mechanism for incomplete legacy data.
    """

    if snapshot.get("asset") != "XAUUSD":
        raise ValueError("legacy analysis snapshot asset must be XAUUSD")
    as_of = _snapshot_time(snapshot)
    snapshot_ref = _snapshot_reference(snapshot, as_of)
    macro = _available_data(snapshot.get("macro"))
    technical = _available_data(snapshot.get("technical"))
    market_prices = snapshot.get("market_prices")
    oil = snapshot.get("oil")
    cot = snapshot.get("cot")

    payload: dict[str, Any] = {
        "schema_version": "feature_snapshot.v2",
        "readiness_policy_version": "gold_readiness_policy.v1",
        "asset": "XAUUSD",
        "scope": "daily_close",
        "as_of": as_of,
        "xauusd_spot": _formal_observation(market_prices, "market_price_snapshot.v1", "xauusd_spot", "XAUUSD_SPOT", "spot", "usd_per_troy_oz", "5m", as_of, snapshot_ref) if "market_prices" in snapshot else _spot_observation(technical, as_of, snapshot_ref),
        "gc_futures": _formal_observation(market_prices, "market_price_snapshot.v1", "gc_futures", "GC_FUTURES", "futures", "usd_per_troy_oz", "1d", as_of, snapshot_ref) if "market_prices" in snapshot else None,
        "official_events": _official_events(snapshot, as_of, snapshot_ref),
    }
    indicators = macro.get("indicators") if isinstance(macro.get("indicators"), Mapping) else {}
    aligned_real10y = _aligned_real10y_observations(macro, as_of, snapshot_ref)
    for field, key, series_id, role, unit in _OBSERVATIONS:
        if aligned_real10y is not None and field in {"us10y", "t10yie"}:
            payload[field] = aligned_real10y.get(field) or _missing(
                series_id, role, unit, as_of, snapshot_ref
            )
        else:
            payload[field] = _macro_indicator_observation(
                indicators.get(key),
                macro.get("source_refs"),
                source_symbol=_MACRO_SOURCE_SYMBOLS[key],
                series_id=series_id,
                role=role,
                unit=unit,
                snapshot_time=as_of,
                snapshot_ref=snapshot_ref,
            )
    # REAL10Y is the direct DFII10 observation only.  The estimated real yield
    # is constructed by the canonical v2 builder from US10Y and T10YIE.
    payload["real10y_direct"] = _macro_indicator_observation(
        indicators.get("REAL10Y"),
        macro.get("source_refs"),
        source_symbol="DFII10",
        series_id="DFII10",
        role="real_yield_direct",
        unit="percent",
        snapshot_time=as_of,
        snapshot_ref=snapshot_ref,
    )
    for field, series_id, role, unit in _OPTIONAL:
        if field == "gc_futures" and "market_prices" in snapshot:
            payload[field] = payload[field] or _formal_missing(series_id, role, unit, as_of, snapshot_ref)
        elif field == "cot" and "cot" in snapshot:
            payload[field] = _formal_cot_observation(cot, as_of, snapshot_ref)
        elif field in {"wti", "brent"} and "oil" in snapshot:
            payload[field] = _formal_observation(oil, "oil_snapshot.v1", field, series_id, role, unit, "1d", as_of, snapshot_ref)
        else:
            payload[field] = _optional_observation(snapshot, field, series_id, role, unit, as_of, snapshot_ref)
    result = build_feature_snapshot(payload)
    if not isinstance(result, FeatureSnapshotV2):
        raise AssertionError("legacy adapter must produce feature_snapshot.v2")
    return result


def _snapshot_time(snapshot: Mapping[str, Any]) -> datetime:
    value = snapshot.get("snapshot_time") or snapshot.get("trade_date")
    parsed = _parse_time(value)
    if parsed is None:
        raise ValueError("legacy analysis snapshot requires a parseable snapshot_time or trade_date")
    return parsed


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _snapshot_reference(snapshot: Mapping[str, Any], as_of: datetime) -> SourceReference:
    identifier = snapshot.get("snapshot_id") or snapshot.get("run_id") or "unidentified-analysis-snapshot"
    return SourceReference(source="analysis_snapshot", reference=str(identifier), retrieved_at=as_of)


def _available_data(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or value.get("status") != "available":
        return {}
    data = value.get("data")
    return data if isinstance(data, Mapping) else {}


def _missing(series_id: str, role: str, unit: str, as_of: datetime, snapshot_ref: SourceReference) -> dict[str, Any]:
    return {
        "series_id": series_id, "market_role": role, "value": None, "unit": unit, "as_of": as_of,
        "expected_frequency": "daily", "freshness_status": "missing", "quality_status": "blocked",
        "alignment_status": "unknown", "source_refs": (snapshot_ref,),
    }


def _formal_missing(series_id: str, role: str, unit: str, as_of: datetime, snapshot_ref: SourceReference, *, alignment: str = "misaligned") -> dict[str, Any]:
    payload = _missing(series_id, role, unit, as_of, snapshot_ref)
    return {**payload, "alignment_status": alignment}


def _formal_observation(section: object, schema_version: str, field: str, series_id: str, role: str, unit: str, timeframe: str, snapshot_time: datetime, snapshot_ref: SourceReference) -> dict[str, Any]:
    """Consume a formal section exclusively; malformed payloads never fall back."""

    if not isinstance(section, Mapping) or section.get("status") != "available":
        return _formal_missing(series_id, role, unit, snapshot_time, snapshot_ref)
    data = section.get("data")
    if not isinstance(data, Mapping) or data.get("schema_version") != schema_version:
        return _formal_missing(series_id, role, unit, snapshot_time, snapshot_ref)
    value = data.get(field)
    if not isinstance(value, Mapping):
        return _formal_missing(series_id, role, unit, snapshot_time, snapshot_ref)
    if (
        value.get("series_id") != series_id
        or value.get("market_role") != role
        or value.get("timeframe") != timeframe
        or value.get("asset") != ("XAUUSD" if series_id == "XAUUSD_SPOT" else "GC" if series_id == "GC_FUTURES" else series_id)
    ):
        return _formal_missing(series_id, role, unit, snapshot_time, snapshot_ref)
    freshness = _axis(value.get("freshness_status"), {"fresh", "stale", "missing"}, "missing")
    quality = _axis(value.get("quality_status"), {"accepted", "observe", "blocked"}, "blocked")
    alignment = _axis(value.get("alignment_status"), {"aligned", "misaligned", "unknown"}, "misaligned")
    refs = _formal_source_references(value.get("source_refs"))
    if freshness == "missing":
        if value.get("value") is not None or not refs:
            return _formal_missing(series_id, role, unit, snapshot_time, snapshot_ref)
        return {"series_id": series_id, "market_role": role, "value": None, "unit": unit, "as_of": _parse_time(value.get("bar_close_time")) or snapshot_time, "expected_frequency": str(value.get("expected_frequency") or timeframe), "freshness_status": "missing", "quality_status": "blocked", "alignment_status": alignment, "source_refs": refs}
    bar_open_time = _parse_formal_time(value.get("bar_open_time"))
    bar_close_time = _parse_formal_time(value.get("bar_close_time"))
    if not refs or any(ref.retrieved_at > snapshot_time for ref in refs) or bar_open_time is None or bar_close_time is None or bar_close_time <= bar_open_time or bar_close_time > snapshot_time or not _number(value.get("value")) or not _number(value.get("close")) or float(value["value"]) != float(value["close"]):
        return _formal_missing(series_id, role, unit, snapshot_time, snapshot_ref)
    return {"series_id": series_id, "market_role": role, "value": float(value["value"]), "unit": unit, "as_of": bar_close_time, "expected_frequency": str(value.get("expected_frequency") or timeframe), "freshness_status": freshness, "quality_status": quality, "alignment_status": alignment, "source_refs": refs}


def _formal_source_references(value: object) -> tuple[SourceReference, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    refs: list[SourceReference] = []
    for raw in value:
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump(mode="python")
        if not isinstance(raw, Mapping):
            return ()
        source, reference, retrieved_at = raw.get("source"), raw.get("reference"), _parse_formal_time(raw.get("retrieved_at"))
        if not isinstance(source, str) or not source.strip() or not isinstance(reference, str) or not reference.strip() or retrieved_at is None:
            return ()
        refs.append(SourceReference(source=source, reference=reference, retrieved_at=retrieved_at))
    return tuple(refs)


def _formal_cot_observation(section: object, snapshot_time: datetime, snapshot_ref: SourceReference) -> dict[str, Any]:
    """Consume only the exact COT formal contract; never infer legacy positioning."""

    if not isinstance(section, Mapping) or section.get("status") != "available":
        return _formal_missing("GOLD_COT", "positioning", "contracts", snapshot_time, snapshot_ref)
    data = section.get("data")
    if not isinstance(data, Mapping) or data.get("schema_version") != "cot_snapshot.v1":
        return _formal_missing("GOLD_COT", "positioning", "contracts", snapshot_time, snapshot_ref)
    try:
        formal_snapshot = COTSnapshot.model_validate(data)
    except ValueError:
        return _formal_missing("GOLD_COT", "positioning", "contracts", snapshot_time, snapshot_ref)
    data = formal_snapshot.model_dump(mode="json")
    formal_as_of = _parse_formal_time(data.get("as_of"))
    observation = data.get("managed_money_net")
    if formal_as_of is None or formal_as_of > snapshot_time or not isinstance(observation, Mapping):
        return _formal_missing("GOLD_COT", "positioning", "contracts", snapshot_time, snapshot_ref)
    if (
        observation.get("series_id") != "GOLD_COT"
        or observation.get("metric_kind") != "managed_money_net_contracts"
        or observation.get("unit") != "contracts"
        or observation.get("expected_frequency") != "weekly"
    ):
        return _formal_missing("GOLD_COT", "positioning", "contracts", snapshot_time, snapshot_ref)
    freshness = _axis(observation.get("freshness_status"), {"fresh", "stale", "missing"}, "missing")
    quality = _axis(observation.get("quality_status"), {"accepted", "observe", "blocked"}, "blocked")
    alignment = _axis(observation.get("alignment_status"), {"aligned", "misaligned", "unknown"}, "misaligned")
    refs = _formal_source_references(observation.get("source_refs"))
    if not refs or any(ref.retrieved_at > snapshot_time for ref in refs):
        return _formal_missing("GOLD_COT", "positioning", "contracts", snapshot_time, snapshot_ref)
    if freshness == "missing":
        if observation.get("value") is not None or observation.get("report_date") is not None or quality != "blocked":
            return _formal_missing("GOLD_COT", "positioning", "contracts", snapshot_time, snapshot_ref)
        if data.get("readiness") != "blocked":
            return _formal_missing("GOLD_COT", "positioning", "contracts", snapshot_time, snapshot_ref)
        return {"series_id": "GOLD_COT", "market_role": "positioning", "value": None, "unit": "contracts", "as_of": snapshot_time, "expected_frequency": "weekly", "freshness_status": "missing", "quality_status": "blocked", "alignment_status": alignment, "source_refs": refs}
    report_date = _parse_date(observation.get("report_date"))
    if report_date is None or report_date > formal_as_of.date() or report_date > snapshot_time.date() or not _number(observation.get("value")):
        return _formal_missing("GOLD_COT", "positioning", "contracts", snapshot_time, snapshot_ref)
    expected_readiness = "blocked" if quality == "blocked" or alignment == "misaligned" else "observe" if quality == "observe" or freshness == "stale" or alignment == "unknown" else "ready"
    if data.get("readiness") != expected_readiness:
        return _formal_missing("GOLD_COT", "positioning", "contracts", snapshot_time, snapshot_ref)
    return {"series_id": "GOLD_COT", "market_role": "positioning", "value": float(observation["value"]), "unit": "contracts", "as_of": datetime.combine(report_date, time.min, tzinfo=UTC), "expected_frequency": "weekly", "freshness_status": freshness, "quality_status": quality, "alignment_status": alignment, "source_refs": refs}


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_formal_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _indicator_observation(value: object, series_id: str, role: str, unit: str, snapshot_time: datetime, snapshot_ref: SourceReference) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not _number(value.get("value")):
        return _missing(series_id, role, unit, snapshot_time, snapshot_ref)
    return _present_observation(value, series_id, role, unit, snapshot_time, snapshot_ref)


def _macro_indicator_observation(
    value: object,
    source_refs: object,
    *,
    source_symbol: str,
    series_id: str,
    role: str,
    unit: str,
    snapshot_time: datetime,
    snapshot_ref: SourceReference,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not _number(value.get("value")):
        return _missing(series_id, role, unit, snapshot_time, snapshot_ref)
    if not isinstance(source_refs, Mapping) or source_symbol not in source_refs:
        return _indicator_observation(
            value, series_id, role, unit, snapshot_time, snapshot_ref
        )
    source_ref = _strict_macro_source_reference(
        source_refs.get(source_symbol),
        expected_symbol=source_symbol,
        snapshot_time=snapshot_time,
    )
    if source_ref is None:
        return _missing(series_id, role, unit, snapshot_time, snapshot_ref)
    candidate = {
        **value,
        "source_refs": (source_ref.model_dump(mode="json"),),
    }
    return _indicator_observation(
        candidate, series_id, role, unit, snapshot_time, snapshot_ref
    )


def _aligned_real10y_observations(
    macro: Mapping[str, Any],
    snapshot_time: datetime,
    snapshot_ref: SourceReference,
) -> dict[str, dict[str, Any]] | None:
    """Return exact same-date constituents used by canonical REAL_10Y.

    Absence preserves legacy input behavior. Once a producer advertises
    components, malformed arithmetic or lineage blocks both core observations
    instead of falling back to independently latest values.
    """

    indicators = macro.get("indicators")
    if not isinstance(indicators, Mapping):
        return None
    derived = indicators.get("REAL_10Y")
    if not isinstance(derived, Mapping):
        return None
    derivation_version = derived.get("derivation_version")
    if derivation_version is None and "components" not in derived:
        return None
    if derivation_version != "real10y_components.v1" or "components" not in derived:
        return {}
    raw_components = derived.get("components")
    if (
        not isinstance(raw_components, Sequence)
        or isinstance(raw_components, (str, bytes))
        or len(raw_components) != 2
        or not _number(derived.get("value"))
    ):
        return {}

    derived_at = _parse_time(derived.get("date") or derived.get("as_of"))
    if derived_at is None or derived_at > snapshot_time:
        return {}
    source_refs = macro.get("source_refs")
    if not isinstance(source_refs, Mapping):
        return {}

    by_symbol: dict[str, tuple[float, SourceReference]] = {}
    for raw in raw_components:
        if not isinstance(raw, Mapping):
            return {}
        symbol = raw.get("source_symbol")
        component_at = _parse_time(raw.get("date") or raw.get("as_of"))
        if (
            symbol not in {"DGS10", "T10YIE"}
            or symbol in by_symbol
            or component_at != derived_at
            or not _number(raw.get("value"))
        ):
            return {}
        source_ref = _strict_macro_source_reference(
            source_refs.get(symbol), expected_symbol=str(symbol), snapshot_time=snapshot_time
        )
        if source_ref is None:
            return {}
        by_symbol[str(symbol)] = (float(raw["value"]), source_ref)

    if set(by_symbol) != {"DGS10", "T10YIE"}:
        return {}
    us10y_value, us10y_ref = by_symbol["DGS10"]
    t10yie_value, t10yie_ref = by_symbol["T10YIE"]
    if us10y_ref.reference == t10yie_ref.reference:
        return {}
    derived_value = Decimal(str(us10y_value)) - Decimal(str(t10yie_value))
    if round(derived_value, 6) != round(Decimal(str(derived["value"])), 6):
        return {}

    freshness_status = _daily_observation_freshness(derived_at, snapshot_time)

    return {
        "us10y": _present_observation(
            {
                "value": us10y_value,
                "date": derived_at.isoformat(),
                "freshness_status": freshness_status,
                "quality_status": "accepted",
                "alignment_status": "aligned",
                "source_refs": (us10y_ref.model_dump(mode="json"),),
            },
            "US10Y",
            "yield",
            "percent",
            snapshot_time,
            snapshot_ref,
        ),
        "t10yie": _present_observation(
            {
                "value": t10yie_value,
                "date": derived_at.isoformat(),
                "freshness_status": freshness_status,
                "quality_status": "accepted",
                "alignment_status": "aligned",
                "source_refs": (t10yie_ref.model_dump(mode="json"),),
            },
            "T10YIE",
            "breakeven_inflation",
            "percent",
            snapshot_time,
            snapshot_ref,
        ),
    }


def _strict_macro_source_reference(
    value: object,
    *,
    expected_symbol: str,
    snapshot_time: datetime,
) -> SourceReference | None:
    if not isinstance(value, Mapping):
        return None
    source = value.get("source")
    reference = value.get("source_url")
    raw_path = value.get("raw_path")
    retrieved_at = _parse_formal_time(value.get("retrieved_at"))
    parsed_reference = urlparse(reference) if isinstance(reference, str) else None
    series_ids = parse_qs(parsed_reference.query).get("series_id", []) if parsed_reference else []
    if (
        not isinstance(source, str)
        or source.strip().lower() != "fred"
        or not isinstance(reference, str)
        or not reference.strip()
        or parsed_reference is None
        or parsed_reference.scheme != "https"
        or parsed_reference.hostname != "api.stlouisfed.org"
        or parsed_reference.path != "/fred/series/observations"
        or series_ids != [expected_symbol]
        or not isinstance(raw_path, str)
        or not raw_path.strip()
        or retrieved_at is None
        or retrieved_at > snapshot_time
    ):
        return None
    return SourceReference(source=source, reference=reference, retrieved_at=retrieved_at)


def _daily_observation_freshness(observed_at: datetime, snapshot_time: datetime) -> str:
    return "fresh" if (snapshot_time.date() - observed_at.date()).days <= 3 else "stale"


def _spot_observation(technical: Mapping[str, Any], snapshot_time: datetime, snapshot_ref: SourceReference) -> dict[str, Any]:
    # Only the structured technical XAUUSD price is eligible.  Yahoo/GC=F is
    # rejected even if a value happens to be present under a legacy field.
    candidate = technical.get("xauusd") if isinstance(technical.get("xauusd"), Mapping) else technical
    refs = _source_references(candidate.get("source_refs") if isinstance(candidate, Mapping) else None, snapshot_time, snapshot_ref)
    source_text = " ".join(f"{ref.source} {ref.reference}".lower() for ref in refs)
    if (
        not isinstance(candidate, Mapping)
        or not _number(candidate.get("price", candidate.get("value")))
        or "gc=f" in source_text
        or "yahoo" in source_text
    ):
        return _missing("XAUUSD_SPOT", "spot", "usd_per_troy_oz", snapshot_time, snapshot_ref)
    candidate = {**candidate, "value": candidate.get("price", candidate.get("value")), "source_refs": refs}
    return _present_observation(candidate, "XAUUSD_SPOT", "spot", "usd_per_troy_oz", snapshot_time, snapshot_ref)


def _optional_observation(snapshot: Mapping[str, Any], field: str, series_id: str, role: str, unit: str, snapshot_time: datetime, snapshot_ref: SourceReference) -> dict[str, Any]:
    # Optional domains are admitted only through a named structured section.
    section_names = {"gc_futures": "futures", "wti": "oil", "brent": "oil", "etf_flow": "etf_flow", "cot": "positioning", "cme_options_regime": "options"}
    data = _available_data(snapshot.get(section_names[field]))
    candidate = data.get(field) if isinstance(data.get(field), Mapping) else data
    if not isinstance(candidate, Mapping) or not _number(candidate.get("value")):
        return _missing(series_id, role, unit, snapshot_time, snapshot_ref)
    return _present_observation(candidate, series_id, role, unit, snapshot_time, snapshot_ref)


def _present_observation(value: Mapping[str, Any], series_id: str, role: str, unit: str, snapshot_time: datetime, snapshot_ref: SourceReference) -> dict[str, Any]:
    observed_at = _parse_time(value.get("as_of") or value.get("date")) or snapshot_time
    refs = _source_references(value.get("source_refs"), snapshot_time, snapshot_ref)
    freshness = _axis(value.get("freshness_status") or value.get("status"), {"fresh", "stale", "missing"}, "fresh")
    quality = _axis(value.get("quality_status"), {"accepted", "observe", "blocked"}, "observe" if freshness == "stale" else "accepted")
    alignment = _axis(value.get("alignment_status"), {"aligned", "misaligned", "unknown"}, "aligned")
    future = observed_at > snapshot_time
    if future:
        # Point-in-time violation is independent of freshness: retain the
        # observed freshness but prevent it from entering formal analysis.
        quality, alignment = "blocked", "misaligned"
    return {
        "series_id": series_id, "market_role": role, "value": float(value["value"]), "unit": str(value.get("unit") or unit),
        "as_of": observed_at, "expected_frequency": str(value.get("expected_frequency") or "daily"),
        "freshness_status": freshness, "quality_status": quality, "alignment_status": alignment, "source_refs": refs,
    }


def _official_events(snapshot: Mapping[str, Any], snapshot_time: datetime, snapshot_ref: SourceReference) -> dict[str, Any]:
    if "official_events" not in snapshot:
        return _legacy_official_events(snapshot, snapshot_time, snapshot_ref)
    section = snapshot.get("official_events")
    if not isinstance(section, Mapping) or section.get("status") != "available":
        return _blocked_official_events(snapshot_time, snapshot_ref)
    payload = section.get("data")
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "official_event_snapshot.v1":
        return _blocked_official_events(snapshot_time, snapshot_ref)
    try:
        formal = FormalOfficialEventSnapshot.model_validate(payload)
    except ValueError:
        return _blocked_official_events(snapshot_time, snapshot_ref)
    formal_as_of = _parse_formal_time(formal.as_of)
    snapshot_refs = _formal_source_references(formal.source_refs)
    if (
        formal_as_of is None
        or formal_as_of > snapshot_time
        or formal.readiness == "blocked"
        or formal.quality_status == "blocked"
        or formal.alignment_status == "misaligned"
        or not snapshot_refs
        or any(ref.retrieved_at > snapshot_time for ref in snapshot_refs)
    ):
        return _blocked_official_events(snapshot_time, snapshot_ref)

    parsed_events: list[dict[str, Any]] = []
    for event in formal.events:
        occurred_at = _parse_formal_time(event.occurred_at)
        reaction_window_end = _parse_formal_time(event.reaction_window_end)
        event_refs = _formal_source_references(event.source_refs)
        reaction_refs = _formal_source_references(event.reaction_source_refs)
        if (
            occurred_at is None
            or occurred_at > snapshot_time
            or not event_refs
            or any(ref.retrieved_at > snapshot_time for ref in (*event_refs, *reaction_refs))
            or (
                event.reaction_status == "confirmed"
                and (
                    reaction_window_end is None
                    or reaction_window_end > snapshot_time
                    or reaction_window_end <= occurred_at
                    or event.reaction_asset != "XAUUSD"
                    or not _number(event.reaction_return_pct)
                    or not event.reaction_summary
                    or not reaction_refs
                )
            )
        ):
            return _blocked_official_events(snapshot_time, snapshot_ref)
        parsed_events.append(
            {
                "event_id": event.event_id,
                "title": event.title,
                "occurred_at": occurred_at,
                "reaction_window_end": reaction_window_end,
                "reaction_summary": event.reaction_summary,
                "reaction_asset": event.reaction_asset,
                "reaction_return_pct": event.reaction_return_pct,
                "reaction_status": event.reaction_status,
                "source_refs": event_refs,
                "reaction_source_refs": reaction_refs,
            }
        )
    return {
        "events": tuple(parsed_events),
        "as_of": formal_as_of,
        "expected_frequency": "event_driven",
        "freshness_status": formal.freshness_status,
        "quality_status": formal.quality_status,
        "alignment_status": formal.alignment_status,
        "source_refs": snapshot_refs,
    }


def _blocked_official_events(snapshot_time: datetime, snapshot_ref: SourceReference) -> dict[str, Any]:
    return {
        "events": (),
        "as_of": snapshot_time,
        "expected_frequency": "event_driven",
        "freshness_status": "missing",
        "quality_status": "blocked",
        "alignment_status": "misaligned",
        "source_refs": (snapshot_ref,),
    }


def _legacy_official_events(snapshot: Mapping[str, Any], snapshot_time: datetime, snapshot_ref: SourceReference) -> dict[str, Any]:
    section = _available_data(snapshot.get("official_events"))
    events = section.get("events") if isinstance(section.get("events"), Sequence) and not isinstance(section.get("events"), (str, bytes)) else ()
    parsed_events: list[dict[str, Any]] = []
    has_future_event = False
    for event in events:
        if not isinstance(event, Mapping) or not isinstance(event.get("event_id"), str) or not isinstance(event.get("title"), str):
            continue
        occurred_at = _parse_time(event.get("occurred_at"))
        if occurred_at is None:
            continue
        has_future_event = has_future_event or occurred_at > snapshot_time
        reaction_status = _axis(event.get("reaction_status"), {"confirmed", "observe", "unconfirmed"}, "unconfirmed")
        reaction_window_end = _parse_time(event.get("reaction_window_end"))
        reaction_refs = _source_references(event.get("reaction_source_refs"), snapshot_time, snapshot_ref) if event.get("reaction_source_refs") else ()
        if reaction_status == "confirmed" and (
            reaction_window_end is None
            or event.get("reaction_asset") != "XAUUSD"
            or not _number(event.get("reaction_return_pct"))
            or not isinstance(event.get("reaction_summary"), str)
            or not reaction_refs
        ):
            reaction_status = "unconfirmed"
        parsed_events.append({
            "event_id": event["event_id"], "title": event["title"], "occurred_at": occurred_at,
            "reaction_window_end": reaction_window_end, "reaction_summary": event.get("reaction_summary"),
            "reaction_asset": event.get("reaction_asset"), "reaction_return_pct": event.get("reaction_return_pct"),
            "reaction_status": reaction_status,
            "source_refs": _source_references(event.get("source_refs"), snapshot_time, snapshot_ref),
            "reaction_source_refs": reaction_refs,
        })
    present = bool(section)
    freshness = _axis(section.get("freshness_status") or section.get("status"), {"fresh", "stale", "missing"}, "fresh") if present else "missing"
    quality = _axis(section.get("quality_status"), {"accepted", "observe", "blocked"}, "observe" if freshness == "stale" else "accepted") if present else "blocked"
    alignment = _axis(section.get("alignment_status"), {"aligned", "misaligned", "unknown"}, "aligned") if present else "unknown"
    if has_future_event:
        quality, alignment = "blocked", "misaligned"
    return {
        "events": tuple(parsed_events), "as_of": snapshot_time, "expected_frequency": "event_driven",
        "freshness_status": freshness, "quality_status": quality, "alignment_status": alignment,
        "source_refs": _source_references(section.get("source_refs"), snapshot_time, snapshot_ref),
    }


def _source_references(value: object, snapshot_time: datetime, fallback: SourceReference) -> tuple[SourceReference, ...]:
    raw_refs = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()
    refs: list[SourceReference] = []
    for raw in raw_refs:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("source"), str) or not raw["source"].strip():
            continue
        reference = raw.get("source_url") or raw.get("raw_path") or raw.get("reference") or raw.get("source_ref")
        if not isinstance(reference, str) or not reference.strip():
            continue
        refs.append(SourceReference(source=raw["source"], reference=reference, retrieved_at=_parse_time(raw.get("retrieved_at") or raw.get("as_of") or raw.get("date")) or snapshot_time))
    return tuple(refs) or (fallback,)


def _number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _axis(value: object, allowed: set[str], default: str) -> str:
    normalized = str(value).lower() if value is not None else default
    return normalized if normalized in allowed else default
