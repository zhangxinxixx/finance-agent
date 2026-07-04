"""Unify runtime schema under Alembic.

Revision ID: 20260704_0001
Revises:
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op

from database.models.analysis import AnalysisBase
from database.models.execution import ExecutionBase
from database.models.report import ReportBase
from database.models.task import Base

# Register tables attached to shared metadata before create_all().
from database.models import cme as _cme_models  # noqa: F401
from database.models import playbook as _playbook_models  # noqa: F401


revision = "20260704_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for metadata in (AnalysisBase.metadata, Base.metadata, ExecutionBase.metadata, ReportBase.metadata):
        metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for metadata in (ReportBase.metadata, ExecutionBase.metadata, Base.metadata, AnalysisBase.metadata):
        metadata.drop_all(bind=bind, checkfirst=True)
