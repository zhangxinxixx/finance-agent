"""TDD: Analysis persistence repository — idempotent upsert and query tests.

All tests use in-memory SQLite; no dependency on local PostgreSQL.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from database.models.analysis import (
    AgentOutput,
    AnalysisSnapshot,
    FinalAnalysisResult,
    PromptVersion,
    ensure_analysis_tables,
)


# ── Test fixtures / helpers ──

def _make_engine():
    return create_engine("sqlite:///:memory:", echo=False)


def _make_session(engine=None) -> Session:
    if engine is None:
        engine = _make_engine()
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


_SAMPLE_SNAPSHOT_PAYLOAD = {
    "snapshot_id": "snap-2026-05-14-001",
    "asset": "XAUUSD",
    "trade_date": "2026-05-14",
    "run_id": "run-001",
    "snapshot_time": "2026-05-14T10:00:00Z",
    "status": "success",
    "input_snapshot_ids": {"macro": "macro-001"},
    "source_refs": ["fred://dgs10"],
    "macro": {"dgs10": 4.42},
    "options": {"wall": {"strike": 2600}},
    "positioning": None,
    "news": None,
    "technical": None,
    "payload": {"full": "snapshot_data"},
}

_SAMPLE_AGENT_OUTPUT_PAYLOAD = {
    "snapshot_id": "snap-2026-05-14-001",
    "analysis_snapshot_db_id": None,
    "asset": "XAUUSD",
    "trade_date": "2026-05-14",
    "run_id": "run-001",
    "agent_name": "macro_agent",
    "module": "macro_liquidity",
    "version": "1.0",
    "status": "success",
    "bias": "bullish",
    "confidence": 0.8500,
    "input_snapshot_ids": {"macro": "macro-001"},
    "source_refs": ["fred://dgs10"],
    "key_findings": [{"finding": "DXY weakening"}],
    "risk_points": [{"risk": "Fed hawkish surprise"}],
    "watchlist": [],
    "invalid_conditions": [],
    "summary": "Bullish on gold",
    "payload": {"bias": "bullish", "score": 0.85},
}

_SAMPLE_FINAL_PAYLOAD = {
    "asset": "XAUUSD",
    "trade_date": "2026-05-14",
    "run_id": "run-001",
    "snapshot_id": "snap-2026-05-14-001",
    "analysis_snapshot_db_id": None,
    "final_bias": "bullish",
    "confidence": 0.7200,
    "market_state": "risk-on",
    "scenario_summary": "Gold bullish on DXY weakness",
    "is_trade_instruction": False,
    "input_snapshot_ids": {"macro": "macro-001"},
    "source_refs": ["fred://dgs10"],
    "source_agent_outputs": ["ao-macro-001"],
    "risk_points": [{"risk": "CPI surprise"}],
    "watchlist": ["XAUUSD 2680 resistance"],
    "invalid_conditions": [],
    "strategy_card": {"entry": 2650, "target": 2720},
    "run_summaries": {"steps": ["collect", "parse", "analyze"]},
    "payload": {"final": "report"},
}

_SAMPLE_FINAL_PATHS = {
    "final_report_path": "storage/outputs/final_report/XAUUSD/2026-05-14/run-001/final_report.md",
    "strategy_card_json_path": "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/strategy_card.json",
    "strategy_card_md_path": "storage/outputs/strategy_card/XAUUSD/2026-05-14/run-001/strategy_card.md",
    "run_summary_path": "storage/outputs/run/2026-05-14/run-001/step_summaries.json",
    "final_report_sha256": "abc123",
    "strategy_card_sha256": "def456",
}


def _sha256_hex(data: dict) -> str:
    """Deterministic SHA256 of JSON-serialized dict with sorted keys."""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _iso_date(d: str) -> date:
    return date.fromisoformat(d)


# ═══════════════════════════════════════════════════════════════════
# AnalysisSnapshot — idempotent upsert
# ═══════════════════════════════════════════════════════════════════


def test_upsert_analysis_snapshot_creates_new_record():
    """First upsert creates a new row."""
    from database.queries.analysis import upsert_analysis_snapshot

    session = _make_session()

    result = upsert_analysis_snapshot(
        session,
        payload=_SAMPLE_SNAPSHOT_PAYLOAD,
        artifact_path="storage/features/snapshots/XAUUSD/2026-05-14/run-001/premarket_snapshot.json",
    )
    session.commit()

    # Verify the returned snapshot
    assert result.snapshot_id == "snap-2026-05-14-001"
    assert result.asset == "XAUUSD"
    assert result.trade_date == date(2026, 5, 14)
    assert result.run_id == "run-001"
    assert result.macro == {"dgs10": 4.42}
    assert result.payload == {"full": "snapshot_data"}
    assert result.payload_sha256 == _sha256_hex({"full": "snapshot_data"})

    # Verify only one row exists
    rows = session.scalars(
        select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == "snap-2026-05-14-001")
    ).all()
    assert len(rows) == 1


def test_upsert_analysis_snapshot_is_idempotent():
    """Same snapshot_id upsert must not create duplicates."""
    from database.queries.analysis import upsert_analysis_snapshot

    session = _make_session()
    artifact_path = "storage/features/snapshots/XAUUSD/2026-05-14/run-001/premarket_snapshot.json"

    first = upsert_analysis_snapshot(session, payload=_SAMPLE_SNAPSHOT_PAYLOAD, artifact_path=artifact_path)
    session.commit()

    # Second upsert with same snapshot_id — should return existing row, not duplicate
    second = upsert_analysis_snapshot(session, payload=_SAMPLE_SNAPSHOT_PAYLOAD, artifact_path=artifact_path)
    session.commit()

    assert first.id == second.id

    rows = session.scalars(
        select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == "snap-2026-05-14-001")
    ).all()
    assert len(rows) == 1


def test_upsert_analysis_snapshot_preserves_source_refs_and_input_snapshot_ids():
    """source_refs and input_snapshot_ids are stored and roundtripped correctly."""
    from database.queries.analysis import upsert_analysis_snapshot

    session = _make_session()
    artifact_path = "storage/features/snapshots/XAUUSD/2026-05-14/run-001/premarket_snapshot.json"

    result = upsert_analysis_snapshot(session, payload=_SAMPLE_SNAPSHOT_PAYLOAD, artifact_path=artifact_path)
    session.commit()

    assert result.input_snapshot_ids == {"macro": "macro-001"}
    assert result.source_refs == ["fred://dgs10"]
    assert result.artifact_path == artifact_path


def test_upsert_analysis_snapshot_preserves_null_modules():
    """Unavailable modules (None) are preserved."""
    from database.queries.analysis import upsert_analysis_snapshot

    session = _make_session()
    artifact_path = "storage/features/snapshots/XAUUSD/2026-05-14/run-001/premarket_snapshot.json"

    result = upsert_analysis_snapshot(session, payload=_SAMPLE_SNAPSHOT_PAYLOAD, artifact_path=artifact_path)
    session.commit()

    assert result.positioning is None
    assert result.news is None
    assert result.technical is None


# ═══════════════════════════════════════════════════════════════════
# AnalysisSnapshot — query
# ═══════════════════════════════════════════════════════════════════


def test_get_analysis_snapshot_returns_record():
    """get_analysis_snapshot returns the correct record."""
    from database.queries.analysis import get_analysis_snapshot, upsert_analysis_snapshot

    session = _make_session()
    artifact_path = "storage/features/snapshots/XAUUSD/2026-05-14/run-001/premarket_snapshot.json"
    upsert_analysis_snapshot(session, payload=_SAMPLE_SNAPSHOT_PAYLOAD, artifact_path=artifact_path)
    session.commit()

    snap = get_analysis_snapshot(session, asset="XAUUSD", trade_date="2026-05-14", run_id="run-001")
    assert snap is not None
    assert snap.snapshot_id == "snap-2026-05-14-001"


def test_get_analysis_snapshot_returns_none_for_missing():
    """get_analysis_snapshot returns None when no matching record."""
    from database.queries.analysis import get_analysis_snapshot

    session = _make_session()
    result = get_analysis_snapshot(session, asset="XAUUSD", trade_date="2099-01-01", run_id="nonexistent")
    assert result is None


def test_get_analysis_snapshot_latest_returns_most_recent():
    """get_analysis_snapshot_latest returns the snapshot with the latest trade_date."""
    from database.queries.analysis import get_analysis_snapshot_latest, upsert_analysis_snapshot

    session = _make_session()
    artifact_path = "storage/features/snapshots/XAUUSD/{date}/run-{run_id}/premarket_snapshot.json"

    # Insert two snapshots with different dates
    older = dict(_SAMPLE_SNAPSHOT_PAYLOAD)
    older["snapshot_id"] = "snap-older"
    older["trade_date"] = "2026-05-13"
    older["run_id"] = "run-older"
    upsert_analysis_snapshot(
        session, payload=older,
        artifact_path=artifact_path.format(date="2026-05-13", run_id="run-older"),
    )

    newer = dict(_SAMPLE_SNAPSHOT_PAYLOAD)
    newer["snapshot_id"] = "snap-newer"
    newer["trade_date"] = "2026-05-14"
    newer["run_id"] = "run-newer"
    upsert_analysis_snapshot(
        session, payload=newer,
        artifact_path=artifact_path.format(date="2026-05-14", run_id="run-newer"),
    )
    session.commit()

    latest = get_analysis_snapshot_latest(session, asset="XAUUSD")
    assert latest is not None
    assert latest.snapshot_id == "snap-newer"
    assert latest.trade_date == date(2026, 5, 14)


def test_get_analysis_snapshot_latest_returns_none_when_empty():
    """get_analysis_snapshot_latest returns None when no records."""
    from database.queries.analysis import get_analysis_snapshot_latest

    session = _make_session()
    result = get_analysis_snapshot_latest(session, asset="XAUUSD")
    assert result is None


# ═══════════════════════════════════════════════════════════════════
# AgentOutput — idempotent upsert
# ═══════════════════════════════════════════════════════════════════


def test_upsert_agent_output_creates_new_record():
    """First upsert creates a new row."""
    from database.queries.analysis import upsert_agent_output

    session = _make_session()

    result = upsert_agent_output(session, payload=_SAMPLE_AGENT_OUTPUT_PAYLOAD)
    session.commit()

    assert result.snapshot_id == "snap-2026-05-14-001"
    assert result.agent_name == "macro_agent"
    assert result.module == "macro_liquidity"
    assert result.version == "1.0"
    assert result.bias == "bullish"
    assert result.confidence == 0.8500
    assert result.payload == {"bias": "bullish", "score": 0.85}
    assert result.payload_sha256 == _sha256_hex({"bias": "bullish", "score": 0.85})

    # Only one row
    rows = session.scalars(
        select(AgentOutput).where(
            AgentOutput.snapshot_id == "snap-2026-05-14-001",
            AgentOutput.agent_name == "macro_agent",
        )
    ).all()
    assert len(rows) == 1


def test_upsert_agent_output_is_idempotent():
    """Same (snapshot_id, agent_name, module, version) upsert must not create duplicates."""
    from database.queries.analysis import upsert_agent_output

    session = _make_session()

    first = upsert_agent_output(session, payload=_SAMPLE_AGENT_OUTPUT_PAYLOAD)
    session.commit()

    # Insert a second with same key but updated confidence
    updated = dict(_SAMPLE_AGENT_OUTPUT_PAYLOAD)
    updated["confidence"] = 0.9000
    updated["bias"] = "strong_bullish"
    updated["summary"] = "Strong bullish on gold"
    updated["payload"] = {"bias": "strong_bullish", "score": 0.90}

    second = upsert_agent_output(session, payload=updated)
    session.commit()

    # Should be same record (idempotent on key), updated values
    assert first.id == second.id
    assert second.confidence == 0.9000
    assert second.bias == "strong_bullish"
    assert second.summary == "Strong bullish on gold"

    rows = session.scalars(
        select(AgentOutput).where(
            AgentOutput.snapshot_id == "snap-2026-05-14-001",
            AgentOutput.agent_name == "macro_agent",
        )
    ).all()
    assert len(rows) == 1


def test_upsert_agent_output_preserves_json_fields():
    """source_refs, key_findings, risk_points, watchlist, invalid_conditions are roundtripped."""
    from database.queries.analysis import upsert_agent_output

    session = _make_session()

    result = upsert_agent_output(session, payload=_SAMPLE_AGENT_OUTPUT_PAYLOAD)
    session.commit()

    assert result.source_refs == ["fred://dgs10"]
    assert result.key_findings == [{"finding": "DXY weakening"}]
    assert result.risk_points == [{"risk": "Fed hawkish surprise"}]
    assert result.watchlist == []
    assert result.invalid_conditions == []


def test_upsert_agent_output_fails_fast_on_snapshot_run_mismatch():
    """AgentOutput write should fail when snapshot_id resolves to a different run_id."""
    from database.queries.analysis import upsert_agent_output, upsert_analysis_snapshot

    session = _make_session()
    artifact_path = "storage/features/snapshots/XAUUSD/2026-05-14/run-actual/premarket_snapshot.json"
    snapshot_payload = dict(_SAMPLE_SNAPSHOT_PAYLOAD)
    snapshot_payload["run_id"] = "run-actual"
    upsert_analysis_snapshot(session, payload=snapshot_payload, artifact_path=artifact_path)

    conflicting = dict(_SAMPLE_AGENT_OUTPUT_PAYLOAD)
    conflicting["run_id"] = "run-conflict"

    import pytest

    with pytest.raises(ValueError, match="agent output lineage conflict"):
        upsert_agent_output(session, payload=conflicting)


def test_upsert_agent_output_accepts_consistent_snapshot_lineage():
    """AgentOutput write remains valid when snapshot lineage is consistent."""
    from database.queries.analysis import upsert_agent_output, upsert_analysis_snapshot

    session = _make_session()
    artifact_path = "storage/features/snapshots/XAUUSD/2026-05-14/run-001/premarket_snapshot.json"
    snapshot = upsert_analysis_snapshot(session, payload=_SAMPLE_SNAPSHOT_PAYLOAD, artifact_path=artifact_path)

    payload = dict(_SAMPLE_AGENT_OUTPUT_PAYLOAD)
    payload["analysis_snapshot_db_id"] = snapshot.id

    row = upsert_agent_output(session, payload=payload)
    session.commit()

    assert row.snapshot_id == _SAMPLE_SNAPSHOT_PAYLOAD["snapshot_id"]
    assert row.run_id == _SAMPLE_SNAPSHOT_PAYLOAD["run_id"]


def test_upsert_agent_output_binds_active_prompt_version_when_missing():
    """AgentOutput persistence should record the active PromptVersion used by the agent."""
    from database.queries.analysis import upsert_agent_output

    session = _make_session()
    prompt = PromptVersion(
        id="pv-macro-active",
        agent_id="macro_agent",
        version="v1",
        prompt_kind="llm",
        prompt_source="apps/analysis/agents/macro_prompt.py",
        prompt_template={"messages": [{"role": "user", "content": "analyze macro"}]},
        prompt_sha256="a" * 64,
        status="active",
        enabled=True,
    )
    session.add(prompt)

    row = upsert_agent_output(session, payload=_SAMPLE_AGENT_OUTPUT_PAYLOAD)
    session.commit()

    assert row.prompt_version_id == "pv-macro-active"


def test_upsert_agent_output_preserves_explicit_prompt_version_id():
    """An explicit prompt_version_id from a runner must take precedence over active lookup."""
    from database.queries.analysis import upsert_agent_output

    session = _make_session()
    prompt = PromptVersion(
        id="pv-macro-active",
        agent_id="macro_agent",
        version="v1",
        prompt_kind="llm",
        prompt_source="apps/analysis/agents/macro_prompt.py",
        prompt_template={"messages": [{"role": "user", "content": "analyze macro"}]},
        prompt_sha256="a" * 64,
        status="active",
        enabled=True,
    )
    session.add(prompt)
    payload = dict(_SAMPLE_AGENT_OUTPUT_PAYLOAD)
    payload["prompt_version_id"] = "pv-explicit-runner"

    row = upsert_agent_output(session, payload=payload)
    session.commit()

    assert row.prompt_version_id == "pv-explicit-runner"


# ═══════════════════════════════════════════════════════════════════
# AgentOutput — query
# ═══════════════════════════════════════════════════════════════════


def test_get_agent_output_returns_record():
    """get_agent_output returns the correct record by snapshot_id + agent_name."""
    from database.queries.analysis import get_agent_output, upsert_agent_output

    session = _make_session()
    upsert_agent_output(session, payload=_SAMPLE_AGENT_OUTPUT_PAYLOAD)
    session.commit()

    ao = get_agent_output(session, snapshot_id="snap-2026-05-14-001", agent_name="macro_agent")
    assert ao is not None
    assert ao.agent_name == "macro_agent"
    assert ao.module == "macro_liquidity"


def test_get_agent_output_returns_none_for_missing():
    """get_agent_output returns None when no matching record."""
    from database.queries.analysis import get_agent_output

    session = _make_session()
    result = get_agent_output(session, snapshot_id="nonexistent", agent_name="nonexistent")
    assert result is None


def test_list_agent_outputs_returns_all_for_snapshot():
    """list_agent_outputs returns all agent outputs for a snapshot_id."""
    from database.queries.analysis import list_agent_outputs, upsert_agent_output

    session = _make_session()

    # Insert two agent outputs for the same snapshot
    upsert_agent_output(session, payload=_SAMPLE_AGENT_OUTPUT_PAYLOAD)

    risk_ao = dict(_SAMPLE_AGENT_OUTPUT_PAYLOAD)
    risk_ao["agent_name"] = "risk_agent"
    risk_ao["module"] = "risk"
    risk_ao["bias"] = "neutral"
    risk_ao["confidence"] = 0.5000
    risk_ao["summary"] = "Neutral on risk"
    risk_ao["payload"] = {"bias": "neutral", "score": 0.50}
    upsert_agent_output(session, payload=risk_ao)
    session.commit()

    results = list_agent_outputs(session, snapshot_id="snap-2026-05-14-001")
    assert len(results) == 2
    agent_names = {r.agent_name for r in results}
    assert agent_names == {"macro_agent", "risk_agent"}


def test_list_agent_outputs_returns_empty_for_no_match():
    """list_agent_outputs returns empty list when no records."""
    from database.queries.analysis import list_agent_outputs

    session = _make_session()
    results = list_agent_outputs(session, snapshot_id="nonexistent")
    assert results == []


# ═══════════════════════════════════════════════════════════════════
# FinalAnalysisResult — idempotent upsert
# ═══════════════════════════════════════════════════════════════════


def test_upsert_final_analysis_creates_new_record():
    """First upsert creates a new row."""
    from database.queries.analysis import upsert_final_analysis_result

    session = _make_session()

    result = upsert_final_analysis_result(
        session,
        payload=_SAMPLE_FINAL_PAYLOAD,
        paths=_SAMPLE_FINAL_PATHS,
    )
    session.commit()

    assert result.asset == "XAUUSD"
    assert result.trade_date == date(2026, 5, 14)
    assert result.run_id == "run-001"
    assert result.final_bias == "bullish"
    assert result.confidence == 0.7200
    assert result.strategy_card == {"entry": 2650, "target": 2720}
    assert result.payload == {"final": "report"}
    assert result.payload_sha256 == _sha256_hex({"final": "report"})
    assert result.final_report_path == _SAMPLE_FINAL_PATHS["final_report_path"]
    assert result.strategy_card_json_path == _SAMPLE_FINAL_PATHS["strategy_card_json_path"]
    assert result.final_report_sha256 == "abc123"
    assert result.strategy_card_sha256 == "def456"

    rows = session.scalars(
        select(FinalAnalysisResult).where(
            FinalAnalysisResult.asset == "XAUUSD",
            FinalAnalysisResult.trade_date == date(2026, 5, 14),
            FinalAnalysisResult.run_id == "run-001",
        )
    ).all()
    assert len(rows) == 1


def test_upsert_final_analysis_updates_not_duplicates():
    """Same (asset, trade_date, run_id) upsert updates the existing row."""
    from database.queries.analysis import upsert_final_analysis_result

    session = _make_session()

    first = upsert_final_analysis_result(
        session, payload=_SAMPLE_FINAL_PAYLOAD, paths=_SAMPLE_FINAL_PATHS,
    )
    session.commit()

    # Upsert again with same key but updated values
    updated_payload = dict(_SAMPLE_FINAL_PAYLOAD)
    updated_payload["final_bias"] = "bearish"
    updated_payload["confidence"] = 0.3500
    updated_payload["scenario_summary"] = "Gold bearish on rate hike"

    updated_paths = dict(_SAMPLE_FINAL_PATHS)
    updated_paths["final_report_sha256"] = "updated_sha"

    second = upsert_final_analysis_result(
        session, payload=updated_payload, paths=updated_paths,
    )
    session.commit()

    assert first.id == second.id
    assert second.final_bias == "bearish"
    assert second.confidence == 0.3500
    assert second.final_report_sha256 == "updated_sha"

    rows = session.scalars(
        select(FinalAnalysisResult).where(
            FinalAnalysisResult.asset == "XAUUSD",
            FinalAnalysisResult.trade_date == date(2026, 5, 14),
            FinalAnalysisResult.run_id == "run-001",
        )
    ).all()
    assert len(rows) == 1


def test_upsert_final_analysis_preserves_source_refs_and_input_ids():
    """source_refs, input_snapshot_ids, source_agent_outputs are preserved."""
    from database.queries.analysis import upsert_final_analysis_result

    session = _make_session()

    result = upsert_final_analysis_result(
        session, payload=_SAMPLE_FINAL_PAYLOAD, paths=_SAMPLE_FINAL_PATHS,
    )
    session.commit()

    assert result.input_snapshot_ids == {"macro": "macro-001"}
    assert result.source_refs == ["fred://dgs10"]
    assert result.source_agent_outputs == ["ao-macro-001"]


def test_upsert_final_analysis_preserves_risk_and_watchlist():
    """risk_points, watchlist, invalid_conditions are preserved."""
    from database.queries.analysis import upsert_final_analysis_result

    session = _make_session()

    result = upsert_final_analysis_result(
        session, payload=_SAMPLE_FINAL_PAYLOAD, paths=_SAMPLE_FINAL_PATHS,
    )
    session.commit()

    assert result.risk_points == [{"risk": "CPI surprise"}]
    assert result.watchlist == ["XAUUSD 2680 resistance"]
    assert result.invalid_conditions == []


def test_upsert_final_analysis_fails_fast_on_snapshot_run_mismatch():
    """FinalAnalysisResult write should fail when snapshot_id resolves to a different run_id."""
    from database.queries.analysis import upsert_analysis_snapshot, upsert_final_analysis_result

    session = _make_session()
    artifact_path = "storage/features/snapshots/XAUUSD/2026-05-14/run-actual/premarket_snapshot.json"
    snapshot_payload = dict(_SAMPLE_SNAPSHOT_PAYLOAD)
    snapshot_payload["run_id"] = "run-actual"
    upsert_analysis_snapshot(session, payload=snapshot_payload, artifact_path=artifact_path)

    conflicting = dict(_SAMPLE_FINAL_PAYLOAD)
    conflicting["run_id"] = "run-conflict"

    import pytest

    with pytest.raises(ValueError, match="final analysis lineage conflict"):
        upsert_final_analysis_result(session, payload=conflicting, paths=_SAMPLE_FINAL_PATHS)


# ═══════════════════════════════════════════════════════════════════
# FinalAnalysisResult — query
# ═══════════════════════════════════════════════════════════════════


def test_get_final_analysis_returns_record():
    """get_final_analysis returns the correct record."""
    from database.queries.analysis import get_final_analysis, upsert_final_analysis_result

    session = _make_session()
    upsert_final_analysis_result(session, payload=_SAMPLE_FINAL_PAYLOAD, paths=_SAMPLE_FINAL_PATHS)
    session.commit()

    result = get_final_analysis(session, asset="XAUUSD", trade_date="2026-05-14", run_id="run-001")
    assert result is not None
    assert result.final_bias == "bullish"


def test_get_final_analysis_returns_none_for_missing():
    """get_final_analysis returns None when no matching record."""
    from database.queries.analysis import get_final_analysis

    session = _make_session()
    result = get_final_analysis(session, asset="XAUUSD", trade_date="2099-01-01", run_id="nonexistent")
    assert result is None


def test_get_final_analysis_latest_returns_most_recent():
    """get_final_analysis_latest returns the result with the latest trade_date."""
    from database.queries.analysis import get_final_analysis_latest, upsert_final_analysis_result

    session = _make_session()

    # Insert two final results
    older = dict(_SAMPLE_FINAL_PAYLOAD)
    older["trade_date"] = "2026-05-13"
    older["run_id"] = "run-older"
    older["final_bias"] = "bearish"
    upsert_final_analysis_result(session, payload=older, paths=_SAMPLE_FINAL_PATHS)

    newer = dict(_SAMPLE_FINAL_PAYLOAD)
    newer["trade_date"] = "2026-05-14"
    newer["run_id"] = "run-newer"
    newer["final_bias"] = "bullish"
    upsert_final_analysis_result(session, payload=newer, paths=_SAMPLE_FINAL_PATHS)
    session.commit()

    latest = get_final_analysis_latest(session, asset="XAUUSD")
    assert latest is not None
    assert latest.final_bias == "bullish"
    assert latest.trade_date == date(2026, 5, 14)


def test_get_final_analysis_latest_returns_none_when_empty():
    """get_final_analysis_latest returns None when no records."""
    from database.queries.analysis import get_final_analysis_latest

    session = _make_session()
    result = get_final_analysis_latest(session, asset="XAUUSD")
    assert result is None


# ═══════════════════════════════════════════════════════════════════
# payload_sha256 — deterministic
# ═══════════════════════════════════════════════════════════════════


def test_payload_sha256_is_deterministic_across_upserts():
    """payload_sha256 is identical for the same payload dict."""
    from database.queries.analysis import upsert_analysis_snapshot

    session = _make_session()
    artifact_path = "storage/features/snapshots/XAUUSD/2026-05-14/run-001/premarket_snapshot.json"

    first = upsert_analysis_snapshot(session, payload=_SAMPLE_SNAPSHOT_PAYLOAD, artifact_path=artifact_path)
    session.commit()

    # Create a fresh session and upsert again — sha256 must match
    session2 = _make_session()
    second = upsert_analysis_snapshot(session2, payload=_SAMPLE_SNAPSHOT_PAYLOAD, artifact_path=artifact_path)
    session2.commit()

    assert first.payload_sha256 == second.payload_sha256
    assert first.payload_sha256 == _sha256_hex({"full": "snapshot_data"})


def test_payload_sha256_differs_for_different_payloads():
    """payload_sha256 changes when the payload content changes."""
    from database.queries.analysis import upsert_analysis_snapshot

    session = _make_session()
    artifact_path = "storage/features/snapshots/XAUUSD/2026-05-14/run-001/premarket_snapshot.json"

    first = upsert_analysis_snapshot(session, payload=_SAMPLE_SNAPSHOT_PAYLOAD, artifact_path=artifact_path)
    session.commit()

    modified = dict(_SAMPLE_SNAPSHOT_PAYLOAD)
    modified["snapshot_id"] = "snap-different"
    modified["payload"] = {"full": "different_data"}

    session2 = _make_session()
    second = upsert_analysis_snapshot(session2, payload=modified, artifact_path=artifact_path)
    session2.commit()

    assert first.payload_sha256 != second.payload_sha256


# ═══════════════════════════════════════════════════════════════════
# ensure_analysis_tables is callable from session
# ═══════════════════════════════════════════════════════════════════


def test_ensure_analysis_tables_from_session():
    """ensure_analysis_tables accepts a Session and creates tables."""
    engine = _make_engine()
    session = sessionmaker(bind=engine)()

    ensure_analysis_tables(session)

    from sqlalchemy import inspect
    tables = inspect(engine).get_table_names()
    assert "analysis_snapshots" in tables
    assert "agent_outputs" in tables
    assert "final_analysis_results" in tables
