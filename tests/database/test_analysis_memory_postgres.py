"""PostgreSQL-only migration lifecycle and canonical-head CAS checks."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from typing import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from apps.analysis.state import (
    CanonicalHeadConflictError,
    StateMaterializationAuthority,
    advance_canonical_head,
    advance_canonical_head_scoped,
)
from database.migrations.runtime import build_alembic_config
from database.models.analysis import AnalysisSnapshot
from database.models.analysis_state import AnalysisState, AnalysisStateHead, CanaryApproval, CanaryAttempt
from database.queries.canary_approvals import (
    CanaryApprovalConsumptionError,
    consume_canary_approval,
    issue_canary_approval,
)
from database.queries.canary_attempts import create_or_resume_canary_attempt


POSTGRES_URL_ENV = "ANALYSIS_MEMORY_POSTGRES_URL"
STATE_TABLES = {"analysis_states", "analysis_state_heads", "analysis_transitions"}


def _postgres_url() -> str:
    database_url = os.getenv(POSTGRES_URL_ENV)
    if not database_url:
        pytest.skip(f"{POSTGRES_URL_ENV} is required for PostgreSQL migration checks")
    if make_url(database_url).get_backend_name() != "postgresql":
        pytest.fail(f"{POSTGRES_URL_ENV} must use PostgreSQL")
    return database_url


def _render_url(url: URL) -> str:
    return url.render_as_string(hide_password=False)


@contextmanager
def _isolated_schema(database_url: str) -> Iterator[str]:
    schema_name = f"analysis_memory_ci_{uuid.uuid4().hex}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    schema_url = make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema_name}"},
        append=False,
    )
    try:
        yield _render_url(schema_url)
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        admin_engine.dispose()


def _table_names(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_postgres_fresh_and_incremental_migration_lifecycle() -> None:
    database_url = _postgres_url()

    with _isolated_schema(database_url) as fresh_url:
        config = build_alembic_config(fresh_url)
        command.upgrade(config, "head")
        assert STATE_TABLES <= _table_names(fresh_url)

        engine = create_engine(fresh_url)
        state_id = "00000000-0000-0000-0000-000000000074"
        try:
            with engine.begin() as connection:
                connection.execute(
                    AnalysisState.__table__.insert().values(
                        id=state_id,
                        schema_version="1.0",
                        asset="XAUUSD",
                        state_scope="daily_close",
                        as_of=datetime(2026, 7, 22, 8, tzinfo=UTC),
                        task_run_id="issue-74-repeat",
                        quality_gate_action="manual_review",
                        publish_allowed=False,
                        accepted_output_source="none",
                        input_snapshot_ids={},
                        source_refs=[],
                        evidence_cursors={},
                        payload={"asset": "XAUUSD"},
                        content_hash="0" * 64,
                    )
                )
            command.upgrade(config, "head")
            with engine.connect() as connection:
                assert connection.scalar(select(AnalysisState.id).where(AnalysisState.id == state_id)) == state_id
            command.check(config)
        finally:
            engine.dispose()

        command.downgrade(config, "20260704_0001")
        assert STATE_TABLES.isdisjoint(_table_names(fresh_url))
        command.upgrade(config, "head")
        assert STATE_TABLES <= _table_names(fresh_url)

    with _isolated_schema(database_url) as incremental_url:
        config = build_alembic_config(incremental_url)
        command.upgrade(config, "20260704_0001")
        assert STATE_TABLES.isdisjoint(_table_names(incremental_url))

        engine = create_engine(incremental_url)
        snapshot_id = "snapshot-issue-74-existing"
        try:
            with engine.begin() as connection:
                connection.execute(
                    AnalysisSnapshot.__table__.insert().values(
                        id="00000000-0000-0000-0000-000000000075",
                        snapshot_id=snapshot_id,
                        asset="XAUUSD",
                        trade_date=date(2026, 7, 22),
                        run_id="issue-74-incremental",
                        status="success",
                        input_snapshot_ids={},
                        source_refs=[],
                        payload={"asset": "XAUUSD"},
                        payload_sha256="1" * 64,
                        artifact_path="outputs/issue-74.json",
                    )
                )
            command.upgrade(config, "20260722_0002")
            legacy_state_id = "00000000-0000-0000-0000-000000000082"
            legacy_payload = '{"asset":"XAUUSD","schema_version":"1.0"}'
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO analysis_states "
                        "(id, schema_version, asset, as_of, task_run_id, quality_gate_action, "
                        "publish_allowed, accepted_output_source, input_snapshot_ids, source_refs, "
                        "evidence_cursors, payload, content_hash) VALUES "
                        "(:id, '1.0', 'XAUUSD', :as_of, 'issue-75-v1', 'manual_review', "
                        "false, 'none', '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, "
                        "CAST(:payload AS jsonb), :content_hash)"
                    ),
                    {
                        "id": legacy_state_id,
                        "as_of": datetime(2026, 7, 22, 8, tzinfo=UTC),
                        "payload": legacy_payload,
                        "content_hash": "3" * 64,
                    },
                )
                before = connection.execute(
                    text(
                        "SELECT id, payload::text, content_hash FROM analysis_states WHERE id = :id"
                    ),
                    {"id": legacy_state_id},
                ).one()
            command.upgrade(config, "head")
            assert STATE_TABLES <= _table_names(incremental_url)
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        select(AnalysisSnapshot.snapshot_id).where(AnalysisSnapshot.snapshot_id == snapshot_id)
                    )
                    == snapshot_id
                )
                after = connection.execute(
                    text(
                        "SELECT id, payload::text, content_hash FROM analysis_states WHERE id = :id"
                    ),
                    {"id": legacy_state_id},
                ).one()
                assert tuple(after) == tuple(before)
                assert connection.scalar(
                    text("SELECT state_scope FROM analysis_states WHERE id = :id"),
                    {"id": legacy_state_id},
                ) == "daily_close"
            command.upgrade(config, "head")
            command.check(config)
        finally:
            engine.dispose()


def test_canonical_head_cas_uses_real_postgresql() -> None:
    database_url = _postgres_url()
    with _isolated_schema(database_url) as schema_url:
        command.upgrade(build_alembic_config(schema_url), "head")
        engine = create_engine(schema_url)
        authority = StateMaterializationAuthority(
            quality_gate_action="pass",
            publish_allowed=True,
            accepted_output_source="primary",
            accepted_output_agent_name="coordinator_agent",
            accepted_output_snapshot_id="snapshot-issue-74",
        )
        root_id = "00000000-0000-0000-0000-000000000076"
        winner_id = "00000000-0000-0000-0000-000000000077"
        stale_id = "00000000-0000-0000-0000-000000000078"

        def state_values(
            state_id: str, previous_state_id: str | None, *, state_scope: str = "daily_close"
        ) -> dict:
            return {
                "id": state_id,
                "schema_version": "1.0",
                "asset": "XAUUSD",
                "state_scope": state_scope,
                "as_of": datetime(2026, 7, 22, 8, tzinfo=UTC),
                "previous_state_id": previous_state_id,
                "task_run_id": f"issue-74-{state_id[-2:]}",
                "quality_gate_action": "pass",
                "publish_allowed": True,
                "accepted_output_source": "primary",
                "accepted_output_agent_name": "coordinator_agent",
                "accepted_output_snapshot_id": "snapshot-issue-74",
                "input_snapshot_ids": {"market": "snapshot-issue-74"},
                "source_refs": [{"snapshot_id": "snapshot-issue-74"}],
                "evidence_cursors": {},
                "payload": {"asset": "XAUUSD", "state_id": state_id},
                "content_hash": state_id.replace("-", "").ljust(64, "0"),
            }

        try:
            with engine.begin() as connection:
                connection.execute(
                    AnalysisState.__table__.insert(),
                    [
                        state_values(root_id, None),
                        state_values(winner_id, root_id),
                        state_values(stale_id, root_id),
                    ],
                )
                connection.execute(
                    AnalysisStateHead.__table__.insert().values(
                        id="00000000-0000-0000-0000-000000000079",
                        asset="XAUUSD",
                        state_scope="daily_close",
                        canonical_state_id=root_id,
                        version=1,
                    )
                )

            with Session(engine) as winner, Session(engine) as stale:
                winner_head = winner.scalar(
                    select(AnalysisStateHead).where(AnalysisStateHead.asset == "XAUUSD")
                )
                stale_head = stale.scalar(select(AnalysisStateHead).where(AnalysisStateHead.asset == "XAUUSD"))
                assert winner_head is not None and stale_head is not None
                assert (winner_head.canonical_state_id, winner_head.version) == (root_id, 1)
                assert (stale_head.canonical_state_id, stale_head.version) == (root_id, 1)

                advance_canonical_head(
                    winner,
                    asset="XAUUSD",
                    new_state_id=winner_id,
                    expected_state_id=root_id,
                    expected_version=1,
                    authority=authority,
                )
                winner.commit()

                with pytest.raises(CanonicalHeadConflictError, match="compare-and-swap conflict"):
                    advance_canonical_head(
                        stale,
                        asset="XAUUSD",
                        new_state_id=stale_id,
                        expected_state_id=root_id,
                        expected_version=1,
                        authority=authority,
                    )

            with Session(engine) as verify:
                head = verify.scalar(select(AnalysisStateHead).where(AnalysisStateHead.asset == "XAUUSD"))
                assert head is not None
                assert (head.canonical_state_id, head.version) == (winner_id, 2)

            intraday_root = "00000000-0000-0000-0000-000000000083"
            intraday_next = "00000000-0000-0000-0000-000000000084"
            with engine.begin() as connection:
                connection.execute(
                    AnalysisState.__table__.insert(),
                    [
                        state_values(intraday_root, None, state_scope="intraday"),
                        state_values(intraday_next, intraday_root, state_scope="intraday"),
                    ],
                )
                connection.execute(
                    AnalysisStateHead.__table__.insert().values(
                        id="00000000-0000-0000-0000-000000000085",
                        asset="XAUUSD",
                        state_scope="intraday",
                        canonical_state_id=intraday_root,
                        version=1,
                    )
                )
            with Session(engine) as scoped:
                advance_canonical_head_scoped(
                    scoped,
                    asset="XAUUSD",
                    state_scope="intraday",
                    new_state_id=intraday_next,
                    expected_state_id=intraday_root,
                    expected_version=1,
                    authority=authority,
                )
                scoped.commit()
            with Session(engine) as verify:
                heads = {
                    row.state_scope: (row.canonical_state_id, row.version)
                    for row in verify.scalars(
                        select(AnalysisStateHead).where(AnalysisStateHead.asset == "XAUUSD")
                    )
                }
                assert heads == {
                    "daily_close": (winner_id, 2),
                    "intraday": (intraday_next, 2),
                }
        finally:
            engine.dispose()


def test_canary_approval_has_one_postgres_concurrent_consumer() -> None:
    database_url = _postgres_url()
    with _isolated_schema(database_url) as schema_url:
        command.upgrade(build_alembic_config(schema_url), "head")
        engine = create_engine(schema_url)
        now = datetime(2026, 7, 28, 8, tzinfo=UTC)
        try:
            with Session(engine) as session, session.begin():
                approval = issue_canary_approval(
                    session,
                    approval_id="approval-postgres-concurrency",
                    asset="XAUUSD",
                    state_scope="daily_close",
                    trade_date=now.date(),
                    run_id=None,
                    approved_by="postgres-ci",
                    approved_role="canary_approver",
                    approved_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                )
                approval_hash = approval.approval_hash

            barrier = Barrier(2)

            def consume(run_id: str) -> str:
                with Session(engine) as session:
                    barrier.wait(timeout=10)
                    try:
                        with session.begin():
                            consume_canary_approval(
                                session,
                                approval_id="approval-postgres-concurrency",
                                expected_approval_hash=approval_hash,
                                run_id=run_id,
                                consumed_at=now,
                            )
                        return "consumed"
                    except CanaryApprovalConsumptionError:
                        return "rejected"

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(consume, ("run-a", "run-b")))
            assert sorted(outcomes) == ["consumed", "rejected"]
            with Session(engine) as session:
                stored = session.get(CanaryApproval, "approval-postgres-concurrency")
                assert stored is not None
                assert stored.status == "consumed"
                assert stored.consumed_by_run_id in {"run-a", "run-b"}
        finally:
            engine.dispose()


def test_canary_attempt_postgres_concurrent_create_recovers_one_identity() -> None:
    database_url = _postgres_url()
    with _isolated_schema(database_url) as schema_url:
        command.upgrade(build_alembic_config(schema_url), "head")
        engine = create_engine(schema_url)
        barrier = Barrier(2)
        now = datetime(2026, 7, 28, 8, tzinfo=UTC)

        def create() -> str:
            with Session(engine) as session:
                synchronized = False

                def synchronize_insert(_session, _flush_context, _instances) -> None:
                    nonlocal synchronized
                    if not synchronized and any(isinstance(item, CanaryAttempt) for item in session.new):
                        synchronized = True
                        barrier.wait(timeout=10)

                event.listen(session, "before_flush", synchronize_insert)
                with session.begin():
                    attempt = create_or_resume_canary_attempt(
                        session,
                        run_id="run-postgres-concurrency",
                        approval_id="approval-postgres-concurrency",
                        approval_hash="a" * 64,
                        attempt_no=0,
                        asset="XAUUSD",
                        state_scope="daily_close",
                        trade_date=now.date(),
                        requested_canonical_state_id="state-0",
                        expected_head_version=1,
                        started_at=now,
                    )
                    attempt_id = attempt.attempt_id
                return attempt_id

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                attempt_ids = list(executor.map(lambda _item: create(), range(2)))
            assert attempt_ids[0] == attempt_ids[1]
            with Session(engine) as session:
                attempts = list(
                    session.scalars(
                        select(CanaryAttempt).where(
                            CanaryAttempt.run_id == "run-postgres-concurrency"
                        )
                    )
                )
                assert len(attempts) == 1
                assert attempts[0].attempt_id == attempt_ids[0]
        finally:
            engine.dispose()
