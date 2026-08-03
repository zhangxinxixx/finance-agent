"""Production-caller coverage for Gold Policy bundle registry delivery."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.analysis.gold_policy.daily_close_store import verify_gold_daily_close_bundle
from database.models.analysis import ensure_analysis_tables
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables
from scripts import run_gold_daily_report as report


_FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "gold_daily_report" / "premarket_snapshot_2026-07-07.json"
_FIXTURE_SHA256 = "85dd2f24075812d62206ee12d1e5fea37d892e3cb2c9360a3c73d0a3e07a4d97"


def _make_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _materialize_snapshot(storage_root: Path) -> str:
    fixture_bytes = _FIXTURE_PATH.read_bytes()
    assert hashlib.sha256(fixture_bytes).hexdigest() == _FIXTURE_SHA256
    payload = json.loads(fixture_bytes.decode("utf-8"))
    trade_date = payload["trade_date"]
    target = (
        storage_root / "features" / "snapshots" / "XAUUSD" / trade_date / payload["run_id"] / "premarket_snapshot.json"
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(fixture_bytes)
    return trade_date


def _generate_bundle(storage_root: Path) -> dict[str, Any]:
    trade_date = _materialize_snapshot(storage_root)
    result = report.run_gold_daily_report(
        trade_date=trade_date,
        storage_root=storage_root,
    )
    assert result["status"] == "completed", result
    return result


@pytest.fixture(autouse=True)
def _disable_jin10(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", "true")


@pytest.fixture(scope="module")
def existing_bundle_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    storage_root = tmp_path_factory.mktemp("gold-production-existing")
    previous = os.environ.get("FINANCE_AGENT_DISABLE_JIN10")
    os.environ["FINANCE_AGENT_DISABLE_JIN10"] = "true"
    try:
        _generate_bundle(storage_root)
    finally:
        if previous is None:
            os.environ.pop("FINANCE_AGENT_DISABLE_JIN10", None)
        else:
            os.environ["FINANCE_AGENT_DISABLE_JIN10"] = previous
    return storage_root


def _copy_existing_bundle(template: Path, tmp_path: Path) -> Path:
    target = tmp_path / "storage"
    shutil.copytree(template, target)
    return target


def _invoke_main(
    *,
    storage_root: Path,
    session_factory: Callable[[], Any],
    capsys: pytest.CaptureFixture[str],
    extra_args: list[str] | None = None,
) -> tuple[int, dict[str, Any]]:
    exit_code = report.main(
        [
            "--date",
            "2026-07-07",
            "--storage-root",
            str(storage_root),
            *(extra_args or []),
        ],
        session_factory=session_factory,
    )
    payload = json.loads(capsys.readouterr().out)
    return exit_code, payload


def _bundle_path(result: dict[str, Any]) -> Path:
    return Path(result["report_paths"][0]).parent


def _assert_valid_bundle(storage_root: Path, result: dict[str, Any]) -> None:
    verification = verify_gold_daily_close_bundle(
        storage_root=storage_root,
        bundle_path=_bundle_path(result),
    )
    assert verification.status == "valid", verification


def test_fresh_cli_registers_real_bundle_and_commits(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage_root = tmp_path / "storage"
    _materialize_snapshot(storage_root)
    factory = _make_session_factory()

    exit_code, result = _invoke_main(
        storage_root=storage_root,
        session_factory=factory,
        capsys=capsys,
    )

    assert exit_code == 0
    assert result["status"] == "completed"
    assert result["registry_status"] == "registered"
    assert result["report_id"].startswith("gold_policy_daily:2026-07-07:")
    _assert_valid_bundle(storage_root, result)
    with factory() as db:
        assert db.query(ReportItem).count() == 1
        assert db.query(ReportArtifact).count() == 9


def test_existing_valid_bundle_recovers_into_empty_registry(
    existing_bundle_template: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage_root = _copy_existing_bundle(existing_bundle_template, tmp_path)
    factory = _make_session_factory()

    exit_code, result = _invoke_main(
        storage_root=storage_root,
        session_factory=factory,
        capsys=capsys,
    )

    assert exit_code == 0
    assert result["registry_status"] == "registered"
    _assert_valid_bundle(storage_root, result)
    with factory() as db:
        assert db.query(ReportItem).count() == 1
        assert db.query(ReportArtifact).count() == 9


def test_repeated_cli_registration_is_idempotent(
    existing_bundle_template: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage_root = _copy_existing_bundle(existing_bundle_template, tmp_path)
    factory = _make_session_factory()

    first_code, first = _invoke_main(
        storage_root=storage_root,
        session_factory=factory,
        capsys=capsys,
    )
    second_code, second = _invoke_main(
        storage_root=storage_root,
        session_factory=factory,
        capsys=capsys,
    )

    assert first_code == second_code == 0
    assert first["report_id"] == second["report_id"]
    assert first["registry_status"] == second["registry_status"] == "registered"
    with factory() as db:
        assert db.query(ReportItem).count() == 1
        assert db.query(ReportArtifact).count() == 9


def test_dry_run_does_not_create_database_session(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage_root = tmp_path / "storage"
    _materialize_snapshot(storage_root)
    calls = 0

    def forbidden_factory() -> Session:
        nonlocal calls
        calls += 1
        raise AssertionError("dry-run must not create a DB session")

    exit_code, result = _invoke_main(
        storage_root=storage_root,
        session_factory=forbidden_factory,
        capsys=capsys,
        extra_args=["--dry-run"],
    )

    assert exit_code == 0
    assert result["status"] == "dry_run"
    assert "registry_status" not in result
    assert calls == 0


def test_registry_failure_blocks_delivery_but_preserves_valid_bundle(
    existing_bundle_template: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = _copy_existing_bundle(existing_bundle_template, tmp_path)
    factory = _make_session_factory()

    def fail_registry(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("injected registry failure")

    monkeypatch.setattr(report, "register_gold_policy_report_bundle", fail_registry)
    exit_code, result = _invoke_main(
        storage_root=storage_root,
        session_factory=factory,
        capsys=capsys,
    )

    assert exit_code == 2
    assert result["status"] == "blocked"
    assert result["reason"] == "gold_report_registry_failed"
    assert result["registry_status"] == "failed"
    assert result["report_paths"]
    _assert_valid_bundle(storage_root, result)
    with factory() as db:
        assert db.query(ReportItem).count() == 0
        assert db.query(ReportArtifact).count() == 0


class _CommitFailSession:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.rolled_back = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    def commit(self) -> None:
        raise RuntimeError("injected commit failure")

    def rollback(self) -> None:
        self.rolled_back = True
        self._session.rollback()

    def close(self) -> None:
        self._session.close()


def test_commit_failure_rolls_back_and_never_claims_registered(
    existing_bundle_template: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage_root = _copy_existing_bundle(existing_bundle_template, tmp_path)
    factory = _make_session_factory()
    sessions: list[_CommitFailSession] = []

    def failing_commit_factory() -> _CommitFailSession:
        wrapped = _CommitFailSession(factory())
        sessions.append(wrapped)
        return wrapped

    exit_code, result = _invoke_main(
        storage_root=storage_root,
        session_factory=failing_commit_factory,
        capsys=capsys,
    )

    assert exit_code == 2
    assert result["status"] == "blocked"
    assert result["reason"] == "gold_report_registry_commit_failed"
    assert result["registry_status"] == "failed"
    assert result["report_id"]
    assert sessions[0].rolled_back is True
    _assert_valid_bundle(storage_root, result)


def test_session_creation_failure_is_commit_failure(
    existing_bundle_template: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage_root = _copy_existing_bundle(existing_bundle_template, tmp_path)

    def fail_factory() -> Session:
        raise RuntimeError("postgresql://user:super-secret@host/db")

    exit_code, result = _invoke_main(
        storage_root=storage_root,
        session_factory=fail_factory,
        capsys=capsys,
    )

    assert exit_code == 2
    assert result["status"] == "blocked"
    assert result["reason"] == "gold_report_registry_commit_failed"
    assert result["registry_status"] == "failed"
    assert "report_paths" not in result
    emitted = json.dumps(result, ensure_ascii=False)
    assert "super-secret" not in emitted
    assert "postgresql://" not in emitted
