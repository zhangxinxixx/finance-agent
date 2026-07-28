"""Persistent CanaryApproval schema, validation, and one-time consumption contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from database.migrations.runtime import build_alembic_config
from database.models.analysis import AnalysisBase
from database.models.analysis_state import CanaryApproval
from database.queries.canary_approvals import (
    CanaryApprovalConsumptionError,
    CanaryApprovalError,
    compute_canary_approval_hash,
    consume_canary_approval,
    issue_canary_approval,
    load_canary_approval,
    revoke_canary_approval,
)


NOW = datetime(2026, 7, 28, 8, tzinfo=UTC)
TRADE_DATE = NOW.date()
RUN_ID = "00000000-0000-0000-0000-000000000080"


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AnalysisBase.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _issue(session: Session, **overrides) -> CanaryApproval:
    values = {
        "approval_id": "approval-80",
        "asset": "XAUUSD",
        "state_scope": "daily_close",
        "trade_date": TRADE_DATE,
        "run_id": RUN_ID,
        "approved_by": "review-center",
        "approved_role": "canary_approver",
        "approved_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(overrides)
    return issue_canary_approval(session, **values)


def _load(session: Session, **overrides) -> CanaryApproval:
    values = {
        "approval_id": "approval-80",
        "asset": "XAUUSD",
        "state_scope": "daily_close",
        "trade_date": TRADE_DATE,
        "run_id": RUN_ID,
        "now": NOW,
    }
    values.update(overrides)
    return load_canary_approval(session, **values)


def test_create_all_registers_approval_columns_constraints_and_indexes() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AnalysisBase.metadata.create_all(engine)
    inspector = inspect(engine)

    assert "canary_approvals" in inspector.get_table_names()
    assert {column["name"] for column in inspector.get_columns("canary_approvals")} == {
        "approval_id",
        "asset",
        "state_scope",
        "trade_date",
        "run_id",
        "approved_by",
        "approved_role",
        "approved_at",
        "expires_at",
        "approval_hash",
        "status",
        "consumed_at",
        "consumed_by_run_id",
        "created_at",
        "updated_at",
    }
    assert {item["name"] for item in inspector.get_check_constraints("canary_approvals")} == {
        "ck_canary_approvals_binding",
        "ck_canary_approvals_state_scope",
        "ck_canary_approvals_status",
        "ck_canary_approvals_valid_window",
    }
    assert {item["name"] for item in inspector.get_indexes("canary_approvals")} == {
        "ix_canary_approvals_asset_scope_date",
        "ix_canary_approvals_consumed_by_run_id",
        "ix_canary_approvals_run_id",
        "ix_canary_approvals_status_expires",
    }


def test_migration_upgrade_and_downgrade_owns_canary_approval_table(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'approval-migration.sqlite'}"
    config = build_alembic_config(database_url)
    engine = create_engine(database_url)

    command.upgrade(config, "20260728_0004")
    assert "canary_approvals" in inspect(engine).get_table_names()
    command.downgrade(config, "20260722_0003")
    assert "canary_approvals" not in inspect(engine).get_table_names()


def test_issue_load_and_hash_ignore_mutable_lifecycle_fields(session: Session) -> None:
    approval = _issue(session)
    original_hash = approval.approval_hash
    assert _load(session) is approval

    approval.status = "revoked"
    approval.updated_at = NOW
    session.flush()
    expected = compute_canary_approval_hash(
        approval_id=approval.approval_id,
        asset=approval.asset,
        state_scope=approval.state_scope,
        trade_date=approval.trade_date,
        run_id=approval.run_id,
        approved_by=approval.approved_by,
        approved_role=approval.approved_role,
        approved_at=approval.approved_at.replace(tzinfo=UTC),
        expires_at=approval.expires_at.replace(tzinfo=UTC),
    )
    assert expected == original_hash


def test_load_rejects_hash_tamper_expiry_revoke_and_wrong_binding(session: Session) -> None:
    with pytest.raises(CanaryApprovalError, match="does not exist"):
        _load(session)
    approval = _issue(session)
    approval.approval_hash = "0" * 64
    session.flush()
    with pytest.raises(CanaryApprovalError, match="hash"):
        _load(session)

    session.rollback()
    approval = _issue(session, approval_id="expired", expires_at=NOW - timedelta(minutes=1))
    with pytest.raises(CanaryApprovalError, match="expired"):
        _load(session, approval_id=approval.approval_id)

    active = _issue(session, approval_id="revoked")
    revoke_canary_approval(session, approval_id=active.approval_id, revoked_at=NOW)
    with pytest.raises(CanaryApprovalError, match="revoked"):
        _load(session, approval_id=active.approval_id)

    future = _issue(
        session,
        approval_id="future",
        approved_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )
    with pytest.raises(CanaryApprovalError, match="not yet active"):
        _load(session, approval_id=future.approval_id)

    wrong_role = _issue(session, approval_id="wrong-role")
    wrong_role.approved_role = "viewer"
    wrong_role.approval_hash = compute_canary_approval_hash(
        approval_id=wrong_role.approval_id,
        asset=wrong_role.asset,
        state_scope=wrong_role.state_scope,
        trade_date=wrong_role.trade_date,
        run_id=wrong_role.run_id,
        approved_by=wrong_role.approved_by,
        approved_role=wrong_role.approved_role,
        approved_at=wrong_role.approved_at,
        expires_at=wrong_role.expires_at,
    )
    session.flush()
    with pytest.raises(CanaryApprovalError, match="role"):
        _load(session, approval_id=wrong_role.approval_id)

    _issue(session)
    for field, value, message in (
        ("asset", "EURUSD", "asset"),
        ("state_scope", "intraday", "state_scope"),
        ("trade_date", TRADE_DATE - timedelta(days=1), "trade_date"),
        ("run_id", "different-run", "run_id"),
    ):
        with pytest.raises(CanaryApprovalError, match=message):
            _load(session, **{field: value})


def test_issue_requires_binding_valid_window_and_authorized_role(session: Session) -> None:
    with pytest.raises(CanaryApprovalError, match="bind"):
        _issue(session, trade_date=None, run_id=None)
    with pytest.raises(CanaryApprovalError, match="later"):
        _issue(session, approval_id="bad-window", expires_at=NOW - timedelta(hours=1))
    with pytest.raises(CanaryApprovalError, match="role"):
        _issue(session, approval_id="bad-role", approved_role="viewer")


def test_consume_is_conditional_single_use_and_same_run_replay_is_explicit(session: Session) -> None:
    approval = _issue(session, run_id=None)
    consumed = consume_canary_approval(
        session,
        approval_id="approval-80",
        expected_approval_hash=approval.approval_hash,
        run_id=RUN_ID,
        consumed_at=NOW,
    )
    assert consumed.status == "consumed"
    assert consumed.consumed_by_run_id == RUN_ID
    with pytest.raises(CanaryApprovalConsumptionError, match="active-to-consumed"):
        consume_canary_approval(
            session,
            approval_id="approval-80",
            expected_approval_hash=approval.approval_hash,
            run_id=RUN_ID,
            consumed_at=NOW,
        )
    assert _load(session, allow_consumed_by_same_run=True).status == "consumed"
    with pytest.raises(CanaryApprovalError, match="another run"):
        _load(
            session,
            run_id="different-run",
            allow_consumed_by_same_run=True,
        )


def test_consume_rollback_restores_active_status(session: Session) -> None:
    approval = _issue(session)
    with pytest.raises(RuntimeError, match="force rollback"):
        with session.begin_nested():
            consume_canary_approval(
                session,
                approval_id="approval-80",
                expected_approval_hash=approval.approval_hash,
                run_id=RUN_ID,
                consumed_at=NOW,
            )
            raise RuntimeError("force rollback")
    session.expire_all()
    assert session.get(CanaryApproval, "approval-80").status == "active"
