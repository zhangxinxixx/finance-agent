from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import UniqueConstraint, create_engine, inspect, select, text


def _metadata_table_names(target_metadata) -> set[str]:
    metadatas = target_metadata if isinstance(target_metadata, (list, tuple)) else [target_metadata]
    return {table.name for metadata in metadatas for table in metadata.tables.values()}


def test_alembic_env_targets_all_runtime_metadata() -> None:
    from database.migrations.env import target_metadata

    table_names = _metadata_table_names(target_metadata)

    assert "analysis_snapshots" in table_names
    assert "task_runs" in table_names
    assert "execution_events" in table_names
    assert "report_items" in table_names
    assert "cme_option_rows" in table_names


def test_alembic_config_preserves_percent_encoded_database_url() -> None:
    from database.migrations.runtime import build_alembic_config

    database_url = (
        "postgresql://finance_agent@127.0.0.1/finance_agent"
        "?options=-csearch_path%3Dfinance_agent_issue65"
    )

    config = build_alembic_config(database_url)

    assert config.get_main_option("sqlalchemy.url") == database_url


def test_report_primary_keys_do_not_duplicate_unique_constraints() -> None:
    from database.models.report import ReportArtifact, ReportItem

    tables_and_primary_keys = (
        (ReportItem.__table__, "report_id"),
        (ReportArtifact.__table__, "artifact_id"),
    )
    for table, primary_key_column in tables_and_primary_keys:
        redundant_uniques = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
            and tuple(column.name for column in constraint.columns) == (primary_key_column,)
        }
        assert redundant_uniques == set()

    report_artifact_uniques = {
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in ReportArtifact.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert (
        "uq_report_artifacts_report_type_path",
        ("report_id", "artifact_type", "file_path"),
    ) in report_artifact_uniques


def test_runtime_alembic_upgrade_creates_current_schema(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from database.migrations.runtime import run_database_migrations

    db_path = tmp_path / "finance-agent.sqlite"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", "postgresql://ignored:ignored@127.0.0.1:1/ignored")

    run_database_migrations(database_url)

    inspector = inspect(create_engine(database_url))
    table_names = set(inspector.get_table_names())

    assert "analysis_snapshots" in table_names
    assert "task_runs" in table_names
    assert "execution_events" in table_names
    assert "report_items" in table_names
    assert "cme_option_rows" in table_names


def test_analysis_memory_revision_boundary_is_explicit_and_replay_safe(tmp_path: Path) -> None:
    from database.migrations.runtime import build_alembic_config
    from database.models.analysis_state import AnalysisState

    database_url = f"sqlite:///{tmp_path / 'revision-boundary.sqlite'}"
    config = build_alembic_config(database_url)
    engine = create_engine(database_url)
    state_tables = {"analysis_states", "analysis_state_heads", "analysis_transitions"}

    command.upgrade(config, "20260704_0001")
    assert state_tables.isdisjoint(inspect(engine).get_table_names())

    command.upgrade(config, "20260722_0002")
    inspector = inspect(engine)
    assert state_tables <= set(inspector.get_table_names())
    expected_indexes = {
        "analysis_states": {
            "ix_analysis_states_asset_as_of", "ix_analysis_states_previous_state_id",
            "ix_analysis_states_task_run_id", "ix_analysis_states_quality",
            "ix_analysis_states_content_hash", "ix_analysis_states_payload_gin",
            "ix_analysis_states_source_refs_gin",
        },
        "analysis_state_heads": {"ix_analysis_state_heads_asset_version"},
        "analysis_transitions": {
            "ix_analysis_transitions_asset_created", "ix_analysis_transitions_from_state_id",
            "ix_analysis_transitions_task_run_id", "ix_analysis_transitions_content_hash",
            "ix_analysis_transitions_actions_gin",
        },
    }
    for table_name, index_names in expected_indexes.items():
        assert {index["name"] for index in inspector.get_indexes(table_name)} == index_names
    assert {"uq_analysis_state_heads_asset", "uq_analysis_state_heads_state"} == {
        constraint["name"] for constraint in inspector.get_unique_constraints("analysis_state_heads")
    }
    assert {"uq_analysis_transitions_to_state"} == {
        constraint["name"] for constraint in inspector.get_unique_constraints("analysis_transitions")
    }
    assert {
        (tuple(foreign_key["constrained_columns"]), foreign_key["referred_table"])
        for foreign_key in inspector.get_foreign_keys("analysis_states")
    } == {
        (("previous_state_id",), "analysis_states"),
        (("analysis_snapshot_db_id",), "analysis_snapshots"),
        (("final_analysis_result_id",), "final_analysis_results"),
    }

    state_id = "00000000-0000-0000-0000-000000000074"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO analysis_states "
                "(id, schema_version, asset, as_of, task_run_id, quality_gate_action, "
                "publish_allowed, accepted_output_source, input_snapshot_ids, source_refs, "
                "evidence_cursors, payload, content_hash) VALUES "
                "(:id, '1.0', 'XAUUSD', :as_of, 'issue-74-replay', 'manual_review', "
                "0, 'none', '{}', '[]', '{}', :payload, :content_hash)"
            ),
            {
                "id": state_id,
                "as_of": datetime(2026, 7, 22, 8, tzinfo=UTC),
                "payload": '{"asset":"XAUUSD","schema_version":"1.0"}',
                "content_hash": "0" * 64,
            },
        )
        before = connection.execute(
            text("SELECT id, payload, content_hash FROM analysis_states WHERE id = :id"),
            {"id": state_id},
        ).one()

    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(select(AnalysisState.id).where(AnalysisState.id == state_id)) == state_id
        after = connection.execute(
            text("SELECT id, payload, content_hash FROM analysis_states WHERE id = :id"),
            {"id": state_id},
        ).one()
        assert tuple(after) == tuple(before)
        assert connection.scalar(
            text("SELECT state_scope FROM analysis_states WHERE id = :id"), {"id": state_id}
        ) == "daily_close"
    inspector = inspect(engine)
    assert {column["name"] for column in inspector.get_columns("analysis_states")} >= {
        "state_scope"
    }
    assert {item["name"] for item in inspector.get_unique_constraints("analysis_state_heads")} == {
        "uq_analysis_state_heads_asset_scope", "uq_analysis_state_heads_state"
    }

    command.downgrade(config, "20260704_0001")
    assert state_tables.isdisjoint(inspect(engine).get_table_names())
    command.upgrade(config, "head")
    assert state_tables <= set(inspect(engine).get_table_names())


def test_analysis_memory_revision_does_not_import_live_orm() -> None:
    revision_path = (
        Path(__file__).resolve().parents[2]
        / "database/migrations/versions/20260722_0002_add_analysis_state_core.py"
    )
    source = revision_path.read_text(encoding="utf-8")

    assert "database.models.analysis_state" not in source
    assert source.count("\n    _create_table_if_missing(") == 3
    assert source.count("\n        op.create_table(") == 1
    assert '"analysis_states"' in source
    assert '"analysis_state_heads"' in source
    assert '"analysis_transitions"' in source


def test_analysis_memory_upgrade_preserves_precreated_tables_and_data(tmp_path: Path) -> None:
    from database.migrations.runtime import build_alembic_config
    from database.models.analysis_state import AnalysisState, AnalysisStateHead, AnalysisTransition

    database_url = f"sqlite:///{tmp_path / 'precreated-state.sqlite'}"
    config = build_alembic_config(database_url)
    engine = create_engine(database_url)
    command.upgrade(config, "20260704_0001")
    for table in (AnalysisState.__table__, AnalysisStateHead.__table__, AnalysisTransition.__table__):
        table.create(bind=engine, checkfirst=True)

    state_id = "00000000-0000-0000-0000-000000000080"
    with engine.begin() as connection:
        connection.execute(
            AnalysisState.__table__.insert().values(
                id=state_id,
                schema_version="1.0",
                asset="XAUUSD",
                state_scope="daily_close",
                as_of=datetime(2026, 7, 22, 8, tzinfo=UTC),
                task_run_id="issue-74-precreated",
                quality_gate_action="manual_review",
                publish_allowed=False,
                accepted_output_source="none",
                input_snapshot_ids={},
                source_refs=[],
                evidence_cursors={},
                payload={"asset": "XAUUSD"},
                content_hash="2" * 64,
            )
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(select(AnalysisState.id).where(AnalysisState.id == state_id)) == state_id


def test_analysis_state_scope_downgrade_fails_closed(tmp_path: Path) -> None:
    from database.migrations.runtime import build_alembic_config

    database_url = f"sqlite:///{tmp_path / 'scoped-downgrade.sqlite'}"
    config = build_alembic_config(database_url)
    engine = create_engine(database_url)
    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO analysis_states "
                "(id, schema_version, asset, state_scope, as_of, task_run_id, "
                "quality_gate_action, publish_allowed, accepted_output_source, "
                "input_snapshot_ids, source_refs, evidence_cursors, payload, content_hash) "
                "VALUES ('scoped-state', '1.1', 'XAUUSD', 'intraday', :as_of, "
                "'run-scoped', 'manual_review', 0, 'none', '{}', '[]', '{}', '{}', :hash)"
            ),
            {"as_of": datetime(2026, 7, 22, 8, tzinfo=UTC), "hash": "4" * 64},
        )

    with pytest.raises(RuntimeError, match="cannot downgrade scoped analysis state"):
        command.downgrade(config, "20260722_0002")


def test_analysis_state_scope_downgrade_rejects_daily_close_v11_rows(tmp_path: Path) -> None:
    from database.migrations.runtime import build_alembic_config

    database_url = f"sqlite:///{tmp_path / 'v11-downgrade.sqlite'}"
    config = build_alembic_config(database_url)
    engine = create_engine(database_url)
    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO analysis_states "
                "(id, schema_version, asset, state_scope, as_of, task_run_id, "
                "quality_gate_action, publish_allowed, accepted_output_source, "
                "input_snapshot_ids, source_refs, evidence_cursors, payload, content_hash) "
                "VALUES ('daily-v11', '1.1', 'XAUUSD', 'daily_close', :as_of, "
                "'run-v11', 'manual_review', 0, 'none', '{}', '[]', '{}', '{}', :hash)"
            ),
            {"as_of": datetime(2026, 7, 22, 8, tzinfo=UTC), "hash": "5" * 64},
        )

    with pytest.raises(RuntimeError, match="v1.1 rows"):
        command.downgrade(config, "20260722_0002")


@pytest.mark.anyio
async def test_api_startup_runs_alembic_upgrade_instead_of_runtime_table_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main

    calls: list[str] = []

    monkeypatch.setattr(api_main, "_database_reachable", lambda: True)
    monkeypatch.setattr(api_main, "_should_skip_background_jobs", lambda: True)
    monkeypatch.setattr(api_main, "run_database_migrations", lambda *_args, **_kwargs: calls.append("alembic"), raising=False)

    def fail_runtime_patch(_db):
        raise AssertionError("startup must use Alembic, not runtime ensure_* DDL")

    monkeypatch.setattr(api_main, "ensure_task_tables", fail_runtime_patch, raising=False)
    monkeypatch.setattr(api_main, "ensure_execution_tables", fail_runtime_patch, raising=False)
    monkeypatch.setattr(api_main, "ensure_analysis_tables", fail_runtime_patch, raising=False)
    monkeypatch.setattr(api_main, "ensure_report_tables", fail_runtime_patch, raising=False)

    async with api_main.lifespan(api_main.app):
        pass

    assert calls == ["alembic"]
