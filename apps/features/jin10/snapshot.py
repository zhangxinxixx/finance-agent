"""Jin10 unified feature snapshot.

Consolidates all Jin10 MCP data into a single filesystem JSON snapshot:
  - Real-time quotes (get_quote)
  - K-line data (get_kline)
  - Flash news (list_flash, search_flash)
  - News articles (list_news, search_news, get_news)
  - Economic calendar (list_calendar)

This is the feature-layer output consumed by downstream agents and the
analysis snapshot builder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.parsers.macro.models import CollectorResult

SNAPSHOT_VERSION = "1.0.0"


# ── Schema types ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QuoteEntry:
    """A single quote snapshot."""

    code: str
    name: str | None
    price: float | None
    open: float | None
    high: float | None
    low: float | None
    change: float | None
    change_pct: float | None
    updated_at: str | None


@dataclass(frozen=True)
class Jin10Snapshot:
    """Unified Jin10 data snapshot for a single run."""

    snapshot_id: str
    asset: str = "XAUUSD"
    trade_date: str = ""
    run_id: str = ""
    generated_at: str = ""

    quotes: dict[str, QuoteEntry] = field(default_factory=dict)
    flash_count: int = 0
    article_count: int = 0
    calendar_event_count: int = 0
    kline_codes: list[str] = field(default_factory=list)

    status: str = "unavailable"  # available | partial | unavailable
    unavailable_modules: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)


# ── Builder ───────────────────────────────────────────────────────────────


def build_jin10_snapshot(
    *,
    asset: str,
    trade_date: str,
    run_id: str,
    quotes_result: CollectorResult | None = None,
    flash_result: CollectorResult | None = None,
    article_result: CollectorResult | None = None,
    calendar_result: CollectorResult | None = None,
    kline_result: CollectorResult | None = None,
) -> Jin10Snapshot:
    """Build a unified Jin10 feature snapshot from collector results.

    Args:
        asset: Asset code (e.g. 'XAUUSD')
        trade_date: Trade date (YYYY-MM-DD)
        run_id: Run identifier
        quotes_result: Result from quotes collector
        flash_result: Result from flash/news collector (existing)
        article_result: Result from article collector
        calendar_result: Result from calendar collector
        kline_result: Result from K-line collector

    Returns:
        Jin10Snapshot with consolidated data
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    snapshot_id = f"{asset}:{trade_date}:{run_id}:jin10"

    quotes: dict[str, QuoteEntry] = {}
    unavailable: list[str] = []
    refs: list[dict[str, Any]] = []

    # ── Quotes ──────────────────────────────────────────────────
    if quotes_result:
        refs.extend(quotes_result.source_refs)
        unavailable.extend(quotes_result.unavailable_symbols)
        quotes = _parse_quotes(quotes_result)

    # ── Flash news ──────────────────────────────────────────────
    flash_count = 0
    if flash_result:
        refs.extend(flash_result.source_refs)
        unavailable.extend(flash_result.unavailable_symbols)
        flash_count = sum(
            1 for p in flash_result.points
            if p.symbol.startswith("NEWS_FLASH")
        )

    # ── Articles ────────────────────────────────────────────────
    article_count = 0
    if article_result:
        refs.extend(article_result.source_refs)
        unavailable.extend(article_result.unavailable_symbols)
        article_count = sum(
            1 for p in article_result.points
            if p.symbol.startswith("NEWS_ARTICLE:HEADLINE")
        )

    # ── Calendar ────────────────────────────────────────────────
    calendar_count = 0
    if calendar_result:
        refs.extend(calendar_result.source_refs)
        unavailable.extend(calendar_result.unavailable_symbols)
        calendar_count = sum(
            1 for p in calendar_result.points
            if p.symbol.startswith("NEWS_EVENT")
        )

    # ── Kline ───────────────────────────────────────────────────
    kline_codes: list[str] = []
    if kline_result:
        refs.extend(kline_result.source_refs)
        unavailable.extend(kline_result.unavailable_symbols)
        kline_codes = list({
            p.symbol.split(":")[1]
            for p in kline_result.points
            if p.symbol.startswith("KLINE:")
            and len(p.symbol.split(":")) >= 2
        })

    # ── Status ──────────────────────────────────────────────────
    has_quotes = len(quotes) > 0
    has_any = has_quotes or flash_count > 0 or article_count > 0 or calendar_count > 0
    status = "partial" if (has_any and unavailable) else (
        "available" if has_any else "unavailable"
    )

    return Jin10Snapshot(
        snapshot_id=snapshot_id,
        asset=asset,
        trade_date=trade_date,
        run_id=run_id,
        generated_at=generated_at,
        quotes=quotes,
        flash_count=flash_count,
        article_count=article_count,
        calendar_event_count=calendar_count,
        kline_codes=kline_codes,
        status=status,
        unavailable_modules=unavailable,
        source_refs=refs,
    )


def write_jin10_snapshot(
    snapshot: Jin10Snapshot,
    *,
    storage_root: Path,
) -> Path:
    """Write Jin10 snapshot JSON to the standard feature snapshot path."""
    out_dir = storage_root / "features" / "snapshots" / snapshot.asset / snapshot.trade_date / snapshot.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "jin10_snapshot.json"
    out_path.write_text(
        json.dumps(jin10_snapshot_to_dict(snapshot), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


# ── Serialization ─────────────────────────────────────────────────────────


def jin10_snapshot_to_dict(snapshot: Jin10Snapshot) -> dict[str, Any]:
    """Serialize Jin10Snapshot to JSON-safe dict."""
    return {
        "version": SNAPSHOT_VERSION,
        "snapshot_id": snapshot.snapshot_id,
        "asset": snapshot.asset,
        "trade_date": snapshot.trade_date,
        "run_id": snapshot.run_id,
        "generated_at": snapshot.generated_at,
        "quotes": {
            code: {
                "code": q.code,
                "name": q.name,
                "price": q.price,
                "open": q.open,
                "high": q.high,
                "low": q.low,
                "change": q.change,
                "change_pct": q.change_pct,
                "updated_at": q.updated_at,
            }
            for code, q in snapshot.quotes.items()
        },
        "counts": {
            "flash_news": snapshot.flash_count,
            "articles": snapshot.article_count,
            "calendar_events": snapshot.calendar_event_count,
        },
        "kline_codes": snapshot.kline_codes,
        "status": snapshot.status,
        "unavailable_modules": snapshot.unavailable_modules,
        "source_refs": snapshot.source_refs,
    }


# ── Parsers ───────────────────────────────────────────────────────────────


def _parse_quotes(result: CollectorResult) -> dict[str, QuoteEntry]:
    """Parse MacroPoints into QuoteEntry dict."""
    # Group points by code
    by_code: dict[str, dict[str, Any]] = {}
    for p in result.points:
        parts = p.symbol.split(":")
        if len(parts) < 2 or parts[0] != "QUOTE":
            continue
        code = parts[1]
        field = parts[2] if len(parts) > 2 else "PRICE"
        entry = by_code.setdefault(code, {})
        if field == "PRICE":
            entry["price"] = p.value
        elif field == "OPEN":
            entry["open"] = p.value
        elif field == "HIGH":
            entry["high"] = p.value
        elif field == "LOW":
            entry["low"] = p.value
        elif field == "CHANGE":
            entry["change"] = p.value
        elif field == "CHANGE_PCT":
            entry["change_pct"] = p.value

    quotes: dict[str, QuoteEntry] = {}
    for code, fields in by_code.items():
        quotes[code] = QuoteEntry(
            code=code,
            name=None,
            price=fields.get("price"),
            open=fields.get("open"),
            high=fields.get("high"),
            low=fields.get("low"),
            change=fields.get("change"),
            change_pct=fields.get("change_pct"),
            updated_at=None,
        )
    return quotes
