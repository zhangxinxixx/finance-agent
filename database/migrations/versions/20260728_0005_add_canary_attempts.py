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


_EXPECTED_COLUMNS = {
    "attempt_id": (sa.String, 36, False),
    "run_id": (sa.String, 255, False),
    "approval_id": (sa.String, 64, False),
    "approval_hash": (sa.String, 64, False),
    "attempt_no": (sa.Integer, None, False),
    "asset": (sa.String, 32, False),
    "state_scope": (sa.String, 32, False),
    "trade_date": (sa.Date, None, False),
    "requested_canonical_state_id": (sa.String, 36, True),
    "expected_head_version": (sa.Integer, None, True),
    "status": (sa.String, 32, False),
    "started_at": (sa.DateTime, None, False),
    "context_bundle_id": (sa.String, 255, True),
    "context_bundle_hash": (sa.String, 64, True),
    "authority_hash": (sa.String, 64, True),
    "audit_artifact_path": (sa.Text, None, True),
    "audit_artifact_sha256": (sa.String, 64, True),
    "terminal_artifact_path": (sa.Text, None, True),
    "terminal_artifact_sha256": (sa.String, 64, True),
    "terminal_status": (sa.String, 32, True),
    "failure_code": (sa.String, 128, True),
    "failure_detail": (sa.Text, None, True),
    "created_at": (sa.DateTime, None, False),
    "updated_at": (sa.DateTime, None, False),
}
_EXPECTED_INDEXES = {
    "ix_canary_attempts_run_status": ("run_id", "status"),
    "ix_canary_attempts_approval_id": ("approval_id",),
    "ix_canary_attempts_updated_at": ("updated_at",),
}
_EXPECTED_UNIQUES = {
    "uq_canary_attempts_run_attempt": ("run_id", "attempt_no"),
}
_EXPECTED_CHECKS = {
    "ck_canary_attempts_attempt_no": "attempt_no IN (0, 1)",
    "ck_canary_attempts_status": (
        "status IN ('started', 'audit_persisted', 'recompute_authorized', 'terminal', 'failed')"
    ),
}


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("canary_attempts"):
        _validate_existing_table(bind)
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


def _validate_existing_table(bind) -> None:
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("canary_attempts")}
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
    if tuple(inspector.get_pk_constraint("canary_attempts").get("constrained_columns") or ()) != (
        "attempt_id",
    ):
        _incompatible("primary key")
    indexes = {
        item["name"]: tuple(item.get("column_names") or ())
        for item in inspector.get_indexes("canary_attempts")
        if not item.get("duplicates_constraint")
    }
    if indexes != _EXPECTED_INDEXES:
        _incompatible("indexes")
    uniques = {
        item["name"]: tuple(item.get("column_names") or ())
        for item in inspector.get_unique_constraints("canary_attempts")
    }
    if uniques != _EXPECTED_UNIQUES:
        _incompatible("unique constraints")
    checks = {
        item["name"]: str(item.get("sqltext") or "")
        for item in inspector.get_check_constraints("canary_attempts")
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
    raise RuntimeError(f"existing canary_attempts table is incompatible: {detail}")
