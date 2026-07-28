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


_EXPECTED_COLUMNS = {
    "approval_id": (sa.String, 64, False),
    "asset": (sa.String, 32, False),
    "state_scope": (sa.String, 32, False),
    "trade_date": (sa.Date, None, True),
    "run_id": (sa.String, 255, True),
    "approved_by": (sa.String, 128, False),
    "approved_role": (sa.String, 64, False),
    "approved_at": (sa.DateTime, None, False),
    "expires_at": (sa.DateTime, None, False),
    "approval_hash": (sa.String, 64, False),
    "status": (sa.String, 16, False),
    "consumed_at": (sa.DateTime, None, True),
    "consumed_by_run_id": (sa.String, 255, True),
    "created_at": (sa.DateTime, None, False),
    "updated_at": (sa.DateTime, None, False),
}
_EXPECTED_INDEXES = {
    "ix_canary_approvals_status_expires": ("status", "expires_at"),
    "ix_canary_approvals_asset_scope_date": ("asset", "state_scope", "trade_date"),
    "ix_canary_approvals_run_id": ("run_id",),
    "ix_canary_approvals_consumed_by_run_id": ("consumed_by_run_id",),
}
_EXPECTED_CHECKS = {
    "ck_canary_approvals_state_scope": "state_scope IN ('intraday', 'daily_close', 'weekly_fundamental')",
    "ck_canary_approvals_status": "status IN ('active', 'consumed', 'revoked')",
    "ck_canary_approvals_binding": "trade_date IS NOT NULL OR run_id IS NOT NULL",
    "ck_canary_approvals_valid_window": "expires_at > approved_at",
}


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("canary_approvals"):
        _validate_existing_table(bind)
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


def _validate_existing_table(bind) -> None:
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("canary_approvals")}
    if set(columns) != set(_EXPECTED_COLUMNS):
        _incompatible("columns")
    for name, (expected_type, expected_length, nullable) in _EXPECTED_COLUMNS.items():
        column = columns[name]
        if not isinstance(column["type"], expected_type):
            _incompatible(f"column {name} type")
        if expected_length is not None and getattr(column["type"], "length", None) != expected_length:
            _incompatible(f"column {name} length")
        if bool(column["nullable"]) != nullable:
            _incompatible(f"column {name} nullability")
    if tuple(inspector.get_pk_constraint("canary_approvals").get("constrained_columns") or ()) != (
        "approval_id",
    ):
        _incompatible("primary key")
    indexes = {
        item["name"]: tuple(item.get("column_names") or ())
        for item in inspector.get_indexes("canary_approvals")
        if not item.get("duplicates_constraint")
    }
    if indexes != _EXPECTED_INDEXES:
        _incompatible("indexes")
    checks = {
        item["name"]: str(item.get("sqltext") or "")
        for item in inspector.get_check_constraints("canary_approvals")
    }
    if set(checks) != set(_EXPECTED_CHECKS):
        _incompatible("check constraints")
    if bind.dialect.name == "sqlite":
        for name, expected_sql in _EXPECTED_CHECKS.items():
            if _normalize_sql(checks[name]) != _normalize_sql(expected_sql):
                _incompatible(f"check constraint {name}")


def _normalize_sql(value: str) -> str:
    return " ".join(value.lower().split())


def _incompatible(detail: str) -> None:
    raise RuntimeError(f"existing canary_approvals table is incompatible: {detail}")
