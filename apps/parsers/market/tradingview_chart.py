"""Validate bounded TradingView chart WebSocket observations.

The parser accepts archived wire frames rather than a normalized provider
response.  This keeps the full provider evidence in ``raw`` while exposing
only identity, delay, completion, and OHLCV fields downstream.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Any, Iterable

from apps.parsers.market.tradingview import ALL_INSTRUMENTS

MAX_FRAME_BYTES = 1_048_576
MAX_RAW_FRAMES = 64
MAX_PROTOCOL_MESSAGES = 128
MAX_BARS = 256
RESOLUTION_SECONDS = {"1": 60, "15": 900, "60": 3_600, "240": 14_400}

_FRAME_PREFIX = b"~m~"
_DELAYED_MODE = re.compile(r"delayed_streaming_(\d+)")


class TradingViewChartParseError(ValueError):
    """Fail-closed parse error whose class is safe to expose."""

    def __init__(self, error_class: str) -> None:
        super().__init__(error_class)
        self.error_class = error_class


def decode_protocol_messages(frames: Iterable[str]) -> list[str]:
    """Decode TradingView's length-prefixed messages with hard size limits."""

    frame_list = list(frames)
    if len(frame_list) > MAX_RAW_FRAMES:
        raise TradingViewChartParseError("MessageLimitError")

    messages: list[str] = []
    for frame in frame_list:
        if not isinstance(frame, str):
            raise TradingViewChartParseError("ProtocolFrameError")
        data = frame.encode("utf-8")
        if len(data) > MAX_FRAME_BYTES:
            raise TradingViewChartParseError("FrameSizeError")

        offset = 0
        while offset < len(data):
            if not data.startswith(_FRAME_PREFIX, offset):
                raise TradingViewChartParseError("ProtocolFrameError")
            length_end = data.find(_FRAME_PREFIX, offset + len(_FRAME_PREFIX))
            if length_end < 0:
                raise TradingViewChartParseError("ProtocolFrameError")
            length_bytes = data[offset + len(_FRAME_PREFIX) : length_end]
            if not length_bytes.isdigit() or len(length_bytes) > 8:
                raise TradingViewChartParseError("ProtocolFrameError")
            payload_start = length_end + len(_FRAME_PREFIX)
            payload_end = payload_start + int(length_bytes)
            if payload_end > len(data):
                raise TradingViewChartParseError("ProtocolFrameError")
            try:
                messages.append(data[payload_start:payload_end].decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise TradingViewChartParseError("ProtocolFrameError") from exc
            if len(messages) > MAX_PROTOCOL_MESSAGES:
                raise TradingViewChartParseError("MessageLimitError")
            offset = payload_end

    return messages


def parse_tradingview_chart(
    payload: dict[str, Any],
    *,
    ticker: str,
    resolution: str,
    retrieved_at: str,
    source_ref: dict[str, Any],
) -> dict[str, Any]:
    """Parse one requested chart series after validating its provider identity."""

    if ticker not in ALL_INSTRUMENTS or resolution not in RESOLUTION_SECONDS:
        raise TradingViewChartParseError("RequestValidationError")
    if not isinstance(payload, dict) or not isinstance(payload.get("frames"), list):
        raise TradingViewChartParseError("PayloadValidationError")
    if payload.get("ticker", ticker) != ticker or str(payload.get("resolution", resolution)) != resolution:
        raise TradingViewChartParseError("PayloadIdentityError")

    decoded = decode_protocol_messages(payload["frames"])
    messages: list[dict[str, Any]] = []
    for raw_message in decoded:
        if raw_message.startswith("~h~"):
            continue
        try:
            message = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError) as exc:
            raise TradingViewChartParseError("ProtocolMessageError") from exc
        if not isinstance(message, dict):
            raise TradingViewChartParseError("ProtocolMessageError")
        messages.append(message)

    provider_methods = [message.get("m") for message in messages if isinstance(message.get("m"), str)]
    if any(method.endswith("_error") or method in {"critical_error", "protocol_error"} for method in provider_methods):
        raise TradingViewChartParseError("ProviderError")

    metadata = _resolved_metadata(messages)
    _validate_identity(ticker, metadata)
    update_mode = _completed_update_mode(messages)
    delay_seconds = _validated_delay(metadata.get("delay"), update_mode)
    bars = _validated_bars(messages, RESOLUTION_SECONDS[resolution])

    _symbol, instrument_type, _unit, _description = ALL_INSTRUMENTS[ticker]
    is_continuous = instrument_type == "futures" and ticker.endswith("1!")
    front_contract = metadata.get("front_contract")
    if is_continuous and (not isinstance(front_contract, str) or not front_contract.strip()):
        raise TradingViewChartParseError("IdentityMismatch")

    safe_metadata = {
        "exchange": metadata["exchange"],
        "instrument_type": metadata["type"],
        "currency": metadata.get("currency_code"),
        "update_mode": update_mode,
        "provider_delay_seconds": metadata.get("delay"),
        "series_completed": True,
    }
    for key in ("timezone", "session"):
        if isinstance(metadata.get(key), str):
            safe_metadata[key] = metadata[key]
    if isinstance(metadata.get("description"), str):
        safe_metadata["description"] = metadata["description"]

    return {
        "ticker": ticker,
        "status": "available",
        "resolution_seconds": RESOLUTION_SECONDS[resolution],
        "delay_seconds": delay_seconds,
        "retrieved_at": retrieved_at,
        "front_contract": front_contract if is_continuous else None,
        "continuous_contract": is_continuous,
        "bars": bars,
        "source_refs": [dict(source_ref)],
        "metadata": safe_metadata,
    }


def unavailable_tradingview_chart(
    *,
    ticker: str,
    resolution: str,
    retrieved_at: str,
    source_ref: dict[str, Any],
    error_class: str,
) -> dict[str, Any]:
    """Build a stable unavailable row without exception text or provider payloads."""

    instrument_type = ALL_INSTRUMENTS[ticker][1]
    return {
        "ticker": ticker,
        "status": "unavailable",
        "resolution_seconds": RESOLUTION_SECONDS[resolution],
        "delay_seconds": None,
        "retrieved_at": retrieved_at,
        "front_contract": None,
        "continuous_contract": instrument_type == "futures" and ticker.endswith("1!"),
        "bars": [],
        "source_refs": [dict(source_ref)],
        "error": error_class,
    }


def _resolved_metadata(messages: list[dict[str, Any]]) -> dict[str, Any]:
    resolved: list[dict[str, Any]] = []
    for message in messages:
        if message.get("m") != "symbol_resolved":
            continue
        params = message.get("p")
        if not isinstance(params, list) or len(params) < 3 or params[1] != "symbol_1" or not isinstance(params[2], dict):
            raise TradingViewChartParseError("ProtocolMessageError")
        resolved.append(params[2])
    if not resolved:
        raise TradingViewChartParseError("IdentityMissing")
    if any(item != resolved[0] for item in resolved[1:]):
        raise TradingViewChartParseError("IdentityConflict")
    return resolved[0]


def _validate_identity(ticker: str, metadata: dict[str, Any]) -> None:
    _symbol, instrument_type, unit, _description = ALL_INSTRUMENTS[ticker]
    base_name = metadata.get("base_name")
    base_names = base_name if isinstance(base_name, list) else [base_name]
    provider_name_matches = metadata.get("pro_name") == ticker or ticker in base_names
    expected_exchange = ticker.split(":", 1)[0]
    unit_currency = unit.split("/", 1)[0]
    expected_currency = unit_currency if re.fullmatch(r"[A-Z]{3}", unit_currency) else None
    if (
        not provider_name_matches
        or metadata.get("exchange") != expected_exchange
        or metadata.get("type") != instrument_type
        or (expected_currency is not None and metadata.get("currency_code") != expected_currency)
    ):
        raise TradingViewChartParseError("IdentityMismatch")


def _completed_update_mode(messages: list[dict[str, Any]]) -> str:
    modes: list[str] = []
    for message in messages:
        if message.get("m") != "series_completed":
            continue
        params = message.get("p")
        if not isinstance(params, list) or len(params) < 3 or params[1] != "s1" or not isinstance(params[2], str):
            raise TradingViewChartParseError("ProtocolMessageError")
        modes.append(params[2])
    if not modes:
        raise TradingViewChartParseError("SeriesIncomplete")
    if any(mode != modes[0] for mode in modes[1:]):
        raise TradingViewChartParseError("UpdateModeConflict")
    return modes[0]


def _validated_delay(raw_delay: Any, update_mode: str) -> int:
    metadata_delay: int | None
    if raw_delay is None:
        metadata_delay = None
    elif isinstance(raw_delay, (int, float)) and not isinstance(raw_delay, bool) and math.isfinite(raw_delay):
        metadata_delay = int(raw_delay)
        if metadata_delay != raw_delay or metadata_delay < 0:
            raise TradingViewChartParseError("UpdateModeMismatch")
    else:
        raise TradingViewChartParseError("UpdateModeMismatch")

    if update_mode == "streaming":
        if metadata_delay not in {None, 0}:
            raise TradingViewChartParseError("UpdateModeMismatch")
        return 0
    delayed = _DELAYED_MODE.fullmatch(update_mode)
    if delayed:
        completed_delay = int(delayed.group(1))
        if not 1 <= completed_delay <= 86_400:
            raise TradingViewChartParseError("UpdateModeMismatch")
        if metadata_delay is not None and metadata_delay != completed_delay:
            raise TradingViewChartParseError("UpdateModeMismatch")
        return completed_delay
    raise TradingViewChartParseError("UpdateModeMismatch")


def _validated_bars(messages: list[dict[str, Any]], resolution_seconds: int) -> list[dict[str, Any]]:
    by_timestamp: dict[int, tuple[float, float, float, float, float | None]] = {}
    saw_series = False
    for message in messages:
        if message.get("m") != "timescale_update":
            continue
        params = message.get("p")
        if not isinstance(params, list) or len(params) < 2 or not isinstance(params[1], dict):
            raise TradingViewChartParseError("ProtocolMessageError")
        series = params[1].get("s1")
        if series is None:
            continue
        if not isinstance(series, dict) or not isinstance(series.get("s"), list):
            raise TradingViewChartParseError("ProtocolMessageError")
        saw_series = True
        for item in series["s"]:
            values = item.get("v") if isinstance(item, dict) else None
            if not isinstance(values, list) or len(values) < 5:
                raise TradingViewChartParseError("BarValidationError")
            timestamp, open_, high, low, close = values[:5]
            volume = values[5] if len(values) >= 6 else None
            numbers = (timestamp, open_, high, low, close)
            if any(not _finite_number(value) for value in numbers):
                raise TradingViewChartParseError("BarValidationError")
            if volume is not None and not _finite_number(volume):
                raise TradingViewChartParseError("BarValidationError")
            timestamp_int = int(timestamp)
            # Native 4H bars may be anchored to a provider trading session
            # (e.g. 17:00 New York), not midnight UTC. Keep their timestamps.
            alignment = 3600 if resolution_seconds == 14400 else resolution_seconds
            if timestamp_int != timestamp or timestamp_int % alignment:
                raise TradingViewChartParseError("BarValidationError")
            ohlcv = (float(open_), float(high), float(low), float(close), float(volume) if volume is not None else None)
            if high < max(open_, close) or low > min(open_, close) or high < low or (volume is not None and volume < 0):
                raise TradingViewChartParseError("BarValidationError")
            previous = by_timestamp.get(timestamp_int)
            if previous is not None and previous != ohlcv:
                raise TradingViewChartParseError("BarConflictError")
            by_timestamp[timestamp_int] = ohlcv
            if len(by_timestamp) > MAX_BARS:
                raise TradingViewChartParseError("BarLimitError")

    if not saw_series or not by_timestamp:
        raise TradingViewChartParseError("BarsMissing")

    return [
        {
            "time": _utc_bar_time(timestamp),
            "open": values[0],
            "high": values[1],
            "low": values[2],
            "close": values[3],
            "volume": values[4],
        }
        for timestamp, values in sorted(by_timestamp.items())
    ]


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _utc_bar_time(timestamp: int) -> str:
    try:
        return datetime.fromtimestamp(timestamp, UTC).isoformat()
    except (OverflowError, OSError, ValueError) as exc:
        raise TradingViewChartParseError("BarValidationError") from exc
