from datetime import UTC, datetime, timedelta
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

import apps.data_layer.raw_retention as retention
from apps.data_layer.raw_retention import apply_raw_retention, preview_raw_retention
from database.models.raw_source import (
    RawRetentionEvent,
    RawRetentionScan,
    RawSourceBase,
    RawSourceFile,
    RawSourceLoad,
    RawSourceLoadBatch,
)
from database.models.task import Base, TaskRun, TaskStatus
from database.models.warehouse import LoadBatch, WarehouseBase
from database.models.warehouse_sync import BatchSourceFile
from database.queries.raw_source import record_raw_file_load, register_raw_file


NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    WarehouseBase.metadata.create_all(engine)
    RawSourceBase.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield engine, factory, tmp_path
    engine.dispose()


def add_file(
    factory,
    root,
    name,
    collected_at,
    *,
    loaded=True,
    producer_run_id=None,
    recent_mtime=False,
    mtime_days=None,
):
    path = root / "raw" / "source" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(name.encode())
    mtime = NOW - timedelta(days=mtime_days if mtime_days is not None else (1 if recent_mtime else 40))
    os.utime(path, (mtime.timestamp(), mtime.timestamp()))
    with factory.begin() as session:
        row = register_raw_file(
            session,
            storage_root=root,
            raw_path=path.relative_to(root).as_posix(),
            source_key="source",
            producer_run_id=producer_run_id,
            collected_at=collected_at,
        )
        if loaded:
            batch = LoadBatch(
                dataset="macro",
                source_cursor=row.id,
                source_artifact_path=row.raw_path,
                transform_version="test",
                processed=1,
                inserted=1,
                skipped=0,
                rejected=0,
                status="loaded",
                audit_task_run_id="audit",
                audit_task_step_id="step",
            )
            session.add(batch)
            session.flush()
            session.add(BatchSourceFile(batch_id=batch.id, raw_path=row.raw_path, storage_root=row.storage_root,
                                       sha256=row.sha256, byte_size=row.byte_size, source_key=row.source_key,
                                       collected_at=row.collected_at, purpose="primary",
                                       batch_source_path=batch.source_artifact_path,
                                       batch_source_sha256=batch.source_sha256, batch_source_cursor=batch.source_cursor))
            session.flush()
            record_raw_file_load(
                session,
                raw_file_id=row.id,
                dataset="macro",
                expected_records=1,
                loaded_records=1,
                rejected_records=0,
                load_batch_ids=[batch.id],
                completed_at=NOW - timedelta(days=39),
            )
        return row.id, path


def test_preview_exact_boundary_new_mtime_hash_and_incomplete_are_blocked(store):
    engine, factory, root = store
    old_id, _ = add_file(factory, root, "old.bin", NOW - timedelta(days=31))
    exact_id, _ = add_file(
        factory, root, "exact.bin", NOW - timedelta(days=30), mtime_days=30
    )
    add_file(factory, root, "new.bin", NOW - timedelta(days=29))
    add_file(factory, root, "recent-mtime.bin", NOW - timedelta(days=31), recent_mtime=True)
    add_file(factory, root, "unloaded.bin", NOW - timedelta(days=31), loaded=False)
    _, changed = add_file(factory, root, "changed.bin", NOW - timedelta(days=31))
    changed.write_bytes(b"changed after registration")

    before = []
    event.listen(engine, "before_cursor_execute", lambda *args: before.append(args[2]))
    with factory() as session:
        result = preview_raw_retention(session, storage_root=root, now=NOW)
    assert {item["raw_file_id"] for item in result["candidates"]} == {old_id, exact_id}
    assert {item["reason"] for item in result["blocked"]} == {
        "RETENTION_NOT_DUE",
        "RAW_FILE_MTIME_RECENT",
        "LOAD_COVERAGE_INCOMPLETE",
        "RAW_FILE_HASH_CHANGED",
    }
    assert before and all(statement.lstrip().upper().startswith(("SELECT", "PRAGMA")) for statement in before)


def test_multiple_producer_reference_and_active_task_block_physical_file(store):
    _, factory, root = store
    producer = uuid4()
    with factory.begin() as session:
        session.add(TaskRun(id=producer, name="producer", status=TaskStatus.running, started_at=NOW))
    _, path = add_file(factory, root, "shared.bin", NOW - timedelta(days=31))
    mtime = NOW - timedelta(days=40)
    os.utime(path, (mtime.timestamp(), mtime.timestamp()))
    add_file(factory, root, "shared.bin", NOW - timedelta(days=31), producer_run_id=producer)
    with factory() as session:
        result = preview_raw_retention(session, storage_root=root, now=NOW)
    assert result["candidate_count"] == 0
    assert result["blocked"][0]["reason"] == "PRODUCER_TASK_ACTIVE"
    assert len(result["blocked"][0]["reference_ids"]) == 2


def test_apply_deletes_only_raw_file_and_keeps_typed_load_and_batch(store):
    _, factory, root = store
    raw_id, path = add_file(factory, root, "delete.bin", NOW - timedelta(days=31))
    report = root / "reports" / "keep.md"
    report.parent.mkdir()
    report.write_text("keep")
    result = apply_raw_retention(factory, storage_root=root, now=NOW)
    assert result["deleted_count"] == 1 and not path.exists() and report.read_text() == "keep"
    with factory() as session:
        raw = session.get(RawSourceFile, raw_id)
        assert raw.state == "deleted" and raw.deleted_at == NOW
        assert session.scalar(select(func.count()).select_from(RawSourceLoad)) == 1
        assert session.scalar(select(func.count()).select_from(LoadBatch)) == 1
        event_row = session.scalar(select(RawRetentionEvent))
        assert event_row.status == "deleted" and event_row.sha256 == raw.sha256
        assert session.get(TaskRun, UUID(result["task_run_id"])).status == TaskStatus.success
    assert apply_raw_retention(factory, storage_root=root, now=NOW)["deleted_count"] == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(RawRetentionEvent)) == 1


def test_intent_commit_failure_does_not_move_or_unlink_file(store):
    engine, factory, root = store
    _, path = add_file(factory, root, "db-failure.bin", NOW - timedelta(days=31))

    class FailingCommitSession(Session):
        commit_calls = 0

        def commit(self):
            type(self).commit_calls += 1
            if type(self).commit_calls == 2:
                raise RuntimeError("injected intent commit failure")
            return super().commit()

    failing_factory = sessionmaker(engine, class_=FailingCommitSession, expire_on_commit=False)
    with pytest.raises(RuntimeError, match="intent commit"):
        apply_raw_retention(failing_factory, storage_root=root, now=NOW)
    assert path.exists()
    assert not list(path.parent.glob("*.raw-retention-*"))


def test_interrupted_after_unlink_is_reconciled_on_retry(store, monkeypatch):
    _, factory, root = store
    raw_id, path = add_file(factory, root, "interrupted.bin", NOW - timedelta(days=31))
    original = retention._mark_deleted

    def interrupt(*args, **kwargs):
        raise RuntimeError("simulated process interruption")

    monkeypatch.setattr(retention, "_mark_deleted", interrupt)
    with pytest.raises(RuntimeError, match="process interruption"):
        apply_raw_retention(factory, storage_root=root, now=NOW)
    assert not path.exists()
    monkeypatch.setattr(retention, "_mark_deleted", original)
    result = apply_raw_retention(factory, storage_root=root, now=NOW + timedelta(minutes=1))
    assert result["reconciled_count"] == 1
    with factory() as session:
        assert session.get(RawSourceFile, raw_id).state == "deleted"
        assert session.scalar(select(RawRetentionEvent)).status == "deleted"


def test_expired_intent_from_hard_interruption_can_be_retried(store, monkeypatch):
    _, factory, root = store
    _, path = add_file(factory, root, "intent-crash.bin", NOW - timedelta(days=31))
    original = retention._stage

    class ProcessCrash(BaseException):
        pass

    monkeypatch.setattr(retention, "_stage", lambda *args, **kwargs: (_ for _ in ()).throw(ProcessCrash()))
    with pytest.raises(ProcessCrash):
        apply_raw_retention(factory, storage_root=root, now=NOW)
    assert path.exists()

    still_owned = apply_raw_retention(factory, storage_root=root, now=NOW + timedelta(minutes=1))
    assert still_owned["reconciled_count"] == still_owned["deleted_count"] == 0
    assert path.exists()

    monkeypatch.setattr(retention, "_stage", original)
    result = apply_raw_retention(factory, storage_root=root, now=NOW + timedelta(minutes=16))
    assert result["reconciled_count"] == 1 and result["deleted_count"] == 1
    assert not path.exists()


def test_active_owner_protects_staged_file_then_expired_recovery_revalidates(store, monkeypatch):
    _, factory, root = store
    raw_id, path = add_file(factory, root, "staged-owner.bin", NOW - timedelta(days=31))
    original = retention._stage

    class ProcessCrash(BaseException):
        pass

    def move_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise ProcessCrash()

    monkeypatch.setattr(retention, "_stage", move_then_crash)
    with pytest.raises(ProcessCrash):
        apply_raw_retention(factory, storage_root=root, now=NOW)
    staged = list(path.parent.glob(".*.raw-retention-*"))
    assert not path.exists() and len(staged) == 1

    protected = apply_raw_retention(factory, storage_root=root, now=NOW + timedelta(minutes=1))
    assert protected["reconciled_count"] == protected["deleted_count"] == 0
    assert staged[0].exists()

    monkeypatch.setattr(retention, "_stage", original)
    recovered = apply_raw_retention(factory, storage_root=root, now=NOW + timedelta(minutes=16))
    assert recovered["reconciled_count"] == 1
    assert not staged[0].exists()
    with factory() as session:
        assert session.get(RawSourceFile, raw_id).state == "deleted"


def test_expired_staged_recovery_rechecks_batch_lineage_and_restores_source(store, monkeypatch):
    _, factory, root = store
    raw_id, path = add_file(factory, root, "staged-invalid.bin", NOW - timedelta(days=31))
    original = retention._stage

    class ProcessCrash(BaseException):
        pass

    def move_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise ProcessCrash()

    monkeypatch.setattr(retention, "_stage", move_then_crash)
    with pytest.raises(ProcessCrash):
        apply_raw_retention(factory, storage_root=root, now=NOW)
    with factory.begin() as session:
        link = session.scalar(
            select(RawSourceLoadBatch).join(RawSourceLoad, RawSourceLoad.id == RawSourceLoadBatch.load_id)
            .where(RawSourceLoad.raw_file_id == raw_id)
        )
        session.get(LoadBatch, link.batch_id).source_artifact_path = "raw/source/unrelated.bin"

    monkeypatch.setattr(retention, "_stage", original)
    result = apply_raw_retention(factory, storage_root=root, now=NOW + timedelta(minutes=16))
    assert result["reconciled_count"] == 1 and result["deleted_count"] == 0
    assert path.exists() and path.read_bytes() == b"staged-invalid.bin"
    with factory() as session:
        event_row = session.scalar(select(RawRetentionEvent))
        assert event_row.status == "blocked"
        assert event_row.error_code == "RAW_LOAD_SOURCE_BATCH_CHANGED"


def test_apply_scan_cursor_prevents_blocked_old_rows_from_starving_later_file(store):
    _, factory, root = store
    add_file(factory, root, "blocked-1.bin", NOW - timedelta(days=40), loaded=False)
    add_file(factory, root, "blocked-2.bin", NOW - timedelta(days=39), loaded=False)
    eligible_id, eligible_path = add_file(factory, root, "eligible.bin", NOW - timedelta(days=38))

    first = apply_raw_retention(factory, storage_root=root, now=NOW, limit=2)
    assert first["deleted_count"] == 0 and first["blocked_count"] == 2
    assert first["scan_next_cursor"] is not None
    second = apply_raw_retention(factory, storage_root=root, now=NOW, limit=2)
    assert second["deleted_count"] == 1 and not eligible_path.exists()
    with factory() as session:
        assert session.get(RawSourceFile, eligible_id).state == "deleted"
        assert session.get(RawRetentionScan, str(root.resolve())).last_file_id is None


def test_cleanup_rechecks_receipt_lineage_before_unlink(store):
    _, factory, root = store
    raw_id, path = add_file(factory, root, "receipt-mutated.bin", NOW - timedelta(days=31))
    with factory.begin() as session:
        link = session.scalar(
            select(RawSourceLoadBatch).join(RawSourceLoad, RawSourceLoad.id == RawSourceLoadBatch.load_id)
            .where(RawSourceLoad.raw_file_id == raw_id)
        )
        session.get(LoadBatch, link.batch_id).source_artifact_path = "raw/source/other.bin"
    result = apply_raw_retention(factory, storage_root=root, now=NOW)
    assert result["deleted_count"] == 0 and path.exists()
    assert {item["reason"] for item in result["blocked"]} == {"RAW_LOAD_SOURCE_BATCH_CHANGED"}


def test_restore_never_overwrites_new_source_and_unlink_detects_inode_swap(store, monkeypatch):
    _, _, root = store
    parent = root / "raw" / "source"
    parent.mkdir(parents=True, exist_ok=True)
    source = retention.PurePosixPath("raw/source/race.bin")
    staged = retention.PurePosixPath("raw/source/.race.bin.raw-retention-event")
    (root / source.as_posix()).write_bytes(b"new-source")
    (root / staged.as_posix()).write_bytes(b"old-source")
    old_hash, old_size, _ = retention.file_identity(root, staged)
    assert retention._restore(root, source, staged, old_hash, old_size) is False
    assert (root / source.as_posix()).read_bytes() == b"new-source"
    assert (root / staged.as_posix()).read_bytes() == b"old-source"

    replacement = parent / "replacement.bin"
    replacement.write_bytes(b"replacement")
    original_identity = retention.file_identity
    swapped = False

    def swap_after_read(read_root, relative):
        nonlocal swapped
        result = original_identity(read_root, relative)
        if relative == staged and not swapped:
            swapped = True
            os.rename(root / staged.as_posix(), parent / "saved-old.bin")
            os.rename(replacement, root / staged.as_posix())
        return result

    monkeypatch.setattr(retention, "file_identity", swap_after_read)
    with pytest.raises(retention.RawSourceError, match="RAW_RETENTION_STAGE_CHANGED"):
        retention._unlink_stage(root, staged, old_hash, old_size)
    assert (root / staged.as_posix()).read_bytes() == b"replacement"


def test_repeated_load_receipts_use_bounded_queries_and_recheck_changed_lineage(store):
    engine, factory, root = store
    raw_id, _ = add_file(factory, root, "many-receipts.bin", NOW - timedelta(days=40))
    with factory.begin() as session:
        original = session.scalar(select(RawSourceLoad).where(RawSourceLoad.raw_file_id == raw_id))
        batch_id = session.scalar(select(RawSourceLoadBatch.batch_id).where(RawSourceLoadBatch.load_id == original.id))
        for _ in range(200):
            load = RawSourceLoad(raw_file_id=raw_id, dataset=original.dataset, expected_records=1,
                loaded_records=1, rejected_records=0, status="completed", completed_at=NOW - timedelta(days=39))
            session.add(load)
            session.flush([load])
            session.add(RawSourceLoadBatch(load_id=load.id, batch_id=batch_id, ordinal=0))
    statements = []

    def observe(_conn, _cursor, statement, *_args):
        statements.append(statement)

    with factory() as session:
        raw = session.get(RawSourceFile, raw_id)
        event.listen(engine, "before_cursor_execute", observe)
        try:
            assert retention._load_coverage_error(session, raw) is None
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert len(statements) <= 10
        link = session.get(BatchSourceFile, (batch_id, raw.raw_path))
        link.sha256 = "0" * 64
        session.commit()
        assert retention._load_coverage_error(session, raw) == "RAW_LOAD_SOURCE_HASH_MISMATCH"
