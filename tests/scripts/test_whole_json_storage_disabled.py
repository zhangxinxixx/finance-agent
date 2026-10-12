# Real SQLite rows and real files: observe transactions as well as persisted state.
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from apps.data_layer.structured_artifacts import canonical_payload_sha256
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from database.models.analysis import AnalysisSnapshot
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.task import TaskRun, TaskStep, ensure_task_tables


import pytest
from scripts import backfill_structured_artifacts as blobs
from scripts import backfill_news_structured_artifacts as news


def forbidden(*args, **kwargs):
    raise AssertionError("disabled apply must not open database")


@pytest.mark.parametrize(
    "module,argv", [(blobs, ["--apply"]), (news, ["--apply", "--run-id", "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"])]
)
def test_old_cli_apply_cannot_write(module, argv):
    with pytest.raises(SystemExit) as exc:
        module.main(argv, session_factory=forbidden)
    assert exc.value.code == 2


def test_old_python_backfills_cannot_bypass_cli():
    with pytest.raises(ValueError, match="whole_json_backfill_disabled"):
        blobs.backfill_batch(session_factory=forbidden, storage=None, apply=True)
    with pytest.raises(ValueError, match="whole_json_backfill_disabled"):
        news.backfill_news_batch(session_factory=forbidden, storage_root=None, run_ids=[], apply=True)


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "storage"
    root.mkdir()
    db_path = tmp_path / "preview.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    AnalysisSnapshot.__table__.create(engine)
    yield engine, root, db_path
    engine.dispose()


def artifact(db, root, run_id, number, body, *, suffix="json", **fields):
    path = f"features/news/2026-10-12/{run_id}/{number}.{suffix}"
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(body)
    row = RunArtifact(
        artifact_id=uuid.UUID(int=0xAAAAAAAAAAAA4AAA8AAA000000000000 + number),
        run_id=run_id,
        artifact_type="feature_json",
        file_path=path,
        sha256=hashlib.sha256(body).hexdigest(),
        storage_backend="local_fs",
        **fields,
    )
    db.add(row)
    return row


@contextmanager
def read_only(archive):
    engine, root, db_path = archive

    def state():
        with sqlite3.connect(db_path) as conn:
            sql = tuple(conn.iterdump())
        files = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        return sql, files

    before = state()
    writes, commits = [], []

    def observe(conn, cursor, statement, params, context, many):
        if statement.lstrip().split()[0].upper() in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "ALTER",
            "DROP",
            "REPLACE",
        }:
            writes.append(statement)

    def committed(conn):
        commits.append(True)

    class PreviewSession(Session):
        def commit(self):
            raise AssertionError("preview must not commit")

    event.listen(engine, "before_cursor_execute", observe)
    event.listen(engine, "commit", committed)
    try:
        yield lambda: PreviewSession(engine)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
        event.remove(engine, "commit", committed)
        assert writes == []
        assert commits == []
        assert state() == before


def test_registered_preview_pagination_filters_and_historical_body(archive):
    engine, root, _ = archive
    run_id, other = uuid.uuid4(), uuid.uuid4()
    body = {"quality": "historical", "value": 7}
    with Session(engine) as db:
        artifact(
            db,
            root,
            run_id,
            1,
            json.dumps(body).encode(),
            structured_payload=body,
            structured_payload_sha256=canonical_payload_sha256(body),
            structured_status="persisted",
        )
        artifact(db, root, other, 2, b"{}")
        artifact(
            db, root, run_id, 3, b"{broken", structured_status="rejected", structured_error="STRUCTURED_JSON_INVALID"
        )
        db.commit()
    with read_only(archive) as factory:
        kwargs = dict(session_factory=factory, storage=LocalFileSystemArtifactStorage(root=root), run_ids=[str(run_id)])
        first = blobs.backfill_batch(**kwargs, limit=1)
        assert first == dict(
            dry_run=True,
            scanned=1,
            persisted=1,
            rejected=0,
            unavailable=0,
            not_applicable=0,
            skipped=1,
            written=0,
            next_cursor=str(uuid.UUID(int=0xAAAAAAAAAAAA4AAA8AAA000000000001)),
            has_more=True,
            audit_run_id=None,
            errors={},
        )
        second = blobs.backfill_batch(**kwargs, limit=1, after=first["next_cursor"])
        assert second == dict(
            first,
            persisted=0,
            rejected=1,
            skipped=0,
            has_more=False,
            next_cursor=str(uuid.UUID(int=0xAAAAAAAAAAAA4AAA8AAA000000000003)),
            errors={"STRUCTURED_JSON_INVALID": 1},
        )
        filtered = blobs.backfill_batch(**kwargs, status="rejected", error="STRUCTURED_JSON_INVALID")
        assert filtered == second
        empty = blobs.backfill_batch(**kwargs, after=second["next_cursor"])
        assert empty["scanned"] == 0 and empty["next_cursor"] is None and not empty["has_more"]


def test_registered_preview_valid_corrupt_missing_hash_and_size(archive):
    engine, root, _ = archive
    run_id = uuid.uuid4()
    with Session(engine) as db:
        artifact(db, root, run_id, 1, b"{}")
        artifact(db, root, run_id, 2, b'{"x":NaN}')
        artifact(db, root, run_id, 3, b"{}").sha256 = "0" * 64
        missing = artifact(db, root, run_id, 4, b"{}")
        (root / missing.file_path).unlink()
        artifact(db, root, run_id, 5, b"text", suffix="md")
        db.commit()
    with read_only(archive) as factory:
        kwargs = dict(session_factory=factory, storage=LocalFileSystemArtifactStorage(root=root))
        result = blobs.backfill_batch(**kwargs)
        assert (
            result["scanned"],
            result["persisted"],
            result["rejected"],
            result["unavailable"],
            result["not_applicable"],
            result["skipped"],
            result["written"],
        ) == (5, 1, 2, 1, 1, 0, 0)
        assert result["errors"] == {
            "STRUCTURED_JSON_NONFINITE": 1,
            "STRUCTURED_FILE_SHA_MISMATCH": 1,
            "STRUCTURED_FILE_MISSING": 1,
        }
        small = blobs.backfill_batch(**kwargs, limit=1, max_bytes=1)
        assert small["errors"] == {"STRUCTURED_FILE_TOO_LARGE": 1}


def snapshot(db, run_id, paths, *, corrupt_hash=False):
    payload = {"run_id": str(run_id), "news": {"data": {"artifact_paths": paths}}}
    db.add(
        AnalysisSnapshot(
            snapshot_id=f"snapshot:{run_id}",
            asset="XAUUSD",
            trade_date=date(2026, 10, 12),
            run_id=str(run_id),
            payload=payload,
            artifact_path="unused.json",
            payload_sha256="0" * 64
            if corrupt_hash
            else hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        )
    )


def test_news_preview_selection_existing_planned_and_snapshot_gaps(archive):
    engine, root, _ = archive
    chosen, invalid, mismatch, missing, excluded = [uuid.uuid4() for _ in range(5)]
    with Session(engine) as db:
        row = artifact(db, root, chosen, 1, b"{}")
        broken_path = f"features/news/2026-10-12/{chosen}/triggers.json"
        (root / broken_path).write_bytes(b"{broken")
        db.add(TaskRun(id=chosen, name="original producer"))
        db.add_all([TaskStep(task_run_id=chosen, name=stage) for stage in ("news_collect", "news_feature")])
        snapshot(db, chosen, {"collection_diagnostics": row.file_path, "daily_analysis_triggers": broken_path})
        snapshot(db, invalid, {}, corrupt_hash=True)
        snapshot(db, mismatch, {"daily_analysis_triggers": f"features/news/{excluded}/triggers.json"})
        snapshot(db, excluded, {})
        db.commit()
    with read_only(archive) as factory:
        runs = [str(chosen), str(invalid), str(mismatch), str(missing), str(chosen)]
        result = news.backfill_news_batch(session_factory=factory, storage_root=root, run_ids=runs)
        assert result == dict(
            dry_run=True,
            producer_runs=runs[:-1],
            planned=1,
            registered=0,
            persisted=1,
            rejected=1,
            unavailable=0,
            not_applicable=0,
            existing=1,
            audit_run_id=None,
            gaps=result["gaps"],
        )
        assert sorted(result["gaps"], key=lambda gap: gap["run_id"]) == sorted(
            [
                {"run_id": str(missing), "error": "news_source_snapshot_missing"},
                {"run_id": str(invalid), "error": "news_source_snapshot_invalid"},
                {"run_id": str(mismatch), "error": "news_source_snapshot_invalid"},
                {"run_id": str(chosen), "error": "news_original_task_step_missing", "stage": "news_brief"},
            ],
            key=lambda gap: gap["run_id"],
        )


def test_news_missing_file_exception_and_cli_sanitization(archive, capsys):
    engine, root, _ = archive
    run_id = uuid.uuid4()
    with Session(engine) as db:
        db.add(TaskRun(id=run_id, name="producer"))
        db.add(TaskStep(task_run_id=run_id, name="news_collect"))
        snapshot(db, run_id, {"collection_diagnostics": f"features/news/{run_id}/missing.json"})
        db.commit()
    with read_only(archive) as factory:
        with pytest.raises(FileNotFoundError):
            news.backfill_news_batch(session_factory=factory, storage_root=root, run_ids=[str(run_id)])
        assert (
            news.main(
                ["--run-id", str(run_id), "--storage-root", str(root)],
                session_factory=factory,
                project_root=root.parent,
            )
            == 1
        )
        assert json.loads(capsys.readouterr().out) == {"error": "news_structured_batch_failed", "dry_run": True}


@pytest.mark.parametrize(
    "kwargs", [{"limit": 0}, {"limit": 1001}, {"max_bytes": 0}, {"run_ids": ["invalid"]}, {"after": "invalid"}]
)
def test_registered_invalid_arguments_do_not_open_db(kwargs):
    with pytest.raises(ValueError):
        blobs.backfill_batch(session_factory=forbidden, storage=None, **kwargs)


@pytest.mark.parametrize(
    "runs,limit", [([], 20), (["invalid"], 20), ([str(uuid.uuid4())], 101), ([str(uuid.uuid4())] * 2, 1)]
)
def test_news_invalid_arguments_do_not_open_db(runs, limit):
    with pytest.raises(ValueError):
        news.backfill_news_batch(session_factory=forbidden, storage_root=None, run_ids=runs, limit=limit)


def test_registered_cli_preview(archive, capsys):
    engine, root, _ = archive
    run_id = uuid.uuid4()
    with Session(engine) as db:
        artifact(db, root, run_id, 1, b"{}")
        db.commit()
    with read_only(archive) as factory:
        argv = ["--run-id", str(run_id), "--storage-root", str(root), "--limit", "1"]
        assert blobs.main(argv, session_factory=factory, project_root=root.parent) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["persisted"] == 1 and result["written"] == 0 and result["audit_run_id"] is None


def test_news_cli_sanitizes_real_database_failure(archive, capsys):
    engine, root, _ = archive
    run_id = uuid.uuid4()
    # A real absent SQL table raises a driver error; CLI must hide its details.
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE analysis_snapshots")
    with read_only(archive) as factory:
        assert (
            news.main(
                ["--run-id", str(run_id), "--storage-root", str(root)],
                session_factory=factory,
                project_root=root.parent,
            )
            == 1
        )
        assert json.loads(capsys.readouterr().out) == {"error": "news_structured_batch_failed", "dry_run": True}


def test_old_schema_preview_reports_migration_without_ddl(archive, capsys):
    engine, root, _ = archive
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE run_artifacts")
        conn.exec_driver_sql("CREATE TABLE run_artifacts (artifact_id UUID PRIMARY KEY)")
    with read_only(archive) as factory:
        result = blobs.backfill_batch(session_factory=factory, storage=LocalFileSystemArtifactStorage(root=root))
        assert result["error"] == "structured_artifact_migration_required"
        assert result["scanned"] == result["written"] == 0
        assert blobs.main(["--storage-root", str(root)], session_factory=factory, project_root=root.parent) == 2
        assert json.loads(capsys.readouterr().out) == result
