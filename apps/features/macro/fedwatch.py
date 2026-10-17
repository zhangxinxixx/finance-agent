"""Deterministic features for the normalized free CME FedWatch snapshot.

Public interface
----------------
``build_fedwatch_health(snapshot, *, as_of, allowed_staleness_seconds=3600)``
returns source health (``fresh``, ``stale``, ``missing`` or ``parse_failed``).

``build_fedwatch_factors(snapshot, *, as_of, target_reference=None,
confirmation=None)`` returns three deliberately separate sections:

* ``official_policy`` validates the independently sourced target range;
* ``market_implied_path`` contains normalized marginal distributions and
  deterministic expectations; and
* ``repricing`` is a versioned heuristic based only on a same-meeting 1d/1w
  FedWatch comparison.  Confirmation data is reported separately and is
  never included in that score.

All rates and ranges are percentages, rate deltas are basis points, and
probability deltas are percentage points.  A missing official target does not
discard valid distributions, but target-relative fields remain ``None``.
This module has no database, storage, or network dependencies.
"""

from __future__ import annotations

from calendar import monthrange
from copy import deepcopy
from datetime import UTC, date, datetime
from math import isfinite
from typing import Any, Mapping
from urllib.parse import urlparse
from uuid import UUID

SCHEMA_VERSION = "fedwatch_factors.v1"
HEALTH_SCHEMA_VERSION = "fedwatch_health.v1"
REPRICING_RULE_VERSION = "fedwatch_repricing.v1"
EXPECTED_SOURCE = "cme_fedwatch_free"
WINDOWS = ("current", "1d", "1w", "1m")
COMPARISON_DAY_RANGES = {"1d": (1, 4), "1w": (5, 10), "1m": (21, 40)}
_EPSILON = 1e-9
STATE_PROBABILITY_FIELDS = {
    "cut": "prob_below_current_target",
    "hold": "prob_at_current_target",
    "hike": "prob_above_current_target",
}


class _ContractError(ValueError):
    """A normalized snapshot violates the shared contract."""


class _TargetError(ValueError):
    """An independently supplied official-policy reference is invalid."""


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise _ContractError(f"{field}_missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _ContractError(f"{field}_invalid") from exc
    if parsed.tzinfo is None:
        raise _ContractError(f"{field}_timezone_missing")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise _ContractError(f"{field}_invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise _ContractError(f"{field}_invalid") from exc
    if not isfinite(number):
        raise _ContractError(f"{field}_nonfinite")
    return number


def _source_refs(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or not all(isinstance(item, Mapping) and item for item in value):
        raise _ContractError("source_refs_missing")
    return [deepcopy(dict(item)) for item in value]


def _snapshot_lineage(snapshot: object) -> tuple[str | None, list[dict[str, Any]]]:
    if not isinstance(snapshot, Mapping):
        return None, []
    snapshot_id = snapshot.get("snapshot_id") if isinstance(snapshot.get("snapshot_id"), str) else None
    refs = snapshot.get("source_refs")
    if not isinstance(refs, list):
        return snapshot_id, []
    return snapshot_id, [deepcopy(dict(item)) for item in refs if isinstance(item, Mapping)]


def _validate_official_url(value: object) -> None:
    if not isinstance(value, str):
        raise _ContractError("source_url_invalid")
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise _ContractError("source_url_not_official_cme_https")


def _validate_distribution(rows: list[Mapping[str, Any]], *, meeting_date: str, window: str) -> dict[str, Any]:
    source_times: set[datetime] = set()
    bins: list[dict[str, Any]] = []
    contract_refs: set[str] = set()
    for row in rows:
        row_time = _timestamp(row.get("as_of"), "row_as_of")
        source_times.add(row_time)
        low = _finite_number(row.get("target_low"), "target_low")
        high = _finite_number(row.get("target_high"), "target_high")
        probability = _finite_number(row.get("probability"), "probability")
        if not -5 <= low < high <= 30 or high-low > 1:
            raise _ContractError("target_range_invalid")
        if probability < 0 or probability > 1:
            raise _ContractError("probability_out_of_range")
        contract_ref = row.get("contract_ref")
        if contract_ref is not None:
            if not isinstance(contract_ref, str) or not contract_ref:
                raise _ContractError("contract_ref_invalid")
            contract_refs.add(contract_ref)
        bins.append({"target_low": low, "target_high": high, "probability": probability})
    if len(source_times) != 1:
        raise _ContractError("window_source_time_inconsistent")
    bins.sort(key=lambda item: (item["target_low"], item["target_high"]))
    if any(abs(left["target_high"] - right["target_low"]) > _EPSILON for left, right in zip(bins, bins[1:])):
        raise _ContractError("probability_bins_overlap_or_gap")
    mass = sum(item["probability"] for item in bins)
    if mass < 0.99 - _EPSILON or mass > 1.01 + _EPSILON:
        raise _ContractError("probability_mass_outside_rounding_tolerance")
    normalized = abs(mass - 1.0) > _EPSILON
    for item in bins:
        item["probability"] /= mass
    expected = sum((item["target_low"] + item["target_high"]) / 2 * item["probability"] for item in bins)
    return {
        "meeting_date": meeting_date,
        "comparison_window": window,
        "source_as_of": _iso(next(iter(source_times))),
        "contract_refs": sorted(contract_refs),
        "input_probability_mass": mass,
        "normalization_applied": normalized,
        "bins": bins,
        "expected_rate_pct": expected,
    }


def _validated_snapshot(snapshot: object, *, evaluation_time: datetime) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        raise _ContractError("snapshot_missing")
    if not isinstance(snapshot.get("source"), str) or not snapshot.get("source"):
        raise _ContractError("source_invalid")
    try:
        UUID(str(snapshot.get("snapshot_id")))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _ContractError("snapshot_id_invalid") from exc
    if snapshot.get("parse_status") != "ok":
        raise _ContractError("snapshot_not_parsed")
    _validate_official_url(snapshot.get("source_url"))
    refs = _source_refs(snapshot.get("source_refs"))
    collected_at = _timestamp(snapshot.get("collected_at"), "collected_at")
    if collected_at > evaluation_time:
        raise _ContractError("collected_at_in_future")
    rows = snapshot.get("rows")
    if not isinstance(rows, list) or not rows:
        raise _ContractError("rows_missing")

    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise _ContractError("row_invalid")
        try:
            meeting = date.fromisoformat(str(row.get("meeting_date")))
        except ValueError as exc:
            raise _ContractError("meeting_date_invalid") from exc
        window = row.get("comparison_window")
        if window not in WINDOWS:
            raise _ContractError("comparison_window_invalid")
        grouped.setdefault((meeting.isoformat(), str(window)), []).append(row)

    distributions = {
        key: _validate_distribution(group_rows, meeting_date=key[0], window=key[1])
        for key, group_rows in grouped.items()
    }
    meeting_dates = sorted({meeting for meeting, _ in distributions})
    if any((meeting, "current") not in distributions for meeting in meeting_dates):
        raise _ContractError("current_distribution_missing")
    current_times = {_timestamp(distributions[(meeting, "current")]["source_as_of"], "current_as_of") for meeting in meeting_dates}
    oldest_time, current_time = min(current_times), max(current_times)
    if len(current_times) != 1:
        window = (snapshot.get("coverage") or {}).get("source_time_window") or {}
        span = (current_time - oldest_time).total_seconds()
        if (snapshot.get("transport") not in {"native_chromium_direct", "curl_cffi_webforms"} or span > 60
                or _timestamp(window.get("start"), "source_window_start") != oldest_time
                or _timestamp(window.get("end"), "source_window_end") != current_time):
            raise _ContractError("current_source_time_inconsistent")
    if current_time > evaluation_time or current_time > collected_at:
        raise _ContractError("source_time_in_future")
    if any(date.fromisoformat(meeting) < current_time.date() for meeting in meeting_dates):
        raise _ContractError("past_meeting_in_current_distribution")
    snapshot_as_of = snapshot.get("as_of")
    if snapshot_as_of is not None and _timestamp(snapshot_as_of, "snapshot_as_of") != current_time:
        raise _ContractError("snapshot_as_of_mismatch")

    comparison_meta: dict[tuple[str, str], dict[str, Any]] = {}
    for (meeting, window), distribution in distributions.items():
        if window == "current":
            continue
        previous = _timestamp(distribution["source_as_of"], "comparison_as_of")
        meeting_time = _timestamp(distributions[(meeting, "current")]["source_as_of"], "current_as_of")
        if previous >= meeting_time:
            raise _ContractError("comparison_time_not_before_current")
        elapsed_days = (meeting_time.date() - previous.date()).days
        minimum, maximum = COMPARISON_DAY_RANGES[window]
        if not minimum <= elapsed_days <= maximum:
            raise _ContractError(f"{window}_elapsed_calendar_days_invalid")
        comparison_meta[(meeting, window)] = {
            "elapsed_calendar_days": elapsed_days,
            "elapsed_seconds": (meeting_time - previous).total_seconds(),
            "elapsed_label": f"{elapsed_days}_calendar_days",
            "calendar_basis": (
                "source_labeled_trading_lookback; actual source timestamps retained; "
                "1d permits 1-4 calendar days only for weekend/common-holiday closures"
            ),
        }

    return {
        "snapshot_id": str(snapshot["snapshot_id"]),
        "source_refs": refs,
        "collected_at": collected_at,
        "source_as_of": current_time,
        "oldest_source_as_of": oldest_time,
        "distributions": distributions,
        "meeting_dates": meeting_dates,
        "comparison_meta": comparison_meta,
    }


def _quality_summary(snapshot, validated):
    """Completeness is independent of age; archive proof must come from ingestion."""
    meetings = validated["meeting_dates"]
    distributions = validated["distributions"]
    coverage = snapshot.get("coverage") or {}
    missing = [{"meeting_date": meeting, "window": window, "availability": "not_provided"}
               for meeting in meetings for window in WINDOWS
               if (meeting, window) not in distributions]
    refs = [ref for ref in validated["source_refs"] if ref.get("raw_artifact_ref")]
    verification = [ref.get("hash_verified_at_ingestion") for ref in refs]
    verified = (all(v is True for v in verification) if verification and all(v is not None for v in verification)
                else None)
    all_tabs = coverage.get("all_future_meetings")
    quality = ("valid_partial_meetings" if all_tabs is False else
               "valid_partial_history" if missing else "valid_observed_distributions")
    return {
        "snapshot_id": validated["snapshot_id"],
        "source_observed_at": _iso(validated["source_as_of"]),
        "source_window_start": _iso(validated["oldest_source_as_of"]),
        "ingested_at": _iso(validated["collected_at"]),
        "meeting_count": len(meetings),
        "probability_row_count": len(snapshot["rows"]),
        "comparison_coverage": {window: sum((m, window) in distributions for m in meetings) for window in WINDOWS},
        "available_tab_count": coverage.get("available_tab_count"),
        "captured_tab_count": coverage.get("captured_tab_count"),
        "all_meeting_tabs_captured": all_tabs,
        "raw_response_count": sum(ref.get("capture_kind") == "http_response" for ref in refs),
        "raw_capture_count": len(refs),
        "raw_hash_verified": verified,
        "hash_verification_scope": "at_ingestion_not_continuous_audit" if verified is not None else "not_recorded",
        "quality_status": quality,
        "missing": missing,
    }


def build_fedwatch_health(
    snapshot: object,
    *,
    as_of: str,
    allowed_staleness_seconds: int = 3600,
) -> dict[str, Any]:
    """Validate source timing and return fail-closed FedWatch health."""

    snapshot_id, refs = _snapshot_lineage(snapshot)
    base = {
        "schema_version": HEALTH_SCHEMA_VERSION,
        "source": "fedwatch",
        "snapshot_id": snapshot_id,
        "status": "missing",
        "reason": "snapshot_missing",
        "actionable": False,
        "evaluated_at": as_of,
        "source_as_of": None,
        "collected_at": None,
        "age_seconds": None,
        "last_updated": None,
        "freshness_seconds": None,
        "allowed_staleness_seconds": allowed_staleness_seconds,
        "source_refs": refs,
        "quality_summary": None,
    }
    try:
        evaluation_time = _timestamp(as_of, "as_of")
    except _ContractError as exc:
        return {**base, "status": "parse_failed", "reason": str(exc)}
    if isinstance(allowed_staleness_seconds, bool) or not isinstance(allowed_staleness_seconds, int) or allowed_staleness_seconds < 0:
        return {**base, "evaluated_at": _iso(evaluation_time), "status": "parse_failed", "reason": "allowed_staleness_seconds_invalid"}
    if not isinstance(snapshot, Mapping) or not snapshot:
        return {**base, "evaluated_at": _iso(evaluation_time)}
    if snapshot.get("parse_status") == "missing":
        return {
            **base,
            "evaluated_at": _iso(evaluation_time),
            "reason": str(snapshot.get("reason") or "upstream_snapshot_missing"),
        }
    if snapshot.get("parse_status") == "parse_failed":
        return {
            **base,
            "evaluated_at": _iso(evaluation_time),
            "status": "parse_failed",
            "reason": str(snapshot.get("reason") or "upstream_parse_failed"),
        }
    try:
        validated = _validated_snapshot(snapshot, evaluation_time=evaluation_time)
    except _ContractError as exc:
        return {
            **base,
            "evaluated_at": _iso(evaluation_time),
            "status": "parse_failed",
            "reason": str(exc),
        }
    age = (evaluation_time - validated["oldest_source_as_of"]).total_seconds()
    status = "fresh" if age <= allowed_staleness_seconds else "stale"
    return {
        **base,
        "snapshot_id": validated["snapshot_id"],
        "status": status,
        "reason": None if status == "fresh" else "source_stale",
        "actionable": status == "fresh",
        "evaluated_at": _iso(evaluation_time),
        "source_as_of": _iso(validated["source_as_of"]),
        "collected_at": _iso(validated["collected_at"]),
        "age_seconds": age,
        "last_updated": _iso(validated["source_as_of"]),
        "freshness_seconds": age,
        "source_refs": validated["source_refs"],
        "quality_summary": _quality_summary(snapshot, validated),
    }


def _official_policy(
    target_reference: object,
    *,
    source_as_of: datetime,
    evaluation_time: datetime,
) -> tuple[dict[str, Any], tuple[float, float] | None, bool]:
    if target_reference is None:
        return (
            {
                "status": "missing",
                "reason": "official_target_missing",
                "lower": None,
                "upper": None,
                "midpoint": None,
                "rate_unit": "percent",
                "effective_at": None,
                "published_at": None,
                "source_refs": [],
            },
            None,
            False,
        )
    try:
        if not isinstance(target_reference, Mapping):
            raise _TargetError("official_target_invalid")
        if target_reference.get("rate_unit") != "percent":
            raise _TargetError("official_target_rate_unit_invalid")
        lower = _finite_number(target_reference.get("lower"), "official_target_lower")
        upper = _finite_number(target_reference.get("upper"), "official_target_upper")
        if lower >= upper:
            raise _TargetError("official_target_range_invalid")
        effective_at = _timestamp(target_reference.get("effective_at"), "official_target_effective_at")
        published_at = _timestamp(target_reference.get("published_at"), "official_target_published_at")
        refs = _source_refs(target_reference.get("source_refs"))
        if max(effective_at, published_at) > source_as_of or max(effective_at, published_at) > evaluation_time:
            raise _TargetError("official_target_not_effective_at_snapshot")
        result = {
            "status": "available",
            "reason": None,
            "lower": lower,
            "upper": upper,
            "midpoint": (lower + upper) / 2,
            "rate_unit": "percent",
            "effective_at": _iso(effective_at),
            "published_at": _iso(published_at),
            "source_refs": refs,
            "timestamp_precision": target_reference.get("timestamp_precision", "second"),
            "availability_convention": target_reference.get("availability_convention"),
        }
        return result, (lower, upper), False
    except (_ContractError, _TargetError) as exc:
        return (
            {
                "status": "invalid",
                "reason": str(exc),
                "lower": None,
                "upper": None,
                "midpoint": None,
                "rate_unit": "percent",
                "effective_at": None,
                "published_at": None,
                "source_refs": [],
            },
            None,
            True,
        )


def _classify_distribution(distribution: dict[str, Any], target: tuple[float, float] | None) -> dict[str, Any]:
    result = deepcopy(distribution)
    result["implied_target_midpoint_expected_rate"] = result["expected_rate_pct"]
    result.update({field: None for field in STATE_PROBABILITY_FIELDS.values()})
    result["expected_change_bp"] = None
    result["equivalent_cumulative_25bp"] = None
    result["expected_cuts_25bp"] = None
    result["expected_hikes_25bp"] = None
    result["cut_probability"] = None
    result["hold_probability"] = None
    result["hike_probability"] = None
    if target is None:
        return result
    target_low, target_high = target
    probabilities = {"cut": 0.0, "hold": 0.0, "hike": 0.0}
    classified_bins = []
    for item in result["bins"]:
        low, high = item["target_low"], item["target_high"]
        if high <= target_low + _EPSILON:
            classification = "cut"
        elif low >= target_high - _EPSILON:
            classification = "hike"
        elif abs(low - target_low) <= _EPSILON and abs(high - target_high) <= _EPSILON:
            classification = "hold"
        else:
            raise _TargetError("probability_bin_crosses_official_target_boundary")
        probabilities[classification] += item["probability"]
        classified_bins.append({**item, "policy_classification": classification})
    expected_change = (result["expected_rate_pct"] - (target_low + target_high) / 2) * 100
    result.update(
        bins=classified_bins,
        expected_change_bp=expected_change,
        equivalent_cumulative_25bp=expected_change / 25,
        expected_cuts_25bp=sum(max(0, ((target_low+target_high)/2 - (b["target_low"]+b["target_high"])/2)*100/25)*b["probability"] for b in result["bins"]),
        expected_hikes_25bp=sum(max(0, ((b["target_low"]+b["target_high"])/2 - (target_low+target_high)/2)*100/25)*b["probability"] for b in result["bins"]),
        cut_probability=probabilities["cut"],
        hold_probability=probabilities["hold"],
        hike_probability=probabilities["hike"],
    )
    result.update({field: probabilities[label] for label, field in STATE_PROBABILITY_FIELDS.items()})
    return result


def _comparison_delta(
    current: dict[str, Any],
    previous: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    result = {
        "comparison_window": previous["comparison_window"],
        "current_source_as_of": current["source_as_of"],
        "comparison_source_as_of": previous["source_as_of"],
        **metadata,
        "expected_rate_delta_bp": (current["expected_rate_pct"] - previous["expected_rate_pct"]) * 100,
        "cut_probability_delta_pp": None,
        "hold_probability_delta_pp": None,
        "hike_probability_delta_pp": None,
        "bin_probability_deltas_pp": [],
        "expected_change_delta_bp": (current["expected_rate_pct"] - previous["expected_rate_pct"]) * 100 if current["expected_change_bp"] is not None else None,
        "target_comparison_basis": "both_distributions_relative_to_current_official_target",
    }
    current_bins = {(item["target_low"], item["target_high"]): item["probability"] for item in current["bins"]}
    previous_bins = {(item["target_low"], item["target_high"]): item["probability"] for item in previous["bins"]}
    for low, high in sorted(set(current_bins) | set(previous_bins)):
        result["bin_probability_deltas_pp"].append(
            {
                "target_low": low,
                "target_high": high,
                "delta_pp": (current_bins.get((low, high), 0.0) - previous_bins.get((low, high), 0.0)) * 100,
            }
        )
    if current["cut_probability"] is not None and previous["cut_probability"] is not None:
        for label in ("cut", "hold", "hike"):
            result[f"{label}_probability_delta_pp"] = (
                current[f"{label}_probability"] - previous[f"{label}_probability"]
            ) * 100
    for label, field in STATE_PROBABILITY_FIELDS.items():
        result[field + "_delta_pp"] = result[f"{label}_probability_delta_pp"]
    return result


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _horizon(meetings: list[dict[str, Any]], source_day: date, months: int) -> dict[str, Any]:
    target_day = _add_months(source_day, months)
    candidates = [row for row in meetings if date.fromisoformat(row["meeting_date"]) <= target_day]
    selected = candidates[-1] if candidates and (target_day - date.fromisoformat(candidates[-1]["meeting_date"])).days <= 62 else None
    return {
        "status": "covered" if selected else "unavailable",
        "target_date": target_day.isoformat(),
        "selected_meeting": selected,
        "selected_meeting_date": selected["meeting_date"] if selected else None,
        "gap_days": (target_day - date.fromisoformat(selected["meeting_date"])).days if selected else None,
        "selection_basis": "latest_scheduled_meeting_on_or_before_horizon; not_an_exact_horizon_observation",
    }


def _coverage(meetings: list[dict[str, Any]], source_day: date) -> dict[str, Any]:
    year_rows = [row for row in meetings if row["meeting_date"].startswith(f"{source_day.year}-12")]
    return {
        "next_meeting": meetings[0] if meetings else None,
        "next_two": meetings[:2],
        "next_three": meetings[:3],
        "year_end": year_rows[-1] if year_rows else None,
        "horizon12m": _horizon(meetings, source_day, 12),
        "horizons": {"6m": _horizon(meetings, source_day, 6), "3m": _horizon(meetings, source_day, 3), "12m": _horizon(meetings, source_day, 12)},
        "coverage": {
            "next_meeting": "covered" if meetings else "missing",
            "next_two": "covered" if len(meetings) >= 2 else "partial" if meetings else "missing",
            "next_three": "covered" if len(meetings) >= 3 else "partial" if meetings else "missing",
            "year_end": "covered" if year_rows else "missing_for_source_calendar_year",
            "horizon12m": _horizon(meetings, source_day, 12)["status"],
        },
    }


def _repricing(meetings, *, health, target_invalid):
    base = {"status": "unavailable", "reason": "same_meeting_comparison_missing",
            "direction": None, "strength": None, "score": None, "drivers": [],
            "meeting_focus": None, "as_of": health.get("source_as_of"),
            "rule_version": REPRICING_RULE_VERSION,
            "interpretation": "versioned heuristic, not calibrated economic truth",
            "confirmation_included_in_score": False,
            "delta_1d_bp": None, "delta_1w_bp": None, "delta_1m_bp": None}
    if health.get("status") != "fresh" or target_invalid or not meetings:
        return {**base, "reason": "source_stale_or_target_invalid_or_meetings_missing"}
    year = str(health["source_as_of"])[:4]
    terminal = next((m for m in reversed(meetings) if m["meeting_date"].startswith(year + "-12")), None)
    focus = {"next_meeting": meetings[0]}
    if terminal is not None and terminal["meeting_date"] != meetings[0]["meeting_date"]:
        focus["year_end"] = terminal
    drivers = []
    for horizon, meeting in focus.items():
        for window in ("1d", "1w"):
            delta = meeting["comparisons"].get(window)
            if delta:
                drivers.append({"horizon": horizon, "meeting_date": meeting["meeting_date"],
                                "comparison_window": window, **deepcopy(delta),
                                "weight": 1.0 if window == "1d" else 0.75})
    if not drivers:
        return base
    score = sum(max(-1., min(1., d["expected_rate_delta_bp"] / 25)) * d["weight"] for d in drivers) / sum(d["weight"] for d in drivers)
    positive = any(d["expected_rate_delta_bp"] >= 1 for d in drivers)
    negative = any(d["expected_rate_delta_bp"] <= -1 for d in drivers)
    conflicting = positive and negative
    direction = "neutral" if conflicting or abs(score) < .04 else "hawkish" if score > 0 else "dovish"
    dominant = max(drivers, key=lambda d: abs(d["expected_rate_delta_bp"]))
    selected = focus[dominant["horizon"]]
    next_delta = meetings[0]["comparisons"].get(dominant["comparison_window"], {}).get("expected_rate_delta_bp")
    year_delta = terminal["comparisons"].get(dominant["comparison_window"], {}).get("expected_rate_delta_bp") if terminal else None
    pattern = "insufficient_curve_coverage"
    if next_delta is not None and year_delta is not None:
        if conflicting:
            pattern = "mixed_path_shift"
        elif abs(next_delta) < 1 and abs(year_delta) >= 1:
            pattern = "year_end_terminal_repricing"
        elif abs(year_delta) < 1 and abs(next_delta) >= 1:
            pattern = "front_end_repricing"
        elif abs(next_delta - year_delta) < 3 and abs(next_delta) >= 1:
            pattern = "parallel_path_shift"
        elif abs(next_delta) >= 1:
            pattern = "non_parallel_path_shift"
        else:
            pattern = "no_material_repricing"
    return {**base, "status": "available", "reason": "conflicting_windows" if conflicting else None,
            "direction": direction, "strength": "weak" if abs(score) < 1/3 else "medium" if abs(score) < 2/3 else "strong",
            "score": score, "score_scale": "-1_dovish_to_+1_hawkish", "drivers": drivers,
            "meeting_focus": selected["meeting_date"], "focus_horizon": dominant["horizon"],
            "path_pattern": pattern, "conflicting_evidence": conflicting,
            **{"delta_" + w + "_bp": selected["comparisons"].get(w, {}).get("expected_rate_delta_bp") for w in ("1d", "1w", "1m")}}


def _confirmation(
    confirmation: object,
    *,
    evaluation_time: datetime,
    repricing_direction: str | None,
    repricing_drivers: list | None = None,
) -> dict[str, Any]:
    aliases = {"two_year": ("two_year", "change_bp"), "2y": ("two_year", "change_bp"), "real10y": ("real10y", "change_bp"), "dollar": ("dollar", "change_pct"), "dxy": ("dollar", "change_pct")}
    result = {"status": "missing", "included_in_repricing_score": False, "items": {}}
    if confirmation is None:
        return result
    if not isinstance(confirmation, Mapping):
        return {**result, "status": "invalid", "reason": "confirmation_invalid"}
    for supplied_key, item in confirmation.items():
        if supplied_key not in aliases:
            continue
        canonical, value_field = aliases[supplied_key]
        if canonical in result["items"]:
            result["items"][canonical] = {"status": "invalid", "reason": "duplicate_confirmation_alias", "included_in_repricing_score": False}
            continue
        try:
            if not isinstance(item, Mapping):
                raise _ContractError("confirmation_item_invalid")
            observed_at = _timestamp(item.get("as_of", item.get("observed_at")), "confirmation_as_of")
            max_age = item.get("max_age_seconds", 86400)
            if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age < 0:
                raise _ContractError("confirmation_max_age_invalid")
            if observed_at > evaluation_time:
                raise _ContractError("confirmation_in_future")
            age = (evaluation_time - observed_at).total_seconds()
            if age > max_age:
                result["items"][canonical] = {
                    "status": "stale",
                    "reason": "confirmation_stale",
                    "as_of": _iso(observed_at),
                    "age_seconds": age,
                    "included_in_repricing_score": False,
                    "source_refs": deepcopy(item.get("source_refs", [])),
                }
                continue
            value = _finite_number(item.get(value_field), f"confirmation_{value_field}")
            refs = _source_refs(item.get("source_refs"))
            signal = "up" if value > 0 else "down" if value < 0 else "flat"
            aligned = None
            matched = any(item.get("window_start") == d.get("comparison_source_as_of")
                          and item.get("window_end") == d.get("current_source_as_of")
                          for d in (repricing_drivers or []))
            if matched and repricing_direction in {"hawkish", "dovish"}:
                aligned = (repricing_direction == "hawkish" and value > 0) or (repricing_direction == "dovish" and value < 0)
            result["items"][canonical] = {
                "status": "available",
                "as_of": _iso(observed_at),
                "age_seconds": age,
                value_field: value,
                "signal": signal,
                "aligned_with_repricing": aligned,
                "window_aligned": matched,
                "comparison_reason": None if matched else "matching_policy_repricing_window_unverified",
                "included_in_repricing_score": False,
                "source_refs": refs,
            }
        except _ContractError as exc:
            result["items"][canonical] = {"status": "invalid", "reason": str(exc), "included_in_repricing_score": False}
    if result["items"]:
        statuses = {item["status"] for item in result["items"].values()}
        result["status"] = "available" if statuses == {"available"} else "partial" if "available" in statuses else "unavailable"
    return result


def build_fedwatch_factors(
    snapshot: object,
    *,
    as_of: str,
    target_reference: object = None,
    confirmation: object = None,
    allowed_staleness_seconds: int = 3600,
) -> dict[str, Any]:
    """Build normalized FedWatch distributions, horizons, and repricing."""

    snapshot_id, refs = _snapshot_lineage(snapshot)
    health = build_fedwatch_health(snapshot, as_of=as_of, allowed_staleness_seconds=allowed_staleness_seconds)
    base = {
        "schema_version": SCHEMA_VERSION,
        "factor_version": SCHEMA_VERSION,
        "status": "unavailable",
        "reason": health["reason"],
        "source": EXPECTED_SOURCE,
        "snapshot_id": snapshot_id,
        "as_of": as_of,
        "source_as_of": health.get("source_as_of"),
        "source_refs": refs,
        "health": health,
        "official_policy": {
            "status": "missing",
            "reason": "official_target_not_evaluated",
            "lower": None,
            "upper": None,
            "midpoint": None,
            "rate_unit": "percent",
            "effective_at": None,
            "published_at": None,
            "source_refs": [],
        },
        "market_implied_path": {"status": "unavailable", "reason": health["reason"], "meetings": []},
        "repricing": {
            "status": "unavailable",
            "reason": "fedwatch_distribution_unavailable",
            "direction": None,
            "strength": None,
            "score": None,
            "drivers": [],
            "meeting_focus": None,
            "as_of": health.get("source_as_of"),
            "rule_version": REPRICING_RULE_VERSION,
            "confirmation_included_in_score": False,
        },
        "confirmation": {"status": "missing", "included_in_repricing_score": False, "items": {}},
        "warnings": [],
    }
    try:
        evaluation_time = _timestamp(as_of, "as_of")
    except _ContractError:
        return base
    if health["status"] in {"missing", "parse_failed"}:
        return {**base, "as_of": _iso(evaluation_time)}
    try:
        validated = _validated_snapshot(snapshot, evaluation_time=evaluation_time)
    except _ContractError:
        return {**base, "as_of": _iso(evaluation_time)}

    official, target, target_invalid = _official_policy(
        target_reference,
        source_as_of=validated["source_as_of"],
        evaluation_time=evaluation_time,
    )
    classified: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        for key, distribution in validated["distributions"].items():
            classified[key] = _classify_distribution(distribution, target)
    except _TargetError as exc:
        official = {**official, "status": "invalid", "reason": str(exc), "lower": None, "upper": None, "midpoint": None}
        target = None
        target_invalid = True
        classified = {key: _classify_distribution(distribution, None) for key, distribution in validated["distributions"].items()}

    meetings = []
    for meeting_date in validated["meeting_dates"]:
        current = classified[(meeting_date, "current")]
        current["comparisons"] = {}
        for window in ("1d", "1w", "1m"):
            key = (meeting_date, window)
            if key in classified:
                current["comparisons"][window] = _comparison_delta(
                    current,
                    classified[key],
                    validated["comparison_meta"][key],
                )
        meetings.append(current)

    path = {
        "status": "available",
        "probability_semantics": "marginal_target_range_relative_to_current_official_target_not_meeting_action",
        "legacy_probability_aliases": {label + "_probability": field for label, field in STATE_PROBABILITY_FIELDS.items()},
        "expected_rate_definition": "probability_weighted_target_range_midpoint_percent_not_EFFR",
        "meeting_action_probabilities": {"status": "unavailable", "reason": "joint_transition_distribution_not_available"},
        "reason": None,
        "rate_unit": "percent",
        "probability_unit": "fraction",
        "delta_rate_unit": "basis_points",
        "delta_probability_unit": "percentage_points",
        "source_as_of": _iso(validated["source_as_of"]),
        "meetings": meetings,
        **_coverage(meetings, validated["source_as_of"].date()),
    }
    repricing = _repricing(meetings, health=health, target_invalid=target_invalid)
    confirmations = _confirmation(
        confirmation,
        evaluation_time=evaluation_time,
        repricing_direction=repricing["direction"],
        repricing_drivers=repricing["drivers"],
    )
    warnings = []
    if official["status"] == "missing":
        warnings.append("official_target_missing; target-relative fields unavailable")
    elif official["status"] == "invalid":
        warnings.append("official_target_invalid; target-relative fields and directional repricing unavailable")
    for meeting in meetings:
        missing_windows = [window for window in ("1d", "1w", "1m") if window not in meeting["comparisons"]]
        if missing_windows:
            warnings.append(f"{meeting['meeting_date']}:missing_comparison_windows:{','.join(missing_windows)}")
    if health["status"] == "stale":
        warnings.append("fedwatch_source_stale; repricing_not_actionable")

    status = "available"
    reason = None
    if health["status"] == "stale":
        status, reason = "stale", "source_stale"
    elif official["status"] != "available":
        status, reason = "incomplete", official["reason"]
    return {
        **base,
        "status": status,
        "reason": reason,
        "snapshot_id": validated["snapshot_id"],
        "as_of": _iso(evaluation_time),
        "source_as_of": _iso(validated["source_as_of"]),
        "source_refs": validated["source_refs"] + official.get("source_refs", []),
        "official_policy": official,
        "market_implied_path": path,
        "repricing": repricing,
        "confirmation": confirmations,
        "warnings": warnings,
    }


def _view_time(value):
    return _timestamp(value, "view_time")


def build_fedwatch_view(observed, *, as_of, latest_attempt=None, settings=None):
    """Pure shared normalization for archived collectors and worker consumers."""
    settings = deepcopy(settings or {"allowed_staleness_seconds": 3600, "event_window": False})
    source = deepcopy(observed or latest_attempt or {})
    health = build_fedwatch_health(source, as_of=as_of,
                                   allowed_staleness_seconds=settings["allowed_staleness_seconds"])
    failed_attempt = (latest_attempt and latest_attempt.get("parse_status") != "ok"
                      and (not observed or _view_time(latest_attempt["collected_at"]) >= _view_time(observed["collected_at"])))
    if failed_attempt:
        health.update(status="stale" if observed else latest_attempt.get("parse_status", "missing"),
                      actionable=False,
                      reason="latest_collection_failed_cached_snapshot" if observed else latest_attempt.get("reason"))
    elif latest_attempt and observed and latest_attempt.get("snapshot_id") != observed.get("snapshot_id") and (
        _view_time(latest_attempt["collected_at"]) >= _view_time(observed["collected_at"])
    ):
        health.update(status="stale", actionable=False, reason="latest_collection_not_materialized")
    # The feature builder validates source values independently of this view.
    factor = build_fedwatch_factors(source, as_of=as_of, target_reference=source.get("target_reference"),
                                    allowed_staleness_seconds=settings["allowed_staleness_seconds"])
    if health["status"] != "fresh":
        factor["status"] = "degraded"
        repricing = dict(factor.get("repricing") or {})
        repricing.update(status="unavailable", direction=None, strength=None, score=None,
                         reason="fedwatch_" + health["status"])
        factor["repricing"] = repricing
    factor["health"] = deepcopy(health)
    path = factor.get("market_implied_path", {})
    complete = bool(path.get("next_meeting") and path.get("year_end") and all(
        all(w in m.get("comparisons", {}) for w in ("1d", "1w", "1m"))
        for m in path.get("meetings", [])))
    return {"schema_version": "fedwatch_view.v1", "as_of": source.get("as_of"),
            "evaluated_at": str(as_of), "snapshot_id": source.get("snapshot_id"),
            "source_health": health, "factor": factor, "source_refs": factor.get("source_refs", []),
            "quality_summary": health.get("quality_summary"),
            "next_meeting": path.get("next_meeting"), "year_end": path.get("year_end"),
            "repricing": factor.get("repricing"),
            "latest_attempt": {k: (latest_attempt or {}).get(k) for k in
                               ("snapshot_id", "collected_at", "parse_status", "reason")},
            "settings": settings, "coverage_status": "complete" if complete else "partial",
            "status": "available" if health["status"] == "fresh" and complete else "degraded"}
