from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SOURCE_CONFIDENCE_ORDER = {
    "official_confirmed": 0,
    "multi_source": 1,
    "report_derived": 2,
    "single_source": 3,
    "unverified": 4,
}


@dataclass(frozen=True)
class DailyBriefInputSnapshot:
    date: str
    run_id: str
    report_mode: str
    should_generate: bool
    one_line_inputs: list[str]
    core_events: list[dict[str, Any]]
    key_articles: list[dict[str, Any]]
    market_reactions: list[dict[str, Any]]
    key_levels: dict[str, Any]
    scenario_inputs: list[dict[str, Any]]
    risk_flags: list[str]
    source_refs: list[dict[str, Any]]
    quality_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_daily_brief_input_snapshot(
    *,
    retrieved_date: str,
    run_id: str,
    daily_market_brief: Any | None = None,
    daily_analysis_triggers: Any | None = None,
    jin10_article_briefs: Any | None = None,
    report_events: Any | None = None,
    market_reactions: Any | None = None,
) -> DailyBriefInputSnapshot:
    market_brief = _unwrap(_dict(daily_market_brief), "daily_market_brief")
    trigger_bundle = _unwrap(_dict(daily_analysis_triggers), "daily_analysis_triggers")
    article_bundle = _unwrap(_dict(jin10_article_briefs), "jin10_article_briefs")
    report_event_bundle = _unwrap(_dict(report_events), "report_events")

    triggers = [_dict(item) for item in _list(trigger_bundle.get("triggers"))]
    articles = [_dict(item) for item in _list(article_bundle.get("briefs"))]
    report_items = [_dict(item) for item in _list(report_event_bundle.get("items"))]

    core_events = _core_events(market_brief=market_brief, triggers=triggers)
    key_articles = _key_articles(articles)
    reactions = _market_reactions(market_brief=market_brief, market_reactions=market_reactions)
    has_market_validation = any(bool(item.get("threshold_hit")) for item in reactions)
    has_high_trigger = any(str(trigger.get("priority")) == "high" for trigger in triggers)
    has_strong_news = has_high_trigger or _has_strong_news(core_events=core_events, market_reactions=reactions)
    has_report_input = bool(key_articles or report_items)

    if has_strong_news and has_report_input:
        report_mode = "hybrid"
    elif has_strong_news:
        report_mode = "news_driven"
    elif has_report_input:
        report_mode = "report_driven"
    else:
        report_mode = "empty"
    should_generate = report_mode != "empty"

    source_refs = _source_refs(
        market_brief=market_brief,
        core_events=core_events,
        triggers=triggers,
        key_articles=key_articles,
        report_items=report_items,
    )
    one_line_inputs = _one_line_inputs(market_brief=market_brief, triggers=triggers, key_articles=key_articles)
    key_levels = _key_levels([*one_line_inputs, *[str(article.get("original_excerpt") or "") for article in key_articles]])
    risk_flags = _risk_flags(core_events=core_events, triggers=triggers)
    quality_flags = _quality_flags(
        should_generate=should_generate,
        core_events=core_events,
        triggers=triggers,
        key_articles=key_articles,
        has_market_validation=has_market_validation,
    )

    return DailyBriefInputSnapshot(
        date=retrieved_date,
        run_id=run_id,
        report_mode=report_mode,
        should_generate=should_generate,
        one_line_inputs=one_line_inputs,
        core_events=core_events,
        key_articles=key_articles,
        market_reactions=reactions,
        key_levels=key_levels,
        scenario_inputs=_scenario_inputs(market_brief=market_brief, report_items=report_items),
        risk_flags=risk_flags,
        source_refs=source_refs,
        quality_flags=quality_flags,
    )


def archive_daily_brief_input_snapshot(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    snapshot: DailyBriefInputSnapshot,
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "daily_brief_input_snapshot.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "retrieved_date": retrieved_date,
                "run_id": run_id,
                "daily_brief_input_snapshot": snapshot.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target.relative_to(storage_root).as_posix()


def _core_events(*, market_brief: dict[str, Any], triggers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for key in ("confirmed_events", "unconfirmed_risks", "candidate_events"):
        events.extend(_dict(item) for item in _list(market_brief.get(key)))

    trigger_event_ids = {str(trigger.get("source_event_id") or "") for trigger in triggers if trigger.get("source_event_id")}
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        event_id = str(event.get("event_id") or event.get("source_event_id") or "")
        if event_id and event_id in seen:
            continue
        if not _is_actionable_event(event) and event_id not in trigger_event_ids:
            continue
        seen.add(event_id)
        selected.append(_event_summary(event))

    return sorted(selected, key=_event_sort_key)[:6]


def _key_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for article in articles:
        actions = {str(action) for action in _list(article.get("suggested_actions"))}
        article_class = str(article.get("article_class") or "")
        if "queue_daily_analysis" not in actions and article_class not in {
            "gold_macro_market_reference",
            "vip_market_reference",
            "energy_macro_reference",
        }:
            continue
        selected.append(
            {
                "brief_id": article.get("brief_id"),
                "article_class": article_class,
                "display_bucket": article.get("display_bucket"),
                "headline": article.get("headline"),
                "source_url": article.get("source_url"),
                "final_url": article.get("final_url"),
                "access_status": article.get("access_status"),
                "original_excerpt": article.get("original_excerpt"),
                "key_points": _list(article.get("key_points"))[:5],
                "analysis_summary": article.get("analysis_summary"),
                "asset_tags": _list(article.get("asset_tags")),
                "topic_tags": _list(article.get("topic_tags")),
                "detail_artifacts": _dict(article.get("detail_artifacts")),
                "source_refs": [dict(ref) for ref in _list(article.get("source_refs")) if isinstance(ref, dict)],
                "source_confidence": "report_derived",
            }
        )
    return selected[:5]


def _market_reactions(*, market_brief: dict[str, Any], market_reactions: Any | None) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for item in _list(market_brief.get("asset_reactions")):
        if isinstance(item, dict):
            flattened.append(dict(item))

    explicit = _dict(market_reactions)
    if explicit:
        raw_reactions = _list(explicit.get("market_reactions"))
    else:
        raw_reactions = _list(market_reactions)
    for reaction in (_dict(item) for item in raw_reactions):
        event_id = str(reaction.get("event_id") or "")
        pricing_status = reaction.get("pricing_status") or "unknown"
        for window, assets in _dict(reaction.get("windows")).items():
            for asset, movement in _dict(assets).items():
                movement_dict = _dict(movement)
                if not movement_dict:
                    continue
                flattened.append(
                    {
                        "event_id": event_id,
                        "window": window,
                        "asset": asset,
                        "direction": movement_dict.get("direction"),
                        "pct_change": movement_dict.get("pct_change"),
                        "change_bp": movement_dict.get("change_bp"),
                        "threshold_hit": movement_dict.get("threshold_hit"),
                        "expected_direction": movement_dict.get("expected_direction"),
                        "pricing_status": pricing_status,
                    }
                )
    return _dedupe_dicts(flattened)[:12]


def _has_strong_news(*, core_events: list[dict[str, Any]], market_reactions: list[dict[str, Any]]) -> bool:
    if any(event.get("source_confidence") in {"official_confirmed", "multi_source"} for event in core_events):
        return True
    if any(bool(reaction.get("threshold_hit")) for reaction in market_reactions):
        return True
    return False


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    source_confidence = _source_confidence(event)
    return {
        "event_id": event.get("event_id") or event.get("source_event_id"),
        "event_type": event.get("event_type"),
        "event_time": event.get("event_time"),
        "what_happened": event.get("what_happened") or event.get("source_title") or event.get("evidence_text"),
        "verification_status": event.get("verification_status"),
        "source_confidence": source_confidence,
        "risk_level": event.get("risk_level") or "low",
        "impact_path": event.get("impact_path") or "unknown",
        "gold_impact": event.get("gold_impact") or "unknown",
        "pricing_status": event.get("pricing_status") or "unknown",
        "asset_tags": _list(event.get("affected_assets") or event.get("asset_tags")),
        "source_refs": [dict(ref) for ref in _list(event.get("source_refs")) if isinstance(ref, dict)],
    }


def _is_actionable_event(event: dict[str, Any]) -> bool:
    if event.get("verification_status") in {"official_confirmed", "multi_source"}:
        return True
    if event.get("risk_level") in {"high", "medium"}:
        return True
    if event.get("pricing_status") not in {None, "", "unknown"}:
        return True
    return False


def _source_confidence(item: dict[str, Any]) -> str:
    verification = str(item.get("verification_status") or "")
    if verification in SOURCE_CONFIDENCE_ORDER:
        return verification
    if item.get("source_confidence") in SOURCE_CONFIDENCE_ORDER:
        return str(item["source_confidence"])
    if item.get("source_count") and int(item.get("source_count") or 0) > 1:
        return "multi_source"
    return "single_source"


def _event_sort_key(event: dict[str, Any]) -> tuple[int, int, str]:
    risk_rank = {"high": 0, "medium": 1, "low": 2}
    return (
        SOURCE_CONFIDENCE_ORDER.get(str(event.get("source_confidence") or "single_source"), 99),
        risk_rank.get(str(event.get("risk_level") or "low"), 9),
        str(event.get("event_time") or event.get("event_id") or ""),
    )


def _one_line_inputs(
    *,
    market_brief: dict[str, Any],
    triggers: list[dict[str, Any]],
    key_articles: list[dict[str, Any]],
) -> list[str]:
    values: list[str] = []
    mainline = _dict(market_brief.get("market_mainline"))
    if mainline.get("status") == "available":
        values.append(str(mainline.get("summary") or "").strip())
    for trigger in sorted(triggers, key=lambda item: str(item.get("priority") or ""), reverse=True):
        values.append(str(trigger.get("source_title") or trigger.get("evidence_text") or "").strip())
    if not triggers:
        for article in key_articles:
            values.append(str(article.get("headline") or "").strip())
    return _dedupe_text(values)[:5]


def _key_levels(texts: list[str]) -> dict[str, Any]:
    levels: list[int] = []
    for text in texts:
        for match in re.findall(r"(?<!\d)(?:[34]\d{3}|5\d{3})(?!\d)", text):
            value = int(match)
            if value not in levels:
                levels.append(value)
    return {"mentioned_levels": levels} if levels else {}


def _scenario_inputs(*, market_brief: dict[str, Any], report_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    report_inputs = _dict(market_brief.get("report_inputs"))
    scenarios: list[dict[str, Any]] = []
    for risk in _list(report_inputs.get("risk_points"))[:5]:
        scenarios.append({"type": "risk_point", "text": str(risk)})
    for item in report_items[:5]:
        scenarios.append(
            {
                "type": "report_event",
                "event_type": item.get("event_type"),
                "text": item.get("summary") or item.get("title"),
                "source_confidence": "report_derived",
            }
        )
    return scenarios


def _risk_flags(*, core_events: list[dict[str, Any]], triggers: list[dict[str, Any]]) -> list[str]:
    flags: list[str] = []
    if any(event.get("risk_level") == "high" for event in core_events):
        flags.append("high_risk_event")
    if any(str(trigger.get("priority")) == "high" for trigger in triggers):
        flags.append("high_priority_daily_analysis_trigger")
    if any(event.get("source_confidence") in {"single_source", "unverified"} for event in core_events):
        flags.append("verification_risk")
    return flags


def _quality_flags(
    *,
    should_generate: bool,
    core_events: list[dict[str, Any]],
    triggers: list[dict[str, Any]],
    key_articles: list[dict[str, Any]],
    has_market_validation: bool,
) -> list[str]:
    if not should_generate:
        return ["no_actionable_inputs"]
    flags: list[str] = []
    if any(event.get("source_confidence") in {"single_source", "unverified"} for event in core_events) or any(
        _trigger_source_confidence(trigger) in {"single_source", "unverified"} for trigger in triggers
    ):
        flags.append("single_source_verification_required")
    if key_articles and not has_market_validation:
        flags.append("missing_market_validation")
    return flags


def _trigger_source_confidence(trigger: dict[str, Any]) -> str:
    data_quality = _dict(trigger.get("data_quality"))
    verification = str(data_quality.get("verification_status") or trigger.get("verification_status") or "single_source")
    return verification if verification in SOURCE_CONFIDENCE_ORDER else "single_source"


def _source_refs(
    *,
    market_brief: dict[str, Any],
    core_events: list[dict[str, Any]],
    triggers: list[dict[str, Any]],
    key_articles: list[dict[str, Any]],
    report_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    refs.extend(dict(ref) for ref in _list(market_brief.get("source_refs")) if isinstance(ref, dict))
    for container in [*core_events, *triggers, *key_articles, *report_items]:
        refs.extend(dict(ref) for ref in _list(container.get("source_refs")) if isinstance(ref, dict))
    return _dedupe_dicts(refs)


def _unwrap(value: dict[str, Any], key: str) -> dict[str, Any]:
    nested = value.get(key)
    return _dict(nested) if isinstance(nested, dict) else value


def _dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _dedupe_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
