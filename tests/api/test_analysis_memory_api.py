"""Focused API contracts for analysis-memory observability and review."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ["FINANCE_AGENT_DISABLE_BACKGROUND_JOBS"] = "1"

from apps.analysis.context_bundle import assemble_context_bundle
from apps.analysis.context_bundle.schemas import compute_bundle_content_hash
from apps.analysis.state import (
    ANALYSIS_STATE_MACHINE_VERSION,
    AnalysisStateDocument,
    AnalysisStateDocumentV11,
    AnalysisTransitionDocument,
    AnalysisTransitionDocumentV11,
    StateChange,
    StateScope,
    StateMaterializationAuthority,
    TransitionAction,
    advance_canonical_head,
    advance_canonical_head_scoped,
    append_analysis_state,
    append_analysis_state_scoped,
)
from apps.api import main as api_main
from apps.api.services import analysis_memory_service
from apps.output.context_bundle import write_context_bundle
from database.models.analysis import AgentOutput, AnalysisBase, AnalysisSnapshot, FinalAnalysisResult
from database.models.analysis_state import AnalysisState, AnalysisStateHead, AnalysisTransition
from database.models.engine import get_db


NOW = datetime(2026, 7, 22, 8, tzinfo=UTC)


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnalysisBase.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session


def _document(*, thesis: str, as_of: datetime, snapshot_id: str = "snapshot-71") -> AnalysisStateDocument:
    return AnalysisStateDocument(
        asset="XAUUSD",
        as_of=as_of,
        market_stage="direction_decision",
        core_thesis=thesis,
        net_bias="mixed_bullish",
        dominant_drivers=[{"name": "real_yield"}],
        key_levels=[{"price": 4126.63}],
        scenario_states=[{"name": "base", "status": "active"}],
        unresolved_items=[{"item": "breakout"}],
        invalidation_conditions=[{"condition": "close_below_4000"}],
        evidence_cursors={"market": {"evidence_id": snapshot_id}},
        input_snapshot_ids={"market": snapshot_id},
        source_refs=[{"source": "market", "snapshot_id": snapshot_id}],
    )


def _transition(*, action: TransitionAction = TransitionAction.MAINTAIN) -> AnalysisTransitionDocument:
    return AnalysisTransitionDocument(
        summary="reviewable state transition",
        changes=[
            StateChange(
                target="core_thesis",
                action=action,
                reason="new persisted evidence",
                evidence_refs=[{"source": "market", "snapshot_id": "snapshot-71"}],
            )
        ],
        evidence_refs=[{"source": "market", "snapshot_id": "snapshot-71"}],
    )


def _scoped_document(
    *,
    state_scope: StateScope,
    thesis: str,
    as_of: datetime,
    snapshot_id: str,
) -> AnalysisStateDocumentV11:
    return AnalysisStateDocumentV11(
        state_scope=state_scope,
        state_machine_version=ANALYSIS_STATE_MACHINE_VERSION,
        session=state_scope,
        trade_date=as_of.date(),
        asset="XAUUSD",
        as_of=as_of,
        market_stage="direction_decision",
        core_thesis=thesis,
        net_bias="mixed_bullish",
        dominant_drivers=[
            {
                "driver_id": "real_yield",
                "label": "real yield",
                "direction": "mixed",
            }
        ],
        key_levels=[{"value": 4126.63, "role": "resistance", "source": "market"}],
        scenario_states=[
            {"scenario_id": "base", "condition": "range holds", "status": "active"}
        ],
        evidence_cursors={"market": {"evidence_id": snapshot_id}},
        input_snapshot_ids={"market": snapshot_id},
        source_refs=[{"source": "market", "snapshot_id": snapshot_id}],
    )


def _scoped_transition(
    *,
    state_scope: StateScope,
    action: TransitionAction = TransitionAction.MAINTAIN,
) -> AnalysisTransitionDocumentV11:
    return AnalysisTransitionDocumentV11(
        state_scope=state_scope,
        summary="reviewable scoped state transition",
        changes=[
            StateChange(
                target="core_thesis",
                action=action,
                reason="new persisted evidence",
                evidence_refs=[{"source": "market", "snapshot_id": f"{state_scope}-snapshot"}],
            )
        ],
        evidence_refs=[{"source": "market", "snapshot_id": f"{state_scope}-snapshot"}],
    )


def _accepted_authority() -> StateMaterializationAuthority:
    return StateMaterializationAuthority(
        quality_gate_action="pass",
        publish_allowed=True,
        accepted_output_source="primary",
        accepted_output_agent_name="coordinator_agent",
        accepted_output_snapshot_id="snapshot-root",
    )


def _seed_root(db: Session) -> AnalysisState:
    root = append_analysis_state(
        db,
        document=_document(thesis="accepted root", as_of=NOW, snapshot_id="snapshot-root"),
        transition=_transition(),
        authority=_accepted_authority(),
        previous_state_id=None,
        task_run_id="run-root",
    )
    advance_canonical_head(
        db,
        asset="XAUUSD",
        new_state_id=root.id,
        expected_state_id=None,
        expected_version=0,
        authority=_accepted_authority(),
    )
    db.flush()
    return root


def _seed_scoped_root(db: Session, *, state_scope: StateScope) -> AnalysisState:
    snapshot_id = f"{state_scope}-snapshot"
    root = append_analysis_state_scoped(
        db,
        state_scope=state_scope,
        document=_scoped_document(
            state_scope=state_scope,
            thesis=f"{state_scope} accepted root",
            as_of=NOW,
            snapshot_id=snapshot_id,
        ),
        transition=_scoped_transition(state_scope=state_scope),
        authority=_accepted_authority(),
        previous_state_id=None,
        task_run_id=f"run-{state_scope}",
    )
    advance_canonical_head_scoped(
        db,
        asset="XAUUSD",
        state_scope=state_scope,
        new_state_id=root.id,
        expected_state_id=None,
        expected_version=0,
        authority=_accepted_authority(),
    )
    db.flush()
    return root


def _seed_scoped_candidate(
    db: Session,
    *,
    root: AnalysisState,
    state_scope: StateScope,
) -> AnalysisState:
    candidate = append_analysis_state_scoped(
        db,
        state_scope=state_scope,
        document=_scoped_document(
            state_scope=state_scope,
            thesis=f"{state_scope} candidate",
            as_of=NOW + timedelta(hours=1),
            snapshot_id=f"{state_scope}-candidate",
        ),
        transition=_scoped_transition(
            state_scope=state_scope,
            action=TransitionAction.STRENGTHEN,
        ),
        authority=StateMaterializationAuthority(
            quality_gate_action="manual_review",
            publish_allowed=False,
        ),
        previous_state_id=root.id,
        task_run_id=f"run-{state_scope}-candidate",
    )
    db.flush()
    return candidate


def _seed_candidate_lineage(db: Session, *, run_id: str = "run-71") -> tuple[str, str]:
    snapshot = AnalysisSnapshot(
        snapshot_id="snapshot-71",
        asset="XAUUSD",
        trade_date=date(2026, 7, 22),
        run_id=run_id,
        snapshot_time=NOW,
        status="success",
        input_snapshot_ids={"market": "snapshot-71"},
        source_refs=[{"source": "market", "snapshot_id": "snapshot-71"}],
        payload={"asset": "XAUUSD"},
        payload_sha256="a" * 64,
        artifact_path="analysis/snapshots/snapshot-71.json",
    )
    db.add(snapshot)
    db.flush()
    final = FinalAnalysisResult(
        asset="XAUUSD",
        trade_date=date(2026, 7, 22),
        run_id=run_id,
        snapshot_id=snapshot.snapshot_id,
        analysis_snapshot_db_id=snapshot.id,
        final_bias="mixed_bullish",
        confidence=0.7,
        market_state="direction_decision",
        scenario_summary="candidate",
        is_trade_instruction=False,
        input_snapshot_ids={"market": snapshot.snapshot_id},
        source_refs=list(snapshot.source_refs),
        source_agent_outputs=[],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        payload={"review_status": "manual_review"},
        payload_sha256="b" * 64,
    )
    coordinator = AgentOutput(
        snapshot_id=snapshot.snapshot_id,
        analysis_snapshot_db_id=snapshot.id,
        asset="XAUUSD",
        trade_date=date(2026, 7, 22),
        run_id=run_id,
        agent_name="coordinator_agent",
        module="coordinator",
        version="1.0",
        status="success",
        bias="mixed_bullish",
        confidence=0.7,
        input_snapshot_ids={"market": snapshot.snapshot_id},
        source_refs=list(snapshot.source_refs),
        key_findings=[],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary="candidate coordinator output",
        payload={"review_status": "manual_review"},
        payload_sha256="c" * 64,
    )
    db.add_all((final, coordinator))
    db.flush()
    return snapshot.id, final.id


def _seed_candidate(db: Session, *, root: AnalysisState, with_lineage: bool = True) -> AnalysisState:
    snapshot_db_id = final_id = None
    if with_lineage:
        snapshot_db_id, final_id = _seed_candidate_lineage(db)
    candidate = append_analysis_state(
        db,
        document=_document(thesis="candidate thesis", as_of=NOW + timedelta(hours=1)),
        transition=_transition(action=TransitionAction.STRENGTHEN),
        authority=StateMaterializationAuthority(
            quality_gate_action="manual_review",
            publish_allowed=False,
        ),
        previous_state_id=root.id,
        task_run_id="run-71",
        analysis_snapshot_db_id=snapshot_db_id,
        final_analysis_result_id=final_id,
    )
    db.flush()
    return candidate


def _seed_blocked(db: Session, *, root: AnalysisState) -> AnalysisState:
    blocked = append_analysis_state(
        db,
        document=_document(thesis="blocked thesis", as_of=NOW + timedelta(hours=2)),
        transition=_transition(action=TransitionAction.INVALIDATE),
        authority=StateMaterializationAuthority(
            quality_gate_action="block_publish",
            publish_allowed=False,
        ),
        previous_state_id=root.id,
        task_run_id="run-blocked",
    )
    db.flush()
    return blocked


def _client(db: Session) -> TestClient:
    api_main.app.dependency_overrides[get_db] = lambda: db
    return TestClient(api_main.app)


def test_get_routes_are_read_only_and_isolate_canonical_from_candidates(db: Session) -> None:
    root = _seed_root(db)
    candidate = _seed_candidate(db, root=root)
    blocked = _seed_blocked(db, root=root)
    before = (
        db.scalar(select(func.count()).select_from(AnalysisState)),
        db.scalar(select(func.count()).select_from(AnalysisTransition)),
        db.scalar(select(func.count()).select_from(AnalysisStateHead)),
    )
    client = _client(db)
    try:
        canonical = client.get(
            "/api/analysis-memory/assets/XAUUSD/canonical",
            params={"stateScope": "daily_close"},
        )
        candidates = client.get(
            "/api/analysis-memory/assets/XAUUSD/candidates",
            params={"stateScope": "daily_close", "page": 1, "pageSize": 10},
        )
        state = client.get(
            f"/api/analysis-memory/states/{candidate.id}",
            params={"stateScope": "daily_close"},
        )
        transition_id = state.json()["transition"]["transition_id"]
        transition = client.get(
            f"/api/analysis-memory/transitions/{transition_id}",
            params={"stateScope": "daily_close"},
        )
    finally:
        api_main.app.dependency_overrides.pop(get_db, None)

    assert canonical.status_code == 200
    assert canonical.json()["schema_version"] == "analysis_memory_read.v2"
    assert canonical.json()["state_scope"] == "daily_close"
    assert canonical.json()["state"]["state_kind"] == "accepted_canonical"
    assert canonical.json()["state"]["state_id"] == root.id
    canonical_ids = {item["state_id"] for item in canonical.json()["canonical_chain"]}
    assert candidate.id not in canonical_ids
    assert blocked.id not in canonical_ids
    assert candidates.status_code == 200
    assert {item["state_kind"] for item in candidates.json()["data"]} == {"candidate", "blocked"}
    assert candidates.json()["pagination"] == {
        "page": 1,
        "page_size": 10,
        "total_items": 2,
        "total_pages": 1,
    }
    assert transition.status_code == 200
    assert transition.json()["state_scope"] == "daily_close"
    assert transition.json()["to_state_id"] == candidate.id
    after = (
        db.scalar(select(func.count()).select_from(AnalysisState)),
        db.scalar(select(func.count()).select_from(AnalysisTransition)),
        db.scalar(select(func.count()).select_from(AnalysisStateHead)),
    )
    assert after == before


def test_candidate_review_appends_accepted_state_transition_and_real_artifact(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _seed_root(db)
    candidate = _seed_candidate(db, root=root)
    candidate_before = {
        column.name: getattr(candidate, column.name)
        for column in candidate.__table__.columns
        if column.name != "as_of"
    }
    materializer_calls: list[dict] = []
    original_materializer = analysis_memory_service.materialize_reviewed_transition

    def record_materializer(*args, **kwargs):
        materializer_calls.append(kwargs)
        return original_materializer(*args, **kwargs)

    monkeypatch.setattr(analysis_memory_service, "materialize_reviewed_transition", record_materializer)
    monkeypatch.setattr("apps.api.services.analysis_memory_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("FINANCE_AGENT_ANALYSIS_MEMORY_WRITE_TOKEN", "review-secret")
    client = _client(db)
    try:
        missing = client.post(
            f"/api/analysis-memory/candidates/{candidate.id}/reviews",
            json={
                "action": "accept",
                "actor": "reviewer@example.com",
                "reason": "lineage and transition diff verified",
                "request_id": "review-71-001",
                "expected_canonical_state_id": root.id,
                "expected_head_version": 1,
                "state_scope": "daily_close",
            },
        )
        wrong = client.post(
            f"/api/analysis-memory/candidates/{candidate.id}/reviews",
            headers={"X-Finance-Analysis-Memory-Token": "wrong"},
            json={
                "action": "accept",
                "actor": "reviewer@example.com",
                "reason": "lineage and transition diff verified",
                "request_id": "review-71-001",
                "expected_canonical_state_id": root.id,
                "expected_head_version": 1,
                "state_scope": "daily_close",
            },
        )
        response = client.post(
            f"/api/analysis-memory/candidates/{candidate.id}/reviews",
            headers={"X-Finance-Analysis-Memory-Token": "review-secret"},
            json={
                "action": "accept",
                "actor": "reviewer@example.com",
                "reason": "lineage and transition diff verified",
                "request_id": "review-71-001",
                "expected_canonical_state_id": root.id,
                "expected_head_version": 1,
                "state_scope": "daily_close",
            },
        )
    finally:
        api_main.app.dependency_overrides.pop(get_db, None)

    assert missing.status_code == 403
    assert missing.json()["detail"]["code"] == "ANALYSIS_MEMORY_WRITE_FORBIDDEN"
    assert wrong.status_code == 403
    assert wrong.json()["detail"]["code"] == "ANALYSIS_MEMORY_WRITE_FORBIDDEN"
    assert response.status_code == 200, response.text
    assert len(materializer_calls) == 1
    assert materializer_calls[0]["quality_gate"].action.value == "pass"
    assert materializer_calls[0]["agent_loop"].accepted_output.snapshot_id == "snapshot-71"
    payload = response.json()
    accepted_id = payload["canonical_state"]["state_id"]
    assert accepted_id != candidate.id
    assert payload["canonical_state"]["state_kind"] == "accepted_canonical"
    assert payload["canonical_state"]["accepted_output_agent_name"] == "coordinator_agent"
    assert payload["canonical_state"]["lineage"]["accepted_output_snapshot_id"] == "snapshot-71"
    artifact = payload["review_artifact"]
    artifact_path = tmp_path / "storage" / artifact["artifact_path"]
    assert artifact_path.is_file()
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact_payload["schema_version"] == "analysis_state_review.v2"
    assert artifact_payload["state_scope"] == "daily_close"
    assert "/daily_close/" in artifact["artifact_path"]
    assert artifact_payload["quality_gate"]["action"] == "pass"
    assert artifact_payload["agent_loop"]["accepted_output"]["snapshot_id"] == "snapshot-71"
    assert artifact["artifact_id"] != artifact["transition_id"]
    db.expire(candidate)
    assert {
        column.name: getattr(candidate, column.name)
        for column in candidate.__table__.columns
        if column.name != "as_of"
    } == candidate_before
    accepted = db.get(AnalysisState, accepted_id)
    assert accepted is not None and accepted.publish_allowed is True
    assert accepted.previous_state_id == root.id
    accepted_transition = db.get(AnalysisTransition, artifact["transition_id"])
    assert accepted_transition is not None
    assert accepted_transition.to_state_id == accepted.id
    assert accepted_transition.evidence_refs[-1]["review_artifact_id"] == artifact["artifact_id"]


def test_candidate_review_rejects_missing_persisted_authority_and_stale_head(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _seed_root(db)
    candidate = _seed_candidate(db, root=root, with_lineage=False)
    monkeypatch.setattr("apps.api.services.analysis_memory_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("FINANCE_AGENT_ANALYSIS_MEMORY_WRITE_TOKEN", "review-secret")
    client = _client(db)
    body = {
        "action": "accept",
        "actor": "reviewer",
        "reason": "checked",
        "request_id": "review-invalid",
        "expected_canonical_state_id": root.id,
        "expected_head_version": 1,
        "state_scope": "daily_close",
    }
    try:
        missing_lineage = client.post(
            f"/api/analysis-memory/candidates/{candidate.id}/reviews",
            headers={"X-Finance-Analysis-Memory-Token": "review-secret"},
            json=body,
        )
        stale = client.post(
            f"/api/analysis-memory/candidates/{candidate.id}/reviews",
            headers={"X-Finance-Analysis-Memory-Token": "review-secret"},
            json={**body, "expected_head_version": 2},
        )
    finally:
        api_main.app.dependency_overrides.pop(get_db, None)

    assert missing_lineage.status_code == 422
    assert missing_lineage.json()["detail"]["code"] == "ANALYSIS_MEMORY_REVIEW_INVALID"
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "ANALYSIS_MEMORY_CONFLICT"


def test_context_bundle_metadata_is_validated_paginated_and_payload_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = assemble_context_bundle(
        run_id="run-71",
        asset="XAUUSD",
        state_scope="daily_close",
        canonical_state_id="state-root",
        canonical_state={
            "asset": "XAUUSD",
            "state_scope": "daily_close",
            "core_thesis": "accepted root",
        },
        evidence=[
            {
                "source": "market",
                "evidence_id": "market-71",
                "business_time": NOW,
                "ingested_at": NOW,
                "payload": {"price": 4100},
                "source_ref": {"source": "market", "snapshot_id": "market-71"},
            }
        ],
        evidence_cursors={},
        cutoff_at=NOW + timedelta(minutes=1),
        assembled_at=NOW + timedelta(minutes=2),
    )
    write_context_bundle(storage_root=tmp_path / "storage", bundle=bundle)
    monkeypatch.setattr("apps.api.services.analysis_memory_service._PROJECT_ROOT", tmp_path)
    client = TestClient(api_main.app)
    page = client.get(
        "/api/analysis-memory/assets/XAUUSD/context-bundles",
        params={"stateScope": "daily_close", "page": 1, "pageSize": 10},
    )
    detail = client.get(
        f"/api/analysis-memory/context-bundles/{bundle.bundle_id}",
        params={"stateScope": "daily_close"},
    )
    wrong_scope = client.get(
        f"/api/analysis-memory/context-bundles/{bundle.bundle_id}",
        params={"stateScope": "intraday"},
    )

    assert page.status_code == 200
    assert page.json()["pagination"]["total_items"] == 1
    metadata = detail.json()
    assert detail.status_code == 200
    assert metadata["estimated_tokens"] == bundle.budget_trace.estimated_tokens
    assert metadata["state_scope"] == "daily_close"
    assert metadata["blocks"][1]["name"] == "delta_evidence"
    assert "payload" not in metadata["blocks"][1]
    assert metadata["source_refs"] == bundle.source_refs
    assert metadata["artifact_path"].startswith("outputs/context_bundles/")
    assert wrong_scope.status_code == 404
    invalid = client.get(
        "/api/analysis-memory/context-bundles/not-a-uuid",
        params={"stateScope": "daily_close"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "ANALYSIS_MEMORY_INVALID"


def test_api_requires_valid_scope_and_isolates_all_three_heads(db: Session) -> None:
    daily_root = _seed_root(db)
    intraday_root = _seed_scoped_root(db, state_scope="intraday")
    weekly_root = _seed_scoped_root(db, state_scope="weekly_fundamental")
    candidates = {
        "daily_close": _seed_candidate(db, root=daily_root),
        "intraday": _seed_scoped_candidate(
            db,
            root=intraday_root,
            state_scope="intraday",
        ),
        "weekly_fundamental": _seed_scoped_candidate(
            db,
            root=weekly_root,
            state_scope="weekly_fundamental",
        ),
    }
    roots = {
        "daily_close": daily_root,
        "intraday": intraday_root,
        "weekly_fundamental": weekly_root,
    }
    client = _client(db)
    try:
        missing = client.get("/api/analysis-memory/assets/XAUUSD/canonical")
        invalid = client.get(
            "/api/analysis-memory/assets/XAUUSD/canonical",
            params={"stateScope": "monthly"},
        )
        responses = {}
        for state_scope in roots:
            canonical = client.get(
                "/api/analysis-memory/assets/XAUUSD/canonical",
                params={"stateScope": state_scope},
            )
            candidate_page = client.get(
                "/api/analysis-memory/assets/XAUUSD/candidates",
                params={"stateScope": state_scope, "page": 1, "pageSize": 20},
            )
            responses[state_scope] = (canonical, candidate_page)
        cross_scope_detail = client.get(
            f"/api/analysis-memory/states/{candidates['intraday'].id}",
            params={"stateScope": "daily_close"},
        )
    finally:
        api_main.app.dependency_overrides.pop(get_db, None)

    assert missing.status_code == 200
    assert missing.json()["state_scope"] == "daily_close"
    assert missing.json()["state"]["state_id"] == daily_root.id
    assert invalid.status_code == 422
    assert cross_scope_detail.status_code == 404
    for state_scope, (canonical, candidate_page) in responses.items():
        assert canonical.status_code == 200
        assert canonical.json()["state_scope"] == state_scope
        assert canonical.json()["state"]["state_id"] == roots[state_scope].id
        assert {item["state_scope"] for item in canonical.json()["canonical_chain"]} == {
            state_scope
        }
        assert candidate_page.status_code == 200
        assert candidate_page.json()["state_scope"] == state_scope
        assert [item["state_id"] for item in candidate_page.json()["data"]] == [
            candidates[state_scope].id
        ]


def test_cross_scope_candidate_review_fails_before_write(
    db: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _seed_root(db)
    candidate = _seed_candidate(db, root=root)
    before = (
        db.scalar(select(func.count()).select_from(AnalysisState)),
        db.scalar(select(func.count()).select_from(AnalysisTransition)),
        db.scalar(select(func.count()).select_from(AnalysisStateHead)),
    )
    monkeypatch.setattr("apps.api.services.analysis_memory_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("FINANCE_AGENT_ANALYSIS_MEMORY_WRITE_TOKEN", "review-secret")
    client = _client(db)
    try:
        response = client.post(
            f"/api/analysis-memory/candidates/{candidate.id}/reviews",
            headers={"X-Finance-Analysis-Memory-Token": "review-secret"},
            json={
                "action": "accept",
                "state_scope": "intraday",
                "actor": "reviewer",
                "reason": "cross-scope request must fail",
                "request_id": "review-cross-scope",
                "expected_canonical_state_id": root.id,
                "expected_head_version": 1,
            },
        )
    finally:
        api_main.app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ANALYSIS_MEMORY_REVIEW_INVALID"
    after = (
        db.scalar(select(func.count()).select_from(AnalysisState)),
        db.scalar(select(func.count()).select_from(AnalysisTransition)),
        db.scalar(select(func.count()).select_from(AnalysisStateHead)),
    )
    assert after == before
    assert not (tmp_path / "storage" / "outputs" / "analysis_state_reviews").exists()


def test_legacy_bundle_is_only_observable_as_daily_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = assemble_context_bundle(
        run_id="run-legacy-bundle",
        asset="XAUUSD",
        state_scope="daily_close",
        canonical_state_id="state-legacy",
        canonical_state={
            "asset": "XAUUSD",
            "state_scope": "daily_close",
            "core_thesis": "legacy daily close",
        },
        evidence=[],
        evidence_cursors={},
        cutoff_at=NOW,
        assembled_at=NOW,
    )
    payload = bundle.model_dump(mode="json")
    payload["schema_version"] = "analysis_context_bundle.v1"
    payload.pop("state_scope")
    payload["content_hash"] = compute_bundle_content_hash(payload)
    payload["bundle_id"] = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"finance-agent:context-bundle:{payload['content_hash']}",
        )
    )
    path = (
        tmp_path
        / "storage"
        / "outputs"
        / "context_bundles"
        / "XAUUSD"
        / "run-legacy-bundle"
        / f"{payload['bundle_id']}.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("apps.api.services.analysis_memory_service._PROJECT_ROOT", tmp_path)
    client = TestClient(api_main.app)

    daily = client.get(
        f"/api/analysis-memory/context-bundles/{payload['bundle_id']}",
        params={"stateScope": "daily_close"},
    )
    intraday = client.get(
        f"/api/analysis-memory/context-bundles/{payload['bundle_id']}",
        params={"stateScope": "intraday"},
    )

    assert daily.status_code == 200
    assert daily.json()["schema_version"] == "analysis_context_bundle.v1"
    assert daily.json()["state_scope"] == "daily_close"
    assert intraday.status_code == 404
