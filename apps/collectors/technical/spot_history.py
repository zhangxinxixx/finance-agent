"""XAU/USD spot history and bounded execution-timeframe observations.

The daily history remains the compatibility output consumed by the macro
pipeline.  Optional quote/intraday collection is intentionally explicit so a
caller can decide when the additional provider requests are justified.  A
completed candle is never labelled as a live quote.
"""

import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import httpx

from apps.collectors.twelvedata.client import (
    SUPPORTED_INTERVALS,
    TWELVE_DATA_API_URL,
    TWELVE_DATA_SYMBOL,
    TwelveDataClient,
)
from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.runtime.secret_resolver import resolve_runtime_secret

TWELVE_DATA_QUOTE_API_URL = "https://api.twelvedata.com/quote"
TWELVE_DATA_API_KEY_ENV = "TWELVE_DATA_API_KEY"
PROVIDER_GRACE_SECONDS = 75
INTRADAY_INTERVALS = ("4h", "1h", "15min", "5min")
_INTERVAL_SECONDS = {"4h": 14_400, "1h": 3_600, "15min": 900, "5min": 300}


def collect_spot_history(
    *,
    retrieved_date: str,
    storage_root: Path,
    include_quote: bool = False,
    include_intraday: bool = False,
    intraday_outputsize: int = 120,
    clock: Callable[[], datetime] | None = None,
) -> CollectorResult:
    clock = clock or (lambda: datetime.now(UTC))
    client = TwelveDataClient(storage_root=storage_root, clock=clock)
    daily_error = None
    try:
        result = client.fetch_time_series(interval="1day", outputsize=80)
    except Exception as exc:
        # The client archives transport failures. Keep optional intraday/quote
        # requests independent, without exposing provider exception text.
        daily_error = type(exc).__name__
        result = None
    retrieved_at = result.retrieved_at if result is not None else _as_utc(clock())
    cutoff = min(retrieved_at, datetime.combine(date.fromisoformat(retrieved_date) + timedelta(days=1), datetime.min.time(), tzinfo=UTC))
    # A provider's unfinished daily bar is not a daily close. Weekend labels
    # are excluded from this 24x5 spot proxy; they cannot create a new session.
    bars = sorted((bar for bar in (result.candles if result else []) if bar.open_time.weekday() < 5 and bar.open_time + timedelta(days=1) <= cutoff), key=lambda bar: bar.open_time)
    ref = {
        **(result.source_ref() if result else {}),
        "source": "twelvedata_xauusd_daily",
        "symbol": "XAUUSD",
        "source_url": TWELVE_DATA_API_URL,
        "frequency": "daily",
        "retrieved_at": retrieved_at.isoformat(),
        "notes": {"source_refs": [], "spot_anchor": {"status": "unavailable", "reason": "daily_history_unavailable"}},
    }
    if not bars:
        ref.update(reason="daily_request_failed" if daily_error else "no_completed_spot_daily_bars")
        if daily_error:
            ref["error_type"] = daily_error
    else:
        latest = bars[-1]
        ref["notes"].update({
            "quote_time": (latest.open_time + timedelta(days=1)).isoformat(),
            "observation_date": latest.open_time.date().isoformat(),
            "open": latest.open, "high": latest.high, "low": latest.low,
            "closes": [bar.close for bar in bars],
            "highs": [bar.high for bar in bars], "lows": [bar.low for bar in bars],
            "dates": [bar.open_time.date().isoformat() for bar in bars],
            "instrument_type": "composite_otc_spot_proxy", "quality_status": "observe",
        })
        # A daily close remains a fallback, never a current quote.
        daily_anchor = _bar_anchor(
            price=latest.close,
            price_time=latest.open_time + timedelta(days=1),
            raw_path=result.raw_path,
            retrieved_at=result.retrieved_at,
            anchor_kind="daily_close",
            delay="completed_daily_bar",
        )
        ref["notes"]["spot_anchor"] = daily_anchor
        ref["notes"]["source_refs"] = [{
            "source": ref["source"],
            "source_url": ref["source_url"],
            "raw_path": result.raw_path,
            "retrieved_at": result.retrieved_at.isoformat(),
        }]

    execution_timeframes: dict[str, dict[str, Any]] = {}
    if include_intraday:
        for interval in INTRADAY_INTERVALS:
            execution_timeframes[SUPPORTED_INTERVALS[interval]] = _collect_execution_timeframe(
                client=client,
                interval=interval,
                outputsize=intraday_outputsize,
            )
        ref["notes"]["execution_timeframes"] = execution_timeframes

    if include_quote:
        # This timestamp is captured after the final optional intraday call.
        # The daily result's retrieval time can be materially earlier and must
        # never be reused as if it were the quote response time.
        quote = _collect_quote(storage_root=storage_root, retrieved_at=_as_utc(clock()), clock=clock)
        if quote is not None:
            quote_anchor, quote_ref = quote
            ref["notes"]["spot_anchor"] = quote_anchor
            ref["notes"]["source_refs"].append(quote_ref)
        else:
            ref["notes"]["spot_anchor"]["quote_status"] = "unavailable"

    # If a quote endpoint is unavailable, a completed 5m bar is a more useful
    # execution anchor than a daily close, but it remains explicitly partial.
    if not include_quote and include_intraday:
        five_minute = execution_timeframes.get("5m")
        if isinstance(five_minute, dict) and five_minute.get("status") == "available":
            latest_bar = (five_minute.get("bars") or [])[-1]
            if isinstance(latest_bar, dict):
                ref["notes"]["spot_anchor"] = _bar_anchor(
                    price=float(latest_bar["close"]),
                    price_time=datetime.fromisoformat(str(latest_bar["close_time"])),
                    raw_path=str(five_minute["raw_path"]),
                    retrieved_at=datetime.fromisoformat(str(five_minute["retrieved_at"])),
                    anchor_kind="intraday_bar",
                    delay="completed_5m_bar",
                )
                ref["notes"]["spot_anchor"]["source_refs"] = [{
                    "source": "twelvedata_xauusd_5m",
                    "source_url": TWELVE_DATA_API_URL,
                    "raw_path": five_minute["raw_path"],
                    "retrieved_at": five_minute["retrieved_at"],
                }]
    points = [MacroPoint(symbol="XAUUSD", date=bar.open_time.date().isoformat(), value=bar.close, source=ref["source"], source_url=TWELVE_DATA_API_URL, retrieved_at=result.retrieved_at.isoformat(), raw_path=result.raw_path) for bar in bars]
    return CollectorResult(points=points, unavailable_symbols=[] if bars else ["XAUUSD"], source_refs=[ref])


def _collect_execution_timeframe(
    *,
    client: TwelveDataClient,
    interval: str,
    outputsize: int,
) -> dict[str, Any]:
    """Collect only completed bars for one bounded execution timeframe."""

    try:
        result = client.fetch_time_series(interval=interval, outputsize=outputsize)
    except Exception as exc:
        return {
            "status": "unavailable",
            "timeframe": SUPPORTED_INTERVALS[interval],
            "interval": interval,
            "instrument_type": "spot",
            "timezone": "UTC",
            "error_type": type(exc).__name__,
            "reason": "provider_request_failed",
        }

    closed_before = result.retrieved_at - timedelta(seconds=PROVIDER_GRACE_SECONDS)
    interval_seconds = _INTERVAL_SECONDS[interval]
    closed = [
        candle for candle in result.candles
        if candle.open_time + timedelta(seconds=interval_seconds) <= closed_before
    ]
    bars = [
        {
            "open_time": candle.open_time.isoformat(),
            "close_time": (candle.open_time + timedelta(seconds=interval_seconds)).isoformat(),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
        }
        for candle in closed
    ]
    return {
        "status": "available" if bars else "partial",
        "timeframe": result.timeframe,
        "interval": interval,
        "instrument_type": "spot",
        "timezone": "UTC",
        "retrieved_at": result.retrieved_at.isoformat(),
        "closed_before": closed_before.isoformat(),
        "raw_path": result.raw_path,
        "ticker": "XAUUSD",
        "symbol": "XAUUSD",
        "unit": "USD/oz",
        "source_refs": [{
            "source": f"twelvedata_xauusd_{result.timeframe}",
            "source_url": TWELVE_DATA_API_URL,
            "raw_path": result.raw_path,
            "retrieved_at": result.retrieved_at.isoformat(),
            "symbol": "XAUUSD",
            "provider_symbol": TWELVE_DATA_SYMBOL,
            "instrument_type": "spot",
            "unit": "USD/oz",
        }],
        "bars": bars,
        "latest_closed_time": bars[-1]["close_time"] if bars else None,
        "credits_used": result.credits_used,
        "credits_left": result.credits_left,
    }


def _collect_quote(*, storage_root: Path, retrieved_at: datetime, clock=None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Fetch and archive Twelve Data's quote timestamp without fabricating it."""

    api_key = resolve_runtime_secret(TWELVE_DATA_API_KEY_ENV)
    if not api_key:
        return None
    request_params = {"symbol": TWELVE_DATA_SYMBOL}
    try:
        with httpx.Client(timeout=20.0, trust_env=True) as http_client:
            response = http_client.get(
                TWELVE_DATA_QUOTE_API_URL,
                params=request_params,
                headers={"Authorization": f"apikey {api_key}", "User-Agent": "finance-agent/0.1"},
            )
            payload = response.json()
            if clock is not None:
                retrieved_at = _as_utc(clock())
            raw_path = _archive_quote(
                storage_root=storage_root,
                retrieved_at=retrieved_at,
                request_params=request_params,
                http_status=response.status_code,
                payload=payload if isinstance(payload, dict) else {"payload": payload},
            )
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    if response.status_code >= 400 or not isinstance(payload, dict):
        return None
    price = _number(payload.get("close") or payload.get("price"))
    quote_epoch = _number(payload.get("last_quote_at"))
    if price is None or quote_epoch is None:
        return None
    try:
        price_time = datetime.fromtimestamp(quote_epoch, UTC)
    except (OverflowError, OSError, ValueError):
        return None
    delay_seconds = (retrieved_at - price_time).total_seconds()
    status = "verified" if 0.0 <= delay_seconds <= 15 * 60 else "partial"
    source_ref = {
        "source": "twelvedata_xauusd_quote",
        "source_url": TWELVE_DATA_QUOTE_API_URL,
        "raw_path": raw_path,
        "retrieved_at": retrieved_at.isoformat(),
    }
    return (
        {
            "price": price,
            "price_time": price_time.isoformat(),
            "instrument_type": "spot",
            "timezone": "UTC",
            "delay": "provider_quote_timestamp",
            "delay_seconds": round(delay_seconds, 3),
            "anchor_kind": "quote",
            "status": status,
            "is_market_open": payload.get("is_market_open"),
            "source_refs": [source_ref],
        },
        source_ref,
    )


def _archive_quote(
    *,
    storage_root: Path,
    retrieved_at: datetime,
    request_params: dict[str, str],
    http_status: int,
    payload: dict[str, Any],
) -> str:
    root = storage_root / "raw" / "market" / "twelvedata" / retrieved_at.date().isoformat()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"XAU-USD-quote-{retrieved_at.strftime('%H%M%S%f')}-{uuid4().hex[:8]}.json"
    path.write_text(json.dumps({
        "provider": "twelve_data",
        "provider_symbol": TWELVE_DATA_SYMBOL,
        "request": request_params,
        "retrieved_at": retrieved_at.isoformat(),
        "http_status": http_status,
        "response": payload,
        "parser_version": "twelvedata_quote_v1",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path.relative_to(storage_root).as_posix()


def _bar_anchor(
    *,
    price: float,
    price_time: datetime,
    raw_path: str,
    retrieved_at: datetime,
    anchor_kind: str,
    delay: str,
) -> dict[str, Any]:
    delay_seconds = max(0.0, (retrieved_at - price_time).total_seconds())
    return {
        "price": price,
        "price_time": price_time.isoformat(),
        "instrument_type": "spot",
        "timezone": "UTC",
        "delay": delay,
        "delay_seconds": round(delay_seconds, 3),
        "anchor_kind": anchor_kind,
        "status": "partial",
        "source_refs": [{
            "source": "twelvedata_xauusd",
            "source_url": TWELVE_DATA_API_URL,
            "raw_path": raw_path,
            "retrieved_at": retrieved_at.isoformat(),
        }],
    }


def _number(value: object) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
