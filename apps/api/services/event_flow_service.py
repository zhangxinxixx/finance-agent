"""
P1-08: Event Flow Read Model 后端服务。

提供只读事件流 overview，数据来源：
  - Jin10 MCP: 快讯 (list_flash / search_flash)、财经日历 (list_calendar)
  - Market Odds: 事件定价状态
  - 未来可接入 Polymarket / CME FedWatch

规则:
  - 不计算事件影响 / 传导链 / 交易判断。
  - 缺失数据显式返回 unavailable。
  - source_refs 可追溯到真实数据源。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.agent_read_model import build_event_impact_agent_summary
from apps.api.services.daily_analysis_followup_service import get_daily_analysis_followups_latest
from apps.api.services.daily_analysis_trigger_service import get_daily_analysis_triggers_latest
from apps.api.services.jin10_article_brief_service import get_jin10_article_briefs_latest

logger = logging.getLogger(__name__)


def build_event_flow_overview() -> dict[str, Any]:
    """构建事件流 overview 只读响应。"""
    result: dict[str, Any] = {
        "status": "unavailable",
        "source": "unavailable",
        "updated_at": None,
        "events": [],
        "flash_count": 0,
        "calendar_count": 0,
        "event_impact_summary": build_event_impact_agent_summary(),
        "brief_summary": None,
        "daily_analysis_triggers": None,
        "daily_analysis_followups": None,
        "article_briefs": None,
        "source_refs": [],
        "warnings": [],
    }

    daily_analysis_followups = get_daily_analysis_followups_latest(project_root=_PROJECT_ROOT)
    if daily_analysis_followups:
        result["daily_analysis_followups"] = daily_analysis_followups

    daily_analysis_triggers = get_daily_analysis_triggers_latest(project_root=_PROJECT_ROOT)
    if daily_analysis_triggers:
        result["daily_analysis_triggers"] = daily_analysis_triggers

    article_briefs = get_jin10_article_briefs_latest(project_root=_PROJECT_ROOT)
    if article_briefs:
        result["article_briefs"] = article_briefs

    brief = _load_latest_daily_market_brief()
    if brief and not _has_newer_news_signal(
        brief,
        daily_analysis_triggers=daily_analysis_triggers,
        article_briefs=article_briefs,
    ):
        result["status"] = "partial"
        result["source"] = "daily_market_brief"
        result["updated_at"] = brief.get("as_of")
        result["events"].extend(_normalize_daily_market_brief_events(brief))
        result["brief_summary"] = _build_brief_summary(brief)
        result["source_refs"] = _normalize_brief_source_refs(brief)
        if daily_analysis_triggers:
            result["source_refs"].append(_daily_analysis_triggers_source_ref(daily_analysis_triggers))
        if article_briefs:
            result["source_refs"].append(_article_briefs_source_ref(article_briefs))
        result["warnings"].extend(str(warning) for warning in brief.get("warnings", []) if warning)
        return result

    if brief:
        result["warnings"].append("daily_market_brief is older than the latest Jin10 follow-up read model.")
        _apply_latest_followup_read_model(
            result,
            daily_analysis_triggers=daily_analysis_triggers,
            article_briefs=article_briefs,
        )
        return result

    # ── 尝试从 Jin10 快照提取事件数据 ──
    jin10 = _load_jin10_from_snapshot()
    if jin10:
        result["status"] = "partial"
        result["source"] = "jin10_mcp"

        # 快讯
        flashes_raw = jin10.get("flashes") or jin10.get("flash_items") or []
        if isinstance(flashes_raw, list):
            result["flash_count"] = len(flashes_raw)
            result["events"].extend(_normalize_flashes(flashes_raw))

        # 财经日历
        calendar_raw = jin10.get("calendar") or jin10.get("calendar_items") or []
        if isinstance(calendar_raw, list):
            result["calendar_count"] = len(calendar_raw)
            result["events"].extend(_normalize_calendar(calendar_raw))

        # 文章
        articles_raw = jin10.get("articles") or jin10.get("article_items") or []
        if isinstance(articles_raw, list):
            result["events"].extend(_normalize_articles(articles_raw))

        result["source_refs"] = [{
            "source_ref": "jin10.mcp",
            "label": "Jin10 MCP 快讯 & 财经日历",
            "status": "ok",
        }]

    if daily_analysis_triggers and not result["events"]:
        result["status"] = "partial"
        result["source"] = "daily_analysis_triggers"
        result["updated_at"] = daily_analysis_triggers.get("as_of")
        result["events"].extend(_normalize_daily_analysis_trigger_events(daily_analysis_triggers))
        result["source_refs"].append(_daily_analysis_triggers_source_ref(daily_analysis_triggers))
        if article_briefs:
            result["events"].extend(_normalize_article_brief_events(article_briefs))
            result["source_refs"].append(_article_briefs_source_ref(article_briefs))

    if article_briefs and not result["events"]:
        result["status"] = "partial"
        result["source"] = "jin10_article_briefs"
        result["updated_at"] = article_briefs.get("as_of")
        result["events"].extend(_normalize_article_brief_events(article_briefs))
        result["source_refs"].append(_article_briefs_source_ref(article_briefs))

    if not result["events"] and not article_briefs and not daily_analysis_triggers:
        result["warnings"].append("Jin10 快讯/日历数据当前不可用，页面展示 mock 数据。")

    return result


def build_event_flow_briefs() -> dict[str, Any]:
    """构建当日快讯 / 金十文章只读 read model。"""
    overview = build_event_flow_overview()
    article_briefs = overview.get("article_briefs") if isinstance(overview.get("article_briefs"), dict) else None
    if article_briefs:
        return {
            "status": article_briefs.get("status") or overview.get("status") or "partial",
            "source": "jin10_article_briefs",
            "updated_at": article_briefs.get("as_of") or overview.get("updated_at"),
            "date": article_briefs.get("date"),
            "run_id": article_briefs.get("run_id"),
            "artifact_path": article_briefs.get("artifact_path"),
            "brief_count": int(article_briefs.get("brief_count") or len(article_briefs.get("briefs") or [])),
            "briefs": article_briefs.get("briefs") if isinstance(article_briefs.get("briefs"), list) else [],
            "source_refs": [_article_briefs_source_ref(article_briefs)],
            "page_source_refs": overview.get("source_refs") if isinstance(overview.get("source_refs"), list) else [],
            "warnings": overview.get("warnings") if isinstance(overview.get("warnings"), list) else [],
        }

    brief_events = [event for event in _overview_events(overview) if event.get("kind") in {"jin10_article_brief", "daily_analysis_trigger", "flash", "article"}]
    return {
        "status": overview.get("status") or "unavailable",
        "source": overview.get("source") or "unavailable",
        "updated_at": overview.get("updated_at"),
        "date": None,
        "run_id": None,
        "artifact_path": None,
        "brief_count": len(brief_events),
        "briefs": [],
        "events": brief_events,
        "source_refs": overview.get("source_refs") if isinstance(overview.get("source_refs"), list) else [],
        "page_source_refs": overview.get("source_refs") if isinstance(overview.get("source_refs"), list) else [],
        "warnings": overview.get("warnings") if isinstance(overview.get("warnings"), list) else [],
    }


def build_event_flow_events() -> dict[str, Any]:
    """构建事件列表只读 read model。"""
    overview = build_event_flow_overview()
    events = _overview_events(overview)
    return {
        "status": overview.get("status") or "unavailable",
        "source": overview.get("source") or "unavailable",
        "updated_at": overview.get("updated_at"),
        "event_count": len(events),
        "events": events,
        "source_refs": overview.get("source_refs") if isinstance(overview.get("source_refs"), list) else [],
        "warnings": overview.get("warnings") if isinstance(overview.get("warnings"), list) else [],
    }


def build_event_flow_event_detail(event_id: str) -> dict[str, Any] | None:
    """按 event_id 构建单事件只读详情。"""
    overview = build_event_flow_overview()
    event = _find_event(overview, event_id)
    if event is None:
        return None
    event_refs = event.get("source_refs") if isinstance(event.get("source_refs"), list) else []
    page_refs = overview.get("source_refs") if isinstance(overview.get("source_refs"), list) else []
    return {
        "status": overview.get("status") or "unavailable",
        "source": overview.get("source") or "unavailable",
        "updated_at": overview.get("updated_at"),
        "event": event,
        "source_refs": event_refs,
        "page_source_refs": page_refs,
        "article_briefs": _related_article_briefs(overview, event),
        "warnings": overview.get("warnings") if isinstance(overview.get("warnings"), list) else [],
    }


def build_event_flow_impact(event_id: str) -> dict[str, Any] | None:
    """按 event_id 构建影响分析只读 read model。"""
    overview = build_event_flow_overview()
    event = _find_event(overview, event_id)
    if event is None:
        return None
    impact_fields = {
        "event_id": event.get("id"),
        "status": overview.get("status") or "unavailable",
        "source": overview.get("source") or "unavailable",
        "updated_at": overview.get("updated_at"),
        "impact_path": event.get("impact_path"),
        "gold_impact": event.get("gold_impact"),
        "silver_impact": event.get("silver_impact"),
        "dollar_impact": event.get("dollar_impact"),
        "yield_impact": event.get("yield_impact"),
        "oil_impact": event.get("oil_impact"),
        "risk_level": event.get("risk_level"),
        "pricing_status": event.get("pricing"),
        "verification_status": event.get("verification_status"),
        "affected_assets": event.get("affected_assets") if isinstance(event.get("affected_assets"), list) else [],
        "event": event,
        "event_impact_summary": overview.get("event_impact_summary"),
        "source_refs": event.get("source_refs") if isinstance(event.get("source_refs"), list) else [],
    }
    return impact_fields


def build_event_flow_market_reaction(event_id: str) -> dict[str, Any] | None:
    """按 event_id 构建行情反应只读 read model。"""
    overview = build_event_flow_overview()
    event = _find_event(overview, event_id)
    if event is None:
        return None
    market_validation = event.get("market_validation") if isinstance(event.get("market_validation"), dict) else {}
    market_snapshot = event.get("market_snapshot")
    if market_snapshot is None and isinstance(market_validation.get("market_snapshot"), dict):
        market_snapshot = market_validation.get("market_snapshot")
    return {
        "event_id": event.get("id"),
        "status": market_validation.get("status") or ("unavailable" if not market_validation and market_snapshot is None else "partial"),
        "source": overview.get("source") or "unavailable",
        "updated_at": overview.get("updated_at"),
        "pricing_status": event.get("pricing"),
        "verification_status": event.get("verification_status"),
        "market_validation": market_validation,
        "market_snapshot": market_snapshot,
        "source_refs": event.get("source_refs") if isinstance(event.get("source_refs"), list) else [],
        "warnings": [] if market_validation or market_snapshot is not None else ["market_validation unavailable for this event."],
    }


def build_event_flow_report_inputs() -> dict[str, Any]:
    """构建报告输入只读 read model。"""
    overview = build_event_flow_overview()
    brief_summary = overview.get("brief_summary") if isinstance(overview.get("brief_summary"), dict) else {}
    report_inputs = brief_summary.get("report_inputs") if isinstance(brief_summary.get("report_inputs"), dict) else {}
    article_briefs = overview.get("article_briefs") if isinstance(overview.get("article_briefs"), dict) else {}
    daily_analysis_followups = overview.get("daily_analysis_followups") if isinstance(overview.get("daily_analysis_followups"), dict) else {}
    source_refs = overview.get("source_refs") if isinstance(overview.get("source_refs"), list) else []
    return {
        "status": overview.get("status") or "unavailable",
        "source": overview.get("source") or "unavailable",
        "updated_at": overview.get("updated_at"),
        "report_inputs": report_inputs,
        "brief_summary": brief_summary or None,
        "article_briefs": article_briefs or None,
        "daily_analysis_triggers": overview.get("daily_analysis_triggers"),
        "daily_analysis_followups": daily_analysis_followups or None,
        "actionable_inputs": _build_actionable_report_inputs(
            report_inputs=report_inputs,
            article_briefs=article_briefs,
            daily_analysis_followups=daily_analysis_followups,
            page_source_refs=source_refs,
        ),
        "source_refs": source_refs,
        "warnings": overview.get("warnings") if isinstance(overview.get("warnings"), list) else [],
    }


def _overview_events(overview: dict[str, Any]) -> list[dict[str, Any]]:
    events = overview.get("events")
    return [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []


def _find_event(overview: dict[str, Any], event_id: str) -> dict[str, Any] | None:
    for event in _overview_events(overview):
        if str(event.get("id")) == event_id:
            return event
    return None


def _related_article_briefs(overview: dict[str, Any], event: dict[str, Any]) -> list[dict[str, Any]]:
    article_briefs = overview.get("article_briefs") if isinstance(overview.get("article_briefs"), dict) else {}
    briefs = article_briefs.get("briefs") if isinstance(article_briefs.get("briefs"), list) else []
    assets = set(str(asset) for asset in event.get("affected_assets") or [] if asset)
    event_type = str(event.get("event_type") or "")
    related: list[dict[str, Any]] = []
    for brief in briefs:
        if not isinstance(brief, dict):
            continue
        brief_assets = set(str(asset) for asset in brief.get("asset_tags") or [] if asset)
        brief_topics = set(str(topic) for topic in brief.get("topic_tags") or [] if topic)
        if assets.intersection(brief_assets) or (event_type and event_type in brief_topics):
            related.append(brief)
    return related[:10]


def _apply_latest_followup_read_model(
    result: dict[str, Any],
    *,
    daily_analysis_triggers: dict[str, Any] | None,
    article_briefs: dict[str, Any] | None,
) -> None:
    result["status"] = "partial"
    result["updated_at"] = _latest_as_of(daily_analysis_triggers, article_briefs)

    if daily_analysis_triggers:
        result["source"] = "daily_analysis_triggers"
        result["events"].extend(_normalize_daily_analysis_trigger_events(daily_analysis_triggers))
        result["source_refs"].append(_daily_analysis_triggers_source_ref(daily_analysis_triggers))

    if article_briefs:
        if result["source"] == "unavailable":
            result["source"] = "jin10_article_briefs"
        result["events"].extend(_normalize_article_brief_events(article_briefs))
        result["source_refs"].append(_article_briefs_source_ref(article_briefs))

    if not result["events"] and result["source"] == "unavailable":
        result["source"] = "daily_analysis_triggers" if daily_analysis_triggers else "jin10_article_briefs"


def _has_newer_news_signal(
    brief: dict[str, Any],
    *,
    daily_analysis_triggers: dict[str, Any] | None,
    article_briefs: dict[str, Any] | None,
) -> bool:
    brief_date = _payload_date(brief.get("_artifact_ref") if isinstance(brief.get("_artifact_ref"), dict) else brief)
    brief_time = _parse_as_of(brief.get("as_of"))
    if brief_time is None:
        return bool(daily_analysis_triggers or article_briefs)
    for payload in (daily_analysis_triggers, article_briefs):
        if _payload_date(payload) <= brief_date:
            continue
        payload_time = _parse_as_of(payload.get("as_of") if isinstance(payload, dict) else None)
        if payload_time is not None and payload_time > brief_time:
            return True
    return False


def _payload_date(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    value = payload.get("date")
    return str(value) if value else ""


def _latest_as_of(*payloads: dict[str, Any] | None) -> str | None:
    latest_payload: dict[str, Any] | None = None
    latest_time: datetime | None = None
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        parsed = _parse_as_of(payload.get("as_of"))
        if parsed is not None and (latest_time is None or parsed > latest_time):
            latest_time = parsed
            latest_payload = payload
    if latest_payload is not None:
        value = latest_payload.get("as_of")
        return str(value) if value else None
    return None


def _parse_as_of(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _daily_analysis_triggers_source_ref(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_ref": f"daily_analysis_triggers:{payload.get('date')}/{payload.get('run_id')}",
        "label": "Daily Analysis Triggers",
        "status": payload.get("status") or "ok",
        "path": payload.get("artifact_path"),
    }


def _article_briefs_source_ref(article_briefs: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_ref": f"jin10_article_briefs:{article_briefs.get('date')}/{article_briefs.get('run_id')}",
        "label": "Jin10 Article Briefs",
        "status": article_briefs.get("status") or "ok",
        "path": article_briefs.get("artifact_path"),
    }


def _normalize_daily_analysis_trigger_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in payload.get("triggers") or []:
        if not isinstance(item, dict):
            continue
        data_quality = item.get("data_quality") if isinstance(item.get("data_quality"), dict) else {}
        event = {
            "id": str(item.get("trigger_id") or item.get("source_event_id") or _stable_event_id("trigger", item.get("source_title"), item.get("evidence_text"))),
            "kind": "daily_analysis_trigger",
            "time": item.get("created_at") or payload.get("as_of"),
            "title": str(item.get("source_title") or item.get("evidence_text") or item.get("event_type") or "")[:120],
            "importance": _priority_importance(item.get("priority")),
            "pricing": "unpriced",
            "source": item.get("source_key") or "daily_analysis_triggers",
            "verification_status": item.get("verification_status") or data_quality.get("verification_status"),
            "risk_level": item.get("risk_level"),
            "event_type": item.get("event_type"),
            "affected_assets": item.get("asset_tags") if isinstance(item.get("asset_tags"), list) else [],
            "impact_path": item.get("impact_path"),
            "gold_impact": item.get("gold_impact"),
            "silver_impact": item.get("silver_impact"),
            "dollar_impact": item.get("dollar_impact"),
            "yield_impact": item.get("yield_impact"),
            "oil_impact": item.get("oil_impact"),
            "source_refs": item.get("source_refs") if isinstance(item.get("source_refs"), list) else [],
        }
        events.append(event)
    return events[:50]


def _normalize_article_brief_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in payload.get("briefs") or []:
        if not isinstance(item, dict):
            continue
        data_quality = item.get("data_quality") if isinstance(item.get("data_quality"), dict) else {}
        event = {
            "id": str(item.get("brief_id") or _stable_event_id("article_brief", item.get("headline"), item.get("final_url"))),
            "kind": "jin10_article_brief",
            "time": item.get("created_at") or payload.get("as_of"),
            "title": str(item.get("headline") or item.get("analysis_summary") or "")[:120],
            "importance": _article_brief_importance(item),
            "pricing": "unpriced",
            "source": "jin10_article_briefs",
            "verification_status": item.get("verification_status") or data_quality.get("verification_status"),
            "risk_level": item.get("priority"),
            "event_type": item.get("article_class"),
            "affected_assets": item.get("asset_tags") if isinstance(item.get("asset_tags"), list) else [],
            "source_refs": item.get("source_refs") if isinstance(item.get("source_refs"), list) else [],
        }
        events.append(event)
    return events[:50]


def _priority_importance(priority: Any) -> str:
    if priority == "high":
        return "高"
    if priority == "medium":
        return "中"
    return "低"


def _article_brief_importance(item: dict[str, Any]) -> str:
    bucket = item.get("display_bucket")
    if bucket in {"重点分析", "VIP预览"}:
        return "中"
    return "低"


def _build_brief_summary(brief: dict[str, Any]) -> dict[str, Any]:
    artifact_ref = brief.get("_artifact_ref") if isinstance(brief.get("_artifact_ref"), dict) else {}
    market_mainline = brief.get("market_mainline") if isinstance(brief.get("market_mainline"), dict) else {}
    data_quality = brief.get("data_quality") if isinstance(brief.get("data_quality"), dict) else {}
    report_inputs = brief.get("report_inputs") if isinstance(brief.get("report_inputs"), dict) else {}
    return {
        "artifact_ref": artifact_ref,
        "market_mainline": market_mainline,
        "data_quality": data_quality,
        "report_inputs": report_inputs,
        "counts": {
            "confirmed_event_count": len(brief.get("confirmed_events") or []),
            "candidate_event_count": len(brief.get("candidate_events") or []),
            "unconfirmed_risk_count": len(brief.get("unconfirmed_risks") or []),
            "calendar_event_count": len(brief.get("next_7d_calendar") or []),
            "source_ref_count": len(brief.get("source_refs") or []),
        },
    }


def _build_actionable_report_inputs(
    *,
    report_inputs: dict[str, Any],
    article_briefs: dict[str, Any],
    daily_analysis_followups: dict[str, Any],
    page_source_refs: list[Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    group_specs = [
        ("news_highlights", "news_highlights", "新闻重点"),
        ("watchlist", "watchlist", "观察清单"),
        ("risk_points", "risk_points", "风险提示"),
    ]
    for group_key, group_label, display_group in group_specs:
        raw_items = report_inputs.get(group_key)
        if not isinstance(raw_items, list):
            continue
        for raw_item in raw_items:
            title = _report_input_title(raw_item)
            if not title:
                continue
            summary = _report_input_summary(raw_item, fallback=title)
            stable_key = _stable_event_id(group_key, title, summary)
            items.append(
                {
                    "input_id": f"summary:{group_key}:{stable_key}",
                    "input_kind": "summary",
                    "group": display_group,
                    "title": title,
                    "summary": summary,
                    "verification_status": None,
                    "access_status": None,
                    "artifact_path": None,
                    "source_url": None,
                    "source_refs": [dict(ref) for ref in page_source_refs if isinstance(ref, dict)],
                }
            )

    for followup in daily_analysis_followups.get("followups") or []:
        if not isinstance(followup, dict):
            continue
        followup_id = str(followup.get("followup_id") or _stable_event_id("followup", followup.get("title"), followup.get("source_url")))
        items.append(
            {
                "input_id": f"followup:{followup_id}",
                "input_kind": "followup",
                "group": "待跟进分析",
                "title": str(followup.get("source_title") or followup.get("title") or "未命名跟进项"),
                "summary": _followup_summary(followup),
                "verification_status": _string_or_none((followup.get("data_quality") or {}).get("verification_status")),
                "access_status": None,
                "artifact_path": _followup_artifact_path(daily_analysis_followups, followup),
                "source_url": _string_or_none(followup.get("source_url")),
                "source_refs": [dict(ref) for ref in followup.get("source_refs") or [] if isinstance(ref, dict)],
                "task_status": str(followup.get("status") or "queued"),
            }
        )

    for brief in article_briefs.get("briefs") or []:
        if not isinstance(brief, dict):
            continue
        brief_id = str(brief.get("brief_id") or _stable_event_id("brief", brief.get("headline"), brief.get("final_url") or brief.get("source_url")))
        items.append(
            {
                "input_id": f"article_brief:{brief_id}",
                "input_kind": "article_brief",
                "group": "文章简报",
                "title": str(brief.get("headline") or "未命名文章"),
                "summary": _report_input_summary(brief, fallback=str(brief.get("analysis_summary") or brief.get("original_excerpt") or brief.get("headline") or "")),
                "verification_status": _string_or_none((brief.get("data_quality") or {}).get("verification_status")),
                "access_status": _string_or_none(brief.get("access_status")),
                "artifact_path": _string_or_none(article_briefs.get("artifact_path")),
                "source_url": _string_or_none(brief.get("final_url") or brief.get("source_url")),
                "source_refs": [dict(ref) for ref in brief.get("source_refs") or [] if isinstance(ref, dict)],
            }
        )

    return items


def _report_input_title(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in ("title", "what_happened", "event_name", "summary", "event_type"):
        text = str(value.get(key) or "").strip()
        if text:
            return text
    return ""


def _report_input_summary(value: Any, *, fallback: str) -> str:
    if isinstance(value, str):
        return value.strip() or fallback
    if not isinstance(value, dict):
        return fallback
    for key in ("summary", "what_happened", "evidence_text", "title", "event_name", "event_type"):
        text = str(value.get(key) or "").strip()
        if text:
            return text
    return fallback


def _followup_summary(followup: dict[str, Any]) -> str:
    for key in ("summary", "evidence_text", "headline", "title"):
        text = str(followup.get(key) or "").strip()
        if text:
            return text
    return "暂无摘要"


def _followup_artifact_path(payload: dict[str, Any], followup: dict[str, Any]) -> str | None:
    source_artifact = str(followup.get("source_artifact") or "")
    artifact_paths = payload.get("artifact_paths") if isinstance(payload.get("artifact_paths"), dict) else {}
    if source_artifact and source_artifact in artifact_paths:
        return _string_or_none(artifact_paths.get(source_artifact))
    return _string_or_none(payload.get("artifact_path"))


def _string_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _load_latest_daily_market_brief() -> dict[str, Any] | None:
    brief_root = _PROJECT_ROOT / "storage" / "features" / "news"
    if not brief_root.exists():
        return None
    for date_dir in sorted((d for d in brief_root.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            brief_path = run_dir / "daily_market_brief.json"
            if not brief_path.exists():
                continue
            try:
                payload = json.loads(brief_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Failed to load daily_market_brief artifact", exc_info=True, extra={"path": str(brief_path)})
                continue
            brief = payload.get("daily_market_brief")
            if isinstance(brief, dict):
                brief["_artifact_ref"] = {
                    "date": date_dir.name,
                    "run_id": run_dir.name,
                    "path": brief_path.relative_to(_PROJECT_ROOT).as_posix(),
                }
                return brief
    return None


def _normalize_daily_market_brief_events(brief: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in brief.get("candidate_events") or []:
        if isinstance(item, dict):
            events.append(_normalize_brief_event(item, kind="candidate_event"))
    for item in brief.get("unconfirmed_risks") or []:
        if isinstance(item, dict):
            events.append(_normalize_brief_event(item, kind="unconfirmed_risk"))
    for item in brief.get("confirmed_events") or []:
        if isinstance(item, dict):
            events.append(_normalize_brief_event(item, kind="confirmed_event"))
    for item in brief.get("next_7d_calendar") or []:
        if isinstance(item, dict):
            events.append({
                "id": str(item.get("event_id") or _stable_event_id("calendar", item.get("event_name"), item.get("event_time"))),
                "kind": "calendar",
                "time": item.get("event_time"),
                "title": str(item.get("event_name") or "")[:120],
                "importance": item.get("importance") or "中",
                "pricing": "scheduled",
                "source": item.get("source") or "official_calendar",
                "verification_status": item.get("verification_status"),
            })
    return events[:50]


def _normalize_brief_event(item: dict[str, Any], *, kind: str) -> dict[str, Any]:
    event = {
        "id": str(item.get("event_id") or _stable_event_id(kind, item.get("what_happened"), item.get("event_time"))),
        "kind": kind,
        "time": item.get("event_time"),
        "title": str(item.get("what_happened") or item.get("event_type") or "")[:120],
        "importance": _brief_importance(item),
        "pricing": item.get("pricing_status") or "unknown",
        "source": item.get("who_said") or "daily_market_brief",
        "verification_status": item.get("verification_status"),
        "risk_level": item.get("risk_level"),
        "event_type": item.get("event_type"),
    }
    passthrough_fields = (
        "affected_assets",
        "impact_path",
        "gold_impact",
        "silver_impact",
        "dollar_impact",
        "yield_impact",
        "oil_impact",
        "market_validation",
        "market_snapshot",
        "source_refs",
    )
    for field in passthrough_fields:
        if field in item:
            event[field] = item[field]

    market_validation = item.get("market_validation")
    if "market_snapshot" not in event and isinstance(market_validation, dict) and "market_snapshot" in market_validation:
        event["market_snapshot"] = market_validation["market_snapshot"]
    return event


def _brief_importance(item: dict[str, Any]) -> str:
    if item.get("risk_level") == "high":
        return "高"
    if item.get("risk_level") == "medium":
        return "中"
    if item.get("verification_status") == "official_confirmed":
        return "高"
    return "低"


def _normalize_brief_source_refs(brief: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    artifact_ref = brief.get("_artifact_ref") or {}
    if artifact_ref:
        refs.append({
            "source_ref": f"daily_market_brief:{artifact_ref.get('date')}/{artifact_ref.get('run_id')}",
            "label": "Daily Market Brief",
            "status": "ok",
            "path": artifact_ref.get("path"),
        })
    for ref in brief.get("source_refs") or []:
        if not isinstance(ref, dict):
            continue
        refs.append({
            "source_ref": str(ref.get("source_ref") or ref.get("path") or ref.get("source") or "daily_market_brief.source"),
            "label": str(ref.get("label") or ref.get("source") or ref.get("asset_type") or "source_ref"),
            "status": str(ref.get("status") or "ok"),
            **({"path": ref.get("path")} if ref.get("path") else {}),
        })
    return refs


def _load_jin10_from_snapshot() -> dict[str, Any] | None:
    """从最新的 premarket_snapshot.json 中加载 Jin10 分区。"""
    snap_dir = _PROJECT_ROOT / "storage" / "features" / "snapshots" / "XAUUSD"
    if not snap_dir.exists():
        return None
    for date_dir in sorted((d for d in snap_dir.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            snap_path = run_dir / "premarket_snapshot.json"
            if not snap_path.exists():
                continue
            try:
                snap = json.loads(snap_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            jin10 = snap.get("jin10")
            if isinstance(jin10, dict):
                return jin10
    return None


def _normalize_flashes(flashes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for f in flashes[:30]:  # 最多 30 条快讯
        events.append({
            "id": str(f.get("id") or _stable_event_id("flash", f.get("content") or f.get("title"))),
            "kind": "flash",
            "time": f.get("time") or f.get("created_at"),
            "title": (f.get("content") or f.get("title", ""))[:120],
            "importance": _infer_importance(f),
            "pricing": "unknown",
            "source": "Jin10",
        })
    return events


def _normalize_calendar(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in items[:20]:
        events.append({
            "id": str(item.get("id") or _stable_event_id("calendar", item.get("title") or item.get("name"))),
            "kind": "calendar",
            "time": item.get("time") or item.get("pub_time"),
            "title": (item.get("title") or item.get("name", ""))[:120],
            "importance": item.get("importance") or item.get("star", "中"),
            "pricing": "unknown" if item.get("actual") is None else "priced",
            "source": "Jin10",
        })
    return events


def _normalize_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for a in articles[:10]:
        events.append({
            "id": str(a.get("id") or a.get("article_id", "")),
            "kind": "article",
            "time": a.get("time") or a.get("created_at"),
            "title": (a.get("title") or a.get("name", ""))[:120],
            "importance": "中",
            "pricing": "unknown",
            "source": "Jin10",
        })
    return events


def _infer_importance(item: dict[str, Any]) -> str:
    """从内容推断事件重要度。"""
    raw = item.get("importance") or item.get("level")
    if raw in ("高", "high", 3):
        return "高"
    if raw in ("中", "medium", 2):
        return "中"
    # 关键词简易推断
    content = (item.get("content") or item.get("title") or "").lower()
    high_keywords = ["fed", "cpi", "nft", "gdp", "战争", "利率决议", "非农", "通胀"]
    if any(kw in content for kw in high_keywords):
        return "高"
    return "低"


def _stable_event_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts if part not in (None, ""))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"
