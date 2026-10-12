from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import apps.data_layer.raw_retention as raw_retention
import apps.data_layer.warehouse_maintenance as maintenance
from apps.data_layer.collection_ingestion import ingest_collection_records
from apps.data_layer.raw_retention import apply_raw_retention
from apps.data_layer.warehouse_maintenance import reconcile_warehouse, run_warehouse_maintenance
from database.migrations.runtime import run_database_migrations
from database.models.analysis import MacroObservation, MarketCandle
from database.models.raw_source import RawRetentionEvent, RawSourceFile, RawSourceLoadBatch
from database.models.task import TaskRun, TaskStep, TaskStatus, StepStatus
from database.models.warehouse import CandleFact, LoadBatch, MacroFact, ProducerRunDimension
from database.models.warehouse_sync import WarehouseSyncCursor
from database.models.warehouse_sync import BatchSourceFile
from apps.data_layer.warehouse_etl import load_warehouse, WarehouseError
import apps.data_layer.warehouse_etl as etl


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


def add_macro(session, root, identity="macro", *, value=3.25, age=31, producer=None):
    collected = datetime.now(UTC) - timedelta(days=age)
    path = root / "raw" / f"{identity}.json"
    path.write_text('{"fixture":"macro"}')
    os.utime(path, (collected.timestamp(), collected.timestamp()))
    row = MacroObservation(
        id=identity,
        source_key="fred",
        symbol=f"DGS-{identity}",
        observation_date=date(2026, 9, 1),
        value=value,
        source_url="https://example.test/official",
        raw_path=f"raw/{identity}.json",
        retrieved_at=collected,
        run_id=str(producer) if producer else None,
    )
    session.add(row)
    return row


def add_candle(session, root, identity="candle"):
    collected = datetime.now(UTC) - timedelta(days=31)
    path = root / "raw" / f"{identity}.json"
    path.write_text('{"fixture":"candle"}')
    os.utime(path, (collected.timestamp(), collected.timestamp()))
    row = MarketCandle(
        id=identity,
        asset="XAUUSD",
        source="twelvedata_xauusd_5m",
        timeframe="5m",
        open_time=datetime(2026, 9, 1, tzinfo=UTC),
        open=4000,
        high=4010,
        low=3990,
        close=4005,
        volume=10,
        raw_path=f"raw/{identity}.json",
        source_ref={
            "retrieved_at": collected.isoformat(),
            "provider": "twelve_data",
            "provider_symbol": "XAU/USD",
            "instrument_type": "composite_otc_spot_proxy",
            "source_role": "validation",
            "quality_status": "accepted_validation",
        },
        created_at=collected,
        updated_at=collected,
    )
    session.add(row)
    return row


def scan(factory, root, datasets=("macro", "candles"), *, commit=True):
    with factory() as session:
        result = reconcile_warehouse(
            session, storage_root=root, datasets=datasets, page_size=10, max_pages=2
        )
        session.commit() if commit else session.rollback()
        return result


def counts(session):
    return {
        "batches": session.scalar(select(func.count()).select_from(LoadBatch)),
        "macro": session.scalar(select(func.count()).select_from(MacroFact)),
        "candles": session.scalar(select(func.count()).select_from(CandleFact)),
        "receipts": session.scalar(select(func.count()).select_from(RawSourceLoadBatch)),
        "tasks": session.scalar(select(func.count()).select_from(TaskRun)),
    }


@pytest.mark.parametrize("dataset", ["macro", "candles"])
def test_repeated_rejection_keeps_failed_audits_without_success_receipts(warehouse, dataset):
    factory, root = warehouse
    with factory.begin() as session:
        if dataset == "macro":
            add_macro(session, root).source_refs = [{"upstream": {"source": "jin10"}}]
        else:
            add_candle(session, root).source_ref = {"upstream": {"source": "jin10"}}
    first = scan(factory, root, (dataset,))
    with factory() as session:
        before = counts(session)
        batch_id = session.scalar(select(LoadBatch.id))
    second = scan(factory, root, (dataset,))
    assert first["status"] == second["status"] == "partial"
    for result in (first, second):
        page = result["datasets"][0]
        assert (page["processed"], page["rejected"], page["inserted"], page["skipped"]) == (1, 1, 0, 0)
        assert page["reused_batches"] == page["raw_ready"] == 0
        assert page["error_codes"] == ["DWH_NUMERIC_SOURCE_FORBIDDEN"]
    assert first["datasets"][0]["reused_rejected_batches"] == 0
    assert second["datasets"][0]["reused_rejected_batches"] == 1
    with factory.begin() as session:
        direct = load_warehouse(session, dataset, storage_root=root, dry_run=False,
                                reuse_unchanged_rejected=True)
        assert direct["load_batch_ids"] == [batch_id]
        assert direct["planned"] == direct["skipped"] == direct["inserted"] == 0
    with factory() as session:
        assert counts(session) == {**before, "tasks": before["tasks"] + 2}
        assert session.scalar(select(func.count()).select_from(BatchSourceFile)) == 0
        assert all(row.status == TaskStatus.failed for row in session.scalars(select(TaskRun)))
        assert all(row.status == StepStatus.failed for row in session.scalars(select(TaskStep)))
    assert apply_raw_retention(factory, storage_root=root)["deleted_count"] == 0
    assert list((root / "raw").glob("*.json"))


@pytest.mark.parametrize("field,value", [
    ("source_sha256", None), ("source_sha256", "0" * 64),
    ("transform_version", "old"), ("error_code", "different"),
    ("status", "loaded"), ("status", "partial"), ("processed", 2),
    ("rejected", 2), ("inserted", 1), ("skipped", 1), ("rule_version", "changed"),
    ("source_artifact_path", "raw/changed.json"),
])
def test_rejected_batch_tampering_never_reuses(warehouse, field, value):
    factory, root = warehouse
    with factory.begin() as session:
        add_macro(session, root).source_key = "jin10"
    scan(factory, root, ("macro",))
    with factory.begin() as session:
        setattr(session.scalar(select(LoadBatch)), field, value)
    result = scan(factory, root, ("macro",))["datasets"][0]
    assert result["reused_rejected_batches"] == 0 and result["rejected"] == 1
    with factory() as session:
        assert counts(session)["batches"] == 2


@pytest.mark.parametrize("change", ["value", "lineage", "source", "run", "producer", "transform"])
def test_rejected_input_or_producer_changes_create_new_batches(warehouse, monkeypatch, change):
    factory, root = warehouse
    producer = uuid4()
    with factory.begin() as session:
        session.add(TaskRun(id=producer, name="producer", status=TaskStatus.success,
                            started_at=datetime(2026, 9, 1, tzinfo=UTC), trade_date="2026-09-01"))
        add_macro(session, root, producer=producer).source_refs = [{"source": "jin10", "rule_version": "one"}]
    scan(factory, root, ("macro",))
    with factory.begin() as session:
        row = session.get(MacroObservation, "macro")
        if change == "value":
            row.value = 7
        elif change == "lineage":
            row.source_refs = [{"source": "jin10", "rule_version": "two"}]
        elif change == "source":
            row.source_url = "https://example.test/changed"
        elif change == "run":
            row.run_id = str(uuid4())
        elif change == "producer":
            session.get(TaskRun, producer).trade_date = "2026-09-02"
    if change == "transform":
        monkeypatch.setattr(etl, "TRANSFORM_VERSION", "changed-transform")
    result = scan(factory, root, ("macro",))["datasets"][0]
    assert result["reused_rejected_batches"] == 0 and result["rejected"] == 1
    assert scan(factory, root, ("macro",))["datasets"][0]["reused_rejected_batches"] == 1


def test_rejection_default_dry_run_and_rollback_remain_distinct(warehouse):
    factory, root = warehouse
    with factory.begin() as session:
        add_macro(session, root).source_key = "jin10"
    with factory.begin() as session:
        for _ in range(2):
            result = load_warehouse(session, "macro", storage_root=root, dry_run=False)
            assert result["reused_rejected_batches"] == 0
        assert session.scalar(select(func.count()).select_from(LoadBatch)) == 2
        assert all(row.source_sha256 is None for row in session.scalars(select(LoadBatch)))
    scan(factory, root, ("macro",))  # Old batches have no maintenance fingerprint.
    with factory() as session:
        before = counts(session)
        cursor_time = session.get(WarehouseSyncCursor, "macro").updated_at
        dry = load_warehouse(session, "macro", storage_root=root, dry_run=True,
                             reuse_unchanged_rejected=True)
        assert dry["rejected"] == 1 and dry["load_batch_ids"] == []
        assert dry["task_run_id"] is None and counts(session) == before
    assert scan(factory, root, ("macro",), commit=False)["datasets"][0]["reused_rejected_batches"] == 1
    with factory() as session:
        assert counts(session) == before
        assert session.get(WarehouseSyncCursor, "macro").updated_at == cursor_time
    with factory.begin() as session:
        session.get(MacroObservation, "macro").source_key = "fred"
    recovered = scan(factory, root, ("macro",))["datasets"][0]
    assert recovered["inserted"] == 1 and recovered["reused_rejected_batches"] == 0
    with factory() as session:
        with pytest.raises(WarehouseError, match="DWH_ARGUMENT_INVALID"):
            load_warehouse(session, "news-events", reuse_unchanged_rejected=True)


def test_rejected_latest_with_linked_fact_cannot_reuse(warehouse):
    factory, root = warehouse
    with factory.begin() as session:
        add_macro(session, root)
    scan(factory, root, ("macro",))
    with factory.begin() as session:
        session.get(MacroObservation, "macro").source_refs = [{"source": "jin10"}]
    scan(factory, root, ("macro",))
    with factory.begin() as session:
        latest = session.scalars(select(LoadBatch).order_by(LoadBatch.id.desc())).first()
        session.scalar(select(MacroFact)).batch_id = latest.id
    result = scan(factory, root, ("macro",))["datasets"][0]
    assert result["reused_rejected_batches"] == result["reused_batches"] == 0
    assert result["rejected"] == 1


def test_invalid_candle_rejection_reuse_and_producer_dimension_tampering(warehouse):
    factory, root = warehouse
    with factory.begin() as session:
        add_candle(session, root).high = 1  # Invalid OHLC, not a source-policy reject.
    first = scan(factory, root, ("candles",))["datasets"][0]
    second = scan(factory, root, ("candles",))["datasets"][0]
    assert second["error_codes"] == first["error_codes"]
    assert second["rejected"] == second["reused_rejected_batches"] == 1
    with factory.begin() as session:
        session.get(MarketCandle, "candle").high = 2
    changed = scan(factory, root, ("candles",))["datasets"][0]
    assert changed["reused_rejected_batches"] == 0 and changed["error_codes"] == first["error_codes"]
    with factory.begin() as session:
        session.get(MarketCandle, "candle").high = 4010
    assert scan(factory, root, ("candles",))["datasets"][0]["inserted"] == 1

    producer = uuid4()
    with factory.begin() as session:
        session.add(TaskRun(id=producer, name="producer", status=TaskStatus.success,
                            started_at=datetime(2026, 9, 1, tzinfo=UTC)))
        add_macro(session, root, producer=producer).unit = "x" * 65
    scan(factory, root, ("macro",))
    assert scan(factory, root, ("macro",))["datasets"][0]["reused_rejected_batches"] == 1
    with factory.begin() as session:
        session.scalar(select(ProducerRunDimension)).verified = False
    assert scan(factory, root, ("macro",))["datasets"][0]["reused_rejected_batches"] == 0


def test_mixed_page_reused_rejection_stays_partial_and_savepoint_failure_rolls_back(warehouse, monkeypatch):
    factory, root = warehouse
    with factory.begin() as session:
        add_macro(session, root, "bad").source_key = "jin10"
        add_macro(session, root, "good")
    scan(factory, root, ("macro",))
    with factory.begin() as session:
        page = load_warehouse(session, "macro", storage_root=root, dry_run=False,
                              reuse_unchanged_successful=True, reuse_unchanged_rejected=True)
        assert (page["rejected"], page["planned"], page["skipped"], page["inserted"]) == (1, 1, 1, 0)
        assert page["reused_batches"] == page["reused_rejected_batches"] == 1
        task_id = UUID(page["task_run_id"])
        assert session.get(TaskRun, task_id).status == TaskStatus.partial_success
        assert session.scalar(select(TaskStep).where(TaskStep.task_run_id == task_id)).status == StepStatus.failed
    with factory.begin() as session:
        session.get(MacroObservation, "good").value = 8
    with factory() as session:
        before = counts(session)

        def broken_insert(*args, **kwargs):
            raise RuntimeError("injected fact write failure")

        monkeypatch.setattr(etl, "insert_fact", broken_insert)
        with pytest.raises(WarehouseError, match="DWH_TRANSACTION_FAILED"):
            load_warehouse(session, "macro", storage_root=root, dry_run=False,
                           reuse_unchanged_rejected=True)
        assert counts(session) == before
        session.commit()
    with factory() as session:
        assert counts(session) == before


def test_unchanged_macro_and_candle_reuse_latest_batch_but_keep_scan_audits(warehouse):
    factory, root = warehouse
    with factory.begin() as session:
        add_macro(session, root)
        add_candle(session, root)
    first = scan(factory, root)
    with factory() as session:
        before = counts(session)
    second = scan(factory, root)
    with factory() as session:
        after = counts(session)

    assert [row["inserted"] for row in first["datasets"]] == [1, 1]
    assert [row["reused_batches"] for row in second["datasets"]] == [1, 1]
    assert after == {**before, "tasks": before["tasks"] + 2}
    assert before["batches"] == before["macro"] + before["candles"] == 2
    assert before["receipts"] == 2


def test_revision_latest_failure_recovery_and_late_record_are_not_reused(warehouse):
    factory, root = warehouse
    with factory.begin() as session:
        add_macro(session, root, "original")
    scan(factory, root, ("macro",))

    with factory.begin() as session:
        session.get(MacroObservation, "original").value = 4.5
    revised = scan(factory, root, ("macro",))["datasets"][0]
    assert revised["inserted"] == 1 and revised["reused_batches"] == 0

    with factory.begin() as session:
        current = session.get(MacroObservation, "original")
        current.source_refs = [{"source": "aggregate", "upstream": [{"source": "jin10"}]}]
    rejected = scan(factory, root, ("macro",))["datasets"][0]
    assert rejected["rejected"] == 1 and rejected["reused_batches"] == 0

    with factory.begin() as session:
        session.get(MacroObservation, "original").source_refs = []
        add_macro(session, root, "late")
    recovered = scan(factory, root, ("macro",))["datasets"][0]
    assert recovered["inserted"] == 1
    assert recovered["skipped"] == 1
    assert recovered["reused_batches"] == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MacroFact)) == 3
        latest = session.scalars(
            select(LoadBatch)
            .where(LoadBatch.source_cursor == "original")
            .order_by(LoadBatch.id.desc())
        ).first()
        assert latest.status == "loaded" and latest.rejected == 0


def test_transform_or_producer_change_is_processed_before_reuse(warehouse):
    factory, root = warehouse
    producer = uuid4()
    collected = datetime.now(UTC) - timedelta(days=31)
    with factory.begin() as session:
        session.add(
            TaskRun(
                id=producer,
                name="producer",
                status=TaskStatus.success,
                started_at=collected,
                trade_date="2026-09-01",
            )
        )
        add_macro(session, root, producer=producer)
    scan(factory, root, ("macro",))

    with factory.begin() as session:
        session.scalar(select(LoadBatch)).transform_version = "superseded-transform"
    refreshed = scan(factory, root, ("macro",))["datasets"][0]
    assert refreshed["reused_batches"] == 0 and refreshed["skipped"] == 1
    reused = scan(factory, root, ("macro",))["datasets"][0]
    assert reused["reused_batches"] == 1

    with factory.begin() as session:
        session.get(TaskRun, producer).started_at = collected + timedelta(minutes=1)
    producer_changed = scan(factory, root, ("macro",))["datasets"][0]
    assert producer_changed["reused_batches"] == 0
    assert producer_changed["skipped"] == 1


def test_reconciliation_rollback_does_not_advance_cursor_or_keep_new_batch(warehouse):
    factory, root = warehouse
    with factory.begin() as session:
        add_macro(session, root)
    scan(factory, root, ("macro",))
    with factory.begin() as session:
        session.get(MacroObservation, "macro").value = 4.5
    with factory() as session:
        before = counts(session)
        cursor_before = session.get(WarehouseSyncCursor, "macro").updated_at
    scan(factory, root, ("macro",), commit=False)
    with factory() as session:
        assert counts(session) == before
        assert session.get(WarehouseSyncCursor, "macro").updated_at == cursor_before
    assert scan(factory, root, ("macro",))["datasets"][0]["inserted"] == 1


@pytest.mark.parametrize("action", ["delete", "explicit_cutoff"])
def test_deleted_tombstone_unknown_missing_and_reappeared_file_are_distinct(warehouse, action):
    factory, root = warehouse
    with factory.begin() as session:
        add_macro(session, root)
    scan(factory, root, ("macro",))
    deleted = apply_raw_retention(factory, storage_root=root)
    assert deleted["deleted_count"] == 1
    with factory.begin() as session:
        session.scalar(select(RawRetentionEvent)).action = action
    with factory() as session:
        stable = counts(session)

    expired = scan(factory, root, ("macro",))["datasets"][0]
    assert (expired["raw_expired"], expired["raw_registered"], expired["raw_ready"]) == (1, 0, 0)
    assert expired["raw_blocked"] == []
    with factory() as session:
        current = counts(session)
        assert current["batches"] == stable["batches"]
        assert current["macro"] == stable["macro"]
        assert current["receipts"] == stable["receipts"]

    (root / "raw/macro.json").write_text('{"fixture":"new physical revision"}')
    reappeared = scan(factory, root, ("macro",))["datasets"][0]
    assert reappeared["raw_expired"] == 0
    assert reappeared["raw_registered"] == 1
    assert reappeared["raw_ready"] == 0
    assert reappeared["raw_blocked"] == [
        {"raw_path": "raw/macro.json", "reason": "RAW_REGISTRATION_REJECTED"}
    ]
    with factory() as session:
        revisions = session.scalars(select(RawSourceFile).order_by(RawSourceFile.created_at)).all()
        assert len(revisions) == 2
        assert revisions[0].state == "deleted" and revisions[1].state == "registered"

    with factory.begin() as session:
        session.add(
            MacroObservation(
                id="unknown-missing",
                source_key="fred",
                symbol="DGS-unknown",
                observation_date=date(2026, 9, 1),
                value=1,
                source_url="https://example.test/official",
                raw_path="raw/unknown-missing.json",
                retrieved_at=datetime.now(UTC) - timedelta(days=31),
            )
        )
    unknown = scan(factory, root, ("macro",))["datasets"][0]
    assert unknown["raw_expired"] == 0
    assert {item["raw_path"] for item in unknown["raw_blocked"]} >= {"raw/unknown-missing.json"}


def test_other_audit_actions_do_not_authorize_missing_file(warehouse):
    factory, root = warehouse
    with factory.begin() as session:
        add_macro(session, root)
    scan(factory, root, ("macro",))
    assert apply_raw_retention(factory, storage_root=root)["deleted_count"] == 1
    with factory.begin() as session:
        session.scalar(select(RawRetentionEvent)).action = "preview"

    missing = scan(factory, root, ("macro",))["datasets"][0]
    assert missing["raw_expired"] == 0
    assert missing["raw_ready"] == 0
    assert missing["raw_blocked"] == [
        {"raw_path": "raw/macro.json", "reason": "RAW_REGISTRATION_REJECTED"}
    ]


def test_old_tombstone_does_not_hide_loss_of_current_same_path_version(warehouse):
    factory, root = warehouse
    with factory.begin() as session:
        add_macro(session, root)
    scan(factory, root, ("macro",))
    assert apply_raw_retention(factory, storage_root=root)["deleted_count"] == 1

    (root / "raw/macro.json").write_text('{"fixture":"current version"}')
    with factory.begin() as session:
        row = session.get(MacroObservation, "macro")
        row.value = 4.75
        row.retrieved_at = datetime.now(UTC)
    current = scan(factory, root, ("macro",))["datasets"][0]
    assert current["raw_ready"] == 1

    (root / "raw/macro.json").unlink()
    missing = scan(factory, root, ("macro",))["datasets"][0]
    assert missing["raw_expired"] == 0
    assert {tuple(item.values()) for item in missing["raw_blocked"]} >= {
        ("raw/macro.json", "RAW_REGISTRATION_REJECTED")
    }


def test_unsafe_catalog_root_is_blocked_without_rolling_back_loaded_fact(warehouse):
    factory, root = warehouse
    with factory.begin() as session:
        add_macro(session, root)
    alias = root.parent / "untrusted-link"
    alias.symlink_to(root, target_is_directory=True)

    with factory() as session:
        result = ingest_collection_records(
            session, "macro", record_ids=["macro"], storage_root=alias
        )
        assert result["inserted"] == 1
        assert result["raw_blocked"] == [
            {"raw_path": "raw/macro.json", "reason": "RAW_REGISTRATION_REJECTED"}
        ]
        assert session.scalar(select(func.count()).select_from(MacroFact)) == 1


class _SessionStub:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def commit(self):
        pass


def test_maintenance_applies_bounded_retention_pages_with_one_cutoff(monkeypatch, tmp_path):
    monkeypatch.setattr(
        maintenance,
        "reconcile_warehouse",
        lambda *a, **k: {"status": "loaded", "datasets": []},
    )
    pages = [
        dict(
            task_run_id="one",
            cutoff="same",
            candidate_count=2,
            deleted_count=1,
            blocked_count=1,
            reconciled_count=0,
            deleted=[{"id": 1}],
            blocked=[{"id": 2, "reason": "LOAD_COVERAGE_INCOMPLETE"}],
            scan_started_after=None,
            scan_wrapped=False,
            scan_has_more=True,
            scan_next_cursor=(1, "a"),
        ),
        dict(
            task_run_id="two",
            cutoff="same",
            candidate_count=1,
            deleted_count=1,
            blocked_count=0,
            reconciled_count=2,
            deleted=[{"id": 3}],
            blocked=[],
            scan_started_after=(1, "a"),
            scan_wrapped=False,
            scan_has_more=False,
            scan_next_cursor=None,
        ),
    ]
    calls = []

    def apply(*args, **kwargs):
        calls.append(kwargs)
        return pages[len(calls) - 1]

    monkeypatch.setattr(raw_retention, "apply_raw_retention", apply)
    result = run_warehouse_maintenance(
        lambda: _SessionStub(), storage_root=tmp_path, page_size=2, max_pages=5, apply_retention=True
    )["raw_retention"]

    assert len(calls) == result["pages"] == 2
    assert calls[0]["now"] == calls[1]["now"]
    assert all(call["limit"] == 2 for call in calls)
    assert result["task_run_id"] == "one"
    assert result["task_run_ids"] == ["one", "two"]
    assert (result["candidate_count"], result["deleted_count"], result["blocked_count"]) == (3, 2, 1)
    assert result["reconciled_count"] == 2
    assert result["inspected_file_count"] == 3
    assert result["blocked_by_reason"] == {"LOAD_COVERAGE_INCOMPLETE": 1}
    assert result["blocked_file_count_by_reason"] == {"LOAD_COVERAGE_INCOMPLETE": 1}
    assert result["blocked_reason_count_basis"] == "blocked_entries"
    assert result["scan_has_more"] is False and result["scan_next_cursor"] is None


def test_retention_observability_counts_distinct_physical_identities():
    result = maintenance.enrich_raw_retention_result(
        {
            "candidates": [
                {"raw_path": "raw/a.json", "sha256": "a"},
            ],
            "blocked": [
                {"raw_path": "raw/shared.json", "sha256": "b", "reason": "PRODUCER_TASK_ACTIVE"},
                {"raw_path": "raw/shared.json", "sha256": "b", "reason": "PRODUCER_TASK_ACTIVE"},
            ],
        }
    )
    assert result["inspected_file_count"] == 2
    assert result["blocked_by_reason"] == {"PRODUCER_TASK_ACTIVE": 2}
    assert result["blocked_file_count_by_reason"] == {"PRODUCER_TASK_ACTIVE": 1}
    assert result["blocked_reason_count_basis"] == "blocked_entries"


def test_retention_observability_preserves_catalog_scan_count():
    result = maintenance.enrich_raw_retention_result(
        {
            "inspected_count": 3,
            "candidates": [{"raw_path": "raw/a.json", "sha256": "a"}],
            "blocked": [
                {"raw_path": "raw/shared.json", "sha256": "b", "reason": "PRODUCER_TASK_ACTIVE"},
            ],
        }
    )
    assert result["inspected_count"] == 3
    assert result["inspected_file_count"] == 2


def test_retention_aggregation_deduplicates_same_file_across_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(
        maintenance,
        "reconcile_warehouse",
        lambda *a, **k: {"status": "loaded", "datasets": []},
    )
    pages = [
        {
            "task_run_id": "one",
            "candidate_count": 0,
            "deleted_count": 0,
            "blocked_count": 1,
            "reconciled_count": 0,
            "deleted": [],
            "blocked": [{"raw_path": "raw/shared.bin", "sha256": "same", "reason": "RAW_FILE_HASH_CHANGED"}],
            "scan_has_more": True,
            "scan_next_cursor": (1, "a"),
        },
        {
            "task_run_id": "two",
            "candidate_count": 1,
            "deleted_count": 1,
            "blocked_count": 0,
            "reconciled_count": 0,
            "deleted": [{"raw_path": "raw/shared.bin", "sha256": "same"}],
            "blocked": [],
            "scan_has_more": False,
            "scan_next_cursor": None,
        },
    ]
    calls = []

    def apply(*args, **kwargs):
        calls.append(kwargs)
        return pages[len(calls) - 1]

    monkeypatch.setattr(raw_retention, "apply_raw_retention", apply)
    result = run_warehouse_maintenance(
        lambda: _SessionStub(), storage_root=tmp_path, page_size=1, max_pages=2, apply_retention=True
    )["raw_retention"]
    assert result["inspected_file_count"] == 1
    assert result["blocked_by_reason"] == {"RAW_FILE_HASH_CHANGED": 1}
    assert result["blocked_file_count_by_reason"] == {"RAW_FILE_HASH_CHANGED": 1}


def test_maintenance_stops_at_max_pages_and_preview_stays_single_page(monkeypatch, tmp_path):
    monkeypatch.setattr(
        maintenance,
        "reconcile_warehouse",
        lambda *a, **k: {"status": "loaded", "datasets": []},
    )
    calls = []

    def apply(*args, **kwargs):
        calls.append(kwargs)
        return dict(
            task_run_id=str(len(calls)),
            candidate_count=0,
            deleted_count=0,
            blocked_count=0,
            reconciled_count=0,
            deleted=[],
            blocked=[],
            scan_wrapped=False,
            scan_has_more=True,
            scan_next_cursor=(len(calls), "x"),
        )

    monkeypatch.setattr(raw_retention, "apply_raw_retention", apply)
    applied = run_warehouse_maintenance(
        lambda: _SessionStub(), storage_root=tmp_path, page_size=1, max_pages=2, apply_retention=True
    )["raw_retention"]
    assert len(calls) == applied["pages"] == 2
    assert applied["scan_has_more"] is True

    previews = []
    monkeypatch.setattr(
        raw_retention,
        "preview_raw_retention",
        lambda *a, **k: previews.append(k) or {"has_more": True},
    )
    preview = run_warehouse_maintenance(
        lambda: _SessionStub(), storage_root=tmp_path, page_size=1, max_pages=9, apply_retention=False
    )["raw_retention"]
    assert preview == {"has_more": True}
    assert len(previews) == 1
