from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.analysis.state.repository import append_analysis_state_scoped, advance_canonical_head_scoped
from apps.analysis.state.schemas import (
    ANALYSIS_STATE_MACHINE_VERSION,
    AnalysisStateDocumentV11,
    AnalysisTransitionDocumentV11,
    StateChange,
    StateMaterializationAuthority,
    TransitionAction,
)
from apps.worker.runner import _build_persisted_state_shadow_input
from database.models.analysis import AnalysisBase, AnalysisSnapshot


PRIOR_RUN = "00000000-0000-0000-0000-000000000071"
CURRENT_RUN = "00000000-0000-0000-0000-000000000072"
PRIOR_AT = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
CURRENT_AT = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


def _snapshot(*, run_id: str, trade_date: date, observed_at: datetime, dxy: float) -> AnalysisSnapshot:
    snapshot_id = f"XAUUSD:{trade_date.isoformat()}:{run_id}"
    source_ref = {
        "source": "cnbc",
        "symbol": "DXY",
        "raw_path": f"raw/macro/cnbc/{trade_date.isoformat()}/dxy.json",
    }
    payload = {
        "snapshot_id": snapshot_id,
        "asset": "XAUUSD",
        "trade_date": trade_date.isoformat(),
        "snapshot_time": observed_at.isoformat(),
        "run_id": run_id,
        "input_snapshot_ids": {"macro": f"macro:{run_id}"},
        "source_refs": [source_ref],
        "macro": {
            "status": "available",
            "data": {"indicators": {"DXY": {"value": dxy, "date": trade_date.isoformat()}}},
        },
    }
    return AnalysisSnapshot(
        snapshot_id=snapshot_id,
        asset="XAUUSD",
        trade_date=trade_date,
        run_id=run_id,
        snapshot_time=observed_at,
        status="success",
        input_snapshot_ids=payload["input_snapshot_ids"],
        source_refs=[source_ref],
        macro=payload["macro"],
        payload=payload,
        payload_sha256="a" * 64,
        artifact_path=f"outputs/{run_id}/snapshot.json",
        created_at=observed_at,
        updated_at=observed_at,
    )


def _seed_canonical(session: Session) -> None:
    ref = {"source": "cnbc", "symbol": "DXY", "raw_path": "raw/macro/cnbc/2026-07-14/dxy.json"}
    document = AnalysisStateDocumentV11(
        state_scope="daily_close",
        state_machine_version=ANALYSIS_STATE_MACHINE_VERSION,
        session="daily_close",
        trade_date=PRIOR_AT.date(),
        asset="XAUUSD",
        as_of=PRIOR_AT,
        market_stage="weak_repair_watch",
        core_thesis="prior canonical",
        net_bias="mixed",
        dominant_drivers=[],
        key_levels=[],
        scenario_states=[],
        unresolved_items=[],
        invalidation_conditions=[],
        evidence_cursors={},
        input_snapshot_ids={"analysis_snapshot": f"XAUUSD:2026-07-14:{PRIOR_RUN}"},
        source_refs=[ref],
    )
    transition = AnalysisTransitionDocumentV11(
        state_scope="daily_close",
        summary="bootstrap",
        changes=[
            StateChange(
                target="core_thesis",
                action=TransitionAction.MAINTAIN,
                reason="bootstrap",
                evidence_refs=[ref],
            )
        ],
        evidence_refs=[ref],
    )
    authority = StateMaterializationAuthority(
        quality_gate_action="pass",
        publish_allowed=True,
        accepted_output_source="primary",
        accepted_output_agent_name="coordinator_agent",
        accepted_output_snapshot_id=f"XAUUSD:2026-07-14:{PRIOR_RUN}",
    )
    state = append_analysis_state_scoped(
        session,
        state_scope="daily_close",
        document=document,
        transition=transition,
        authority=authority,
        previous_state_id=None,
        task_run_id=PRIOR_RUN,
    )
    advance_canonical_head_scoped(
        session,
        asset="XAUUSD",
        state_scope="daily_close",
        new_state_id=state.id,
        expected_state_id=None,
        expected_version=0,
        authority=authority,
    )


def test_builds_shadow_input_from_persisted_head_and_two_snapshots() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AnalysisBase.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_canonical(session)
        prior = _snapshot(run_id=PRIOR_RUN, trade_date=PRIOR_AT.date(), observed_at=PRIOR_AT, dxy=101.1)
        current = _snapshot(run_id=CURRENT_RUN, trade_date=CURRENT_AT.date(), observed_at=CURRENT_AT, dxy=100.5)
        session.add_all((prior, current))
        session.commit()

        result = _build_persisted_state_shadow_input(db=session, analysis_snapshot=current.payload)

    assert result is not None
    assert result["canonical_state"]["core_thesis"] == "prior canonical"
    assert result["cutoff_at"] == CURRENT_AT.isoformat()
    assert result["evidence"][0]["payload"]["current_value"] == 100.5
    assert result["evidence"][0]["payload"]["previous_value"] == 101.1
    passport = result["evidence"][0]["payload"]["metadata"]["analysis_snapshot_passport"]
    assert passport["analysis_snapshot"] == current.snapshot_id
    assert passport["analysis_snapshot_db_id"] == current.id
    assert passport["macro"] == f"macro:{CURRENT_RUN}"


def test_missing_previous_snapshot_keeps_state_delta_readiness_blocked() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AnalysisBase.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_canonical(session)
        current = _snapshot(run_id=CURRENT_RUN, trade_date=CURRENT_AT.date(), observed_at=CURRENT_AT, dxy=100.5)
        session.add(current)
        session.commit()

        result = _build_persisted_state_shadow_input(db=session, analysis_snapshot=current.payload)

    assert result is None
