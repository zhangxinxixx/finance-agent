from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import JSON, LargeBinary
from sqlalchemy.orm import sessionmaker

from database.models.raw_source import (
    RawSourceBase,
    RawSourceFile,
    RawSourceLoadBatch,
    ensure_raw_source_tables,
)
from database.models.warehouse import LoadBatch, WarehouseBase
from database.models.warehouse_sync import BatchSourceFile
from database.queries.raw_source import RawSourceError, record_raw_file_load, register_raw_file


@pytest.fixture
def db(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    WarehouseBase.metadata.create_all(engine)
    ensure_raw_source_tables(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def raw_file(tmp_path, name="source.bin", body=b"source"):
    path = tmp_path / "raw" / "provider" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def batch(
    db,
    *,
    dataset="macro",
    status="loaded",
    processed=2,
    inserted=2,
    skipped=0,
    rejected=0,
    source_artifact_path="raw/provider/source.bin",
    source_sha256=None,
):
    row = LoadBatch(
        dataset=dataset,
        source_cursor="source-1",
        source_artifact_path=source_artifact_path,
        source_sha256=source_sha256,
        transform_version="test",
        processed=processed,
        inserted=inserted,
        skipped=skipped,
        rejected=rejected,
        status=status,
        audit_task_run_id="audit-run",
        audit_task_step_id="audit-step",
    )
    db.add(row)
    db.flush()
    if dataset in {"macro", "candles"}:
        raw = db.scalar(select(RawSourceFile).where(RawSourceFile.raw_path == source_artifact_path))
        if raw:
            db.add(BatchSourceFile(batch_id=row.id, raw_path=raw.raw_path, storage_root=raw.storage_root,
                                   sha256=raw.sha256, byte_size=raw.byte_size, source_key=raw.source_key,
                                   collected_at=raw.collected_at, purpose="primary",
                                   batch_source_path=row.source_artifact_path,
                                   batch_source_sha256=row.source_sha256, batch_source_cursor=row.source_cursor))
            db.flush()
    return row


def test_schema_is_typed_portable_and_has_no_cross_metadata_foreign_keys(db):
    assert set(RawSourceBase.metadata.tables) == {
        "raw_source_file",
        "raw_source_load",
        "raw_source_load_batch",
        "raw_retention_event",
        "raw_retention_scan",
    }
    for table in RawSourceBase.metadata.tables.values():
        assert str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert not any(isinstance(column.type, (JSON, LargeBinary)) for column in table.c)
        assert not any(column.name in {"payload", "metadata", "value_json"} for column in table.c)
        assert all(foreign_key.column.table.metadata is RawSourceBase.metadata for foreign_key in table.foreign_keys)
    assert inspect(db.connection()).has_table("raw_source_file")


def test_register_validates_raw_path_hash_symlinks_and_preserves_revisions(db, tmp_path):
    path = raw_file(tmp_path)
    first = register_raw_file(
        db,
        storage_root=tmp_path,
        raw_path="raw/provider/source.bin",
        source_key="provider",
        collected_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert first.storage_root == str(tmp_path.resolve()) and first.byte_size == 6
    assert register_raw_file(
        db,
        storage_root=tmp_path,
        raw_path="raw/provider/source.bin",
        source_key="provider",
        collected_at=datetime(2026, 1, 1, tzinfo=UTC),
    ).id == first.id

    second_producer = register_raw_file(
        db,
        storage_root=tmp_path,
        raw_path="raw/provider/source.bin",
        source_key="provider",
        producer_run_id="producer-two",
        collected_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert second_producer.id != first.id and second_producer.sha256 == first.sha256
    path.write_bytes(b"revised")
    revised = register_raw_file(
        db,
        storage_root=tmp_path,
        raw_path="raw/provider/source.bin",
        source_key="provider",
        collected_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert revised.id != first.id and revised.sha256 != first.sha256

    with pytest.raises(RawSourceError, match="RAW_PATH_INVALID"):
        register_raw_file(
            db,
            storage_root=tmp_path,
            raw_path="raw/../outputs/report.md",
            source_key="provider",
            collected_at=datetime.now(UTC),
        )
    prefix = tmp_path / "raw_backup" / "not-raw.bin"
    prefix.parent.mkdir()
    prefix.write_bytes(b"not raw")
    with pytest.raises(RawSourceError, match="RAW_PATH_INVALID"):
        register_raw_file(
            db,
            storage_root=tmp_path,
            raw_path="raw_backup/not-raw.bin",
            source_key="provider",
            collected_at=datetime.now(UTC),
        )
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    link = tmp_path / "raw" / "provider" / "link.bin"
    link.symlink_to(outside)
    with pytest.raises(RawSourceError, match="RAW_FILE_UNSAFE_OR_MISSING"):
        register_raw_file(
            db,
            storage_root=tmp_path,
            raw_path="raw/provider/link.bin",
            source_key="provider",
            collected_at=datetime.now(UTC),
        )
    real_dir = tmp_path / "real-parent"
    real_dir.mkdir()
    (real_dir / "nested.bin").write_bytes(b"nested")
    (tmp_path / "raw" / "linked-parent").symlink_to(real_dir, target_is_directory=True)
    with pytest.raises(RawSourceError, match="RAW_FILE_UNSAFE_OR_MISSING"):
        register_raw_file(
            db,
            storage_root=tmp_path,
            raw_path="raw/linked-parent/nested.bin",
            source_key="provider",
            collected_at=datetime.now(UTC),
        )


def test_record_load_requires_real_matching_complete_batches(db, tmp_path):
    raw_file(tmp_path)
    raw = register_raw_file(
        db,
        storage_root=tmp_path,
        raw_path="raw/provider/source.bin",
        source_key="provider",
        collected_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    good = batch(db)
    load = record_raw_file_load(
        db,
        raw_file_id=raw.id,
        dataset="macro",
        expected_records=2,
        loaded_records=2,
        rejected_records=0,
        load_batch_ids=[good.id],
    )
    assert load.status == "completed" and raw.state == "loaded"
    assert db.scalar(select(RawSourceLoadBatch.batch_id)) == good.id
    assert record_raw_file_load(
        db,
        raw_file_id=raw.id,
        dataset="macro",
        expected_records=2,
        loaded_records=2,
        rejected_records=0,
        load_batch_ids=[good.id],
    ).id == load.id

    bad_dataset = batch(db, dataset="candles")
    with pytest.raises(RawSourceError, match="RAW_LOAD_DATASET_MISMATCH"):
        record_raw_file_load(
            db,
            raw_file_id=raw.id,
            dataset="macro",
            expected_records=2,
            loaded_records=2,
            rejected_records=0,
            load_batch_ids=[bad_dataset.id],
        )
    rejected = batch(db, status="partial", processed=2, inserted=1, rejected=1)
    with pytest.raises(RawSourceError, match="RAW_LOAD_BATCH_INCOMPLETE"):
        record_raw_file_load(
            db,
            raw_file_id=raw.id,
            dataset="macro",
            expected_records=2,
            loaded_records=2,
            rejected_records=0,
            load_batch_ids=[rejected.id],
        )
    with pytest.raises(RawSourceError, match="RAW_LOAD_INCOMPLETE"):
        record_raw_file_load(
            db,
            raw_file_id=raw.id,
            dataset="macro",
            expected_records=2,
            loaded_records=1,
            rejected_records=1,
            load_batch_ids=[good.id],
        )


@pytest.mark.parametrize(
    ("artifact_path", "error"),
    [
        (None, "RAW_LOAD_SOURCE_PATH_INVALID"),
        ("", "RAW_LOAD_SOURCE_PATH_INVALID"),
        ("raw/provider/other.bin", "RAW_LOAD_SOURCE_PATH_MISMATCH"),
        ("/outside/raw/provider/source.bin", "RAW_LOAD_SOURCE_PATH_INVALID"),
    ],
)
def test_load_receipt_rejects_missing_or_unrelated_source_path(db, tmp_path, artifact_path, error):
    raw_file(tmp_path)
    raw = register_raw_file(
        db,
        storage_root=tmp_path,
        raw_path="raw/provider/source.bin",
        source_key="provider",
        collected_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    unrelated = batch(db, source_artifact_path=artifact_path)
    with pytest.raises(RawSourceError, match=error):
        record_raw_file_load(
            db,
            raw_file_id=raw.id,
            dataset="macro",
            expected_records=2,
            loaded_records=2,
            rejected_records=0,
            load_batch_ids=[unrelated.id],
        )


def test_source_file_datasets_bind_hash_but_field_hash_datasets_do_not(db, tmp_path):
    path = raw_file(tmp_path)
    raw = register_raw_file(
        db,
        storage_root=tmp_path,
        raw_path="raw/provider/source.bin",
        source_key="provider",
        collected_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    missing_hash = batch(db, dataset="cme-options")
    with pytest.raises(RawSourceError, match="RAW_LOAD_SOURCE_HASH_MISSING"):
        record_raw_file_load(
            db,
            raw_file_id=raw.id,
            dataset="cme-options",
            expected_records=2,
            loaded_records=2,
            rejected_records=0,
            load_batch_ids=[missing_hash.id],
        )
    wrong_hash = batch(db, dataset="fedwatch", source_sha256="0" * 64)
    with pytest.raises(RawSourceError, match="RAW_LOAD_SOURCE_HASH_MISMATCH"):
        record_raw_file_load(
            db,
            raw_file_id=raw.id,
            dataset="fedwatch",
            expected_records=2,
            loaded_records=2,
            rejected_records=0,
            load_batch_ids=[wrong_hash.id],
        )
    exact = batch(
        db,
        dataset="settlement",
        source_artifact_path=str(path),
        source_sha256=raw.sha256.upper(),
    )
    assert record_raw_file_load(
        db,
        raw_file_id=raw.id,
        dataset="settlement",
        expected_records=2,
        loaded_records=2,
        rejected_records=0,
        load_batch_ids=[exact.id],
    ).status == "completed"

    field_version = batch(db, dataset="macro", source_sha256="f" * 64)
    assert record_raw_file_load(
        db,
        raw_file_id=raw.id,
        dataset="macro",
        expected_records=2,
        loaded_records=2,
        rejected_records=0,
        load_batch_ids=[field_version.id],
    ).status == "completed"
