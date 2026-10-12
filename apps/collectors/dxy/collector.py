from __future__ import annotations

import math
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

TRADINGVIEW_SCAN_URL = "https://scanner.tradingview.com/america/scan"
CNBC_DXY_URL = "https://quote.cnbc.com/quote-html-webservice/quote.htm"


def collect_dxy_series(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    tv_result = _collect_from_tradingview(retrieved_date=retrieved_date, storage_root=storage_root)
    cnbc_result = _collect_from_cnbc(retrieved_date=retrieved_date, storage_root=storage_root)
    # The TradingView scanner supplies one dated bar plus undated performance
    # fields. CNBC's verified prior-session comparison is useful metadata,
    # although its absent prior date must not become a fabricated history point.
    if cnbc_result.points and any(ref.get("previous_close_status") == "verified_by_provider_change" for ref in cnbc_result.source_refs):
        return cnbc_result
    if tv_result.points:
        return tv_result
    if cnbc_result.points:
        return cnbc_result
    return CollectorResult(points=[], unavailable_symbols=["DXY"], source_refs=[*tv_result.source_refs, *cnbc_result.source_refs])


def _collect_from_tradingview(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    payload = {"symbols": {"tickers": ["TVC:DXY"], "query": {"types": []}}, "columns": ["close", "Perf.W", "Perf.1M", "description", "time"]}
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
            response = client.post(TRADINGVIEW_SCAN_URL, json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        return _unavailable("tradingview", f"TradingView request failed: {type(exc).__name__}: {exc}")
    raw_path = archive_raw_payload(storage_root=storage_root, source="tradingview", retrieved_date=retrieved_date, symbol="DXY", payload=data)
    try:
        row = data["data"][0]
        close, perf_w, perf_1m, _, bar_timestamp = row["d"]
        current = _finite_positive_float(close)
        bar_time = datetime.fromtimestamp(int(bar_timestamp), tz=UTC)
        if bar_time.date() > date.fromisoformat(retrieved_date):
            raise ValueError("future provider bar")
    except Exception as exc:
        return CollectorResult(points=[], unavailable_symbols=["DXY"], source_refs=[{"symbol": "DXY", "source": "tradingview", "source_url": TRADINGVIEW_SCAN_URL, "raw_path": raw_path, "reason": f"Payload parse: {type(exc).__name__}: {exc}"}])
    retrieved_at = utc_now_iso()
    points = [_point("DXY", bar_time.date(), current, "tradingview", raw_path, retrieved_at)]
    # Provider percentage changes are metadata, not dated historical closes.
    return CollectorResult(points=points, unavailable_symbols=[], source_refs=[{"symbol": "DXY", "source": "tradingview", "source_url": TRADINGVIEW_SCAN_URL, "raw_path": raw_path, "retrieved_at": retrieved_at, "provider_bar_time": bar_time.isoformat(), "weekly_performance_pct": perf_w, "monthly_performance_pct": perf_1m}])


def _collect_from_cnbc(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    params = {"symbols": ".DXY", "requestMethod": "quick", "noform": "1", "partnerId": "2", "fund": "1", "exthrs": "1", "output": "json"}
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
            response = client.get(CNBC_DXY_URL, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        return _unavailable("cnbc", f"CNBC fallback failed: {type(exc).__name__}: {exc}")
    raw_path = archive_raw_payload(storage_root=storage_root, source="cnbc", retrieved_date=retrieved_date, symbol="DXY", payload=data)
    try:
        quote = data["QuickQuoteResult"]["QuickQuote"][0]
        value = _finite_positive_float(quote["last"])
        quote_time = _parse_cnbc_quote_time(quote)
        if quote_time.date() > date.fromisoformat(retrieved_date):
            raise ValueError("missing timezone or future quote timestamp")
    except Exception as exc:
        return CollectorResult(points=[], unavailable_symbols=["DXY"], source_refs=[{"symbol": "DXY", "source": "cnbc", "source_url": CNBC_DXY_URL, "raw_path": raw_path, "reason": f"Payload parse: {type(exc).__name__}: {exc}"}])
    retrieved_at = utc_now_iso()
    quote_date = quote_time.date()
    points = [_point("DXY", quote_date, value, "cnbc", raw_path, retrieved_at)]
    source_ref: dict[str, object] = {
        "symbol": "DXY",
        "source": "cnbc",
        "source_url": CNBC_DXY_URL,
        "raw_path": raw_path,
        "retrieved_at": retrieved_at,
        "provider_observation_time": quote_time.isoformat(),
    }

    # CNBC exposes the prior session's close in the same quote payload, but
    # does not expose its date. Keep that value as provider metadata only; a
    # dated MacroPoint requires an observed date and cannot use a weekday guess.
    try:
        previous_value = _finite_positive_float(quote["previous_day_closing"])
        provider_change = _optional_finite_float(quote.get("change"))
        if provider_change is None:
            raise ValueError("provider change missing")
        if not _close_enough(value - previous_value, provider_change):
            raise ValueError("previous close conflicts with provider change")
        source_ref.update({
            "previous_observation_date": None,
            "previous_observation_status": "unavailable",
            "previous_close_field": "previous_day_closing",
            "previous_close": f"{previous_value:.6f}",
            "reported_daily_change": f"{provider_change:.6f}",
            "comparison": "provider_previous_session",
            "previous_close_status": "verified_by_provider_change",
        })
    except (KeyError, TypeError, ValueError):
        source_ref["previous_observation_date"] = None
        source_ref["previous_observation_status"] = "unavailable"
        source_ref["previous_observation_reason"] = "provider_previous_day_closing_missing_or_conflicting"

    source_ref["history_points"] = str(len(points))
    return CollectorResult(points=points, unavailable_symbols=[], source_refs=[source_ref])  # type: ignore[arg-type]


def _parse_cnbc_quote_time(quote: dict[str, object]) -> datetime:
    """Return a timezone-aware provider observation time.

    CNBC commonly includes ``reg_last_time`` with an offset; the millisecond
    epoch and ISO ``last_time`` are accepted as explicit fallbacks. A date-only
    value is not promoted because it has no timezone or clock provenance.
    """
    for field in ("reg_last_time", "last_time_msec", "last_time"):
        raw = quote.get(field)
        if raw in (None, ""):
            continue
        try:
            if field == "last_time_msec":
                parsed = datetime.fromtimestamp(float(raw) / 1000.0, tz=UTC)
            else:
                parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed
        except (TypeError, ValueError, OverflowError, OSError):
            continue
    raise ValueError("missing timezone-aware quote timestamp")


def _finite_positive_float(value: object) -> float:
    parsed = float(str(value).replace(",", ""))
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError("expected finite positive number")
    return parsed


def _optional_finite_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    parsed = float(str(value).replace(",", ""))
    return parsed if math.isfinite(parsed) else None


def _close_enough(left: float, right: float) -> bool:
    return abs(left - right) <= max(0.005, abs(right) * 0.02)


def _point(symbol, point_date, value, source, raw_path, retrieved_at):
    return MacroPoint(symbol=symbol, date=point_date.isoformat(), value=round(value, 6), source=source, source_url=TRADINGVIEW_SCAN_URL if source == "tradingview" else CNBC_DXY_URL, retrieved_at=retrieved_at, raw_path=raw_path)


def _unavailable(source, reason):
    return CollectorResult(points=[], unavailable_symbols=["DXY"], source_refs=[{"symbol": "DXY", "source": source, "source_url": TRADINGVIEW_SCAN_URL if source == "tradingview" else CNBC_DXY_URL, "reason": reason}])
