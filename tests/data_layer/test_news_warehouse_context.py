from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from apps.collectors.news.base import RawNewsItem
from apps.data_layer.news_warehouse import NewsContextError, persist_news_context, prepare_news_context
from apps.features.news.event_candidates import build_event_candidates
from apps.features.news.official_calendar import build_official_calendar_snapshot
from apps.features.news.research_focus import build_research_news_focus
from database.models.warehouse import LoadBatch, ProducerRunDimension, WarehouseBase
from database.models.warehouse_news import (
    NewsArticleParagraph,
    NewsItemContext,
    NewsItemSourceReference,
)
from database.models.warehouse_sources import NewsItemFact
from database.queries.warehouse_news import WarehouseNewsReadError, list_warehouse_news_items


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    WarehouseBase.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def item(*, fetched_at="2026-10-10T01:00:00+00:00", title="Policy update", payload=None):
    return RawNewsItem(
        source_key="fed_rss",
        source_name="Federal Reserve",
        source_type="official",
        feed_key="speeches_testimony",
        title=title,
        url="https://www.federalreserve.gov/newsevents/speech/test.htm",
        domain="federalreserve.gov",
        published_at="2026-10-10T00:30:00+00:00",
        fetched_at=fetched_at,
        summary="Named summary",
        source_country="US",
        source_language="en",
        event_type="fed_hawkish",
        verification_status="official_confirmed",
        duplicate_key="news:fed:one",
        raw_path="raw/news/feed.xml",
        parsed_path="parsed/news/feed.json",
        raw_payload=payload or {},
    )


def full_payload():
    return {
        "publisher": "Federal Reserve",
        "publisher_url": "https://www.federalreserve.gov/",
        "discovery_method": "official_rss",
        "candidate_scope": "official_publication",
        "authorized_wire": False,
        "content_scope": "full_text",
        "full_text_available": True,
        "start_date": "2026-10-27",
        "end_date": "2026-10-28",
        "release_date": "2026-10-28",
        "date_text": "October 27-28",
        "is_sep": False,
        "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "article_paragraphs": [
            "If underlying inflation improves, I would be inclined to support holding the policy rate.",
            "If that improvement does not continue, it may be appropriate to raise the policy rate.",
        ],
        "relevance_decision": {
            "decision": "high_value",
            "score": 0.92,
            "asset_tags": ["XAUUSD", "DXY"],
            "topic_tags": ["rates", "macro"],
        },
        "source_refs": [
            {
                "source_ref": "fed_official_article:test",
                "source": "fed_official_article",
                "source_type": "official",
                "source_url": "https://www.federalreserve.gov/newsevents/speech/test.htm",
                "raw_path": "raw/news/article.html",
                "parsed_path": "parsed/news/article.json",
                "retrieved_at": "2026-10-10T01:00:00Z",
                "status": "available",
                "content_scope": "full_text",
                "authorized_wire": False,
                "full_text_available": True,
            }
        ],
        "ignored_untyped_body": {"must": "not persist"},
    }


def add_fact(db, raw_item, *, run_id="run-1", version="a" * 64, with_context=True, status="loaded"):
    producer = db.scalar(select(ProducerRunDimension).where(ProducerRunDimension.run_id == run_id))
    if producer is None:
        producer = ProducerRunDimension(run_id=run_id, verified=True, started_at=datetime(2026, 10, 10, tzinfo=UTC))
        db.add(producer)
        db.flush()
    batch = LoadBatch(
        dataset="news-items",
        source_cursor=raw_item.duplicate_key,
        producer_run_id=producer.id,
        source_artifact_path=raw_item.raw_path,
        as_of=datetime.fromisoformat(raw_item.fetched_at),
        transform_version="test",
        processed=1,
        inserted=1,
        skipped=0,
        rejected=0,
        status=status,
        audit_task_run_id="00000000-0000-0000-0000-000000000001",
        audit_task_step_id="00000000-0000-0000-0000-000000000002",
    )
    db.add(batch)
    db.flush()
    fact = NewsItemFact(
        batch_id=batch.id,
        producer_run_id=producer.id,
        version_sha256=version,
        source_record_id=raw_item.duplicate_key,
        raw_path=raw_item.raw_path,
        as_of=datetime.fromisoformat(raw_item.fetched_at),
        quality_status=raw_item.verification_status,
        source_id=_source_id(db, raw_item),
        source_key=raw_item.source_key,
        source_name=raw_item.source_name,
        source_type=raw_item.source_type,
        feed_key=raw_item.feed_key,
        title=raw_item.title,
        url=raw_item.url,
        domain=raw_item.domain,
        published_at=datetime.fromisoformat(raw_item.published_at),
        fetched_at=datetime.fromisoformat(raw_item.fetched_at),
        summary=raw_item.summary,
        source_language=raw_item.source_language,
        source_country=raw_item.source_country,
        event_type=raw_item.event_type,
        verification_status=raw_item.verification_status,
        duplicate_key=raw_item.duplicate_key,
        parsed_path=raw_item.parsed_path,
    )
    db.add(fact)
    db.flush()
    if with_context:
        persist_news_context(db, prepare_news_context(raw_item), news_fact_id=fact.id)
    return fact


def _source_id(db, raw_item):
    from database.models.warehouse import SourceDimension

    row = db.scalar(select(SourceDimension).where(SourceDimension.source_key == raw_item.source_key))
    if row is None:
        row = SourceDimension(
            source_key=raw_item.source_key, source_type=raw_item.source_type, name=raw_item.source_name
        )
        db.add(row)
        db.flush()
    return row.id


def test_prepare_persist_and_reader_preserve_named_policy_calendar_and_qualification(db):
    raw_item = item(payload=full_payload())
    first = prepare_news_context(raw_item)
    second = prepare_news_context(raw_item.to_dict())
    assert first.context_sha256 == second.context_sha256
    fact = add_fact(db, raw_item)
    same = persist_news_context(db, second, news_fact_id=fact.id)
    assert same.context_sha256 == first.context_sha256
    db.commit()

    [row] = list_warehouse_news_items(db, "run-1")
    rebuilt = RawNewsItem(**row)
    assert rebuilt.raw_payload["authorized_wire"] is False
    assert rebuilt.raw_payload["full_text_available"] is True
    assert rebuilt.raw_payload["is_sep"] is False
    assert rebuilt.raw_payload["article_paragraphs"][0].startswith("If underlying inflation")
    assert rebuilt.raw_payload["start_date"] == "2026-10-27"
    assert rebuilt.raw_payload["relevance_decision"] == {
        "decision": "high_value",
        "score": 0.92,
        "asset_tags": ["XAUUSD", "DXY"],
        "topic_tags": ["rates", "macro"],
    }
    assert rebuilt.raw_payload["source_refs"][0]["content_scope"] == "full_text"
    assert "ignored_untyped_body" not in rebuilt.raw_payload
    assert "raw_payload" not in NewsItemContext.__table__.columns

    bundle = build_event_candidates([row], as_of="2026-10-10T02:00:00+00:00")
    assert bundle.raw_news_items[0].source_refs[0]["authorized_wire"] is False
    focus = build_research_news_focus(
        [
            {
                "event_id": "event:fed:one",
                "primary_news_item_id": rebuilt.duplicate_key,
                "event_time": rebuilt.published_at,
                "verification_status": rebuilt.verification_status,
                "source_refs": [{"title": rebuilt.title}],
            }
        ],
        [row],
    )
    assert focus[0]["topic"] == "美联储政策条件"
    assert focus[0]["evidence_scope"] == "official_full_text"


@pytest.mark.parametrize(
    "field,value",
    [
        ("authorized_wire", "false"),
        ("full_text_available", 1),
        ("is_sep", "no"),
    ],
)
def test_prepare_rejects_truthy_boolean_qualification(field, value):
    payload = full_payload()
    payload[field] = value
    with pytest.raises(NewsContextError, match="BOOLEAN_INVALID"):
        prepare_news_context(item(payload=payload))


def test_prepare_rejects_malformed_dates_relevance_and_source_refs():
    for change in (
        {"start_date": "2026-99-01"},
        {"relevance_decision": {"decision": "high_value", "score": "0.9"}},
        {"relevance_decision": {"decision": "high_value", "score": 0.9}},
        {"source_refs": ["not-an-object"]},
    ):
        payload = full_payload()
        payload.update(change)
        with pytest.raises(NewsContextError):
            prepare_news_context(item(payload=payload))


def test_official_calendar_consumer_receives_typed_dates(db):
    values = item(
        payload={
            "start_date": "2026-10-27",
            "end_date": "2026-10-28",
            "date_text": "October 27-28",
            "is_sep": False,
            "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        }
    ).to_dict()
    values.update(
        source_key="fomc_calendar",
        source_name="Federal Open Market Committee",
        feed_key="fomc_meetings",
        event_type="fomc_meeting",
        duplicate_key="news:fomc:2026-10-27",
        title="FOMC meeting",
    )
    add_fact(db, RawNewsItem(**values))
    db.commit()
    rows = list_warehouse_news_items(db, "run-1")
    snapshot = build_official_calendar_snapshot(rows, as_of="2026-10-10T02:00:00+00:00", horizon_days=30)
    assert snapshot["events"][0]["start_date"] == "2026-10-27"
    assert snapshot["events"][0]["end_date"] == "2026-10-28"
    assert snapshot["events"][0]["is_sep"] is False


def test_known_eia_named_release_date_is_normalized_without_guessing():
    prepared = prepare_news_context(item(payload={"release_date": "October 14, 2026"}))
    assert prepared.calendar_release_date.isoformat() == "2026-10-14"


def test_reader_selects_latest_revision_and_honors_pit_and_record_ids(db):
    old = item(fetched_at="2026-10-10T01:00:00+00:00", title="Old", payload={"full_text_available": False})
    new = item(fetched_at="2026-10-10T02:00:00+00:00", title="New", payload={"full_text_available": True})
    add_fact(db, old, version="1" * 64)
    add_fact(db, new, version="2" * 64)
    db.commit()
    [latest] = list_warehouse_news_items(db, "run-1", record_ids=[old.duplicate_key])
    [pit] = list_warehouse_news_items(db, "run-1", as_of=datetime(2026, 10, 10, 1, 30, tzinfo=UTC))
    assert latest["title"] == "New" and latest["raw_payload"]["full_text_available"] is True
    assert pit["title"] == "Old" and pit["raw_payload"]["full_text_available"] is False


def test_latest_missing_context_blocks_instead_of_falling_back(db):
    add_fact(db, item(fetched_at="2026-10-10T01:00:00+00:00", title="Old"), version="1" * 64)
    add_fact(db, item(fetched_at="2026-10-10T02:00:00+00:00", title="New"), version="2" * 64, with_context=False)
    db.commit()
    with pytest.raises(WarehouseNewsReadError, match="DWH_NEWS_CONTEXT_MISSING:news:fed:one"):
        list_warehouse_news_items(db, "run-1")


def test_latest_partial_context_blocks_instead_of_showing_older_revision(db):
    add_fact(db, item(fetched_at="2026-10-10T01:00:00+00:00", title="Old"), version="1" * 64)
    add_fact(db, item(fetched_at="2026-10-10T02:00:00+00:00", title="New"), version="2" * 64, status="partial")
    db.commit()
    with pytest.raises(WarehouseNewsReadError, match="DWH_NEWS_QUALITY_BLOCKED"):
        list_warehouse_news_items(db, "run-1")


def test_persist_participates_in_callers_single_transaction_rollback(db):
    raw_item = item(payload=full_payload())
    with db.begin_nested() as transaction:
        fact = add_fact(db, raw_item)
        assert db.get(NewsItemContext, fact.id) is not None
        transaction.rollback()
    assert db.scalar(select(func.count()).select_from(NewsItemFact)) == 0
    assert db.scalar(select(func.count()).select_from(NewsItemContext)) == 0
    assert db.scalar(select(func.count()).select_from(NewsArticleParagraph)) == 0
    assert db.scalar(select(func.count()).select_from(NewsItemSourceReference)) == 0


def test_reader_does_not_open_raw_or_parsed_files(db, monkeypatch):
    add_fact(db, item(payload=full_payload()))
    db.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("reader attempted a file read")

    monkeypatch.setattr("pathlib.Path.open", forbidden)
    monkeypatch.setattr("pathlib.Path.read_text", forbidden)
    [row] = list_warehouse_news_items(db, "run-1")
    assert row["title"] == "Policy update"
