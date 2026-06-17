from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from apps.collectors.news.base import (
    NewsCollectionResult,
    RawNewsItem,
    archive_news_payload,
    stable_news_item_id,
    utc_now_iso,
)
from apps.features.news.relevance_gate import NewsRelevanceDecision, evaluate_news_relevance
from apps.integrations.feishu.client import FeishuOpenApiClient
from apps.parsers.news.feishu_message import FeishuMessageEnvelope, looks_like_jin10_message, parse_feishu_message

SOURCE_KEY = "jin10_feishu"
SOURCE_NAME = "Jin10 Feishu Chat Pull"
INGEST_CHANNEL = "feishu_chat_pull"


def is_feishu_jin10_enabled() -> bool:
    return bool(_env_chat_id() and _env_app_id() and _env_app_secret())


def collect_feishu_jin10_messages(
    *,
    retrieved_date: str,
    storage_root: Path,
    chat_id: str | None = None,
    client: Any | None = None,
    page_size: int = 50,
    max_pages: int = 1,
) -> NewsCollectionResult:
    target_chat_id = (chat_id if chat_id is not None else _env_chat_id()).strip()
    if not target_chat_id:
        return _unavailable(reason_code="missing_chat_id", reason="FEISHU_JIN10_CHAT_ID is not configured")

    owns_client = False
    if client is None:
        app_id = _env_app_id()
        app_secret = _env_app_secret()
        if not app_id or not app_secret:
            return _unavailable(
                reason_code="missing_app_credentials",
                reason="FEISHU_NEWS_APP_ID/FEISHU_NEWS_APP_SECRET is not configured",
            )
        client = FeishuOpenApiClient(app_id=app_id, app_secret=app_secret)
        owns_client = True

    raw_paths: list[str] = []
    parsed_messages: list[dict[str, Any]] = []
    item_dicts: list[dict[str, Any]] = []
    warnings: list[str] = []
    page_token: str | None = None

    try:
        for page_index in range(max_pages):
            payload = client.list_chat_messages(chat_id=target_chat_id, page_size=page_size, page_token=page_token)
            if payload.get("code", 0) not in (0, None):
                raise RuntimeError(f"Feishu code {payload.get('code')}: {payload.get('msg') or payload}")
            raw_path = archive_news_payload(
                storage_root=storage_root,
                layer="raw",
                source_key=SOURCE_KEY,
                retrieved_date=retrieved_date,
                name=f"messages-page-{page_index + 1}",
                payload={
                    "source_key": SOURCE_KEY,
                    "chat_id": target_chat_id,
                    "page_index": page_index + 1,
                    "fetched_at": utc_now_iso(),
                    "payload": payload,
                },
            )
            raw_paths.append(raw_path)

            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            for raw_message in data.get("items") or []:
                if not isinstance(raw_message, dict):
                    continue
                envelope = parse_feishu_message(raw_message)
                decision = evaluate_news_relevance(
                    envelope.content,
                    links=envelope.links,
                    source_marker=envelope.source_marker,
                )
                parsed_messages.append({
                    "message": envelope.to_dict(),
                    "looks_like_jin10": looks_like_jin10_message(envelope),
                    "relevance_decision": decision.to_dict(),
                })
                if not looks_like_jin10_message(envelope):
                    continue
                if decision.decision not in {"candidate", "high_value"}:
                    continue
                item_dicts.append(_raw_item_dict(
                    envelope=envelope,
                    decision=decision,
                    chat_id=target_chat_id,
                    raw_path=raw_path,
                ))

            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "").strip()
            if not page_token:
                break
    except Exception as exc:
        warning = f"{SOURCE_KEY}:request_failed: {type(exc).__name__}: {exc}"
        return NewsCollectionResult(
            source_key=SOURCE_KEY,
            status="unavailable",
            items=[],
            source_refs=[_source_ref(
                chat_id=target_chat_id,
                status="unavailable",
                reason_code="request_failed",
                reason=f"{type(exc).__name__}: {exc}",
                warning=warning,
                raw_paths=raw_paths,
                parsed_path=None,
                raw_message_count=len(parsed_messages),
                accepted_item_count=0,
            )],
            unavailable_feeds=[target_chat_id],
            warnings=[warning],
        )
    finally:
        if owns_client and hasattr(client, "close"):
            client.close()

    parsed_path = archive_news_payload(
        storage_root=storage_root,
        layer="parsed",
        source_key=SOURCE_KEY,
        retrieved_date=retrieved_date,
        name="messages",
        payload={
            "source_key": SOURCE_KEY,
            "chat_id": target_chat_id,
            "retrieved_date": retrieved_date,
            "messages": parsed_messages,
            "items": item_dicts,
        },
    )
    items = [RawNewsItem(**{**item, "parsed_path": parsed_path}) for item in item_dicts]
    source_status = "available" if items else "empty"
    if not items:
        warnings.append(f"{SOURCE_KEY}:no_candidate_items: no Jin10 Feishu messages passed relevance gate")

    return NewsCollectionResult(
        source_key=SOURCE_KEY,
        status="success" if items else "unavailable",
        items=items,
        source_refs=[_source_ref(
            chat_id=target_chat_id,
            status=source_status,
            reason_code=None if items else "no_candidate_items",
            reason=None if items else "No Jin10 Feishu messages passed relevance gate",
            warning=None if items else warnings[-1],
            raw_paths=raw_paths,
            parsed_path=parsed_path,
            raw_message_count=len(parsed_messages),
            accepted_item_count=len(items),
        )],
        unavailable_feeds=[] if items else [target_chat_id],
        warnings=warnings,
    )


def _raw_item_dict(
    *,
    envelope: FeishuMessageEnvelope,
    decision: NewsRelevanceDecision,
    chat_id: str,
    raw_path: str,
) -> dict[str, Any]:
    item_url = envelope.links[0] if envelope.links else f"feishu://messages/{envelope.message_id}"
    title = _title_from_content(envelope.content)
    duplicate_key = stable_news_item_id(source_key=SOURCE_KEY, title=title, url=item_url)
    return {
        "source_key": SOURCE_KEY,
        "source_name": SOURCE_NAME,
        "source_type": "supplemental",
        "feed_key": chat_id,
        "title": title,
        "url": item_url,
        "domain": urlparse(item_url).netloc.lower().removeprefix("www.") or "feishu.local",
        "published_at": envelope.published_at,
        "fetched_at": utc_now_iso(),
        "summary": _summary_from_content(envelope.content),
        "source_country": "CN",
        "source_language": "zh-CN",
        "event_type": decision.event_type_hint or "market_news_candidate",
        "verification_status": "single_source",
        "duplicate_key": duplicate_key,
        "raw_path": raw_path,
        "parsed_path": None,
        "raw_payload": {
            "ingest_channel": INGEST_CHANNEL,
            "message_id": envelope.message_id,
            "chat_id": chat_id,
            "sender_id": envelope.sender_id,
            "sender_name": envelope.sender_name,
            "message_type": envelope.message_type,
            "detail_urls": envelope.links,
            "relevance_decision": decision.to_dict(),
            "source_refs": [{
                "source_ref": f"{SOURCE_KEY}:{chat_id}:{envelope.message_id}",
                "source": SOURCE_KEY,
                "status": "ok",
                "message_id": envelope.message_id,
                "chat_id": chat_id,
            }],
        },
    }


def _title_from_content(content: str) -> str:
    clean = _clean_message_text(content)
    return clean[:120] or "Jin10 Feishu message"


def _summary_from_content(content: str) -> str:
    return _clean_message_text(content)[:500]


def _clean_message_text(content: str) -> str:
    clean = re.sub(r"https?://\S+", "", content)
    clean = clean.replace("[点击查看详情]", "").replace("点击查看详情", "")
    clean = clean.replace("[来自金十数据APP重要推送]", "").replace("来自金十数据APP重要推送", "")
    return re.sub(r"\s+", " ", clean).strip()


def _source_ref(
    *,
    chat_id: str,
    status: str,
    reason_code: str | None,
    reason: str | None,
    warning: str | None,
    raw_paths: list[str],
    parsed_path: str | None,
    raw_message_count: int,
    accepted_item_count: int,
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "source_ref": f"{SOURCE_KEY}:{chat_id}",
        "source": SOURCE_KEY,
        "source_type": "supplemental",
        "ingest_channel": INGEST_CHANNEL,
        "chat_id": chat_id,
        "status": status,
        "raw_paths": raw_paths,
        "raw_message_count": raw_message_count,
        "accepted_item_count": accepted_item_count,
    }
    if parsed_path:
        ref["parsed_path"] = parsed_path
    if reason_code:
        ref["reason_code"] = reason_code
    if reason:
        ref["reason"] = reason
    if warning:
        ref["warning"] = warning
    return ref


def _unavailable(*, reason_code: str, reason: str) -> NewsCollectionResult:
    warning = f"{SOURCE_KEY}:{reason_code}: {reason}"
    return NewsCollectionResult(
        source_key=SOURCE_KEY,
        status="unavailable",
        items=[],
        source_refs=[_source_ref(
            chat_id=_env_chat_id(),
            status="unavailable",
            reason_code=reason_code,
            reason=reason,
            warning=warning,
            raw_paths=[],
            parsed_path=None,
            raw_message_count=0,
            accepted_item_count=0,
        )],
        unavailable_feeds=[_env_chat_id() or SOURCE_KEY],
        warnings=[warning],
    )


def _env_chat_id() -> str:
    return os.getenv("FEISHU_JIN10_CHAT_ID", "").strip()


def _env_app_id() -> str:
    return os.getenv("FEISHU_NEWS_APP_ID", "").strip()


def _env_app_secret() -> str:
    return os.getenv("FEISHU_NEWS_APP_SECRET", "").strip()
