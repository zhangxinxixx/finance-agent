"""Jin10 minute-level K-line collector.

Collects 1-minute K-line data via Jin10 MCP ``get_kline`` for specified
symbols. Used for intraday technical analysis and level monitoring.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from apps.collectors.jin10.mcp_client import Jin10MCPClient
from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

logger = logging.getLogger(__name__)
JIN10_MCP_MARKET_SOURCE_KEY = "jin10_mcp_market"

DEFAULT_KLINE_COUNT = 100


def collect_kline(
    *,
    retrieved_date: str,
    storage_root: Path,
    codes: list[str] | None = None,
    count: int = DEFAULT_KLINE_COUNT,
    mcp_key: str | None = None,
) -> CollectorResult:
    """Collect minute K-line data for configured symbols.

    Args:
        retrieved_date: ISO date string
        storage_root: Root directory for raw payload archives
        codes: List of Jin10 quote codes (default: ['XAUUSD', 'DXY'])
        count: Number of candles per symbol (1-100)
        mcp_key: Jin10 MCP API key

    Returns:
        CollectorResult with per-candle MacroPoint entries
    """
    codes = codes or ["XAUUSD", "DXY"]
    points: list[MacroPoint] = []
    unavailable: list[str] = []
    refs: list[dict[str, Any]] = []
    retrieved_at = utc_now_iso()

    try:
        with Jin10MCPClient(mcp_key=mcp_key) as client:
            for code in codes:
                try:
                    ts = int(time.time())
                    data = client.get_kline(code, time_stamp=ts, count=count)
                    ref_path = _archive_and_ref(
                        data, retrieved_date, code, storage_root, refs
                    )
                    points.extend(_extract_kline_points(
                        data, code, ref_path, retrieved_at, retrieved_date
                    ))
                except Exception as exc:
                    logger.warning("Kline %s failed: %s", code, exc)
                    unavailable.append(f"KLINE:{code}")
    except RuntimeError as exc:
        logger.error("Jin10 MCP kline: %s", exc)
        unavailable.extend(f"KLINE:{c}" for c in (codes or []))

    return CollectorResult(
        points=points,
        unavailable_symbols=unavailable,
        source_refs=refs,
    )


def _archive_and_ref(
    data: dict[str, Any],
    retrieved_date: str,
    code: str,
    storage_root: Path,
    refs: list[dict[str, Any]],
) -> str:
    raw_path = archive_raw_payload(
        storage_root=storage_root,
        source="jin10_mcp",
        retrieved_date=retrieved_date,
        symbol=f"kline_{code}",
        payload=data,
    )
    refs.append({
        "source": "jin10_mcp",
        "source_key": JIN10_MCP_MARKET_SOURCE_KEY,
        "method": f"get_kline:{code}",
        "raw_path": str(raw_path),
    })
    return str(raw_path)


def _extract_kline_points(
    data: dict[str, Any],
    code: str,
    raw_path: str,
    retrieved_at: str,
    retrieved_date: str,
) -> list[MacroPoint]:
    """Extract MacroPoints from K-line response.

    Each candle becomes one MacroPoint with OHLCV encoded in the value metadata.
    """
    inner = data.get("data", data)
    if not isinstance(inner, dict):
        return []

    candles = inner.get("klines") or inner.get("list") or inner.get("data") or []
    if not isinstance(candles, list):
        return []

    points: list[MacroPoint] = []
    for candle in candles:
        if not isinstance(candle, dict):
            continue
        # Encode OHLCV as a pseudo-value (close price) plus raw_path
        close_val = candle.get("close") or candle.get("c")
        if close_val is None:
            continue
        try:
            val = float(close_val)
        except (TypeError, ValueError):
            continue

        candle_ts = candle.get("time") or candle.get("t") or ""
        points.append(MacroPoint(
            symbol=f"KLINE:{code}:{candle_ts}",
            date=retrieved_date,
            value=val,
            source="jin10_mcp",
            source_url=raw_path,
            retrieved_at=retrieved_at,
            raw_path=raw_path,
        ))

    return points
