"""Add durable canary attempt lifecycle records.

Revision ID: 20260728_0005
Revises: 20260728_0004
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260728_0005"
down_revision = "20260728_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("canary_attempts"):
        return
    op.create_table(
        "canary_attempts",
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("approval_id", sa.String(length=64), nullable=False),
        sa.Column("approval_hash", sa.String(length=64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("asset", sa.String(length=32), nullable=False),
        sa.Column("state_scope", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("requested_canonical_state_id", sa.String(length=36), nullable=True),
        sa.Column("expected_head_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context_bundle_id", sa.String(length=255), nullable=True),
        sa.Column("context_bundle_hash", sa.String(length=64), nullable=True),
        sa.Column("authority_hash", sa.String(length=64), nullable=True),
        sa.Column("audit_artifact_path", sa.Text(), nullable=True),
        sa.Column("audit_artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("terminal_artifact_path", sa.Text(), nullable=True),
        sa.Column("terminal_artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("terminal_status", sa.String(length=32), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("attempt_no IN (0, 1)", name="ck_canary_attempts_attempt_no"),
        sa.CheckConstraint(
            "status IN ('started', 'audit_persisted', 'recompute_authorized', 'terminal', 'failed')",
            name="ck_canary_attempts_status",
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint("run_id", "attempt_no", name="uq_canary_attempts_run_attempt"),
    )
    op.create_index("ix_canary_attempts_run_status", "canary_attempts", ["run_id", "status"])
    op.create_index("ix_canary_attempts_approval_id", "canary_attempts", ["approval_id"])
    op.create_index("ix_canary_attempts_updated_at", "canary_attempts", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_canary_attempts_updated_at", table_name="canary_attempts")
    op.drop_index("ix_canary_attempts_approval_id", table_name="canary_attempts")
    op.drop_index("ix_canary_attempts_run_status", table_name="canary_attempts")
    op.drop_table("canary_attempts")
