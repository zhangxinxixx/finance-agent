from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models.analysis import AnalysisBase, PromptVersion, ensure_analysis_tables
from scripts.seed_prompt_versions import seed


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnalysisBase.metadata.create_all(engine)
    ensure_analysis_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_seed_prompt_versions_includes_macro_liquidity_and_macro_event_followup(monkeypatch) -> None:
    db = _session()

    def _session_local():
        return db

    monkeypatch.setattr("scripts.seed_prompt_versions.SessionLocal", _session_local)
    seed()

    rows = db.query(PromptVersion).filter(
        PromptVersion.agent_id.in_(["macro_liquidity_agent", "macro_event_followup_agent"])
    ).all()
    pairs = {(row.agent_id, row.version, row.status, row.enabled) for row in rows}

    assert ("macro_liquidity_agent", "v1", "active", True) in pairs
    assert ("macro_event_followup_agent", "v1", "active", True) in pairs
