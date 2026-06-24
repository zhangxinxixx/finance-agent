"""TDD: Analysis DB models — SQLite-compatible tests.

All tests use in-memory SQLite to avoid depending on local PostgreSQL.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from database.models.analysis import (
    AgentOutput,
    AnalysisBase,
    AnalysisSnapshot,
    FinalAnalysisResult,
    ensure_analysis_tables,
)


def _make_engine() -> create_engine:
    """In-memory SQLite engine for portable tests."""
    return create_engine("sqlite:///:memory:", echo=False)


def _make_engine_with_tables():
    """In-memory SQLite engine with analysis tables created."""
    engine = _make_engine()
    ensure_analysis_tables(engine)
    return engine


def _make_session(engine=None) -> Session:
    if engine is None:
        engine = _make_engine()
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# ── RED phase: table creation and structure ──


def test_analysis_tables_can_be_created_in_sqlite():
    """All three analysis tables create without error on SQLite."""
    engine = _make_engine()
    ensure_analysis_tables(engine)

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "analysis_snapshots" in tables
    assert "agent_outputs" in tables
    assert "final_analysis_results" in tables


def test_create_twice_is_idempotent():
    """Repeated create_all must not error (checkfirst semantics)."""
    engine = _make_engine()
    ensure_analysis_tables(engine)
    # second call must not raise
    ensure_analysis_tables(engine)


def test_analysis_base_independent():
    """AnalysisBase tables must not appear in task.Base metadata."""
    from database.models.task import Base as TaskBase

    analysis_tables = {t.name for t in AnalysisBase.metadata.tables.values()}
    task_tables = {t.name for t in TaskBase.metadata.tables.values()}

    # task tables must not include analysis tables
    assert "analysis_snapshots" not in task_tables
    assert "agent_outputs" not in task_tables
    assert "final_analysis_results" not in task_tables

    # analysis tables must not include task tables
    assert "task_runs" not in analysis_tables
    assert "task_steps" not in analysis_tables


# ── Column type validation ──


def test_analysis_snapshot_columns_use_portable_types():
    """AnalysisSnapshot columns must use String(36) for UUID, JSON for JSONB, Float for NUMERIC."""
    cols = AnalysisSnapshot.__table__.columns

    # UUID stored as String(36) — portable
    assert str(cols["id"].type) == "VARCHAR(36)"
    assert str(cols["snapshot_id"].type).startswith("VARCHAR")
    assert str(cols["asset"].type).startswith("VARCHAR")
    assert str(cols["trade_date"].type) == "DATE"
    assert str(cols["run_id"].type).startswith("VARCHAR")
    assert str(cols["status"].type).startswith("VARCHAR")

    # JSONB → JSON (portable)
    assert "json" in str(cols["input_snapshot_ids"].type).lower()
    assert "json" in str(cols["source_refs"].type).lower()
    assert "json" in str(cols["macro"].type).lower()
    assert "json" in str(cols["options"].type).lower()
    assert "json" in str(cols["positioning"].type).lower()
    assert "json" in str(cols["payload"].type).lower()

    # NUMERIC → Float (portable)
    assert "float" not in str(cols["payload_sha256"].type).lower()  # it's a text column, not float
    assert str(cols["payload_sha256"].type).startswith("VARCHAR")


def test_agent_output_columns_use_portable_types():
    """AgentOutput confidence must use Float (portable NUMERIC)."""
    cols = AgentOutput.__table__.columns

    assert str(cols["id"].type) == "VARCHAR(36)"
    assert str(cols["confidence"].type) == "FLOAT"  # NUMERIC(5,4) → Float


def test_final_analysis_columns_use_portable_types():
    """FinalAnalysisResult confidence must use Float (portable NUMERIC)."""
    cols = FinalAnalysisResult.__table__.columns

    assert str(cols["id"].type) == "VARCHAR(36)"
    assert str(cols["confidence"].type) == "FLOAT"
    assert "json" in str(cols["strategy_card"].type).lower()
    assert "json" in str(cols["payload"].type).lower()


# ── Constraint and index validation ──


def test_analysis_snapshot_unique_constraint():
    """Unique constraint on (asset, trade_date, run_id, snapshot_id)."""
    inspector = inspect(_make_engine_with_tables())

    uq_names = [c["name"] for c in inspector.get_unique_constraints("analysis_snapshots")]
    assert any("uq_analysis_snapshot" in name for name in uq_names), f"Expected uq_analysis_snapshot*, got {uq_names}"


def test_agent_output_unique_constraint():
    """Unique constraint on (snapshot_id, agent_name, module, version)."""
    inspector = inspect(_make_engine_with_tables())

    uq_names = [c["name"] for c in inspector.get_unique_constraints("agent_outputs")]
    has_uq = any("uq_agent_output" in name for name in uq_names)
    assert has_uq, f"Expected uq_agent_output*, got {uq_names}"


def test_final_analysis_unique_constraint():
    """Unique constraint on (asset, trade_date, run_id)."""
    inspector = inspect(_make_engine_with_tables())

    uq_names = [c["name"] for c in inspector.get_unique_constraints("final_analysis_results")]
    has_uq = any("uq_final_analysis" in name for name in uq_names)
    assert has_uq, f"Expected uq_final_analysis*, got {uq_names}"


def test_analysis_snapshot_indexes():
    """Expected indexes exist on analysis_snapshots."""
    inspector = inspect(_make_engine_with_tables())

    index_names = {idx["name"] for idx in inspector.get_indexes("analysis_snapshots")}

    # Must have indexes on run_id and snapshot_id (in addition to unique constraint index)
    has_run_id = any("run_id" in name for name in index_names)
    has_snapshot_id = any("snapshot_id" in name for name in index_names)
    # asset+trade_date composite index
    has_asset_date = any("asset" in name and "date" in name for name in index_names)

    assert has_run_id, f"Missing run_id index, got {index_names}"
    assert has_snapshot_id, f"Missing snapshot_id index, got {index_names}"
    assert has_asset_date, f"Missing asset+trade_date index, got {index_names}"


def test_agent_output_indexes():
    """Expected indexes exist on agent_outputs."""
    inspector = inspect(_make_engine_with_tables())

    index_names = {idx["name"] for idx in inspector.get_indexes("agent_outputs")}

    has_run_id = any("run_id" in name for name in index_names)
    has_snapshot_id = any("snapshot_id" in name for name in index_names)
    has_agent = any("agent_name" in name for name in index_names)
    has_module = any("module" in name for name in index_names)
    has_status = any("status" in name for name in index_names)

    assert has_run_id, f"Missing run_id index, got {index_names}"
    assert has_snapshot_id, f"Missing snapshot_id index, got {index_names}"
    assert has_agent, f"Missing agent_name index, got {index_names}"
    assert has_module, f"Missing module index, got {index_names}"
    assert has_status, f"Missing status index, got {index_names}"


def test_final_analysis_indexes():
    """Expected indexes exist on final_analysis_results."""
    inspector = inspect(_make_engine_with_tables())

    index_names = {idx["name"] for idx in inspector.get_indexes("final_analysis_results")}

    has_run_id = any("run_id" in name for name in index_names)
    has_snapshot_id = any("snapshot_id" in name for name in index_names)
    has_bias = any("bias" in name for name in index_names)

    assert has_run_id, f"Missing run_id index, got {index_names}"
    assert has_snapshot_id, f"Missing snapshot_id index, got {index_names}"
    assert has_bias, f"Missing final_bias index, got {index_names}"


# ── Basic insert/read roundtrip ──


def test_analysis_snapshot_insert_and_read():
    """Basic roundtrip: insert a snapshot and read it back."""
    session = _make_session()
    snapshot_id_val = "snap-2026-05-14-test"

    snap = AnalysisSnapshot(
        snapshot_id=snapshot_id_val,
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-test-001",
        status="success",
        input_snapshot_ids={"macro": "macro-001"},
        source_refs=["fred://dgs10"],
        macro={"dgs10": 4.42},
        payload={"macro": {"dgs10": 4.42}},
        payload_sha256="abc123",
        artifact_path="storage/features/snapshots/XAUUSD/2026-05-14/run-test-001/premarket_snapshot.json",
    )
    session.add(snap)
    session.commit()

    result = session.query(AnalysisSnapshot).filter_by(snapshot_id=snapshot_id_val).one()
    assert result.asset == "XAUUSD"
    assert result.trade_date == date(2026, 5, 14)
    assert result.run_id == "run-test-001"
    assert result.status == "success"
    assert result.input_snapshot_ids == {"macro": "macro-001"}
    assert result.source_refs == ["fred://dgs10"]
    assert result.macro == {"dgs10": 4.42}
    assert result.payload == {"macro": {"dgs10": 4.42}}
    assert result.payload_sha256 == "abc123"


def test_agent_output_insert_and_read():
    """Basic roundtrip: insert an agent_output and read it back."""
    session = _make_session()

    # Insert parent snapshot first (FK)
    snap = AnalysisSnapshot(
        snapshot_id="snap-agent-test",
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-test-002",
        status="success",
        input_snapshot_ids={},
        source_refs=[],
        payload={},
        payload_sha256="dummy",
        artifact_path="/tmp/dummy.json",
    )
    session.add(snap)
    session.flush()

    ao = AgentOutput(
        snapshot_id="snap-agent-test",
        analysis_snapshot_db_id=snap.id,
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-test-002",
        agent_name="macro_agent",
        module="macro_liquidity",
        version="1.0",
        status="success",
        bias="bullish",
        confidence=0.8500,
        input_snapshot_ids={"macro": "macro-001"},
        source_refs=["fred://dgs10"],
        key_findings=[{"finding": "DXY weakening"}],
        risk_points=[{"risk": "Fed hawkish surprise"}],
        watchlist=[],
        invalid_conditions=[],
        summary="Bullish on gold",
        payload={"bias": "bullish"},
        payload_sha256="def456",
    )
    session.add(ao)
    session.commit()

    result = session.query(AgentOutput).filter_by(snapshot_id="snap-agent-test").one()
    assert result.agent_name == "macro_agent"
    assert result.bias == "bullish"
    assert result.confidence == 0.8500
    assert result.key_findings == [{"finding": "DXY weakening"}]
    assert result.risk_points == [{"risk": "Fed hawkish surprise"}]
    assert result.summary == "Bullish on gold"
    assert result.analysis_snapshot_db_id == snap.id


def test_final_analysis_insert_and_read():
    """Basic roundtrip: insert a final_analysis_result and read it back."""
    session = _make_session()

    # Insert parent snapshot first (FK)
    snap = AnalysisSnapshot(
        snapshot_id="snap-final-test",
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-test-003",
        status="success",
        input_snapshot_ids={},
        source_refs=[],
        payload={},
        payload_sha256="dummy",
        artifact_path="/tmp/dummy.json",
    )
    session.add(snap)
    session.flush()

    far = FinalAnalysisResult(
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-test-003",
        snapshot_id="snap-final-test",
        analysis_snapshot_db_id=snap.id,
        final_bias="bullish",
        confidence=0.7200,
        market_state="risk-on",
        scenario_summary="Gold bullish on DXY weakness",
        is_trade_instruction=False,
        input_snapshot_ids={"macro": "macro-001"},
        source_refs=["fred://dgs10"],
        source_agent_outputs=["ao-macro-001"],
        risk_points=[{"risk": "CPI surprise"}],
        watchlist=["XAUUSD 2680 resistance"],
        invalid_conditions=[],
        strategy_card={"entry": 2650, "target": 2720},
        run_summaries={"steps": ["collect", "parse", "analyze"]},
        payload={"final": "report"},
        final_report_path="storage/outputs/final_report/XAUUSD/2026-05-14/run-test-003/final_report.md",
        strategy_card_json_path="storage/outputs/strategy_card/XAUUSD/2026-05-14/run-test-003/strategy_card.json",
        final_report_sha256="aaa111",
        payload_sha256="zzz999",
    )
    session.add(far)
    session.commit()

    result = session.query(FinalAnalysisResult).filter_by(run_id="run-test-003").one()
    assert result.final_bias == "bullish"
    assert result.confidence == 0.7200
    assert result.scenario_summary == "Gold bullish on DXY weakness"
    assert result.strategy_card == {"entry": 2650, "target": 2720}
    assert result.source_agent_outputs == ["ao-macro-001"]
    assert result.analysis_snapshot_db_id == snap.id


# ── JSON column roundtrip ──


def test_analysis_snapshot_json_columns_preserve_types():
    """JSON columns roundtrip dicts and lists correctly on SQLite."""
    session = _make_session()

    nested = {"key": "value", "list": [1, 2, 3]}
    snap = AnalysisSnapshot(
        snapshot_id="json-test",
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-json-001",
        input_snapshot_ids={"macro": "m1", "options": "o1"},
        source_refs=["s1", "s2"],
        macro={"dgs10": 4.42, "dxy": 104.5},
        options={"wall": {"strike": 2600}},
        positioning=None,
        news=None,
        technical=None,
        payload=nested,
        payload_sha256="sha-json",
        artifact_path="/tmp/json.json",
    )
    session.add(snap)
    session.commit()

    result = session.query(AnalysisSnapshot).filter_by(snapshot_id="json-test").one()
    assert result.input_snapshot_ids == {"macro": "m1", "options": "o1"}
    assert result.source_refs == ["s1", "s2"]
    assert result.macro["dgs10"] == 4.42
    assert result.macro["dxy"] == 104.5
    assert result.options["wall"]["strike"] == 2600
    assert result.payload["list"] == [1, 2, 3]


def test_agent_output_json_columns_preserve_types():
    """AgentOutput JSONB columns roundtrip correctly."""
    session = _make_session()
    snap = AnalysisSnapshot(
        snapshot_id="ao-json-test",
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-ao-json",
        input_snapshot_ids={},
        source_refs=[],
        payload={},
        payload_sha256="dummy",
        artifact_path="/tmp/dummy.json",
    )
    session.add(snap)
    session.flush()

    ao = AgentOutput(
        snapshot_id="ao-json-test",
        analysis_snapshot_db_id=snap.id,
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-ao-json",
        agent_name="risk_agent",
        module="risk",
        status="success",
        bias="neutral",
        confidence=0.5000,
        input_snapshot_ids={"a": "b"},
        source_refs=["src1"],
        key_findings=[{"k": "v1"}, {"k": "v2"}],
        risk_points=[{"r": "high"}],
        watchlist=["item1", "item2"],
        invalid_conditions=[],
        summary="neutral",
        payload={"data": 42},
        payload_sha256="sha-ao",
    )
    session.add(ao)
    session.commit()

    result = session.query(AgentOutput).filter_by(snapshot_id="ao-json-test").one()
    assert result.key_findings == [{"k": "v1"}, {"k": "v2"}]
    assert result.risk_points == [{"r": "high"}]
    assert result.watchlist == ["item1", "item2"]
    assert result.payload == {"data": 42}


def test_final_analysis_json_columns_preserve_types():
    """FinalAnalysisResult JSONB columns roundtrip correctly."""
    session = _make_session()
    snap = AnalysisSnapshot(
        snapshot_id="far-json-test",
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-far-json",
        input_snapshot_ids={},
        source_refs=[],
        payload={},
        payload_sha256="dummy",
        artifact_path="/tmp/dummy.json",
    )
    session.add(snap)
    session.flush()

    far = FinalAnalysisResult(
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-far-json",
        snapshot_id="far-json-test",
        analysis_snapshot_db_id=snap.id,
        input_snapshot_ids={"x": "y"},
        source_refs=["src-a"],
        source_agent_outputs=["ao-1", "ao-2"],
        risk_points=[{"severity": "critical"}],
        watchlist=["w1"],
        invalid_conditions=[],
        strategy_card={"entry": 2650, "stop": 2620},
        run_summaries={"phases": [1, 2, 3]},
        payload={"report": "content"},
        payload_sha256="sha-far",
    )
    session.add(far)
    session.commit()

    result = session.query(FinalAnalysisResult).filter_by(run_id="run-far-json").one()
    assert result.input_snapshot_ids == {"x": "y"}
    assert result.source_agent_outputs == ["ao-1", "ao-2"]
    assert result.strategy_card["entry"] == 2650
    assert result.strategy_card["stop"] == 2620
    assert result.run_summaries["phases"] == [1, 2, 3]


# ── Nullable FK and optional columns ──


def test_agent_output_without_snapshot_fk():
    """AgentOutput can be created without analysis_snapshot_db_id FK."""
    session = _make_session()

    ao = AgentOutput(
        snapshot_id="no-fk-test",
        analysis_snapshot_db_id=None,
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-no-fk",
        agent_name="test_agent",
        module="test_module",
        status="success",
        bias="neutral",
        confidence=0.5000,
        input_snapshot_ids={},
        source_refs=[],
        payload={},
        payload_sha256="sha-no-fk",
    )
    session.add(ao)
    session.commit()

    result = session.query(AgentOutput).filter_by(snapshot_id="no-fk-test").one()
    assert result.analysis_snapshot_db_id is None


def test_final_analysis_without_snapshot():
    """FinalAnalysisResult can be created without snapshot_id or FK."""
    session = _make_session()

    far = FinalAnalysisResult(
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-no-snap",
        snapshot_id=None,
        analysis_snapshot_db_id=None,
        input_snapshot_ids={},
        source_refs=[],
        source_agent_outputs=[],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        payload={},
        payload_sha256="sha-no-snap",
    )
    session.add(far)
    session.commit()

    result = session.query(FinalAnalysisResult).filter_by(run_id="run-no-snap").one()
    assert result.snapshot_id is None
    assert result.analysis_snapshot_db_id is None


# ── Default values ──


def test_analysis_snapshot_default_values():
    """Default values populate correctly."""
    session = _make_session()

    snap = AnalysisSnapshot(
        snapshot_id="defaults-test",
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-defaults",
        payload={"x": 1},
        payload_sha256="sha-defaults",
        artifact_path="/tmp/defaults.json",
    )
    session.add(snap)
    session.commit()

    result = session.query(AnalysisSnapshot).filter_by(snapshot_id="defaults-test").one()
    assert result.status == "success"
    assert result.input_snapshot_ids == {}
    assert result.source_refs == []
    assert result.created_at is not None


def test_agent_output_default_values():
    """AgentOutput defaults populate correctly."""
    session = _make_session()

    ao = AgentOutput(
        snapshot_id="ao-defaults",
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-ao-defaults",
        agent_name="test",
        module="test",
        status="success",
        bias="neutral",
        confidence=0.5000,
        input_snapshot_ids={},
        payload={},
        payload_sha256="sha-ao-defaults",
    )
    session.add(ao)
    session.commit()

    result = session.query(AgentOutput).filter_by(snapshot_id="ao-defaults").one()
    assert result.version == "1.0"
    assert result.source_refs == []
    assert result.key_findings == []
    assert result.risk_points == []
    assert result.watchlist == []
    assert result.invalid_conditions == []
    assert result.summary == ""


def test_final_analysis_default_values():
    """FinalAnalysisResult defaults populate correctly."""
    session = _make_session()

    far = FinalAnalysisResult(
        asset="XAUUSD",
        trade_date=date(2026, 5, 14),
        run_id="run-far-defaults",
        payload={},
        payload_sha256="sha-far-defaults",
    )
    session.add(far)
    session.commit()

    result = session.query(FinalAnalysisResult).filter_by(run_id="run-far-defaults").one()
    assert result.is_trade_instruction is False
    assert result.input_snapshot_ids == {}
    assert result.source_refs == []
    assert result.source_agent_outputs == []
    assert result.risk_points == []
    assert result.watchlist == []
    assert result.invalid_conditions == []
    assert result.created_at is not None
