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
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.agent_read_model import build_event_impact_agent_summary
from apps.api.services.daily_analysis_followup_service import get_daily_analysis_followups_latest
from apps.api.services.daily_analysis_trigger_service import get_daily_analysis_triggers_latest
from apps.api.services.gold_mainline_service import get_gold_mainlines_latest

logger = logging.getLogger(__name__)

_TRANSLATION_CACHE: dict[tuple[str, str], str] = {}
_TRANSLATION_DISABLED_UNTIL: dict[tuple[str, str], float] = {}
_TRANSLATION_ATTEMPTS: dict[tuple[str, str], list[float]] = {}
_TRANSLATION_WINDOW_SECONDS = 60
_TRANSLATION_MAX_CALLS_PER_WINDOW = max(1, int(os.getenv("EVENT_FLOW_TRANSLATION_MAX_CALLS_PER_MINUTE", "2")))


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _looks_like_english_block(text: str) -> bool:
    if not text or _has_chinese(text):
        return False
    letters = len(re.findall(r"[A-Za-z]", text))
    return letters >= 24 and letters >= max(12, len(text) // 5)


def _should_translate_long_english(text: str) -> bool:
    normalized = _normalize_text(text)
    if not _looks_like_english_block(normalized):
        return False
    return len(normalized) >= 72 or len(normalized.split()) >= 12


def _translation_target() -> tuple[str, str] | None:
    provider = os.getenv("EVENT_FLOW_TRANSLATION_PROVIDER", "").strip()
    if not provider:
        return None
    model = os.getenv("EVENT_FLOW_TRANSLATION_MODEL", "").strip()
    if provider == "mimo" and not model:
        model = "mimo-v2.5"
    return provider, model


def _translation_cooldown_active(provider: str, model: str) -> bool:
    disabled_until = _TRANSLATION_DISABLED_UNTIL.get((provider, model), 0.0)
    return disabled_until > time.time()


def _disable_translation_temporarily(provider: str, model: str, *, seconds: int = 120) -> None:
    _TRANSLATION_DISABLED_UNTIL[(provider, model)] = time.time() + max(1, seconds)


def _translation_budget_available(provider: str, model: str) -> bool:
    now = time.time()
    key = (provider, model)
    recent = [stamp for stamp in _TRANSLATION_ATTEMPTS.get(key, []) if now - stamp < _TRANSLATION_WINDOW_SECONDS]
    _TRANSLATION_ATTEMPTS[key] = recent
    return len(recent) < _TRANSLATION_MAX_CALLS_PER_WINDOW


def _mark_translation_attempt(provider: str, model: str) -> None:
    key = (provider, model)
    _TRANSLATION_ATTEMPTS.setdefault(key, []).append(time.time())


def _should_translate_english(text: str) -> bool:
    normalized = _normalize_text(text)
    if _should_translate_long_english(normalized):
        return True
    return False


def _translate_english(text: Any, *, field: str) -> str:
    normalized = _normalize_text(text)
    if not _should_translate_english(normalized):
        return normalized

    cache_key = (field, normalized)
    if cache_key in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[cache_key]

    target = _translation_target()
    if target is None:
        return normalized

    provider, model = target
    if _translation_cooldown_active(provider, model):
        return normalized
    if not _translation_budget_available(provider, model):
        return normalized
    _mark_translation_attempt(provider, model)
    try:
        from apps.llm.gateway import chat_sync

        response = chat_sync(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是金融事件翻译中枢。把用户给出的英文金融资讯翻译成简体中文。"
                        "保留事实、时间、数字、机构、资产和方向，不扩写，不解释，不加前后缀，只输出中文结果。"
                    ),
                },
                {"role": "user", "content": normalized},
            ],
            provider=provider,
            model=model,
            temperature=0.0,
            max_tokens=min(2048, max(256, len(normalized) * 2)),
        )
    except Exception as exc:
        logger.warning(
            "event_flow mimo translation failed",
            exc_info=True,
            extra={"field": field, "provider": provider, "model": model},
        )
        last_error = str(exc)
        if "429" in last_error or "Too many requests" in last_error:
            _disable_translation_temporarily(provider, model)
        _TRANSLATION_CACHE[cache_key] = normalized
        return normalized

    translated = _normalize_text(response.content)
    if not translated or _should_translate_english(translated):
        return normalized
    _TRANSLATION_CACHE[cache_key] = translated
    return translated


def _translate_long_english(text: Any, *, field: str) -> str:
    return _translate_english(text, field=field)


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
        "gold_macro_overview": None,
        "gold_mainlines": None,
        "source_refs": [],
        "warnings": [],
    }

    daily_analysis_followups = get_daily_analysis_followups_latest(project_root=_PROJECT_ROOT)
    if daily_analysis_followups:
        result["daily_analysis_followups"] = daily_analysis_followups

    daily_analysis_triggers = get_daily_analysis_triggers_latest(project_root=_PROJECT_ROOT)
    daily_analysis_triggers = _merge_key_flash_triggers(daily_analysis_triggers)
    if daily_analysis_triggers:
        result["daily_analysis_triggers"] = daily_analysis_triggers

    # Event Flow 暂不注入金十文章/报告摘要，避免报告中心内容在事件流每页重复展示。
    article_briefs = None

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
        result["warnings"].extend(str(warning) for warning in brief.get("warnings", []) if warning)
        return _finalize_event_flow_result(result)

    if brief:
        result["warnings"].append("daily_market_brief is older than the latest Jin10 follow-up read model.")
        _apply_latest_followup_read_model(
            result,
            daily_analysis_triggers=daily_analysis_triggers,
            article_briefs=article_briefs,
        )
        return _finalize_event_flow_result(result)

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

    if not result["events"] and not daily_analysis_triggers:
        result["warnings"].append("Jin10 快讯/日历数据当前不可用，页面展示 mock 数据。")

    return _finalize_event_flow_result(result)


def build_event_flow_briefs() -> dict[str, Any]:
    """构建当日快讯只读 read model。"""
    overview = build_event_flow_overview()
    brief_events = [event for event in _overview_events(overview) if event.get("kind") in {"daily_analysis_trigger", "flash", "article"}]
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


def _finalize_event_flow_result(result: dict[str, Any]) -> dict[str, Any]:
    _attach_gold_mainline_read_model(result)
    preferred_ids = set()
    brief_summary = result.get("brief_summary") if isinstance(result.get("brief_summary"), dict) else {}
    market_mainline = brief_summary.get("market_mainline") if isinstance(brief_summary.get("market_mainline"), dict) else {}
    primary_event_id = str(market_mainline.get("primary_event_id") or "").strip()
    if primary_event_id:
        preferred_ids.add(primary_event_id)

    events = _overview_events(result)
    result["events"] = _dedupe_event_flow_events(events, preferred_ids=preferred_ids)
    _enrich_events_with_gold_mainline_links(result)
    if primary_event_id and not any(event.get("id") == primary_event_id for event in result["events"]):
        replacement = next(
            (
                event
                for event in result["events"]
                if primary_event_id in {str(item) for item in event.get("related_event_ids") or []}
            ),
            None,
        )
        if replacement is not None:
            market_mainline["primary_event_id"] = replacement.get("id")
    return result


def _attach_gold_mainline_read_model(result: dict[str, Any]) -> None:
    try:
        payload = get_gold_mainlines_latest(project_root=_PROJECT_ROOT)
    except Exception:
        logger.warning("failed to load gold mainline read model for event flow", exc_info=True)
        return
    if not isinstance(payload, dict) or payload.get("status") == "unavailable":
        return
    overview = payload.get("gold_macro_overview")
    mainlines = payload.get("gold_mainlines")
    if isinstance(overview, dict):
        result["gold_macro_overview"] = overview
    if isinstance(mainlines, dict):
        result["gold_mainlines"] = mainlines
    source_refs = payload.get("source_refs")
    if isinstance(source_refs, list) and source_refs:
        result["source_refs"] = _merge_source_refs(
            result.get("source_refs") if isinstance(result.get("source_refs"), list) else [],
            [
                {
                    "source_ref": f"gold_mainlines:{payload.get('date')}/{payload.get('run_id')}",
                    "label": "黄金九主线归因",
                    "status": payload.get("status") or "partial",
                    "path": payload.get("artifact_path"),
                }
            ],
        )


def _enrich_events_with_gold_mainline_links(result: dict[str, Any]) -> None:
    gold_mainlines = result.get("gold_mainlines")
    if not isinstance(gold_mainlines, dict):
        return
    event_links = gold_mainlines.get("event_links")
    if not isinstance(event_links, list):
        return
    links_by_event_id = {
        str(link.get("event_id") or ""): link
        for link in event_links
        if isinstance(link, dict) and str(link.get("event_id") or "").strip()
    }
    if not links_by_event_id:
        return
    enriched: list[dict[str, Any]] = []
    for event in _overview_events(result):
        event_id = str(event.get("id") or "")
        link = links_by_event_id.get(event_id)
        if link is None:
            enriched.append(event)
            continue
        item = dict(event)
        field_map = {
            "mainline_ids": "mainline_ids",
            "primary_mainline": "primary_mainline",
            "transmission_path_ids": "transmission_path_ids",
            "bullish_drivers": "bullish_drivers",
            "bearish_drivers": "bearish_drivers",
            "dominant_driver": "dominant_driver",
            "verification_needed": "verification_needed",
            "verification_chain": "verification_chain",
            "changed_dominant_theme": "changed_dominant_theme",
        }
        for source_field, target_field in field_map.items():
            if source_field in link:
                item[target_field] = link[source_field]
        direction_by_asset = link.get("direction_by_asset")
        if isinstance(direction_by_asset, dict):
            item["direction_by_asset"] = dict(direction_by_asset)
            item["net_effect"] = direction_by_asset.get("XAUUSD") or direction_by_asset.get("gold")
        if link.get("pricing_status"):
            item["pricing"] = link.get("pricing_status")
        if link.get("verification_status"):
            item["verification_status"] = link.get("verification_status")
        market_validation_ref = str(link.get("market_validation_ref") or "").strip()
        if market_validation_ref:
            item["market_validation_ref"] = market_validation_ref
        enriched.append(item)
    result["events"] = enriched


def _dedupe_event_flow_events(events: list[dict[str, Any]], *, preferred_ids: set[str] | None = None) -> list[dict[str, Any]]:
    preferred_ids = preferred_ids or set()
    buckets: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for event in events:
        key = _event_dedupe_key(event)
        if key not in buckets:
            buckets[key] = dict(event)
            order.append(key)
            continue
        buckets[key] = _merge_duplicate_event(buckets[key], event, preferred_ids=preferred_ids)

    return sorted(
        (buckets[key] for key in order),
        key=_event_sort_key,
        reverse=True,
    )[:50]


def _event_dedupe_key(event: dict[str, Any]) -> str:
    kind = str(event.get("kind") or "").strip()
    event_type = _normalize_event_key_text(event.get("event_type"))
    assets = "|".join(sorted(_normalize_asset_key(asset) for asset in event.get("affected_assets") or [] if asset))
    title = _normalize_event_key_text(event.get("title"))

    if kind == "calendar":
        return f"calendar:{title}:{_event_date_key(event.get('time'))}"
    if event_type:
        return f"event_type:{event_type}:assets:{assets or 'none'}"
    if title:
        return f"title:{title}"
    return f"id:{event.get('id') or _stable_event_id('event', event.get('time'), event.get('source'))}"


def _normalize_event_key_text(value: Any) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    return text[:80]


def _normalize_asset_key(value: Any) -> str:
    return str(value or "").lower().strip().replace(" ", "")


def _event_date_key(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def _merge_duplicate_event(existing: dict[str, Any], incoming: dict[str, Any], *, preferred_ids: set[str]) -> dict[str, Any]:
    if _event_rank(incoming, preferred_ids=preferred_ids) > _event_rank(existing, preferred_ids=preferred_ids):
        primary = dict(incoming)
        secondary = existing
    else:
        primary = dict(existing)
        secondary = incoming

    related_ids = _ordered_unique(
        [
            str(primary.get("id") or ""),
            *(str(item) for item in primary.get("related_event_ids") or []),
            str(secondary.get("id") or ""),
            *(str(item) for item in secondary.get("related_event_ids") or []),
        ]
    )
    source_refs = _merge_source_refs(
        primary.get("source_refs") if isinstance(primary.get("source_refs"), list) else [],
        secondary.get("source_refs") if isinstance(secondary.get("source_refs"), list) else [],
    )
    related_news_items = _merge_related_news_items(
        primary.get("related_news_items") if isinstance(primary.get("related_news_items"), list) else [],
        secondary.get("related_news_items") if isinstance(secondary.get("related_news_items"), list) else [],
    )
    affected_assets = _ordered_unique(
        [
            *(str(item) for item in primary.get("affected_assets") or [] if item),
            *(str(item) for item in secondary.get("affected_assets") or [] if item),
        ]
    )

    primary["related_event_ids"] = related_ids
    primary["duplicate_count"] = max(1, int(primary.get("duplicate_count") or 1)) + max(1, int(secondary.get("duplicate_count") or 1))
    if source_refs:
        primary["source_refs"] = source_refs
    if related_news_items:
        primary["related_news_items"] = related_news_items
    if affected_assets:
        primary["affected_assets"] = affected_assets
    for field in ("market_validation", "market_snapshot", "impact_path"):
        if field not in primary and field in secondary:
            primary[field] = secondary[field]
    return primary


def _event_rank(event: dict[str, Any], *, preferred_ids: set[str]) -> tuple[int, int, int, int, int, float]:
    return (
        1 if str(event.get("id") or "") in preferred_ids else 0,
        _risk_rank(event.get("risk_level")),
        _validation_rank(event),
        _importance_rank(event.get("importance")),
        _kind_rank(event.get("kind")),
        _event_timestamp_rank(event.get("time")),
    )


def _event_sort_key(event: dict[str, Any]) -> tuple[int, int, int, int, float]:
    return (
        _risk_rank(event.get("risk_level")),
        _validation_rank(event),
        _importance_rank(event.get("importance")),
        _kind_rank(event.get("kind")),
        _event_timestamp_rank(event.get("time")),
    )


def _validation_rank(event: dict[str, Any]) -> int:
    market_validation = event.get("market_validation")
    if isinstance(market_validation, dict) and market_validation:
        return 2
    if event.get("market_snapshot") is not None:
        return 1
    return 0


def _risk_rank(value: Any) -> int:
    normalized = str(value or "").lower()
    if normalized in {"high", "高"}:
        return 3
    if normalized in {"medium", "中"}:
        return 2
    if normalized in {"low", "低"}:
        return 1
    return 0


def _importance_rank(value: Any) -> int:
    normalized = str(value or "").lower()
    if normalized in {"高", "high", "3"}:
        return 3
    if normalized in {"中", "medium", "2"}:
        return 2
    if normalized in {"低", "low", "1"}:
        return 1
    return 0


def _kind_rank(value: Any) -> int:
    return {
        "confirmed_event": 5,
        "daily_analysis_trigger": 4,
        "candidate_event": 3,
        "unconfirmed_risk": 2,
        "jin10_article_brief": 1,
        "article": 1,
        "flash": 1,
        "calendar": 0,
    }.get(str(value or ""), 0)


def _event_timestamp_rank(value: Any) -> float:
    parsed = _parse_as_of(value)
    return parsed.timestamp() if parsed is not None else 0.0


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _merge_source_refs(*groups: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for ref in group:
            if not isinstance(ref, dict):
                continue
            key = "|".join(str(ref.get(field) or "") for field in ("source_ref", "snapshot_id", "artifact_path", "path"))
            if not key.strip("|"):
                key = json.dumps(ref, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            refs.append(dict(ref))
    return refs


def _merge_related_news_items(*groups: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            key = str(item.get("news_item_id") or item.get("source_ref") or item.get("url") or item.get("title") or "").strip()
            if not key:
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            items.append(dict(item))
    return items[:20]


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


def _date_from_timestamp(value: Any) -> str | None:
    parsed = _parse_as_of(value)
    if parsed is None:
        return None
    return parsed.date().isoformat()


def _daily_analysis_triggers_source_ref(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_ref": f"daily_analysis_triggers:{payload.get('date')}/{payload.get('run_id')}",
        "label": "日度分析触发器",
        "status": payload.get("status") or "ok",
        "path": payload.get("artifact_path"),
    }


def _article_briefs_source_ref(article_briefs: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_ref": f"jin10_article_briefs:{article_briefs.get('date')}/{article_briefs.get('run_id')}",
        "label": "金十文章简报",
        "status": article_briefs.get("status") or "ok",
        "path": article_briefs.get("artifact_path"),
    }


def _flash_cache_path() -> Any:
    return _PROJECT_ROOT / "storage" / "outputs" / "jin10" / "flash_cache.json"


def _load_key_flash_items() -> tuple[list[dict[str, Any]], str | None]:
    path = _flash_cache_path()
    if not path.exists():
        return [], None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("failed to read jin10 flash cache for event flow", exc_info=True, extra={"path": str(path)})
        return [], None
    if not isinstance(payload, dict):
        return [], None
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    return [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("is_key_event") is True
        and str(item.get("importance") or "").lower() in {"high", "高"}
    ], payload.get("generated_at")


def _flash_source_ref(item: dict[str, Any], index: int) -> dict[str, Any]:
    url = str(item.get("url") or "").strip()
    source_ref = f"jin10_flash:{_stable_event_id('key_flash', url or item.get('content') or item.get('title') or index)}"
    return {
        "source_ref": source_ref,
        "provider": "jin10_flash",
        "label": "金十重点快讯",
        "status": "ok",
        "source_url": url or None,
        "generated_at": item.get("time"),
    }


def _key_flash_trigger(item: dict[str, Any], index: int, *, generated_at: str | None) -> dict[str, Any]:
    title = str(item.get("content") or item.get("title") or "").strip()
    summary = str(item.get("summary_zh") or item.get("filter_reason") or title).strip()
    source_ref = _flash_source_ref(item, index)
    return {
        "trigger_id": source_ref["source_ref"],
        "trigger_type": "jin10_key_flash",
        "event_type": "flash_news",
        "priority": item.get("importance") or "medium",
        "status": "available",
        "source_key": "jin10_flash",
        "source_title": title,
        "evidence_text": summary,
        "source_url": item.get("url") or "",
        "created_at": item.get("time") or generated_at,
        "published_at": item.get("time") or generated_at,
        "asset_tags": item.get("signal_tags") if isinstance(item.get("signal_tags"), list) else [],
        "topic_tags": ["重点快讯"],
        "source_refs": [source_ref],
        "data_quality": {
            "origin": "jin10_flash_cache",
            "classification_provider": item.get("classification_provider"),
            "classification_model": item.get("classification_model"),
            "classification_confidence": item.get("classification_confidence"),
        },
    }


def _merge_key_flash_triggers(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    key_items, generated_at = _load_key_flash_items()
    if not key_items:
        return payload

    base = dict(payload or {})
    existing = [item for item in base.get("triggers", []) if isinstance(item, dict)] if isinstance(base.get("triggers"), list) else []
    seen = {
        str(item.get("source_url") or item.get("trigger_id") or item.get("source_title") or "").strip()
        for item in existing
    }
    key_triggers: list[dict[str, Any]] = []
    for index, item in enumerate(key_items):
        trigger = _key_flash_trigger(item, index, generated_at=generated_at)
        dedupe_key = str(trigger.get("source_url") or trigger.get("trigger_id") or trigger.get("source_title") or "").strip()
        if dedupe_key and dedupe_key in seen:
            continue
        if dedupe_key:
            seen.add(dedupe_key)
        key_triggers.append(trigger)

    triggers = existing + key_triggers
    if not triggers:
        return payload

    priority_counts: dict[str, int] = {}
    for item in triggers:
        priority = str(item.get("priority") or "normal")
        priority_counts[priority] = priority_counts.get(priority, 0) + 1

    base.update({
        "status": "available",
        "date": base.get("date") or _date_from_timestamp(generated_at),
        "run_id": base.get("run_id") or "jin10-flash-cache",
        "artifact_path": base.get("artifact_path") or "storage/outputs/jin10/flash_cache.json",
        "as_of": base.get("as_of") or generated_at,
        "rule_version": base.get("rule_version") or "jin10-key-flash-cache-v1",
        "trigger_count": len(triggers),
        "priority_counts": priority_counts,
        "source_key_counts": {
            **(base.get("source_key_counts") if isinstance(base.get("source_key_counts"), dict) else {}),
            "jin10_flash": len(key_triggers),
        },
        "triggers": triggers,
        "data_quality": {
            **(base.get("data_quality") if isinstance(base.get("data_quality"), dict) else {}),
            "key_flash_count": len(key_triggers),
            "source": "storage/outputs/jin10/flash_cache.json",
        },
    })
    return base


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
            "title": _translate_long_english(item.get("source_title") or item.get("evidence_text") or item.get("event_type") or "", field="trigger_title")[:120],
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
            "title": _translate_long_english(item.get("headline") or item.get("analysis_summary") or "", field="article_brief_title")[:120],
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
    market_mainline = dict(brief.get("market_mainline")) if isinstance(brief.get("market_mainline"), dict) else {}
    data_quality = brief.get("data_quality") if isinstance(brief.get("data_quality"), dict) else {}
    report_inputs = dict(brief.get("report_inputs")) if isinstance(brief.get("report_inputs"), dict) else {}
    for key in ("headline", "summary"):
        if key in market_mainline:
            market_mainline[key] = _translate_long_english(market_mainline.get(key), field=f"market_mainline_{key}")
    for list_key in ("news_highlights", "watchlist", "risk_points"):
        values = report_inputs.get(list_key)
        if isinstance(values, list):
            report_inputs[list_key] = [
                _translate_long_english(item, field=f"report_inputs_{list_key}") if isinstance(item, str) else item
                for item in values
            ]
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
        ("positioning", "positioning", "持仓报告"),
        ("technical_levels", "technical_levels", "点位报告"),
    ]
    for group_key, group_label, display_group in group_specs:
        raw_items = report_inputs.get(group_key)
        if not isinstance(raw_items, list):
            continue
        for raw_item in raw_items:
            title = _report_input_title(raw_item, group_key=group_key)
            if not title:
                continue
            summary = _report_input_summary(raw_item, fallback=title)
            stable_key = _stable_event_id(group_key, title, summary)
            items.append(
                {
                    "input_id": f"summary:{group_key}:{stable_key}",
                    "input_kind": "summary",
                    "group": display_group,
                    "title": _translate_long_english(title, field=f"report_input_title_{group_key}"),
                    "summary": _translate_long_english(summary, field=f"report_input_summary_{group_key}"),
                    "verification_status": _report_input_verification_status(raw_item),
                    "access_status": None,
                    "artifact_path": None,
                    "source_url": None,
                    "source_refs": _report_input_source_refs(raw_item, page_source_refs=page_source_refs),
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
                "title": _translate_long_english(followup.get("source_title") or followup.get("title") or "未命名跟进项", field="followup_title"),
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
                "title": _translate_long_english(brief.get("headline") or "未命名文章", field="article_brief_input_title"),
                "summary": _report_input_summary(brief, fallback=str(brief.get("analysis_summary") or brief.get("original_excerpt") or brief.get("headline") or "")),
                "verification_status": _string_or_none((brief.get("data_quality") or {}).get("verification_status")),
                "access_status": _string_or_none(brief.get("access_status")),
                "artifact_path": _string_or_none(article_briefs.get("artifact_path")),
                "source_url": _string_or_none(brief.get("final_url") or brief.get("source_url")),
                "source_refs": [dict(ref) for ref in brief.get("source_refs") or [] if isinstance(ref, dict)],
            }
        )

    return items


def _report_input_title(value: Any, *, group_key: str = "") -> str:
    if isinstance(value, str):
        return _translate_long_english(value.strip(), field="report_input_title")
    if not isinstance(value, dict):
        return ""
    if group_key == "positioning":
        text = _positioning_input_title(value)
        if text:
            return text
    if group_key == "technical_levels":
        text = _technical_level_input_title(value)
        if text:
            return text
    for key in ("title", "what_happened", "event_name", "summary", "event_type"):
        text = str(value.get(key) or "").strip()
        if text:
            return _translate_long_english(text, field="report_input_title")
    return ""


def _report_input_summary(value: Any, *, fallback: str) -> str:
    if isinstance(value, str):
        return _translate_long_english(value.strip() or fallback, field="report_input_summary")
    if not isinstance(value, dict):
        return fallback
    for key in ("summary", "what_happened", "evidence_text", "title", "event_name", "event_type"):
        text = str(value.get(key) or "").strip()
        if text:
            return _translate_long_english(text, field="report_input_summary")
    return _translate_long_english(fallback, field="report_input_summary")


def _report_input_verification_status(value: Any) -> str | None:
    if isinstance(value, dict):
        data_quality = value.get("data_quality")
        if isinstance(data_quality, dict):
            nested = _string_or_none(data_quality.get("verification_status"))
            if nested:
                return nested
        return _string_or_none(value.get("verification_status"))
    return None


def _report_input_source_refs(value: Any, *, page_source_refs: list[Any]) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        refs = [dict(ref) for ref in value.get("source_refs") or [] if isinstance(ref, dict)]
        if refs:
            return refs
    return [dict(ref) for ref in page_source_refs if isinstance(ref, dict)]


def _positioning_input_title(value: dict[str, Any]) -> str:
    asset = str(value.get("asset") or "").strip()
    direction = str(value.get("direction") or "").strip()
    level = str(value.get("strike_or_level") or "").strip()
    change = str(value.get("position_change") or "").strip()
    parts = [part for part in (asset, level, direction, change) if part]
    return " / ".join(parts)


def _technical_level_input_title(value: dict[str, Any]) -> str:
    symbol = str(value.get("symbol") or "").strip()
    level_type = str(value.get("level_type") or "").strip()
    price = value.get("price")
    price_range = value.get("range")
    price_text = ""
    if price is not None:
        price_text = str(price)
    elif isinstance(price_range, dict):
        low = price_range.get("low")
        high = price_range.get("high")
        if low is not None and high is not None:
            price_text = f"{low}-{high}"
    parts = [part for part in (symbol, level_type, price_text) if part]
    return " / ".join(parts)


def _followup_summary(followup: dict[str, Any]) -> str:
    for key in ("summary", "evidence_text", "headline", "title"):
        text = str(followup.get(key) or "").strip()
        if text:
            return _translate_long_english(text, field="followup_summary")
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
            event = _normalize_brief_event(item, kind="candidate_event")
            if event is not None:
                events.append(event)
    for item in brief.get("unconfirmed_risks") or []:
        if isinstance(item, dict):
            event = _normalize_brief_event(item, kind="unconfirmed_risk")
            if event is not None:
                events.append(event)
    for item in brief.get("confirmed_events") or []:
        if isinstance(item, dict):
            event = _normalize_brief_event(item, kind="confirmed_event")
            if event is not None:
                events.append(event)
    for item in brief.get("next_7d_calendar") or []:
        if isinstance(item, dict):
            events.append({
                "id": str(item.get("event_id") or _stable_event_id("calendar", item.get("event_name"), item.get("event_time"))),
                "kind": "calendar",
                "time": item.get("event_time"),
                "title": _translate_long_english(item.get("event_name") or "", field="calendar_title")[:120],
                "importance": item.get("importance") or "中",
                "pricing": "scheduled",
                "source": item.get("source") or "official_calendar",
                "verification_status": item.get("verification_status"),
            })
    return events[:50]


def _normalize_brief_event(item: dict[str, Any], *, kind: str) -> dict[str, Any] | None:
    source_refs = _filter_event_flow_source_refs(item.get("source_refs") if isinstance(item.get("source_refs"), list) else [])
    source_label = _clean_event_flow_source_label(item.get("who_said") or item.get("source") or "daily_market_brief")
    if not source_refs and source_label is None:
        return None
    event = {
        "id": str(item.get("event_id") or _stable_event_id(kind, item.get("what_happened"), item.get("event_time"))),
        "kind": kind,
        "time": item.get("event_time"),
        "title": _translate_long_english(item.get("what_happened") or item.get("event_type") or "", field=f"{kind}_title")[:120],
        "importance": _brief_importance(item),
        "pricing": item.get("pricing_status") or "unknown",
        "source": source_label or "daily_market_brief",
        "verification_status": item.get("verification_status"),
        "risk_level": item.get("risk_level"),
        "event_type": item.get("event_type"),
        "related_news_items": _related_news_items_from_refs(source_refs),
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
    )
    for field in passthrough_fields:
        if field in item:
            event[field] = item[field]
    if source_refs:
        event["source_refs"] = source_refs

    market_validation = item.get("market_validation")
    if "market_snapshot" not in event and isinstance(market_validation, dict) and "market_snapshot" in market_validation:
        event["market_snapshot"] = market_validation["market_snapshot"]
    return event


def _clean_event_flow_source_label(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return "daily_market_brief"
    parts = [
        part.strip()
        for part in re.split(r"\s*(?:\+|/|,|，|\|)\s*", text)
        if part.strip()
    ]
    kept = [part for part in parts if not _is_jinshi_text(part)]
    if kept:
        return " + ".join(_ordered_unique(kept))
    return None if _is_jinshi_text(text) else text


def _related_news_items_from_refs(source_refs: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in source_refs:
        if not isinstance(ref, dict):
            continue
        item = _news_item_from_source_ref(ref)
        if item is None:
            continue
        key = str(item.get("news_item_id") or item.get("source_ref") or item.get("url") or item.get("title") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items[:12]


def _filter_event_flow_source_refs(source_refs: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for ref in source_refs:
        if not isinstance(ref, dict):
            continue
        if _is_jinshi_source_ref(ref):
            continue
        refs.append(dict(ref))
    return refs


def _is_jinshi_source_ref(ref: dict[str, Any]) -> bool:
    text = " ".join(
        str(ref.get(field) or "")
        for field in (
            "source_ref",
            "source",
            "provider",
            "label",
            "url",
            "source_url",
            "domain",
            "raw_path",
            "parsed_path",
            "path",
        )
    ).lower()
    return _is_jinshi_text(text)


def _is_jinshi_text(text: Any) -> bool:
    normalized = str(text or "").lower()
    return "jin10" in normalized or "xnews.jin10.com" in normalized or "flash.jin10.com" in normalized or "金十" in normalized


def _news_item_from_source_ref(ref: dict[str, Any]) -> dict[str, Any] | None:
    source_ref = str(ref.get("source_ref") or "").strip()
    source = str(ref.get("source") or ref.get("provider") or "").strip()
    title = _normalize_text(ref.get("title") or ref.get("label") or ref.get("summary"))
    summary = _normalize_text(
        ref.get("summary")
        or ref.get("analysis_summary")
        or ref.get("evidence_text")
        or ref.get("filter_reason")
    )
    url = _normalize_text(ref.get("url") or ref.get("source_url"))
    raw_path = _normalize_text(ref.get("raw_path"))
    parsed_path = _normalize_text(ref.get("parsed_path"))
    if not any((source_ref, source, title, url, raw_path, parsed_path)):
        return None
    published_at = _normalize_text(ref.get("published_at") or ref.get("event_time") or ref.get("as_of"))
    source_type = _normalize_text(ref.get("source_type") or ref.get("provider_role"))
    importance = _string_or_none(ref.get("importance") or ref.get("priority") or ref.get("risk_level"))
    confidence = ref.get("classification_confidence")
    try:
        normalized_confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        normalized_confidence = None
    return {
        "news_item_id": source_ref or _stable_event_id("news_item", title, url, published_at),
        "source_ref": source_ref or None,
        "source": source or "unknown",
        "source_label": _news_source_label(source or source_ref),
        "source_type": source_type or None,
        "title": _translate_long_english(title, field="related_news_title")[:180] if title else "",
        "summary": _translate_long_english(summary, field="related_news_summary")[:240] if summary else None,
        "importance": importance,
        "confidence": normalized_confidence,
        "url": url or None,
        "domain": _normalize_text(ref.get("domain")) or None,
        "published_at": published_at or None,
        "raw_path": raw_path or None,
        "parsed_path": parsed_path or None,
        "status": _normalize_text(ref.get("status")) or "ok",
        "evaluation_role": "event_evidence",
    }


def _news_source_label(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if "jin10_feishu" in normalized:
        return "金十飞书快讯"
    if "jin10" in normalized:
        return "金十"
    if "reuters_public" in normalized or "reuters" in normalized:
        return "路透快讯"
    if "google_news" in normalized:
        return "Google 新闻"
    if "gdelt" in normalized:
        return "GDELT 新闻"
    if "fed" in normalized:
        return "美联储"
    if "bls" in normalized:
        return "美国劳工统计局"
    if "bea" in normalized:
        return "美国经济分析局"
    if "eia" in normalized:
        return "美国能源信息署"
    return str(value or "来源未知")


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
            "label": "日度市场简报",
            "status": "ok",
            "path": artifact_ref.get("path"),
        })
    for ref in brief.get("source_refs") or []:
        if not isinstance(ref, dict):
            continue
        if _is_jinshi_source_ref(ref):
            continue
        refs.append({
            "source_ref": str(ref.get("source_ref") or ref.get("path") or ref.get("source") or "daily_market_brief.source"),
            "label": _translate_long_english(ref.get("label") or ref.get("source") or ref.get("asset_type") or "source_ref", field="brief_source_ref_label"),
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
            "title": _translate_long_english(f.get("content") or f.get("title", ""), field="flash_title")[:120],
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
            "title": _translate_long_english(item.get("title") or item.get("name", ""), field="jin10_calendar_title")[:120],
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
            "title": _translate_long_english(a.get("title") or a.get("name", ""), field="jin10_article_title")[:120],
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
