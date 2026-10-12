"""Collector for official SPDR GLD shares and physical holdings history."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from apps.parsers.etf.official_gld import (
    GldHoldingsHistory,
    GldNavHistory,
    parse_gld_historical_archive,
    parse_gld_nav_history,
)
from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import utc_now_iso


GLD_NAV_HISTORY_URL = "https://www.ssga.com/library-content/products/fund-data/etfs/us/navhist-us-en-gld.xlsx"
GLD_HISTORICAL_ARCHIVE_URL = "https://api.spdrgoldshares.com/api/v1/historical-archive?exchange=NYSE&lang=en&product=gld"
GLD_SOURCE_NAV = "ssga_gld"
GLD_SOURCE_HOLDINGS = "spdr_gld"
GLD_SHARES_SYMBOL = "GLD_shares_outstanding"
GLD_HOLDINGS_SYMBOL = "GLD_gold_holdings_tonnes"
GLD_SHARES_WEEKLY_ANCHOR_SYMBOL = f"{GLD_SHARES_SYMBOL}_weekly_anchor"
GLD_HOLDINGS_WEEKLY_ANCHOR_SYMBOL = f"{GLD_HOLDINGS_SYMBOL}_weekly_anchor"
GLD_REQUEST_ATTEMPTS = 3


class _GldRequestError(RuntimeError):
    """Transport failure after the bounded official-source retry budget."""

    def __init__(self, *, url: str, failures: list[str]) -> None:
        self.url = url
        self.failures = tuple(failures)
        super().__init__(failures[-1] if failures else f"request failed: {url}")


def collect_official_gld(
    *,
    retrieved_date: str,
    storage_root: Path,
    client: Any | None = None,
    trust_env: bool = True,
) -> CollectorResult:
    """Collect official GLD shares/NAV and trust holdings into CollectorResult.

    The SSGA NAV history and SPDR historical archive are independent official
    workbooks.  The collector archives both original response bodies under
    ``raw/etf/spdr/<retrieved_date>/`` and computes changes from the previous
    actual published row.  Total net assets are emitted as a level only; no
    AUM-to-flow conversion is performed.  The default client respects the
    process environment so the configured local proxy can be used; callers
    that inject a client own its transport settings.
    """

    try:
        cutoff_date = _parse_retrieved_date(retrieved_date)
    except (TypeError, ValueError):
        reason = f"Invalid retrieved_date for official GLD cutoff: {retrieved_date!r}"
        return _unavailable_result(reason)

    close_client = False
    if client is None:
        client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "finance-agent/0.1", "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            trust_env=trust_env,
        )
        close_client = True

    points: list[MacroPoint] = []
    source_refs: list[dict[str, str]] = []
    unavailable: list[str] = []
    retrieved_at = utc_now_iso()
    try:
        nav_result = _collect_nav(
            client=client,
            cutoff_date=cutoff_date,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            retrieved_at=retrieved_at,
        )
        points.extend(nav_result[0])
        source_refs.append(nav_result[1])
        unavailable.extend(nav_result[2])

        holdings_result = _collect_holdings(
            client=client,
            cutoff_date=cutoff_date,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            retrieved_at=retrieved_at,
        )
        points.extend(holdings_result[0])
        source_refs.append(holdings_result[1])
        unavailable.extend(holdings_result[2])
    finally:
        if close_client:
            client.close()
    return CollectorResult(
        points=points,
        unavailable_symbols=unavailable,
        source_refs=source_refs,
    )


def _collect_nav(
    *,
    client: Any,
    cutoff_date: date,
    retrieved_date: str,
    storage_root: Path,
    retrieved_at: str,
) -> tuple[list[MacroPoint], dict[str, str], list[str]]:
    raw_path = _raw_path(storage_root, retrieved_date, "gld_nav_history.xlsx")
    attempt_failures: list[str] = []
    try:
        response, attempt_failures = _get_with_retry(client, GLD_NAV_HISTORY_URL)
        raw_path.write_bytes(response.content)
        raw_path_ref = raw_path.relative_to(storage_root).as_posix()
        history = parse_gld_nav_history(response.content, cutoff_date=cutoff_date)
        if not history.rows:
            raise ValueError("SSGA GLD NAV history has no usable rows on or before cutoff")
        latest, previous = history.latest_pair()
        weekly_anchor = history.weekly_anchor(latest)
        points = _nav_points(history, latest, previous, weekly_anchor, raw_path_ref, retrieved_at)
        ref = _source_ref(
            source=GLD_SOURCE_NAV,
            source_url=GLD_NAV_HISTORY_URL,
            raw_path=raw_path_ref,
            retrieved_at=retrieved_at,
            report_date=latest.report_date,
            previous_report_date=previous.report_date if previous else None,
            metrics="shares_outstanding,nav_per_share,total_net_assets_usd",
            skipped_rows=history.skipped_rows,
            attempts=1 + len(attempt_failures),
            attempt_failures=attempt_failures,
        )
        return points, ref, []
    except Exception as exc:
        if isinstance(exc, _GldRequestError):
            attempt_failures = list(exc.failures)
            attempts = len(attempt_failures)
        else:
            attempts = 1 + len(attempt_failures)
        return [], _error_ref(
            source=GLD_SOURCE_NAV,
            source_url=GLD_NAV_HISTORY_URL,
            raw_path=raw_path.relative_to(storage_root).as_posix() if raw_path.exists() else None,
            retrieved_at=retrieved_at,
            reason=f"official GLD NAV collection failed: {type(exc).__name__}: {exc}",
            report_type="nav_history",
            attempts=attempts,
            attempt_failures=attempt_failures,
        ), [GLD_SHARES_SYMBOL]


def _collect_holdings(
    *,
    client: Any,
    cutoff_date: date,
    retrieved_date: str,
    storage_root: Path,
    retrieved_at: str,
) -> tuple[list[MacroPoint], dict[str, str], list[str]]:
    raw_path = _raw_path(storage_root, retrieved_date, "gld_historical_archive.xlsx")
    attempt_failures: list[str] = []
    try:
        response, attempt_failures = _get_with_retry(client, GLD_HISTORICAL_ARCHIVE_URL)
        raw_path.write_bytes(response.content)
        raw_path_ref = raw_path.relative_to(storage_root).as_posix()
        history = parse_gld_historical_archive(response.content, cutoff_date=cutoff_date)
        if not history.rows:
            raise ValueError("SPDR GLD historical archive has no usable rows on or before cutoff")
        latest, previous = history.latest_pair()
        weekly_anchor = history.weekly_anchor(latest)
        points = _holdings_points(history, latest, previous, weekly_anchor, raw_path_ref, retrieved_at)
        ref = _source_ref(
            source=GLD_SOURCE_HOLDINGS,
            source_url=GLD_HISTORICAL_ARCHIVE_URL,
            raw_path=raw_path_ref,
            retrieved_at=retrieved_at,
            report_date=latest.report_date,
            previous_report_date=previous.report_date if previous else None,
            metrics="gold_holdings_ounces,gold_holdings_tonnes,total_net_asset_value_usd",
            skipped_rows=history.skipped_rows,
            attempts=1 + len(attempt_failures),
            attempt_failures=attempt_failures,
        )
        return points, ref, []
    except Exception as exc:
        if isinstance(exc, _GldRequestError):
            attempt_failures = list(exc.failures)
            attempts = len(attempt_failures)
        else:
            attempts = 1 + len(attempt_failures)
        return [], _error_ref(
            source=GLD_SOURCE_HOLDINGS,
            source_url=GLD_HISTORICAL_ARCHIVE_URL,
            raw_path=raw_path.relative_to(storage_root).as_posix() if raw_path.exists() else None,
            retrieved_at=retrieved_at,
            reason=f"official GLD holdings collection failed: {type(exc).__name__}: {exc}",
            report_type="historical_archive",
            attempts=attempts,
            attempt_failures=attempt_failures,
        ), [GLD_HOLDINGS_SYMBOL]


def _nav_points(
    history: GldNavHistory,
    latest: Any,
    previous: Any | None,
    weekly_anchor: Any | None,
    raw_path: str,
    retrieved_at: str,
) -> list[MacroPoint]:
    points = [
        _point(GLD_SHARES_SYMBOL, latest.shares_outstanding, latest.report_date, GLD_SOURCE_NAV, GLD_NAV_HISTORY_URL, raw_path, retrieved_at),
        _point("GLD_nav_per_share", latest.nav_per_share, latest.report_date, GLD_SOURCE_NAV, GLD_NAV_HISTORY_URL, raw_path, retrieved_at),
        _point("GLD_total_net_assets_usd", latest.total_net_assets_usd, latest.report_date, GLD_SOURCE_NAV, GLD_NAV_HISTORY_URL, raw_path, retrieved_at),
    ]
    if previous is not None:
        points.extend(
            [
                _point(f"{GLD_SHARES_SYMBOL}_prev", previous.shares_outstanding, previous.report_date, GLD_SOURCE_NAV, GLD_NAV_HISTORY_URL, raw_path, retrieved_at),
                _point(f"{GLD_SHARES_SYMBOL}_delta", latest.shares_outstanding - previous.shares_outstanding, latest.report_date, GLD_SOURCE_NAV, GLD_NAV_HISTORY_URL, raw_path, retrieved_at),
            ]
        )
    if weekly_anchor is not None:
        points.append(
            _point(
                GLD_SHARES_WEEKLY_ANCHOR_SYMBOL,
                weekly_anchor.shares_outstanding,
                weekly_anchor.report_date,
                GLD_SOURCE_NAV,
                GLD_NAV_HISTORY_URL,
                raw_path,
                retrieved_at,
            )
        )
    return points


def _holdings_points(
    history: GldHoldingsHistory,
    latest: Any,
    previous: Any | None,
    weekly_anchor: Any | None,
    raw_path: str,
    retrieved_at: str,
) -> list[MacroPoint]:
    points = [
        _point(GLD_HOLDINGS_SYMBOL, latest.gold_holdings_tonnes, latest.report_date, GLD_SOURCE_HOLDINGS, GLD_HISTORICAL_ARCHIVE_URL, raw_path, retrieved_at),
        _point("GLD_gold_holdings_ounces", latest.gold_holdings_ounces, latest.report_date, GLD_SOURCE_HOLDINGS, GLD_HISTORICAL_ARCHIVE_URL, raw_path, retrieved_at),
        _point("GLD_total_net_asset_value_usd", latest.total_net_asset_value_usd, latest.report_date, GLD_SOURCE_HOLDINGS, GLD_HISTORICAL_ARCHIVE_URL, raw_path, retrieved_at),
    ]
    if previous is not None:
        points.extend(
            [
                _point(f"{GLD_HOLDINGS_SYMBOL}_prev", previous.gold_holdings_tonnes, previous.report_date, GLD_SOURCE_HOLDINGS, GLD_HISTORICAL_ARCHIVE_URL, raw_path, retrieved_at),
                _point(f"{GLD_HOLDINGS_SYMBOL}_delta", latest.gold_holdings_tonnes - previous.gold_holdings_tonnes, latest.report_date, GLD_SOURCE_HOLDINGS, GLD_HISTORICAL_ARCHIVE_URL, raw_path, retrieved_at),
                _point("GLD_gold_holdings_ounces_prev", previous.gold_holdings_ounces, previous.report_date, GLD_SOURCE_HOLDINGS, GLD_HISTORICAL_ARCHIVE_URL, raw_path, retrieved_at),
                _point("GLD_gold_holdings_ounces_delta", latest.gold_holdings_ounces - previous.gold_holdings_ounces, latest.report_date, GLD_SOURCE_HOLDINGS, GLD_HISTORICAL_ARCHIVE_URL, raw_path, retrieved_at),
            ]
        )
    if weekly_anchor is not None:
        points.append(
            _point(
                GLD_HOLDINGS_WEEKLY_ANCHOR_SYMBOL,
                weekly_anchor.gold_holdings_tonnes,
                weekly_anchor.report_date,
                GLD_SOURCE_HOLDINGS,
                GLD_HISTORICAL_ARCHIVE_URL,
                raw_path,
                retrieved_at,
            )
        )
    return points


def _point(symbol: str, value: float, report_date: date, source: str, source_url: str, raw_path: str, retrieved_at: str) -> MacroPoint:
    return MacroPoint(
        symbol=symbol,
        date=report_date.isoformat(),
        value=round(value, 6),
        source=source,
        source_url=source_url,
        retrieved_at=retrieved_at,
        raw_path=raw_path,
    )


def _raw_path(storage_root: Path, retrieved_date: str, filename: str) -> Path:
    stem = Path(filename).stem
    suffix = datetime.now(timezone.utc).strftime("%H%M%S%f") + f"-{uuid4().hex[:8]}"
    # Keep the partition a canonical ISO date even if this helper is called
    # outside the public collector entry point.
    partition = _parse_retrieved_date(retrieved_date).isoformat()
    path = storage_root / "raw" / "etf" / "spdr" / partition / f"{stem}-{suffix}.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _get_with_retry(client: Any, url: str) -> tuple[Any, list[str]]:
    """Fetch one official workbook with a small, auditable retry budget."""

    failures: list[str] = []
    for attempt in range(1, GLD_REQUEST_ATTEMPTS + 1):
        try:
            response = client.get(url)
            response.raise_for_status()
            return response, failures
        except Exception as exc:
            failures.append(f"attempt_{attempt}:{type(exc).__name__}: {exc}")
    raise _GldRequestError(url=url, failures=failures)


def _parse_retrieved_date(value: str) -> date:
    """Parse the collector's date partition without accepting path suffixes."""

    if not isinstance(value, str):
        raise TypeError("retrieved_date must be a string")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("retrieved_date must be exactly YYYY-MM-DD")
    return parsed


def _source_ref(
    *,
    source: str,
    source_url: str,
    raw_path: str,
    retrieved_at: str,
    report_date: date,
    previous_report_date: date | None,
    metrics: str,
    skipped_rows: int,
    attempts: int = 1,
    attempt_failures: list[str] | None = None,
) -> dict[str, str]:
    ref = {
        "symbol": "GLD",
        "source": source,
        "source_url": source_url,
        "raw_path": raw_path,
        "retrieved_at": retrieved_at,
        "report_date": report_date.isoformat(),
        "previous_report_date": previous_report_date.isoformat() if previous_report_date else "",
        "metrics": metrics,
        "skipped_rows": str(skipped_rows),
        "status": "ok",
        "provider_role": "official_primary",
        "source_tier": "official",
        "verification_status": "single_source",
    }
    _add_attempt_metadata(ref, attempts=attempts, attempt_failures=attempt_failures)
    return ref


def _error_ref(
    *,
    source: str,
    source_url: str,
    raw_path: str | None,
    retrieved_at: str,
    reason: str,
    report_type: str,
    attempts: int = 1,
    attempt_failures: list[str] | None = None,
) -> dict[str, str]:
    ref = {
        "symbol": "GLD",
        "source": source,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "report_type": report_type,
        "status": "unavailable",
        "reason": reason,
        "provider_role": "official_primary",
        "source_tier": "official",
        "verification_status": "single_source",
    }
    if raw_path is not None:
        ref["raw_path"] = raw_path
    _add_attempt_metadata(ref, attempts=attempts, attempt_failures=attempt_failures)
    return ref


def _add_attempt_metadata(
    ref: dict[str, str],
    *,
    attempts: int,
    attempt_failures: list[str] | None,
) -> None:
    ref["attempt_count"] = str(max(1, attempts))
    if attempt_failures:
        ref["attempt_failures"] = " | ".join(attempt_failures)


def _unavailable_result(reason: str) -> CollectorResult:
    return CollectorResult(
        points=[],
        unavailable_symbols=[GLD_SHARES_SYMBOL, GLD_HOLDINGS_SYMBOL],
        source_refs=[
            _error_ref(source=GLD_SOURCE_NAV, source_url=GLD_NAV_HISTORY_URL, raw_path=None, retrieved_at=utc_now_iso(), reason=reason, report_type="nav_history"),
            _error_ref(source=GLD_SOURCE_HOLDINGS, source_url=GLD_HISTORICAL_ARCHIVE_URL, raw_path=None, retrieved_at=utc_now_iso(), reason=reason, report_type="historical_archive"),
        ],
    )
