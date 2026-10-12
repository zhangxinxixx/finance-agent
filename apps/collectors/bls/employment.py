"""Read-only collector for the BLS Employment series.

The collector prefers one BLS batch request, keeps the original response in
an immutable raw archive, and only reuses a successful raw response when its
sidecar contains an auditable retrieval timestamp. If BLS is rate limited and
there is no eligible local cache, the existing FRED API collector provides
    an official mirror reported as ``fred``; it is never labelled as a BLS cache.
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from apps.parsers.bls.employment import (
    BLS_EMPLOYMENT_SERIES,
    BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL,
    BLS_EMPLOYMENT_RELEASE_SOURCE,
    BLS_INDUSTRY_SERIES as BLS_INDUSTRY_SERIES,
    BLS_SERIES_BY_ID,
    BLSMonthlyObservation,
    BLSParseError,
    BLSReleaseParseError,
    normalize_bls_cutoff_month,
    parse_bls_employment_release_html,
    parse_bls_series_payload,
)
from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import utc_now_iso
from apps.runtime.secret_resolver import resolve_runtime_secret

BLS_API_BASE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data"
BLS_SOURCE = "bls_public_api_v2"
BLS_EMPLOYMENT_RELEASE_URL = "https://www.bls.gov/news.release/empsit.htm"
BLS_EMPLOYMENT_RELEASE_ARCHIVE_URL_TEMPLATE = "https://www.bls.gov/news.release/archives/empsit_{date}.htm"
BLS_EMPLOYMENT_RELEASE_LOOKBACK_DAYS = 21
BLS_EMPLOYMENT_RELEASE_RAW_ROOT = "raw/macro/bls_release"
BLS_DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
# A cache may bridge a temporary quota outage, while still requiring a recent
# successful source response and a real retrieval timestamp.
BLS_CACHE_MAX_AGE_DAYS = 31
BLS_RAW_METADATA_SUFFIX = ".meta.json"
FRED_GRAPH_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
BLS_FRED_MIRROR_SYMBOLS = {
    "CES0000000001": "PAYEMS",
    "CES0500000003": "CES0500000003",
    "LNS14000000": "UNRATE",
    "LNS11300000": "CIVPART",
    # BLS CES ids are the stable internal symbols; these are the matching
    # official FRED Graph ids used only when the BLS API is unavailable.
    "CES3000000001": "MANEMP",
    "CES5000000001": "USINFO",
    "CES7072200001": "CES7072200001",
    "CES9093161101": "CES9093161101",
    "CES6562000101": "CES6562000101",
}
FRED_MIRROR_SOURCE = "fred"
FRED_MIRROR_KIND = "official_fred_graph_csv"
FRED_API_MIRROR_KIND = "official_fred_api_collector"
FRED_VINTAGE_SOURCE = "fred_vintage"
FRED_VINTAGE_KIND = "fred_vintage"
FRED_VINTAGE_DATES_URL = "https://api.stlouisfed.org/fred/series/vintagedates"
FRED_VINTAGE_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
# Match the existing collector naming convention while exposing the more
# descriptive Employment-specific constant as the primary name.
BLS_SERIES = BLS_EMPLOYMENT_SERIES


@dataclass(frozen=True)
class _CachedSeries:
    symbol: str
    observations: tuple[BLSMonthlyObservation, ...]
    raw_path: str
    source_url: str
    retrieved_at: str
    latest_observation_month: str
    cache_age_days: float


@dataclass(frozen=True)
class _FredOutcome:
    points_by_symbol: dict[str, list[MacroPoint]]
    refs_by_symbol: dict[str, dict[str, Any]]
    failure_kind: str | None
    reason: str | None


def bls_series_url(series_id: str, start_year: int, end_year: int) -> str:
    """Build the official BLS v2 GET URL for one series and year range."""

    return f"{BLS_API_BASE_URL}/{series_id}?{urlencode({'startyear': start_year, 'endyear': end_year})}"


def bls_batch_url(start_year: int, end_year: int) -> str:
    """Build the logical URL recorded for an official BLS batch request."""

    return f"{BLS_API_BASE_URL}?{urlencode({'startyear': start_year, 'endyear': end_year})}"


def collect_bls_series_from_payload(
    *,
    symbol: str,
    payload: Mapping[str, object],
    retrieved_date: str,
    storage_root: Path,
    source_url: str,
    retrieved_at: str | None = None,
) -> CollectorResult:
    """Archive and normalize one BLS response without making a network call."""

    _validate_retrieved_date(retrieved_date)
    if symbol not in BLS_SERIES_BY_ID:
        raise ValueError(f"Unsupported BLS Employment series: {symbol}")
    if not isinstance(payload, Mapping):
        raise BLSParseError("BLS payload must be a mapping")

    retrieved_at = _validated_retrieved_at(retrieved_at or utc_now_iso())
    raw_path = _archive_bls_payload(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        symbol=symbol,
        payload=dict(payload),
    )
    cutoff_month = normalize_bls_cutoff_month(retrieved_date)
    try:
        observations = parse_bls_series_payload(
            payload,
            series_id=symbol,
            cutoff_month=cutoff_month,
        )
    except BLSParseError as exc:
        failure_kind = _classify_parse_failure(exc)
        reason = f"BLS response parse failed: {type(exc).__name__}: {exc}"
        _write_bls_metadata(
            storage_root=storage_root,
            raw_path=raw_path,
            symbol=symbol,
            source_url=source_url,
            retrieved_at=retrieved_at,
            retrieved_date=retrieved_date,
            cutoff_month=cutoff_month,
            latest_observation_month=None,
            status="unavailable",
            failure_kind=failure_kind,
        )
        return _unavailable_result(
            symbol=symbol,
            source_url=source_url,
            raw_path=raw_path,
            retrieved_at=retrieved_at,
            retrieved_date=retrieved_date,
            reason=reason,
            failure_kind=failure_kind,
        )

    status = "available" if observations else "unavailable"
    failure_kind = None if observations else "missing_fields"
    reason = None if observations else "BLS returned no usable monthly observations through the cutoff"
    latest_observation_month = observations[-1].observation_month if observations else None
    _write_bls_metadata(
        storage_root=storage_root,
        raw_path=raw_path,
        symbol=symbol,
        source_url=source_url,
        retrieved_at=retrieved_at,
        retrieved_date=retrieved_date,
        cutoff_month=cutoff_month,
        latest_observation_month=latest_observation_month,
        status=status,
        failure_kind=failure_kind,
    )
    points = [
        MacroPoint(
            symbol=symbol,
            date=observation.point_date,
            value=observation.value,
            source=BLS_SOURCE,
            source_url=source_url,
            retrieved_at=retrieved_at,
            raw_path=raw_path,
        )
        for observation in observations
    ]
    source_ref = _source_ref(
        symbol=symbol,
        source_url=source_url,
        raw_path=raw_path,
        retrieved_at=retrieved_at,
        observation_cutoff_date=retrieved_date,
        observation_cutoff_month=cutoff_month,
        observation_month=latest_observation_month,
        status=status,
        reason=reason,
        failure_kind=failure_kind,
    )
    return CollectorResult(
        points=points,
        unavailable_symbols=[] if observations else [symbol],
        source_refs=[source_ref],
    )


def collect_bls_employment(
    *,
    retrieved_date: str,
    storage_root: Path,
    series_ids: tuple[str, ...] = BLS_EMPLOYMENT_SERIES,
    start_year: int | None = None,
    end_year: int | None = None,
    client: Any | None = None,
    fred_client: Any | None = None,
    release_client: Any | None = None,
    fred_vintage_client: Any | None = None,
    request_timeout: float = BLS_DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> CollectorResult:
    """Collect Employment series with auditable latest-available fallbacks.

    A client with ``post`` receives one BLS batch request, reducing quota use;
    older injected GET-only clients remain supported. An unavailable BLS
    series first consults only ``storage_root/raw/macro/bls``. When no
    eligible cache exists, the live path reuses the existing official FRED
    collector/API and then the keyless FRED Graph CSV path under
    ``source="fred"`` with explicit BLS failure provenance. If the release
    HTML is unavailable, the shared HTTP client can additionally compare two
    dated PAYEMS FRED vintages under ``source="fred_vintage"``; publication
    time, sectors, and consensus stay unavailable in that fallback. Injected
    clients retain the deterministic combined Graph CSV path for tests and
    read-only probes.
    """

    retrieval_day = _validate_retrieved_date(retrieved_date)
    requested_series = tuple(series_ids)
    unsupported = [symbol for symbol in requested_series if symbol not in BLS_SERIES_BY_ID]
    if unsupported:
        raise ValueError(f"Unsupported BLS Employment series: {', '.join(unsupported)}")
    if start_year is None:
        start_year = retrieval_day.year - 1
    if end_year is None:
        end_year = retrieval_day.year
    _validate_year_range(start_year=start_year, end_year=end_year)
    if not requested_series:
        return CollectorResult(points=[], unavailable_symbols=[], source_refs=[])

    attempted_at = _validated_retrieved_at(utc_now_iso())
    if client is not None:
        result = _collect_with_client(
            client=client,
            fred_client=fred_client if fred_client is not None else client,
            use_fred_api=False,
            requested_series=requested_series,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            start_year=start_year,
            end_year=end_year,
            attempted_at=attempted_at,
        )
        if release_client is None:
            # Injected API clients are used by deterministic unit tests and
            # should not cause an unexpected second network contract.  The
            # production path below always supplies the shared HTTP client.
            return result
        return _append_release_context(
            result,
            client=release_client,
            fred_vintage_client=fred_vintage_client,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            attempted_at=attempted_at,
        )

    import httpx

    with httpx.Client(
        timeout=max(1.0, min(float(request_timeout), 120.0)),
        headers={"User-Agent": "finance-agent/0.1"},
        trust_env=False,
    ) as http_client:
        result = _collect_with_client(
            client=http_client,
            # Keep the shared HTTP client available for the keyless official
            # FRED Graph fallback even when the optional FRED API client is
            # not configured.  The API-key path is still attempted first
            # when no explicit fallback client was supplied.
            fred_client=fred_client or http_client,
            use_fred_api=fred_client is None,
            requested_series=requested_series,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            start_year=start_year,
            end_year=end_year,
            attempted_at=attempted_at,
        )
        return _append_release_context(
            result,
            client=release_client or http_client,
            fred_vintage_client=fred_vintage_client or http_client,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            attempted_at=attempted_at,
        )


def _append_release_context(
    result: CollectorResult,
    *,
    client: Any,
    fred_vintage_client: Any | None,
    retrieved_date: str,
    storage_root: Path,
    attempted_at: str,
) -> CollectorResult:
    release_ref = _collect_employment_release_context(
        client=client,
        retrieved_date=retrieved_date,
        storage_root=storage_root,
        attempted_at=attempted_at,
    )
    if (
        release_ref.get("status") == "unavailable"
        and fred_vintage_client is not None
    ):
        release_ref = _append_fred_vintage_fallback(
            html_ref=release_ref,
            client=fred_vintage_client,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            attempted_at=attempted_at,
        )
    return CollectorResult(
        points=list(result.points),
        unavailable_symbols=list(result.unavailable_symbols),
        source_refs=[*result.source_refs, release_ref],
    )


def _collect_employment_release_context(
    *,
    client: Any,
    retrieved_date: str,
    storage_root: Path,
    attempted_at: str,
) -> dict[str, Any]:
    """Fetch the official release page and retain every attempted raw body."""

    cutoff_day = _validate_retrieved_date(retrieved_date)
    cutoff_month = cutoff_day.strftime("%Y-%m")
    attempted_urls: list[str] = []
    raw_paths: list[str] = []
    attempted_raw_refs: list[dict[str, Any]] = []
    failure_details: list[str] = []
    for url in _employment_release_urls(cutoff_day):
        attempted_urls.append(url)
        try:
            response = _release_get(client, url)
        except Exception as exc:
            failure_details.append(f"{url}: {type(exc).__name__}: {exc}")
            continue

        status_code = _response_status_code(response)
        body = _response_body(response)
        raw_path = _archive_release_body(
            storage_root=storage_root,
            retrieved_date=retrieved_date,
            body=body,
        )
        if raw_path is not None:
            raw_paths.append(raw_path)
            attempted_raw_refs.append(
                {
                    "source": BLS_EMPLOYMENT_RELEASE_SOURCE,
                    "source_url": url,
                    "raw_path": raw_path,
                    "retrieved_at": attempted_at,
                }
            )
        if status_code >= 400:
            _write_release_metadata(
                storage_root=storage_root,
                raw_path=raw_path,
                source_url=url,
                retrieved_at=attempted_at,
                retrieved_date=retrieved_date,
                status="unavailable",
                failure_kind=_classify_release_http_failure(status_code),
                release_date=None,
                observation_month=None,
            )
            failure_details.append(f"{url}: HTTP {status_code}")
            continue
        if body is None:
            failure_details.append(f"{url}: empty response body")
            continue
        try:
            parsed = parse_bls_employment_release_html(body)
        except BLSReleaseParseError as exc:
            _write_release_metadata(
                storage_root=storage_root,
                raw_path=raw_path,
                source_url=url,
                retrieved_at=attempted_at,
                retrieved_date=retrieved_date,
                status="unavailable",
                failure_kind="parse_error",
                release_date=None,
                observation_month=None,
            )
            failure_details.append(f"{url}: parse_error: {exc}")
            continue
        if parsed.release_date is None or parsed.observation_month is None:
            _write_release_metadata(
                storage_root=storage_root,
                raw_path=raw_path,
                source_url=url,
                retrieved_at=attempted_at,
                retrieved_date=retrieved_date,
                status="unavailable",
                failure_kind="missing_fields",
                release_date=parsed.release_date,
                observation_month=parsed.observation_month,
            )
            failure_details.append(f"{url}: release_date_or_month_unavailable")
            continue
        if parsed.release_date > cutoff_day.isoformat() or parsed.observation_month > cutoff_month:
            _write_release_metadata(
                storage_root=storage_root,
                raw_path=raw_path,
                source_url=url,
                retrieved_at=attempted_at,
                retrieved_date=retrieved_date,
                status="unavailable",
                failure_kind="release_mismatch",
                release_date=parsed.release_date,
                observation_month=parsed.observation_month,
            )
            failure_details.append(
                f"{url}: release_is_after_cutoff({parsed.release_date}/{parsed.observation_month})"
            )
            continue

        context = parsed.to_dict()
        context["source_kind"] = "bls_release_html"
        context["release_date_kind"] = "official_publication_date"
        context["source_refs"] = [
            {
                "source": BLS_EMPLOYMENT_RELEASE_SOURCE,
                "source_url": url,
                "raw_path": raw_path,
                "retrieved_at": attempted_at,
            }
        ]
        ref = {
            "symbol": BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL,
            "source": BLS_EMPLOYMENT_RELEASE_SOURCE,
            "source_kind": "bls_release_html",
            "source_url": url,
            "raw_path": raw_path,
            "retrieved_at": attempted_at,
            "observation_cutoff_date": retrieved_date,
            "observation_cutoff_month": cutoff_month,
            "observation_month": parsed.observation_month,
            "release_date": parsed.release_date,
            "release_date_kind": "official_publication_date",
            "release_datetime": parsed.release_datetime,
            "release_timezone": parsed.release_timezone,
            "status": parsed.status,
            "release_context": context,
            "archive_fallback_used": url != BLS_EMPLOYMENT_RELEASE_URL,
            "attempted_urls": attempted_urls,
        }
        if raw_paths:
            ref["attempted_raw_paths"] = raw_paths
        _write_release_metadata(
            storage_root=storage_root,
            raw_path=raw_path,
            source_url=url,
            retrieved_at=attempted_at,
            retrieved_date=retrieved_date,
            status=parsed.status,
            failure_kind=None,
            release_date=parsed.release_date,
            observation_month=parsed.observation_month,
        )
        return ref

    reason = "; ".join(failure_details) if failure_details else "no release URL was attempted"
    failure_kind = _release_failure_kind(failure_details)
    context = {
        "status": "unavailable",
        "source_kind": "bls_release_html",
        "release_date_kind": None,
        "release_date": None,
        "release_time_local": None,
        "release_timezone": None,
        "release_datetime": None,
        "observation_month": None,
        "headline": {
            "new_jobs_thousands": None,
            "unemployment_rate": None,
            "wage_mom_pct": None,
            "wage_yoy_pct": None,
        },
        "revisions": [],
        "sector_contributions": [],
        "missing_fields": ["official_release"],
        "parser_notes": [reason],
        "source_refs": attempted_raw_refs,
    }
    ref = {
        "symbol": BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL,
        "source": BLS_EMPLOYMENT_RELEASE_SOURCE,
        "source_kind": "bls_release_html",
        "source_url": attempted_urls[0] if attempted_urls else BLS_EMPLOYMENT_RELEASE_URL,
        "retrieved_at": attempted_at,
        "observation_cutoff_date": retrieved_date,
        "observation_cutoff_month": cutoff_month,
        "status": "unavailable",
        "release_context": context,
        "failure_kind": failure_kind,
        "reason": reason,
        "attempted_urls": attempted_urls,
    }
    if raw_paths:
        ref["raw_path"] = raw_paths[-1]
        ref["attempted_raw_paths"] = raw_paths
        _write_release_metadata(
            storage_root=storage_root,
            raw_path=raw_paths[-1],
            source_url=attempted_urls[-1],
            retrieved_at=attempted_at,
            retrieved_date=retrieved_date,
            status="unavailable",
            failure_kind=failure_kind,
            release_date=None,
            observation_month=None,
        )
    return ref


@dataclass(frozen=True)
class _FredVintageResponse:
    """One authenticated FRED vintage response and its safe lineage."""

    payload: Mapping[str, object] | None
    source_url: str
    raw_path: str | None
    status_code: int | None
    failure_kind: str | None
    reason: str | None


def _append_fred_vintage_fallback(
    *,
    html_ref: Mapping[str, Any],
    client: Any,
    retrieved_date: str,
    storage_root: Path,
    attempted_at: str,
) -> dict[str, Any]:
    """Use FRED's dated vintages only after the official HTML path fails."""

    fred_ref = _collect_fred_vintage_context(
        client=client,
        retrieved_date=retrieved_date,
        storage_root=storage_root,
        attempted_at=attempted_at,
    )
    html_context = html_ref.get("release_context")
    html_context = dict(html_context) if isinstance(html_context, Mapping) else {}
    html_refs = html_context.get("source_refs")
    html_refs = list(html_refs) if isinstance(html_refs, list) else []
    fred_context = fred_ref.get("release_context")
    fred_context = dict(fred_context) if isinstance(fred_context, Mapping) else {}
    fred_refs = fred_context.get("source_refs")
    fred_refs = list(fred_refs) if isinstance(fred_refs, list) else []
    fallback_from = {
        "source_kind": html_context.get("source_kind") or "bls_release_html",
        "source": html_ref.get("source"),
        "status": html_ref.get("status"),
        "failure_kind": html_ref.get("failure_kind"),
        "source_refs": html_refs,
    }
    fred_context["fallback_from"] = fallback_from
    # Keep both the successful FRED evidence and the blocked/failed BLS HTML
    # attempts in one context so the research layer can explain the source
    # boundary without treating FRED as a BLS publication response.
    fred_context["source_refs"] = [*fred_refs, *html_refs]
    combined_paths = [
        *(_string_list(html_ref.get("attempted_raw_paths"))),
        *(_string_list(fred_ref.get("fred_vintage_raw_paths"))),
    ]
    if fred_ref.get("status") != "unavailable":
        result = dict(fred_ref)
        result["release_context"] = fred_context
        result["fallback_from"] = fallback_from
        result["html_attempt"] = html_context
        if combined_paths:
            result["attempted_raw_paths"] = _unique_strings(combined_paths)
        return result

    # Preserve the original BLS failure as the domain status.  A failed FRED
    # probe is useful provenance, but it must never turn into an available
    # release or erase the official-source failure reason.
    result = dict(html_ref)
    result["fallback_source_kind"] = FRED_VINTAGE_KIND
    result["fallback_failure_kind"] = fred_ref.get("failure_kind") or "http_error"
    if fred_ref.get("reason"):
        result["fallback_reason"] = fred_ref["reason"]
    result["fallback_context"] = fred_context
    fred_paths = _string_list(fred_ref.get("fred_vintage_raw_paths"))
    if fred_paths:
        result["fred_vintage_raw_paths"] = _unique_strings(fred_paths)
        result["attempted_raw_paths"] = _unique_strings([*combined_paths])
    return result


def _collect_fred_vintage_context(
    *,
    client: Any,
    retrieved_date: str,
    storage_root: Path,
    attempted_at: str,
) -> dict[str, Any]:
    """Compare two official FRED PAYEMS vintages without reconstructing BLS."""

    cutoff_day = _validate_retrieved_date(retrieved_date)
    cutoff_month = cutoff_day.strftime("%Y-%m")
    api_key = resolve_runtime_secret("FRED_API_KEY")
    if not api_key:
        return _fred_vintage_unavailable_ref(
            retrieved_date=retrieved_date,
            cutoff_month=cutoff_month,
            attempted_at=attempted_at,
            reason="FRED vintage API key is unavailable",
            failure_kind="missing_api_key",
            source_refs=[],
            raw_paths=[],
        )

    date_params = {
        "series_id": "PAYEMS",
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
    }
    date_response = _fetch_fred_vintage_json(
        client=client,
        endpoint=FRED_VINTAGE_DATES_URL,
        params=date_params,
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        attempted_at=attempted_at,
        archive_symbol="PAYEMS-vintagedates",
    )
    source_refs = [_fred_vintage_source_ref(date_response, attempted_at=attempted_at)]
    raw_paths = _response_raw_paths(date_response)
    if date_response.failure_kind is not None or date_response.payload is None:
        reason = date_response.reason or "FRED vintagedates response unavailable"
        return _fred_vintage_unavailable_ref(
            retrieved_date=retrieved_date,
            cutoff_month=cutoff_month,
            attempted_at=attempted_at,
            reason=reason,
            failure_kind=date_response.failure_kind or "missing_fields",
            source_refs=source_refs,
            raw_paths=raw_paths,
        )

    vintage_dates = _fred_vintage_dates(date_response.payload, cutoff_day=cutoff_day)
    if len(vintage_dates) < 2:
        return _fred_vintage_unavailable_ref(
            retrieved_date=retrieved_date,
            cutoff_month=cutoff_month,
            attempted_at=attempted_at,
            reason="FRED PAYEMS vintagedates returned fewer than two historical dates through cutoff",
            failure_kind="missing_fields",
            source_refs=source_refs,
            raw_paths=raw_paths,
        )
    previous_vintage, current_vintage = vintage_dates[-2:]
    observation_start = (cutoff_day - timedelta(days=450)).isoformat()
    observation_responses: dict[str, _FredVintageResponse] = {}
    for vintage_date in (previous_vintage, current_vintage):
        params = {
            "series_id": "PAYEMS",
            "api_key": api_key,
            "file_type": "json",
            "realtime_start": vintage_date,
            "realtime_end": vintage_date,
            "observation_start": observation_start,
            "observation_end": retrieved_date,
            "sort_order": "asc",
        }
        response = _fetch_fred_vintage_json(
            client=client,
            endpoint=FRED_VINTAGE_OBSERVATIONS_URL,
            params=params,
            storage_root=storage_root,
            retrieved_date=retrieved_date,
            attempted_at=attempted_at,
            archive_symbol=f"PAYEMS-observations-{vintage_date}",
        )
        observation_responses[vintage_date] = response
        source_refs.append(_fred_vintage_source_ref(response, attempted_at=attempted_at, vintage_date=vintage_date))
        raw_paths.extend(_response_raw_paths(response))

    failed_observations = [
        response
        for response in observation_responses.values()
        if response.failure_kind is not None or response.payload is None
    ]
    if failed_observations:
        first_failure = failed_observations[0]
        return _fred_vintage_unavailable_ref(
            retrieved_date=retrieved_date,
            cutoff_month=cutoff_month,
            attempted_at=attempted_at,
            reason=first_failure.reason or "FRED PAYEMS vintage observations unavailable",
            failure_kind=first_failure.failure_kind or "missing_fields",
            source_refs=source_refs,
            raw_paths=raw_paths,
            vintage_date=current_vintage,
            previous_vintage_date=previous_vintage,
        )

    current_observations = _fred_vintage_observation_map(
        observation_responses[current_vintage].payload or {},
        cutoff_day=cutoff_day,
    )
    previous_observations = _fred_vintage_observation_map(
        observation_responses[previous_vintage].payload or {},
        cutoff_day=cutoff_day,
    )
    if not current_observations or not previous_observations:
        return _fred_vintage_unavailable_ref(
            retrieved_date=retrieved_date,
            cutoff_month=cutoff_month,
            attempted_at=attempted_at,
            reason="FRED PAYEMS vintage observations contain no usable monthly values through cutoff",
            failure_kind="missing_fields",
            source_refs=source_refs,
            raw_paths=raw_paths,
            vintage_date=current_vintage,
            previous_vintage_date=previous_vintage,
        )

    latest_month = max(current_observations)
    prior_month = _previous_month(latest_month)
    headline_new_jobs = None
    headline_excerpt = None
    if prior_month in current_observations:
        headline_new_jobs = round(current_observations[latest_month] - current_observations[prior_month], 6)
        headline_excerpt = (
            f"PAYEMS {latest_month}: FRED vintage {current_vintage} value "
            f"{current_observations[latest_month]:g}; prior month {prior_month} value "
            f"{current_observations[prior_month]:g}; change {headline_new_jobs:g} thousand"
        )

    revisions: list[dict[str, Any]] = []
    revision_excerpts: list[str] = []
    for month in (_previous_month(latest_month), _previous_month(_previous_month(latest_month))):
        prior_month = _previous_month(month)
        previous_level = previous_observations.get(month)
        previous_prior_level = previous_observations.get(prior_month)
        revised_level = current_observations.get(month)
        revised_prior_level = current_observations.get(prior_month)
        # PAYEMS levels are not themselves the published monthly payroll
        # change.  Each vintage must first derive its own month-over-month
        # change; only then can the two published vintages be compared.
        if (
            previous_level is None
            or previous_prior_level is None
            or revised_level is None
            or revised_prior_level is None
        ):
            continue
        previous_value = round(previous_level - previous_prior_level, 6)
        revised_value = round(revised_level - revised_prior_level, 6)
        delta = round(revised_value - previous_value, 6)
        direction = "up" if delta > 0 else "down" if delta < 0 else "unchanged"
        excerpt = (
            f"PAYEMS {month} monthly change: FRED vintage {previous_vintage} "
            f"{previous_level:g}-{prior_month} {previous_prior_level:g}={previous_value:g}; "
            f"FRED vintage {current_vintage} {revised_level:g}-{prior_month} "
            f"{revised_prior_level:g}={revised_value:g}; revision {delta:g} thousand"
        )
        revisions.append(
            {
                "observation_month": month,
                "previous_value_thousands": previous_value,
                "revised_value_thousands": revised_value,
                "delta_thousands": delta,
                "value_kind": "monthly_change",
                "unit": "thousand_persons",
                "direction": direction,
                "baseline_kind": "previous_fred_vintage",
                "previous_vintage_date": previous_vintage,
                "current_vintage_date": current_vintage,
                "level_components": {
                    "previous_vintage": {
                        "observation_month": month,
                        "observation_level_thousands": previous_level,
                        "prior_month": prior_month,
                        "prior_month_level_thousands": previous_prior_level,
                    },
                    "current_vintage": {
                        "observation_month": month,
                        "observation_level_thousands": revised_level,
                        "prior_month": prior_month,
                        "prior_month_level_thousands": revised_prior_level,
                    },
                },
                "evidence_excerpt": excerpt,
            }
        )
        revision_excerpts.append(excerpt)

    missing_fields: list[str] = [
        "release_time_local",
        "release_datetime",
        "headline.unemployment_rate",
        "headline.wage_mom_pct",
        "headline.wage_yoy_pct",
        "sector_contributions",
    ]
    if headline_new_jobs is None:
        missing_fields.append("headline.new_jobs_thousands")
    if not revisions:
        missing_fields.append("revisions")
    status = "partial" if headline_new_jobs is not None or revisions else "unavailable"
    if status == "unavailable":
        return _fred_vintage_unavailable_ref(
            retrieved_date=retrieved_date,
            cutoff_month=cutoff_month,
            attempted_at=attempted_at,
            reason="FRED PAYEMS vintages have no adjacent headline change or comparable revisions",
            failure_kind="missing_fields",
            source_refs=source_refs,
            raw_paths=raw_paths,
            vintage_date=current_vintage,
            previous_vintage_date=previous_vintage,
        )
    context = {
        "status": status,
        "source_kind": FRED_VINTAGE_KIND,
        "release_date_kind": "fred_vintage_date",
        "release_date": current_vintage,
        "release_time_local": None,
        "release_timezone": None,
        "release_datetime": None,
        "observation_month": latest_month,
        "vintage_date": current_vintage,
        "previous_vintage_date": previous_vintage,
        "baseline_kind": "previous_fred_vintage",
        "headline": {
            "new_jobs_thousands": headline_new_jobs,
            "unemployment_rate": None,
            "wage_mom_pct": None,
            "wage_yoy_pct": None,
        },
        "revisions": revisions,
        "sector_contributions": [],
        "missing_fields": missing_fields,
        "parser_notes": [
            "FRED PAYEMS monthly changes are computed independently within each dated vintage before revision comparison; this is not a BLS release HTML response.",
            "Release time, industry contributions, and consensus are unavailable from this FRED vintage endpoint.",
        ],
        "evidence_excerpts": {
            "publication": None,
            "headline": headline_excerpt,
            "wages": None,
            "revisions": revision_excerpts,
            "sector_contributions": [],
        },
        "source_refs": source_refs,
    }
    current_response = observation_responses[current_vintage]
    return {
        "symbol": BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL,
        "source": FRED_VINTAGE_SOURCE,
        "source_kind": FRED_VINTAGE_KIND,
        "source_url": current_response.source_url,
        "raw_path": current_response.raw_path,
        "retrieved_at": attempted_at,
        "observation_cutoff_date": retrieved_date,
        "observation_cutoff_month": cutoff_month,
        "observation_month": latest_month,
        "release_date": current_vintage,
        "release_date_kind": "fred_vintage_date",
        "release_datetime": None,
        "release_timezone": None,
        "vintage_date": current_vintage,
        "previous_vintage_date": previous_vintage,
        "status": status,
        "release_context": context,
        "fred_vintage_raw_paths": _unique_strings(raw_paths),
        "vintage_dates": [previous_vintage, current_vintage],
    }


def _fetch_fred_vintage_json(
    *,
    client: Any,
    endpoint: str,
    params: Mapping[str, object],
    storage_root: Path,
    retrieved_date: str,
    attempted_at: str,
    archive_symbol: str,
) -> _FredVintageResponse:
    safe_params = {key: value for key, value in params.items() if key != "api_key"}
    source_url = _fred_vintage_safe_url(endpoint, safe_params)
    try:
        response = _fred_vintage_get(client, endpoint, params)
    except Exception as exc:
        return _FredVintageResponse(
            payload=None,
            source_url=source_url,
            raw_path=None,
            status_code=None,
            failure_kind="http_error",
            reason=f"FRED vintage request failed: {type(exc).__name__}",
        )

    status_code = _response_status_code(response)
    payload = _response_payload(response)
    raw_payload: dict[str, object]
    if payload is not None:
        raw_payload = dict(payload)
    else:
        raw_payload = {
            "_http_status": status_code,
            "_raw_text": str(getattr(response, "text", "") or "")[:2000],
        }
    raw_path = _archive_fred_vintage_payload(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        symbol=archive_symbol,
        payload=raw_payload,
    )
    if status_code >= 400:
        return _FredVintageResponse(
            payload=payload,
            source_url=source_url,
            raw_path=raw_path,
            status_code=status_code,
            failure_kind=_classify_fred_vintage_http_failure(status_code),
            reason=f"FRED vintage endpoint returned HTTP {status_code}",
        )
    if payload is None:
        return _FredVintageResponse(
            payload=None,
            source_url=source_url,
            raw_path=raw_path,
            status_code=status_code,
            failure_kind="parse_error",
            reason="FRED vintage endpoint returned a non-JSON response",
        )
    if payload.get("error_code") not in (None, "", 0, "0"):
        return _FredVintageResponse(
            payload=payload,
            source_url=source_url,
            raw_path=raw_path,
            status_code=status_code,
            failure_kind="http_error",
            reason="FRED vintage endpoint returned an API error",
        )
    return _FredVintageResponse(
        payload=payload,
        source_url=source_url,
        raw_path=raw_path,
        status_code=status_code,
        failure_kind=None,
        reason=None,
    )


def _fred_vintage_get(client: Any, endpoint: str, params: Mapping[str, object]) -> Any:
    getter = getattr(client, "get", None)
    if not callable(getter):
        raise TypeError("FRED vintage client has no GET method")
    try:
        return getter(
            endpoint,
            params=dict(params),
            headers={"Accept": "application/json", "User-Agent": "finance-agent/0.1"},
            follow_redirects=True,
        )
    except TypeError:
        return getter(endpoint, params=dict(params))


def _archive_fred_vintage_payload(
    *,
    storage_root: Path,
    retrieved_date: str,
    symbol: str,
    payload: Mapping[str, object],
) -> str:
    """Archive one FRED response under an exclusive, run-safe raw path."""

    raw_dir = Path(storage_root) / "raw" / "macro" / FRED_VINTAGE_SOURCE / retrieved_date
    raw_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n"
    for _ in range(3):
        stamp = datetime.now(timezone.utc).strftime("%H%M%S%f")
        path = raw_dir / f"{symbol}-{stamp}-{uuid4().hex[:8]}.json"
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(body)
        except FileExistsError:
            continue
        return path.resolve().relative_to(Path(storage_root).resolve()).as_posix()
    raise FileExistsError("Could not allocate an immutable FRED vintage raw path")


def _fred_vintage_dates(payload: Mapping[str, object], *, cutoff_day: date) -> list[str]:
    raw_dates = payload.get("vintage_dates")
    if not isinstance(raw_dates, list):
        return []
    normalized: set[str] = set()
    for raw_date in raw_dates:
        value = str(raw_date or "").strip()
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            continue
        if parsed.isoformat() == value and parsed <= cutoff_day:
            normalized.add(value)
    return sorted(normalized)


def _fred_vintage_observation_map(
    payload: Mapping[str, object],
    *,
    cutoff_day: date,
) -> dict[str, float]:
    raw_observations = payload.get("observations")
    if not isinstance(raw_observations, list):
        return {}
    observations: dict[str, float] = {}
    for raw_observation in raw_observations:
        if not isinstance(raw_observation, Mapping):
            continue
        raw_date = str(raw_observation.get("date") or "").strip()
        try:
            observation_day = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if observation_day.day != 1 or observation_day > cutoff_day:
            continue
        raw_value = raw_observation.get("value")
        if raw_value in (None, "", "."):
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            observations[raw_date[:7]] = value
    return observations


def _fred_vintage_source_ref(
    response: _FredVintageResponse,
    *,
    attempted_at: str,
    vintage_date: str | None = None,
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "source": FRED_VINTAGE_SOURCE,
        "source_kind": FRED_VINTAGE_KIND,
        "source_url": response.source_url,
        "retrieved_at": attempted_at,
        "status": "available" if response.failure_kind is None else "unavailable",
    }
    if response.raw_path:
        ref["raw_path"] = response.raw_path
    if vintage_date:
        ref["vintage_date"] = vintage_date
    if response.failure_kind:
        ref["failure_kind"] = response.failure_kind
    if response.reason:
        ref["reason"] = response.reason
    return ref


def _fred_vintage_unavailable_ref(
    *,
    retrieved_date: str,
    cutoff_month: str,
    attempted_at: str,
    reason: str,
    failure_kind: str,
    source_refs: list[dict[str, Any]],
    raw_paths: list[str],
    vintage_date: str | None = None,
    previous_vintage_date: str | None = None,
) -> dict[str, Any]:
    context = {
        "status": "unavailable",
        "source_kind": FRED_VINTAGE_KIND,
        "release_date_kind": "fred_vintage_date" if vintage_date else None,
        "release_date": vintage_date,
        "release_time_local": None,
        "release_timezone": None,
        "release_datetime": None,
        "observation_month": None,
        "vintage_date": vintage_date,
        "previous_vintage_date": previous_vintage_date,
        "baseline_kind": "previous_fred_vintage" if previous_vintage_date else None,
        "headline": {
            "new_jobs_thousands": None,
            "unemployment_rate": None,
            "wage_mom_pct": None,
            "wage_yoy_pct": None,
        },
        "revisions": [],
        "sector_contributions": [],
        "missing_fields": ["fred_vintage_context"],
        "parser_notes": [reason],
        "evidence_excerpts": {
            "publication": None,
            "headline": None,
            "wages": None,
            "revisions": [],
            "sector_contributions": [],
        },
        "source_refs": source_refs,
    }
    result: dict[str, Any] = {
        "symbol": BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL,
        "source": FRED_VINTAGE_SOURCE,
        "source_kind": FRED_VINTAGE_KIND,
        "source_url": source_refs[-1].get("source_url", FRED_VINTAGE_DATES_URL) if source_refs else FRED_VINTAGE_DATES_URL,
        "retrieved_at": attempted_at,
        "observation_cutoff_date": retrieved_date,
        "observation_cutoff_month": cutoff_month,
        "status": "unavailable",
        "release_context": context,
        "failure_kind": failure_kind,
        "reason": reason,
    }
    if vintage_date:
        result["vintage_date"] = vintage_date
    if previous_vintage_date:
        result["previous_vintage_date"] = previous_vintage_date
    if raw_paths:
        result["fred_vintage_raw_paths"] = _unique_strings(raw_paths)
        result["raw_path"] = raw_paths[-1]
    return result


def _classify_fred_vintage_http_failure(status_code: int | None) -> str:
    if status_code in {401, 403}:
        return "http_forbidden"
    if status_code == 429:
        return "rate_limit"
    return "http_error"


def _fred_vintage_safe_url(endpoint: str, params: Mapping[str, object]) -> str:
    safe_params = {key: value for key, value in params.items() if key != "api_key"}
    return f"{endpoint}?{urlencode(safe_params)}" if safe_params else endpoint


def _response_raw_paths(response: _FredVintageResponse) -> list[str]:
    return [response.raw_path] if response.raw_path else []


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _employment_release_urls(cutoff_day: date) -> list[str]:
    urls = [BLS_EMPLOYMENT_RELEASE_URL]
    for offset in range(BLS_EMPLOYMENT_RELEASE_LOOKBACK_DAYS + 1):
        candidate = cutoff_day - timedelta(days=offset)
        if candidate.weekday() != 4:
            continue
        archive_url = BLS_EMPLOYMENT_RELEASE_ARCHIVE_URL_TEMPLATE.format(date=candidate.strftime("%m%d%Y"))
        if archive_url not in urls:
            urls.append(archive_url)
    return urls


def _release_get(client: Any, url: str) -> Any:
    getter = getattr(client, "get", None)
    if not callable(getter):
        raise TypeError("BLS release client has no GET method")
    try:
        return getter(
            url,
            headers={"Accept": "text/html", "User-Agent": "finance-agent/0.1"},
            follow_redirects=True,
        )
    except TypeError:
        # Small injected clients commonly accept only the URL.
        return getter(url)


def _response_body(response: Any) -> bytes | str | None:
    if response is None:
        return None
    body = getattr(response, "content", None)
    if isinstance(body, bytes):
        return body
    text = getattr(response, "text", None)
    return text if isinstance(text, str) else None


def _archive_release_body(
    *,
    storage_root: Path,
    retrieved_date: str,
    body: bytes | str | None,
) -> str | None:
    if body is None:
        return None
    raw_dir = Path(storage_root) / BLS_EMPLOYMENT_RELEASE_RAW_ROOT / retrieved_date
    raw_dir.mkdir(parents=True, exist_ok=True)
    payload = body if isinstance(body, bytes) else body.encode("utf-8")
    for _ in range(3):
        stamp = datetime.now(timezone.utc).strftime("%H%M%S%f")
        path = raw_dir / f"empsit-{stamp}-{uuid4().hex[:8]}.html"
        try:
            with path.open("xb") as handle:
                handle.write(payload)
        except FileExistsError:
            continue
        return path.resolve().relative_to(Path(storage_root).resolve()).as_posix()
    raise FileExistsError("Could not allocate an immutable Employment release raw path")


def _write_release_metadata(
    *,
    storage_root: Path,
    raw_path: str | None,
    source_url: str,
    retrieved_at: str,
    retrieved_date: str,
    status: str,
    failure_kind: str | None,
    release_date: str | None,
    observation_month: str | None,
) -> None:
    if raw_path is None:
        return
    metadata_path = Path(storage_root) / f"{raw_path}.meta.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "schema_version": "bls_employment_release_raw_metadata.v1",
        "symbol": BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL,
        "source": BLS_EMPLOYMENT_RELEASE_SOURCE,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "retrieved_date": retrieved_date,
        "status": status,
        "release_date": release_date or "unavailable",
        "observation_month": observation_month or "unavailable",
    }
    if failure_kind:
        metadata["failure_kind"] = failure_kind
    try:
        with metadata_path.open("x", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError:
        return


def _classify_release_http_failure(status_code: int | None) -> str:
    if status_code == 403:
        return "http_forbidden"
    if status_code == 429:
        return "rate_limit"
    return "http_error"


def _release_failure_kind(details: list[str]) -> str:
    text = " ".join(details).lower()
    if "http 403" in text:
        return "http_forbidden"
    if "http 429" in text or "rate limit" in text:
        return "rate_limit"
    if "parse_error" in text:
        return "parse_error"
    if "release_is_after_cutoff" in text:
        return "release_mismatch"
    return "http_error"


def _collect_with_client(
    *,
    client: Any,
    fred_client: Any | None,
    use_fred_api: bool,
    requested_series: tuple[str, ...],
    retrieved_date: str,
    storage_root: Path,
    start_year: int,
    end_year: int,
    attempted_at: str,
) -> CollectorResult:
    if callable(getattr(client, "post", None)):
        initial = _collect_with_batch_client(
            client=client,
            requested_series=requested_series,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            start_year=start_year,
            end_year=end_year,
            attempted_at=attempted_at,
        )
    else:
        initial = _collect_with_get_client(
            client=client,
            requested_series=requested_series,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            start_year=start_year,
            end_year=end_year,
            attempted_at=attempted_at,
        )
    return _apply_fred_fallbacks(
        initial=initial,
        client=fred_client,
        use_fred_api=use_fred_api,
        requested_series=requested_series,
        retrieved_date=retrieved_date,
        storage_root=storage_root,
        start_year=start_year,
        end_year=end_year,
        attempted_at=attempted_at,
    )


def _collect_with_batch_client(
    *,
    client: Any,
    requested_series: tuple[str, ...],
    retrieved_date: str,
    storage_root: Path,
    start_year: int,
    end_year: int,
    attempted_at: str,
) -> CollectorResult:
    source_url = bls_batch_url(start_year, end_year)
    request_payload = {
        "seriesid": list(requested_series),
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    try:
        response = client.post(BLS_API_BASE_URL, json=request_payload)
    except Exception as exc:
        return _request_exception_result(
            requested_series=requested_series,
            retrieved_date=retrieved_date,
            source_url=source_url,
            storage_root=storage_root,
            attempted_at=attempted_at,
            exc=exc,
        )

    status_code = _response_status_code(response)
    payload = _response_payload(response)
    if status_code >= 400:
        return _response_failure_result(
            requested_series=requested_series,
            retrieved_date=retrieved_date,
            source_url=source_url,
            storage_root=storage_root,
            attempted_at=attempted_at,
            payload=payload,
            status_code=status_code,
            failure_kind=_classify_http_failure(status_code),
        )
    if payload is None:
        return _unavailable_for_symbols(
            requested_series=requested_series,
            retrieved_date=retrieved_date,
            source_url=source_url,
            attempted_at=attempted_at,
            reason="BLS request or parse failed: response body is not a JSON object",
            failure_kind="missing_fields",
        )

    return _collect_payload_for_symbols(
        payload=payload,
        requested_series=requested_series,
        retrieved_date=retrieved_date,
        storage_root=storage_root,
        source_url=source_url,
        attempted_at=attempted_at,
    )


def _collect_with_get_client(
    *,
    client: Any,
    requested_series: tuple[str, ...],
    retrieved_date: str,
    storage_root: Path,
    start_year: int,
    end_year: int,
    attempted_at: str,
) -> CollectorResult:
    results: list[CollectorResult] = []
    for symbol in requested_series:
        source_url = bls_series_url(symbol, start_year, end_year)
        try:
            response = client.get(source_url)
        except Exception as exc:
            results.append(
                _request_exception_result(
                    requested_series=(symbol,),
                    retrieved_date=retrieved_date,
                    source_url=source_url,
                    storage_root=storage_root,
                    attempted_at=attempted_at,
                    exc=exc,
                )
            )
            continue

        status_code = _response_status_code(response)
        payload = _response_payload(response)
        if status_code >= 400:
            results.append(
                _response_failure_result(
                    requested_series=(symbol,),
                    retrieved_date=retrieved_date,
                    source_url=source_url,
                    storage_root=storage_root,
                    attempted_at=attempted_at,
                    payload=payload,
                    status_code=status_code,
                    failure_kind=_classify_http_failure(status_code),
                )
            )
            continue
        if payload is None:
            results.append(
                _unavailable_for_symbols(
                    requested_series=(symbol,),
                    retrieved_date=retrieved_date,
                    source_url=source_url,
                    attempted_at=attempted_at,
                    reason="BLS request or parse failed: response body is not a JSON object",
                    failure_kind="missing_fields",
                )
            )
            continue
        results.append(
            _collect_payload_for_symbols(
                payload=payload,
                requested_series=(symbol,),
                retrieved_date=retrieved_date,
                storage_root=storage_root,
                source_url=source_url,
                attempted_at=attempted_at,
            )
        )
    return _combine_results(results)


def _collect_payload_for_symbols(
    *,
    payload: Mapping[str, object],
    requested_series: tuple[str, ...],
    retrieved_date: str,
    storage_root: Path,
    source_url: str,
    attempted_at: str,
) -> CollectorResult:
    results = [
        collect_bls_series_from_payload(
            symbol=symbol,
            payload=payload,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            source_url=source_url,
            retrieved_at=attempted_at,
        )
        for symbol in requested_series
    ]
    return _combine_results(results)


def _request_exception_result(
    *,
    requested_series: tuple[str, ...],
    retrieved_date: str,
    source_url: str,
    storage_root: Path,
    attempted_at: str,
    exc: Exception,
) -> CollectorResult:
    response = getattr(exc, "response", None)
    status_code = _response_status_code(response) if response is not None else None
    failure_kind = _classify_http_failure(status_code) if status_code is not None else "http_error"
    payload = _response_payload(response) if response is not None else None
    raw_paths = _archive_failure_payloads(
        requested_series=requested_series,
        retrieved_date=retrieved_date,
        storage_root=storage_root,
        source_url=source_url,
        retrieved_at=attempted_at,
        payload=payload,
        failure_kind=failure_kind,
    )
    refs = [
        _source_ref(
            symbol=symbol,
            source_url=source_url,
            raw_path=raw_paths.get(symbol),
            retrieved_at=attempted_at,
            observation_cutoff_date=retrieved_date,
            observation_cutoff_month=retrieved_date[:7],
            observation_month=None,
            status="unavailable",
            reason=f"BLS request or parse failed: {type(exc).__name__}: {exc}",
            failure_kind=failure_kind,
        )
        for symbol in requested_series
    ]
    return CollectorResult(points=[], unavailable_symbols=list(requested_series), source_refs=refs)


def _response_failure_result(
    *,
    requested_series: tuple[str, ...],
    retrieved_date: str,
    source_url: str,
    storage_root: Path,
    attempted_at: str,
    payload: Mapping[str, object] | None,
    status_code: int,
    failure_kind: str,
) -> CollectorResult:
    raw_paths = _archive_failure_payloads(
        requested_series=requested_series,
        retrieved_date=retrieved_date,
        storage_root=storage_root,
        source_url=source_url,
        retrieved_at=attempted_at,
        payload=payload,
        failure_kind=failure_kind,
    )
    message = _payload_message(payload)
    suffix = f": {message}" if message else ""
    refs = [
        _source_ref(
            symbol=symbol,
            source_url=source_url,
            raw_path=raw_paths.get(symbol),
            retrieved_at=attempted_at,
            observation_cutoff_date=retrieved_date,
            observation_cutoff_month=retrieved_date[:7],
            observation_month=None,
            status="unavailable",
            reason=f"BLS request or parse failed: HTTP {status_code}{suffix}",
            failure_kind=failure_kind,
        )
        for symbol in requested_series
    ]
    return CollectorResult(points=[], unavailable_symbols=list(requested_series), source_refs=refs)


def _unavailable_for_symbols(
    *,
    requested_series: tuple[str, ...],
    retrieved_date: str,
    source_url: str,
    attempted_at: str,
    reason: str,
    failure_kind: str,
) -> CollectorResult:
    refs = [
        _source_ref(
            symbol=symbol,
            source_url=source_url,
            raw_path=None,
            retrieved_at=attempted_at,
            observation_cutoff_date=retrieved_date,
            observation_cutoff_month=retrieved_date[:7],
            observation_month=None,
            status="unavailable",
            reason=reason,
            failure_kind=failure_kind,
        )
        for symbol in requested_series
    ]
    return CollectorResult(points=[], unavailable_symbols=list(requested_series), source_refs=refs)


def _archive_failure_payloads(
    *,
    requested_series: tuple[str, ...],
    retrieved_date: str,
    storage_root: Path,
    source_url: str,
    retrieved_at: str,
    payload: Mapping[str, object] | None,
    failure_kind: str,
) -> dict[str, str]:
    if payload is None:
        return {}
    paths: dict[str, str] = {}
    for symbol in requested_series:
        raw_path = _archive_bls_payload(
            storage_root=storage_root,
            retrieved_date=retrieved_date,
            symbol=symbol,
            payload=dict(payload),
        )
        _write_bls_metadata(
            storage_root=storage_root,
            raw_path=raw_path,
            symbol=symbol,
            source_url=source_url,
            retrieved_at=retrieved_at,
            retrieved_date=retrieved_date,
            cutoff_month=retrieved_date[:7],
            latest_observation_month=None,
            status="unavailable",
            failure_kind=failure_kind,
        )
        paths[symbol] = raw_path
    return paths


def _archive_bls_payload(
    *,
    storage_root: Path,
    retrieved_date: str,
    symbol: str,
    payload: dict[str, object],
) -> str:
    """Write one BLS response with an exclusive, unique raw path."""

    raw_dir = Path(storage_root) / "raw" / "macro" / "bls" / retrieved_date
    raw_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    for _ in range(3):
        stamp = datetime.now(timezone.utc).strftime("%H%M%S%f")
        path = raw_dir / f"{symbol}-{stamp}-{uuid4().hex[:8]}.json"
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(body)
        except FileExistsError:
            continue
        return path.resolve().relative_to(Path(storage_root).resolve()).as_posix()
    raise FileExistsError(f"Could not allocate an immutable BLS raw path for {symbol}")


def _apply_fred_fallbacks(
    *,
    initial: CollectorResult,
    client: Any,
    use_fred_api: bool,
    requested_series: tuple[str, ...],
    retrieved_date: str,
    storage_root: Path,
    start_year: int,
    end_year: int,
    attempted_at: str,
) -> CollectorResult:
    refs_by_symbol = {
        str(ref.get("symbol")): dict(ref)
        for ref in initial.source_refs
        if isinstance(ref, Mapping) and ref.get("symbol")
    }
    points_by_symbol: dict[str, list[MacroPoint]] = {symbol: [] for symbol in requested_series}
    for point in initial.points:
        points_by_symbol.setdefault(point.symbol, []).append(point)

    # A BLS connection failure is as unusable as a quota response for this
    # read-only domain.  Try the official FRED mirror for every series that
    # has no usable BLS observations, while preserving the original BLS
    # failure in the returned passport.  This also covers a successful HTTP
    # envelope that contains no requested series (a common partial response).
    fallback_candidates = [
        symbol
        for symbol in requested_series
        if symbol in refs_by_symbol
        and symbol in initial.unavailable_symbols
        and str(refs_by_symbol[symbol].get("failure_kind") or "")
        in {"rate_limit", "http_error", "http_forbidden", "missing_fields", "parse_error"}
    ]
    if not fallback_candidates:
        return initial

    cache_rejections: dict[str, str] = {}
    for symbol in fallback_candidates:
        cached, rejection = _load_cached_series(
            symbol=symbol,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            attempted_at=attempted_at,
        )
        if cached is None:
            cache_rejections[symbol] = rejection
            continue
        original_ref = refs_by_symbol[symbol]
        points_by_symbol[symbol] = [
            MacroPoint(
                symbol=symbol,
                date=observation.point_date,
                value=observation.value,
                source=BLS_SOURCE,
                source_url=cached.source_url,
                retrieved_at=cached.retrieved_at,
                raw_path=cached.raw_path,
            )
            for observation in cached.observations
        ]
        refs_by_symbol[symbol] = _source_ref(
            symbol=symbol,
            source_url=cached.source_url,
            raw_path=cached.raw_path,
            retrieved_at=cached.retrieved_at,
            observation_cutoff_date=retrieved_date,
            observation_cutoff_month=retrieved_date[:7],
            observation_month=cached.latest_observation_month,
            status="available",
            reason=f"BLS upstream fallback used same-storage raw: {original_ref.get('reason', 'upstream failure')}",
            cache_used=True,
            fallback_source="same_storage_raw",
            fallback_reason=str(original_ref.get("reason") or "BLS upstream failure"),
            cache_age_days=cached.cache_age_days,
            cache_original_retrieved_at=cached.retrieved_at,
            collection_attempted_at=attempted_at,
            requested_source_url=str(original_ref.get("source_url") or ""),
            unit=BLS_SERIES_BY_ID[symbol].unit,
        )

    unresolved = [symbol for symbol in fallback_candidates if refs_by_symbol[symbol].get("status") != "available"]
    fred_outcome = _empty_fred_outcome()
    if unresolved:
        fred_outcome = _collect_fred_mirror(
            client=client,
            use_fred_api=use_fred_api,
            requested_series=tuple(unresolved),
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            start_year=start_year,
            end_year=end_year,
            attempted_at=attempted_at,
            upstream_reasons={
                symbol: str(refs_by_symbol[symbol].get("reason") or "BLS upstream failure")
                for symbol in unresolved
            },
            upstream_failure_kinds={
                symbol: str(refs_by_symbol[symbol].get("failure_kind") or "http_error")
                for symbol in unresolved
            },
        )
        for symbol, points in fred_outcome.points_by_symbol.items():
            points_by_symbol[symbol] = points
            fred_ref = dict(fred_outcome.refs_by_symbol[symbol])
            original_ref = refs_by_symbol[symbol]
            # Keep the failed BLS attempt alongside the successful mirror
            # passport.  Consumers can therefore tell that FRED is a
            # fallback rather than silently treating it as the primary BLS
            # response.
            fred_ref["upstream_source"] = original_ref.get("source") or BLS_SOURCE
            fred_ref["upstream_source_url"] = original_ref.get("source_url")
            fred_ref["upstream_raw_path"] = original_ref.get("raw_path")
            fred_ref["upstream_status"] = original_ref.get("status")
            fred_ref["upstream_failure_kind"] = (
                original_ref.get("failure_kind")
                or fred_ref.get("upstream_failure_kind")
            )
            fred_ref["upstream_reason"] = (
                original_ref.get("reason")
                or fred_ref.get("upstream_reason")
            )
            fred_ref["cache_rejection_reason"] = cache_rejections.get(
                symbol,
                "no_successful_same_storage_raw",
            )
            refs_by_symbol[symbol] = fred_ref

    for symbol in unresolved:
        if refs_by_symbol[symbol].get("status") == "available":
            continue
        ref = dict(refs_by_symbol[symbol])
        ref["cache_used"] = False
        ref["cache_rejection_reason"] = cache_rejections.get(symbol, "no_successful_same_storage_raw")
        if fred_outcome.failure_kind is not None:
            ref["fallback_failure_kind"] = fred_outcome.failure_kind
        if fred_outcome.reason:
            ref["fallback_reason"] = fred_outcome.reason
        refs_by_symbol[symbol] = ref

    ordered_refs = [refs_by_symbol[symbol] for symbol in requested_series if symbol in refs_by_symbol]
    ordered_points = [point for symbol in requested_series for point in points_by_symbol.get(symbol, [])]
    unavailable = [
        symbol
        for symbol in requested_series
        if refs_by_symbol.get(symbol, {}).get("status") != "available"
    ]
    return CollectorResult(points=ordered_points, unavailable_symbols=unavailable, source_refs=ordered_refs)


def _load_cached_series(
    *,
    symbol: str,
    retrieved_date: str,
    storage_root: Path,
    attempted_at: str,
) -> tuple[_CachedSeries | None, str]:
    cutoff_day = _validate_retrieved_date(retrieved_date)
    cutoff_month = normalize_bls_cutoff_month(retrieved_date)
    storage_root_path = Path(storage_root).resolve()
    raw_root = (storage_root_path / "raw" / "macro" / "bls").resolve()
    try:
        raw_root.relative_to(storage_root_path)
    except ValueError:
        return None, "outside_storage_root"
    if not raw_root.exists() or not raw_root.is_dir():
        return None, "no_successful_same_storage_raw"

    attempted_dt = datetime.fromisoformat(_validated_retrieved_at(attempted_at))
    candidates = sorted(raw_root.rglob(f"{symbol}-*.json"), key=lambda path: path.as_posix())
    if not candidates:
        return None, "no_successful_same_storage_raw"
    reasons: set[str] = set()
    valid: list[_CachedSeries] = []
    for candidate in candidates:
        try:
            resolved_candidate = candidate.resolve()
            resolved_candidate.relative_to(raw_root)
        except (OSError, ValueError):
            reasons.add("outside_storage_root")
            continue
        if not candidate.is_file() or candidate.name.endswith(BLS_RAW_METADATA_SUFFIX):
            continue
        metadata_path = Path(f"{candidate}{BLS_RAW_METADATA_SUFFIX}")
        if not metadata_path.is_file():
            reasons.add("missing_provenance_sidecar")
            continue
        try:
            metadata_path.resolve().relative_to(raw_root)
        except (OSError, ValueError):
            reasons.add("outside_storage_root")
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            reasons.add("invalid_provenance")
            continue
        if not isinstance(metadata, Mapping):
            reasons.add("invalid_provenance")
            continue
        if (
            metadata.get("schema_version") != "bls_raw_metadata.v1"
            or metadata.get("source") != BLS_SOURCE
            or metadata.get("symbol") != symbol
            or metadata.get("status") != "available"
        ):
            reasons.add("not_successful_bls_raw")
            continue
        try:
            candidate_retrieved_at = datetime.fromisoformat(
                _validated_retrieved_at(str(metadata["retrieved_at"]))
            )
            candidate_retrieved_date = _validate_retrieved_date(str(metadata["retrieved_date"]))
            candidate_cutoff_month = normalize_bls_cutoff_month(str(metadata["observation_cutoff_month"]))
            metadata_latest = normalize_bls_cutoff_month(str(metadata["latest_observation_month"]))
        except (KeyError, TypeError, ValueError, BLSParseError):
            reasons.add("invalid_provenance")
            continue
        candidate_relative = resolved_candidate.relative_to(storage_root_path)
        if len(candidate_relative.parts) < 2 or candidate_relative.parts[-2] != candidate_retrieved_date.isoformat():
            reasons.add("metadata_mismatch")
            continue
        if candidate_retrieved_at > attempted_dt or candidate_retrieved_at.date() > cutoff_day:
            reasons.add("future_retrieved_at")
            continue
        age_days = (attempted_dt - candidate_retrieved_at).total_seconds() / 86400.0
        if age_days > BLS_CACHE_MAX_AGE_DAYS:
            reasons.add("expired")
            continue
        if candidate_retrieved_date > cutoff_day:
            reasons.add("future_retrieved_date")
            continue
        if candidate_cutoff_month is None or metadata_latest is None:
            reasons.add("invalid_report_month")
            continue
        if candidate_cutoff_month > cutoff_month:
            reasons.add("future_observation_cutoff")
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            reasons.add("invalid_payload")
            continue
        if not isinstance(payload, Mapping):
            reasons.add("invalid_payload")
            continue
        try:
            all_observations = parse_bls_series_payload(payload, series_id=symbol, cutoff_month=None)
        except BLSParseError:
            reasons.add("invalid_payload")
            continue
        if not all_observations:
            reasons.add("no_observations")
            continue
        actual_latest = all_observations[-1].observation_month
        if actual_latest != metadata_latest:
            reasons.add("metadata_mismatch")
            continue
        if actual_latest > cutoff_month:
            reasons.add("future_report_month")
            continue
        if actual_latest < _previous_month(cutoff_month):
            reasons.add("stale_report_month")
            continue
        try:
            observations = parse_bls_series_payload(
                payload,
                series_id=symbol,
                cutoff_month=cutoff_month,
            )
        except BLSParseError:
            reasons.add("invalid_payload")
            continue
        if not observations:
            reasons.add("no_observations_through_cutoff")
            continue
        source_url = str(metadata.get("source_url") or "")
        if not source_url:
            reasons.add("invalid_provenance")
            continue
        raw_path = resolved_candidate.relative_to(storage_root_path).as_posix()
        valid.append(
            _CachedSeries(
                symbol=symbol,
                observations=tuple(observations),
                raw_path=raw_path,
                source_url=source_url,
                retrieved_at=candidate_retrieved_at.isoformat(),
                latest_observation_month=observations[-1].observation_month,
                cache_age_days=round(max(0.0, age_days), 6),
            )
        )

    if not valid:
        return None, ",".join(sorted(reasons)) or "no_successful_same_storage_raw"
    valid.sort(key=lambda item: (item.retrieved_at, item.raw_path), reverse=True)
    return valid[0], ""


def _collect_fred_mirror(
    *,
    client: Any,
    use_fred_api: bool,
    requested_series: tuple[str, ...],
    retrieved_date: str,
    storage_root: Path,
    start_year: int,
    end_year: int,
    attempted_at: str,
    upstream_reasons: Mapping[str, str],
    upstream_failure_kinds: Mapping[str, str] | None = None,
) -> _FredOutcome:
    if use_fred_api:
        api_outcome = _collect_fred_api_series(
            requested_series=requested_series,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            attempted_at=attempted_at,
            upstream_reasons=upstream_reasons,
            upstream_failure_kinds=upstream_failure_kinds,
        )
        # The API-key collector is the preferred existing FRED path, but a
        # failed/missing key must not make the keyless official Graph CSV
        # source unreachable.  Reuse the same client and only prefer the
        # graph result when it actually supplies observations.
        graph_outcome = _collect_fred_graph_mirror(
            client=client,
            requested_series=requested_series,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            start_year=start_year,
            end_year=end_year,
            attempted_at=attempted_at,
            upstream_reasons=upstream_reasons,
            upstream_failure_kinds=upstream_failure_kinds,
        )
        if graph_outcome.points_by_symbol:
            return graph_outcome
        return api_outcome
    return _collect_fred_graph_mirror(
        client=client,
        requested_series=requested_series,
        retrieved_date=retrieved_date,
        storage_root=storage_root,
        start_year=start_year,
        end_year=end_year,
        attempted_at=attempted_at,
        upstream_reasons=upstream_reasons,
        upstream_failure_kinds=upstream_failure_kinds,
    )


def _collect_fred_api_series(
    *,
    requested_series: tuple[str, ...],
    retrieved_date: str,
    storage_root: Path,
    attempted_at: str,
    upstream_reasons: Mapping[str, str],
    upstream_failure_kinds: Mapping[str, str] | None = None,
) -> _FredOutcome:
    """Use the existing FRED collector/API-key path for the live fallback."""

    from apps.collectors.fred.collector import collect_fred_series

    fred_series = tuple(BLS_FRED_MIRROR_SYMBOLS[symbol] for symbol in requested_series)
    try:
        result = collect_fred_series(
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            symbols=fred_series,
        )
    except Exception as exc:
        return _FredOutcome(
            points_by_symbol={},
            refs_by_symbol={},
            failure_kind="http_error",
            reason=f"official FRED collector failed: {type(exc).__name__}: {exc}",
        )

    refs_by_fred_symbol = {
        str(ref.get("symbol")): ref
        for ref in result.source_refs
        if isinstance(ref, Mapping) and ref.get("symbol")
    }
    cutoff_day = _validate_retrieved_date(retrieved_date)
    cutoff_month = normalize_bls_cutoff_month(retrieved_date)
    points_by_symbol: dict[str, list[MacroPoint]] = {}
    refs_by_symbol: dict[str, dict[str, Any]] = {}
    for symbol in requested_series:
        fred_symbol = BLS_FRED_MIRROR_SYMBOLS[symbol]
        source_points = [
            point
            for point in result.points
            if point.symbol == fred_symbol
            and _is_monthly_cutoff_point(point.date, cutoff_day=cutoff_day, cutoff_month=cutoff_month)
        ]
        source_points.sort(key=lambda point: point.date)
        if not source_points or source_points[-1].date[:7] < _previous_month(cutoff_month):
            continue
        original_ref = refs_by_fred_symbol.get(fred_symbol, {})
        source_url = str(original_ref.get("source_url") or source_points[-1].source_url)
        raw_path = str(original_ref.get("raw_path") or source_points[-1].raw_path)
        retrieved_at = str(original_ref.get("retrieved_at") or source_points[-1].retrieved_at or attempted_at)
        points_by_symbol[symbol] = [
            MacroPoint(
                symbol=symbol,
                date=point.date,
                value=point.value,
                source=FRED_MIRROR_SOURCE,
                source_url=source_url,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
            )
            for point in source_points
        ]
        refs_by_symbol[symbol] = _source_ref(
            symbol=symbol,
            source_url=source_url,
            raw_path=raw_path,
            retrieved_at=retrieved_at,
            observation_cutoff_date=retrieved_date,
            observation_cutoff_month=cutoff_month,
            observation_month=source_points[-1].date[:7],
            status="available",
            reason="BLS upstream failure fallback used existing official FRED collector/API; source is FRED",
            source=FRED_MIRROR_SOURCE,
            cache_used=False,
            fallback_source=FRED_API_MIRROR_KIND,
            source_series=fred_symbol,
            unit=BLS_SERIES_BY_ID[symbol].unit,
            upstream_failure_kind=(upstream_failure_kinds or {}).get(symbol, "rate_limit"),
            upstream_reason=upstream_reasons.get(symbol, "BLS API fallback"),
        )
    missing_symbols = [symbol for symbol in requested_series if symbol not in points_by_symbol]
    if missing_symbols:
        source_failures = [
            str(ref.get("reason"))
            for fred_symbol, ref in refs_by_fred_symbol.items()
            if fred_symbol in {BLS_FRED_MIRROR_SYMBOLS[symbol] for symbol in missing_symbols}
            and ref.get("reason")
        ]
        detail = f"; {source_failures[0]}" if source_failures else ""
        return _FredOutcome(
            points_by_symbol=points_by_symbol,
            refs_by_symbol=refs_by_symbol,
            failure_kind="missing_fields",
            reason=f"official FRED collector has no usable monthly values for: {', '.join(missing_symbols)}{detail}",
        )
    return _FredOutcome(points_by_symbol=points_by_symbol, refs_by_symbol=refs_by_symbol, failure_kind=None, reason=None)


def _is_monthly_cutoff_point(point_date: str, *, cutoff_day: date, cutoff_month: str) -> bool:
    try:
        observation_day = date.fromisoformat(point_date)
    except ValueError:
        return False
    return observation_day.day == 1 and observation_day <= cutoff_day and point_date[:7] <= cutoff_month


def _collect_fred_graph_mirror(
    *,
    client: Any,
    requested_series: tuple[str, ...],
    retrieved_date: str,
    storage_root: Path,
    start_year: int,
    end_year: int,
    attempted_at: str,
    upstream_reasons: Mapping[str, str],
    upstream_failure_kinds: Mapping[str, str] | None = None,
) -> _FredOutcome:
    if not callable(getattr(client, "get", None)):
        return _FredOutcome(
            points_by_symbol={},
            refs_by_symbol={},
            failure_kind="http_error",
            reason="official FRED mirror client has no GET method",
        )
    fred_series = tuple(BLS_FRED_MIRROR_SYMBOLS[symbol] for symbol in requested_series)
    source_url = _fred_mirror_url(
        fred_series=fred_series,
        start_year=start_year,
        end_year=end_year,
        retrieved_date=retrieved_date,
    )
    try:
        response = client.get(source_url)
    except Exception as exc:
        return _FredOutcome(
            points_by_symbol={},
            refs_by_symbol={},
            failure_kind="http_error",
            reason=f"official FRED mirror request failed: {type(exc).__name__}: {exc}",
        )

    raw_path = _archive_fred_response(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        response=response,
    )
    status_code = _response_status_code(response)
    if status_code >= 400:
        return _FredOutcome(
            points_by_symbol={},
            refs_by_symbol={},
            failure_kind="http_error",
            reason=f"official FRED mirror returned HTTP {status_code}",
        )
    csv_text = getattr(response, "text", None)
    if not isinstance(csv_text, str):
        return _FredOutcome(
            points_by_symbol={},
            refs_by_symbol={},
            failure_kind="missing_fields",
            reason="official FRED mirror response has no text body",
        )
    try:
        rows = list(csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"))))
    except (csv.Error, TypeError, ValueError) as exc:
        return _FredOutcome(
            points_by_symbol={},
            refs_by_symbol={},
            failure_kind="parse_error",
            reason=f"official FRED mirror CSV parse failed: {type(exc).__name__}: {exc}",
        )
    fieldnames = set(rows[0].keys()) if rows else set()
    date_field = next((field for field in ("observation_date", "DATE", "date") if field in fieldnames), None)
    if date_field is None:
        return _FredOutcome(
            points_by_symbol={},
            refs_by_symbol={},
            failure_kind="missing_fields",
            reason="official FRED mirror CSV is missing observation_date",
        )

    points_by_symbol: dict[str, list[MacroPoint]] = {}
    refs_by_symbol: dict[str, dict[str, Any]] = {}
    cutoff_day = _validate_retrieved_date(retrieved_date)
    cutoff_month = normalize_bls_cutoff_month(retrieved_date)
    for symbol in requested_series:
        fred_symbol = BLS_FRED_MIRROR_SYMBOLS[symbol]
        if fred_symbol not in fieldnames:
            continue
        observations: list[tuple[str, float]] = []
        for row in rows:
            date_value = str(row.get(date_field) or "").strip()
            try:
                observation_day = date.fromisoformat(date_value)
            except ValueError:
                continue
            if observation_day.day != 1 or observation_day > cutoff_day:
                continue
            observation_month = date_value[:7]
            if observation_month > cutoff_month:
                continue
            raw_value = row.get(fred_symbol)
            if raw_value in (None, "", "."):
                continue
            try:
                numeric_value = float(str(raw_value).strip())
            except (TypeError, ValueError):
                continue
            if not math.isfinite(numeric_value):
                continue
            observations.append((date_value, numeric_value))
        observations.sort(key=lambda item: item[0])
        if (
            not observations
            or observations[-1][0][:7] < _previous_month(cutoff_month)
            or raw_path is None
        ):
            continue
        points_by_symbol[symbol] = [
            MacroPoint(
                symbol=symbol,
                date=observation_date,
                value=value,
                source=FRED_MIRROR_SOURCE,
                source_url=source_url,
                retrieved_at=attempted_at,
                raw_path=raw_path,
            )
            for observation_date, value in observations
        ]
        refs_by_symbol[symbol] = _source_ref(
            symbol=symbol,
            source_url=source_url,
            raw_path=raw_path,
            retrieved_at=attempted_at,
            observation_cutoff_date=retrieved_date,
            observation_cutoff_month=cutoff_month,
            observation_month=observations[-1][0][:7],
            status="available",
            reason="BLS upstream failure fallback used official FRED Graph CSV; source is FRED",
            source=FRED_MIRROR_SOURCE,
            cache_used=False,
            fallback_source=FRED_MIRROR_KIND,
            source_series=fred_symbol,
            unit=BLS_SERIES_BY_ID[symbol].unit,
            upstream_failure_kind=(upstream_failure_kinds or {}).get(symbol, "rate_limit"),
            upstream_reason=upstream_reasons.get(symbol, "BLS API fallback"),
        )
    missing_symbols = [symbol for symbol in requested_series if symbol not in points_by_symbol]
    if missing_symbols:
        return _FredOutcome(
            points_by_symbol=points_by_symbol,
            refs_by_symbol=refs_by_symbol,
            failure_kind="missing_fields",
            reason=f"official FRED mirror has no usable monthly values for: {', '.join(missing_symbols)}",
        )
    return _FredOutcome(points_by_symbol=points_by_symbol, refs_by_symbol=refs_by_symbol, failure_kind=None, reason=None)


def _empty_fred_outcome() -> _FredOutcome:
    return _FredOutcome(points_by_symbol={}, refs_by_symbol={}, failure_kind=None, reason=None)


def _archive_fred_response(*, storage_root: Path, retrieved_date: str, response: Any) -> str | None:
    body = getattr(response, "content", None)
    if not isinstance(body, bytes):
        text = getattr(response, "text", None)
        if not isinstance(text, str):
            return None
        body = text.encode("utf-8")
    raw_dir = Path(storage_root) / "raw" / "macro" / "fred" / retrieved_date
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%H%M%S%f")
    path = raw_dir / f"bls-employment-mirror-{stamp}-{uuid4().hex[:8]}.csv"
    with path.open("xb") as handle:
        handle.write(body)
    return path.resolve().relative_to(Path(storage_root).resolve()).as_posix()


def _fred_mirror_url(*, fred_series: tuple[str, ...], start_year: int, end_year: int, retrieved_date: str) -> str:
    start_date = f"{start_year:04d}-01-01"
    end_date = min(_validate_retrieved_date(retrieved_date), date(end_year, 12, 31)).isoformat()
    return f"{FRED_GRAPH_CSV_URL}?{urlencode({'id': ','.join(fred_series), 'cosd': start_date, 'coed': end_date})}"


def _combine_results(results: list[CollectorResult]) -> CollectorResult:
    points: list[MacroPoint] = []
    unavailable: list[str] = []
    refs: list[dict[str, Any]] = []
    for result in results:
        points.extend(result.points)
        unavailable.extend(result.unavailable_symbols)
        refs.extend(result.source_refs)
    return CollectorResult(points=points, unavailable_symbols=unavailable, source_refs=refs)


def _unavailable_result(
    *,
    symbol: str,
    source_url: str,
    raw_path: str | None,
    retrieved_at: str,
    retrieved_date: str,
    reason: str,
    failure_kind: str,
) -> CollectorResult:
    return CollectorResult(
        points=[],
        unavailable_symbols=[symbol],
        source_refs=[
            _source_ref(
                symbol=symbol,
                source_url=source_url,
                raw_path=raw_path,
                retrieved_at=retrieved_at,
                observation_cutoff_date=retrieved_date,
                observation_cutoff_month=retrieved_date[:7],
                observation_month=None,
                status="unavailable",
                reason=reason,
                failure_kind=failure_kind,
            )
        ],
    )


def _source_ref(
    *,
    symbol: str,
    source_url: str,
    raw_path: str | None,
    retrieved_at: str,
    observation_cutoff_date: str,
    observation_cutoff_month: str,
    observation_month: str | None,
    status: str,
    reason: str | None,
    source: str = BLS_SOURCE,
    cache_used: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "symbol": symbol,
        "source": source,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "observation_cutoff_date": observation_cutoff_date,
        "observation_cutoff_month": observation_cutoff_month,
        "release_date": "unavailable",
        "vintage_status": "unavailable",
        "status": status,
        "latest_observation_month": observation_month or "unavailable",
        "cache_used": cache_used,
    }
    if raw_path is not None:
        ref["raw_path"] = raw_path
    if reason:
        ref["reason"] = reason
    for key, value in extra.items():
        if value is not None:
            ref[key] = value
    return ref


def _write_bls_metadata(
    *,
    storage_root: Path,
    raw_path: str,
    symbol: str,
    source_url: str,
    retrieved_at: str,
    retrieved_date: str,
    cutoff_month: str,
    latest_observation_month: str | None,
    status: str,
    failure_kind: str | None,
) -> None:
    metadata_path = Path(storage_root) / f"{raw_path}{BLS_RAW_METADATA_SUFFIX}"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "schema_version": "bls_raw_metadata.v1",
        "symbol": symbol,
        "source": BLS_SOURCE,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "retrieved_date": retrieved_date,
        "observation_cutoff_month": cutoff_month,
        "latest_observation_month": latest_observation_month or "unavailable",
        "status": status,
    }
    if failure_kind is not None:
        metadata["failure_kind"] = failure_kind
    try:
        with metadata_path.open("x", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError:
        # A pre-existing sidecar is immutable. The raw archive itself has a
        # unique name, so this is only a collision-safe no-overwrite guard.
        return


def _response_payload(response: Any) -> Mapping[str, object] | None:
    if response is None or not callable(getattr(response, "json", None)):
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    return payload if isinstance(payload, Mapping) else None


def _response_status_code(response: Any) -> int:
    try:
        return int(getattr(response, "status_code", 200) or 200)
    except (TypeError, ValueError):
        return 200


def _payload_message(payload: Mapping[str, object] | None) -> str | None:
    if payload is None:
        return None
    value = payload.get("message")
    if isinstance(value, list):
        for item in value:
            message = str(item).strip()
            if message:
                return message
    if value not in (None, ""):
        return str(value).strip() or None
    return None


def _classify_parse_failure(exc: BLSParseError) -> str:
    text = str(exc).lower()
    if _is_rate_limit_message(text):
        return "rate_limit"
    if any(token in text for token in ("missing", "no usable", "not found")):
        return "missing_fields"
    return "parse_error"


def _classify_http_failure(status_code: int | None) -> str:
    return "rate_limit" if status_code == 429 else "http_error"


def _is_rate_limit_message(text: str) -> bool:
    return any(
        token in text
        for token in (
            "request_not_processed",
            "daily threshold",
            "daily quota",
            "rate limit",
            "rate-limit",
            "too many requests",
            "quota",
            "threshold for total number of requests",
        )
    )


def _validated_retrieved_at(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("retrieved_at must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"retrieved_at must be an ISO timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("retrieved_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _previous_month(month: str) -> str:
    normalized = normalize_bls_cutoff_month(month)
    if normalized is None:
        raise ValueError(f"Invalid month: {month!r}")
    year, month_number = (int(part) for part in normalized.split("-"))
    if month_number == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month_number - 1:02d}"


def _validate_retrieved_date(value: str) -> date:
    if not isinstance(value, str):
        raise ValueError("retrieved_date must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"retrieved_date must be YYYY-MM-DD: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"retrieved_date must be YYYY-MM-DD: {value!r}")
    return parsed


def _validate_year_range(*, start_year: int, end_year: int) -> None:
    if isinstance(start_year, bool) or isinstance(end_year, bool):
        raise ValueError("BLS start_year and end_year must be integers")
    if not isinstance(start_year, int) or not isinstance(end_year, int):
        raise ValueError("BLS start_year and end_year must be integers")
    if not 1900 <= start_year <= 2100 or not 1900 <= end_year <= 2100:
        raise ValueError("BLS start_year and end_year must be four-digit years")
    if start_year > end_year:
        raise ValueError("BLS start_year cannot be after end_year")
