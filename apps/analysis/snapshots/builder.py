from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.output.artifacts import normalize_run_id

SNAPSHOT_VERSION = "1.0"


def build_analysis_snapshot(
    *,
    asset: str,
    trade_date: str,
    run_id: str,
    macro_snapshot: dict[str, Any] | None,
    options_snapshot: dict[str, Any] | None,
    source_refs: list[dict[str, Any]] | None = None,
    snapshot_time: str | None = None,
    collected_points: list[dict[str, Any]] | None = None,
    news_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one deterministic premarket analysis snapshot from existing artifacts.

    This function is intentionally pure: it does not read files, call networks,
    parse PDFs, or mutate inputs. Persistence is handled by
    ``write_analysis_snapshot``.
    """

    timestamp = snapshot_time or datetime.now(timezone.utc).isoformat()
    input_snapshot_ids: dict[str, Any] = {
        "macro": f"macro:{trade_date}:{run_id}",
        "options": f"options:{trade_date}:{run_id}",
    }

    options_detail = _extract_options_input_snapshot_ids(options_snapshot)
    if options_detail:
        input_snapshot_ids["options_detail"] = options_detail

    technical_section = _build_technical_section(collected_points or [], source_refs or [])
    positioning_section = _build_positioning_section(collected_points or [])
    market_odds_section = _build_market_odds_section(
        asset=asset, trade_date=trade_date, run_id=run_id,
        options_snapshot=options_snapshot,
    )

    return {
        "version": SNAPSHOT_VERSION,
        "snapshot_id": f"{asset}:{trade_date}:{run_id}",
        "asset": asset,
        "trade_date": trade_date,
        "snapshot_time": timestamp,
        "run_id": run_id,
        "input_snapshot_ids": input_snapshot_ids,
        "macro": _section(macro_snapshot),
        "options": _section(options_snapshot),
        "positioning": positioning_section,
        "news": _section(news_snapshot) if news_snapshot is not None else _build_news_section(collected_points or [], source_refs or []),
        "jin10": _build_jin10_section(collected_points or []),
        "technical": technical_section,
        "market_odds": market_odds_section,
        "source_refs": _merge_source_refs(source_refs, macro_snapshot),
    }


def write_analysis_snapshot(
    snapshot: dict[str, Any],
    *,
    storage_root: Path,
) -> Path:
    """Write ``premarket_snapshot.json`` under the versioned snapshot artifact path."""

    out_dir = analysis_snapshot_run_dir(
        storage_root,
        asset=str(snapshot["asset"]),
        trade_date=str(snapshot["trade_date"]),
        run_id=str(snapshot["run_id"]),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "premarket_snapshot.json"
    path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _safe_component(name: str, value: str) -> str:
    try:
        return normalize_run_id(value)
    except ValueError as exc:
        raise ValueError(str(exc).replace("run_id", name, 1)) from exc


def analysis_snapshot_run_dir(
    storage_root: Path,
    *,
    asset: str,
    trade_date: str,
    run_id: str,
) -> Path:
    """Return the artifact directory for a unified analysis snapshot."""

    safe_asset = _safe_component("asset", asset)
    safe_trade_date = _safe_component("trade_date", trade_date)
    safe_run_id = _safe_component("run_id", run_id)
    storage_dir = storage_root.resolve()
    artifact_dir = (storage_dir / "features" / "snapshots" / safe_asset / safe_trade_date / safe_run_id).resolve()
    if not artifact_dir.is_relative_to(storage_dir):
        raise ValueError("analysis snapshot path escapes storage root")
    return artifact_dir


def _section(data: dict[str, Any] | None) -> dict[str, Any]:
    if data is None:
        return {"status": "unavailable", "reason": "input_not_available"}
    return {"status": "available", "data": copy.deepcopy(data)}


def _extract_options_input_snapshot_ids(options_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not options_snapshot:
        return {}
    data_source = options_snapshot.get("data_source")
    if not isinstance(data_source, dict):
        return {}
    input_ids = data_source.get("input_snapshot_ids")
    if not isinstance(input_ids, dict):
        return {}
    return copy.deepcopy(input_ids)


def _merge_source_refs(
    source_refs: list[dict[str, Any]] | None,
    macro_snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    refs.extend(copy.deepcopy(source_refs or []))
    if macro_snapshot and isinstance(macro_snapshot.get("source_refs"), list):
        refs.extend(copy.deepcopy(macro_snapshot["source_refs"]))

    unique: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        key = json.dumps(ref, ensure_ascii=False, sort_keys=True)
        unique[key] = ref
    return [unique[key] for key in sorted(unique)]


# ---------------------------------------------------------------------------
# Technical & Positioning section builders
# ---------------------------------------------------------------------------


def _build_technical_section(
    collected_points: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the technical snapshot section from collected MacroPoints.

    Extracts XAUUSD close price from collected points and OHLC / SMA
    data from the corresponding source_ref notes (Yahoo Finance).
    """
    from apps.features.technical.snapshot import build_technical_snapshot

    # Find XAUUSD MacroPoint
    xau_points = [p for p in collected_points if p.get("symbol") == "XAUUSD"]
    if not xau_points:
        return {"status": "unavailable", "reason": "no_xauusd_collected_points"}

    xau = xau_points[0]
    try:
        close = float(xau["value"])
    except (TypeError, ValueError, KeyError):
        return {"status": "unavailable", "reason": "xauusd_close_missing_or_invalid"}

    # Find OHLC / SMA extras from source_refs notes (Yahoo Finance)
    open_: float | None = None
    high: float | None = None
    low: float | None = None
    ma20: float | None = None
    ma50: float | None = None
    closes: list[float] | None = None
    highs: list[float] | None = None
    lows: list[float] | None = None
    tech_source_refs: list[dict[str, str]] = []

    for ref in source_refs:
        if not isinstance(ref, dict):
            continue
        if ref.get("symbol") == "XAUUSD" and ref.get("source") == "yahoo_finance":
            notes = ref.get("notes")
            if isinstance(notes, dict):
                open_ = _try_float(notes.get("open"))
                high = _try_float(notes.get("high"))
                low = _try_float(notes.get("low"))
                ma20 = _try_float(notes.get("ma20"))
                ma50 = _try_float(notes.get("ma50"))
                closes = _try_float_list(notes.get("closes"))
                highs = _try_float_list(notes.get("highs"))
                lows = _try_float_list(notes.get("lows"))
            tech_source_refs.append({
                "source": str(ref.get("source", "")),
                "source_url": str(ref.get("source_url", "")),
                "raw_path": str(ref.get("raw_path", "")),
            })

    snapshot = build_technical_snapshot(
        close=close,
        open_=open_,
        high=high,
        low=low,
        ma20=ma20,
        ma50=ma50,
        closes=closes,
        highs=highs,
        lows=lows,
        source_refs=tech_source_refs or None,
    )
    return {"status": "available", "data": snapshot.to_dict()}


def _build_positioning_section(
    collected_points: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the positioning (CFTC COT) snapshot section from collected MacroPoints.

    Extracts COT_GOLD_* points and builds a PositioningSnapshot.
    """
    from apps.features.positioning.snapshot import build_positioning_snapshot

    cot_points = [
        p for p in collected_points
        if isinstance(p.get("symbol"), str) and p["symbol"].startswith("COT_GOLD")
    ]
    if not cot_points:
        return {"status": "unavailable", "reason": "no_cot_gold_collected_points"}

    # Collect unavailable COT symbols
    unavailable = [
        p.get("reason", "cot_unavailable")
        for p in collected_points
        if p.get("symbol") == "COT_GOLD"
        and isinstance(p, dict)
        and "reason" in p
    ]

    # Build source_refs from the COT points
    source_refs: list[dict[str, str]] = []
    for point in cot_points:
        source_refs.append({
            "source": str(point.get("source", "")),
            "source_url": str(point.get("source_url", "")),
            "raw_path": str(point.get("raw_path", "")),
        })

    snapshot = build_positioning_snapshot(
        points=cot_points,
        unavailable_symbols=unavailable or None,
        source_refs=source_refs or None,
    )
    return {"status": snapshot.status, "data": snapshot.to_dict()}


def _build_news_section(
    collected_points: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the news snapshot section from collected MacroPoints.

    Extracts NEWS_EVENT:* and NEWS_FLASH points and builds a NewsSnapshot.
    """
    from apps.features.news.snapshot import build_news_snapshot
    from datetime import datetime, timezone

    news_points = [
        p for p in collected_points
        if isinstance(p.get("symbol"), str) and (
            p["symbol"].startswith("NEWS_EVENT:") or p["symbol"] == "NEWS_FLASH"
        )
    ]
    if not news_points:
        return {"status": "unavailable", "reason": "no_news_collected_points"}

    # Filter news source_refs
    news_refs = [
        r for r in source_refs
        if isinstance(r, dict) and r.get("source") == "jin10_mcp"
    ]

    as_of = datetime.now(timezone.utc).date().isoformat()
    snapshot = build_news_snapshot(
        points=news_points,
        as_of=as_of,
        source_refs=news_refs or None,
    )
    return {"status": "available", "data": snapshot.to_dict()}


def _try_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _try_float_list(value: Any) -> list[float] | None:
    """Convert a list of values to a list of floats, returning None on failure."""
    if not isinstance(value, list):
        return None
    try:
        result = [float(v) for v in value]
        return result
    except (TypeError, ValueError):
        return None


# ── P4-07: Market odds section builder ─────────────────────────────────


def _build_market_odds_section(
    *,
    asset: str,
    trade_date: str,
    run_id: str,
    options_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the market_odds section for the unified analysis snapshot.

    P4-07 MVP: Derives CME-based price target probabilities from options
    wall data. Polymarket/Bloomberg placeholders are explicitly unavailable.

    Returns a section dict with status and data, suitable for the
    analysis snapshot JSON.
    """
    try:
        from apps.features.market_odds.snapshot import build_market_odds_snapshot

        odds = build_market_odds_snapshot(
            asset=asset,
            trade_date=trade_date,
            run_id=run_id,
            options_snapshot=options_snapshot,
        )
        return _market_odds_snapshot_to_dict(odds)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to build market odds section")
        return {
            "status": "unavailable",
            "reason": "Market odds builder failed — see logs for details.",
        }


def _market_odds_snapshot_to_dict(odds) -> dict[str, Any]:
    """Convert a MarketOddsSnapshot to a JSON-safe section dict."""
    return {
        "status": odds.status,
        "snapshot_id": odds.snapshot_id,
        "aggregate_signal": odds.aggregate_signal,
        "aggregate_confidence": odds.aggregate_confidence,
        "events": [
            {
                "event_id": e.event_id,
                "event_name": e.event_name,
                "event_type": e.event_type,
                "target_value": e.target_value,
                "target_unit": e.target_unit,
                "horizon_end": e.horizon_end,
                "final_probability": e.final_probability,
                "signal_label": e.signal_label,
                "confidence": e.confidence,
                "reliability_score": e.reliability_score,
                "divergence_score": e.divergence_score,
                "interpretation": e.interpretation,
                "probabilities": {
                    k: {
                        "source": v.source,
                        "probability": v.probability,
                        "confidence": v.confidence,
                    }
                    for k, v in e.probabilities.items()
                },
                "status": e.status,
            }
            for e in odds.events
        ],
        "source_refs": odds.source_refs,
    }


def _build_jin10_section(collected_points: list[dict[str, Any]]) -> dict[str, Any]:
    """Build Jin10 section from collected macro points.

    Extracts QUOTE:*, KLINE:*, NEWS_ARTICLE:*, NEWS_FLASH, and NEWS_EVENT
    entries from the collected points and provides a summary.
    """
    quotes: dict[str, dict[str, Any]] = {}
    flash_count = 0
    article_count = 0
    calendar_count = 0
    kline_codes: set[str] = set()

    for p in collected_points:
        symbol = str(p.get("symbol", ""))
        if symbol.startswith("QUOTE:"):
            parts = symbol.split(":")
            if len(parts) >= 2:
                code = parts[1]
                entry = quotes.setdefault(code, {})
                entry["code"] = code
                if len(parts) >= 3:
                    field = parts[2]
                    entry[field.lower()] = p.get("value")
                else:
                    entry["price"] = p.get("value")
        elif symbol.startswith("KLINE:"):
            parts = symbol.split(":")
            if len(parts) >= 2:
                kline_codes.add(parts[1])
            elif len(parts) >= 3:
                pass  # individual candle, counted via kline_codes
        elif symbol.startswith("NEWS_FLASH"):
            flash_count += 1
        elif symbol.startswith("NEWS_ARTICLE:HEADLINE"):
            article_count += 1
        elif symbol.startswith("NEWS_EVENT:"):
            calendar_count += 1

    has_any = bool(quotes) or flash_count > 0 or article_count > 0 or calendar_count > 0

    return {
        "status": "available" if has_any else "unavailable",
        "quotes": {
            code: {
                "code": q.get("code"),
                "price": q.get("price"),
                "open": q.get("open"),
                "high": q.get("high"),
                "low": q.get("low"),
                "change": q.get("change"),
                "change_pct": q.get("change_pct"),
            }
            for code, q in quotes.items()
        },
        "counts": {
            "flash_news": flash_count,
            "articles_headlines": article_count,
            "calendar_events": calendar_count,
        },
        "kline_codes": sorted(kline_codes),
    }
