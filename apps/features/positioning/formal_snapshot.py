"""Pure, fail-closed CFTC COT input contract for Gold policy snapshots."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator


COT_SNAPSHOT_VERSION = "cot_snapshot.v1"
_CFTC_COT_PATH = re.compile(r"/files/dea/history/(?:fut|com)_disagg_txt_\d{4}\.zip")
_FUTURES_ONLY_CFTC_COT_PATH = re.compile(r"/files/dea/history/fut_disagg_txt_\d{4}\.zip")
_COMBINED_CFTC_COT_PATH = re.compile(r"/files/dea/history/com_disagg_txt_\d{4}\.zip")
_FRESH_AGE = timedelta(days=10)
_OBSERVE_AGE = timedelta(days=17)


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class COTSourceReference(_Frozen):
    """Typed provenance retained even when the COT observation is blocked."""

    source: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    raw_path: str | None = None
    retrieved_at: datetime
    qualification_reason: str

    @model_validator(mode="after")
    def _requires_aware_retrieval_time(self) -> "COTSourceReference":
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("COT source reference retrieved_at must be timezone-aware")
        if self.qualification_reason == "eligible" and (
            self.source != "cftc"
            or not _is_futures_only_cftc_cot_url(self.reference)
            or not self.raw_path
        ):
            raise ValueError("eligible COT source references require official CFTC raw lineage")
        return self


class COTObservation(_Frozen):
    series_id: Literal["GOLD_COT"] = "GOLD_COT"
    metric_kind: Literal["managed_money_net_contracts"] = "managed_money_net_contracts"
    value: float | None
    unit: Literal["contracts"] = "contracts"
    report_date: date | None
    expected_frequency: Literal["weekly"] = "weekly"
    freshness_status: Literal["fresh", "stale", "missing"]
    quality_status: Literal["accepted", "observe", "blocked"]
    alignment_status: Literal["aligned", "misaligned", "unknown"]
    source_refs: tuple[COTSourceReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _requires_explicit_missing_semantics(self) -> "COTObservation":
        if self.freshness_status == "missing":
            if self.value is not None or self.report_date is not None:
                raise ValueError("missing COT observation must not contain a value or report date")
        elif self.value is None or self.report_date is None:
            raise ValueError("present COT observation requires value and report date")
        return self


class COTSnapshot(_Frozen):
    schema_version: Literal["cot_snapshot.v1"] = COT_SNAPSHOT_VERSION
    as_of: datetime
    readiness: Literal["ready", "observe", "blocked"]
    managed_money_net: COTObservation

    @model_validator(mode="after")
    def _requires_aware_as_of_and_matching_readiness(self) -> "COTSnapshot":
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("COT snapshot as_of must be timezone-aware")
        expected = _readiness(self.managed_money_net)
        if self.readiness != expected:
            raise ValueError("COT snapshot readiness must match its observation")
        return self


def build_cot_snapshot(*, candidates: Iterable[Mapping[str, Any]], as_of: datetime) -> COTSnapshot:
    """Select one known CFTC managed-money net observation without inference.

    Candidate rows are intentionally narrow MacroPoint-shaped records.  Every
    candidate must independently satisfy the official CFTC identity and the
    point-in-time boundary; malformed rows are retained only as blocked lineage.
    """

    point_in_time = _aware_utc(as_of)
    rows = tuple(dict(candidate) for candidate in candidates)
    checked = tuple(_check_candidate(row, point_in_time) for row in rows)
    eligible = tuple(item for item in checked if item["eligible"])
    if not eligible:
        return _snapshot_from_observation(point_in_time, _missing(point_in_time, checked, "no_eligible_cot_candidate"))

    latest_date = max(item["report_date"] for item in eligible)
    latest = tuple(item for item in eligible if item["report_date"] == latest_date)
    values = {item["value"] for item in latest}
    sources = {(item["source"], item["reference"]) for item in latest}
    if len(values) != 1 or len(sources) != 1:
        return _snapshot_from_observation(point_in_time, _missing(point_in_time, latest, "ambiguous_latest_cot_candidate"))

    selected = latest[0]
    age = point_in_time.date() - selected["report_date"]
    if age <= _FRESH_AGE:
        freshness, quality = "fresh", "accepted"
    elif age <= _OBSERVE_AGE:
        freshness, quality = "stale", "observe"
    else:
        freshness, quality = "stale", "blocked"
    observation = COTObservation(
        value=selected["value"], report_date=selected["report_date"],
        freshness_status=freshness, quality_status=quality, alignment_status="aligned",
        source_refs=_deduplicated_refs(item["source_ref"] for item in latest),
    )
    return _snapshot_from_observation(point_in_time, observation)


def _check_candidate(row: Mapping[str, Any], as_of: datetime) -> dict[str, Any]:
    source = str(row.get("source") or "")
    reference = str(row.get("source_url") or "")
    raw_path = row.get("raw_path")
    raw_path_text = str(raw_path).strip() if raw_path is not None else ""
    retrieved_at = _parse_time(row.get("retrieved_at"))
    report_date = _parse_date(row.get("date"))
    value = _finite_number(row.get("value"))
    reason = "eligible"
    if row.get("symbol") != "COT_GOLD_noncomm_net":
        reason = "wrong_symbol"
    elif source != "cftc":
        reason = "wrong_source"
    elif not _is_futures_only_cftc_cot_url(reference):
        reason = "wrong_source_url"
    elif not raw_path_text:
        reason = "raw_path_missing"
    elif retrieved_at is None:
        reason = "retrieval_time_missing_or_naive"
    elif retrieved_at > as_of:
        reason = "retrieval_time_after_as_of"
    elif report_date is None:
        reason = "report_date_invalid"
    elif report_date > as_of.date():
        reason = "report_date_after_as_of"
    elif value is None:
        reason = "value_invalid"
    source_ref = (
        COTSourceReference(
            source=source or "cot_snapshot_query", reference=reference or f"query://COT_GOLD/noncomm_net/{reason}",
            raw_path=raw_path_text or None, retrieved_at=retrieved_at, qualification_reason=reason,
        )
        if retrieved_at is not None
        else COTSourceReference(
            source="cot_snapshot_query", reference="query://COT_GOLD/noncomm_net",
            retrieved_at=as_of, qualification_reason=reason,
        )
    )
    return {
        "eligible": reason == "eligible", "reason": reason,
        "source": source, "reference": reference, "value": value,
        "report_date": report_date, "source_ref": source_ref,
    }


def _missing(as_of: datetime, checked: Iterable[Mapping[str, Any]], reason: str) -> COTObservation:
    checked_rows = tuple(checked)
    refs = tuple(
        item["source_ref"].model_copy(update={"qualification_reason": reason})
        if item["reason"] == "eligible" else item["source_ref"]
        for item in checked_rows
    )
    if not refs:
        refs = (COTSourceReference(
            source="cot_snapshot_query", reference="query://COT_GOLD/noncomm_net",
            retrieved_at=as_of, qualification_reason=reason,
        ),)
    return COTObservation(
        value=None, report_date=None, freshness_status="missing", quality_status="blocked",
        alignment_status=(
            "misaligned"
            if any(
                item["reason"] in {"retrieval_time_after_as_of", "report_date_after_as_of"}
                for item in checked_rows
            )
            else "unknown"
        ),
        source_refs=refs,
    )


def _snapshot_from_observation(as_of: datetime, observation: COTObservation) -> COTSnapshot:
    return COTSnapshot(
        as_of=as_of,
        readiness=_readiness(observation), managed_money_net=observation,
    )


def _readiness(observation: COTObservation) -> Literal["ready", "observe", "blocked"]:
    if observation.quality_status == "blocked" or observation.alignment_status == "misaligned":
        return "blocked"
    if observation.quality_status == "observe" or observation.freshness_status == "stale" or observation.alignment_status == "unknown":
        return "observe"
    return "ready"


def _deduplicated_refs(refs: Iterable[COTSourceReference]) -> tuple[COTSourceReference, ...]:
    unique = {
        (ref.source, ref.reference, ref.raw_path, ref.retrieved_at, ref.qualification_reason): ref
        for ref in refs
    }
    return tuple(unique[key] for key in sorted(unique))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("COT snapshot as_of must be timezone-aware")
    return value.astimezone(UTC)


def _parse_time(value: object) -> datetime | None:
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


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _is_cftc_cot_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "www.cftc.gov"
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and _CFTC_COT_PATH.fullmatch(parsed.path) is not None
    )


def _is_futures_only_cftc_cot_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "www.cftc.gov"
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and _FUTURES_ONLY_CFTC_COT_PATH.fullmatch(parsed.path) is not None
    )


# ---------------------------------------------------------------------------
# Full disaggregated report contract
# ---------------------------------------------------------------------------


COT_POSITIONING_SNAPSHOT_VERSION = "cot_positioning_snapshot.v1"
COT_REPORT_TYPES = ("futures_only", "combined")


class COTPositioningSourceReference(_Frozen):
    """Lineage for a full CFTC report, including the ZIP and filtered rows."""

    source: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    raw_path: str | None = None
    raw_archive_path: str | None = None
    retrieved_at: datetime
    report_type: Literal["futures_only", "combined"]
    qualification_reason: str

    @model_validator(mode="after")
    def _validate_lineage(self) -> "COTPositioningSourceReference":
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("COT positioning retrieved_at must be timezone-aware")
        if self.qualification_reason == "eligible" and (
            self.source != "cftc"
            or not _is_cftc_cot_url_for_report_type(self.reference, self.report_type)
            or not self.raw_path
            or not self.raw_archive_path
        ):
            raise ValueError("eligible COT positioning references require official CFTC ZIP and filtered raw lineage")
        return self


class COTLongShortNet(_Frozen):
    """One CFTC category's long, short and net contracts."""

    long: float | None
    short: float | None
    net: float | None
    unit: Literal["contracts"] = "contracts"

    @model_validator(mode="after")
    def _net_matches_long_short(self) -> "COTLongShortNet":
        if self.long is None or self.short is None:
            if self.net is not None:
                raise ValueError("COT net requires both long and short")
            return self
        if self.net is None or not math.isclose(self.net, self.long - self.short, abs_tol=1e-6):
            raise ValueError("COT net must equal long minus short")
        return self


class COTSeries(_Frozen):
    """Latest, actual previous report and arithmetic delta for one category."""

    latest: COTLongShortNet
    previous: COTLongShortNet | None = None
    delta: COTLongShortNet | None = None

    @model_validator(mode="after")
    def _delta_matches_previous(self) -> "COTSeries":
        if self.previous is None:
            if self.delta is not None:
                raise ValueError("COT delta requires an actual previous report")
            return self
        if self.delta is None:
            raise ValueError("COT series with a previous report requires a delta")
        latest_values = (self.latest.long, self.latest.short, self.latest.net)
        previous_values = (self.previous.long, self.previous.short, self.previous.net)
        delta_values = (self.delta.long, self.delta.short, self.delta.net)
        if any(value is None for value in (*latest_values, *previous_values, *delta_values)):
            raise ValueError("complete COT series values are required to calculate a delta")
        if any(
            not math.isclose(actual - before, change, abs_tol=1e-6)
            for actual, before, change in zip(latest_values, previous_values, delta_values)
        ):
            raise ValueError("COT delta must equal latest minus actual previous")
        return self


class COTOpenInterest(_Frozen):
    """Open interest level and its delta from the actual previous report."""

    value: float | None
    previous: float | None = None
    delta: float | None = None
    unit: Literal["contracts"] = "contracts"

    @model_validator(mode="after")
    def _delta_matches_previous(self) -> "COTOpenInterest":
        if self.previous is None:
            if self.delta is not None:
                raise ValueError("open-interest delta requires an actual previous report")
        elif self.delta is None or self.value is None or not math.isclose(self.value - self.previous, self.delta, abs_tol=1e-6):
            raise ValueError("open-interest delta must equal latest minus actual previous")
        return self


class COTPositioningSnapshot(_Frozen):
    """Full typed CFTC Gold positioning snapshot for Core integration.

    ``report_type`` is explicit because futures-only and combined reports use
    different open-interest universes.  ``previous`` is the immediately prior
    published Gold row selected by report date; no change column is substituted.
    """

    schema_version: Literal["cot_positioning_snapshot.v1"] = COT_POSITIONING_SNAPSHOT_VERSION
    as_of: datetime
    readiness: Literal["ready", "observe", "blocked"]
    freshness_status: Literal["fresh", "stale", "missing"]
    quality_status: Literal["accepted", "observe", "blocked"]
    alignment_status: Literal["aligned", "misaligned", "unknown"]
    report_type: Literal["futures_only", "combined"]
    report_date: date | None
    previous_report_date: date | None
    managed_money: COTSeries
    producer_merchant: COTSeries
    swap_dealers: COTSeries
    other_reportables: COTSeries
    open_interest: COTOpenInterest
    source_refs: tuple[COTPositioningSourceReference, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_snapshot(self) -> "COTPositioningSnapshot":
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("COT positioning as_of must be timezone-aware")
        if self.report_date is None:
            if self.previous_report_date is not None:
                raise ValueError("previous_report_date requires report_date")
        elif self.previous_report_date is not None and self.previous_report_date >= self.report_date:
            raise ValueError("previous_report_date must precede report_date")
        expected = _positioning_readiness(self.freshness_status, self.quality_status, self.alignment_status)
        if self.readiness != expected:
            raise ValueError(f"COT positioning readiness must be {expected}")
        return self


def build_cot_positioning_snapshot(
    *,
    candidates: Iterable[Mapping[str, Any]],
    as_of: datetime,
    report_type: Literal["futures_only", "combined"] | None = None,
    source_refs: Iterable[Mapping[str, Any]] | None = None,
) -> COTPositioningSnapshot:
    """Build a full CFTC contract from collector points or normalized rows.

    Accepted candidate forms are the ``MacroPoint.to_dict()`` values emitted
    by ``collect_positioning_cot`` and the dictionaries emitted by
    ``COTRow.to_dict()``.  Core may therefore call this function directly with
    a ``CollectorResult.points`` list and its ``source_refs`` list.
    """

    point_in_time = _aware_utc(as_of)
    rows = tuple(dict(row) for row in candidates if isinstance(row, Mapping))
    inferred_types = {_positioning_report_type(row) for row in rows}
    inferred_types.discard(None)
    selected_type = report_type
    if selected_type is None:
        if len(inferred_types) == 1:
            selected_type = next(iter(inferred_types))
        elif len(inferred_types) > 1:
            return _missing_positioning_snapshot(
                point_in_time,
                report_type="futures_only",
                reason="ambiguous_report_type",
                source_refs=source_refs,
            )
        else:
            selected_type = "futures_only"
    if selected_type not in COT_REPORT_TYPES:
        raise ValueError(f"unsupported COT report_type: {selected_type!r}")

    refs, refs_ok = _positioning_source_refs(
        rows=rows,
        source_refs=source_refs,
        report_type=selected_type,
        as_of=point_in_time,
    )
    eligible_lineages = _eligible_positioning_lineages(
        refs,
        report_type=selected_type,
        as_of=point_in_time,
    )
    metric_rows: list[dict[str, Any]] = []
    rejected_reasons: list[str] = []
    for row in rows:
        row_type = _positioning_report_type(row)
        if row_type not in {None, selected_type}:
            continue
        rejection_reason = _positioning_candidate_rejection_reason(
            row,
            report_type=selected_type,
            as_of=point_in_time,
            eligible_lineages=eligible_lineages,
        )
        if rejection_reason is not None:
            rejected_reasons.append(rejection_reason)
            continue
        normalized = _normalize_positioning_candidate(row, selected_type)
        if normalized is not None:
            metric_rows.append(normalized)
        else:
            rejected_reasons.append("invalid_positioning_candidate")
    if not metric_rows:
        return _missing_positioning_snapshot(
            point_in_time,
            report_type=selected_type,
            reason=_positioning_missing_reason(
                rejected_reasons=rejected_reasons,
                refs=refs,
            ),
            source_refs=refs,
            alignment_status=_positioning_missing_alignment(
                rejected_reasons=rejected_reasons,
                refs=refs,
            ),
        )

    dates = sorted({row["report_date"] for row in metric_rows if row["report_date"] <= point_in_time.date()})
    if not dates:
        return _missing_positioning_snapshot(
            point_in_time,
            report_type=selected_type,
            reason="report_date_after_as_of",
            source_refs=refs,
            alignment_status="misaligned",
        )
    latest_date = dates[-1]
    previous_date = dates[-2] if len(dates) > 1 else None
    latest = _merge_positioning_rows(metric_rows, latest_date)
    previous = _merge_positioning_rows(metric_rows, previous_date) if previous_date else {}
    report_complete = _complete_positioning_row(latest)
    official_lineage = refs_ok and any(ref.qualification_reason == "eligible" for ref in refs)
    age_days = (point_in_time.date() - latest_date).days
    freshness: Literal["fresh", "stale", "missing"] = "fresh" if age_days <= 10 else "stale"
    quality: Literal["accepted", "observe", "blocked"] = "accepted"
    reasons: list[str] = []
    alignment: Literal["aligned", "misaligned", "unknown"] = "aligned"
    if age_days < 0:
        alignment, quality = "misaligned", "blocked"
        reasons.append("report_date_after_as_of")
    elif age_days > 17:
        quality = "blocked"
        reasons.append("cot_stale_beyond_observe_window")
    elif age_days > 10:
        quality = "observe"
        reasons.append("cot_stale")
    if not report_complete:
        quality = "blocked"
        reasons.append("required_latest_metrics_missing")
    if not official_lineage:
        quality = "blocked"
        reasons.append("official_cftc_lineage_missing")
    if previous_date is None:
        reasons.append("previous_report_missing")

    snapshot = COTPositioningSnapshot(
        as_of=point_in_time,
        readiness=_positioning_readiness(freshness, quality, alignment),
        freshness_status=freshness,
        quality_status=quality,
        alignment_status=alignment,
        report_type=selected_type,
        report_date=latest_date,
        previous_report_date=previous_date,
        managed_money=_series_from_rows(latest, previous),
        producer_merchant=_series_from_rows(latest, previous, prefix="producer"),
        swap_dealers=_series_from_rows(latest, previous, prefix="swap"),
        other_reportables=_series_from_rows(latest, previous, prefix="other"),
        open_interest=_open_interest_from_rows(latest, previous),
        source_refs=refs,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )
    return snapshot


def _positioning_report_type(row: Mapping[str, Any]) -> Literal["futures_only", "combined"] | None:
    raw_type = row.get("report_type")
    if raw_type in COT_REPORT_TYPES:
        return raw_type
    symbol = str(row.get("symbol") or "")
    if symbol.startswith("COT_GOLD_combined_"):
        return "combined"
    if symbol.startswith("COT_GOLD_"):
        return "futures_only"
    return None


def _is_cftc_cot_url_for_report_type(
    value: str,
    report_type: Literal["futures_only", "combined"],
) -> bool:
    """Require the CFTC archive URL to name the selected report universe."""

    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.cftc.gov"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return False
    pattern = (
        _FUTURES_ONLY_CFTC_COT_PATH
        if report_type == "futures_only"
        else _COMBINED_CFTC_COT_PATH
    )
    return pattern.fullmatch(parsed.path) is not None


def _eligible_positioning_lineages(
    refs: Iterable[COTPositioningSourceReference],
    *,
    report_type: Literal["futures_only", "combined"],
    as_of: datetime,
) -> set[tuple[str, str, str, Literal["futures_only", "combined"]]]:
    """Return the exact raw lineages allowed to contribute derived metrics."""

    return {
        (ref.source, ref.reference, ref.raw_path, ref.report_type)
        for ref in refs
        if ref.qualification_reason == "eligible"
        and ref.report_type == report_type
        and ref.raw_path
        and ref.retrieved_at <= as_of
    }


def _positioning_candidate_rejection_reason(
    row: Mapping[str, Any],
    *,
    report_type: Literal["futures_only", "combined"],
    as_of: datetime,
    eligible_lineages: set[tuple[str, str, str, Literal["futures_only", "combined"]]],
) -> str | None:
    """Validate time and exact lineage before a row can form a report metric."""

    retrieved_at = _parse_time(row.get("retrieved_at"))
    if retrieved_at is None:
        return "retrieval_time_missing_or_naive"
    if retrieved_at > as_of:
        return "retrieval_time_after_as_of"
    report_date = _parse_date(row.get("report_date") or row.get("date"))
    if report_date is None:
        return "report_date_invalid"
    if report_date > as_of.date():
        return "report_date_after_as_of"

    source = str(row.get("source") or "")
    reference = str(row.get("source_url") or row.get("reference") or "")
    raw_path = str(row.get("raw_path") or "").strip()
    lineage = (source, reference, raw_path, report_type)
    if lineage not in eligible_lineages:
        return "candidate_source_lineage_not_eligible"
    return None


def _positioning_missing_reason(
    *,
    rejected_reasons: Iterable[str],
    refs: Iterable[COTPositioningSourceReference],
) -> str:
    """Keep the first actionable fail-closed reason in the typed snapshot."""

    reasons = set(rejected_reasons)
    reasons.update(ref.qualification_reason for ref in refs)
    for reason in (
        "retrieval_time_after_as_of",
        "retrieval_time_missing_or_naive",
        "report_date_after_as_of",
        "candidate_source_lineage_not_eligible",
        "invalid_official_lineage",
        "report_date_invalid",
        "no_source_reference",
    ):
        if reason in reasons:
            return reason
    return "no_eligible_cot_positioning_candidate"


def _positioning_missing_alignment(
    *,
    rejected_reasons: Iterable[str],
    refs: Iterable[COTPositioningSourceReference],
) -> Literal["aligned", "misaligned", "unknown"]:
    reasons = set(rejected_reasons)
    reasons.update(ref.qualification_reason for ref in refs)
    if reasons & {"retrieval_time_after_as_of", "report_date_after_as_of"}:
        return "misaligned"
    return "unknown"


def _normalize_positioning_candidate(
    row: Mapping[str, Any],
    report_type: Literal["futures_only", "combined"],
) -> dict[str, Any] | None:
    report_date = _parse_date(row.get("report_date") or row.get("date"))
    if report_date is None:
        return None
    if all(key in row for key in ("managed_money_long", "managed_money_short")):
        return {
            "report_date": report_date,
            "report_type": report_type,
            "managed_long": _finite_number(row.get("managed_money_long")),
            "managed_short": _finite_number(row.get("managed_money_short")),
            "producer_long": _finite_number(row.get("producer_long")),
            "producer_short": _finite_number(row.get("producer_short")),
            "swap_long": _finite_number(row.get("swap_long")),
            "swap_short": _finite_number(row.get("swap_short")),
            "other_long": _finite_number(row.get("other_long")),
            "other_short": _finite_number(row.get("other_short")),
            "open_interest": _finite_number(row.get("open_interest")),
        }

    symbol = str(row.get("symbol") or "")
    prefix = "COT_GOLD_combined_" if report_type == "combined" else "COT_GOLD_"
    if not symbol.startswith(prefix):
        return None
    suffix = symbol[len(prefix):]
    if suffix.endswith("_delta"):
        # Deltas are recomputed from the two actual report rows below; treating
        # this convenience point as a latest level would create a false conflict.
        return None
    for marker in ("_prev", "_delta"):
        if suffix.endswith(marker):
            suffix = suffix[: -len(marker)]
            break
    field_map = {
        "mm_long": "managed_long",
        "noncomm_long": "managed_long",
        "mm_short": "managed_short",
        "noncomm_short": "managed_short",
        "mm_net": "managed_net",
        "noncomm_net": "managed_net",
        "producer_long": "producer_long",
        "producer_short": "producer_short",
        "producer_net": "producer_net",
        "swap_long": "swap_long",
        "swap_short": "swap_short",
        "swap_net": "swap_net",
        "other_long": "other_long",
        "other_short": "other_short",
        "open_interest": "open_interest",
    }
    field = field_map.get(suffix)
    value = _finite_number(row.get("value"))
    if field is None or value is None:
        return None
    return {"report_date": report_date, "report_type": report_type, field: value}


def _merge_positioning_rows(rows: list[dict[str, Any]], report_date: date | None) -> dict[str, float | None]:
    if report_date is None:
        return {}
    merged: dict[str, float | None] = {}
    for row in rows:
        if row.get("report_date") != report_date:
            continue
        for key, value in row.items():
            if key in {"report_date", "report_type"} or value is None:
                continue
            existing = merged.get(key)
            if existing is not None and not math.isclose(existing, value, abs_tol=1e-6):
                # Preserve an explicit conflict marker for the caller.
                merged[key] = None
            elif key not in merged:
                merged[key] = value
    return merged


def _complete_positioning_row(row: Mapping[str, Any]) -> bool:
    required = ("managed_long", "managed_short", "open_interest")
    return all(_finite_number(row.get(key)) is not None for key in required)


def _series_from_rows(
    latest: Mapping[str, Any],
    previous: Mapping[str, Any],
    *,
    prefix: str = "managed",
) -> COTSeries:
    long_key = f"{prefix}_long"
    short_key = f"{prefix}_short"
    net_key = f"{prefix}_net"
    latest_long = _finite_number(latest.get(long_key))
    latest_short = _finite_number(latest.get(short_key))
    latest_net = _finite_number(latest.get(net_key))
    if latest_net is None and latest_long is not None and latest_short is not None:
        latest_net = latest_long - latest_short
    latest_series = COTLongShortNet(long=latest_long, short=latest_short, net=latest_net)
    if not previous:
        return COTSeries(latest=latest_series)
    previous_long = _finite_number(previous.get(long_key))
    previous_short = _finite_number(previous.get(short_key))
    previous_net = _finite_number(previous.get(net_key))
    if previous_net is None and previous_long is not None and previous_short is not None:
        previous_net = previous_long - previous_short
    previous_series = COTLongShortNet(long=previous_long, short=previous_short, net=previous_net)
    if any(value is None for value in (latest_long, latest_short, latest_net, previous_long, previous_short, previous_net)):
        # A partial category cannot claim a previous/delta series.  Keep the
        # latest values that are present and let the snapshot quality status
        # describe the incomplete evidence.
        return COTSeries(latest=latest_series)
    delta = COTLongShortNet(
        long=latest_long - previous_long,
        short=latest_short - previous_short,
        net=latest_net - previous_net,
    )
    return COTSeries(latest=latest_series, previous=previous_series, delta=delta)


def _open_interest_from_rows(latest: Mapping[str, Any], previous: Mapping[str, Any]) -> COTOpenInterest:
    value = _finite_number(latest.get("open_interest"))
    previous_value = _finite_number(previous.get("open_interest")) if previous else None
    delta = value - previous_value if value is not None and previous_value is not None else None
    return COTOpenInterest(value=value, previous=previous_value, delta=delta)


def _positioning_source_refs(
    *,
    rows: tuple[dict[str, Any], ...],
    source_refs: Iterable[Mapping[str, Any]] | None,
    report_type: Literal["futures_only", "combined"],
    as_of: datetime,
) -> tuple[tuple[COTPositioningSourceReference, ...], bool]:
    raw_refs = [dict(ref) for ref in (source_refs or ()) if isinstance(ref, Mapping)]
    if not raw_refs:
        raw_refs = [
            {
                "source": row.get("source"),
                "reference": row.get("source_url"),
                "raw_path": row.get("raw_path"),
                "retrieved_at": row.get("retrieved_at"),
                "report_type": _positioning_report_type(row) or report_type,
            }
            for row in rows
            if row.get("source") or row.get("source_url")
        ]
    refs: list[COTPositioningSourceReference] = []
    eligible = False
    for raw in raw_refs:
        if raw.get("report_type") not in {None, report_type}:
            continue
        parsed_retrieved_at = _parse_time(raw.get("retrieved_at"))
        source = str(raw.get("source") or "positioning_candidate")
        reference = str(raw.get("source_url") or raw.get("reference") or "positioning://candidate")
        raw_path = str(raw.get("raw_path")) if raw.get("raw_path") else None
        archive_path = str(raw.get("raw_archive_path")) if raw.get("raw_archive_path") else None
        if parsed_retrieved_at is None:
            # The typed reference requires an aware timestamp.  Retain the
            # run cutoff only as a displayable placeholder for blocked lineage;
            # it must never make this reference eligible.
            retrieved_at = as_of
            reason = "retrieval_time_missing_or_naive"
        elif parsed_retrieved_at > as_of:
            retrieved_at = parsed_retrieved_at
            reason = "retrieval_time_after_as_of"
        else:
            retrieved_at = parsed_retrieved_at
            reason = (
                "eligible"
                if (
                    source == "cftc"
                    and _is_cftc_cot_url_for_report_type(reference, report_type)
                    and raw_path
                    and archive_path
                )
                else "invalid_official_lineage"
            )
        eligible = eligible or reason == "eligible"
        refs.append(
            COTPositioningSourceReference(
                source=source,
                reference=reference,
                raw_path=raw_path,
                raw_archive_path=archive_path,
                retrieved_at=retrieved_at,
                report_type=report_type,
                qualification_reason=reason,
            )
        )
    if not refs:
        refs = [
            COTPositioningSourceReference(
                source="cot_positioning_query",
                reference=f"query://COT_GOLD/{report_type}",
                retrieved_at=as_of,
                report_type=report_type,
                qualification_reason="no_source_reference",
            )
        ]
    return _deduplicated_positioning_refs(refs), eligible


def _missing_positioning_snapshot(
    as_of: datetime,
    *,
    report_type: Literal["futures_only", "combined"],
    reason: str,
    source_refs: Iterable[Mapping[str, Any]] | Iterable[COTPositioningSourceReference] | None = None,
    alignment_status: Literal["aligned", "misaligned", "unknown"] = "unknown",
) -> COTPositioningSnapshot:
    refs: tuple[COTPositioningSourceReference, ...]
    candidate_refs = tuple(source_refs or ())
    if candidate_refs and all(isinstance(item, COTPositioningSourceReference) for item in candidate_refs):
        refs = candidate_refs  # type: ignore[assignment]
    else:
        refs, _ = _positioning_source_refs(
            rows=(), source_refs=candidate_refs or None, report_type=report_type, as_of=as_of
        )
    empty = COTLongShortNet(long=None, short=None, net=None)
    return COTPositioningSnapshot(
        as_of=as_of,
        readiness="blocked",
        freshness_status="missing",
        quality_status="blocked",
        alignment_status=alignment_status,
        report_type=report_type,
        report_date=None,
        previous_report_date=None,
        managed_money=COTSeries(latest=empty),
        producer_merchant=COTSeries(latest=empty),
        swap_dealers=COTSeries(latest=empty),
        other_reportables=COTSeries(latest=empty),
        open_interest=COTOpenInterest(value=None),
        source_refs=refs,
        reason_codes=(reason,),
    )


def _positioning_readiness(
    freshness: str,
    quality: str,
    alignment: str,
) -> Literal["ready", "observe", "blocked"]:
    if quality == "blocked" or alignment == "misaligned":
        return "blocked"
    if quality == "observe" or freshness == "stale" or alignment == "unknown":
        return "observe"
    return "ready"


def _deduplicated_positioning_refs(
    refs: Iterable[COTPositioningSourceReference],
) -> tuple[COTPositioningSourceReference, ...]:
    unique = {
        (
            ref.source,
            ref.reference,
            ref.raw_path,
            ref.raw_archive_path,
            ref.retrieved_at,
            ref.report_type,
            ref.qualification_reason,
        ): ref
        for ref in refs
    }
    return tuple(unique[key] for key in sorted(unique))
