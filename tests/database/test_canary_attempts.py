from __future__ import annotations

from datetime import UTC, date, datetime
from importlib import import_module

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from database.models.analysis import AnalysisBase
from database.models.analysis_state import CanaryAttempt
from database.queries.canary_attempts import (
    CanaryAttemptError,
    authorize_canary_recompute,
    create_or_resume_canary_attempt,
    mark_canary_attempt_audit_persisted,
    mark_canary_attempt_terminal,
)


NOW = datetime(2026, 7, 28, 2, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'attempts.db'}")
    AnalysisBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False), engine


def _start(session, *, attempt_no=0, canonical="state-0", version=1):
    return create_or_resume_canary_attempt(
        session,
        run_id="run-1",
        approval_id="approval-1",
        approval_hash=HASH_A,
        attempt_no=attempt_no,
        asset="XAUUSD",
        state_scope="daily_close",
        trade_date=date(2026, 7, 28),
        requested_canonical_state_id=canonical,
        expected_head_version=version,
        started_at=NOW,
    )


def test_create_or_resume_reuses_one_stable_attempt(tmp_path) -> None:
    factory, _ = _factory(tmp_path)
    with factory.begin() as first:
        original = _start(first)
        attempt_id = original.attempt_id
    with factory.begin() as second:
        resumed = _start(second)
        assert resumed.attempt_id == attempt_id
    with factory() as check:
        assert check.query(CanaryAttempt).count() == 1


def test_create_or_resume_recovers_concurrent_unique_winner_without_poisoning_transaction(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, _ = _factory(tmp_path)
    loser = factory()
    original_flush = loser.flush
    raced = False

    def racing_flush(*args, **kwargs):
        nonlocal raced
        if not raced and any(isinstance(item, CanaryAttempt) for item in loser.new):
            raced = True
            with factory.begin() as winner:
                _start(winner)
            raise IntegrityError("simulated unique race", {}, Exception("unique"))
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(loser, "flush", racing_flush)
    with loser.begin():
        recovered = _start(loser)
        assert recovered.run_id == "run-1"
        assert loser.query(CanaryAttempt).count() == 1
    loser.close()


def test_resume_rejects_changed_authority_identity(tmp_path) -> None:
    factory, _ = _factory(tmp_path)
    with factory.begin() as session:
        _start(session)
    with factory.begin() as session:
        with pytest.raises(CanaryAttemptError, match="approval_hash"):
            create_or_resume_canary_attempt(
                session,
                run_id="run-1",
                approval_id="approval-1",
                approval_hash=HASH_B,
                attempt_no=0,
                asset="XAUUSD",
                state_scope="daily_close",
                trade_date=date(2026, 7, 28),
                requested_canonical_state_id="state-0",
                expected_head_version=1,
                started_at=NOW,
            )


def test_attempt_one_requires_durable_recompute_authorization(tmp_path) -> None:
    factory, _ = _factory(tmp_path)
    with factory.begin() as session:
        attempt0 = _start(session)
        attempt0_id = attempt0.attempt_id
    with factory.begin() as session:
        with pytest.raises(CanaryAttemptError, match="recompute authorization"):
            _start(session, attempt_no=1, canonical="state-1", version=2)
    with factory.begin() as session:
        mark_canary_attempt_audit_persisted(
            session,
            attempt_id=attempt0_id,
            context_bundle_id="bundle-0",
            context_bundle_hash=HASH_B,
            authority_hash=HASH_C,
            artifact_path="attempt-0/id/hash.json",
            artifact_sha256=HASH_A,
            updated_at=NOW,
        )
        authorize_canary_recompute(session, attempt_id=attempt0_id, updated_at=NOW)
    with factory.begin() as session:
        attempt1 = _start(session, attempt_no=1, canonical="state-1", version=2)
        assert attempt1.attempt_no == 1


def test_audit_and_terminal_transitions_are_exactly_idempotent(tmp_path) -> None:
    factory, _ = _factory(tmp_path)
    with factory.begin() as session:
        attempt_id = _start(session).attempt_id
    audit = {
        "attempt_id": attempt_id,
        "context_bundle_id": "bundle-0",
        "context_bundle_hash": HASH_B,
        "authority_hash": HASH_C,
        "artifact_path": "attempt-0/id/hash.json",
        "artifact_sha256": HASH_A,
        "updated_at": NOW,
    }
    with factory.begin() as session:
        mark_canary_attempt_audit_persisted(session, **audit)
    with factory.begin() as session:
        mark_canary_attempt_audit_persisted(session, **audit)
        with pytest.raises(CanaryAttemptError, match="audit identity changed"):
            mark_canary_attempt_audit_persisted(
                session,
                **{**audit, "artifact_sha256": HASH_B},
            )
    terminal = {
        "attempt_id": attempt_id,
        "terminal_status": "failed",
        "artifact_path": "terminal/hash.json",
        "artifact_sha256": HASH_C,
        "updated_at": NOW,
    }
    with factory.begin() as session:
        mark_canary_attempt_terminal(session, **terminal)
    with factory.begin() as session:
        mark_canary_attempt_terminal(session, **terminal)
        with pytest.raises(CanaryAttemptError, match="terminal identity changed"):
            mark_canary_attempt_terminal(
                session,
                **{**terminal, "artifact_sha256": HASH_A},
            )


def test_schema_has_named_attempt_uniqueness_and_indexes(tmp_path) -> None:
    _, engine = _factory(tmp_path)
    schema = inspect(engine)
    unique_names = {item["name"] for item in schema.get_unique_constraints("canary_attempts")}
    index_names = {item["name"] for item in schema.get_indexes("canary_attempts")}
    assert "uq_canary_attempts_run_attempt" in unique_names
    assert {
        "ix_canary_attempts_run_status",
        "ix_canary_attempts_approval_id",
        "ix_canary_attempts_updated_at",
    }.issubset(index_names)


def test_linear_alembic_upgrade_adds_attempt_table_after_approval(tmp_path) -> None:
    from database.migrations.runtime import build_alembic_config

    attempt_revision = import_module(
        "database.migrations.versions.20260728_0005_add_canary_attempts"
    )
    assert attempt_revision.down_revision == "20260728_0004"

    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = build_alembic_config(database_url)
    engine = create_engine(database_url)
    command.upgrade(config, "20260728_0004")
    assert "canary_approvals" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260728_0004"
    command.upgrade(config, "20260728_0005")
    schema = inspect(engine)
    assert "canary_attempts" in schema.get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260728_0005"
    assert "uq_canary_attempts_run_attempt" in {
        item["name"] for item in schema.get_unique_constraints("canary_attempts")
    }
