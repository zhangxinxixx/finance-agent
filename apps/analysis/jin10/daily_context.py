from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


KEY_MACRO_SYMBOLS = (
    "US10Y",
    "REAL_10Y",
    "BREAKEVEN_10Y",
    "US02Y",
    "YIELD_SPREAD_2Y_3M",
    "DXY",
    "TGA",
    "RESERVES",
    "SOFR",
)


def build_daily_analysis_context(
    *,
    trade_date: str,
    storage_root: Path | str = "storage",
    asset: str = "XAUUSD",
    preferred_run_id: str | None = None,
) -> dict[str, Any]:
    """Build a compact, deterministic context for the canonical gold daily report.

    When invoked from an active pipeline, ``preferred_run_id`` prevents the
    current run's news artifacts from being replaced by an arbitrary
    lexicographically later sibling run from the same trade date.
    """

    root = Path(storage_root)
    anchor, anchor_path = _load_weekly_anchor(root, trade_date=trade_date, asset=asset)
    previous_analysis_report, previous_analysis_report_path = _load_previous_analysis_report(
        root,
        trade_date=trade_date,
        asset=asset,
    )
    premarket, premarket_path = _load_latest_json(
        root / "features" / "snapshots" / asset,
        trade_date=trade_date,
        filename="premarket_snapshot.json",
        preferred_run_id=preferred_run_id,
    )
    news, news_path = _load_latest_json(
        root / "features" / "news",
        trade_date=trade_date,
        filename="daily_market_brief.json",
        preferred_run_id=preferred_run_id,
    )
    overview, overview_path = _load_latest_json(
        root / "analysis" / "gold_mainlines",
        trade_date=trade_date,
        filename="gold_macro_overview.json",
        preferred_run_id=preferred_run_id,
    )
    oil, oil_path = _load_latest_json(
        root / "features" / "oil_context",
        trade_date=trade_date,
        filename="oil_context.json",
    )
    oil_report, oil_report_path = _load_latest_oil_report(root, trade_date=trade_date)

    latest_market = _compact_market(premarket)
    latest_news = _compact_news(news)
    gold_mainline = _compact_gold_mainline(overview)
    oil_report_summary = _compact_oil_report(oil_report)
    oil_context = _compact_oil(oil) or oil_report_summary

    anchor_date = str(anchor.get("context_as_of") or anchor.get("trade_date") or "")[:10]
    previous_analysis_date = str(previous_analysis_report.get("trade_date") or "")[:10]
    weekly_freshness = _freshness(anchor_date, trade_date, max_age_days=8)
    previous_analysis_freshness = _freshness(previous_analysis_date, trade_date, max_age_days=4)
    previous_is_current = previous_analysis_freshness["status"] == "current"
    weekly_is_current = weekly_freshness["status"] == "current"
    use_weekly = (
        _is_monday(trade_date)
        or not previous_analysis_report
        or (not previous_is_current and weekly_is_current)
    )
    baseline = anchor if use_weekly else previous_analysis_report
    baseline_kind = (
        "weekly_anchor"
        if _is_monday(trade_date)
        else "weekly_fallback"
        if not previous_analysis_report or not previous_is_current
        else "previous_analysis_report"
    )
    baseline_date = str(baseline.get("context_as_of") or baseline.get("trade_date") or "")[:10]
    market_date = str((premarket or {}).get("trade_date") or "")[:10]
    news_date = str((news or {}).get("retrieved_date") or latest_news.get("as_of") or "")[:10]
    overview_date = str((overview or {}).get("retrieved_date") or (overview or {}).get("as_of") or "")[:10]
    oil_date = str(
        (oil or {}).get("trade_date")
        or (oil or {}).get("as_of")
        or oil_report_summary.get("trade_date")
        or ""
    )[:10]
    freshness = {
        "weekly_anchor": weekly_freshness,
        "previous_analysis_report": previous_analysis_freshness,
        "analysis_baseline": _freshness(baseline_date, trade_date, max_age_days=8 if use_weekly else 4),
        "market": _freshness(market_date, trade_date, max_age_days=1),
        "news": _freshness(news_date, trade_date, max_age_days=1),
        "gold_mainline": _freshness(overview_date, trade_date, max_age_days=1),
        "oil": _freshness(oil_date, trade_date, max_age_days=1),
    }
    required_ready = all(
        freshness[key]["status"] == "current"
        for key in ("analysis_baseline", "market", "news", "gold_mainline")
    )
    continuity_status = (
        "weekly_reset"
        if baseline_kind == "weekly_anchor"
        else "weekly_fallback"
        if baseline_kind == "weekly_fallback"
        else "serial"
    )
    warnings: list[str] = []
    if baseline_kind == "weekly_fallback":
        reason = "missing" if not previous_analysis_report else "stale"
        warnings.append(f"previous_analysis_report_{reason}; using current weekly anchor")

    paths = {
        "weekly_anchor": _relative_path(anchor_path, root),
        "previous_analysis_report": _relative_path(previous_analysis_report_path, root),
        "premarket_snapshot": _relative_path(premarket_path, root),
        "daily_market_brief": _relative_path(news_path, root),
        "gold_macro_overview": _relative_path(overview_path, root),
        "oil_context": _relative_path(oil_path, root),
        "oil_report_summary": _relative_path(oil_report_path, root),
    }
    input_snapshot_ids = {key: value for key, value in paths.items() if value}
    source_refs = _dedupe_refs(
        [
            *list(baseline.get("source_refs") or []),
            *([] if baseline is anchor else list(anchor.get("source_refs") or [])),
            *list((premarket or {}).get("source_refs") or []),
            *list(latest_news.get("source_refs") or []),
            *list(gold_mainline.get("source_refs") or []),
            *list(oil_context.get("source_refs") or []),
            *list(oil_report_summary.get("source_refs") or []),
        ]
    )
    return {
        "schema_version": "daily-analysis-context-v1",
        "asset": asset,
        "trade_date": trade_date,
        "status": "ready" if required_ready else "degraded",
        "baseline_kind": baseline_kind,
        "continuity_status": continuity_status,
        "warnings": warnings,
        "analysis_baseline": baseline,
        "weekly_anchor": anchor,
        "previous_analysis_report": previous_analysis_report,
        "latest_market": latest_market,
        "latest_news": latest_news,
        "gold_mainline": gold_mainline,
        "oil_context": oil_context,
        "oil_report_summary": oil_report_summary,
        "freshness": freshness,
        "input_snapshot_ids": input_snapshot_ids,
        "source_refs": source_refs,
    }


def compact_context_metadata(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {}
    anchor = context.get("analysis_baseline") or context.get("weekly_anchor") or {}
    return {
        "status": context.get("status"),
        "baseline_kind": context.get("baseline_kind") or "weekly_anchor",
        "continuity_status": context.get("continuity_status"),
        "warnings": context.get("warnings") or [],
        "analysis_baseline": {
            key: anchor.get(key)
            for key in (
                "source_kind",
                "trade_date",
                "context_as_of",
                "article_id",
                "report_id",
                "run_id",
                "title",
                "quality_status",
                "publication_status",
                "publish_allowed",
            )
            if anchor.get(key) is not None
        },
        "freshness": context.get("freshness") or {},
        "input_snapshot_ids": context.get("input_snapshot_ids") or {},
    }


def compact_context_for_prompt(context: dict[str, Any] | None) -> dict[str, Any]:
    """Return the single effective baseline plus prompt-relevant evidence.

    The persisted daily context intentionally keeps the weekly anchor and the
    previous composite report for audit/replay.  The prompt context must not
    replay both of those historical artifacts after ``analysis_baseline`` has
    already selected one of them.
    """

    if not context:
        return {}
    baseline = context.get("analysis_baseline") or context.get("weekly_anchor") or {}
    return {
        "schema_version": "daily-analysis-prompt-context-v2",
        "status": context.get("status"),
        "baseline_kind": context.get("baseline_kind") or "weekly_anchor",
        "continuity_status": context.get("continuity_status"),
        "warnings": context.get("warnings") or [],
        "analysis_baseline": _without_transport_source_refs(baseline),
        "latest_market": _without_transport_source_refs(context.get("latest_market") or {}),
        "latest_news": _without_transport_source_refs(context.get("latest_news") or {}),
        "gold_mainline": _without_transport_source_refs(context.get("gold_mainline") or {}),
        "oil_context": _without_transport_source_refs(context.get("oil_context") or {}),
        "oil_report_summary": _without_transport_source_refs(context.get("oil_report_summary") or {}),
        "freshness": _without_transport_source_refs(context.get("freshness") or {}),
        "input_snapshot_ids": _without_transport_source_refs(context.get("input_snapshot_ids") or {}),
    }


def _without_transport_source_refs(value: Any) -> Any:
    """Copy JSON-compatible prompt data while removing bulky lineage lists.

    Canonical lineage remains available through ``input_snapshot_ids`` and the
    persisted context's top-level ``source_refs``.  Nested source lists are
    transport detail and often contain repeated URLs or raw paths.
    """

    if isinstance(value, dict):
        return {key: _without_transport_source_refs(item) for key, item in value.items() if key != "source_refs"}
    if isinstance(value, list):
        return [_without_transport_source_refs(item) for item in value]
    return value


def _load_weekly_anchor(root: Path, *, trade_date: str, asset: str) -> tuple[dict[str, Any], Path | None]:
    revision, revision_path = _load_latest_json(
        root / "outputs" / "weekly_context_revision" / asset,
        trade_date=trade_date,
        filename="report_structured.json",
    )
    if revision:
        anchor_meta = revision.get("anchor") or {}
        claims = [
            {
                key: item.get(key)
                for key in (
                    "claim_id",
                    "original_claim",
                    "action",
                    "reason",
                    "confidence_before",
                    "confidence_after",
                )
            }
            for item in list(revision.get("claim_revisions") or [])[:8]
            if isinstance(item, dict)
        ]
        return {
            "source_kind": "weekly_context_revision",
            "trade_date": revision.get("trade_date"),
            "context_as_of": revision.get("context_as_of"),
            "article_id": anchor_meta.get("article_id") or _article_id_from_run_id(revision.get("run_id")),
            "title": anchor_meta.get("title"),
            "quality_status": revision.get("quality_status"),
            "publication_status": revision.get("publication_status"),
            "publish_allowed": revision.get("publish_allowed"),
            "executive_summary": revision.get("executive_summary"),
            "claim_revisions": claims,
            "confirmation_matrix": revision.get("confirmation_matrix") or {},
            "watch_items": list(revision.get("watch_items") or [])[:8],
            "source_refs": _dedupe_refs(list(revision.get("source_refs") or []), limit=12),
        }, revision_path

    base = root / "outputs" / "jin10"
    for path in _candidate_paths(base, trade_date=trade_date, filename="agent_analysis_report.json"):
        payload = _read_json(path)
        if not payload or not _is_weekly_report(payload):
            continue
        identity = payload.get("report_identity") or {}
        return {
            "source_kind": "jin10_weekly_analysis",
            "trade_date": payload.get("trade_date"),
            "context_as_of": payload.get("trade_date"),
            "article_id": payload.get("article_id") or payload.get("run_id"),
            "title": payload.get("title"),
            "quality_status": (payload.get("quality_audit") or {}).get("status"),
            "publication_status": "analysis_baseline",
            "publish_allowed": None,
            "executive_summary": payload.get("one_line_conclusion") or payload.get("final_summary"),
            "market_stage": payload.get("market_stage") or {},
            "key_levels": list(payload.get("key_levels") or [])[:10],
            "scenario_paths": list(payload.get("scenario_paths") or [])[:3],
            "report_type": identity.get("report_type") or "weekly",
            "source_refs": _dedupe_refs(list(payload.get("source_refs") or []), limit=12),
        }, path
    return {}, None


def _load_previous_analysis_report(
    root: Path,
    *,
    trade_date: str,
    asset: str,
) -> tuple[dict[str, Any], Path | None]:
    """Load the previous day's latest composite analysis, not the raw Jin10 daily.

    The composite final report is the durable serial analysis memory. Jin10's
    current-day article remains incremental evidence and is never promoted to
    the previous-day baseline by this loader.
    """

    base = root / "outputs" / "final_report" / asset
    for path in _candidate_paths(base, trade_date=trade_date, filename="agent_analysis_report.json"):
        path_date = _path_date(path)
        if not path_date or path_date >= trade_date:
            continue
        payload = _read_json(path)
        if not payload:
            continue
        return _compact_final_analysis_report(payload), path
    for path in _candidate_paths(base, trade_date=trade_date, filename="structured_report.json"):
        path_date = _path_date(path)
        if not path_date or path_date >= trade_date:
            continue
        payload = _read_json(path)
        if not payload:
            continue
        return _compact_final_analysis_report(payload), path
    return {}, None


def _compact_final_analysis_report(payload: dict[str, Any]) -> dict[str, Any]:
    version = payload.get("version") or {}
    sections = {
        str(item.get("section_id")): item
        for item in list(payload.get("sections") or [])
        if isinstance(item, dict) and item.get("section_id")
    }
    summary = sections.get("one_line_summary") or {}
    phase = sections.get("market_phase") or {}
    trade_date = version.get("trade_date") or payload.get("trade_date")
    return {
        "source_kind": "final_analysis_report",
        "trade_date": trade_date,
        "context_as_of": trade_date,
        "report_id": version.get("report_id"),
        "run_id": version.get("run_id"),
        "title": "前一日最新综合分析报告",
        "quality_status": version.get("status") or "generated",
        "publication_status": version.get("status") or "generated",
        "publish_allowed": version.get("is_final"),
        "executive_summary": summary.get("body"),
        "market_stage": {"label": phase.get("body"), "section_id": phase.get("section_id")},
        "analysis_sections": [
            {
                "section_id": item.get("section_id"),
                "title": item.get("title"),
                "body": str(item.get("body") or "")[:1600],
                "status": item.get("status"),
            }
            for item in list(payload.get("sections") or [])[:8]
            if isinstance(item, dict)
        ],
        "source_refs": _dedupe_refs(list(payload.get("source_refs") or []), limit=12),
    }


def _compact_market(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    technical = ((payload.get("technical") or {}).get("data") or {})
    macro = ((payload.get("macro") or {}).get("data") or {})
    options = ((payload.get("options") or {}).get("data") or {})
    positioning = ((payload.get("positioning") or {}).get("data") or {})
    indicators = macro.get("indicators") or {}
    aggregate = ((options.get("gex") or {}).get("netgex_aggregate") or {})
    gamma_zero = ((aggregate.get("gamma_zero") or {}).get("price"))
    sr = options.get("support_resistance") or {}
    data_source = options.get("data_source") or {}
    walls = options.get("walls") or {}
    block_walls = list(walls.get("block_pnt_walls") or [])
    primary_wall = max(block_walls, key=lambda item: float(item.get("gex") or 0), default={})
    return {
        "trade_date": payload.get("trade_date"),
        "snapshot_time": payload.get("snapshot_time"),
        "technical": {
            key: technical.get(key)
            for key in ("price", "trend", "volatility", "atr14", "ma20", "ma50", "rsi14")
        },
        "macro": {
            "as_of": macro.get("as_of"),
            "indicators": {
                symbol: {
                    key: indicators[symbol].get(key)
                    for key in ("value", "unit", "date", "daily_change", "weekly_change", "direction_note")
                }
                for symbol in KEY_MACRO_SYMBOLS
                if isinstance(indicators.get(symbol), dict)
            },
            "unavailable_symbols": list(macro.get("unavailable_symbols") or []),
        },
        "options": {
            "trade_date": options.get("trade_date"),
            "report_status": data_source.get("status"),
            "report_p0": _first_f_value(options),
            "primary_wall": primary_wall.get("strike"),
            "gamma_zero": gamma_zero,
            "support": list(sr.get("support") or [])[:5],
            "resistance": list(sr.get("resistance") or [])[:5],
            "roll_signals": list(options.get("roll_signals") or [])[:5],
            "data_quality": options.get("data_quality") or {},
        },
        "positioning": {
            key: positioning.get(key)
            for key in (
                "as_of",
                "noncomm_net",
                "noncomm_net_prev",
                "noncomm_direction",
                "commercial_net",
                "commercial_net_prev",
                "commercial_direction",
                "total_oi",
                "extreme_reading",
                "status",
            )
        },
    }


def _compact_news(payload: dict[str, Any]) -> dict[str, Any]:
    brief = payload.get("daily_market_brief") if isinstance(payload.get("daily_market_brief"), dict) else payload
    if not brief:
        return {}
    events: list[dict[str, Any]] = []
    source_refs: list[dict[str, Any]] = []
    for bucket in ("confirmed_events", "candidate_events", "unconfirmed_events"):
        for item in list(brief.get(bucket) or [])[:8]:
            if not isinstance(item, dict):
                continue
            events.append(
                {
                    key: item.get(key)
                    for key in (
                        "event_id",
                        "event_type",
                        "event_time",
                        "what_happened",
                        "verification_status",
                        "need_verification",
                        "source_count",
                        "impact_path",
                        "gold_impact",
                        "yield_impact",
                        "oil_impact",
                        "risk_level",
                        "pricing_status",
                        "invalidation_condition",
                        "confidence",
                    )
                }
            )
            source_refs.extend(item.get("source_refs") or [])
    return {
        "as_of": brief.get("as_of") or payload.get("retrieved_date"),
        "market_mainline": brief.get("market_mainline") or {},
        "events": events[:12],
        "asset_reactions": list(brief.get("asset_reactions") or [])[:8],
        "warnings": list(brief.get("warnings") or [])[:8],
        "source_refs": _dedupe_refs(source_refs),
    }


def _compact_gold_mainline(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    conflict = payload.get("driver_conflict") or {}
    chain = payload.get("war_oil_rate_chain") or {}
    compact_chain = {
        key: chain.get(key)
        for key in (
            "path_id",
            "label",
            "status",
            "dominant_driver",
            "net_effect",
            "conclusion_code",
            "conclusion_label",
            "summary",
        )
        if chain.get(key) is not None
    }
    compact_chain["steps"] = [
        {key: item.get(key) for key in ("id", "label", "status")}
        for item in list(chain.get("steps") or [])
        if isinstance(item, dict)
    ]
    return {
        "as_of": payload.get("as_of"),
        "status": payload.get("status"),
        "phase": payload.get("phase"),
        "one_line_conclusion": payload.get("one_line_conclusion"),
        "dominant_mainline": payload.get("dominant_mainline"),
        "driver_conflict": {
            key: conflict.get(key)
            for key in ("dominant_driver", "net_effect", "explanation", "bullish_drivers", "bearish_drivers")
        },
        "war_oil_rate_chain": compact_chain,
        "review_status": payload.get("review_status"),
        "warnings": list(payload.get("warnings") or [])[:8],
        "source_refs": _dedupe_refs(list(payload.get("source_refs") or []), limit=12),
    }


def _compact_oil(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        key: payload.get(key)
        for key in (
            "as_of",
            "trade_date",
            "status",
            "brent",
            "wti",
            "oil_price_trend",
            "energy_inflation_risk",
            "summary",
            "source_refs",
        )
        if payload.get(key) is not None
    }


def _load_latest_oil_report(root: Path, *, trade_date: str) -> tuple[dict[str, Any], Path | None]:
    base = root / "outputs" / "jin10"
    for path in _candidate_paths(base, trade_date=trade_date, filename="agent_analysis_report.json"):
        payload = _read_json(path)
        if payload and _is_oil_report(payload):
            return payload, path
    return {}, None


def _compact_oil_report(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    return {
        "source_kind": "jin10_oil_analysis",
        "trade_date": payload.get("trade_date"),
        "as_of": payload.get("trade_date"),
        "article_id": payload.get("article_id") or payload.get("run_id"),
        "title": payload.get("title"),
        "status": (payload.get("quality_audit") or {}).get("status") or "unknown",
        "verification_status": "report_analysis",
        "one_line_conclusion": payload.get("one_line_conclusion"),
        "market_stage": payload.get("market_stage") or {},
        "key_levels": list(payload.get("key_levels") or [])[:10],
        "risk_points": list(payload.get("risk_points") or [])[:8],
        "final_summary": payload.get("final_summary"),
        "source_refs": _dedupe_refs(list(payload.get("source_refs") or []), limit=12),
    }


def _load_latest_json(
    base: Path,
    *,
    trade_date: str,
    filename: str,
    preferred_run_id: str | None = None,
) -> tuple[dict[str, Any], Path | None]:
    if preferred_run_id:
        preferred = base / trade_date / preferred_run_id / filename
        payload = _read_json(preferred)
        if payload:
            return payload, preferred
    for path in _candidate_paths(base, trade_date=trade_date, filename=filename):
        payload = _read_json(path)
        if payload:
            return payload, path
    return {}, None


def _candidate_paths(base: Path, *, trade_date: str, filename: str) -> list[Path]:
    if not base.exists():
        return []
    paths: list[Path] = []
    for date_dir in base.iterdir():
        if not date_dir.is_dir() or date_dir.name > trade_date:
            continue
        paths.extend(date_dir.glob(f"*/{filename}"))
        direct = date_dir / filename
        if direct.is_file():
            paths.append(direct)
    return sorted(paths, key=lambda path: (path.parents[1].name, path.parent.name), reverse=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_weekly_report(payload: dict[str, Any]) -> bool:
    identity = payload.get("report_identity") or {}
    values = {
        str(identity.get("report_type") or "").lower(),
        str(payload.get("source_report_family") or "").lower(),
        str((payload.get("generated_from") or {}).get("raw_report_family") or "").lower(),
    }
    return "weekly" in values or "jin10_weekly_visual" in values


def _is_daily_report(payload: dict[str, Any]) -> bool:
    identity = payload.get("report_identity") or {}
    values = {
        str(identity.get("report_type") or "").lower(),
        str(payload.get("source_report_family") or "").lower(),
        str((payload.get("generated_from") or {}).get("raw_report_family") or "").lower(),
    }
    return "daily" in values or "jin10_daily_visual" in values


def _is_oil_report(payload: dict[str, Any]) -> bool:
    identity = payload.get("report_identity") or (payload.get("generated_from") or {}).get("report_identity") or {}
    values = {
        str(identity.get("report_type") or "").lower(),
        str(identity.get("report_family") or "").lower(),
        str(payload.get("source_report_family") or "").lower(),
    }
    return "oil" in values or "jin10_oil_report" in values


def _is_monday(trade_date: str) -> bool:
    try:
        return date.fromisoformat(trade_date[:10]).weekday() == 0
    except ValueError:
        return False


def _path_date(path: Path) -> str:
    for parent in path.parents:
        if len(parent.name) == 10 and parent.name[4] == "-" and parent.name[7] == "-":
            return parent.name
    return ""


def _freshness(as_of: str, trade_date: str, *, max_age_days: int) -> dict[str, Any]:
    if not as_of:
        return {"status": "missing", "as_of": None, "age_days": None}
    try:
        age_days = (date.fromisoformat(trade_date) - date.fromisoformat(as_of)).days
    except ValueError:
        return {"status": "invalid", "as_of": as_of, "age_days": None}
    status = "current" if 0 <= age_days <= max_age_days else "stale"
    return {"status": status, "as_of": as_of, "age_days": age_days}


def _first_f_value(options: dict[str, Any]) -> Any:
    by_expiry = ((options.get("gex") or {}).get("by_expiry") or {})
    for item in by_expiry.values():
        if isinstance(item, dict):
            value = ((item.get("summary") or {}).get("f_value"))
            if value is not None:
                return value
    return None


def _article_id_from_run_id(value: Any) -> str | None:
    text = str(value or "")
    return text.split("-", 1)[0] or None


def _relative_path(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe_refs(refs: list[Any], *, limit: int = 24) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in refs:
        if not isinstance(item, dict):
            continue
        compact = {
            key: item.get(key)
            for key in ("source_ref", "source", "source_type", "title", "domain", "raw_path", "parsed_path", "path", "published_at", "article_id")
            if item.get(key) is not None
        }
        if compact.get("title"):
            compact["title"] = str(compact["title"])[:200]
        marker = str(compact.get("source_ref") or compact.get("path") or compact.get("raw_path") or compact)
        if marker in seen:
            continue
        seen.add(marker)
        output.append(compact)
        if len(output) >= limit:
            break
    return output
