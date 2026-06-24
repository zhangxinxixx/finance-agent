"""Jin10 real-time quote collector.

Collects live price quotes via Jin10 MCP ``get_quote`` for key symbols:
XAUUSD, XAGUSD, DXY, US10Y, USOIL, SPX, and other configured symbols.

Produces ``CollectorResult`` with ``MacroPoint`` entries for downstream
feature and snapshot layers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from apps.collectors.jin10.mcp_client import Jin10MCPClient
from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

logger = logging.getLogger(__name__)
JIN10_MCP_MARKET_SOURCE_KEY = "jin10_mcp_market"

# Default symbol set for premarket / real-time monitoring
DEFAULT_QUOTE_SYMBOLS = [
    "XAUUSD",   # Spot gold
    "XAGUSD",   # Spot silver
    "USDCNH",   # USD/CNH
    "EURUSD",   # EUR/USD
    "USDJPY",   # USD/JPY
    "GBPUSD",   # GBP/USD
    "USOIL",    # WTI crude
    "SPX",      # S&P 500
    "DJI",      # Dow Jones
]


def collect_quotes(
    *,
    retrieved_date: str,
    storage_root: Path,
    symbols: list[str] | None = None,
    mcp_key: str | None = None,
) -> CollectorResult:
    """Collect live quotes for configured symbols.

    Args:
        retrieved_date: ISO date string (YYYY-MM-DD)
        storage_root: Root directory for raw payload archives
        symbols: List of Jin10 quote codes (default: DEFAULT_QUOTE_SYMBOLS)
        mcp_key: Jin10 MCP API key (default: from env)

    Returns:
        CollectorResult with MacroPoint entries per symbol
    """
    symbols = symbols or DEFAULT_QUOTE_SYMBOLS
    points: list[MacroPoint] = []
    unavailable: list[str] = []
    refs: list[dict[str, Any]] = []
    retrieved_at = utc_now_iso()

    try:
        with Jin10MCPClient(mcp_key=mcp_key) as client:
            for code in symbols:
                try:
                    data = client.get_quote(code)
                    ref_path = _archive_and_ref(
                        data, retrieved_date, code, storage_root, refs
                    )
                    points.extend(_extract_quote_points(
                        data, code, ref_path, retrieved_at, retrieved_date
                    ))
                except Exception as exc:
                    logger.warning("Quote %s failed: %s", code, exc)
                    unavailable.append(f"QUOTE:{code}")
    except RuntimeError as exc:
        logger.error("Jin10 MCP quotes: %s", exc)
        unavailable.extend(f"QUOTE:{s}" for s in symbols)

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
    """Archive raw payload and add source ref."""
    raw_path = archive_raw_payload(
        storage_root=storage_root,
        source="jin10_mcp",
        retrieved_date=retrieved_date,
        symbol=f"quote_{code}",
        payload=data,
    )
    refs.append({
        "source": "jin10_mcp",
        "source_key": JIN10_MCP_MARKET_SOURCE_KEY,
        "method": f"get_quote:{code}",
        "raw_path": str(raw_path),
    })
    return str(raw_path)


def _extract_quote_points(
    data: dict[str, Any],
    code: str,
    raw_path: str,
    retrieved_at: str,
    retrieved_date: str,
) -> list[MacroPoint]:
    """Extract MacroPoints from a single quote response."""
    inner = data.get("data", data)
    if not isinstance(inner, dict):
        return []

    price = inner.get("close") or inner.get("price")
    if price is None:
        return []

    try:
        price_val = float(price)
    except (TypeError, ValueError):
        return []

    points = [
        MacroPoint(
            symbol=f"QUOTE:{code}",
            date=retrieved_date,
            value=price_val,
            source="jin10_mcp",
            source_url=raw_path,
            retrieved_at=retrieved_at,
            raw_path=raw_path,
        ),
    ]

    # Additional fields
    for field, prefix in [
        ("open", "OPEN"),
        ("high", "HIGH"),
        ("low", "LOW"),
        ("ups_price", "CHANGE"),
        ("ups_percent", "CHANGE_PCT"),
    ]:
        val = inner.get(field)
        if val is not None:
            try:
                points.append(MacroPoint(
                    symbol=f"QUOTE:{code}:{prefix}",
                    date=retrieved_date,
                    value=float(val),
                    source="jin10_mcp",
                    source_url=raw_path,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                ))
            except (TypeError, ValueError):
                pass

    return points
