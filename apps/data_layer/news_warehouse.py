"""Pure preparation and transactional persistence for typed news context."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.collectors.news.base import RawNewsItem
from database.models.warehouse_news import (
    NewsArticleParagraph,
    NewsItemContext,
    NewsItemSourceReference,
    NewsRelevanceAssetTag,
    NewsRelevanceTopicTag,
)


class NewsContextError(ValueError):
    """A news context cannot be represented without weakening its meaning."""


@dataclass(frozen=True)
class PreparedNewsSourceReference:
    source_ref: str | None = None
    source: str | None = None
    source_key: str | None = None
    source_type: str | None = None
    provider: str | None = None
    provider_role: str | None = None
    reference: str | None = None
    title: str | None = None
    url: str | None = None
    source_url: str | None = None
    domain: str | None = None
    feed_key: str | None = None
    status: str | None = None
    content_scope: str | None = None
    publisher: str | None = None
    publisher_url: str | None = None
    discovery_method: str | None = None
    candidate_scope: str | None = None
    authorized_wire: bool | None = None
    full_text_available: bool | None = None
    raw_path: str | None = None
    parsed_path: str | None = None
    asset_type: str | None = None
    path: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    access_mode: str | None = None
    reason_code: str | None = None
    reason: str | None = None
    message_id: str | None = None
    chat_id: str | None = None


@dataclass(frozen=True)
class PreparedNewsContext:
    context_sha256: str
    publisher: str | None
    publisher_url: str | None
    discovery_method: str | None
    candidate_scope: str | None
    authorized_wire: bool | None
    content_scope: str | None
    full_text_available: bool | None
    calendar_start_date: date | None
    calendar_end_date: date | None
    calendar_release_date: date | None
    calendar_date_text: str | None
    calendar_is_sep: bool | None
    calendar_source_url: str | None
    relevance_decision: str | None
    relevance_score: Decimal | None
    article_paragraphs: tuple[str, ...]
    relevance_asset_tags: tuple[str, ...]
    relevance_topic_tags: tuple[str, ...]
    source_refs: tuple[PreparedNewsSourceReference, ...]


_REF_STRING_LIMITS = {
    "source_ref": None,
    "source": 128,
    "source_key": 128,
    "source_type": 64,
    "provider": 128,
    "provider_role": 64,
    "reference": None,
    "title": None,
    "url": None,
    "source_url": None,
    "domain": 255,
    "feed_key": 128,
    "status": 64,
    "content_scope": 128,
    "publisher": 255,
    "publisher_url": None,
    "discovery_method": 128,
    "candidate_scope": 128,
    "raw_path": None,
    "parsed_path": None,
    "asset_type": 64,
    "path": None,
    "access_mode": 128,
    "reason_code": 128,
    "reason": None,
    "message_id": 255,
    "chat_id": 255,
}
_REF_IDENTITY_FIELDS = (
    "source_ref",
    "source",
    "source_key",
    "provider",
    "reference",
    "url",
    "source_url",
    "raw_path",
    "parsed_path",
    "path",
    "message_id",
)


def prepare_news_context(item: RawNewsItem | Mapping[str, Any]) -> PreparedNewsContext:
    """Validate and canonically hash only the named news compatibility fields."""

    if isinstance(item, RawNewsItem):
        raw_item: Mapping[str, Any] = item.to_dict()
    elif isinstance(item, Mapping):
        raw_item = item
    else:
        raise NewsContextError("DWH_NEWS_CONTEXT_ITEM_INVALID")
    payload = raw_item.get("raw_payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        raise NewsContextError("DWH_NEWS_CONTEXT_PAYLOAD_INVALID")

    paragraphs = _string_list(payload, "article_paragraphs", max_length=None, dedupe=False)
    raw_relevance = payload.get("relevance_decision")
    if raw_relevance is not None and not isinstance(raw_relevance, Mapping):
        raise NewsContextError("DWH_NEWS_RELEVANCE_INVALID")
    relevance = raw_relevance or {}
    decision = _string(relevance, "decision", max_length=64)
    score = _score(relevance.get("score"), present="score" in relevance)
    if raw_relevance is not None and (
        decision is None or score is None or "asset_tags" not in relevance or "topic_tags" not in relevance
    ):
        raise NewsContextError("DWH_NEWS_RELEVANCE_INCOMPLETE")

    start_date = _date(payload, "start_date")
    end_date = _date(payload, "end_date")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise NewsContextError("DWH_NEWS_CALENDAR_RANGE_INVALID")

    values: dict[str, Any] = {
        "publisher": _string(payload, "publisher", max_length=255),
        "publisher_url": _string(payload, "publisher_url"),
        "discovery_method": _string(payload, "discovery_method", max_length=128),
        "candidate_scope": _string(payload, "candidate_scope", max_length=128),
        "authorized_wire": _boolean(payload, "authorized_wire"),
        "content_scope": _string(payload, "content_scope", max_length=128),
        "full_text_available": _boolean(payload, "full_text_available"),
        "calendar_start_date": start_date,
        "calendar_end_date": end_date,
        "calendar_release_date": _date(payload, "release_date"),
        "calendar_date_text": _string(payload, "date_text"),
        "calendar_is_sep": _boolean(payload, "is_sep"),
        "calendar_source_url": _string(payload, "source_url"),
        "relevance_decision": decision,
        "relevance_score": score,
        "article_paragraphs": paragraphs,
        "relevance_asset_tags": _string_list(relevance, "asset_tags", max_length=128, dedupe=True),
        "relevance_topic_tags": _string_list(relevance, "topic_tags", max_length=128, dedupe=True),
        "source_refs": _source_refs(payload),
    }
    canonical = _canonical(values)
    context_sha256 = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return PreparedNewsContext(context_sha256=context_sha256, **values)


def persist_news_context(session: Session, prepared: PreparedNewsContext, *, news_fact_id: int) -> NewsItemContext:
    """Persist one prepared context idempotently without DDL or transaction control."""

    if (
        not isinstance(prepared, PreparedNewsContext)
        or isinstance(news_fact_id, bool)
        or not isinstance(news_fact_id, int)
    ):
        raise NewsContextError("DWH_NEWS_CONTEXT_ARGUMENT_INVALID")
    if news_fact_id <= 0:
        raise NewsContextError("DWH_NEWS_CONTEXT_ARGUMENT_INVALID")
    existing = session.scalar(select(NewsItemContext).where(NewsItemContext.news_fact_id == news_fact_id))
    if existing is not None:
        if existing.context_sha256 != prepared.context_sha256:
            raise NewsContextError("DWH_NEWS_CONTEXT_CONFLICT")
        return existing

    row = NewsItemContext(
        news_fact_id=news_fact_id,
        **{
            field: getattr(prepared, field)
            for field in (
                "context_sha256",
                "publisher",
                "publisher_url",
                "discovery_method",
                "candidate_scope",
                "authorized_wire",
                "content_scope",
                "full_text_available",
                "calendar_start_date",
                "calendar_end_date",
                "calendar_release_date",
                "calendar_date_text",
                "calendar_is_sep",
                "calendar_source_url",
                "relevance_decision",
                "relevance_score",
            )
        },
    )
    session.add(row)
    # There are intentionally no ORM relationships. Flush the 1:1 parent so
    # databases enforcing foreign keys can accept the typed children below.
    session.flush([row])
    for ordinal, paragraph in enumerate(prepared.article_paragraphs):
        session.add(NewsArticleParagraph(news_fact_id=news_fact_id, ordinal=ordinal, paragraph=paragraph))
    for ordinal, tag in enumerate(prepared.relevance_asset_tags):
        session.add(NewsRelevanceAssetTag(news_fact_id=news_fact_id, ordinal=ordinal, asset_tag=tag))
    for ordinal, tag in enumerate(prepared.relevance_topic_tags):
        session.add(NewsRelevanceTopicTag(news_fact_id=news_fact_id, ordinal=ordinal, topic_tag=tag))
    for ordinal, ref in enumerate(prepared.source_refs):
        session.add(NewsItemSourceReference(news_fact_id=news_fact_id, ordinal=ordinal, **asdict(ref)))
    session.flush()
    return row


def _string(mapping: Mapping[str, Any], key: str, *, max_length: int | None = None) -> str | None:
    if key not in mapping or mapping[key] is None:
        return None
    value = mapping[key]
    if not isinstance(value, str):
        raise NewsContextError(f"DWH_NEWS_CONTEXT_FIELD_INVALID:{key}")
    value = value.strip()
    if not value:
        return None
    if max_length is not None and len(value) > max_length:
        raise NewsContextError(f"DWH_NEWS_CONTEXT_FIELD_INVALID:{key}")
    return value


def _boolean(mapping: Mapping[str, Any], key: str) -> bool | None:
    if key not in mapping or mapping[key] is None:
        return None
    value = mapping[key]
    if type(value) is not bool:
        raise NewsContextError(f"DWH_NEWS_CONTEXT_BOOLEAN_INVALID:{key}")
    return value


def _date(mapping: Mapping[str, Any], key: str) -> date | None:
    if key not in mapping or mapping[key] is None:
        return None
    value = mapping[key]
    if isinstance(value, datetime) or not isinstance(value, (str, date)):
        raise NewsContextError(f"DWH_NEWS_CONTEXT_DATE_INVALID:{key}")
    try:
        if isinstance(value, date):
            parsed = value
        else:
            text = value.strip()
            try:
                parsed = date.fromisoformat(text)
            except ValueError:
                # The EIA's official schedule publishes dates in this named
                # month form. Normalize that known source representation.
                parsed = datetime.strptime(text, "%B %d, %Y").date()
    except (ValueError, AttributeError):
        raise NewsContextError(f"DWH_NEWS_CONTEXT_DATE_INVALID:{key}") from None
    return parsed


def _datetime(mapping: Mapping[str, Any], key: str) -> datetime | None:
    if key not in mapping or mapping[key] is None:
        return None
    value = mapping[key]
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise NewsContextError(f"DWH_NEWS_CONTEXT_TIME_INVALID:{key}") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise NewsContextError(f"DWH_NEWS_CONTEXT_TIME_INVALID:{key}")
    return value.astimezone(UTC)


def _string_list(mapping: Mapping[str, Any], key: str, *, max_length: int | None, dedupe: bool) -> tuple[str, ...]:
    if key not in mapping or mapping[key] is None:
        return ()
    raw = mapping[key]
    if not isinstance(raw, (list, tuple)):
        raise NewsContextError(f"DWH_NEWS_CONTEXT_LIST_INVALID:{key}")
    result: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            raise NewsContextError(f"DWH_NEWS_CONTEXT_LIST_INVALID:{key}")
        value = value.strip()
        if max_length is not None and len(value) > max_length:
            raise NewsContextError(f"DWH_NEWS_CONTEXT_LIST_INVALID:{key}")
        if not dedupe or value not in seen:
            result.append(value)
            seen.add(value)
    return tuple(result)


def _score(value: Any, *, present: bool) -> Decimal | None:
    if not present or value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise NewsContextError("DWH_NEWS_RELEVANCE_SCORE_INVALID")
    if isinstance(value, float) and not math.isfinite(value):
        raise NewsContextError("DWH_NEWS_RELEVANCE_SCORE_INVALID")
    score = Decimal(str(value))
    if not Decimal("0") <= score <= Decimal("1"):
        raise NewsContextError("DWH_NEWS_RELEVANCE_SCORE_INVALID")
    return score


def _source_refs(payload: Mapping[str, Any]) -> tuple[PreparedNewsSourceReference, ...]:
    if "source_refs" not in payload or payload["source_refs"] is None:
        return ()
    refs = payload["source_refs"]
    if not isinstance(refs, (list, tuple)):
        raise NewsContextError("DWH_NEWS_SOURCE_REFS_INVALID")
    result: list[PreparedNewsSourceReference] = []
    for raw in refs:
        if not isinstance(raw, Mapping):
            raise NewsContextError("DWH_NEWS_SOURCE_REF_INVALID")
        fields = {key: _string(raw, key, max_length=limit) for key, limit in _REF_STRING_LIMITS.items()}
        fields["authorized_wire"] = _boolean(raw, "authorized_wire")
        fields["full_text_available"] = _boolean(raw, "full_text_available")
        fields["published_at"] = _datetime(raw, "published_at")
        fields["retrieved_at"] = _datetime(raw, "retrieved_at")
        if not any(fields[key] is not None for key in _REF_IDENTITY_FIELDS):
            raise NewsContextError("DWH_NEWS_SOURCE_REF_IDENTITY_MISSING")
        result.append(PreparedNewsSourceReference(**fields))
    return tuple(result)


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _canonical(asdict(value))
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value
