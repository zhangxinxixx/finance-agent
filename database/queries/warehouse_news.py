"""Strict point-in-time reads for typed DWD news items."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from database.models.warehouse import LoadBatch, ProducerRunDimension
from database.models.warehouse_news import (
    NewsArticleParagraph,
    NewsItemContext,
    NewsItemSourceReference,
    NewsRelevanceAssetTag,
    NewsRelevanceTopicTag,
)
from database.models.warehouse_sources import NewsItemFact


class WarehouseNewsReadError(ValueError):
    pass


def list_warehouse_news_items(
    session: Session,
    run_id: str,
    record_ids: Iterable[str] | None = None,
    as_of: datetime | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Return latest typed news revisions, failing closed on a missing context."""

    if not isinstance(run_id, str) or not run_id.strip():
        raise WarehouseNewsReadError("DWH_NEWS_RUN_ID_INVALID")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise WarehouseNewsReadError("DWH_NEWS_LIMIT_INVALID")
    ids = _record_ids(record_ids)
    cutoff = _as_of(as_of)

    ranked = (
        select(
            NewsItemFact.id.label("fact_id"),
            NewsItemFact.duplicate_key.label("duplicate_key"),
            func.row_number()
            .over(
                partition_by=NewsItemFact.duplicate_key,
                order_by=(NewsItemFact.fetched_at.desc(), NewsItemFact.id.desc()),
            )
            .label("revision_rank"),
        )
        .join(ProducerRunDimension, NewsItemFact.producer_run_id == ProducerRunDimension.id)
        .join(LoadBatch, NewsItemFact.batch_id == LoadBatch.id)
        .where(
            ProducerRunDimension.run_id == run_id.strip(),
            LoadBatch.dataset == "news-items",
            LoadBatch.producer_run_id == NewsItemFact.producer_run_id,
        )
    )
    if ids is not None:
        ranked = ranked.where(NewsItemFact.duplicate_key.in_(ids))
    if cutoff is not None:
        ranked = ranked.where(NewsItemFact.fetched_at <= cutoff)
    ranked = ranked.subquery()

    fact = aliased(NewsItemFact)
    stmt = (
        select(fact, NewsItemContext, LoadBatch)
        .join(ranked, fact.id == ranked.c.fact_id)
        .join(LoadBatch, fact.batch_id == LoadBatch.id)
        .outerjoin(NewsItemContext, NewsItemContext.news_fact_id == fact.id)
        .where(ranked.c.revision_rank == 1)
        .order_by(fact.fetched_at.desc(), fact.id.desc())
        .limit(limit)
    )
    with session.no_autoflush:
        selected = list(session.execute(stmt))
        if any(batch.status != "loaded" or batch.rejected or batch.error_code for _, _, batch in selected):
            raise WarehouseNewsReadError("DWH_NEWS_QUALITY_BLOCKED")
        missing = [row[0].duplicate_key for row in selected if row[1] is None]
        if missing:
            raise WarehouseNewsReadError("DWH_NEWS_CONTEXT_MISSING:" + ",".join(missing))
        fact_ids = [row[0].id for row in selected]
        paragraphs = _children(session, NewsArticleParagraph, fact_ids)
        asset_tags = _children(session, NewsRelevanceAssetTag, fact_ids)
        topic_tags = _children(session, NewsRelevanceTopicTag, fact_ids)
        source_refs = _children(session, NewsItemSourceReference, fact_ids)

    return [
        _item_dict(
            fact_row,
            context,
            paragraphs.get(fact_row.id, []),
            asset_tags.get(fact_row.id, []),
            topic_tags.get(fact_row.id, []),
            source_refs.get(fact_row.id, []),
        )
        for fact_row, context, _ in selected
    ]


def _children(session: Session, model: type, fact_ids: list[int]) -> dict[int, list[Any]]:
    result: dict[int, list[Any]] = {fact_id: [] for fact_id in fact_ids}
    if not fact_ids:
        return result
    rows = session.scalars(
        select(model).where(model.news_fact_id.in_(fact_ids)).order_by(model.news_fact_id, model.ordinal)
    )
    for row in rows:
        result[row.news_fact_id].append(row)
    return result


def _item_dict(fact: NewsItemFact, context: NewsItemContext, paragraphs, asset_tags, topic_tags, source_refs):
    payload: dict[str, Any] = {}
    for key, value in (
        ("publisher", context.publisher),
        ("publisher_url", context.publisher_url),
        ("discovery_method", context.discovery_method),
        ("candidate_scope", context.candidate_scope),
        ("authorized_wire", context.authorized_wire),
        ("content_scope", context.content_scope),
        ("full_text_available", context.full_text_available),
        ("start_date", _date_text(context.calendar_start_date)),
        ("end_date", _date_text(context.calendar_end_date)),
        ("release_date", _date_text(context.calendar_release_date)),
        ("date_text", context.calendar_date_text),
        ("is_sep", context.calendar_is_sep),
        ("source_url", context.calendar_source_url),
    ):
        if value is not None:
            payload[key] = value
    if paragraphs:
        payload["article_paragraphs"] = [row.paragraph for row in paragraphs]
    if context.relevance_decision is not None:
        payload["relevance_decision"] = {
            "decision": context.relevance_decision,
            "score": float(context.relevance_score),
            "asset_tags": [row.asset_tag for row in asset_tags],
            "topic_tags": [row.topic_tag for row in topic_tags],
        }
    if source_refs:
        payload["source_refs"] = [_source_ref_dict(row) for row in source_refs]
    return {
        "source_key": fact.source_key,
        "source_name": fact.source_name,
        "source_type": fact.source_type,
        "feed_key": fact.feed_key,
        "title": fact.title,
        "url": fact.url,
        "domain": fact.domain,
        "published_at": _time_text(fact.published_at),
        "fetched_at": _time_text(fact.fetched_at),
        "summary": fact.summary,
        "source_country": fact.source_country,
        "source_language": fact.source_language,
        "event_type": fact.event_type,
        "verification_status": fact.verification_status,
        "duplicate_key": fact.duplicate_key,
        "raw_path": fact.raw_path,
        "parsed_path": fact.parsed_path,
        "raw_payload": payload,
    }


def _source_ref_dict(row: NewsItemSourceReference) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in (
        "source_ref",
        "source",
        "source_key",
        "source_type",
        "provider",
        "provider_role",
        "reference",
        "title",
        "url",
        "source_url",
        "domain",
        "feed_key",
        "status",
        "content_scope",
        "publisher",
        "publisher_url",
        "discovery_method",
        "candidate_scope",
        "authorized_wire",
        "full_text_available",
        "raw_path",
        "parsed_path",
        "asset_type",
        "path",
        "access_mode",
        "reason_code",
        "reason",
        "message_id",
        "chat_id",
    ):
        value = getattr(row, key)
        if value is not None:
            result[key] = value
    if row.published_at is not None:
        result["published_at"] = _time_text(row.published_at)
    if row.retrieved_at is not None:
        result["retrieved_at"] = _time_text(row.retrieved_at)
    return result


def _record_ids(record_ids: Iterable[str] | None) -> tuple[str, ...] | None:
    if record_ids is None:
        return None
    if isinstance(record_ids, (str, bytes)):
        raise WarehouseNewsReadError("DWH_NEWS_RECORD_IDS_INVALID")
    try:
        values = tuple(record_ids)
    except TypeError:
        raise WarehouseNewsReadError("DWH_NEWS_RECORD_IDS_INVALID") from None
    if len(values) > 10000 or any(not isinstance(value, str) or not value.strip() for value in values):
        raise WarehouseNewsReadError("DWH_NEWS_RECORD_IDS_INVALID")
    return tuple(dict.fromkeys(value.strip() for value in values))


def _as_of(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WarehouseNewsReadError("DWH_NEWS_AS_OF_INVALID")
    return value.astimezone(UTC)


def _time_text(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _date_text(value) -> str | None:
    return value.isoformat() if value is not None else None
