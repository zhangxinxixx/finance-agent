"""Collector for official CFTC disaggregated Gold positioning reports."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import utc_now_iso
from apps.parsers.positioning.cftc import (
    CFTC_REPORT_TYPES,
    GOLD_CONTRACT_CODE,
    GOLD_MARKET_NAME,
    COTReportType,
    parse_cftc_disaggregated_zip,
)


# Keep the existing futures-only constant as a compatibility import for
# callers that patch or inspect it.  The callable below selects the yearly URL
# for either report universe.
CFTC_COT_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip"
CFTC_COMBINED_COT_URL = "https://www.cftc.gov/files/dea/history/com_disagg_txt_2026.zip"
COT_SOURCE = "cftc"
COT_SYMBOL = "COT_GOLD"


def cftc_cot_url(*, report_type: COTReportType, year: int) -> str:
    """Return the official annual CFTC URL for one explicit report universe."""

    if report_type == "futures_only":
        if year == 2026:
            return CFTC_COT_URL
        return f"https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
    if report_type == "combined":
        if year == 2026:
            return CFTC_COMBINED_COT_URL
        return f"https://www.cftc.gov/files/dea/history/com_disagg_txt_{year}.zip"
    raise ValueError(f"unsupported CFTC report_type: {report_type!r}")


def collect_positioning_cot(
    *,
    retrieved_date: str,
    storage_root: Path,
    report_type: COTReportType = "futures_only",
    client: Any | None = None,
) -> CollectorResult:
    """Collect one official CFTC Gold report using the shared CollectorResult.

    ``report_type="futures_only"`` preserves the existing ``COT_GOLD_*``
    symbols.  ``report_type="combined"`` exposes explicit
    ``COT_GOLD_combined_*`` symbols so futures-and-options data cannot be
    mistaken for futures-only data.  Both modes archive the downloaded ZIP and
    filtered Gold rows under ``raw/positioning/<retrieved_date>/``.

    Core integration can call this function twice when it needs both
    universes, or call ``collect_positioning_cot_combined`` for the combined
    report only.  All deltas are calculated from the immediately previous
    actual report row, never from a published change column.
    """

    if report_type not in CFTC_REPORT_TYPES:
        return _unavailable(
            report_type=report_type,
            source_url=CFTC_COT_URL,
            reason=f"unsupported CFTC report_type: {report_type!r}",
        )
    try:
        cutoff_date = date.fromisoformat(retrieved_date[:10])
    except ValueError:
        return _unavailable(
            report_type=report_type,
            source_url=CFTC_COT_URL if report_type == "futures_only" else CFTC_COMBINED_COT_URL,
            reason=f"Invalid retrieved_date for COT cutoff: {retrieved_date!r}",
        )

    source_url = cftc_cot_url(report_type=report_type, year=cutoff_date.year)
    close_client = False
    if client is None:
        client = httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "Mozilla/5.0"},
            trust_env=False,
        )
        close_client = True
    try:
        response = client.get(source_url)
        response.raise_for_status()
        return _collect_payload(
            payload=response.content,
            report_type=report_type,
            source_url=source_url,
            cutoff_date=cutoff_date,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
        )
    except Exception as exc:
        return _unavailable(
            report_type=report_type,
            source_url=source_url,
            reason=f"CFTC COT download failed: {type(exc).__name__}: {exc}",
        )
    finally:
        if close_client:
            client.close()


def collect_positioning_cot_combined(
    *,
    retrieved_date: str,
    storage_root: Path,
    client: Any | None = None,
) -> CollectorResult:
    """Explicit convenience entry point for the CFTC combined report."""

    return collect_positioning_cot(
        retrieved_date=retrieved_date,
        storage_root=storage_root,
        report_type="combined",
        client=client,
    )


def _collect_payload(
    *,
    payload: bytes,
    report_type: COTReportType,
    source_url: str,
    cutoff_date: date,
    retrieved_date: str,
    storage_root: Path,
) -> CollectorResult:
    raw_dir = storage_root / "raw" / "positioning" / cutoff_date.isoformat() / uuid4().hex
    raw_dir.mkdir(parents=True, exist_ok=False)
    archive_name = f"cftc_disagg_{report_type}_{cutoff_date.year}.zip"
    archive_path = raw_dir / archive_name
    archive_path.write_bytes(payload)
    archive_path_rel = archive_path.relative_to(storage_root).as_posix()

    try:
        report = parse_cftc_disaggregated_zip(
            payload,
            report_type=report_type,
            cutoff_date=cutoff_date,
            contract_code=GOLD_CONTRACT_CODE,
            market_name=GOLD_MARKET_NAME,
        )
    except ValueError as exc:
        return _unavailable(
            report_type=report_type,
            source_url=source_url,
            reason=str(exc),
            raw_archive_path=archive_path_rel,
        )
    if not report.rows:
        return _unavailable(
            report_type=report_type,
            source_url=source_url,
            reason=(
                f"No standard GOLD contract {GOLD_CONTRACT_CODE} rows found on or before "
                f"{cutoff_date.isoformat()} in CFTC COT CSV"
            ),
            raw_archive_path=archive_path_rel,
        )

    filtered_name = "cot_gold.json" if report_type == "futures_only" else "cot_gold_combined.json"
    filtered_path = raw_dir / filtered_name
    filtered_path.write_text(
        json.dumps(list(report.raw_rows), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    raw_path_rel = filtered_path.relative_to(storage_root).as_posix()
    retrieved_at = utc_now_iso()
    latest, previous = report.latest_pair()
    prefix = COT_SYMBOL if report_type == "futures_only" else f"{COT_SYMBOL}_combined"

    points = _build_points(
        latest=latest,
        previous=previous,
        prefix=prefix,
        source_url=source_url,
        retrieved_at=retrieved_at,
        raw_path=raw_path_rel,
    )
    source_ref = {
        "symbol": prefix,
        "source": COT_SOURCE,
        "source_url": source_url,
        "raw_path": raw_path_rel,
        "raw_archive_path": archive_path_rel,
        "contract_code": GOLD_CONTRACT_CODE,
        "market": GOLD_MARKET_NAME,
        "report_type": report_type,
        "report_date": latest.report_date.isoformat(),
        "previous_report_date": previous.report_date.isoformat() if previous else "",
        "retrieved_at": retrieved_at,
        "skipped_rows": str(report.skipped_rows),
        "provider_role": "official_primary",
        "source_tier": "official",
        "verification_status": "single_source",
    }
    return CollectorResult(points=points, unavailable_symbols=[], source_refs=[source_ref])


def _build_points(
    *,
    latest: Any,
    previous: Any | None,
    prefix: str,
    source_url: str,
    retrieved_at: str,
    raw_path: str,
) -> list[MacroPoint]:
    """Expose compatibility points plus explicit long/short/net/OI deltas."""

    def point(suffix: str, value: float, row_date: date) -> MacroPoint:
        return MacroPoint(
            symbol=f"{prefix}_{suffix}",
            date=row_date.isoformat(),
            value=round(value, 6),
            source=COT_SOURCE,
            source_url=source_url,
            retrieved_at=retrieved_at,
            raw_path=raw_path,
        )

    latest_values = {
        "open_interest": latest.open_interest,
        "producer_net": latest.producer_net,
        "swap_net": latest.swap_net,
        "commercial_net": latest.commercial_net,
        "noncomm_net": latest.managed_money_net,
        "comm_long": latest.producer_long + latest.swap_long,
        "comm_short": latest.producer_short + latest.swap_short,
        "producer_long": latest.producer_long,
        "producer_short": latest.producer_short,
        "swap_long": latest.swap_long,
        "swap_short": latest.swap_short,
        "noncomm_long": latest.managed_money_long,
        "noncomm_short": latest.managed_money_short,
        "other_long": latest.other_long,
        "other_short": latest.other_short,
        "mm_long": latest.managed_money_long,
        "mm_short": latest.managed_money_short,
        "mm_net": latest.managed_money_net,
    }
    points = [point(suffix, value, latest.report_date) for suffix, value in latest_values.items()]

    if previous is not None:
        previous_values = {
            "commercial_net_prev": previous.commercial_net,
            "producer_net_prev": previous.producer_net,
            "swap_net_prev": previous.swap_net,
            "noncomm_net_prev": previous.managed_money_net,
            "open_interest_prev": previous.open_interest,
            "mm_long_prev": previous.managed_money_long,
            "mm_short_prev": previous.managed_money_short,
            "mm_net_prev": previous.managed_money_net,
            "producer_long_prev": previous.producer_long,
            "producer_short_prev": previous.producer_short,
            "swap_long_prev": previous.swap_long,
            "swap_short_prev": previous.swap_short,
        }
        points.extend(point(suffix, value, previous.report_date) for suffix, value in previous_values.items())

        delta_values = {
            "open_interest_delta": latest.open_interest - previous.open_interest,
            "mm_long_delta": latest.managed_money_long - previous.managed_money_long,
            "mm_short_delta": latest.managed_money_short - previous.managed_money_short,
            "mm_net_delta": latest.managed_money_net - previous.managed_money_net,
            "commercial_net_delta": latest.commercial_net - previous.commercial_net,
            "producer_net_delta": latest.producer_net - previous.producer_net,
            "swap_net_delta": latest.swap_net - previous.swap_net,
            "producer_long_delta": latest.producer_long - previous.producer_long,
            "producer_short_delta": latest.producer_short - previous.producer_short,
            "swap_long_delta": latest.swap_long - previous.swap_long,
            "swap_short_delta": latest.swap_short - previous.swap_short,
        }
        points.extend(point(suffix, value, latest.report_date) for suffix, value in delta_values.items())

    return points


def _unavailable(
    *,
    report_type: str,
    source_url: str,
    reason: str,
    raw_archive_path: str | None = None,
) -> CollectorResult:
    symbol = COT_SYMBOL if report_type == "futures_only" else f"{COT_SYMBOL}_combined"
    ref: dict[str, str] = {
        "symbol": symbol,
        "source": COT_SOURCE,
        "source_url": source_url,
        "report_type": report_type,
        "reason": reason,
        "provider_role": "official_primary",
        "source_tier": "official",
        "verification_status": "single_source",
    }
    if raw_archive_path:
        ref["raw_archive_path"] = raw_archive_path
    return CollectorResult(
        points=[],
        unavailable_symbols=[symbol],
        source_refs=[ref],
    )
