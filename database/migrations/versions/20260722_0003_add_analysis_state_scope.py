"""Add scoped AnalysisState v1.1 identity.

Revision ID: 20260722_0003
Revises: 20260722_0002
Create Date: 2026-07-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260722_0003"
down_revision = "20260722_0002"
branch_labels = None
depends_on = None

_SCOPES = "'intraday', 'daily_close', 'weekly_fundamental'"


def upgrade() -> None:
    """Backfill legacy rows without touching immutable payload/hash/identity columns."""

    bind = op.get_bind()
    added_columns: set[str] = set()
    for table_name in ("analysis_states", "analysis_state_heads", "analysis_transitions"):
        if not _column_exists(bind, table_name, "state_scope"):
            op.add_column(table_name, sa.Column("state_scope", sa.String(length=32), nullable=True))
            added_columns.add(table_name)

    if "analysis_states" in added_columns:
        bind.execute(sa.text("UPDATE analysis_states SET state_scope = 'daily_close'"))
    if "analysis_transitions" in added_columns:
        bind.execute(
            sa.text(
                "UPDATE analysis_transitions SET state_scope = "
                "(SELECT s.state_scope FROM analysis_states s "
                "WHERE s.id = analysis_transitions.to_state_id)"
            )
        )
    if "analysis_state_heads" in added_columns:
        bind.execute(
            sa.text(
                "UPDATE analysis_state_heads SET state_scope = "
                "(SELECT s.state_scope FROM analysis_states s "
                "WHERE s.id = analysis_state_heads.canonical_state_id)"
            )
        )
    _validate_upgrade_backfill(bind)

    _drop_index_if_exists(bind, "analysis_states", "ix_analysis_states_asset_as_of")
    with op.batch_alter_table("analysis_states") as batch:
        batch.alter_column("state_scope", existing_type=sa.String(length=32), nullable=False)
        if not _check_exists(bind, "analysis_states", "ck_analysis_states_state_scope"):
            batch.create_check_constraint(
                "ck_analysis_states_state_scope", f"state_scope IN ({_SCOPES})"
            )
    _create_index_if_missing(
        bind,
        "ix_analysis_states_asset_scope_as_of",
        "analysis_states",
        ["asset", "state_scope", "as_of"],
    )

    _drop_index_if_exists(
        bind, "analysis_transitions", "ix_analysis_transitions_asset_created"
    )
    with op.batch_alter_table("analysis_transitions") as batch:
        batch.alter_column("state_scope", existing_type=sa.String(length=32), nullable=False)
        if not _check_exists(
            bind, "analysis_transitions", "ck_analysis_transitions_state_scope"
        ):
            batch.create_check_constraint(
                "ck_analysis_transitions_state_scope", f"state_scope IN ({_SCOPES})"
            )
    _create_index_if_missing(
        bind,
        "ix_analysis_transitions_asset_scope_created",
        "analysis_transitions",
        ["asset", "state_scope", "created_at"],
    )

    _drop_index_if_exists(
        bind, "analysis_state_heads", "ix_analysis_state_heads_asset_version"
    )
    with op.batch_alter_table("analysis_state_heads") as batch:
        if _unique_exists(bind, "analysis_state_heads", "uq_analysis_state_heads_asset"):
            batch.drop_constraint("uq_analysis_state_heads_asset", type_="unique")
        batch.alter_column("state_scope", existing_type=sa.String(length=32), nullable=False)
        if not _check_exists(bind, "analysis_state_heads", "ck_analysis_state_heads_state_scope"):
            batch.create_check_constraint(
                "ck_analysis_state_heads_state_scope", f"state_scope IN ({_SCOPES})"
            )
        if not _unique_exists(
            bind, "analysis_state_heads", "uq_analysis_state_heads_asset_scope"
        ):
            batch.create_unique_constraint(
                "uq_analysis_state_heads_asset_scope", ["asset", "state_scope"]
            )
    _create_index_if_missing(
        bind,
        "ix_analysis_state_heads_asset_scope_version",
        "analysis_state_heads",
        ["asset", "state_scope", "version"],
    )


def downgrade() -> None:
    """Fail closed if scoped state cannot be represented by the legacy schema."""

    bind = op.get_bind()
    non_daily = sum(
        int(
            bind.scalar(
                sa.text(
                    f"SELECT COUNT(*) FROM {table_name} "
                    "WHERE state_scope <> 'daily_close' OR state_scope IS NULL"
                )
            )
            or 0
        )
        for table_name in ("analysis_states", "analysis_state_heads", "analysis_transitions")
    )
    duplicate_assets = int(
        bind.scalar(
            sa.text(
                "SELECT COUNT(*) FROM ("
                "SELECT asset FROM analysis_state_heads GROUP BY asset HAVING COUNT(*) > 1"
                ") duplicate_heads"
            )
        )
        or 0
    )
    if non_daily or duplicate_assets:
        raise RuntimeError(
            "cannot downgrade scoped analysis state: non-daily scope or multiple heads per asset"
        )

    op.drop_index(
        "ix_analysis_state_heads_asset_scope_version", table_name="analysis_state_heads"
    )
    with op.batch_alter_table("analysis_state_heads") as batch:
        batch.drop_constraint("uq_analysis_state_heads_asset_scope", type_="unique")
        batch.drop_constraint("ck_analysis_state_heads_state_scope", type_="check")
        batch.drop_column("state_scope")
        batch.create_unique_constraint("uq_analysis_state_heads_asset", ["asset"])
    op.create_index(
        "ix_analysis_state_heads_asset_version",
        "analysis_state_heads",
        ["asset", "version"],
    )

    op.drop_index(
        "ix_analysis_transitions_asset_scope_created", table_name="analysis_transitions"
    )
    with op.batch_alter_table("analysis_transitions") as batch:
        batch.drop_constraint("ck_analysis_transitions_state_scope", type_="check")
        batch.drop_column("state_scope")
    op.create_index(
        "ix_analysis_transitions_asset_created",
        "analysis_transitions",
        ["asset", "created_at"],
    )

    op.drop_index("ix_analysis_states_asset_scope_as_of", table_name="analysis_states")
    with op.batch_alter_table("analysis_states") as batch:
        batch.drop_constraint("ck_analysis_states_state_scope", type_="check")
        batch.drop_column("state_scope")
    op.create_index(
        "ix_analysis_states_asset_as_of", "analysis_states", ["asset", "as_of"]
    )


def _validate_upgrade_backfill(bind) -> None:
    for table_name in ("analysis_states", "analysis_state_heads", "analysis_transitions"):
        missing = int(
            bind.scalar(
                sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE state_scope IS NULL")
            )
            or 0
        )
        if missing:
            raise RuntimeError(f"state_scope backfill incomplete for {table_name}")

    transition_mismatch = int(
        bind.scalar(
            sa.text(
                "SELECT COUNT(*) FROM analysis_transitions t "
                "JOIN analysis_states s ON s.id = t.to_state_id "
                "WHERE t.state_scope <> s.state_scope"
            )
        )
        or 0
    )
    head_mismatch = int(
        bind.scalar(
            sa.text(
                "SELECT COUNT(*) FROM analysis_state_heads h "
                "JOIN analysis_states s ON s.id = h.canonical_state_id "
                "WHERE h.state_scope <> s.state_scope"
            )
        )
        or 0
    )
    if transition_mismatch or head_mismatch:
        raise RuntimeError("state_scope relationship backfill is inconsistent")


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    return column_name in {
        column["name"] for column in sa.inspect(bind).get_columns(table_name)
    }


def _check_exists(bind, table_name: str, constraint_name: str) -> bool:
    return constraint_name in {
        constraint["name"]
        for constraint in sa.inspect(bind).get_check_constraints(table_name)
    }


def _unique_exists(bind, table_name: str, constraint_name: str) -> bool:
    return constraint_name in {
        constraint["name"]
        for constraint in sa.inspect(bind).get_unique_constraints(table_name)
    }


def _drop_index_if_exists(bind, table_name: str, index_name: str) -> None:
    if index_name in {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}:
        op.drop_index(index_name, table_name=table_name)


def _create_index_if_missing(
    bind, index_name: str, table_name: str, columns: list[str]
) -> None:
    if index_name not in {
        index["name"] for index in sa.inspect(bind).get_indexes(table_name)
    }:
        op.create_index(index_name, table_name, columns)
