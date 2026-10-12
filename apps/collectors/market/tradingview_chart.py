"""Bounded anonymous TradingView chart WebSocket collector."""

from __future__ import annotations

import json
import re
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso
from apps.parsers.market.tradingview import ALL_INSTRUMENTS
from apps.parsers.market.tradingview_chart import (
    MAX_FRAME_BYTES,
    MAX_PROTOCOL_MESSAGES,
    MAX_RAW_FRAMES,
    RESOLUTION_SECONDS,
    TradingViewChartParseError,
    decode_protocol_messages,
    parse_tradingview_chart,
    unavailable_tradingview_chart,
)
from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle

URL = "wss://data.tradingview.com/socket.io/websocket"
ORIGIN = "https://www.tradingview.com"
AUTH_TOKEN = "unauthorized_user_token"
MAX_SYMBOLS = 8
REQUEST_DEADLINE_SECONDS = 30.0

ChartConnector = Callable[..., list[str] | dict[str, Any]]


class _ChartReadError(RuntimeError):
    def __init__(self, error_class: str, frames: list[str]) -> None:
        super().__init__(error_class)
        self.error_class = error_class
        self.frames = frames


def collect_tradingview_chart(
    *,
    retrieved_date: str,
    storage_root: str | Path,
    symbols: list[str] | tuple[str, ...],
    resolution: str = "15",
    bar_count: int = 64,
    connector: ChartConnector | None = None,
) -> dict[str, Any]:
    """Collect at most eight allowlisted public chart series without credentials."""

    _validate_date(retrieved_date)
    selected = tuple(dict.fromkeys(symbols))
    if not selected or len(selected) > MAX_SYMBOLS or any(ticker not in ALL_INSTRUMENTS for ticker in selected):
        raise ValueError("unsupported TradingView chart symbol selection")
    if resolution not in RESOLUTION_SECONDS:
        raise ValueError("unsupported TradingView chart resolution")
    if isinstance(bar_count, bool) or not isinstance(bar_count, int) or not 1 <= bar_count <= 256:
        raise ValueError("TradingView chart bar_count must be between 1 and 256")

    root = Path(storage_root)
    connect_chart = connector or _request_chart_frames

    def request(ticker: str) -> tuple[list[str], str | None, str]:
        frames: list[str] = []
        error_class: str | None = None
        try:
            response = connect_chart(ticker=ticker, resolution=resolution, bar_count=bar_count)
            frames = response.get("frames") if isinstance(response, dict) else response
            if isinstance(response, dict):
                if response.get("ticker", ticker) != ticker or str(response.get("resolution", resolution)) != resolution:
                    frames, error_class = [], "PayloadIdentityError"
            if not isinstance(frames, list) or any(not isinstance(frame, str) for frame in frames):
                frames, error_class = [], "PayloadValidationError"
        except _ChartReadError as exc:
            frames, error_class = exc.frames, exc.error_class
        except Exception as exc:  # Connector implementations are an explicit failure boundary.
            frames, error_class = [], _safe_error_class(exc)
        return frames, error_class, utc_now_iso()

    with ThreadPoolExecutor(max_workers=min(4, len(selected)), thread_name_prefix="tradingview-chart") as executor:
        requested = dict(zip(selected, executor.map(request, selected)))
    retrieved_at = utc_now_iso()

    series: list[dict[str, Any]] = []
    all_refs: list[dict[str, Any]] = []
    for ticker in selected:
        frames, transport_error, series_retrieved_at = requested[ticker]
        raw_payload = {
            "ticker": ticker,
            "resolution": resolution,
            "bar_count": bar_count,
            "transport_url": URL,
            "frames": frames,
            "retrieved_at": series_retrieved_at,
            "error_class": transport_error,
        }
        raw_path = archive_raw_payload(
            storage_root=root,
            source="tradingview_chart",
            retrieved_date=retrieved_date,
            symbol=ALL_INSTRUMENTS[ticker][0],
            payload=raw_payload,
        )
        source_ref = {
            "source": "tradingview_chart",
            "source_url": f"https://www.tradingview.com/chart/?symbol={quote(ticker, safe='')}",
            "ticker": ticker,
            "raw_path": raw_path,
            "retrieved_at": series_retrieved_at,
            "source_tier": "secondary",
            "evidence_scope": "provider_chart_observation",
        }
        all_refs.append(source_ref)
        if transport_error:
            parsed = unavailable_tradingview_chart(
                ticker=ticker,
                resolution=resolution,
                retrieved_at=series_retrieved_at,
                source_ref=source_ref,
                error_class=transport_error,
            )
        else:
            try:
                parsed = parse_tradingview_chart(
                    raw_payload,
                    ticker=ticker,
                    resolution=resolution,
                    retrieved_at=series_retrieved_at,
                    source_ref=source_ref,
                )
            except TradingViewChartParseError as exc:
                parsed = unavailable_tradingview_chart(
                    ticker=ticker,
                    resolution=resolution,
                    retrieved_at=series_retrieved_at,
                    source_ref=source_ref,
                    error_class=exc.error_class,
                )
        series.append(parsed)

    result = {
        "schema_version": "tradingview_chart_series.v1",
        "retrieved_at": retrieved_at,
        "series": series,
        "source_refs": all_refs,
    }
    parsed_path = root / "parsed" / "tradingview_chart" / retrieved_date / f"{uuid.uuid4().hex}.json"
    write_immutable_artifact_bundle([immutable_json_item(parsed_path, result)], storage_root=root)
    return {**result, "parsed_path": parsed_path.relative_to(root).as_posix()}


def _request_chart_frames(*, ticker: str, resolution: str, bar_count: int) -> list[str]:
    """Read one anonymous public chart series within a wall-clock deadline."""

    from websockets.sync.client import connect

    chart_session = f"cs_{secrets.token_hex(6)}"
    commands = [
        ("set_auth_token", [AUTH_TOKEN]),
        ("chart_create_session", [chart_session, ""]),
        ("switch_timezone", [chart_session, "Etc/UTC"]),
        (
            "resolve_symbol",
            [
                chart_session,
                "symbol_1",
                "=" + json.dumps({"symbol": ticker, "adjustment": "splits", "session": "regular"}, separators=(",", ":")),
            ],
        ),
        ("create_series", [chart_session, "s1", "s1", "symbol_1", resolution, bar_count, ""]),
    ]
    frames: list[str] = []
    deadline = time.monotonic() + REQUEST_DEADLINE_SECONDS
    try:
        with connect(
            URL,
            origin=ORIGIN,
            proxy=None,
            open_timeout=min(15.0, REQUEST_DEADLINE_SECONDS),
            close_timeout=1.0,
            ping_interval=None,
            max_size=MAX_FRAME_BYTES,
            max_queue=MAX_RAW_FRAMES,
        ) as websocket:
            for method, params in commands:
                websocket.send(_wire_message(method, params))

            message_count = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                frame = websocket.recv(timeout=remaining)
                if not isinstance(frame, str):
                    raise TypeError
                if len(frame.encode("utf-8")) > MAX_FRAME_BYTES:
                    raise ValueError
                frames.append(frame)
                if len(frames) > MAX_RAW_FRAMES:
                    raise OverflowError
                payloads = decode_protocol_messages([frame])
                message_count += len(payloads)
                if message_count > MAX_PROTOCOL_MESSAGES:
                    raise OverflowError
                for payload in payloads:
                    if payload.startswith("~h~"):
                        websocket.send(_wire_payload(payload))
                methods = _message_methods(payloads)
                if any(method.endswith("_error") or method in {"critical_error", "protocol_error"} for method in methods):
                    return frames
                if "series_completed" in methods:
                    return frames
    except Exception as exc:
        raise _ChartReadError(_safe_transport_error(exc), frames) from exc


def _wire_message(method: str, params: list[Any]) -> str:
    return _wire_payload(json.dumps({"m": method, "p": params}, separators=(",", ":"), ensure_ascii=True))


def _wire_payload(payload: str) -> str:
    return f"~m~{len(payload.encode('utf-8'))}~m~{payload}"


def _message_methods(payloads: list[str]) -> list[str]:
    methods: list[str] = []
    for payload in payloads:
        if payload.startswith("~h~"):
            continue
        try:
            message = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and isinstance(message.get("m"), str):
            methods.append(message["m"])
    return methods


def _safe_transport_error(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "TimeoutError"
    if isinstance(exc, OverflowError):
        return "MessageLimitError"
    if isinstance(exc, TypeError):
        return "ProtocolFrameError"
    if isinstance(exc, ValueError):
        return "FrameSizeError"
    if isinstance(exc, TradingViewChartParseError):
        return exc.error_class
    return _safe_error_class(exc)


def _safe_error_class(exc: Exception) -> str:
    name = type(exc).__name__
    return name if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name) else "TransportError"


def _validate_date(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("retrieved_date must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("retrieved_date must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError("retrieved_date must be an ISO date")
