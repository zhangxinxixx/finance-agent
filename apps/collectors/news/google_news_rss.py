from __future__ import annotations

import html
import re
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from apps.collectors.news.base import (
    NewsCollectionResult,
    RawNewsItem,
    archive_news_payload,
    stable_news_item_id,
    utc_now_iso,
)

GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
GOOGLE_NEWS_SOURCE_NAME = "Google News RSS"
GOOGLE_NEWS_QUERIES: dict[str, str] = {
    "gold_macro": "gold XAU Treasury yields Fed dollar",
    "middle_east": "Iran Israel Hormuz ceasefire sanctions oil tanker",
    "oil": "Brent WTI OPEC EIA crude stocks gasoline stocks",
    "fx_yen": "DXY USDJPY yen intervention BOJ Ueda",
    "silver": "silver solar demand silver deficit COMEX silver",
}


def collect_google_news_rss(
    *,
    retrieved_date: str,
    storage_root: Path,
    query_groups: dict[str, str] | None = None,
    max_items_per_group: int = 30,
    request_timeout: float | httpx.Timeout | None = None,
    request_proxy: str | None = None,
    trust_env: bool = True,
    client: Any | None = None,
) -> NewsCollectionResult:
    queries = query_groups or GOOGLE_NEWS_QUERIES
    items: list[RawNewsItem] = []
    source_refs: list[dict[str, Any]] = []
    unavailable_feeds: list[str] = []
    warnings: list[str] = []

    if client is not None:
        for query_group, query in queries.items():
            _collect_single_query_group(
                query_group=query_group,
                query=query,
                max_items=max_items_per_group,
                retrieved_date=retrieved_date,
                storage_root=storage_root,
                client=client,
                items=items,
                source_refs=source_refs,
                unavailable_feeds=unavailable_feeds,
                warnings=warnings,
            )
    else:
        client_timeout = 20.0 if request_timeout is None else request_timeout
        client_kwargs: dict[str, Any] = {
            "timeout": client_timeout,
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
                    max_items=max_items_per_group,
                    retrieved_date=retrieved_date,
                    storage_root=storage_root,
                    client=http_client,
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
        source_key="google_news_rss",
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
    max_items: int,
    retrieved_date: str,
    storage_root: Path,
    client: Any,
    items: list[RawNewsItem],
    source_refs: list[dict[str, Any]],
    unavailable_feeds: list[str],
    warnings: list[str],
) -> None:
    params: dict[str, object] = {
        "q": query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    try:
        response = client.get(GOOGLE_NEWS_RSS_URL, params=params)
        response.raise_for_status()
        feed_text = response.text
    except Exception as exc:
        status, reason_code, reason = _classify_request_exception(exc)
        unavailable_feeds.append(query_group)
        warning = f"google_news_rss:{query_group} {reason_code}: {reason}"
        source_refs.append(_build_source_ref(
            query_group=query_group,
            status=status,
            reason=reason,
            reason_code=reason_code,
            warning=warning,
        ))
        warnings.append(warning)
        return

    fetched_at = utc_now_iso()
    raw_path = archive_news_payload(
        storage_root=storage_root,
        layer="raw",
        source_key="google_news_rss",
        retrieved_date=retrieved_date,
        name=query_group,
        payload={
            "source_key": "google_news_rss",
            "source_url": GOOGLE_NEWS_RSS_URL,
            "query_group": query_group,
            "query": query,
            "params": params,
            "fetched_at": fetched_at,
            "xml": feed_text,
        },
    )
    try:
        parsed_items = _parse_google_news_items(
            feed_text=feed_text,
            query_group=query_group,
            query=query,
            fetched_at=fetched_at,
            max_items=max_items,
        )
    except ElementTree.ParseError as exc:
        unavailable_feeds.append(query_group)
        warning = f"google_news_rss:{query_group} invalid_payload: {type(exc).__name__}: {exc}"
        source_refs.append(_build_source_ref(
            query_group=query_group,
            status="unavailable",
            reason=f"{type(exc).__name__}: {exc}",
            reason_code="invalid_payload",
            warning=warning,
            raw_path=raw_path,
        ))
        warnings.append(warning)
        return
    parsed_path = archive_news_payload(
        storage_root=storage_root,
        layer="parsed",
        source_key="google_news_rss",
        retrieved_date=retrieved_date,
        name=query_group,
        payload={
            "source_key": "google_news_rss",
            "source_url": GOOGLE_NEWS_RSS_URL,
            "query_group": query_group,
            "query": query,
            "fetched_at": fetched_at,
            "items": [item.to_dict() for item in parsed_items],
        },
    )
    for item in parsed_items:
        items.append(RawNewsItem(**{**item.to_dict(), "raw_path": raw_path, "parsed_path": parsed_path}))
    warning = None if parsed_items else f"google_news_rss:{query_group} no_items: Google News RSS query returned no candidate articles"
    source_refs.append(_build_source_ref(
        query_group=query_group,
        status="available" if parsed_items else "empty",
        reason=None if parsed_items else "Google News RSS query returned no candidate articles",
        reason_code=None if parsed_items else "no_items",
        warning=warning,
        raw_path=raw_path,
        parsed_path=parsed_path,
    ))
    if warning:
        warnings.append(warning)


def _parse_google_news_items(
    *,
    feed_text: str,
    query_group: str,
    query: str,
    fetched_at: str,
    max_items: int,
) -> list[RawNewsItem]:
    root = ElementTree.fromstring(feed_text)
    result: list[RawNewsItem] = []
    for node in root.findall(".//item")[:max_items]:
        title = _node_text(node, "title")
        url = _node_text(node, "link")
        if not title or not url:
            continue
        publisher, publisher_url = _source_node(node)
        domain_url = publisher_url or url
        duplicate_key = stable_news_item_id(source_key="google_news_rss", title=title, url=url)
        result.append(RawNewsItem(
            source_key="google_news_rss",
            source_name=GOOGLE_NEWS_SOURCE_NAME,
            source_type="aggregator",
            feed_key=query_group,
            title=title,
            url=url,
            domain=urlparse(domain_url).netloc.lower().removeprefix("www."),
            published_at=_parse_datetime(_node_text(node, "pubDate")),
            fetched_at=fetched_at,
            summary=_clean_summary(_node_text(node, "description")),
            source_country="US",
            source_language="en",
            event_type=_classify_google_news_candidate(query_group=query_group, title=title),
            verification_status="single_source",
            duplicate_key=duplicate_key,
            raw_payload={
                "query_group": query_group,
                "query": query,
                "publisher": publisher or None,
                "publisher_url": publisher_url or None,
            },
        ))
    return result


def _node_text(node: ElementTree.Element, tag: str) -> str:
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _source_node(node: ElementTree.Element) -> tuple[str, str]:
    child = node.find("source")
    if child is None:
        return "", ""
    return (child.text or "").strip(), (child.attrib.get("url") or "").strip()


def _clean_summary(value: str) -> str | None:
    if not value:
        return None
    without_tags = re.sub(r"<[^>]+>", " ", value)
    normalized = re.sub(r"\s+", " ", html.unescape(without_tags)).strip()
    return normalized or None


def _parse_datetime(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _classify_google_news_candidate(*, query_group: str, title: str) -> str:
    normalized = f"{query_group} {title}".lower()
    if "hormuz" in normalized or "iran" in normalized or "israel" in normalized or "sanction" in normalized:
        return "middle_east_escalation"
    if "brent" in normalized or "wti" in normalized or "opec" in normalized or "oil" in normalized:
        return "oil_supply_shock"
    if "silver" in normalized:
        return "silver_industrial_demand"
    if "gold" in normalized or "xau" in normalized:
        return "gold_market_narrative"
    if "rate cut" in normalized or "dovish" in normalized:
        return "fed_dovish"
    if "federal reserve" in normalized or "fomc" in normalized or "fed" in normalized or "inflation" in normalized:
        return "fed_hawkish"
    if "usdjpy" in normalized or "yen intervention" in normalized or "boj" in normalized:
        return "yen_intervention_risk"
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
        "source_ref": f"google_news_rss:{query_group}",
        "source": "google_news_rss",
        "query_group": query_group,
        "source_url": GOOGLE_NEWS_RSS_URL,
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
            return ("rate_limited", "rate_limited", f"HTTP 429 from {GOOGLE_NEWS_RSS_URL}")
        return ("unavailable", f"http_{status_code}", f"HTTP {status_code} from {GOOGLE_NEWS_RSS_URL}")
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ProxyError, httpx.NetworkError)):
        return ("network_blocked", "network_blocked", f"{type(exc).__name__}: {exc}")
    return ("unavailable", "request_failed", f"{type(exc).__name__}: {exc}")
