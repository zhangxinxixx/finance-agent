"""Add persistent analysis state core tables.

Revision ID: 20260722_0002
Revises: 20260704_0001
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op

from database.models.analysis_state import AnalysisState, AnalysisStateHead, AnalysisTransition


revision = "20260722_0002"
down_revision = "20260704_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in (AnalysisState.__table__, AnalysisStateHead.__table__, AnalysisTransition.__table__):
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (AnalysisTransition.__table__, AnalysisStateHead.__table__, AnalysisState.__table__):
        table.drop(bind=bind, checkfirst=True)
