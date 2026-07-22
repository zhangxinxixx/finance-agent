"""PostgreSQL-only migration lifecycle and canonical-head CAS checks."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from apps.analysis.state import (
    CanonicalHeadConflictError,
    StateMaterializationAuthority,
    advance_canonical_head,
)
from database.migrations.runtime import build_alembic_config
from database.models.analysis import AnalysisSnapshot
from database.models.analysis_state import AnalysisState, AnalysisStateHead


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
            command.upgrade(config, "head")
            assert STATE_TABLES <= _table_names(incremental_url)
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        select(AnalysisSnapshot.snapshot_id).where(AnalysisSnapshot.snapshot_id == snapshot_id)
                    )
                    == snapshot_id
                )
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

        def state_values(state_id: str, previous_state_id: str | None) -> dict:
            return {
                "id": state_id,
                "schema_version": "1.0",
                "asset": "XAUUSD",
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
        finally:
            engine.dispose()
