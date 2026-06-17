from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from apps.collectors.news.base import (
    NewsCollectionResult,
    RawNewsItem,
    archive_news_payload,
    stable_news_item_id,
    utc_now_iso,
)

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_SOURCE_NAME = "GDELT DOC 2.0"
GDELT_DOC_QUERIES: dict[str, str] = {
    "middle_east_hormuz": '(Iran OR Israel) (Hormuz OR ceasefire OR "nuclear deal" OR sanctions)',
    "oil_supply": '(Brent OR WTI OR "oil supply" OR OPEC OR "shipping disruption")',
    "fed_inflation": '("Federal Reserve" OR Fed OR FOMC) ("rate hike" OR "rate cut" OR inflation OR PCE OR CPI)',
    "gold_yields": '(gold OR XAU OR "COMEX gold") ("Treasury yields" OR dollar OR DXY OR "real yields")',
    "yen_intervention": '(USDJPY OR "USD/JPY" OR "yen intervention" OR BOJ OR "Bank of Japan" OR "Japan Ministry of Finance")',
}


def collect_gdelt_docs(
    *,
    retrieved_date: str,
    storage_root: Path,
    query_groups: dict[str, str] | None = None,
    timespan: str = "12h",
    max_items_per_group: int = 50,
    request_timeout: float | None = None,
    request_proxy: str | None = None,
    trust_env: bool = True,
    rate_limit_cooldown_seconds: int = 900,
    now: datetime | None = None,
    client: Any | None = None,
) -> NewsCollectionResult:
    queries = query_groups or GDELT_DOC_QUERIES
    items: list[RawNewsItem] = []
    source_refs: list[dict[str, Any]] = []
    unavailable_feeds: list[str] = []
    warnings: list[str] = []
    collected_at = _normalize_now(now)

    if client is not None:
        for query_group, query in queries.items():
            _collect_single_query_group(
                query_group=query_group,
                query=query,
                timespan=timespan,
                max_items=max_items_per_group,
                retrieved_date=retrieved_date,
                storage_root=storage_root,
                client=client,
                rate_limit_cooldown_seconds=rate_limit_cooldown_seconds,
                now=collected_at,
                items=items,
                source_refs=source_refs,
                unavailable_feeds=unavailable_feeds,
                warnings=warnings,
            )
    else:
        timeout = 20.0 if request_timeout is None else request_timeout
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "headers": {"User-Agent": "finance-agent/0.1"},
            "trust_env": trust_env,
        }
        if request_proxy:
            client_kwargs["proxy"] = request_proxy
        with httpx.Client(**client_kwargs) as http_client:
            for query_group, query in queries.items():
                _collect_single_query_group(
                    query_group=query_group,
                    query=query,
                    timespan=timespan,
                    max_items=max_items_per_group,
                    retrieved_date=retrieved_date,
                    storage_root=storage_root,
                    client=http_client,
                    rate_limit_cooldown_seconds=rate_limit_cooldown_seconds,
                    now=collected_at,
                    items=items,
                    source_refs=source_refs,
                    unavailable_feeds=unavailable_feeds,
                    warnings=warnings,
                )

    degraded = any(str(ref.get("status") or "") != "available" for ref in source_refs if isinstance(ref, dict))
    if items and degraded:
        status = "partial"
    elif items:
        status = "success"
    else:
        status = "unavailable"
    return NewsCollectionResult(
        source_key="gdelt_news",
        status=status,
        items=items,
        source_refs=source_refs,
        unavailable_feeds=unavailable_feeds,
        warnings=warnings,
    )


def _collect_single_query_group(
    *,
    query_group: str,
    query: str,
    timespan: str,
    max_items: int,
    retrieved_date: str,
    storage_root: Path,
    client: Any,
    rate_limit_cooldown_seconds: int,
    now: datetime,
    items: list[RawNewsItem],
    source_refs: list[dict[str, Any]],
    unavailable_feeds: list[str],
    warnings: list[str],
) -> None:
    cooldown = _load_active_rate_limit_cooldown(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        query_group=query_group,
        now=now,
        rate_limit_cooldown_seconds=rate_limit_cooldown_seconds,
    )
    if cooldown is not None:
        unavailable_feeds.append(query_group)
        cooldown_until = cooldown.get("cooldown_until") or "unknown"
        reason = f"GDELT query group is in local cooldown until {cooldown_until}"
        warning = f"gdelt_news:{query_group} cooldown_active: {reason}"
        source_refs.append(_build_source_ref(
            query_group=query_group,
            status="rate_limited",
            reason=reason,
            reason_code="cooldown_active",
            warning=warning,
            parsed_path=str(cooldown.get("cooldown_path") or ""),
        ))
        warnings.append(warning)
        return

    params: dict[str, object] = {
        "query": query,
        "mode": "artlist",
        "maxrecords": max_items,
        "timespan": timespan,
        "sort": "datedesc",
        "format": "json",
    }
    try:
        response = client.get(GDELT_DOC_API, params=params)
        response.raise_for_status()
    except Exception as exc:
        status, reason_code, reason = _classify_request_exception(exc)
        cooldown_path = None
        if reason_code == "rate_limited":
            cooldown_path = _write_rate_limit_cooldown(
                storage_root=storage_root,
                retrieved_date=retrieved_date,
                query_group=query_group,
                reason=reason,
                now=now,
                rate_limit_cooldown_seconds=rate_limit_cooldown_seconds,
            )
        unavailable_feeds.append(query_group)
        warning = f"gdelt_news:{query_group} {reason_code}: {reason}"
        source_refs.append(_build_source_ref(
            query_group=query_group,
            status=status,
            reason=reason,
            reason_code=reason_code,
            warning=warning,
            parsed_path=cooldown_path,
        ))
        warnings.append(warning)
        return

    fetched_at = utc_now_iso()
    try:
        payload = response.json()
    except Exception as exc:
        unavailable_feeds.append(query_group)
        warning = f"gdelt_news:{query_group} invalid_payload: {type(exc).__name__}: {exc}"
        source_refs.append(_build_source_ref(
            query_group=query_group,
            status="unavailable",
            reason=f"{type(exc).__name__}: {exc}",
            reason_code="invalid_payload",
            warning=warning,
        ))
        warnings.append(warning)
        return

    raw_path = archive_news_payload(
        storage_root=storage_root,
        layer="raw",
        source_key="gdelt",
        retrieved_date=retrieved_date,
        name=query_group,
        payload={
            "source_key": "gdelt_news",
            "source_url": GDELT_DOC_API,
            "query_group": query_group,
            "query": query,
            "params": params,
            "fetched_at": fetched_at,
            "payload": payload,
        },
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("articles"), list):
        unavailable_feeds.append(query_group)
        reason = "GDELT payload missing list field 'articles'"
        warning = f"gdelt_news:{query_group} invalid_payload: {reason}"
        source_refs.append(_build_source_ref(
            query_group=query_group,
            status="unavailable",
            reason=reason,
            reason_code="invalid_payload",
            warning=warning,
            raw_path=raw_path,
        ))
        warnings.append(warning)
        return

    parsed_items = fetch_gdelt_doc_articles(
        payload=payload,
        query_group=query_group,
        query=query,
        fetched_at=fetched_at,
        max_items=max_items,
    )
    parsed_path = archive_news_payload(
        storage_root=storage_root,
        layer="parsed",
        source_key="gdelt",
        retrieved_date=retrieved_date,
        name=query_group,
        payload={
            "source_key": "gdelt_news",
            "source_url": GDELT_DOC_API,
            "query_group": query_group,
            "query": query,
            "fetched_at": fetched_at,
            "items": [item.to_dict() for item in parsed_items],
        },
    )
    for item in parsed_items:
        items.append(RawNewsItem(**{**item.to_dict(), "raw_path": raw_path, "parsed_path": parsed_path}))
    warning = None if parsed_items else f"gdelt_news:{query_group} no_items: GDELT query returned no candidate articles"
    source_refs.append(_build_source_ref(
        query_group=query_group,
        status="available" if parsed_items else "empty",
        reason=None if parsed_items else "GDELT query returned no candidate articles",
        reason_code=None if parsed_items else "no_items",
        warning=warning,
        raw_path=raw_path,
        parsed_path=parsed_path,
    ))
    if warning:
        warnings.append(warning)


def fetch_gdelt_doc_articles(
    *,
    payload: dict[str, Any],
    query_group: str,
    query: str,
    fetched_at: str,
    max_items: int,
) -> list[RawNewsItem]:
    articles = payload.get("articles", [])
    if not isinstance(articles, list):
        return []

    result: list[RawNewsItem] = []
    for article in articles[:max_items]:
        if not isinstance(article, dict):
            continue
        title = _clean_text(article.get("title"))
        url = _clean_text(article.get("url"))
        if not title or not url:
            continue
        if not _is_relevant_gdelt_article(query_group=query_group, title=title):
            continue
        domain = _clean_domain(article.get("domain"), url=url)
        duplicate_key = stable_news_item_id(source_key="gdelt_news", title=title, url=url)
        image_url = _clean_text(article.get("socialimage"))
        result.append(RawNewsItem(
            source_key="gdelt_news",
            source_name=GDELT_SOURCE_NAME,
            source_type="aggregator",
            feed_key=query_group,
            title=title,
            url=url,
            domain=domain,
            published_at=_parse_gdelt_datetime(_clean_text(article.get("seendate"))),
            fetched_at=fetched_at,
            summary=_clean_text(article.get("snippet")) or None,
            source_country=_clean_text(article.get("sourceCountry")) or None,
            source_language=_clean_text(article.get("language")) or None,
            event_type=_classify_gdelt_candidate(query_group=query_group, title=title),
            verification_status="single_source",
            duplicate_key=duplicate_key,
            raw_payload={
                "query_group": query_group,
                "query": query,
                "image_url": image_url or None,
                "article": article,
            },
        ))
    return result


def _is_relevant_gdelt_article(*, query_group: str, title: str) -> bool:
    normalized = title.lower()
    if query_group == "yen_intervention":
        return any(
            token in normalized
            for token in (
                "yen",
                "usdjpy",
                "usd/jpy",
                "boj",
                "bank of japan",
                "japan ministry of finance",
                "ueda",
                "carry trade",
            )
        )
    return True


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_domain(value: object, *, url: str) -> str:
    domain = _clean_text(value).lower().removeprefix("www.")
    if domain:
        return domain
    return urlparse(url).netloc.lower().removeprefix("www.")


def _parse_gdelt_datetime(value: str) -> str | None:
    if not value:
        return None
    if value.isdigit() and len(value) == 14:
        parsed = datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    if value.isdigit() and len(value) == 8:
        parsed = datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _normalize_now(value: datetime | None) -> datetime:
    now = value or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _cooldown_file_path(*, storage_root: Path, retrieved_date: str, query_group: str) -> Path:
    safe_query_group = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in query_group)
    return storage_root / "parsed" / "news" / "gdelt" / retrieved_date / f"cooldown-{safe_query_group}.json"


def _load_active_rate_limit_cooldown(
    *,
    storage_root: Path,
    retrieved_date: str,
    query_group: str,
    now: datetime,
    rate_limit_cooldown_seconds: int,
) -> dict[str, Any] | None:
    if rate_limit_cooldown_seconds <= 0:
        return None
    path = _cooldown_file_path(storage_root=storage_root, retrieved_date=retrieved_date, query_group=query_group)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cooldown_until = datetime.fromisoformat(str(payload.get("cooldown_until", "")).replace("Z", "+00:00"))
    except Exception:
        return None
    if cooldown_until.tzinfo is None:
        cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
    cooldown_until = cooldown_until.astimezone(timezone.utc)
    if now >= cooldown_until:
        return None
    payload["cooldown_path"] = path.relative_to(storage_root).as_posix()
    return payload


def _write_rate_limit_cooldown(
    *,
    storage_root: Path,
    retrieved_date: str,
    query_group: str,
    reason: str,
    now: datetime,
    rate_limit_cooldown_seconds: int,
) -> str | None:
    if rate_limit_cooldown_seconds <= 0:
        return None
    path = _cooldown_file_path(storage_root=storage_root, retrieved_date=retrieved_date, query_group=query_group)
    path.parent.mkdir(parents=True, exist_ok=True)
    cooldown_until = datetime.fromtimestamp(now.timestamp() + rate_limit_cooldown_seconds, tz=timezone.utc)
    payload = {
        "source_key": "gdelt_news",
        "query_group": query_group,
        "reason_code": "rate_limited",
        "reason": reason,
        "created_at": now.isoformat(),
        "cooldown_seconds": rate_limit_cooldown_seconds,
        "cooldown_until": cooldown_until.isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path.relative_to(storage_root).as_posix()


def _classify_gdelt_candidate(*, query_group: str, title: str) -> str:
    normalized = f"{query_group} {title}".lower()
    if "hormuz" in normalized:
        return "hormuz_risk"
    if "iran" in normalized or "israel" in normalized or "red sea" in normalized or "houthi" in normalized:
        return "middle_east_escalation"
    if "brent" in normalized or "wti" in normalized or "opec" in normalized or "oil" in normalized:
        return "oil_supply_shock"
    if "rate cut" in normalized or "dovish" in normalized:
        return "fed_dovish"
    if "federal reserve" in normalized or "fomc" in normalized or "fed" in normalized or "inflation" in normalized:
        return "fed_hawkish"
    if "usdjpy" in normalized or "yen intervention" in normalized or "boj" in normalized:
        return "yen_intervention_risk"
    if "dxy" in normalized or "dollar" in normalized:
        return "dollar_strength"
    if "gold" in normalized or "xau" in normalized:
        return "gold_market_narrative"
    return "market_news_candidate"


def _build_source_ref(
    *,
    query_group: str,
    status: str,
    reason: str | None,
    reason_code: str | None,
    warning: str | None,
    raw_path: str | None = None,
    parsed_path: str | None = None,
) -> dict[str, Any]:
    ref = {
        "source_ref": f"gdelt_news:{query_group}",
        "source": "gdelt_news",
        "query_group": query_group,
        "source_url": GDELT_DOC_API,
        "status": status,
    }
    if reason:
        ref["reason"] = reason
    if reason_code:
        ref["reason_code"] = reason_code
    if warning:
        ref["warning"] = warning
    if raw_path:
        ref["raw_path"] = raw_path
    if parsed_path:
        ref["parsed_path"] = parsed_path
    return ref


def _classify_request_exception(exc: Exception) -> tuple[str, str, str]:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 429:
            return ("rate_limited", "rate_limited", f"HTTP 429 from {GDELT_DOC_API}")
        return ("unavailable", f"http_{status_code}", f"HTTP {status_code} from {GDELT_DOC_API}")
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ProxyError, httpx.NetworkError)):
        return ("network_blocked", "network_blocked", f"{type(exc).__name__}: {exc}")
    return ("unavailable", "request_failed", f"{type(exc).__name__}: {exc}")
