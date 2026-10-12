"""Deterministic growth-domain features and source health.

This module consumes normalized ``MacroPoint`` values and the source
references emitted by :mod:`apps.collectors.growth.official`.  It never
assumes that a monthly/quarterly value is a daily market observation.  A
source response can therefore be available for context while its current
period is explicitly marked ``not_published`` or its local value is rejected
as ``stale`` when the official source has moved ahead.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping


GROWTH_SYMBOLS = (
    "GDP_NOW",
    "ISM_MANUFACTURING",
    "ISM_SERVICES",
    "ISM_SERVICES_PRICES",
)
_SOURCE_BY_SYMBOL = {
    "GDP_NOW": "gdp_now",
    "ISM_MANUFACTURING": "ism_manufacturing",
    "ISM_SERVICES": "ism_services",
    "ISM_SERVICES_PRICES": "ism_services",
}
_LABELS = {
    "GDP_NOW": "Atlanta Fed GDPNow",
    "ISM_MANUFACTURING": "ISM Manufacturing PMI",
    "ISM_SERVICES": "ISM Services PMI",
    "ISM_SERVICES_PRICES": "ISM Services Prices Index",
}
_UNITS = {
    "GDP_NOW": "% q/q saar",
    "ISM_MANUFACTURING": "index",
    "ISM_SERVICES": "index",
    "ISM_SERVICES_PRICES": "index",
}


@dataclass(frozen=True)
class GrowthMetric:
    """One growth observation with reference-period and freshness semantics."""

    symbol: str
    label: str
    status: str
    value: float | None = None
    unit: str = ""
    observation_date: str | None = None
    reference_period: str | None = None
    previous_value: float | None = None
    previous_reference_period: str | None = None
    change: float | None = None
    release_date: str | None = None
    release_time: str | None = None
    source_key: str | None = None
    source_ref: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GrowthFeatureSnapshot:
    """Feature snapshot consumed by the macro research and report layers."""

    as_of: str
    metrics: dict[str, GrowthMetric]
    unavailable_symbols: list[str]
    source_refs: dict[str, dict[str, Any]]
    collector_health: dict[str, dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    status: str = "partial"

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "metrics": {symbol: metric.to_dict() for symbol, metric in self.metrics.items()},
            "unavailable_symbols": self.unavailable_symbols,
            "source_refs": self.source_refs,
            "collector_health": self.collector_health,
            "warnings": self.warnings,
            "status": self.status,
        }


def build_growth_features(
    points: Iterable[Mapping[str, Any] | object],
    *,
    as_of: str,
    unavailable_symbols: Iterable[str] | None = (),
    source_refs: Iterable[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None = (),
    collector_health: Mapping[str, Mapping[str, Any]] | None = None,
) -> GrowthFeatureSnapshot:
    """Build growth metrics from an already collected point-in-time bundle.

    The feature layer treats ``actual_latest_date`` as the latest local point
    and compares it with the official source's ``official_latest_date``.  A
    local point behind the official date is rejected and recorded in
    ``warnings``; it cannot silently support a current growth signal.
    """

    cutoff = _parse_date(as_of)
    refs = _source_ref_items(source_refs)
    refs_by_symbol = {
        str(ref.get("symbol")): dict(ref)
        for ref in refs
        if str(ref.get("symbol") or "") in GROWTH_SYMBOLS
    }
    health = {
        str(key): dict(value)
        for key, value in (collector_health or {}).items()
        if isinstance(value, Mapping)
    }
    for symbol, ref in refs_by_symbol.items():
        source_key = str(ref.get("source_key") or _SOURCE_BY_SYMBOL.get(symbol) or symbol.lower())
        if source_key not in health and _has_health_fields(ref):
            health[source_key] = {
                key: ref[key]
                for key in (
                    "source_key",
                    "symbols",
                    "source",
                    "source_url",
                    "raw_path",
                    "retrieved_at",
                    "expected_release_time",
                    "expected_release_date",
                    "expected_release_timezone",
                    "actual_latest_date",
                    "official_latest_date",
                    "collector_status",
                    "staleness",
                    "expected_freshness",
                    "release_status",
                    "reason",
                )
                if key in ref
            }

    # Keep the health contract stable even when a caller builds the feature
    # from a partial/manual bundle.  A missing source is explicitly
    # ``not_connected``; it is never treated as a neutral or successful input.
    for source_key in dict.fromkeys(_SOURCE_BY_SYMBOL.values()):
        health.setdefault(
            source_key,
            {
                "source_key": source_key,
                "collector_status": "not_connected",
                "staleness": "unknown",
                "expected_freshness": "event_driven" if source_key == "gdp_now" else "monthly",
                "expected_release_time": None,
                "actual_latest_date": None,
                "official_latest_date": None,
            },
        )

    by_symbol: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in GROWTH_SYMBOLS}
    for raw_point in points:
        point = _point_mapping(raw_point)
        symbol = str(point.get("symbol") or "")
        if symbol not in by_symbol:
            continue
        observation_date = _date_or_none(point.get("date"))
        if observation_date is None:
            continue
        normalized = dict(point)
        normalized["date"] = observation_date.isoformat()
        try:
            normalized["value"] = float(point["value"])
        except (KeyError, TypeError, ValueError):
            continue
        by_symbol[symbol].append(normalized)
    for values in by_symbol.values():
        values.sort(key=lambda item: str(item["date"]))

    explicit_unavailable = {str(item) for item in (unavailable_symbols or ())}
    metrics: dict[str, GrowthMetric] = {}
    unavailable: set[str] = set()
    warnings: list[str] = []

    for symbol in GROWTH_SYMBOLS:
        ref = refs_by_symbol.get(symbol, {})
        source_key = str(ref.get("source_key") or _SOURCE_BY_SYMBOL[symbol])
        source_health = dict(health.get(source_key) or {})
        values = by_symbol[symbol]
        point = values[-1] if values else None
        upstream_status = str(source_health.get("collector_status") or ref.get("collector_status") or "")
        if symbol in explicit_unavailable or point is None:
            status = _unavailable_status(upstream_status, source_health)
            reason = str(source_health.get("reason") or ref.get("reason") or "growth observation unavailable")
            metrics[symbol] = GrowthMetric(
                symbol=symbol,
                label=_LABELS[symbol],
                status=status,
                unit=_UNITS[symbol],
                source_key=source_key,
                source_ref=ref,
                reason=reason,
            )
            unavailable.add(symbol)
            continue

        local_date = str(point["date"])
        official_date = _date_or_none(source_health.get("official_latest_date") or ref.get("official_latest_date"))
        source_health["source_key"] = source_key
        source_health["actual_latest_date"] = local_date
        if official_date is not None:
            source_health["official_latest_date"] = official_date.isoformat()

        stale_local = official_date is not None and date.fromisoformat(local_date) < official_date
        future = date.fromisoformat(local_date) > cutoff
        official_future = official_date is not None and official_date > cutoff
        failure = upstream_status in {"auth_failed", "fetch_failed", "future_observation"}
        if future or official_future:
            status = "unavailable"
            reason = "official growth observation is after the requested cutoff"
            source_health["collector_status"] = "future_observation"
            source_health["staleness"] = "future"
            warnings.append(f"{symbol}: future observation rejected at feature cutoff")
            unavailable.add(symbol)
        elif stale_local:
            status = "stale"
            reason = "local growth value is older than the official source latest date"
            source_health["upstream_collector_status"] = upstream_status or "success"
            source_health["collector_status"] = "stale"
            source_health["staleness"] = "local_old_value"
            warnings.append(
                f"{symbol}: local date {local_date} trails official date {official_date.isoformat()}"
            )
            unavailable.add(symbol)
        elif failure:
            status = upstream_status
            reason = str(source_health.get("reason") or ref.get("reason") or upstream_status)
            unavailable.add(symbol)
        else:
            status = "available"
            reason = str(source_health.get("reason") or "") or None

        previous_value = _float_or_none(ref.get("previous_value"))
        value = _float_or_none(point.get("value"))
        metrics[symbol] = GrowthMetric(
            symbol=symbol,
            label=_LABELS[symbol],
            status=status,
            value=value,
            unit=str(ref.get("metadata", {}).get("unit") or _UNITS[symbol]),
            observation_date=local_date,
            reference_period=str(ref.get("reference_period") or "") or None,
            previous_value=previous_value,
            previous_reference_period=str(ref.get("previous_reference_period") or "") or None,
            change=round(value - previous_value, 6) if value is not None and previous_value is not None else None,
            release_date=str(ref.get("release_date") or "") or None,
            release_time=str(ref.get("release_time") or "") or None,
            source_key=source_key,
            source_ref=ref,
            reason=reason,
        )
        health[source_key] = source_health

    ready_count = sum(metric.status == "available" for metric in metrics.values())
    result_status = "ready" if ready_count == len(GROWTH_SYMBOLS) else "partial"
    if ready_count == 0:
        result_status = "unavailable"
    return GrowthFeatureSnapshot(
        as_of=as_of,
        metrics=metrics,
        unavailable_symbols=sorted(unavailable),
        source_refs=refs_by_symbol,
        collector_health=health,
        warnings=list(dict.fromkeys(warnings)),
        status=result_status,
    )


def _source_ref_items(
    source_refs: Iterable[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    if isinstance(source_refs, Mapping):
        result: list[dict[str, Any]] = []
        for symbol, ref in source_refs.items():
            if isinstance(ref, Mapping):
                item = dict(ref)
                item.setdefault("symbol", symbol)
                result.append(item)
        return result
    return [dict(ref) for ref in (source_refs or ()) if isinstance(ref, Mapping)]


def _point_mapping(point: Mapping[str, Any] | object) -> dict[str, Any]:
    if isinstance(point, Mapping):
        return dict(point)
    to_dict = getattr(point, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        return dict(result) if isinstance(result, Mapping) else {}
    return {
        key: getattr(point, key)
        for key in ("symbol", "date", "value", "source", "source_url", "retrieved_at", "raw_path")
        if hasattr(point, key)
    }


def _parse_date(value: object) -> date:
    parsed = _date_or_none(value)
    if parsed is None:
        raise ValueError(f"invalid growth as_of date: {value!r}")
    return parsed


def _date_or_none(value: object) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_health_fields(ref: Mapping[str, Any]) -> bool:
    return any(
        key in ref
        for key in (
            "collector_status",
            "staleness",
            "expected_release_time",
            "actual_latest_date",
            "official_latest_date",
        )
    )


def _unavailable_status(upstream_status: str, health: Mapping[str, Any]) -> str:
    if upstream_status in {"auth_failed", "fetch_failed", "future_observation", "stale"}:
        return upstream_status
    if upstream_status == "not_published" or health.get("staleness") == "not_published":
        return "not_published"
    return "unavailable"
