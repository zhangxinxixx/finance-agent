from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.collectors.news.base import RawNewsItem

SOURCE_RELIABILITY: dict[str, float] = {
    "official": 0.95,
    "wire": 0.85,
    "wire_public_candidate": 0.78,
    "aggregator": 0.55,
    "supplemental": 0.60,
    "local_media": 0.50,
}

EVENT_PRIORITY: dict[str, int] = {
    "fomc_statement": 100,
    "inflation_release": 98,
    "labor_release": 96,
    "pce_release": 96,
    "gdp_release": 90,
    "hormuz_risk": 88,
    "middle_east_escalation": 86,
    "energy_inventory_release": 82,
    "oil_supply_shock": 80,
    "fed_hawkish": 78,
    "fed_dovish": 78,
    "gold_fund_flow": 72,
    "macro_watchlist": 70,
    "gold_market_narrative": 65,
    "key_level_watchlist": 60,
    "market_news_candidate": 10,
}


@dataclass(frozen=True)
class StandardNewsItem:
    news_item_id: str
    source_key: str
    source_name: str
    source_type: str
    feed_key: str
    title: str
    normalized_title: str
    url: str
    domain: str
    published_at: str | None
    fetched_at: str
    language: str | None = None
    summary: str | None = None
    event_type: str | None = None
    verification_status: str = "single_source"
    duplicate_key: str = ""
    raw_path: str | None = None
    parsed_path: str | None = None
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EventCandidate:
    event_id: str
    primary_news_item_id: str
    related_news_item_ids: list[str]
    event_time: str | None
    event_type: str
    event_status: str
    asset_tags: list[str]
    region_tags: list[str]
    entities: list[str]
    topic_tags: list[str]
    direction: str
    confidence: float
    verification_status: str
    need_verification: bool
    evidence_text: str
    source_refs: list[dict[str, Any]]
    duplicate_group: str
    source_count: int
    data_quality: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EventCandidateBundle:
    as_of: str
    raw_news_items: list[StandardNewsItem]
    event_candidates: list[EventCandidate]
    top_market_events: list[EventCandidate]
    source_mix: dict[str, int]
    data_quality: dict[str, Any]
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "raw_news_items": [item.to_dict() for item in self.raw_news_items],
            "event_candidates": [event.to_dict() for event in self.event_candidates],
            "top_market_events": [event.to_dict() for event in self.top_market_events],
            "source_mix": self.source_mix,
            "data_quality": self.data_quality,
            "source_refs": self.source_refs,
            "warnings": self.warnings,
        }


def build_event_candidates(
    items: list[RawNewsItem | dict[str, Any]],
    *,
    as_of: str,
    source_refs: list[dict[str, Any]] | None = None,
) -> EventCandidateBundle:
    standard_items = [_standardize_item(item) for item in items]
    standard_items = _dedupe_raw_items(standard_items)
    grouped = _group_items(standard_items)
    event_candidates = [_build_event_candidate(group_items) for group_items in grouped.values()]
    event_candidates = sorted(event_candidates, key=_event_sort_key, reverse=True)
    top_market_events = [event for event in event_candidates if _can_enter_top_market_events(event)]
    source_mix = _source_mix(standard_items)
    data_quality = {
        "raw_news_item_count": len(standard_items),
        "event_candidate_count": len(event_candidates),
        "top_market_event_count": len(top_market_events),
        "single_source_count": sum(1 for event in event_candidates if event.verification_status == "single_source"),
        "multi_source_count": sum(1 for event in event_candidates if event.verification_status == "multi_source"),
        "official_confirmed_count": sum(1 for event in event_candidates if event.verification_status == "official_confirmed"),
        "unverified_count": sum(1 for event in event_candidates if event.verification_status == "unverified"),
    }
    return EventCandidateBundle(
        as_of=as_of,
        raw_news_items=standard_items,
        event_candidates=event_candidates,
        top_market_events=top_market_events,
        source_mix=source_mix,
        data_quality=data_quality,
        source_refs=list(source_refs or []),
    )


def archive_event_candidates(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    bundle: EventCandidateBundle,
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "event_candidates.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def _standardize_item(item: RawNewsItem | dict[str, Any]) -> StandardNewsItem:
    raw = item.to_dict() if isinstance(item, RawNewsItem) else dict(item)
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "").strip()
    source_key = str(raw.get("source_key") or "unknown")
    news_item_id = raw.get("duplicate_key") or _stable_item_id(
        source_key=source_key,
        title=title,
        url=url,
        published_at=raw.get("published_at"),
    )
    raw_payload = dict(raw.get("raw_payload") or {})
    source_refs = [{
        "source_ref": news_item_id,
        "source": source_key,
        "source_type": raw.get("source_type"),
        "title": title,
        "url": url,
        "domain": raw.get("domain"),
        "published_at": raw.get("published_at"),
        "raw_path": raw.get("raw_path"),
        "parsed_path": raw.get("parsed_path"),
    }]
    for ref in raw_payload.get("source_refs") or []:
        if isinstance(ref, dict):
            source_refs.append(dict(ref))
    return StandardNewsItem(
        news_item_id=str(news_item_id),
        source_key=source_key,
        source_name=str(raw.get("source_name") or source_key),
        source_type=str(raw.get("source_type") or "other"),
        feed_key=str(raw.get("feed_key") or ""),
        title=title,
        normalized_title=_normalize_title(title),
        url=url,
        domain=str(raw.get("domain") or ""),
        published_at=raw.get("published_at"),
        fetched_at=str(raw.get("fetched_at") or ""),
        language=raw.get("source_language") or raw.get("language"),
        summary=raw.get("summary"),
        event_type=raw.get("event_type"),
        verification_status=str(raw.get("verification_status") or "single_source"),
        duplicate_key=str(raw.get("duplicate_key") or news_item_id),
        raw_path=raw.get("raw_path"),
        parsed_path=raw.get("parsed_path"),
        source_refs=source_refs,
        raw_payload=raw_payload,
    )


def _dedupe_raw_items(items: list[StandardNewsItem]) -> list[StandardNewsItem]:
    seen: set[str] = set()
    result: list[StandardNewsItem] = []
    for item in items:
        key = item.news_item_id
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _group_items(items: list[StandardNewsItem]) -> dict[str, list[StandardNewsItem]]:
    grouped: dict[str, list[StandardNewsItem]] = {}
    for item in items:
        event_type = _canonical_event_type(item.event_type)
        time_bucket = _time_bucket(item.published_at)
        group_key = _duplicate_group(event_type=event_type, normalized_title=item.normalized_title, time_bucket=time_bucket)
        grouped.setdefault(group_key, []).append(item)
    return grouped


def _build_event_candidate(items: list[StandardNewsItem]) -> EventCandidate:
    canonical_type = _select_event_type(items)
    duplicate_group = _duplicate_group(
        event_type=canonical_type,
        normalized_title=items[0].normalized_title,
        time_bucket=_time_bucket(items[0].published_at),
    )
    primary = _select_primary_item(items)
    verification = _verification_profile(items)
    verification_status = str(verification["status"])
    source_refs = _merge_source_refs(items)
    data_quality = {
        "source_reliability": _source_reliability(primary.source_type),
        "source_keys": sorted({item.source_key for item in items}),
        "domains": sorted({item.domain for item in items if item.domain}),
        "authorized_wire": any(bool(item.raw_payload.get("authorized_wire")) for item in items),
        "has_official_source": any(item.source_type == "official" for item in items),
        "verification_reason": verification["reason"],
        "independent_source_count": verification["independent_source_count"],
        "independent_domain_count": verification["independent_domain_count"],
        "authoritative_source_count": verification["authoritative_source_count"],
    }
    return EventCandidate(
        event_id=_event_id(event_type=canonical_type, duplicate_group=duplicate_group),
        primary_news_item_id=primary.news_item_id,
        related_news_item_ids=sorted(item.news_item_id for item in items),
        event_time=_event_time(items),
        event_type=canonical_type,
        event_status=_event_status(canonical_type),
        asset_tags=_asset_tags(canonical_type),
        region_tags=_region_tags(items, canonical_type),
        entities=_entities(items),
        topic_tags=_topic_tags(canonical_type),
        direction=_direction(canonical_type),
        confidence=_confidence(verification_status=verification_status, primary=primary, event_type=canonical_type),
        verification_status=verification_status,
        need_verification=verification_status != "official_confirmed",
        evidence_text=primary.summary or primary.title,
        source_refs=source_refs,
        duplicate_group=duplicate_group,
        source_count=len({(item.source_key, item.domain) for item in items}),
        data_quality=data_quality,
    )


def _select_event_type(items: list[StandardNewsItem]) -> str:
    candidates = [_canonical_event_type(item.event_type) for item in items]
    return sorted(candidates, key=lambda event_type: EVENT_PRIORITY.get(event_type, 0), reverse=True)[0]


def _canonical_event_type(event_type: str | None) -> str:
    if event_type == "middle_east_escalation":
        return "hormuz_risk"
    if event_type in {"fed_hawkish", "fed_dovish"}:
        return event_type
    return event_type or "market_news_candidate"


def _select_primary_item(items: list[StandardNewsItem]) -> StandardNewsItem:
    return sorted(
        items,
        key=lambda item: (
            _source_reliability(item.source_type),
            EVENT_PRIORITY.get(_canonical_event_type(item.event_type), 0),
            item.published_at or "",
        ),
        reverse=True,
    )[0]


def _verification_profile(items: list[StandardNewsItem]) -> dict[str, Any]:
    unique_sources = {(item.source_key, item.domain) for item in items}
    unique_domains = {
        item.domain.strip().lower()
        for item in items
        if item.domain and item.domain.strip()
    }
    authoritative_source_count = sum(1 for item in items if _is_authoritative_source(item))
    if any(item.source_type == "official" or item.verification_status == "official_confirmed" for item in items):
        return {
            "status": "official_confirmed",
            "reason": "official_source_present",
            "independent_source_count": len(unique_sources),
            "independent_domain_count": len(unique_domains),
            "authoritative_source_count": authoritative_source_count,
        }
    if all(item.source_type == "local_media" for item in items):
        return {
            "status": "unverified",
            "reason": "local_media_only",
            "independent_source_count": len(unique_sources),
            "independent_domain_count": len(unique_domains),
            "authoritative_source_count": authoritative_source_count,
        }
    if len(unique_sources) >= 2 and len(unique_domains) >= 2:
        if authoritative_source_count >= 1:
            return {
                "status": "multi_source",
                "reason": "cross_domain_with_authoritative_candidate",
                "independent_source_count": len(unique_sources),
                "independent_domain_count": len(unique_domains),
                "authoritative_source_count": authoritative_source_count,
            }
        if len(unique_sources) >= 3:
            return {
                "status": "multi_source",
                "reason": "three_independent_sources",
                "independent_source_count": len(unique_sources),
                "independent_domain_count": len(unique_domains),
                "authoritative_source_count": authoritative_source_count,
            }
        return {
            "status": "single_source",
            "reason": "cross_domain_but_low_trust_only",
            "independent_source_count": len(unique_sources),
            "independent_domain_count": len(unique_domains),
            "authoritative_source_count": authoritative_source_count,
        }
    if len(unique_sources) >= 2:
        return {
            "status": "single_source",
            "reason": "same_domain_reposts",
            "independent_source_count": len(unique_sources),
            "independent_domain_count": len(unique_domains),
            "authoritative_source_count": authoritative_source_count,
        }
    return {
        "status": "single_source",
        "reason": "single_independent_source",
        "independent_source_count": len(unique_sources),
        "independent_domain_count": len(unique_domains),
        "authoritative_source_count": authoritative_source_count,
    }


def _is_authoritative_source(item: StandardNewsItem) -> bool:
    if item.source_type in {"wire", "wire_public_candidate"}:
        return True
    return bool(item.raw_payload.get("authorized_wire"))


def _merge_source_refs(items: list[StandardNewsItem]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        for ref in item.source_refs:
            key = json.dumps(ref, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def _normalize_title(title: str) -> str:
    normalized = title.lower()
    normalized = re.sub(r"https?://\S+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", normalized)
    normalized = re.sub(r"\b(reuters|google news|breaking|update)\b", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _time_bucket(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return parsed.isoformat()


def _duplicate_group(*, event_type: str, normalized_title: str, time_bucket: str) -> str:
    digest = hashlib.sha256(f"{event_type}|{normalized_title}|{time_bucket}".encode("utf-8")).hexdigest()[:16]
    return f"dupe:{event_type}:{digest}"


def _event_id(*, event_type: str, duplicate_group: str) -> str:
    return f"event:{event_type}:{duplicate_group.rsplit(':', 1)[-1]}"


def _stable_item_id(*, source_key: str, title: str, url: str, published_at: object) -> str:
    digest = hashlib.sha256(f"{source_key}|{url.lower()}|{title.lower()}|{published_at}".encode("utf-8")).hexdigest()[:24]
    return f"news:{source_key}:{digest}"


def _event_time(items: list[StandardNewsItem]) -> str | None:
    times = sorted(item.published_at for item in items if item.published_at)
    return times[0] if times else None


def _event_status(event_type: str) -> str:
    if event_type in {"inflation_release", "labor_release", "pce_release", "gdp_release", "energy_inventory_release"}:
        return "scheduled"
    return "developing"


def _asset_tags(event_type: str) -> list[str]:
    if event_type in {"fomc_statement", "fed_speech", "fed_hawkish", "fed_dovish", "inflation_release", "labor_release", "pce_release", "gdp_release"}:
        return ["XAUUSD", "DXY", "US02Y", "US10Y"]
    if event_type in {"hormuz_risk", "middle_east_escalation", "oil_supply_shock"}:
        return ["XAUUSD", "WTI", "Brent", "DXY"]
    if event_type == "energy_inventory_release":
        return ["WTI", "Brent", "XAUUSD", "US10Y"]
    if event_type in {"gold_fund_flow", "gold_market_narrative", "key_level_watchlist"}:
        return ["XAUUSD"]
    if event_type == "macro_watchlist":
        return ["XAUUSD", "DXY", "US02Y", "US10Y"]
    if event_type == "yen_intervention_risk":
        return ["DXY", "USDJPY", "XAUUSD"]
    if event_type == "silver_industrial_demand":
        return ["XAGUSD", "XAUUSD"]
    return ["XAUUSD"]


def _region_tags(items: list[StandardNewsItem], event_type: str) -> list[str]:
    joined = " ".join(item.title for item in items).lower()
    regions: set[str] = set()
    if event_type in {"hormuz_risk", "middle_east_escalation", "oil_supply_shock"} or any(token in joined for token in ("iran", "israel", "hormuz", "red sea")):
        regions.add("Middle East")
    if event_type in {"fomc_statement", "fed_speech", "fed_hawkish", "fed_dovish", "inflation_release", "labor_release", "pce_release", "gdp_release"}:
        regions.add("US")
    if event_type == "yen_intervention_risk":
        regions.add("Japan")
    return sorted(regions)


def _entities(items: list[StandardNewsItem]) -> list[str]:
    joined = " ".join(item.title for item in items).lower()
    mapping = {
        "Iran": ("iran",),
        "Israel": ("israel",),
        "Strait of Hormuz": ("hormuz",),
        "Federal Reserve": ("federal reserve", "fomc", "fed "),
        "BOJ": ("boj",),
        "OPEC": ("opec",),
        "EIA": ("eia",),
        "Gold ETF": ("etf", "gold etf", "黄金etf"),
        "Silver": ("silver", "白银"),
    }
    return [entity for entity, markers in mapping.items() if any(marker in joined for marker in markers)]


def _topic_tags(event_type: str) -> list[str]:
    if event_type in {"inflation_release", "pce_release"}:
        return ["inflation", "macro", "monetary_policy"]
    if event_type in {"labor_release"}:
        return ["labor", "macro", "monetary_policy"]
    if event_type in {"fomc_statement", "fed_speech", "fed_hawkish", "fed_dovish"}:
        return ["monetary_policy", "rates"]
    if event_type == "macro_watchlist":
        return ["macro", "watchlist", "external_opinion"]
    if event_type == "gold_fund_flow":
        return ["gold", "fund_flow", "external_opinion"]
    if event_type in {"gold_market_narrative", "key_level_watchlist"}:
        return ["gold", "market_view", "external_opinion"]
    if event_type in {"hormuz_risk", "middle_east_escalation"}:
        return ["geopolitical", "energy", "shipping"]
    if event_type in {"oil_supply_shock", "energy_inventory_release"}:
        return ["energy", "inflation"]
    if event_type == "yen_intervention_risk":
        return ["fx", "intervention"]
    if event_type == "silver_industrial_demand":
        return ["silver", "industrial_demand"]
    return ["market_news"]


def _direction(event_type: str) -> str:
    if event_type in {"inflation_release", "labor_release", "fed_hawkish"}:
        return "neutral"
    if event_type in {"hormuz_risk", "middle_east_escalation", "oil_supply_shock"}:
        return "mixed"
    if event_type == "fed_dovish":
        return "bullish_gold"
    return "neutral"


def _confidence(*, verification_status: str, primary: StandardNewsItem, event_type: str) -> float:
    base = _source_reliability(primary.source_type)
    if verification_status == "official_confirmed":
        base += 0.10
    elif verification_status == "multi_source":
        base += 0.06
    elif verification_status == "single_source":
        base -= 0.12
    elif verification_status == "unverified":
        base -= 0.20
    if event_type in EVENT_PRIORITY and "XAUUSD" in _asset_tags(event_type):
        base += 0.04
    return round(max(0.0, min(base, 0.95)), 2)


def _source_reliability(source_type: str) -> float:
    return SOURCE_RELIABILITY.get(source_type, 0.45)


def _can_enter_top_market_events(event: EventCandidate) -> bool:
    if "XAUUSD" not in event.asset_tags:
        return False
    if event.verification_status == "official_confirmed":
        return True
    return event.verification_status == "multi_source" and event.confidence >= 0.60


def _event_sort_key(event: EventCandidate) -> tuple[float, int, str]:
    return (
        event.confidence,
        EVENT_PRIORITY.get(event.event_type, 0),
        event.event_time or "",
    )


def _source_mix(items: list[StandardNewsItem]) -> dict[str, int]:
    result = {
        "official": 0,
        "wire": 0,
        "wire_public_candidate": 0,
        "aggregator": 0,
        "supplemental": 0,
        "other": 0,
    }
    for item in items:
        if item.source_type in result:
            result[item.source_type] += 1
        else:
            result["other"] += 1
    return result
