from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DailyMarketBrief:
    as_of: str
    market_mainline: dict[str, Any]
    next_7d_calendar: list[dict[str, Any]]
    confirmed_events: list[dict[str, Any]]
    candidate_events: list[dict[str, Any]]
    unconfirmed_risks: list[dict[str, Any]]
    asset_reactions: list[dict[str, Any]]
    report_inputs: dict[str, Any]
    data_quality: dict[str, Any]
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_daily_market_brief(
    *,
    event_bundle: Any,
    impact_assessments: list[Any] | None,
    market_reactions: list[Any] | None,
    as_of: str,
    source_refs: list[dict[str, Any]] | None = None,
    report_input_artifacts: list[dict[str, Any]] | None = None,
) -> DailyMarketBrief:
    events = _event_dicts(event_bundle)
    assessment_by_event_id = {
        str(assessment.get("event_id") or ""): assessment
        for assessment in (_dict(item) for item in (impact_assessments or []))
    }
    reaction_by_event_id = {
        str(reaction.get("event_id") or ""): reaction
        for reaction in (_dict(item) for item in (market_reactions or []))
    }
    bundle_refs = _bundle_source_refs(event_bundle)
    report_input_refs = _report_input_source_refs(report_input_artifacts or [])
    merged_refs = _dedupe_refs([
        *bundle_refs,
        *(source_refs or []),
        *report_input_refs,
        *[ref for event in events for ref in event.get("source_refs", []) if isinstance(ref, dict)],
    ])

    next_7d_calendar = _next_7d_calendar(events, assessment_by_event_id=assessment_by_event_id, as_of=as_of)
    confirmed_events = [
        _brief_event(event, assessment_by_event_id.get(str(event.get("event_id") or "")), reaction_by_event_id.get(str(event.get("event_id") or "")))
        for event in events
        if event.get("verification_status") == "official_confirmed"
    ]
    candidate_events = [
        _brief_event(event, assessment_by_event_id.get(str(event.get("event_id") or "")), reaction_by_event_id.get(str(event.get("event_id") or "")))
        for event in events
        if event.get("verification_status") != "official_confirmed"
    ]
    unconfirmed_risks = [
        event
        for event in candidate_events
        if event.get("risk_level") in {"high", "medium"} or float(event.get("confidence") or 0.0) >= 0.60
    ]
    asset_reactions = _asset_reactions(reaction_by_event_id)
    news_highlights = _news_highlights(confirmed_events=confirmed_events, unconfirmed_risks=unconfirmed_risks, candidate_events=candidate_events)
    highlighted_event_ids = _event_ids(news_highlights)
    watchlist = _watchlist(
        candidate_events=candidate_events,
        next_7d_calendar=next_7d_calendar,
        exclude_event_ids=highlighted_event_ids,
    )
    reported_event_ids = highlighted_event_ids | _event_ids(watchlist)
    risk_points = _risk_points(
        unconfirmed_risks=[event for event in unconfirmed_risks if str(event.get("event_id") or "") not in reported_event_ids],
        watchlist=watchlist,
    )
    warnings = _warnings(events=events, next_7d_calendar=next_7d_calendar)

    report_inputs = {
        "news_highlights": news_highlights,
        "watchlist": watchlist,
        "risk_points": risk_points,
        **_supplemental_report_inputs(report_input_artifacts or []),
    }
    return DailyMarketBrief(
        as_of=as_of,
        market_mainline=_market_mainline(news_highlights=news_highlights, unconfirmed_risks=unconfirmed_risks, confirmed_events=confirmed_events),
        next_7d_calendar=next_7d_calendar,
        confirmed_events=confirmed_events,
        candidate_events=candidate_events,
        unconfirmed_risks=unconfirmed_risks,
        asset_reactions=asset_reactions,
        report_inputs=report_inputs,
        data_quality={
            "event_candidate_count": len(events),
            "confirmed_event_count": len(confirmed_events),
            "candidate_event_count": len(candidate_events),
            "unconfirmed_risk_count": len(unconfirmed_risks),
            "asset_reaction_count": len(asset_reactions),
            "positioning_input_count": len(report_inputs.get("positioning") or []),
            "technical_level_input_count": len(report_inputs.get("technical_levels") or []),
            "market_observation_input_count": len(report_inputs.get("market_observations") or []),
            "source_ref_count": len(merged_refs),
        },
        source_refs=merged_refs,
        warnings=warnings,
    )


def archive_daily_market_brief(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    brief: DailyMarketBrief,
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "daily_market_brief.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "retrieved_date": retrieved_date,
                "run_id": run_id,
                "daily_market_brief": brief.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target.relative_to(storage_root).as_posix()


def _event_dicts(event_bundle: Any) -> list[dict[str, Any]]:
    if isinstance(event_bundle, dict):
        raw_events = event_bundle.get("event_candidates") or event_bundle.get("events") or []
    elif hasattr(event_bundle, "event_candidates"):
        raw_events = getattr(event_bundle, "event_candidates")
    else:
        raw_events = event_bundle or []
    return [_dict(event) for event in raw_events]


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return dict(value)


def _bundle_source_refs(event_bundle: Any) -> list[dict[str, Any]]:
    if isinstance(event_bundle, dict):
        refs = event_bundle.get("source_refs") or []
    else:
        refs = getattr(event_bundle, "source_refs", []) or []
    return [dict(ref) for ref in refs if isinstance(ref, dict)]


def _supplemental_report_inputs(artifacts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "positioning": [],
        "technical_levels": [],
        "market_observations": [],
    }
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        source_key = str(artifact.get("source_key") or "").strip()
        items = [dict(item) for item in artifact.get("items") or artifact.get("inputs") or [] if isinstance(item, dict)]
        if not items:
            continue
        if "positioning" in source_key:
            result["positioning"].extend(items)
        elif "technical" in source_key or "level" in source_key:
            result["technical_levels"].extend(items)
        elif "market_observation" in source_key or "market_observ" in source_key:
            result["market_observations"].extend(items)
    return {key: value for key, value in result.items() if value}


def _report_input_source_refs(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        refs.extend(dict(ref) for ref in artifact.get("source_refs") or [] if isinstance(ref, dict))
        for item in artifact.get("items") or artifact.get("inputs") or []:
            if isinstance(item, dict):
                refs.extend(dict(ref) for ref in item.get("source_refs") or [] if isinstance(ref, dict))
    return refs


def _next_7d_calendar(
    events: list[dict[str, Any]],
    *,
    assessment_by_event_id: dict[str, dict[str, Any]],
    as_of: str,
) -> list[dict[str, Any]]:
    start = _parse_time(as_of)
    if start is None:
        return []
    end = start + timedelta(days=7)
    result: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_status") != "scheduled":
            continue
        if event.get("verification_status") != "official_confirmed":
            continue
        event_time = _parse_time(event.get("event_time"))
        if event_time is None or event_time < start or event_time > end:
            continue
        assessment = assessment_by_event_id.get(str(event.get("event_id") or "")) or {}
        result.append(
            {
                "event_id": event.get("event_id"),
                "event_name": _event_name(event),
                "event_time": event.get("event_time"),
                "source": _source_label(event),
                "importance": _importance(event),
                "related_assets": event.get("asset_tags", []),
                "expected_impact_path": assessment.get("impact_path") or "unknown",
                "verification_status": event.get("verification_status"),
            }
        )
    return sorted(result, key=lambda item: str(item.get("event_time") or ""))


def _brief_event(
    event: dict[str, Any],
    assessment: dict[str, Any] | None,
    reaction: dict[str, Any] | None,
) -> dict[str, Any]:
    assessment = assessment or {}
    reaction = reaction or {}
    return {
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "event_time": event.get("event_time"),
        "what_happened": _event_name(event),
        "who_said": _source_label(event),
        "verification_status": event.get("verification_status"),
        "need_verification": bool(event.get("need_verification")),
        "source_count": event.get("source_count"),
        "source_status": _source_status(event),
        "affected_assets": event.get("asset_tags", []),
        "impact_path": assessment.get("impact_path") or "unknown",
        "gold_impact": assessment.get("gold_impact") or "unknown",
        "silver_impact": assessment.get("silver_impact") or "unknown",
        "dollar_impact": assessment.get("dollar_impact") or "unknown",
        "yield_impact": assessment.get("yield_impact") or "unknown",
        "oil_impact": assessment.get("oil_impact") or "unknown",
        "risk_level": assessment.get("risk_level") or "low",
        "pricing_status": reaction.get("pricing_status") or assessment.get("pricing_status") or "unknown",
        "market_validation": _market_validation(reaction),
        "market_snapshot": _market_snapshot(reaction),
        "invalidation_condition": assessment.get("invalidation_condition") or "等待多源确认和行情反应",
        "confidence": event.get("confidence"),
        "source_refs": event.get("source_refs", []),
    }


def _asset_reactions(reaction_by_event_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event_id, reaction in reaction_by_event_id.items():
        for window, assets in (reaction.get("windows") or {}).items():
            if not isinstance(assets, dict):
                continue
            for asset, movement in assets.items():
                if not isinstance(movement, dict):
                    continue
                result.append(
                    {
                        "event_id": event_id,
                        "window": window,
                        "asset": asset,
                        "direction": movement.get("direction"),
                        "pct_change": movement.get("pct_change"),
                        "change_bp": movement.get("change_bp"),
                        "threshold_hit": movement.get("threshold_hit"),
                        "expected_direction": movement.get("expected_direction"),
                        "pricing_status": reaction.get("pricing_status") or "unknown",
                    }
                )
    return result


def _news_highlights(
    *,
    confirmed_events: list[dict[str, Any]],
    unconfirmed_risks: list[dict[str, Any]],
    candidate_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = [*confirmed_events, *unconfirmed_risks]
    if not selected:
        selected = candidate_events[:3]
    return selected[:5]


def _watchlist(
    *,
    candidate_events: list[dict[str, Any]],
    next_7d_calendar: list[dict[str, Any]],
    exclude_event_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded = exclude_event_ids or set()
    calendar_items = [
        {
            "event_id": item.get("event_id"),
            "event_type": "scheduled_calendar",
            "what_happened": item.get("event_name"),
            "event_time": item.get("event_time"),
            "impact_path": item.get("expected_impact_path"),
            "verification_status": item.get("verification_status"),
            "need_verification": False,
        }
        for item in next_7d_calendar
        if str(item.get("event_id") or "") not in excluded
    ]
    candidate_items = [
        event
        for event in candidate_events
        if str(event.get("event_id") or "") not in excluded
    ]
    return [*candidate_items[:10], *calendar_items[:10]]


def _risk_points(*, unconfirmed_risks: list[dict[str, Any]], watchlist: list[dict[str, Any]]) -> list[str]:
    points = _dedupe_texts([
        f"{event.get('what_happened')} | {event.get('verification_status')} | {event.get('impact_path')}"
        for event in unconfirmed_risks[:5]
    ])
    if not points and watchlist:
        points.append("当前主要事件仍在观察清单中，等待多源确认或行情验证。")
    return points


def _event_ids(events: list[dict[str, Any]]) -> set[str]:
    return {
        str(event.get("event_id") or "")
        for event in events
        if str(event.get("event_id") or "")
    }


def _dedupe_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split())
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _market_mainline(
    *,
    news_highlights: list[dict[str, Any]],
    unconfirmed_risks: list[dict[str, Any]],
    confirmed_events: list[dict[str, Any]],
) -> dict[str, Any]:
    primary = (unconfirmed_risks or confirmed_events or news_highlights or [{}])[0]
    if not primary:
        return {
            "status": "unavailable",
            "summary": "暂无可用新闻事件主线。",
            "primary_event_id": None,
            "risk_level": "low",
        }
    return {
        "status": "available",
        "summary": primary.get("what_happened") or "事件主线待确认",
        "primary_event_id": primary.get("event_id"),
        "risk_level": primary.get("risk_level") or "low",
        "verification_status": primary.get("verification_status"),
        "pricing_status": primary.get("pricing_status"),
    }


def _warnings(*, events: list[dict[str, Any]], next_7d_calendar: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    if not events:
        warnings.append("No event candidates available for daily market brief.")
    if not next_7d_calendar:
        warnings.append("No official calendar events found in the next 7 days.")
    return warnings


def _event_name(event: dict[str, Any]) -> str:
    return str(event.get("evidence_text") or event.get("event_type") or event.get("event_id") or "")


def _source_label(event: dict[str, Any]) -> str:
    data_quality = event.get("data_quality") or {}
    source_keys = data_quality.get("source_keys") or []
    if source_keys:
        return " + ".join(str(source) for source in source_keys)
    source_refs = event.get("source_refs") or []
    sources = sorted({str(ref.get("source")) for ref in source_refs if isinstance(ref, dict) and ref.get("source")})
    return " + ".join(sources) if sources else "unknown"


def _source_status(event: dict[str, Any]) -> str:
    verification = str(event.get("verification_status") or "single_source")
    if verification == "official_confirmed":
        return "official_confirmed"
    if verification == "multi_source":
        return "multi_source_unofficial"
    return "needs_verification"


def _importance(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    if event_type in {"inflation_release", "labor_release", "pce_release", "fomc_statement", "hormuz_risk"}:
        return "high"
    if event_type in {"gdp_release", "energy_inventory_release", "fed_speech"}:
        return "medium"
    return "low"


def _market_validation(reaction: dict[str, Any]) -> dict[str, Any]:
    if not reaction:
        return {
            "pricing_status": "unknown",
            "confirmation_summary": {"confirmed_count": 0, "contradicted_count": 0, "observed_count": 0},
            "windows": {},
        }
    return {
        "pricing_status": reaction.get("pricing_status") or "unknown",
        "confirmation_summary": reaction.get("confirmation_summary") or {},
        "windows": reaction.get("windows") or {},
        "market_snapshot": _market_snapshot(reaction),
    }


def _market_snapshot(reaction: dict[str, Any]) -> dict[str, Any]:
    snapshot = reaction.get("market_snapshot")
    if isinstance(snapshot, dict):
        return snapshot
    return {
        "event_time": None,
        "requested_assets": [],
        "observed_assets": [],
        "missing_assets": [],
        "primary_window": None,
        "assets": [],
    }


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = json.dumps(ref, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped
