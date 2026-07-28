"""Add persistent scoped canary approvals.

Revision ID: 20260728_0004
Revises: 20260722_0003
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260728_0004"
down_revision = "20260722_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("canary_approvals"):
        return
    op.create_table(
        "canary_approvals",
        sa.Column("approval_id", sa.String(length=64), nullable=False),
        sa.Column("asset", sa.String(length=32), nullable=False),
        sa.Column("state_scope", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("run_id", sa.String(length=255), nullable=True),
        sa.Column("approved_by", sa.String(length=128), nullable=False),
        sa.Column("approved_role", sa.String(length=64), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approval_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_by_run_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "state_scope IN ('intraday', 'daily_close', 'weekly_fundamental')",
            name="ck_canary_approvals_state_scope",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'consumed', 'revoked')",
            name="ck_canary_approvals_status",
        ),
        sa.CheckConstraint(
            "trade_date IS NOT NULL OR run_id IS NOT NULL",
            name="ck_canary_approvals_binding",
        ),
        sa.CheckConstraint(
            "expires_at > approved_at",
            name="ck_canary_approvals_valid_window",
        ),
        sa.PrimaryKeyConstraint("approval_id"),
    )
    op.create_index(
        "ix_canary_approvals_status_expires",
        "canary_approvals",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_canary_approvals_asset_scope_date",
        "canary_approvals",
        ["asset", "state_scope", "trade_date"],
    )
    op.create_index("ix_canary_approvals_run_id", "canary_approvals", ["run_id"])
    op.create_index(
        "ix_canary_approvals_consumed_by_run_id",
        "canary_approvals",
        ["consumed_by_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_canary_approvals_consumed_by_run_id", table_name="canary_approvals")
    op.drop_index("ix_canary_approvals_run_id", table_name="canary_approvals")
    op.drop_index("ix_canary_approvals_asset_scope_date", table_name="canary_approvals")
    op.drop_index("ix_canary_approvals_status_expires", table_name="canary_approvals")
    op.drop_table("canary_approvals")
