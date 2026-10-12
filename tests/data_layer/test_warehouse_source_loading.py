"""Typed source loading and transaction behavior, separate from model tests."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from apps.collectors.news.base import RawNewsItem
from apps.data_layer.warehouse_etl import WarehouseError
from apps.data_layer.warehouse_sources import load_news_items, load_source_warehouse
from database.models.cme import CmeOptionRow, CmeParseRun, CmeRawFile
from database.models.cme_settlement import CmeSettlementContract, CmeSettlementSnapshot
from database.models.fedwatch import (
    FedWatchFutures,
    FedWatchMeetingSnapshot,
    FedWatchProbability,
    FedWatchRawSnapshot,
)
from database.models.task import TaskRun, TaskStatus, TaskStep
from database.models.warehouse import LoadBatch, ProducerRunDimension, ensure_warehouse_tables
from database.models.warehouse_sources import (
    CmeOptionFact,
    FedFundsSettlementFact,
    FedWatchFuturesFact,
    FedWatchProbabilityFact,
    NewsItemFact,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    for table in (
        TaskRun.__table__,
        TaskStep.__table__,
        CmeRawFile.__table__,
        CmeOptionRow.__table__,
        CmeParseRun.__table__,
        FedWatchRawSnapshot.__table__,
        FedWatchMeetingSnapshot.__table__,
        FedWatchProbability.__table__,
        FedWatchFutures.__table__,
        CmeSettlementSnapshot.__table__,
        CmeSettlementContract.__table__,
    ):
        table.create(engine, checkfirst=True)
    ensure_warehouse_tables(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def add_cme(db, *, source="cme_daily_bulletin", underlying="GC"):
    raw = CmeRawFile(
        id=str(uuid4()),
        source=source,
        section="PG64",
        source_url="https://www.cmegroup.com/bulletin.pdf",
        raw_path="raw/cme/pg64.pdf",
        sha256="a" * 64,
        report_date="2026-10-09",
        bytes=12,
        retrieved_at=datetime(2026, 10, 10, 1, tzinfo=UTC),
    )
    db.add(raw)
    db.flush()
    db.add(CmeParseRun(raw_file_id=raw.id, status="FINAL", detail_rows_count=1, summary_rows_count=0))
    db.add(
        CmeOptionRow(
            id=str(uuid4()), raw_file_id=raw.id, trade_date="2026-10-09", report_date="2026-10-09",
            version_type="FINAL", product_code="OG", underlying=underlying, expiry="DEC26", strike=4500,
            option_type="CALL", settlement=42.5, delta=0.45, open_interest=123, oi_change=-4,
            total_volume=9, block_volume=1, pnt_volume=2, globex_volume=3, outcry_volume=3,
            exercises=0, pt_change=-1.25, source_page=64,
        )
    )
    db.commit()
    return raw.id


def add_fedwatch(db):
    snapshot_id = str(uuid4())
    snapshot = FedWatchRawSnapshot(
        snapshot_id=snapshot_id,
        source="cme_fedwatch_free",
        collected_at=datetime(2026, 10, 10, 1, 2, tzinfo=UTC),
        as_of=datetime(2026, 10, 10, 1, tzinfo=UTC),
        source_url="https://www.cmegroup.com/fedwatch",
        collector_version="collector-v1",
        http_status=200,
        content_hash="b" * 64,
        raw_artifact_ref="raw/fedwatch/source.html",
        parse_status="ok",
        reason=None,
        source_refs=[],
        snapshot_metadata={},
        payload_hash="c" * 64,
    )
    meeting = FedWatchMeetingSnapshot(
        id=str(uuid4()), row_index=0, meeting_date=date(2026, 12, 16), contract_ref="ZQZ26",
        comparison_window="current", as_of=datetime(2026, 10, 10, 1, tzinfo=UTC),
    )
    meeting.probabilities.append(
        FedWatchProbability(id=str(uuid4()), row_index=0, target_low=4.25, target_high=4.5, probability=1.0)
    )
    snapshot.meetings.append(meeting)
    snapshot.futures.append(
        FedWatchFutures(
            id=str(uuid4()), row_index=0, contract_ref="ZQZ26",
            as_of=datetime(2026, 10, 10, 1, tzinfo=UTC),
            payload={"contract_ref": "ZQZ26", "settlement": 95.75, "implied_rate": 4.25, "ignored": {"x": 1}},
        )
    )
    db.add(snapshot)
    db.commit()
    return snapshot_id


def add_settlement(db, *, source="cme_settlement"):
    snapshot_id = str(uuid4())
    payload = {
        "source": source,
        "source_type": "official_market_data",
        "product_id": 305,
        "instrument": "FUT",
        "official_display_probability": False,
        "source_url": "https://www.cmegroup.com/settlements",
        "schema_version": "cme_settlement_observation.v1",
        "collector_version": "collector-v1",
        "parser_version": "parser-v1",
        "content_hash": "d" * 64,
        "raw_artifact_ref": "raw/macro/cme_settlement/body",
        "manifest_ref": "raw/macro/cme_settlement/manifest.json",
        "request_status": "success",
        "data_status": "available",
        "health": "available",
        "collection_mode": "live",
        "http_status": 200,
        "content_type": "application/json",
        "bytes": 1234,
        "truncated": False,
        "latency_ms": 250,
        "source_update_time_raw": "10/09/2026 17:00",
        "source_time_timezone": None,
        "rows": [{"must_not_copy": True}],
        "private_extension": {"ignored": True},
    }
    db.add(
        CmeSettlementSnapshot(
            snapshot_id=snapshot_id, trade_date=date(2026, 10, 9),
            observed_at=datetime(2026, 10, 10, 1, tzinfo=UTC), settlement_status="FINAL",
            data_status="available", payload_hash="e" * 64, payload=payload,
        )
    )
    db.flush()
    db.add(
        CmeSettlementContract(
            snapshot_id=snapshot_id, contract="OCT 26", contract_month=date(2026, 10, 1),
            settle=95.75, volume=100, open_interest=200,
        )
    )
    db.commit()
    return snapshot_id


def news_item(**changes):
    values = dict(
        source_key="reuters_public",
        source_name="Reuters Public",
        source_type="public_news",
        feed_key="gold",
        title="Gold holds after rates update",
        url="https://www.reuters.com/world/test",
        domain="reuters.com",
        published_at="2026-10-10T08:00:00+08:00",
        fetched_at="2026-10-10T08:01:00+08:00",
        summary="A named summary.",
        source_country="US",
        source_language="en",
        event_type="rates",
        verification_status="single_source",
        duplicate_key="news:reuters:one",
        raw_path="raw/news/reuters/item.json",
        parsed_path="parsed/news/reuters/item.json",
        raw_payload={"body": "must never be stored", "price": 9999},
    )
    values.update(changes)
    return RawNewsItem(**values)


def test_cme_all_fields_version_source_idempotence_and_record_ids(db):
    raw_id = add_cme(db)
    dry = load_source_warehouse(db, "cme-options", record_ids=[raw_id])
    assert dry["processed"] == dry["planned"] == 1 and dry["load_batch_ids"] == []
    first = load_source_warehouse(db, "cme-options", record_ids=[raw_id], dry_run=False)
    db.commit()
    row = db.scalar(select(CmeOptionFact))
    assert first["inserted"] == 1 and len(first["load_batch_ids"]) == 1
    assert (row.version_type, row.parse_status, row.source_raw_id, row.raw_sha256) == ("FINAL", "FINAL", raw_id, "a" * 64)
    assert (row.settlement, row.delta, row.oi_change, row.pt_change) == (
        Decimal("42.500000000000"), Decimal("0.450000000000"), -4, Decimal("-1.250000000000")
    )
    repeated = load_source_warehouse(db, "cme-options", record_ids=[raw_id], dry_run=False)
    assert repeated["skipped"] == 1 and count(db, CmeOptionFact) == 1


def test_cme_one_bad_gc_coordinate_keeps_valid_row_and_marks_partial(db):
    raw_id = add_cme(db)
    db.add(
        CmeOptionRow(
            id=str(uuid4()), raw_file_id=raw_id, trade_date="2026-10-09", report_date="2026-10-09",
            version_type="FINAL", product_code="OG", underlying="XAUUSD", expiry="DEC26", strike=4600,
            option_type="CALL", settlement=12.5, open_interest=1, total_volume=1,
        )
    )
    db.commit()
    result = load_source_warehouse(db, "cme-options", record_ids=[raw_id], dry_run=False)
    db.commit()
    assert result["inserted"] == 1 and result["rejected"] == 1
    assert result["error_codes"] == ["DWH_ASSET_SOURCE_CONFLICT"]
    assert db.scalar(select(LoadBatch)).status == "partial"
    assert db.get(TaskRun, UUID(result["task_run_id"])).status == TaskStatus.partial_success


def test_fedwatch_probability_and_futures_are_typed_and_utc(db):
    snapshot_id = add_fedwatch(db)
    result = load_source_warehouse(db, "fedwatch", record_ids=[snapshot_id], dry_run=False)
    db.commit()
    probability = db.scalar(select(FedWatchProbabilityFact))
    future = db.scalar(select(FedWatchFuturesFact))
    assert result["inserted"] == 2 and result["rejected"] == 0
    assert probability.comparison_window == "current" and probability.probability == Decimal("1.000000000000")
    assert probability.collected_at.tzinfo == UTC and probability.observation_as_of.tzinfo == UTC
    assert future.contract_ref == "ZQZ26" and future.settlement == Decimal("95.750000000000")
    assert future.implied_rate == Decimal("4.250000000000")
    assert "ignored" not in FedWatchFuturesFact.__table__.columns


def test_settlement_projects_only_named_payload_source_fields(db):
    snapshot_id = add_settlement(db)
    result = load_source_warehouse(db, "settlement", record_ids=[snapshot_id], dry_run=False)
    db.commit()
    row = db.scalar(select(FedFundsSettlementFact))
    assert result["inserted"] == 1
    assert (row.settlement_status, row.contract, row.settle, row.volume, row.open_interest) == (
        "FINAL", "OCT 26", Decimal("95.750000000000"), 100, 200
    )
    assert row.source_url == "https://www.cmegroup.com/settlements"
    assert (row.product_id, row.instrument, row.official_display_probability, row.collection_mode) == (
        305, "FUT", False, "live"
    )
    assert not {"payload", "rows", "private_extension"} & set(FedFundsSettlementFact.__table__.columns)


def test_news_item_named_fields_versions_idempotence_and_no_raw_payload(db, tmp_path):
    run_id = uuid4()
    db.add(TaskRun(id=run_id, name="news-producer", status=TaskStatus.success, trade_date="2026-10-10"))
    db.commit()
    first = load_news_items(db, [news_item()], run_id=run_id, storage_root=tmp_path, dry_run=False)
    db.commit()
    row = db.scalar(select(NewsItemFact))
    assert first["inserted"] == 1 and len(first["load_batch_ids"]) == 1
    assert row.published_at == datetime(2026, 10, 10, tzinfo=UTC)
    assert row.fetched_at == datetime(2026, 10, 10, 0, 1, tzinfo=UTC)
    assert row.source_name == "Reuters Public" and row.raw_path.endswith("item.json")
    assert "raw_payload" not in NewsItemFact.__table__.columns
    assert db.scalar(select(ProducerRunDimension)).verified is True
    assert load_news_items(db, [news_item()], run_id=run_id, dry_run=False)["skipped"] == 1
    corrected = news_item(summary="Corrected named summary.")
    assert load_news_items(db, [corrected], run_id=run_id, dry_run=False)["inserted"] == 1
    db.commit()
    assert count(db, NewsItemFact) == 2


def test_failures_numeric_policy_empty_cme_dry_run_and_savepoint_rollback(db):
    bad_id = add_cme(db, source="jin10_quote")
    rejected = load_source_warehouse(db, "cme-options", record_ids=[bad_id])
    assert rejected["rejected"] == 1 and rejected["error_codes"] == ["DWH_NUMERIC_SOURCE_FORBIDDEN"]
    empty = load_source_warehouse(db, "cme-options", record_ids=[])
    assert empty["processed"] == 0 and empty["rejected"] == 0 and empty["error_codes"] == []
    missing = load_source_warehouse(db, "cme-options", record_ids=[str(uuid4())])
    assert missing["rejected"] == 1 and missing["error_codes"] == ["DWH_SOURCE_RECORD_MISSING"]
    run_id = uuid4()
    db.add(TaskRun(id=run_id, name="producer", status=TaskStatus.success))
    db.commit()

    def fail_fact(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO dwh_fact_news_item"):
            raise RuntimeError("private backend detail")

    event.listen(db.get_bind(), "before_cursor_execute", fail_fact)
    with pytest.raises(WarehouseError, match="DWH_TRANSACTION_FAILED"):
        load_news_items(db, [news_item()], run_id=run_id, dry_run=False)
    event.remove(db.get_bind(), "before_cursor_execute", fail_fact)
    assert count(db, NewsItemFact) == count(db, LoadBatch) == 0
    assert count(db, TaskRun) == 1


def test_failed_fedwatch_and_legal_empty_settlement_are_distinct(db):
    failed_id = str(uuid4())
    db.add(
        FedWatchRawSnapshot(
            snapshot_id=failed_id,
            source="cme_fedwatch_free",
            collected_at=datetime(2026, 10, 10, 2, tzinfo=UTC),
            as_of=None,
            source_url="https://www.cmegroup.com/fedwatch",
            collector_version="collector-v1",
            http_status=503,
            content_hash=None,
            raw_artifact_ref="raw/fedwatch/failure.html",
            parse_status="parse_failed",
            reason="upstream_http_503",
            source_refs=[],
            snapshot_metadata={},
            payload_hash="f" * 64,
        )
    )
    empty_id = str(uuid4())
    db.add(
        CmeSettlementSnapshot(
            snapshot_id=empty_id,
            trade_date=date(2026, 10, 10),
            observed_at=datetime(2026, 10, 10, 2, tzinfo=UTC),
            settlement_status=None,
            data_status="no_trade_day",
            payload_hash="1" * 64,
            payload={
                "source": "cme_settlement",
                "source_type": "official_market_data",
                "official_display_probability": False,
                "source_url": "https://www.cmegroup.com/settlements",
                "raw_artifact_ref": "raw/settlement/empty",
                "content_hash": "2" * 64,
                "data_status": "no_trade_day",
                "request_status": "success",
                "health": "no_trade_day",
            },
        )
    )
    db.commit()
    failed = load_source_warehouse(db, "fedwatch", record_ids=[failed_id], dry_run=False)
    empty = load_source_warehouse(db, "settlement", record_ids=[empty_id], dry_run=False)
    db.commit()
    assert failed["rejected"] == 1 and failed["error_codes"] == ["DWH_SOURCE_COLLECTION_FAILED"]
    assert empty["rejected"] == empty["inserted"] == 0 and len(empty["load_batch_ids"]) == 1
    batches = db.scalars(select(LoadBatch).order_by(LoadBatch.id)).all()
    assert [batch.status for batch in batches] == ["rejected", "loaded"]
    assert [batch.quality_status for batch in batches] == ["parse_failed", "no_trade_day"]


def test_news_invalid_path_is_rejected_without_losing_valid_item(db, tmp_path):
    run_id = UUID("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa")
    db.add(TaskRun(id=run_id, name="producer", status=TaskStatus.success))
    db.commit()
    result = load_news_items(
        db,
        [news_item(), news_item(duplicate_key="news:bad", raw_path="../escape.json")],
        run_id=run_id,
        storage_root=tmp_path,
        dry_run=False,
    )
    db.commit()
    assert result["inserted"] == 1 and result["rejected"] == 1
    assert result["error_codes"] == ["DWH_PATH_INVALID"] and count(db, NewsItemFact) == 1


def test_source_apply_is_caller_owned_and_rolls_back_audit_and_fact(db):
    raw_id = add_cme(db)
    result = load_source_warehouse(db, "cme-options", record_ids=[raw_id], dry_run=False)
    assert result["inserted"] == 1 and count(db, CmeOptionFact) == 1
    db.rollback()
    assert count(db, CmeOptionFact) == count(db, LoadBatch) == 0
    assert count(db, TaskRun) == 0
    assert db.get(CmeRawFile, raw_id) is not None
