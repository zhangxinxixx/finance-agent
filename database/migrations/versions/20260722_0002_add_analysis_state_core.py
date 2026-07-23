"""Add persistent analysis state core tables.

Revision ID: 20260722_0002
Revises: 20260704_0001
Create Date: 2026-07-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260722_0002"
down_revision = "20260704_0001"
branch_labels = None
depends_on = None


JSONB_COMPAT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _create_table_if_missing(table_name: str, *elements) -> None:
    if not _table_exists(table_name):
        op.create_table(table_name, *elements)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], **kwargs) -> None:
    if not _table_exists(table_name):
        return
    existing_indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}
    if index_name not in existing_indexes:
        op.create_index(index_name, table_name, columns, **kwargs)


def _drop_table_if_exists(table_name: str) -> None:
    if _table_exists(table_name):
        op.drop_table(table_name)


def upgrade() -> None:
    """Create the frozen Analysis Memory v1 persistence schema.

    Keep this revision independent from live ORM metadata.  Model evolution
    belongs in a later revision so a fresh install and an incremental upgrade
    always execute the same historical DDL.
    """

    _create_table_if_missing(
        "analysis_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("asset", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_state_id", sa.String(length=36), nullable=True),
        sa.Column("task_run_id", sa.String(length=255), nullable=False),
        sa.Column("analysis_snapshot_db_id", sa.String(length=36), nullable=True),
        sa.Column("final_analysis_result_id", sa.String(length=36), nullable=True),
        sa.Column("quality_gate_action", sa.String(length=32), nullable=False),
        sa.Column("publish_allowed", sa.Boolean(), nullable=False),
        sa.Column("accepted_output_source", sa.String(length=32), nullable=False),
        sa.Column("accepted_output_agent_name", sa.String(length=64), nullable=True),
        sa.Column("accepted_output_snapshot_id", sa.String(length=255), nullable=True),
        sa.Column("input_snapshot_ids", JSONB_COMPAT, nullable=False),
        sa.Column("source_refs", JSONB_COMPAT, nullable=False),
        sa.Column("evidence_cursors", JSONB_COMPAT, nullable=False),
        sa.Column("payload", JSONB_COMPAT, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["analysis_snapshot_db_id"], ["analysis_snapshots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["final_analysis_result_id"], ["final_analysis_results.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previous_state_id"], ["analysis_states.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_index_if_missing("ix_analysis_states_asset_as_of", "analysis_states", ["asset", "as_of"])
    _create_index_if_missing("ix_analysis_states_content_hash", "analysis_states", ["content_hash"])
    _create_index_if_missing(
        "ix_analysis_states_payload_gin", "analysis_states", ["payload"], postgresql_using="gin"
    )
    _create_index_if_missing("ix_analysis_states_previous_state_id", "analysis_states", ["previous_state_id"])
    _create_index_if_missing(
        "ix_analysis_states_quality",
        "analysis_states",
        ["quality_gate_action", "publish_allowed"],
    )
    _create_index_if_missing(
        "ix_analysis_states_source_refs_gin",
        "analysis_states",
        ["source_refs"],
        postgresql_using="gin",
    )
    _create_index_if_missing("ix_analysis_states_task_run_id", "analysis_states", ["task_run_id"])

    _create_table_if_missing(
        "analysis_state_heads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("asset", sa.String(length=32), nullable=False),
        sa.Column("canonical_state_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["canonical_state_id"], ["analysis_states.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset", name="uq_analysis_state_heads_asset"),
        sa.UniqueConstraint("canonical_state_id", name="uq_analysis_state_heads_state"),
    )
    _create_index_if_missing(
        "ix_analysis_state_heads_asset_version",
        "analysis_state_heads",
        ["asset", "version"],
    )

    _create_table_if_missing(
        "analysis_transitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("asset", sa.String(length=32), nullable=False),
        sa.Column("from_state_id", sa.String(length=36), nullable=True),
        sa.Column("to_state_id", sa.String(length=36), nullable=False),
        sa.Column("task_run_id", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("actions", JSONB_COMPAT, nullable=False),
        sa.Column("evidence_refs", JSONB_COMPAT, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["from_state_id"], ["analysis_states.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_state_id"], ["analysis_states.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("to_state_id", name="uq_analysis_transitions_to_state"),
    )
    _create_index_if_missing(
        "ix_analysis_transitions_actions_gin",
        "analysis_transitions",
        ["actions"],
        postgresql_using="gin",
    )
    _create_index_if_missing(
        "ix_analysis_transitions_asset_created",
        "analysis_transitions",
        ["asset", "created_at"],
    )
    _create_index_if_missing("ix_analysis_transitions_content_hash", "analysis_transitions", ["content_hash"])
    _create_index_if_missing("ix_analysis_transitions_from_state_id", "analysis_transitions", ["from_state_id"])
    _create_index_if_missing("ix_analysis_transitions_task_run_id", "analysis_transitions", ["task_run_id"])


def downgrade() -> None:
    _drop_table_if_exists("analysis_transitions")
    _drop_table_if_exists("analysis_state_heads")
    _drop_table_if_exists("analysis_states")
