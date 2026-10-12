from datetime import UTC, datetime, timedelta
import json

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from database.models.raw_source import RawRetentionEvent, RawRetentionScan, RawSourceBase
from database.models.task import Base, TaskRun
from database.models.warehouse import WarehouseBase
from scripts.prune_raw_sources import main


def factory():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    WarehouseBase.metadata.create_all(engine)
    RawSourceBase.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)


def test_cli_requires_database_url(monkeypatch, tmp_path, capsys):
    (tmp_path / "raw").mkdir()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert main(["--storage-root", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "RAW_RETENTION_DATABASE_URL_REQUIRED"


def test_cli_defaults_to_read_only_preview_and_apply_is_explicit(tmp_path, capsys):
    engine, sessions = factory()
    (tmp_path / "raw").mkdir()
    assert main(["--storage-root", str(tmp_path)], session_factory=sessions) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True and result["total_count"] == 0
    assert result["blocked_by_reason"] == {} and result["inspected_file_count"] == 0
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(TaskRun)) == 0
        assert session.scalar(select(func.count()).select_from(RawRetentionEvent)) == 0
        assert session.scalar(select(func.count()).select_from(RawRetentionScan)) == 0

    assert main(["--storage-root", str(tmp_path), "--apply"], session_factory=sessions) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is False and result["task_run_id"]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(TaskRun)) == 1
    engine.dispose()


def test_cli_as_of_is_normalized_and_invalid_time_is_rejected(tmp_path, capsys):
    engine, sessions = factory()
    (tmp_path / "raw").mkdir()
    assert main(
        ["--storage-root", str(tmp_path), "--as-of", "2026-10-10T12:00:00+08:00"],
        session_factory=sessions,
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["as_of"] == "2026-10-10T04:00:00+00:00"
    assert result["cutoff"] == "2026-09-10T04:00:00+00:00"

    assert main(["--storage-root", str(tmp_path), "--as-of", "not-a-time"], session_factory=sessions) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "RAW_RETENTION_NOW_INVALID"
    engine.dispose()


def test_cli_apply_rejects_future_as_of_before_creating_task(tmp_path, capsys):
    engine, sessions = factory()
    (tmp_path / "raw").mkdir()
    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    assert main(
        ["--storage-root", str(tmp_path), "--as-of", future, "--apply"],
        session_factory=sessions,
    ) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "RAW_RETENTION_NOW_FUTURE"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(TaskRun)) == 0
    engine.dispose()


def test_cli_bounds_are_enforced(tmp_path, capsys):
    engine, sessions = factory()
    (tmp_path / "raw").mkdir()
    assert main(["--storage-root", str(tmp_path), "--limit", "0"], session_factory=sessions) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "RAW_RETENTION_LIMIT_INVALID"
    assert main(["--storage-root", str(tmp_path), "--retention-days", "0"], session_factory=sessions) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "RAW_RETENTION_DAYS_INVALID"
    engine.dispose()
