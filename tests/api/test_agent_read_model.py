from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.services import agent_read_model
from database.models.analysis import AgentOutput, AnalysisBase, PromptVersion


def test_latest_agent_summaries_materializes_prompt_metadata_before_session_close(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnalysisBase.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as db:
        prompt_version = PromptVersion(
            id="pv-synthesis-v1",
            agent_id="synthesis_agent",
            version="v1",
            prompt_kind="llm",
            prompt_source="apps/analysis/agents/synthesis_prompt.py",
            prompt_template={"messages": [{"role": "user", "content": "synthesize"}]},
            prompt_sha256="1" * 64,
            status="active",
            enabled=True,
        )
        output = AgentOutput(
            id="ao-synthesis-v1",
            snapshot_id="snapshot-synthesis-v1",
            asset="XAUUSD",
            trade_date=date(2026, 7, 10),
            run_id="run-synthesis-v1",
            agent_name="synthesis_agent",
            module="synthesis",
            version="1.0",
            status="success",
            bias="neutral",
            confidence=0.61,
            input_snapshot_ids={},
            source_refs=[],
            key_findings=[],
            risk_points=[],
            watchlist=[],
            invalid_conditions=[],
            summary="综合结论。",
            payload={},
            payload_sha256="a" * 64,
            prompt_version_id=prompt_version.id,
        )
        db.add_all([prompt_version, output])
        db.commit()

    monkeypatch.setattr(agent_read_model, "SessionLocal", session_factory)

    summaries = agent_read_model._latest_agent_summaries(["synthesis_agent"])

    assert summaries["synthesis_agent"]["prompt_version"] == "v1"
    assert summaries["synthesis_agent"]["prompt_checksum"] == "1" * 64
