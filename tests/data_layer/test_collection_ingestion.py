from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import sessionmaker

from apps.data_layer.collection_ingestion import ingest_collection_records, ingest_news_collection, macro_raw_sources
from apps.data_layer.raw_retention import apply_raw_retention
from apps.data_layer.warehouse_maintenance import reconcile_warehouse
from database.migrations.runtime import run_database_migrations
from database.models.analysis import MacroObservation
from database.models.raw_source import RawSourceFile
from database.models.task import TaskRun, TaskStatus
from database.models.warehouse import MacroFact
from database.models.warehouse_sources import NewsItemFact
from database.models.warehouse_sync import WarehouseSyncCursor


@pytest.fixture
def warehouse(tmp_path):
    url = f"sqlite:///{tmp_path / 'warehouse.sqlite'}"
    run_database_migrations(url)
    engine = create_engine(url)
    factory = sessionmaker(engine)
    root = tmp_path / "storage"
    (root / "raw").mkdir(parents=True)
    yield factory, root
    engine.dispose()


def observation(session, root, *, identity, value=3.25, age=31, producer=None, symbol="DFII10"):
    collected = datetime.now(UTC) - timedelta(days=age)
    path = root / "raw" / f"{identity}.json"
    path.write_text('{"observation":"fixture"}')
    os.utime(path, (collected.timestamp(), collected.timestamp()))
    row = MacroObservation(id=identity, source_key="fred", symbol=symbol, observation_date=date(2026, 9, 1),
                           value=value, source_url="https://example.test/official", raw_path=f"raw/{identity}.json",
                           retrieved_at=collected, run_id=str(producer) if producer else None)
    session.add(row)
    session.flush()
    return row


def test_current_collection_has_exact_ids_receipts_and_survives_raw_expiry(warehouse):
    factory, root = warehouse
    producer = uuid4()
    with factory() as session:
        session.add(TaskRun(id=producer, name="fixture producer", status=TaskStatus.success))
        session.flush()
        row = observation(session, root, identity="old", producer=producer)
        result = ingest_collection_records(session, "macro", record_ids=[row.id], storage_root=root,
                                           run_id=str(producer), raw_sources=macro_raw_sources([row]))
        assert (result["inserted"], result["raw_registered"], result["raw_ready"]) == (1, 1, 1)
        assert result["raw_blocked"] == []
        session.commit()
    report = root / "outputs" / "historical.md"
    report.parent.mkdir()
    report.write_text("Saved research at its original cutoff")
    deleted = apply_raw_retention(factory, storage_root=root)
    assert deleted["deleted_count"] == 1
    assert not (root / "raw/old.json").exists()
    assert report.read_text() == "Saved research at its original cutoff"
    with factory() as session:
        assert float(session.scalar(select(MacroFact.value))) == 3.25
        original = session.get(MacroObservation, "old")
        assert original.raw_path == "raw/old.json"
        assert session.scalar(select(RawSourceFile)).deleted_at is not None


def test_exact_ids_find_late_rows_and_keep_revised_values(warehouse):
    factory, root = warehouse
    with factory() as session:
        first = observation(session, root, identity="z")
        ingest_collection_records(session, "macro", record_ids=[first.id], storage_root=root)
        late = observation(session, root, identity="a", symbol="DGS10")
        session.flush()
        result = ingest_collection_records(session, "macro", record_ids=[late.id], storage_root=root)
        assert result["processed"] == 1
        assert result["inserted"] == 1
        late.value = 4.5
        changed = ingest_collection_records(session, "macro", record_ids=[late.id], storage_root=root)
        assert changed["inserted"] == 1
        values = session.scalars(select(MacroFact.value).where(MacroFact.source_record_id == "a")).all()
        assert sorted(map(float, values)) == [3.25, 4.5]
        assert ingest_collection_records(session, "macro", record_ids=[], storage_root=root)["processed"] == 0
        session.rollback()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MacroFact)) == 0


def test_shared_file_requires_all_known_source_records_before_expiry(warehouse):
    factory, root = warehouse
    with factory() as session:
        first = observation(session, root, identity="shared-first")
        second = observation(session, root, identity="shared-second", symbol="DGS10")
        second.raw_path = first.raw_path
        session.flush()
        ingest_collection_records(session, "macro", record_ids=[first.id], storage_root=root)
        session.commit()
    result = apply_raw_retention(factory, storage_root=root)
    assert result["deleted_count"] == 0
    assert (root / "raw/shared-first.json").is_file()
    with factory() as session:
        ingest_collection_records(session, "macro", record_ids=["shared-second"], storage_root=root)
        session.commit()
    result = apply_raw_retention(factory, storage_root=root)
    assert result["deleted_count"] == 1
    assert not (root / "raw/shared-first.json").exists()


def test_unmigrated_database_never_claims_loaded_or_creates_schema(tmp_path):
    engine = create_engine("sqlite://")
    with sessionmaker(engine)() as session:
        result = ingest_collection_records(session, "macro", record_ids=["x"], storage_root=tmp_path)
        assert result["error_code"] == "DWH_SCHEMA_MISSING"
        assert result["status"] == "unavailable"
        assert inspect(engine).get_table_names() == []


def test_news_is_queryable_without_whole_payload_and_preserves_verification(warehouse):
    factory, root = warehouse
    collected = datetime.now(UTC) - timedelta(days=31)
    path = root / "raw/news.json"
    path.write_text('{"body":"source fixture"}')
    os.utime(path, (collected.timestamp(), collected.timestamp()))
    producer = uuid4()
    item = dict(source_key="jin10_news", source_name="Jin10", source_type="news", feed_key="flash",
                title="News title", url="https://example.test/news", domain="example.test",
                published_at=collected.isoformat(), fetched_at=collected.isoformat(), summary="Original excerpt",
                verification_status="single_source", duplicate_key="news:jin10:one", raw_path="raw/news.json",
                raw_payload={"extra_body": "must not become a stored JSON body"})
    with factory() as session:
        session.add(TaskRun(id=producer, name="news fixture", status=TaskStatus.success))
        session.flush()
        result = ingest_news_collection(session, [item], run_id=str(producer), storage_root=root)
        assert result["inserted"] == 1
        assert result["raw_ready"] == 1
        fact = session.scalar(select(NewsItemFact))
        assert fact.verification_status == "single_source"
        assert fact.summary == "Original excerpt"
        assert fact.raw_path == "raw/news.json"
        assert "raw_payload" not in NewsItemFact.__table__.columns
        session.commit()
    assert apply_raw_retention(factory, storage_root=root)["deleted_count"] == 1
    with factory() as session:
        assert session.scalar(select(NewsItemFact.title)) == "News title"


def test_reconciliation_advances_then_rescans_for_late_ids(warehouse):
    factory, root = warehouse
    with factory() as session:
        observation(session, root, identity="m")
        observation(session, root, identity="z", symbol="DGS10")
        session.commit()
    def scan():
        with factory() as session:
            result = reconcile_warehouse(session, storage_root=root, datasets=["macro"], page_size=1, max_pages=1)
            session.commit()
            return result["datasets"][0]
    assert scan()["next_after"] == "m"
    assert scan()["next_after"] == "z"
    assert scan()["cycle_complete"] is True
    with factory() as session:
        observation(session, root, identity="a", symbol="DTWEXBGS")
        session.commit()
    assert scan()["inserted"] == 1
    with factory() as session:
        assert session.get(WarehouseSyncCursor, "macro").after_cursor == "a"
        assert session.scalar(select(func.count()).select_from(MacroFact)) == 3


def test_registered_file_without_successful_load_remains_protected(warehouse):
    factory, root = warehouse
    with factory() as session:
        row = observation(session, root, identity="missing")
        result = ingest_collection_records(session, "macro", record_ids=[], storage_root=root,
                                           raw_sources=macro_raw_sources([row]))
        assert result["raw_ready"] == 0
        assert result["raw_blocked"][0]["reason"] == "RAW_WAREHOUSE_COVERAGE_INCOMPLETE"
        session.commit()
    assert apply_raw_retention(factory, storage_root=root)["deleted_count"] == 0
    assert (root / "raw/missing.json").exists()


def test_numeric_warehouse_checks_legacy_nested_lineage(warehouse):
    factory, root = warehouse
    with factory() as session:
        row = observation(session, root, identity="legacy")
        row.source_refs = [{"source": "aggregate", "upstream": [{"source": "jin10"}]}]
        session.flush()
        result = ingest_collection_records(session, "macro", record_ids=[row.id], storage_root=root)
        assert result["rejected"] == 1
        assert result["error_codes"] == ["DWH_NUMERIC_SOURCE_FORBIDDEN"]
        assert session.scalar(select(func.count()).select_from(MacroFact)) == 0
        assert result["raw_ready"] == 0


def test_archive_and_extracted_cot_data_have_real_batch_lineage(warehouse):
    factory, root = warehouse
    collected = datetime.now(UTC) - timedelta(days=31)
    archive = root / "raw/cftc.zip"
    archive.write_bytes(b"archived input fixture")
    os.utime(archive, (collected.timestamp(), collected.timestamp()))
    with factory() as session:
        row = observation(session, root, identity="cot", symbol="COT_GOLD_NONCOMM_NET")
        row.source_key = "cftc"
        row.source_refs = [{"source": "cftc", "raw_path": row.raw_path, "raw_archive_path": "raw/cftc.zip"}]
        session.flush()
        result = ingest_collection_records(session, "macro", record_ids=[row.id], storage_root=root)
        assert result["raw_ready"] == 2
        assert result["raw_blocked"] == []
        session.commit()
    assert apply_raw_retention(factory, storage_root=root)["deleted_count"] == 2
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MacroFact)) == 1


def test_fedwatch_manifest_and_responses_are_distinct_files(warehouse):
    from hashlib import sha256
    from database.models.fedwatch import FedWatchRawSnapshot, FedWatchMeetingSnapshot, FedWatchProbability
    from database.models.warehouse_sources import FedWatchProbabilityFact
    from database.models.warehouse_sync import BatchSourceFile

    factory, root = warehouse
    collected = datetime.now(UTC) - timedelta(days=31)
    snapshot_id = str(uuid4())
    response = root / "raw/fedwatch.html"
    response.write_text("Official probability fixture")
    response_hash = sha256(response.read_bytes()).hexdigest()
    manifest = root / "raw/manifest.json"
    manifest.write_text('{"snapshot_id":"' + snapshot_id + '"}')
    for path in (response, manifest):
        os.utime(path, (collected.timestamp(), collected.timestamp()))
    with factory() as session:
        raw = FedWatchRawSnapshot(snapshot_id=snapshot_id, source="cme_fedwatch_free", collected_at=collected,
                                 as_of=collected, source_url="https://www.cmegroup.com/fedwatch",
                                 collector_version="fixture", http_status=200, content_hash=response_hash,
                                 raw_artifact_ref="raw/manifest.json", parse_status="ok", payload_hash="a" * 64,
                                 source_refs=[{"raw_artifact_ref": "raw/fedwatch.html", "content_hash": response_hash}],
                                 snapshot_metadata={})
        meeting = FedWatchMeetingSnapshot(row_index=0, meeting_date=date(2026, 12, 16),
                                         comparison_window="current", as_of=collected)
        meeting.probabilities.append(FedWatchProbability(row_index=0, target_low=4.25, target_high=4.5, probability=1.0))
        raw.meetings.append(meeting)
        session.add(raw)
        session.flush()
        result = ingest_collection_records(session, "fedwatch", record_ids=[snapshot_id], storage_root=root)
        assert result["inserted"] == 1 and result["raw_ready"] == 2
        assert result["raw_blocked"] == []
        links = session.scalars(select(BatchSourceFile)).all()
        assert {link.sha256 for link in links} == {response_hash, sha256(manifest.read_bytes()).hexdigest()}
        assert session.scalar(select(FedWatchProbabilityFact.content_hash)) == response_hash
        session.commit()
    assert apply_raw_retention(factory, storage_root=root)["deleted_count"] == 2
    with factory() as session:
        assert float(session.scalar(select(FedWatchProbabilityFact.probability))) == 1.0
