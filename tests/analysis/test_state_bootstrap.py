from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.analysis.state import AnalysisStateDocument
from apps.analysis.state.bootstrap import (
    BootstrapApproval,
    BootstrapContractError,
    CanonicalRecoveryArtifact,
    LegacyRetirementThresholds,
    build_bootstrap_candidate,
    build_recovery_artifact,
    build_recovery_artifact_scoped,
    evaluate_legacy_retirement,
    materialize_bootstrap_candidate,
    recover_canonical_cache_payload,
    require_legacy_retirement_allowed,
    validate_artifact_path,
    write_json_artifact,
)
from apps.analysis.state.hashing import content_hash
from database.models.analysis import AnalysisBase
from database.models.analysis_state import AnalysisState, AnalysisStateHead, AnalysisTransition


NOW = "2026-07-22T08:00:00Z"
REF = {"source": "market_snapshot", "snapshot_id": "snap-accepted"}


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AnalysisBase.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _gate(action: str = "pass") -> dict:
    return {
        "action": action,
        "review_status": "pass" if action == "pass" else "needs_review",
        "publish_allowed": action == "pass",
    }


def _loop() -> dict:
    return {
        "decision": "passed",
        "review_status": "pass",
        "publish_allowed": True,
        "accepted_output": {
            "source": "primary",
            "agent_name": "coordinator_agent",
            "snapshot_id": "snap-accepted",
        },
    }


def _card() -> dict:
    return {
        "version": "1.0",
        "asset": "XAUUSD",
        "trade_date": "2026-07-22",
        "run_id": "run-bootstrap",
        "bias": "mixed_bullish",
        "confidence": 0.72,
        "scenario_summary": "等待突破确认",
        "key_levels_from_options": ["4126 gamma zero"],
        "risk_points": ["流动性仍需观察"],
        "invalid_conditions": ["跌破 4000"],
        "watchlist": ["实际利率"],
        "trigger_conditions": ["站稳 4126"],
        "confirmation_conditions": ["美元转弱"],
        "source_refs": [REF],
        "input_snapshot_ids": {
            "analysis_snapshot": "snap-accepted",
            "coordinator": "snap-accepted",
        },
        "created_at": NOW,
        "is_trade_instruction": False,
    }


def _overview() -> dict:
    return {
        "status": "ready",
        "asset": "XAUUSD",
        "run_id": "run-bootstrap",
        "as_of": NOW,
        "phase": "transition_release",
        "net_bias": "mixed_bullish",
        "one_line_conclusion": "实际利率缓和，但突破仍待确认",
        "theme_rankings": [
            {
                "mainline_id": "real-yield",
                "rank": 1,
                "direction": "tailwind",
                "coverage_status": "covered",
                "full_report_body": "must-not-enter-state",
            }
        ],
        "warnings": [],
        "architecture_gaps": [],
        "input_snapshot_ids": {
            "analysis_snapshot": "snap-accepted",
            "coordinator": "snap-accepted",
        },
        "source_refs": [REF],
    }


def _final(*, action: str = "pass") -> dict:
    card = _card()
    return {
        "asset": "XAUUSD",
        "trade_date": "2026-07-22",
        "run_id": "run-bootstrap",
        "snapshot_id": "snap-accepted",
        "final_bias": "mixed_bullish",
        "market_state": "premarket",
        "scenario_summary": "等待突破确认",
        "input_snapshot_ids": card["input_snapshot_ids"],
        "source_refs": [REF],
        "invalid_conditions": card["invalid_conditions"],
        "strategy_card": card,
        "run_summaries": {
            "gold_runtime_summary": {
                "quality_gate_decision": _gate(action),
                "agent_loop_decision": _loop(),
            }
        },
        "payload_sha256": content_hash(card),
        "strategy_card_sha256": content_hash(card),
        "payload": {"historical_report_body": "must-not-enter-state" * 100},
    }


def _candidate(*, action: str = "pass", state_scope: str = "daily_close"):
    return build_bootstrap_candidate(
        final_result=_final(action=action),
        gold_macro_overview=_overview(),
        strategy_card=_card(),
        state_scope=state_scope,
    )


def test_bootstrap_is_deterministic_compact_and_binds_accepted_output() -> None:
    first = _candidate()
    replay = _candidate()

    assert first == replay
    assert first.document.core_thesis == "实际利率缓和，但突破仍待确认"
    assert first.document.schema_version == "1.1"
    assert first.document.state_scope == "daily_close"
    assert first.document.state_machine_version == "analysis_state.v1.1"
    assert first.document.dominant_drivers[0].driver_id == "real-yield"
    assert first.document.key_levels[0].role == "reference"
    assert first.document.scenario_states[0].scenario_id == "trigger-1"
    assert first.document.input_snapshot_ids["analysis_snapshot"] == "snap-accepted"
    assert first.agent_loop.accepted_output.snapshot_id == "snap-accepted"
    assert "must-not-enter-state" not in json.dumps(
        first.document.model_dump(mode="json"), ensure_ascii=False
    )


def test_bootstrap_rejects_unaccepted_or_cross_asset_artifacts() -> None:
    blocked = _final(action="block_publish")
    blocked["run_summaries"]["gold_runtime_summary"]["agent_loop_decision"] = {
        "decision": "blocked",
        "review_status": "blocked",
        "publish_allowed": False,
    }
    with pytest.raises(BootstrapContractError, match="neither PASS nor manual_review"):
        build_bootstrap_candidate(
            final_result=blocked,
            gold_macro_overview=_overview(),
            strategy_card=_card(),
            state_scope="daily_close",
        )

    overview = _overview()
    overview["asset"] = "GC"
    with pytest.raises(BootstrapContractError, match="asset"):
        build_bootstrap_candidate(
            final_result=_final(), gold_macro_overview=overview, strategy_card=_card(),
            state_scope="daily_close",
        )


def test_bootstrap_rejects_snapshot_card_and_overview_lineage_mismatch() -> None:
    final = _final()
    final["snapshot_id"] = "different-snapshot"
    with pytest.raises(BootstrapContractError, match="snapshot_id conflicts"):
        build_bootstrap_candidate(
            final_result=final, gold_macro_overview=_overview(), strategy_card=_card(),
            state_scope="daily_close",
        )

    card = _card()
    card["scenario_summary"] = "tampered card"
    with pytest.raises(BootstrapContractError, match="StrategyCard content"):
        build_bootstrap_candidate(
            final_result=_final(), gold_macro_overview=_overview(), strategy_card=card,
            state_scope="daily_close",
        )

    overview = _overview()
    overview["input_snapshot_ids"]["unaccepted"] = "foreign-snapshot"
    with pytest.raises(BootstrapContractError, match="exceeds accepted lineage"):
        build_bootstrap_candidate(
            final_result=_final(), gold_macro_overview=overview, strategy_card=_card(),
            state_scope="daily_close",
        )

    overview = _overview()
    overview["source_refs"] = [{"source": "unaccepted", "snapshot_id": "foreign"}]
    with pytest.raises(BootstrapContractError, match="source_refs exceed"):
        build_bootstrap_candidate(
            final_result=_final(), gold_macro_overview=overview, strategy_card=_card(),
            state_scope="daily_close",
        )


def test_candidate_hash_rejects_nested_mutation() -> None:
    candidate = _candidate().model_dump(mode="json")
    candidate["document"]["core_thesis"] = "tampered"
    with pytest.raises(ValidationError, match="content changed"):
        type(_candidate()).model_validate(candidate)


def test_pass_bootstrap_establishes_one_head_and_replays_idempotently(session: Session) -> None:
    candidate = _candidate()
    first = materialize_bootstrap_candidate(session, candidate=candidate)
    replay = materialize_bootstrap_candidate(session, candidate=candidate)

    assert first.authorization == "quality_gate"
    assert first.replayed is False
    assert replay.replayed is True
    assert replay.state_id == first.state_id
    assert session.scalar(select(func.count()).select_from(AnalysisState)) == 1
    assert session.scalar(select(func.count()).select_from(AnalysisTransition)) == 1
    assert session.scalar(select(func.count()).select_from(AnalysisStateHead)) == 1


def test_bootstrap_scopes_create_independent_heads_and_recovery(session: Session) -> None:
    daily = materialize_bootstrap_candidate(session, candidate=_candidate())
    intraday = materialize_bootstrap_candidate(
        session, candidate=_candidate(state_scope="intraday")
    )

    assert daily.state_id != intraday.state_id
    heads = {
        row.state_scope: (row.canonical_state_id, row.version)
        for row in session.scalars(select(AnalysisStateHead).where(AnalysisStateHead.asset == "XAUUSD"))
    }
    assert heads == {
        "daily_close": (daily.state_id, 1),
        "intraday": (intraday.state_id, 1),
    }
    artifact = build_recovery_artifact_scoped(
        session, asset="XAUUSD", state_scope="intraday"
    )
    assert artifact.canonical_state_id == intraday.state_id
    assert artifact.document.state_scope == "intraday"


def test_manual_review_requires_bound_approval_and_persists_audit_evidence(session: Session) -> None:
    candidate = _candidate(action="manual_review")
    with pytest.raises(PermissionError, match="explicit human approval"):
        materialize_bootstrap_candidate(session, candidate=candidate)

    approval = BootstrapApproval(
        candidate_hash=candidate.candidate_hash,
        reviewer="analyst@example.test",
        reviewed_at=datetime(2026, 7, 22, 9, tzinfo=UTC),
        note="Reviewed against accepted artifacts",
    )
    result = materialize_bootstrap_candidate(session, candidate=candidate, approval=approval)
    transition = session.scalar(select(AnalysisTransition))

    assert result.authorization == "manual_review"
    assert transition is not None
    assert transition.evidence_refs[-1]["source"] == "human_bootstrap_review"
    assert transition.evidence_refs[-1]["candidate_hash"] == candidate.candidate_hash
    assert session.get(AnalysisState, result.state_id).quality_gate_action == "pass"


def test_manual_approval_for_another_candidate_is_rejected(session: Session) -> None:
    candidate = _candidate(action="manual_review")
    with pytest.raises(BootstrapContractError, match="different candidate"):
        materialize_bootstrap_candidate(
            session,
            candidate=candidate,
            approval={
                "candidate_hash": "0" * 64,
                "reviewer": "reviewer",
                "reviewed_at": NOW,
            },
        )


def test_pass_bootstrap_rejects_manual_approval(session: Session) -> None:
    candidate = _candidate()
    with pytest.raises(PermissionError, match="without manual approval"):
        materialize_bootstrap_candidate(
            session,
            candidate=candidate,
            approval={
                "candidate_hash": candidate.candidate_hash,
                "reviewer": "reviewer",
                "reviewed_at": NOW,
            },
        )


def test_existing_different_head_blocks_bootstrap(session: Session) -> None:
    first = _candidate()
    materialize_bootstrap_candidate(session, candidate=first)
    payload = _final()
    payload["run_id"] = "another-run"
    payload["strategy_card"] = {**_card(), "run_id": "another-run"}
    payload["strategy_card_sha256"] = content_hash(payload["strategy_card"])
    other = build_bootstrap_candidate(
        final_result=payload,
        gold_macro_overview={
            **_overview(),
            "run_id": "another-run",
            "one_line_conclusion": "另一个结论",
        },
        strategy_card=payload["strategy_card"],
        state_scope="daily_close",
    )
    with pytest.raises(Exception, match="canonical head already exists"):
        materialize_bootstrap_candidate(session, candidate=other)


def test_postgresql_first_recovery_and_sealed_artifact_fallback(
    session: Session, tmp_path: Path
) -> None:
    materialize_bootstrap_candidate(session, candidate=_candidate())
    artifact = build_recovery_artifact(session, asset="XAUUSD")
    path = tmp_path / "storage" / "canonical.json"
    write_json_artifact(payload=artifact, path=path, allowed_root=tmp_path / "storage")

    db_recovery = recover_canonical_cache_payload(asset="XAUUSD", session=session)
    file_recovery = recover_canonical_cache_payload(
        asset="XAUUSD",
        artifact_path=path,
        allowed_root=tmp_path / "storage",
    )
    redis_like_cache: dict[str, dict] = {}
    redis_like_cache.clear()
    redis_like_cache["analysis:XAUUSD"] = file_recovery.cache_payload

    assert db_recovery.source == "postgresql"
    assert file_recovery.source == "artifact"
    assert db_recovery.artifact == file_recovery.artifact
    assert redis_like_cache["analysis:XAUUSD"]["canonical_state_id"] == artifact.canonical_state_id


def test_recovery_rejects_tamper_and_path_escape(tmp_path: Path) -> None:
    with pytest.raises(BootstrapContractError, match="inside allowed root"):
        validate_artifact_path(
            tmp_path / "outside.json",
            allowed_root=tmp_path / "storage",
            must_exist=False,
        )
    payload = {
        "schema_version": "analysis_state_recovery.v1",
        "asset": "XAUUSD",
        "canonical_state_id": "state",
        "canonical_version": 1,
        "state_content_hash": "0" * 64,
        "document": _candidate().document.model_dump(mode="json"),
        "artifact_hash": "0" * 64,
    }
    with pytest.raises(ValidationError, match="content hash mismatch"):
        CanonicalRecoveryArtifact.model_validate(payload)


def test_legacy_v1_recovery_artifact_round_trips_without_added_scope_fields() -> None:
    document = AnalysisStateDocument(
        asset="XAUUSD",
        as_of=NOW,
        market_stage="premarket",
        core_thesis="legacy",
        net_bias="neutral",
    )
    base = {
        "schema_version": "analysis_state_recovery.v1",
        "asset": "XAUUSD",
        "canonical_state_id": "legacy-state",
        "canonical_version": 1,
        "state_content_hash": content_hash(document),
        "document": document.model_dump(mode="json"),
    }
    payload = {**base, "artifact_hash": content_hash(base)}
    artifact = CanonicalRecoveryArtifact.model_validate(payload)

    assert artifact.model_dump(mode="json") == payload
    assert "state_scope" not in artifact.model_dump(mode="json")["document"]


def test_artifact_write_replays_and_refuses_conflicting_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    path = root / "candidate.json"

    assert write_json_artifact(payload={"candidate": "same"}, path=path, allowed_root=root)
    assert not write_json_artifact(payload={"candidate": "same"}, path=path, allowed_root=root)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_json_artifact(payload={"candidate": "different"}, path=path, allowed_root=root)


def _samples(count: int = 20, *, regression: bool = False) -> list[dict]:
    return [
        {
            "run_id": f"run-{index}",
            "conclusion_match": True,
            "legacy_input_tokens": 1000,
            "state_delta_input_tokens": 500,
            "legacy_latency_ms": 1000,
            "state_delta_latency_ms": 700,
            "legacy_quality_pass": True,
            "state_delta_quality_pass": not regression,
        }
        for index in range(count)
    ]


def test_legacy_retirement_gate_is_multidimensional_and_fail_closed() -> None:
    blocked = evaluate_legacy_retirement(_samples(3))
    assert blocked.retirement_allowed is False
    assert "minimum_samples" in blocked.blocked_reasons
    with pytest.raises(PermissionError, match="legacy retirement blocked"):
        require_legacy_retirement_allowed(blocked)

    passed = evaluate_legacy_retirement(_samples())
    require_legacy_retirement_allowed(passed)
    assert passed.retirement_allowed is True
    assert passed.sample_diffs[0].token_delta == -500
    assert passed.sample_diffs[0].latency_delta_ms == -300
    assert set(passed.checks) == {
        "minimum_samples",
        "conclusion_consistency",
        "token_budget",
        "latency",
        "quality",
        "quality_regressions",
    }

    regressed = evaluate_legacy_retirement(
        _samples(regression=True), thresholds=LegacyRetirementThresholds()
    )
    assert regressed.retirement_allowed is False
    assert {"quality", "quality_regressions"} <= set(regressed.blocked_reasons)
