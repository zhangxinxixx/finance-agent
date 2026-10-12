"""Pure Employment feature construction from normalized monthly points.

The builder performs only deterministic calendar arithmetic.  It does not
fetch data, infer a release date, estimate consensus, or write an artifact.
Those boundaries keep a BLS observation useful even when publication and
revision metadata are unavailable.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from apps.parsers.bls.employment import (
    BLS_ALL_SERIES,
    BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL,
    BLS_EMPLOYMENT_SERIES,
    BLS_INDUSTRY_SERIES,
    BLS_INDUSTRY_SERIES_SPECS,
    BLS_SERIES_SPECS,
    BLSSeriesSpec,
)

_MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_UNKNOWN_RELEASE_VALUES = frozenset({"", "unknown", "unavailable", "not_available", "n/a", "none"})
_EMPLOYMENT_SERIES = frozenset(BLS_EMPLOYMENT_SERIES)
_INDUSTRY_SERIES = frozenset(BLS_INDUSTRY_SERIES)
_ALL_EMPLOYMENT_SERIES = frozenset(BLS_ALL_SERIES)


def _empty_release_context() -> dict[str, object]:
    return {
        "status": "unavailable",
        "source_kind": None,
        "release_date_kind": None,
        "release_date": None,
        "release_time_local": None,
        "release_timezone": None,
        "release_datetime": None,
        "observation_month": None,
        "vintage_date": None,
        "previous_vintage_date": None,
        "baseline_kind": None,
        "headline": {
            "new_jobs_thousands": None,
            "unemployment_rate": None,
            "wage_mom_pct": None,
            "wage_yoy_pct": None,
        },
        "revisions": [],
        "sector_contributions": [],
        "missing_fields": ["official_release"],
        "parser_notes": [],
        "source_refs": [],
    }


class EmploymentFeatureError(ValueError):
    """Raised when normalized Employment points are ambiguous or invalid."""


@dataclass(frozen=True)
class EmploymentSourcePassport:
    """Provenance for one current or previous observation.

    ``release_date`` and ``vintage_status`` are explicit because the BLS
    response used here does not verify either value.  ``retrieved_at`` is the
    collection timestamp and is not presented as a publication timestamp.
    """

    source: str | None
    source_url: str | None
    raw_path: str | None
    retrieved_at: str | None
    observation_month: str | None
    release_date: str | None = None
    vintage_status: str = "unavailable"

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "source_url": self.source_url,
            "raw_path": self.raw_path,
            "retrieved_at": self.retrieved_at,
            "observation_month": self.observation_month,
            "release_date": self.release_date,
            "vintage_status": self.vintage_status,
        }


@dataclass(frozen=True)
class EmploymentMetric:
    """Current, previous, monthly, and exact year-over-year Employment data."""

    series_id: str
    label: str
    unit: str
    kind: str
    status: str
    unavailable_reason: str | None = None
    current_month: str | None = None
    current_value: float | None = None
    previous_month: str | None = None
    previous_value: float | None = None
    monthly_change: float | None = None
    monthly_change_pct: float | None = None
    new_jobs_thousands: float | None = None
    yoy_month: str | None = None
    yoy_value: float | None = None
    yoy_change: float | None = None
    yoy_change_pct: float | None = None
    current_source: EmploymentSourcePassport | None = None
    previous_source: EmploymentSourcePassport | None = None

    @property
    def current_source_passport(self) -> EmploymentSourcePassport | None:
        """Descriptive alias for callers that use the passport terminology."""

        return self.current_source

    @property
    def previous_source_passport(self) -> EmploymentSourcePassport | None:
        """Descriptive alias for callers that use the passport terminology."""

        return self.previous_source

    def to_dict(self) -> dict[str, object]:
        return {
            "series_id": self.series_id,
            "label": self.label,
            "unit": self.unit,
            "kind": self.kind,
            "status": self.status,
            "unavailable_reason": self.unavailable_reason,
            "current_month": self.current_month,
            "current_value": self.current_value,
            "previous_month": self.previous_month,
            "previous_value": self.previous_value,
            "monthly_change": self.monthly_change,
            "monthly_change_pct": self.monthly_change_pct,
            "new_jobs_thousands": self.new_jobs_thousands,
            "yoy_month": self.yoy_month,
            "yoy_value": self.yoy_value,
            "yoy_change": self.yoy_change,
            "yoy_change_pct": self.yoy_change_pct,
            "current_source": self.current_source.to_dict() if self.current_source else None,
            "previous_source": self.previous_source.to_dict() if self.previous_source else None,
        }


@dataclass(frozen=True)
class EmploymentFeatureSnapshot:
    """A deterministic Employment domain snapshot for a requested cutoff."""

    as_of: str
    cutoff_month: str
    metrics: dict[str, EmploymentMetric]
    unavailable_series: list[str]
    source_refs: dict[str, dict[str, object]] = field(default_factory=dict)
    release_date: str | None = None
    vintage_status: str = "unavailable"
    consensus: None = None
    release_context: dict[str, object] = field(default_factory=_empty_release_context)
    # Bounded CES industry levels are deliberately kept in their own domain;
    # this preserves the original four-metric ``metrics`` contract while
    # making the derived adjacent-month change explicit to downstream users.
    industry_employment: dict[str, EmploymentMetric] = field(default_factory=dict)
    industry_unavailable_series: list[str] = field(default_factory=list)

    @property
    def unavailable_symbols(self) -> list[str]:
        """Compatibility alias matching ``MacroSnapshot`` terminology."""

        return self.unavailable_series

    @property
    def new_jobs_thousands(self) -> float | None:
        metric = self.metrics.get("CES0000000001")
        return metric.new_jobs_thousands if metric else None

    @property
    def wage_mom(self) -> float | None:
        metric = self.metrics.get("CES0500000003")
        return metric.monthly_change if metric else None

    @property
    def wage_yoy(self) -> float | None:
        metric = self.metrics.get("CES0500000003")
        return metric.yoy_change if metric else None

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "cutoff_month": self.cutoff_month,
            "metrics": {symbol: metric.to_dict() for symbol, metric in self.metrics.items()},
            "unavailable_series": self.unavailable_series,
            "unavailable_symbols": self.unavailable_series,
            "source_refs": self.source_refs,
            "release_date": self.release_date,
            "vintage_status": self.vintage_status,
            "consensus": self.consensus,
            "release_context": self.release_context,
            "industry_employment": {
                symbol: metric.to_dict() for symbol, metric in self.industry_employment.items()
            },
            "industry_unavailable_series": self.industry_unavailable_series,
            "new_jobs_thousands": self.new_jobs_thousands,
            "wage_mom": self.wage_mom,
            "wage_yoy": self.wage_yoy,
        }


def build_employment_features(
    points: Iterable[Mapping[str, object] | object],
    *,
    as_of: str,
    unavailable_symbols: Iterable[str] | None = (),
    source_refs: Iterable[Mapping[str, object]] | Mapping[str, Mapping[str, object]] | None = (),
) -> EmploymentFeatureSnapshot:
    """Build the Employment domain from normalized ``MacroPoint``-like data.

    The previous observation is retained for traceability even when a month
    is missing.  ``monthly_change`` and ``new_jobs_thousands`` are populated
    only for adjacent calendar months; ``yoy_change`` uses the exact month
    twelve months earlier and is otherwise unavailable.
    """

    cutoff_month = _cutoff_month(as_of)
    source_ref_items = _source_ref_items(source_refs)
    refs_by_symbol = {
        symbol: ref
        for symbol, ref in _index_source_refs(source_ref_items).items()
        if symbol in _ALL_EMPLOYMENT_SERIES
    }
    release_ref = next(
        (
            ref
            for ref in source_ref_items
            if str(ref.get("symbol") or "") == BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL
        ),
        None,
    )
    release_context = _release_context_from_ref(release_ref)
    by_series: dict[str, dict[str, dict[str, object]]] = {}
    invalid_series: dict[str, str] = {}

    for raw_point in points:
        point = _point_mapping(raw_point)
        symbol = str(point.get("symbol") or "")
        if symbol not in _ALL_EMPLOYMENT_SERIES:
            continue
        try:
            observation_month = _point_month(point.get("date"))
            value = _point_value(point.get("value"))
        except EmploymentFeatureError as exc:
            invalid_series[symbol] = str(exc)
            continue
        normalized = dict(point)
        normalized["symbol"] = symbol
        normalized["observation_month"] = observation_month
        normalized["value"] = value
        previous = by_series.setdefault(symbol, {}).get(observation_month)
        if previous is not None and _point_identity(previous) != _point_identity(normalized):
            invalid_series[symbol] = f"conflicting duplicate observation for {observation_month}"
            continue
        by_series[symbol][observation_month] = normalized

    explicit_unavailable = {
        str(symbol)
        for symbol in (unavailable_symbols or ())
        if str(symbol) in _ALL_EMPLOYMENT_SERIES
    }
    unavailable_series = set(explicit_unavailable) & set(_EMPLOYMENT_SERIES)
    industry_unavailable_series = set(explicit_unavailable) & set(_INDUSTRY_SERIES)
    metrics: dict[str, EmploymentMetric] = {}
    for spec in BLS_SERIES_SPECS:
        series_id = spec.series_id
        observations = by_series.get(series_id, {})
        if series_id in invalid_series:
            metric = _unavailable_metric(spec, invalid_series[series_id])
        elif series_id in explicit_unavailable:
            metric = _unavailable_metric(spec, _unavailable_reason(refs_by_symbol.get(series_id)))
        else:
            metric = _build_metric(
                spec=spec,
                observations=observations,
                cutoff_month=cutoff_month,
                source_ref=refs_by_symbol.get(series_id),
            )
        metrics[series_id] = metric
        if metric.status != "available":
            unavailable_series.add(series_id)

    industry_employment: dict[str, EmploymentMetric] = {}
    for spec in BLS_INDUSTRY_SERIES_SPECS:
        series_id = spec.series_id
        observations = by_series.get(series_id, {})
        if series_id in invalid_series:
            metric = _unavailable_metric(spec, invalid_series[series_id])
        elif series_id in explicit_unavailable:
            metric = _unavailable_metric(spec, _unavailable_reason(refs_by_symbol.get(series_id)))
        else:
            metric = _build_metric(
                spec=spec,
                observations=observations,
                cutoff_month=cutoff_month,
                source_ref=refs_by_symbol.get(series_id),
            )
        industry_employment[series_id] = metric
        if metric.status != "available":
            industry_unavailable_series.add(series_id)

    return EmploymentFeatureSnapshot(
        as_of=as_of,
        cutoff_month=cutoff_month,
        metrics=metrics,
        unavailable_series=sorted(unavailable_series),
        source_refs=refs_by_symbol,
        release_date=_known_release_date(release_context.get("release_date")),
        release_context=release_context,
        industry_employment=industry_employment,
        industry_unavailable_series=sorted(industry_unavailable_series),
    )


def build_employment_snapshot(
    points: Iterable[Mapping[str, object] | object],
    *,
    as_of: str,
    unavailable_symbols: Iterable[str] | None = (),
    source_refs: Iterable[Mapping[str, object]] | Mapping[str, Mapping[str, object]] | None = (),
) -> EmploymentFeatureSnapshot:
    """Alias kept for feature callers that use the existing snapshot naming."""

    return build_employment_features(
        points,
        as_of=as_of,
        unavailable_symbols=unavailable_symbols,
        source_refs=source_refs,
    )


def _build_metric(
    *,
    spec: BLSSeriesSpec,
    observations: Mapping[str, dict[str, object]],
    cutoff_month: str,
    source_ref: Mapping[str, object] | None,
) -> EmploymentMetric:
    eligible_months = sorted(month for month in observations if month <= cutoff_month)
    if not eligible_months:
        return _unavailable_metric(spec, "no usable observation through cutoff")

    current_month = eligible_months[-1]
    current_point = observations[current_month]
    previous_month = eligible_months[-2] if len(eligible_months) > 1 else None
    previous_point = observations[previous_month] if previous_month else None
    current_value = _rounded(float(current_point["value"]))
    previous_value = _rounded(float(previous_point["value"])) if previous_point else None

    monthly_change = None
    monthly_change_pct = None
    new_jobs_thousands = None
    if previous_point and previous_month and _months_between(previous_month, current_month) == 1:
        monthly_change = _difference(current_value, previous_value)
        monthly_change_pct = _relative_change(current_value, previous_value)
        if spec.kind == "employment_level":
            # BLS CES employment is reported in thousands of persons.
            new_jobs_thousands = monthly_change

    yoy_month = _shift_month(current_month, -12)
    yoy_point = observations.get(yoy_month)
    yoy_value = _rounded(float(yoy_point["value"])) if yoy_point else None
    yoy_change = _difference(current_value, yoy_value)
    yoy_change_pct = _relative_change(current_value, yoy_value)

    return EmploymentMetric(
        series_id=spec.series_id,
        label=spec.label,
        unit=spec.unit,
        kind=spec.kind,
        status="available",
        current_month=current_month,
        current_value=current_value,
        previous_month=previous_month,
        previous_value=previous_value,
        monthly_change=monthly_change,
        monthly_change_pct=monthly_change_pct,
        new_jobs_thousands=new_jobs_thousands,
        yoy_month=yoy_month,
        yoy_value=yoy_value,
        yoy_change=yoy_change,
        yoy_change_pct=yoy_change_pct,
        current_source=_source_passport(current_point, source_ref, current_month),
        previous_source=_source_passport(previous_point, source_ref, previous_month),
    )


def _unavailable_metric(spec: BLSSeriesSpec, reason: str | None) -> EmploymentMetric:
    return EmploymentMetric(
        series_id=spec.series_id,
        label=spec.label,
        unit=spec.unit,
        kind=spec.kind,
        status="unavailable",
        unavailable_reason=reason or "series unavailable",
    )


def _source_passport(
    point: Mapping[str, object] | None,
    source_ref: Mapping[str, object] | None,
    observation_month: str | None,
) -> EmploymentSourcePassport | None:
    if point is None:
        return None
    source_ref = source_ref or {}
    return EmploymentSourcePassport(
        source=_optional_text(point.get("source")) or _optional_text(source_ref.get("source")),
        source_url=_optional_text(point.get("source_url")) or _optional_text(source_ref.get("source_url")),
        raw_path=_optional_text(point.get("raw_path")) or _optional_text(source_ref.get("raw_path")),
        retrieved_at=_optional_text(point.get("retrieved_at")) or _optional_text(source_ref.get("retrieved_at")),
        observation_month=observation_month,
        release_date=_known_release_date(point.get("release_date"))
        or _known_release_date(source_ref.get("release_date")),
        vintage_status=_optional_text(point.get("vintage_status"))
        or _optional_text(source_ref.get("vintage_status"))
        or "unavailable",
    )


def _index_source_refs(
    refs: Iterable[Mapping[str, object]] | Mapping[str, Mapping[str, object]] | None,
) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for fallback_symbol, ref in _source_ref_items(refs, include_fallback=True):
        if not isinstance(ref, Mapping):
            continue
        if fallback_symbol is not None:
            ref = {**ref, "symbol": ref.get("symbol") or fallback_symbol}
        symbol = str(ref.get("symbol") or fallback_symbol or "")
        if symbol:
            indexed[symbol] = dict(ref)
    return indexed


def _source_ref_items(
    refs: Iterable[Mapping[str, object]] | Mapping[str, Mapping[str, object]] | None,
    *,
    include_fallback: bool = False,
) -> list[dict[str, object]] | list[tuple[str | None, Mapping[str, object]]]:
    if refs is None:
        return [] if not include_fallback else []
    if isinstance(refs, Mapping):
        items = [(str(symbol), ref) for symbol, ref in refs.items() if isinstance(ref, Mapping)]
    else:
        items = [(None, ref) for ref in refs if isinstance(ref, Mapping)]
    if include_fallback:
        return items
    normalized: list[dict[str, object]] = []
    for fallback_symbol, ref in items:
        item = dict(ref)
        if fallback_symbol is not None and not item.get("symbol"):
            item["symbol"] = fallback_symbol
        normalized.append(item)
    return normalized


def _release_context_from_ref(ref: Mapping[str, object] | None) -> dict[str, object]:
    if ref is None:
        return _empty_release_context()
    nested = ref.get("release_context")
    context = dict(nested) if isinstance(nested, Mapping) else _empty_release_context()
    context.setdefault("status", str(ref.get("status") or "unavailable"))
    context.setdefault("source_kind", ref.get("source_kind") or ref.get("source"))
    context.setdefault("release_date_kind", ref.get("release_date_kind"))
    context.setdefault("vintage_date", ref.get("vintage_date"))
    context.setdefault("previous_vintage_date", ref.get("previous_vintage_date"))
    context.setdefault("baseline_kind", ref.get("baseline_kind"))
    context.setdefault("source_refs", [])
    if not context.get("source_refs"):
        context["source_refs"] = [
            {
                key: ref[key]
                for key in ("source", "source_url", "raw_path", "retrieved_at")
                if key in ref
            }
        ]
    if ref.get("reason") and not context.get("parser_notes"):
        context["parser_notes"] = [str(ref["reason"])]
    if ref.get("failure_kind"):
        context["failure_kind"] = ref["failure_kind"]
    return context


def _point_mapping(point: Mapping[str, object] | object) -> Mapping[str, object]:
    if isinstance(point, Mapping):
        return point
    to_dict = getattr(point, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, Mapping):
            return value
    raise EmploymentFeatureError("Employment point must be a mapping or expose to_dict()")


def _point_month(value: object) -> str:
    raw = str(value or "").strip()
    if len(raw) >= 7 and _MONTH_PATTERN.fullmatch(raw[:7]):
        return raw[:7]
    raise EmploymentFeatureError(f"invalid Employment observation date: {value!r}")


def _point_value(value: object) -> float:
    if value is None or isinstance(value, bool):
        raise EmploymentFeatureError("Employment observation has no numeric value")
    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise EmploymentFeatureError(f"Employment observation value is not numeric: {value!r}") from exc
    if not math.isfinite(numeric_value):
        raise EmploymentFeatureError("Employment observation value is not finite")
    return numeric_value


def _point_identity(point: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(point.get(field) for field in ("value", "source", "source_url", "raw_path", "retrieved_at"))


def _cutoff_month(as_of: str) -> str:
    if not isinstance(as_of, str):
        raise EmploymentFeatureError("as_of must be an ISO date string")
    try:
        parsed = date.fromisoformat(as_of)
    except ValueError as exc:
        raise EmploymentFeatureError(f"as_of must be YYYY-MM-DD: {as_of!r}") from exc
    if parsed.isoformat() != as_of:
        raise EmploymentFeatureError(f"as_of must be YYYY-MM-DD: {as_of!r}")
    return as_of[:7]


def _months_between(start: str, end: str) -> int:
    start_year, start_month = (int(value) for value in start.split("-"))
    end_year, end_month = (int(value) for value in end.split("-"))
    return (end_year - start_year) * 12 + end_month - start_month


def _shift_month(month: str, delta: int) -> str:
    year, month_number = (int(value) for value in month.split("-"))
    absolute_month = year * 12 + month_number - 1 + delta
    shifted_year, shifted_month = divmod(absolute_month, 12)
    return f"{shifted_year:04d}-{shifted_month + 1:02d}"


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return _normalize_zero(round(value, 6))


def _difference(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return _rounded(current - previous)


def _relative_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return _rounded((current - previous) / previous * 100.0)


def _normalize_zero(value: float) -> float:
    return 0.0 if value == 0 else value


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _known_release_date(value: object) -> str | None:
    text = _optional_text(value)
    if text is None or text.strip().lower() in _UNKNOWN_RELEASE_VALUES:
        return None
    return text


def _unavailable_reason(ref: Mapping[str, object] | None) -> str:
    if ref:
        reason = _optional_text(ref.get("reason"))
        if reason:
            return reason
    return "collector marked series unavailable"
