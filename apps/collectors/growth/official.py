"""Collect and archive first-party GDPNow and ISM observations.

The collector has no local-value fallback.  A successful official response is
archived before parsing, and every returned source reference carries the
health fields consumed by the growth feature.  In particular, a missing
current ISM month is reported as ``not_published`` while the last published
month remains available for context.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from apps.parsers.growth.official import (
    GDP_NOW_COMMENTARY_URL,
    GDP_NOW_SOURCE_URL,
    ISM_MANUFACTURING_SOURCE_URL_TEMPLATE,
    ISM_PRNEWSWIRE_ISSUER_URL,
    ISM_SERVICES_SOURCE_URL_TEMPLATE,
    GrowthObservation,
    GrowthSchedule,
    parse_gdpnow_commentary,
    parse_gdpnow_payload,
    parse_ism_report_html,
    parse_ism_prnewswire_index,
    parse_ism_prnewswire_release,
)
from apps.parsers.macro.models import MacroPoint
from apps.parsers.macro.storage import utc_now_iso


GROWTH_SYMBOLS = (
    "GDP_NOW",
    "ISM_MANUFACTURING",
    "ISM_SERVICES",
    "ISM_SERVICES_PRICES",
)
GROWTH_DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class GrowthCollectorResult:
    """Collector result compatible with the existing macro pipeline."""

    points: list[MacroPoint]
    unavailable_symbols: list[str]
    source_refs: list[dict[str, Any]]
    collector_health: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "points": [point.to_dict() for point in self.points],
            "unavailable_symbols": self.unavailable_symbols,
            "source_refs": self.source_refs,
            "collector_health": self.collector_health,
        }


@dataclass(frozen=True)
class _FetchedResponse:
    url: str
    status_code: int | None
    body: bytes
    retrieved_at: str
    failure_kind: str | None = None
    failure_reason: str | None = None
    attempts: int = 1


def collect_growth_data(
    *,
    retrieved_date: str,
    storage_root: Path,
    client: Any | None = None,
    now: datetime | None = None,
    ism_period: str | None = None,
) -> GrowthCollectorResult:
    """Collect GDPNow plus the latest available Manufacturing/Services ISM.

    ``ism_period`` is an optional ISO ``YYYY-MM`` candidate period used by
    deterministic tests and historical replays.  When omitted, the current
    calendar month from ``retrieved_date`` is probed first; a 404 is treated
    as an official not-published signal and the immediately prior month page
    is then requested.  This is a source lookup, not a claim that the current
    month has already been released.
    """

    cutoff = _parse_date(retrieved_date)
    clock = _ensure_utc(now or datetime.now(timezone.utc))
    close_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=GROWTH_DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "finance-agent/0.1", "Accept": "application/json,text/html"},
            trust_env=False,
        )

    try:
        gdp_points, gdp_refs, gdp_health, gdp_unavailable = _collect_gdpnow(
            client=client,
            retrieved_date=retrieved_date,
            cutoff=cutoff,
            storage_root=storage_root,
            now=clock,
        )
        manufacturing = _collect_ism(
            client=client,
            retrieved_date=retrieved_date,
            cutoff=cutoff,
            storage_root=storage_root,
            now=clock,
            report_kind="manufacturing",
            source_key="ism_manufacturing",
            url_template=ISM_MANUFACTURING_SOURCE_URL_TEMPLATE,
            candidate_period=ism_period,
        )
        services = _collect_ism(
            client=client,
            retrieved_date=retrieved_date,
            cutoff=cutoff,
            storage_root=storage_root,
            now=clock,
            report_kind="services",
            source_key="ism_services",
            url_template=ISM_SERVICES_SOURCE_URL_TEMPLATE,
            candidate_period=ism_period,
        )
    finally:
        if close_client:
            client.close()

    points = [*gdp_points, *manufacturing[0], *services[0]]
    refs = [*gdp_refs, *manufacturing[1], *services[1]]
    health = {
        **gdp_health,
        **manufacturing[2],
        **services[2],
    }
    unavailable = [
        *gdp_unavailable,
        *manufacturing[3],
        *services[3],
    ]
    return GrowthCollectorResult(
        points=points,
        unavailable_symbols=list(dict.fromkeys(unavailable)),
        source_refs=refs,
        collector_health=health,
    )


def _collect_gdpnow(
    *,
    client: Any,
    retrieved_date: str,
    cutoff: date,
    storage_root: Path,
    now: datetime,
) -> tuple[list[MacroPoint], list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    fetched = _fetch(client, GDP_NOW_SOURCE_URL)
    raw_path = _archive_response(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        source_key="atlanta_fed_gdpnow",
        body=fetched.body,
        suffix="json",
    )
    if fetched.failure_kind is not None:
        health = _failure_health(
            source_key="gdp_now",
            symbol="GDP_NOW",
            source="atlanta_fed_gdpnow",
            source_url=GDP_NOW_SOURCE_URL,
            raw_path=raw_path,
            retrieved_at=fetched.retrieved_at,
            failure_kind=fetched.failure_kind,
            reason=fetched.failure_reason,
            now=now,
        )
        return [], [_ref_from_health(health)], {"gdp_now": health}, ["GDP_NOW"]

    try:
        payload = json.loads(fetched.body.decode("utf-8"))
        observation = parse_gdpnow_payload(payload, source_url=GDP_NOW_SOURCE_URL)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        health = _failure_health(
            source_key="gdp_now",
            symbol="GDP_NOW",
            source="atlanta_fed_gdpnow",
            source_url=GDP_NOW_SOURCE_URL,
            raw_path=raw_path,
            retrieved_at=fetched.retrieved_at,
            failure_kind="not_published" if "not published" in str(exc).lower() else "fetch_failed",
            reason=f"GDPNow parse failed: {type(exc).__name__}",
            now=now,
        )
        return [], [_ref_from_health(health)], {"gdp_now": health}, ["GDP_NOW"]

    if _parse_date(observation.observation_date) > cutoff:
        health = _failure_health(
            source_key="gdp_now",
            symbol="GDP_NOW",
            source="atlanta_fed_gdpnow",
            source_url=GDP_NOW_SOURCE_URL,
            raw_path=raw_path,
            retrieved_at=fetched.retrieved_at,
            failure_kind="future_observation",
            reason="official GDPNow update is after the requested cutoff",
            now=now,
        )
        return [], [_ref_from_health(health)], {"gdp_now": health}, ["GDP_NOW"]

    schedule = GrowthSchedule()
    commentary_path: str | None = None
    commentary = _fetch(client, GDP_NOW_COMMENTARY_URL)
    commentary_path = _archive_response(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        source_key="atlanta_fed_gdpnow_commentary",
        body=commentary.body,
        suffix="html",
    )
    if commentary.failure_kind is None:
        try:
            schedule = parse_gdpnow_commentary(
                commentary.body,
                latest_observation_date=observation.observation_date,
            )
        except ValueError:
            # The current JSON observation is still valid.  The next-release
            # calendar is explicitly unavailable rather than guessed.
            schedule = GrowthSchedule(source_note="official commentary parse unavailable")

    if schedule.previous_value is not None:
        observation = GrowthObservation(
            **{
                **asdict(observation),
                "previous_value": schedule.previous_value,
                "previous_reference_period": schedule.previous_reference_period or observation.reference_period,
            }
        )

    point = _point_from_observation(observation, raw_path=fetched_path(raw_path), retrieved_at=fetched.retrieved_at)
    health = _available_health(
        source_key="gdp_now",
        symbols=["GDP_NOW"],
        source="atlanta_fed_gdpnow",
        source_url=GDP_NOW_SOURCE_URL,
        raw_path=raw_path,
        retrieved_at=fetched.retrieved_at,
        observation=observation,
        schedule=schedule,
        now=now,
        extra={"commentary_raw_path": commentary_path},
    )
    ref = _ref_from_observation(observation, health=health, raw_path=raw_path, retrieved_at=fetched.retrieved_at)
    return [point], [ref], {"gdp_now": health}, []


def _collect_ism(
    *,
    client: Any,
    retrieved_date: str,
    cutoff: date,
    storage_root: Path,
    now: datetime,
    report_kind: str,
    source_key: str,
    url_template: str,
    candidate_period: str | None,
) -> tuple[list[MacroPoint], list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    current_period = _normalize_month_period(candidate_period) if candidate_period else f"{cutoff.year:04d}-{cutoff.month:02d}"
    periods = (current_period, _prior_month(current_period))
    symbols = _symbols_for_kind(report_kind)
    failure_records: list[dict[str, Any]] = []

    def _current_candidate_status() -> str | None:
        current_failures = [item for item in failure_records if item.get("period") == current_period]
        if not current_failures:
            return None
        if any(item.get("kind") == "not_published" for item in current_failures):
            return "not_published"
        return "official_unavailable"

    def _finish(
        records: list[GrowthObservation],
        schedule: GrowthSchedule,
        *,
        selected_period: str,
        selected_source: str,
        selected_url: str,
        selected_raw_path: str,
        selected_retrieved_at: str,
        extra: dict[str, Any] | None = None,
    ) -> tuple[list[MacroPoint], list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
        if any(_parse_date(record.observation_date) > cutoff for record in records):
            health = _failure_health(
                source_key=source_key,
                symbol=_symbol_for_kind(report_kind),
                source=selected_source,
                source_url=selected_url,
                raw_path=selected_raw_path,
                retrieved_at=selected_retrieved_at,
                failure_kind="future_observation",
                reason="official ISM reference period is after the requested cutoff",
                now=now,
                extra={"candidate_period": current_period, "selected_period": selected_period, "symbols": symbols, **(extra or {})},
            )
            return [], [_ref_from_health(health)], {source_key: health}, symbols
        points = [
            _point_from_observation(record, raw_path=selected_raw_path, retrieved_at=selected_retrieved_at)
            for record in records
        ]
        health = _available_health(
            source_key=source_key,
            symbols=[record.symbol for record in records],
            source=selected_source,
            source_url=selected_url,
            raw_path=selected_raw_path,
            retrieved_at=selected_retrieved_at,
            observation=records[0],
            schedule=schedule,
            now=now,
            extra={"candidate_period": current_period, "selected_period": selected_period, **(extra or {})},
        )
        refs = [
            _ref_from_observation(record, health=health, raw_path=selected_raw_path, retrieved_at=selected_retrieved_at)
            for record in records
        ]
        return points, refs, {source_key: health}, []

    for index, selected_period in enumerate(periods):
        official_url = url_template.format(period=_month_slug(selected_period))
        official = _fetch(client, official_url)
        official_raw_path = _archive_response(
            storage_root=storage_root,
            retrieved_date=retrieved_date,
            source_key=source_key if index == 0 else f"{source_key}_previous",
            body=official.body,
            suffix="html",
        )
        if official.failure_kind is None:
            try:
                records, schedule = parse_ism_report_html(
                    official.body,
                    report_kind=report_kind,
                    source_url=official_url,
                )
            except (TypeError, ValueError) as exc:
                parse_failure = "not_published" if "not published" in str(exc).lower() else "fetch_failed"
                if parse_failure != "not_published":
                    health = _failure_health(
                        source_key=source_key,
                        symbol=_symbol_for_kind(report_kind),
                        source="ism_official",
                        source_url=official_url,
                        raw_path=official_raw_path,
                        retrieved_at=official.retrieved_at,
                        failure_kind=parse_failure,
                        reason=f"ISM parse failed: {type(exc).__name__}",
                        now=now,
                        extra={"candidate_period": current_period, "symbols": symbols},
                    )
                    return [], [_ref_from_health(health)], {source_key: health}, symbols
                failure_records.append({"period": selected_period, "source": "ism_official", "kind": parse_failure, "raw_path": official_raw_path})
                if index == 0:
                    # A published HTML shell without the report is equivalent
                    # to a 404 candidate; move to the prior release.
                    continue
            else:
                return _finish(
                    records,
                    schedule,
                    selected_period=selected_period,
                    selected_source="ism_official",
                    selected_url=official_url,
                    selected_raw_path=official_raw_path,
                    selected_retrieved_at=official.retrieved_at,
                    extra={
                        "candidate_status": _current_candidate_status(),
                    },
                )
        else:
            failure_records.append({"period": selected_period, "source": "ism_official", "kind": official.failure_kind, "reason": official.failure_reason, "raw_path": official_raw_path})

        # An official report page can be public while the issuer's release
        # page is behind SSO/CAPTCHA.  Search the issuer-owned PR Newswire
        # feed for the same period before giving up on that period.  Explicit
        # 404/shell not-published for the current period is skipped here so
        # the normal prior-month walk stays cheap; the prior period is still
        # checked below.
        should_try_prn = official.failure_kind in {"auth_failed", "fetch_failed"} or index == 1
        if should_try_prn:
            alternate = _collect_ism_prnewswire_period(
                client=client,
                retrieved_date=retrieved_date,
                cutoff=cutoff,
                storage_root=storage_root,
                report_kind=report_kind,
                source_key=source_key,
                expected_period=selected_period,
            )
            if alternate.get("records"):
                return _finish(
                    alternate["records"],
                    alternate["schedule"],
                    selected_period=selected_period,
                    selected_source="ism_prnewswire",
                    selected_url=alternate["candidate"].url,
                    selected_raw_path=alternate["raw_path"],
                    selected_retrieved_at=alternate["retrieved_at"],
                    extra={
                        "candidate_status": _current_candidate_status(),
                        "fallback_used": True,
                        "fallback_transport": "prnewswire",
                        "fallback_channel": "issuer_primary",
                        "issuer": "Institute for Supply Management",
                        "issuer_verified": True,
                        "official_source": "ism_official",
                        "official_source_url": official_url,
                        "official_source_status": official.failure_kind or "not_published",
                        "official_raw_path": official_raw_path,
                        "prnewswire_index_url": ISM_PRNEWSWIRE_ISSUER_URL,
                        "prnewswire_index_raw_path": alternate.get("index_raw_path"),
                        "prnewswire_listing_release_date": alternate["candidate"].listing_release_date,
                        "release_date": alternate["records"][0].release_date,
                        "release_time": alternate["records"][0].release_time,
                    },
                )
            failure_records.append({
                "period": selected_period,
                "source": "ism_prnewswire",
                "kind": alternate.get("failure_kind"),
                "reason": alternate.get("failure_reason"),
                "raw_path": alternate.get("raw_path") or alternate.get("index_raw_path"),
            })

    primary = next((item for item in failure_records if item.get("source") == "ism_official"), None) or failure_records[0]
    health = _failure_health(
        source_key=source_key,
        symbol=_symbol_for_kind(report_kind),
        source="ism_official",
        source_url=url_template.format(period=_month_slug(current_period)),
        raw_path=str(primary.get("raw_path") or ""),
        retrieved_at=utc_now_iso(),
        failure_kind=str(primary.get("kind") or "fetch_failed"),
        reason=str(primary.get("reason") or "current and prior ISM sources did not contain a validated report"),
        now=now,
        extra={
            "candidate_period": current_period,
            "candidate_status": _current_candidate_status() or "official_unavailable",
            "fallback_attempts": failure_records,
            "symbols": symbols,
        },
    )
    return [], [_ref_from_health(health)], {source_key: health}, symbols


def _collect_ism_prnewswire_period(
    *,
    client: Any,
    retrieved_date: str,
    cutoff: date,
    storage_root: Path,
    report_kind: str,
    source_key: str,
    expected_period: str,
) -> dict[str, Any]:
    """Locate and validate one issuer-published PR Newswire ISM release."""

    index_fetch = _fetch(client, ISM_PRNEWSWIRE_ISSUER_URL)
    index_raw_path = _archive_response(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        source_key=f"{source_key}_prnewswire_index_{expected_period}",
        body=index_fetch.body,
        suffix="html",
    )
    if index_fetch.failure_kind is not None:
        return {
            "failure_kind": index_fetch.failure_kind,
            "failure_reason": index_fetch.failure_reason,
            "index_raw_path": index_raw_path,
        }
    try:
        candidate = parse_ism_prnewswire_index(
            index_fetch.body,
            report_kind=report_kind,
            reference_period=expected_period,
        )
    except (TypeError, ValueError) as exc:
        return {"failure_kind": "fetch_failed", "failure_reason": f"PR Newswire index parse failed: {type(exc).__name__}", "index_raw_path": index_raw_path}
    if candidate is None:
        return {"failure_kind": "not_published", "failure_reason": "issuer PR Newswire feed has no matching ISM release", "index_raw_path": index_raw_path}

    article_fetch = _fetch(client, candidate.url)
    article_raw_path = _archive_response(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        source_key=f"{source_key}_prnewswire_release_{expected_period}",
        body=article_fetch.body,
        suffix="html",
    )
    if article_fetch.failure_kind is not None:
        return {
            "failure_kind": article_fetch.failure_kind,
            "failure_reason": article_fetch.failure_reason,
            "index_raw_path": index_raw_path,
            "raw_path": article_raw_path,
            "candidate": candidate,
        }
    try:
        records, schedule = parse_ism_prnewswire_release(
            article_fetch.body,
            report_kind=report_kind,
            source_url=candidate.url,
            expected_period=expected_period,
        )
    except (TypeError, ValueError) as exc:
        return {
            "failure_kind": "fetch_failed",
            "failure_reason": f"PR Newswire release validation failed: {type(exc).__name__}",
            "index_raw_path": index_raw_path,
            "raw_path": article_raw_path,
            "candidate": candidate,
        }
    release_date = records[0].release_date if records else None
    if release_date is None or _parse_date(release_date) > cutoff:
        return {
            "failure_kind": "future_observation" if release_date else "fetch_failed",
            "failure_reason": "issuer release date is after the requested cutoff" if release_date else "issuer release date is missing",
            "index_raw_path": index_raw_path,
            "raw_path": article_raw_path,
            "candidate": candidate,
        }
    return {
        "records": records,
        "schedule": schedule,
        "raw_path": article_raw_path,
        "index_raw_path": index_raw_path,
        "retrieved_at": article_fetch.retrieved_at,
        "candidate": candidate,
    }


def _fetch(client: Any, url: str) -> _FetchedResponse:
    # Retry transport failures only. Authentication, CAPTCHA and publication
    # responses retain their own semantics and are never bypassed or retried.
    for attempt in range(1, 4):
        fetched = _fetch_once(client, url)
        if fetched.status_code is not None or fetched.failure_reason not in {
            "ConnectError", "ConnectTimeout", "ReadTimeout", "ReadError", "RemoteProtocolError"
        } or attempt == 3:
            return replace(fetched, attempts=attempt)
    raise AssertionError("bounded fetch exhausted without a result")


def _fetch_once(client: Any, url: str) -> _FetchedResponse:
    try:
        response = client.get(url)
    except Exception as exc:
        return _FetchedResponse(
            url=url,
            status_code=None,
            body=b"",
            # Record the time the failed request was observed, rather than
            # the instant immediately before the network call began.
            retrieved_at=utc_now_iso(),
            failure_kind="fetch_failed",
            failure_reason=f"{type(exc).__name__}",
        )
    body = bytes(getattr(response, "content", b"") or b"")
    status_code = getattr(response, "status_code", None)
    response_url = str(getattr(response, "url", "") or "").lower()
    headers = getattr(response, "headers", {}) or {}
    location = str(headers.get("location", "") or "").lower()
    # ISM currently redirects the public report pages to its SSO/CAPTCHA
    # endpoint for some clients.  Treat that as an authentication gate even
    # when the redirect's final status is 200/404; otherwise the parser would
    # mislabel an access problem as a not-published report.
    auth_redirect = any(
        marker in f"{response_url} {location}"
        for marker in ("/sso/", "login.aspx", "captcha")
    )
    if auth_redirect:
        return _FetchedResponse(
            url=url,
            status_code=int(status_code) if status_code is not None else None,
            body=body,
            retrieved_at=utc_now_iso(),
            failure_kind="auth_failed",
            failure_reason="official source redirected to authentication",
        )
    if status_code in {401, 403}:
        return _FetchedResponse(
            url=url,
            status_code=int(status_code),
            body=body,
            retrieved_at=utc_now_iso(),
            failure_kind="auth_failed",
            failure_reason=f"HTTP {status_code}",
        )
    if status_code == 404:
        return _FetchedResponse(
            url=url,
            status_code=404,
            body=body,
            retrieved_at=utc_now_iso(),
            failure_kind="not_published",
            failure_reason="official page returned HTTP 404",
        )
    if status_code is None or int(status_code) >= 400:
        return _FetchedResponse(
            url=url,
            status_code=int(status_code) if status_code is not None else None,
            body=body,
            retrieved_at=utc_now_iso(),
            failure_kind="fetch_failed",
            failure_reason=f"HTTP {status_code}" if status_code is not None else "missing HTTP status",
        )
    return _FetchedResponse(
        url=url,
        status_code=int(status_code),
        body=body,
        retrieved_at=utc_now_iso(),
    )


def _archive_response(*, storage_root: Path, retrieved_date: str, source_key: str, body: bytes, suffix: str) -> str:
    raw_dir = storage_root / "raw" / "macro" / "growth" / retrieved_date
    raw_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%H%M%S%f")
    path = raw_dir / f"{source_key}-{timestamp}-{uuid4().hex[:8]}.{suffix}"
    path.write_bytes(body)
    return path.relative_to(storage_root).as_posix()


def _point_from_observation(observation: GrowthObservation, *, raw_path: str, retrieved_at: str) -> MacroPoint:
    return MacroPoint(
        symbol=observation.symbol,
        date=observation.observation_date,
        value=observation.value,
        source=observation.source,
        source_url=observation.source_url,
        retrieved_at=retrieved_at,
        raw_path=raw_path,
    )


def _available_health(
    *,
    source_key: str,
    symbols: list[str],
    source: str,
    source_url: str,
    raw_path: str,
    retrieved_at: str,
    observation: GrowthObservation,
    schedule: GrowthSchedule,
    now: datetime,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expected_time = schedule.expected_release_time
    staleness = "fresh"
    if expected_time is not None:
        try:
            if _ensure_utc(datetime.fromisoformat(expected_time)) <= now and extra and extra.get("candidate_status") == "not_published":
                staleness = "stale"
        except ValueError:
            staleness = "unknown"
    health = {
        "source_key": source_key,
        "symbols": symbols,
        "source": source,
        "source_url": source_url,
        "raw_path": raw_path,
        "retrieved_at": retrieved_at,
        "expected_release_time": expected_time,
        "expected_release_date": schedule.expected_release_date,
        "expected_release_timezone": schedule.expected_release_timezone,
        "actual_latest_date": observation.observation_date,
        "official_latest_date": observation.observation_date,
        "actual_latest_date_type": "reference_period_start" if observation.metadata.get("date_semantics") == "reference_period_start" else "provider_update_date",
        "official_latest_date_type": "reference_period_start" if observation.metadata.get("date_semantics") == "reference_period_start" else "provider_update_date",
        "reference_period": observation.reference_period,
        "collector_status": "success",
        "staleness": staleness,
        "expected_freshness": "event_driven" if source_key == "gdp_now" else "monthly",
        "release_status": "published",
        "reason": schedule.source_note,
    }
    if extra:
        health.update(extra)
    return health


def _failure_health(
    *,
    source_key: str,
    symbol: str,
    source: str,
    source_url: str,
    raw_path: str,
    retrieved_at: str,
    failure_kind: str | None,
    reason: str | None,
    now: datetime,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del now
    staleness = {
        "not_published": "not_published",
        "future_observation": "future",
    }.get(failure_kind or "", "unknown")
    health: dict[str, Any] = {
        "source_key": source_key,
        "symbols": [symbol],
        "source": source,
        "source_url": source_url,
        "raw_path": raw_path,
        "retrieved_at": retrieved_at,
        "expected_release_time": None,
        "expected_release_date": None,
        "expected_release_timezone": None,
        "actual_latest_date": None,
        "official_latest_date": None,
        "collector_status": failure_kind or "fetch_failed",
        "staleness": staleness,
        "expected_freshness": "event_driven" if source_key == "gdp_now" else "monthly",
        "release_status": "not_published" if failure_kind == "not_published" else "unavailable",
        "reason": reason,
    }
    if extra:
        health.update(extra)
    return health


def _ref_from_observation(
    observation: GrowthObservation,
    *,
    health: dict[str, Any],
    raw_path: str,
    retrieved_at: str,
) -> dict[str, Any]:
    return {
        "symbol": observation.symbol,
        "source": observation.source,
        "source_url": observation.source_url,
        "raw_path": raw_path,
        "retrieved_at": retrieved_at,
        "reference_period": observation.reference_period,
        "previous_value": observation.previous_value,
        "previous_reference_period": observation.previous_reference_period,
        "release_date": observation.release_date,
        "release_time": observation.release_time,
        "metadata": observation.metadata,
        **health,
    }


def _ref_from_health(health: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": (health.get("symbols") or [None])[0],
        "source": health.get("source"),
        "source_url": health.get("source_url"),
        "raw_path": health.get("raw_path"),
        "retrieved_at": health.get("retrieved_at"),
        **health,
    }


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError(f"invalid growth retrieved_date: {value!r}") from exc


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_month_period(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid ISM period: {value!r}") from exc
    return parsed.strftime("%Y-%m")


def _month_slug(period: str) -> str:
    return datetime.strptime(period, "%Y-%m").strftime("%B").lower()


def _prior_month(period: str) -> str:
    value = datetime.strptime(period, "%Y-%m")
    return f"{value.year - 1 if value.month == 1 else value.year:04d}-{12 if value.month == 1 else value.month - 1:02d}"


def _symbol_for_kind(report_kind: str) -> str:
    return "ISM_MANUFACTURING" if report_kind == "manufacturing" else "ISM_SERVICES"


def _symbols_for_kind(report_kind: str) -> list[str]:
    return ["ISM_MANUFACTURING"] if report_kind == "manufacturing" else ["ISM_SERVICES", "ISM_SERVICES_PRICES"]


def fetched_path(path: str) -> str:
    """Compatibility hook used to make raw path intent explicit."""

    return path
