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
_CFTC_COT_PATH = re.compile(r"/files/dea/history/fut_disagg_txt_\d{4}\.zip")
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
            or not _is_cftc_cot_url(self.reference)
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
    elif not _is_cftc_cot_url(reference):
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
