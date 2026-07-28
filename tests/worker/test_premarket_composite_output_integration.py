from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables
from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep
from apps.worker.canary_materialization import CanaryActivation

_CREATED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
_TRADE_DATE = "2026-05-14"


@pytest.fixture(autouse=True)
def _mock_source_status_index():
    """Keep composite analysis output integration tests isolated from source gating by default."""
    with (
        patch("apps.api.services.source_service.get_data_source_status_index", return_value={}),
        patch(
            "apps.worker.runner._evaluate_premarket_readiness",
            return_value={"decision": "allow", "reason_code": None, "source_ref": "test:readiness"},
        ),
    ):
        yield


def _make_db_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _make_task_with_steps(db, step_names: list[str]) -> TaskRun:
    task = TaskRun(name="premarket", status=TaskStatus.pending)
    db.add(task)
    db.flush()
    for name in step_names:
        db.add(TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending))
    db.commit()
    return task


def _make_rich_snapshot(
    *,
    run_id: str = "run-composite-rich",
    trade_date: str = _TRADE_DATE,
) -> dict:
    """Return an analysis snapshot with macro + options data for the composite analysis pipeline."""
    return {
        "version": "1.0",
        "snapshot_id": f"XAUUSD:{trade_date}:{run_id}",
        "asset": "XAUUSD",
        "trade_date": trade_date,
        "snapshot_time": _CREATED_AT.isoformat(),
        "run_id": run_id,
        "input_snapshot_ids": {
            "macro": f"macro:{trade_date}:{run_id}",
            "options": f"options:{trade_date}:{run_id}",
        },
        "macro": {
            "status": "available",
            "data": {
                "indicators": {
                    "DXY": {
                        "value": 101.50,
                        "change_1w": -0.80,
                        "unit": "index",
                    },
                    "DGS10": {
                        "value": 4.42,
                        "change_1w": -0.12,
                        "unit": "percent",
                    },
                    "T10YIE": {
                        "value": 2.15,
                        "change_1w": -0.03,
                        "unit": "percent",
                    },
                    "RRPONTSYD": {
                        "value": 180.5,
                        "change_1w": -12.3,
                        "unit": "billions_usd",
                    },
                    "TGA": {
                        "value": 720.1,
                        "change_1w": 45.2,
                        "unit": "billions_usd",
                    },
                    "SOFR": {
                        "value": 4.33,
                        "change_1w": 0.0,
                        "unit": "percent",
                    },
                    "EFFR": {
                        "value": 4.33,
                        "unit": "percent",
                    },
                    "IORB": {
                        "value": 4.40,
                        "unit": "percent",
                    },
                },
                "source_refs": [{"source": "fred", "symbol": "DGS10"}],
            },
        },
        "options": {
            "status": "available",
            "data": {
                "intent": {"type": "supportive", "score": 0.65},
                "wall_scores": [
                    {"strike": 3300, "wall_score": 0.82, "wall_type": "put", "side": "support"},
                ],
                "support_resistance": {
                    "support": [{"strike": 3250, "score": 0.7}],
                    "resistance": [{"strike": 3400, "score": 0.6}],
                },
                "gex": {
                    "netgex_aggregate": {"gamma_zero": {"price": 3350}},
                    "by_expiry": {
                        "2026-06": {
                            "summary": {"net_gex": 2500, "dominant_side": "positive"},
                            "iv_skew": {"risk_reversal_25d": 0.15},
                        },
                    },
                },
                "walls": {
                    "block_pnt_walls": [{"strike": 3320, "block": 120, "pnt": 80}],
                },
                "data_source": {
                    "status": "FINAL",
                    "input_snapshot_ids": {"raw_file_sha256": "abc123"},
                    "expiries": ["2026-06", "2026-07"],
                },
                "data_quality": {"categories": {"prelim_data": 0}, "warnings": []},
            },
        },
        "positioning": {"status": "unavailable", "reason": "collector_not_implemented"},
        "news": {"status": "unavailable", "reason": "collector_not_implemented"},
        "technical": {"status": "unavailable", "reason": "feature_not_implemented"},
        "source_refs": [
            {"source": "analysis_snapshot", "snapshot_id": f"XAUUSD:{trade_date}:{run_id}"},
        ],
    }


def _make_noop_state_shadow_input() -> dict:
    return {
        "state_scope": "daily_close",
        "canonical_state_id": "state-shadow-root",
        "canonical_state": {
            "asset": "XAUUSD",
            "as_of": (_CREATED_AT - timedelta(hours=1)).isoformat(),
            "market_stage": "direction_decision",
            "core_thesis": "等待突破",
            "net_bias": "mixed_bullish",
            "dominant_drivers": [],
            "key_levels": [{"price": 3300, "role": "support"}],
            "scenario_states": [],
            "unresolved_items": [],
            "invalidation_conditions": [],
            "evidence_cursors": {},
            "input_snapshot_ids": {"market": "market-shadow-1"},
            "source_refs": [{"snapshot_id": "market-shadow-1"}],
        },
        "evidence": [],
        "evidence_cursors": {},
        "cutoff_at": _CREATED_AT.isoformat(),
        "assembled_at": _CREATED_AT.isoformat(),
    }


def _make_canary_input(*, run_id: str) -> tuple[dict, dict]:
    evidence_ref = {"snapshot_id": "market-canary-2"}
    return (
        {
            "asset": "XAUUSD",
            "trade_date": _TRADE_DATE,
            "state_scope": "daily_close",
            "canonical_state_id": "state-canary-root",
            "expected_head_version": 1,
            "canonical_state": {
                "schema_version": "1.1",
                "state_scope": "daily_close",
                "state_machine_version": "analysis_state.v1.1",
                "session": "daily_close",
                "trade_date": _TRADE_DATE,
                "asset": "XAUUSD",
                "as_of": (_CREATED_AT - timedelta(hours=1)).isoformat(),
                "market_stage": "direction_decision",
                "core_thesis": "等待突破",
                "net_bias": "mixed_bullish",
                "dominant_drivers": [],
                "key_levels": [{"value": 3300, "role": "support", "source": "market"}],
                "scenario_states": [],
                "unresolved_items": [],
                "invalidation_conditions": [],
                "evidence_cursors": {},
                "input_snapshot_ids": {"market": "market-canary-1"},
                "source_refs": [{"snapshot_id": "market-canary-1"}],
            },
            "evidence": [
                {
                    "source": "market",
                    "evidence_id": "market-canary-2",
                    "business_time": (_CREATED_AT - timedelta(minutes=2)).isoformat(),
                    "ingested_at": (_CREATED_AT - timedelta(minutes=1)).isoformat(),
                    "payload": {
                        "evidence_type": "key_level_event",
                        "asset": "XAUUSD",
                        "source_quality": "validated",
                        "level_id": "resistance-3350",
                        "level_role": "resistance",
                        "level_value": 3350,
                        "observed_value": 3355,
                        "event": "confirmed_break",
                        "confirmation_status": "confirmed",
                    },
                    "source_ref": evidence_ref,
                }
            ],
            "evidence_cursors": {},
            "cutoff_at": _CREATED_AT.isoformat(),
            "assembled_at": _CREATED_AT.isoformat(),
        },
        evidence_ref,
    )


def _persistent_canary_activation(*, run_id: str, canary_input: dict) -> CanaryActivation:
    return CanaryActivation(
        asset="XAUUSD",
        trade_date=_TRADE_DATE,
        run_id=run_id,
        state_scope="daily_close",
        canonical_state_id=canary_input["canonical_state_id"],
        expected_head_version=canary_input["expected_head_version"],
        approval_id=f"approval-{run_id}",
        approval_hash="f" * 64,
        activation_identity=f"approval-{run_id}",
    )


def _canary_analyzer(evidence_ref: dict):
    def analyzer(bundle):
        from apps.analysis.state import TransitionCandidate
        from apps.analysis.state.transition_generator import ScopedTransitionCandidate

        candidate = TransitionCandidate.model_validate(
            {
                "previous_state_id": bundle.canonical_state_id,
                "summary": "canary transition",
                "changes": [
                    {
                        "target": "core_thesis",
                        "action": "strengthen",
                        "reason": "canary price confirmation",
                        "evidence_refs": [evidence_ref],
                    },
                ],
                "state_patch": {
                    "core_thesis": "canary 突破确认",
                },
                "evidence_refs": [evidence_ref],
            }
        )
        return ScopedTransitionCandidate(
            asset=bundle.asset,
            state_scope=bundle.state_scope,
            run_id=bundle.run_id,
            canonical_state_id=bundle.canonical_state_id,
            context_bundle_id=bundle.bundle_id,
            context_bundle_hash=bundle.content_hash,
            candidate=candidate,
        )

    return analyzer


def test_canary_request_is_bound_to_all_fresh_bundle_consumers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.analysis.state.hashing import content_hash
    from apps.worker import runner
    from apps.worker.runner import _run_canary_sidecar_attempt

    run_id = "run-canary-ready"
    canary_input, evidence_ref = _make_canary_input(run_id=run_id)
    actual_gate_inputs: list[list] = []
    original_gate = runner.evaluate_quality_gate

    def record_gate(**kwargs):
        actual_gate_inputs.append(list(kwargs["agent_outputs"]))
        return original_gate(**kwargs)

    monkeypatch.setattr(runner, "evaluate_quality_gate", record_gate)
    _, outputs = _run_canary_sidecar_attempt(
        storage_root=tmp_path,
        snapshot=_make_rich_snapshot(run_id=run_id),
        run_id=run_id,
        created_at=_CREATED_AT,
        state_shadow_input=canary_input,
        state_delta_analyzer=_canary_analyzer(evidence_ref),
        canary_activation=_persistent_canary_activation(run_id=run_id, canary_input=canary_input),
        attempt=0,
        attempt_id="9e91da42-c596-5f09-a010-440e7250cc6d",
    )

    trace = outputs["state_delta_shadow"]
    request = outputs["canary_materialization_request"]
    authority = outputs["canary_authority_payload"]
    assert trace["status"] == "candidate_accepted_shadow_only"
    assert "_review_result" not in trace
    assert len(trace["bundle_consumers"]) == 9
    assert request.context_bundle_id == trace["bundle_id"]
    assert request.context_bundle_hash == trace["bundle_content_hash"]
    assert request.run_id == run_id
    assert request.activation_source == "persistent_approval"
    assert request.approval_id == f"approval-{run_id}"
    assert authority.transition_consistency.status == "unverifiable"
    post_gate_inputs = actual_gate_inputs[-1]
    assert [output.agent_name for output in post_gate_inputs] == list(authority.agent_outputs)
    assert authority.quality_gate_input_hashes == [
        content_hash(
            output.model_dump(mode="json", exclude_computed_fields=True),
            exclude_keys=frozenset(),
        )
        for output in post_gate_inputs
    ]
    assert authority.fact_review_output_hash == authority.agent_output_hashes["fact_review_agent"]
    assert set(authority.transition_consistency.unverifiable_fields) == {
        "net_bias",
        "market_stage",
        "core_thesis",
        "dominant_drivers",
    }
    assert set(request.consumer_projection_hashes) == {
        "macro",
        "options",
        "risk",
        "technical",
        "positioning",
        "news",
        "market_odds",
        "fact_review",
        "coordinator",
    }
    for agent_name, agent_output in outputs["agents"].items():
        if agent_name in trace["bundle_consumers"]:
            consumer = agent_output.input_payload["context_bundle_consumer"]
            assert (
                request.consumer_projection_hashes[consumer]
                == agent_output.input_snapshot_ids["context_bundle_projection_hash"]
            )


def test_canary_advances_trade_date_from_current_bundle_cutoff(tmp_path: Path) -> None:
    from apps.worker.runner import _run_canary_sidecar_attempt

    run_id = "run-canary-next-trade-date"
    canary_input, evidence_ref = _make_canary_input(run_id=run_id)
    canary_input["canonical_state"]["trade_date"] = "2026-05-13"
    canary_input["canonical_state"]["as_of"] = "2026-05-13T08:00:00+00:00"
    canary_input["trade_date"] = _TRADE_DATE
    canary_input["cutoff_at"] = _CREATED_AT.isoformat()
    canary_input["assembled_at"] = _CREATED_AT.isoformat()

    _, outputs = _run_canary_sidecar_attempt(
        storage_root=tmp_path,
        snapshot=_make_rich_snapshot(run_id=run_id),
        run_id=run_id,
        created_at=_CREATED_AT,
        state_shadow_input=canary_input,
        state_delta_analyzer=_canary_analyzer(evidence_ref),
        canary_activation=_persistent_canary_activation(run_id=run_id, canary_input=canary_input),
        attempt=0,
        attempt_id="00000000-0000-0000-0000-000000000082",
    )

    request = outputs["canary_materialization_request"]
    assert request.review.next_state.trade_date.isoformat() == _TRADE_DATE


def test_state_delta_primary_remains_readiness_blocked(tmp_path: Path) -> None:
    from apps.worker.runner import _run_composite_analysis_pipeline

    def unexpected(_bundle):
        raise AssertionError("state_delta_primary must remain disabled")

    _, outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=_make_rich_snapshot(run_id="run-primary-blocked"),
        run_id="run-primary-blocked",
        created_at=_CREATED_AT,
        analysis_context_mode="state_delta_primary",
        state_delta_analyzer=unexpected,
    )
    trace = outputs["state_delta_shadow"]
    assert trace["status"] == "readiness_blocked"
    assert trace["reason"] == "state_delta_primary_not_ready"
    assert trace["model_invocation"] == "skipped"
    assert "canary_materialization_request" not in outputs


def test_canary_sidecar_cannot_overwrite_legacy_report_or_card(tmp_path: Path) -> None:
    from apps.worker import runner

    run_id = "run-canary-isolated"
    snapshot = _make_rich_snapshot(run_id=run_id)
    canary_input, evidence_ref = _make_canary_input(run_id=run_id)
    _, legacy_outputs = runner._run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id=run_id,
        created_at=_CREATED_AT,
        analysis_context_mode="legacy",
    )
    official_paths = [
        *legacy_outputs["report_result"]["paths"],
        *legacy_outputs["card_result"]["paths"],
    ]
    before = {path: Path(path).read_bytes() for path in official_paths}

    _, canary_outputs = runner._run_canary_sidecar_attempt(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id=run_id,
        created_at=_CREATED_AT,
        state_shadow_input=canary_input,
        state_delta_analyzer=_canary_analyzer(evidence_ref),
        canary_activation=_persistent_canary_activation(run_id=run_id, canary_input=canary_input),
        attempt=0,
        attempt_id="60e89ac3-4cc0-59c7-8508-d825dddf487f",
    )

    assert {path: Path(path).read_bytes() for path in official_paths} == before
    attempt_root = Path(canary_outputs["canary_attempt_root"]).resolve()
    sidecar_paths = [
        *canary_outputs["report_result"]["paths"],
        *canary_outputs["card_result"]["paths"],
    ]
    assert sidecar_paths
    assert all(Path(path).resolve().is_relative_to(attempt_root) for path in sidecar_paths)
    descriptor = canary_outputs["context_bundle_registry_artifact"]
    assert descriptor["file_path"].startswith("outputs/context_bundles/")
    assert (tmp_path / descriptor["file_path"]).is_file()
    assert canary_outputs["canary_materialization_request"].authority_hash


def test_canary_composite_rejects_non_sidecar_storage(tmp_path: Path) -> None:
    from apps.worker.runner import _run_composite_analysis_pipeline

    run_id = "run-canary-unsafe-root"
    canary_input, evidence_ref = _make_canary_input(run_id=run_id)
    with pytest.raises(ValueError, match="requires sidecar attempt"):
        _run_composite_analysis_pipeline(
            storage_root=tmp_path,
            snapshot=_make_rich_snapshot(run_id=run_id),
            run_id=run_id,
            created_at=_CREATED_AT,
            analysis_context_mode="canary",
            state_shadow_input=canary_input,
            state_delta_analyzer=_canary_analyzer(evidence_ref),
        )


def test_composite_state_delta_shadow_shares_one_bundle_without_canonical_write(
    tmp_path: Path,
) -> None:
    from apps.worker.runner import _run_composite_analysis_pipeline

    run_id = "run-state-delta-shadow"
    snapshot = _make_rich_snapshot(run_id=run_id)
    evidence_ref = {"snapshot_id": "market-shadow-2"}
    shadow_input = {
        "state_scope": "daily_close",
        "canonical_state_id": "state-shadow-root",
        "canonical_state": {
            "asset": "XAUUSD",
            "as_of": (_CREATED_AT - timedelta(hours=1)).isoformat(),
            "market_stage": "direction_decision",
            "core_thesis": "等待突破",
            "net_bias": "mixed_bullish",
            "dominant_drivers": [],
            "key_levels": [{"price": 3300, "role": "support"}],
            "scenario_states": [],
            "unresolved_items": [],
            "invalidation_conditions": [],
            "evidence_cursors": {},
            "input_snapshot_ids": {"market": "market-shadow-1"},
            "source_refs": [{"snapshot_id": "market-shadow-1"}],
        },
        "evidence": [
            {
                "source": "market",
                "evidence_id": "market-shadow-2",
                "business_time": (_CREATED_AT - timedelta(minutes=2)).isoformat(),
                "ingested_at": (_CREATED_AT - timedelta(minutes=1)).isoformat(),
                # Minimal typed payload conforming to the published #76 EvidenceDelta
                # contract (validated key_level_event) so the v3 bundle can evaluate
                # and retain it for the shadow analyzer.
                "payload": {
                    "evidence_type": "key_level_event",
                    "asset": "XAUUSD",
                    "source_quality": "validated",
                    "level_id": "support-3300",
                    "level_role": "support",
                    "level_value": 3300,
                    "observed_value": 3350,
                    "event": "confirmed_break",
                    "confirmation_status": "confirmed",
                },
                "source_ref": evidence_ref,
            }
        ],
        "evidence_cursors": {},
        "cutoff_at": _CREATED_AT.isoformat(),
        "assembled_at": _CREATED_AT.isoformat(),
    }

    def analyzer(bundle):
        return {
            "previous_state_id": bundle.canonical_state_id,
            "summary": "shadow transition",
            "changes": [
                {
                    "target": "core_thesis",
                    "action": "strengthen",
                    "reason": "shadow price confirmation",
                    "evidence_refs": [evidence_ref],
                },
            ],
            "state_patch": {
                "core_thesis": "shadow 突破确认",
            },
            "evidence_refs": [evidence_ref],
        }

    summaries, outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id=run_id,
        created_at=_CREATED_AT,
        analysis_context_mode="state_delta_context",
        state_shadow_input=shadow_input,
        state_delta_analyzer=analyzer,
    )

    shadow = outputs["state_delta_shadow"]
    assert summaries["state_delta_shadow"]["status"] == "success"
    assert summaries["state_delta_shadow"]["shadow_status"] == ("candidate_accepted_shadow_only")
    assert shadow["production_canonical_write_allowed"] is False
    assert shadow["shadow_review_status"] == "accepted"
    bundle_ids = set(shadow["bundle_consumers"].values())
    assert bundle_ids == {shadow["bundle_id"]}
    for name in (
        "macro_liquidity_agent",
        "cme_options_agent",
        "risk_agent",
        "technical_agent",
        "positioning_agent",
        "news_agent",
        "market_odds_agent",
        "fact_review_agent",
        "coordinator_agent",
    ):
        agent_output = outputs["agents"][name]
        lineage = agent_output.input_snapshot_ids
        assert lineage["context_bundle_id"] == shadow["bundle_id"]
        assert lineage["context_bundle_hash"] == shadow["bundle_content_hash"]
        assert lineage["canonical_state_id"] == shadow["canonical_state_id"]
        assert lineage["state_scope"] == "daily_close"
        assert "retained_evidence_ids" in lineage
        assert lineage["evidence_delta_decision_id"] == shadow["evidence_delta_decision_id"]
        assert (
            agent_output.input_payload["context_bundle_summary"]["decision_id"] == shadow["evidence_delta_decision_id"]
        )
    assert outputs["context_bundle_registry_artifact"]["metadata"]["bundle_id"] == shadow["bundle_id"]
    assert (tmp_path / shadow["bundle_path"]).is_file()


def test_state_delta_pipeline_rejects_consumer_bypass_and_prebuilt_outputs(tmp_path: Path, monkeypatch) -> None:
    from apps.worker import composite_analysis_pipeline as pipeline

    original = pipeline.analyze_market_odds

    def bypass_projection(snapshot, *, created_at=None, context_projection=None):
        assert context_projection is not None
        return original(snapshot, created_at=created_at)

    monkeypatch.setattr(pipeline, "analyze_market_odds", bypass_projection)
    with pytest.raises(ValueError, match="market_odds_agent did not return auditable"):
        pipeline.run_composite_analysis_pipeline(
            storage_root=tmp_path,
            snapshot=_make_rich_snapshot(run_id="run-consumer-bypass"),
            run_id="run-consumer-bypass",
            created_at=_CREATED_AT,
            analysis_context_mode="state_delta_context",
            state_shadow_input=_make_noop_state_shadow_input(),
        )

    def forge_projection_content(snapshot, *, created_at=None, context_projection=None):
        assert context_projection is not None
        output = original(
            snapshot,
            created_at=created_at,
            context_projection=context_projection,
        )
        input_payload = dict(output.input_payload)
        input_payload["context_bundle_projection"] = {"forged": True}
        return output.model_copy(update={"input_payload": input_payload})

    monkeypatch.setattr(pipeline, "analyze_market_odds", forge_projection_content)
    with pytest.raises(ValueError, match="did not consume its exact typed projection"):
        pipeline.run_composite_analysis_pipeline(
            storage_root=tmp_path,
            snapshot=_make_rich_snapshot(run_id="run-consumer-forgery"),
            run_id="run-consumer-forgery",
            created_at=_CREATED_AT,
            analysis_context_mode="state_delta_context",
            state_shadow_input=_make_noop_state_shadow_input(),
        )

    monkeypatch.setattr(pipeline, "analyze_market_odds", original)
    with pytest.raises(ValueError, match="forbids unverified prebuilt Agent outputs"):
        pipeline.run_composite_analysis_pipeline(
            storage_root=tmp_path,
            snapshot=_make_rich_snapshot(run_id="run-prebuilt-bypass"),
            run_id="run-prebuilt-bypass",
            created_at=_CREATED_AT,
            macro_output_prebuilt=object(),
            analysis_context_mode="state_delta_context",
            state_shadow_input=_make_noop_state_shadow_input(),
        )


def test_composite_manual_review_keeps_review_item_and_skips_transition_analyzer(
    tmp_path: Path,
) -> None:
    from apps.worker.runner import _run_composite_analysis_pipeline

    run_id = "run-state-delta-manual-review"
    calls = 0
    shadow_input = {
        "state_scope": "daily_close",
        "canonical_state_id": "state-shadow-root",
        "canonical_state": {
            "asset": "XAUUSD",
            "as_of": (_CREATED_AT - timedelta(hours=1)).isoformat(),
            "market_stage": "direction_decision",
            "core_thesis": "等待宏观确认",
            "net_bias": "mixed_bullish",
            "dominant_drivers": [],
            "key_levels": [{"price": 3300, "role": "support"}],
            "scenario_states": [],
            "unresolved_items": [],
            "invalidation_conditions": [],
            "evidence_cursors": {},
            "input_snapshot_ids": {"market": "market-shadow-1"},
            "source_refs": [{"snapshot_id": "market-shadow-1"}],
        },
        "evidence": [
            {
                "source": "unverified_macro",
                "evidence_id": "dxy-unverified-material",
                "business_time": (_CREATED_AT - timedelta(minutes=2)).isoformat(),
                "ingested_at": (_CREATED_AT - timedelta(minutes=1)).isoformat(),
                "payload": {
                    "evidence_type": "macro_metric",
                    "asset": "XAUUSD",
                    "source_quality": "unverified",
                    "metric": "dxy",
                    "current_value": 101.0,
                    "previous_value": 100.0,
                    "unit": "index",
                },
                "source_ref": {"snapshot_id": "macro-shadow-unverified"},
            }
        ],
        "evidence_cursors": {},
        "cutoff_at": _CREATED_AT.isoformat(),
        "assembled_at": _CREATED_AT.isoformat(),
    }

    def analyzer(_bundle):
        nonlocal calls
        calls += 1
        raise AssertionError("manual review must skip transition analyzer")

    _summaries, outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=_make_rich_snapshot(run_id=run_id),
        run_id=run_id,
        created_at=_CREATED_AT,
        analysis_context_mode="state_delta_context",
        state_shadow_input=shadow_input,
        state_delta_analyzer=analyzer,
    )

    shadow = outputs["state_delta_shadow"]
    assert calls == 0
    assert shadow["schema_version"] == "composite_state_shadow.v3"
    assert shadow["status"] == "manual_review_required"
    assert shadow["evidence_delta_action"] == "manual_review"
    assert shadow["review_items"][0]["run_id"] == run_id


def test_composite_shadow_setup_failure_does_not_break_legacy_outputs(tmp_path: Path) -> None:
    from apps.worker.runner import _run_composite_analysis_pipeline

    summaries, outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=_make_rich_snapshot(run_id="run-shadow-setup-failure"),
        run_id="run-shadow-setup-failure",
        created_at=_CREATED_AT,
        analysis_context_mode="state_delta_context",
        state_shadow_input={"state_scope": {"untrusted": "must-not-enter-trace"}},
    )

    assert summaries["final_report"]["status"] == "success"
    assert outputs["report_result"]["paths"]
    assert outputs["state_delta_shadow"]["status"] == "shadow_setup_failed"
    assert outputs["state_delta_shadow"]["schema_version"] == "composite_state_shadow.v3"
    assert outputs["state_delta_shadow"]["evidence_delta_action"] == "manual_review"
    assert outputs["state_delta_shadow"]["requested_state_scope"] is None
    assert "must-not-enter-trace" not in str(outputs["state_delta_shadow"])
    assert outputs["state_delta_shadow"]["production_canonical_write_allowed"] is False
    review = outputs["state_delta_shadow"]["review_items"][0]
    assert review == {
        "review_id": "state_delta_setup:run-shadow-setup-failure:78a572444077af19",
        "run_id": "run-shadow-setup-failure",
        "source_module": "state_delta_shadow",
        "source_step_id": "state_delta_shadow_setup",
        "severity": "error",
        "reason": "State-delta shadow setup failed: ValueError",
        "impact_modules": ["analysis_state", "state_delta_shadow"],
        "suggested_action": "Review the trusted state-delta setup inputs before retrying shadow analysis.",
        "status": "pending",
        "evidence_refs": [],
    }
    assert "must-not-enter-trace" not in str(review)

    _, replay_outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=_make_rich_snapshot(run_id="run-shadow-setup-failure"),
        run_id="run-shadow-setup-failure",
        created_at=_CREATED_AT,
        analysis_context_mode="state_delta_context",
        state_shadow_input={"state_scope": {"untrusted": "must-not-enter-trace"}},
    )
    assert replay_outputs["state_delta_shadow"]["review_items"][0]["review_id"] == review["review_id"]


def test_composite_source_health_uses_completed_snapshot_over_preliminary_news_health() -> None:
    from apps.worker.composite_analysis_pipeline import source_health_from_snapshot

    snapshot = _make_rich_snapshot(run_id="run-completed-source-health")
    snapshot["technical"] = {
        "status": "available",
        "data": {"price": 3300.0, "atr14": 40.0},
    }
    snapshot["source_refs"].append(
        {
            "source": "jin10_quote",
            "symbol": "XAUUSD",
            "raw_path": "raw/technical/XAUUSD.json",
        }
    )
    snapshot["news"] = {
        "status": "available",
        "data": {
            "gold_macro_overview": {
                "source_health": {
                    "overall_status": "blocked",
                    "p0_missing": ["xauusd_price"],
                }
            }
        },
    }

    health = source_health_from_snapshot(snapshot)

    assert "xauusd_price" not in health["p0_missing"]
    assert health["source_freshness"]["xauusd_price"]["status"] == "fresh"


# ═══════════════════════════════════════════════════════════════════════
# composite analysis pipeline unit tests (no DB)
# ═══════════════════════════════════════════════════════════════════════


def test_composite_analysis_pipeline_writes_final_report_and_strategy_card(tmp_path: Path) -> None:
    """composite analysis should produce final_report.md, strategy_card.md and strategy_card.json."""
    from apps.worker.runner import _run_composite_analysis_pipeline

    snapshot = _make_rich_snapshot(run_id="run-composite-artifacts")
    summaries, outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-composite-artifacts",
        created_at=_CREATED_AT,
    )

    # ── step summaries ──
    assert "domain_agents" in summaries
    assert summaries["domain_agents"]["status"] == "success"
    assert summaries["domain_agents"]["macro_status"] is not None
    assert summaries["domain_agents"]["options_status"] is not None
    assert summaries["domain_agents"]["risk_status"] is not None
    assert summaries["domain_agents"]["coordinator_status"] is not None

    assert "final_report" in summaries
    assert summaries["final_report"]["status"] == "success"
    assert len(summaries["final_report"]["paths"]) >= 1  # P4-04: may include structured_report.json
    assert "quality_gate_decision" in summaries["final_report"]
    assert "agent_loop_decision" in summaries["final_report"]
    assert (
        summaries["final_report"]["quality_gate_action"] == summaries["final_report"]["quality_gate_decision"]["action"]
    )
    assert isinstance(summaries["final_report"]["publish_allowed"], bool)
    source_health_path = tmp_path / summaries["final_report"]["source_health_path"]
    quality_gate_result_path = tmp_path / summaries["final_report"]["quality_gate_result_path"]
    assert json.loads(source_health_path.read_text(encoding="utf-8")) == outputs["source_health"]
    persisted_gate = json.loads(quality_gate_result_path.read_text(encoding="utf-8"))
    assert persisted_gate["publish_allowed"] is outputs["agent_loop_decision"].publish_allowed
    assert persisted_gate["quality_gate_decision"] == outputs["post_coordinator_quality_gate_decision"].model_dump(
        mode="json"
    )

    assert "strategy_card" in summaries
    assert summaries["strategy_card"]["status"] == "success"
    assert len(summaries["strategy_card"]["paths"]) == 2
    assert "gold_runtime_summary" in summaries
    assert summaries["gold_runtime_summary"]["run_mode"] == "premarket_full_run"
    assert summaries["gold_runtime_summary"]["runtime_contract_only"] is False
    assert summaries["gold_runtime_summary"]["artifact_execution_enabled"] is True
    assert (
        summaries["gold_runtime_summary"]["pipeline_materialized_outputs"]
        is summaries["final_report"]["publish_allowed"]
    )
    assert summaries["gold_runtime_summary"]["executed_agents"] == ["report_render_agent"]
    report_agent_path = tmp_path / summaries["final_report"]["report_render_agent_path"]
    assert report_agent_path.exists()
    report_agent = json.loads(report_agent_path.read_text(encoding="utf-8"))
    assert report_agent["agent_name"] == "report_render_agent"
    expected_artifact_types = (
        {"final_report", "strategy_card"}
        if summaries["final_report"]["publish_allowed"]
        else {"observation_report", "observation_strategy_card"}
    )
    assert {item["artifact_type"] for item in report_agent["artifact_refs"]} == expected_artifact_types
    if not summaries["final_report"]["publish_allowed"]:
        assert not expected_artifact_types & {"final_report", "strategy_card"}
    for _ in range(9):
        rerun_summaries, rerun_outputs = _run_composite_analysis_pipeline(
            storage_root=tmp_path,
            snapshot=snapshot,
            run_id="run-composite-artifacts",
            created_at=_CREATED_AT,
        )
        assert rerun_summaries["final_report"]["paths"] == summaries["final_report"]["paths"]
        assert rerun_outputs["report_result"]["skipped"] is True
        assert rerun_outputs["card_result"]["skipped"] is True
        assert (
            rerun_outputs["report_render_agent_result"].content_sha256
            == outputs["report_render_agent_result"].content_sha256
        )
    assert summaries["gold_runtime_summary"]["quality_gate_status"] in {
        "passed",
        "fallback_required",
        "needs_review",
        "blocked",
    }

    # ── files exist ──
    report_path = Path(summaries["final_report"]["paths"][0])
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "# XAUUSD 相关报告" in report_text
    assert "数据刷新时间:" in report_text
    assert "### 宏观流动性视图" in report_text
    assert "## 免责声明" in report_text

    # P4-04: verify structured_report.json when present
    if len(summaries["final_report"]["paths"]) >= 2:
        structured_path = Path(summaries["final_report"]["paths"][1])
        assert structured_path.exists()
        assert structured_path.name == "structured_report.json"

    json_path = Path(summaries["strategy_card"]["paths"][0])
    md_path = Path(summaries["strategy_card"]["paths"][1])
    assert json_path.exists()
    assert md_path.exists()
    assert "# XAUUSD Strategy Card" in md_path.read_text(encoding="utf-8")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["asset"] == "XAUUSD"
    assert data["is_trade_instruction"] is False
    assert "analysis_snapshot" in data["input_snapshot_ids"]
    assert "coordinator" in data["input_snapshot_ids"]


def test_composite_runtime_summary_merges_seven_gold_agents_with_report_render(
    tmp_path: Path,
) -> None:
    from apps.analysis.agents.gold_runtime_agents import materialize_gold_runtime_agent_artifacts
    from apps.worker.runner import _run_composite_analysis_pipeline

    run_id = "run-eight-gold-agents"
    snapshot = _make_rich_snapshot(run_id=run_id)
    execution = materialize_gold_runtime_agent_artifacts(
        storage_root=tmp_path,
        retrieved_date=_TRADE_DATE,
        run_id=run_id,
        as_of=f"{_TRADE_DATE}T09:30:00+00:00",
        input_snapshot_ids={"analysis_snapshot": snapshot["snapshot_id"]},
        source_refs=[{"source": "fixture", "source_ref": "fixture:gold"}],
        canonical_paths={
            "source_health": f"analysis/gold_mainlines/{_TRADE_DATE}/{run_id}/source_health.json",
            "gold_event_mainlines": f"features/news/{_TRADE_DATE}/{run_id}/gold_event_mainlines.json",
            "gold_macro_overview": f"analysis/gold_mainlines/{_TRADE_DATE}/{run_id}/gold_macro_overview.json",
            "quality_gate_result": f"analysis/gold_mainlines/{_TRADE_DATE}/{run_id}/quality_gate_result.json",
        },
        source_health={"overall_status": "degraded"},
        gold_event_mainlines={"status": "partial", "mainlines": [{"confidence": 0.7}]},
        gold_macro_overview={
            "status": "partial",
            "analysis_readiness": {"ready_count": 6, "total_count": 9},
        },
        review_gate={"review_status": "needs_review"},
    )
    snapshot["news"] = {
        "status": "available",
        "data": {
            "gold_agent_execution": {
                "snapshot_id": execution["snapshot_id"],
                "declared_agents": execution["declared_agents"],
                "materialized_stage_envelopes": execution["materialized_stage_envelopes"],
                "executed_agents": execution["executed_agents"],
                "artifact_paths": execution["artifact_paths"],
            }
        },
    }

    summaries, _ = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id=run_id,
        created_at=_CREATED_AT,
    )

    runtime = summaries["gold_runtime_summary"]
    assert runtime["executed_agents"] == ["report_render_agent"]
    assert runtime["declared_agents"] == [
        "source_health_agent",
        "event_attribution_agent",
        "transmission_chain_agent",
        "driver_decomposition_agent",
        "mainline_ranking_agent",
        "gold_macro_overview_agent",
        "review_gate_agent",
        "report_render_agent",
    ]
    assert runtime["materialized_stage_envelopes"] == runtime["declared_agents"]
    assert set(runtime["agent_artifact_refs"]) == set(runtime["materialized_stage_envelopes"])


def test_composite_analysis_pipeline_returns_final_report_quality_gate_metadata(tmp_path: Path) -> None:
    from apps.analysis.agents.quality_gate_evaluator import QualityGateDecision
    from apps.worker.runner import _run_composite_analysis_pipeline

    snapshot = _make_rich_snapshot(run_id="run-quality-gate")
    summaries, composite_outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-quality-gate",
        created_at=_CREATED_AT,
    )

    decision = composite_outputs["quality_gate_decision"]
    assert isinstance(decision, QualityGateDecision)
    assert summaries["final_report"]["quality_gate_decision"] == decision.model_dump(mode="json")
    assert summaries["final_report"]["quality_gate_action"] == decision.action.value
    assert summaries["final_report"]["review_status"] == decision.review_status
    assert summaries["final_report"]["publish_allowed"] == composite_outputs["agent_loop_decision"].publish_allowed
    runtime_summary = composite_outputs["gold_runtime_summary"]
    assert runtime_summary["quality_gate_decision"] == decision.model_dump(mode="json")
    assert runtime_summary["agent_loop_decision"] == composite_outputs["agent_loop_decision"].model_dump(mode="json")
    if summaries["final_report"]["publish_allowed"]:
        assert runtime_summary["accepted_outputs"]["final_report_paths"] == summaries["final_report"]["paths"]
        assert runtime_summary["accepted_outputs"]["strategy_card_paths"] == summaries["strategy_card"]["paths"]
    else:
        assert runtime_summary["accepted_outputs"] == {}
        assert composite_outputs["observe_outputs"]["final_report_paths"] == summaries["final_report"]["paths"]
    assert runtime_summary["fallback_attempts"] == 0


def test_composite_analysis_pipeline_primary_pass_renders_primary_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
    from apps.analysis.agents import coordinator as coordinator_module
    from apps.worker import runner
    from apps.worker import composite_analysis_pipeline as pipeline_module
    from apps.worker.runner import _run_composite_analysis_pipeline

    primary = QualityGateDecision(
        action=QualityGateAction.PASS,
        review_status="pass",
        publish_allowed=True,
        findings=[],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.7,
    )
    events: list[str] = []
    original_fact_review = pipeline_module.build_runtime_fact_review_agent_output
    original_coordinator = coordinator_module.coordinate_agent_outputs

    def record_fact_review(*args: object, **kwargs: object):
        events.append("fact_review")
        return original_fact_review(*args, **kwargs)

    def record_gate(**_: object):
        events.append("quality_gate")
        return primary

    def record_coordinator(*args: object, **kwargs: object):
        events.append("coordinator")
        return original_coordinator(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "build_runtime_fact_review_agent_output", record_fact_review)
    monkeypatch.setattr(runner, "evaluate_quality_gate", record_gate)
    monkeypatch.setattr(coordinator_module, "coordinate_agent_outputs", record_coordinator)

    summaries, outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=_make_rich_snapshot(run_id="run-primary-pass"),
        run_id="run-primary-pass",
        created_at=_CREATED_AT,
    )

    assert outputs["agent_loop_decision"].fallback_trace["accepted_output"] == "primary"
    assert outputs["agent_loop_decision"].accepted_output.source == "primary"
    assert outputs["agent_loop_decision"].accepted_output.agent_name == "coordinator_agent"
    assert outputs["agent_loop_decision"].accepted_output.artifact_ref is not None
    assert events == ["fact_review", "quality_gate", "coordinator", "quality_gate"]
    assert "fact_review_agent" in outputs["agents"]
    assert outputs["agents"]["fact_review_agent"].input_payload["reviewed_agent_outputs"]
    assert summaries["final_report"]["output_mode"] == "accepted"
    assert outputs["observe_outputs"] == {}
    assert (
        outputs["gold_runtime_summary"]["accepted_outputs"]["final_report_paths"] == summaries["final_report"]["paths"]
    )
    assert (
        outputs["strategy_card"].input_snapshot_ids["coordinator"] == outputs["agents"]["coordinator_agent"].snapshot_id
    )


def test_composite_analysis_pipeline_primary_pass_rejects_empty_renderer_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
    from apps.worker import composite_analysis_pipeline as pipeline_module
    from apps.worker import runner
    from apps.worker.runner import _run_composite_analysis_pipeline

    primary = QualityGateDecision(
        action=QualityGateAction.PASS,
        review_status="pass",
        publish_allowed=True,
        findings=[],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.7,
    )
    monkeypatch.setattr(runner, "evaluate_quality_gate", lambda **_: primary)
    monkeypatch.setattr(
        pipeline_module,
        "write_final_report",
        lambda **_: {"artifact_type": "final_report", "paths": [], "skipped": False},
    )
    monkeypatch.setattr(
        pipeline_module,
        "write_strategy_card",
        lambda **_: {"artifact_type": "strategy_card", "paths": [], "skipped": False},
    )

    with pytest.raises(
        RuntimeError,
        match="accepted output materialization produced no final_report paths",
    ):
        _run_composite_analysis_pipeline(
            storage_root=tmp_path,
            snapshot=_make_rich_snapshot(run_id="run-empty-render-paths"),
            run_id="run-empty-render-paths",
            created_at=_CREATED_AT,
        )

    report_agent_path = (
        tmp_path
        / "analysis"
        / "gold_mainlines"
        / _TRADE_DATE
        / "run-empty-render-paths"
        / "agent_outputs"
        / "report_render_output.json"
    )
    assert not report_agent_path.exists()


def test_accepted_output_validation_rejects_declared_but_missing_artifacts(tmp_path: Path) -> None:
    from apps.worker.composite_analysis_pipeline import validated_rendered_outputs

    with pytest.raises(
        RuntimeError,
        match="accepted final_report artifact is not materialized",
    ):
        validated_rendered_outputs(
            storage_root=tmp_path,
            snapshot_id="snapshot:missing-artifacts",
            report_result={
                "artifact_type": "final_report",
                "paths": [str(tmp_path / "outputs" / "final_report" / "missing.md")],
            },
            card_result={
                "artifact_type": "strategy_card",
                "paths": [str(tmp_path / "outputs" / "strategy_card" / "missing.json")],
            },
            publish_allowed=True,
        )


def test_composite_analysis_pipeline_synthesizes_from_coordinator_after_post_gate_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
    from apps.worker import runner
    from apps.worker.runner import _run_composite_analysis_pipeline

    primary_decision = QualityGateDecision(
        action=QualityGateAction.FALLBACK,
        review_status="needs_review",
        publish_allowed=True,
        fallback_recommended=True,
        findings=[
            {
                "code": "unsupported_claim",
                "severity": "fallback",
                "message": "Unsupported primary conclusion.",
                "evidence": {},
            }
        ],
        fallback_actions=["fallback_reanalyze"],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.76,
    )
    fallback_decision = QualityGateDecision(
        action=QualityGateAction.PASS,
        review_status="pass",
        publish_allowed=True,
        findings=[],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.55,
    )
    monkeypatch.setattr(runner, "evaluate_quality_gate", lambda **_: primary_decision)
    monkeypatch.setattr("apps.analysis.agents.fallback_executor.evaluate_quality_gate", lambda **_: fallback_decision)

    snapshot = _make_rich_snapshot(run_id="run-composite-fallback")
    summaries, composite_outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-composite-fallback",
        created_at=_CREATED_AT,
    )

    assert "fallback_synthesis_agent" in composite_outputs["agents"]
    assert "fact_review_agent" in composite_outputs["agents"]
    fallback = composite_outputs["agents"]["fallback_synthesis_agent"]
    assert fallback.input_payload["fallback_of"]["agent_name"] == "coordinator_agent"
    assert summaries["final_report"]["pre_coordinator_quality_gate_decision"]["action"] == "fallback"
    assert summaries["final_report"]["post_coordinator_quality_gate_decision"]["action"] == "fallback"
    assert summaries["final_report"]["fallback_task_results"][0]["task_type"] == "fallback_reanalyze"
    assert summaries["final_report"]["agent_loop_decision"]["fallback_trace"]["accepted_output"] is None
    assert summaries["final_report"]["publish_allowed"] is False
    assert composite_outputs["strategy_card"].bias.value == "neutral"
    assert "No strong conclusion" in composite_outputs["strategy_card"].scenario_summary
    assert composite_outputs["observe_outputs"]["final_report_paths"] == summaries["final_report"]["paths"]
    assert composite_outputs["gold_runtime_summary"]["accepted_outputs"] == {}


def test_composite_analysis_pipeline_post_gate_can_reject_coordinator_after_pre_gate_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
    from apps.worker import runner
    from apps.worker.runner import _run_composite_analysis_pipeline

    pre_gate = QualityGateDecision(
        action=QualityGateAction.PASS,
        review_status="pass",
        publish_allowed=True,
        findings=[],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.68,
    )
    post_gate = QualityGateDecision(
        action=QualityGateAction.BLOCK_PUBLISH,
        review_status="blocked",
        publish_allowed=False,
        findings=[
            {
                "code": "active_blockers_present",
                "severity": "blocker",
                "message": "Coordinator introduced an active blocker.",
                "evidence": {},
            }
        ],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.68,
    )
    gate_inputs: list[list[str]] = []

    def evaluate_in_order(**kwargs):
        gate_inputs.append([output.agent_name for output in kwargs["agent_outputs"]])
        return pre_gate if len(gate_inputs) == 1 else post_gate

    monkeypatch.setattr(runner, "evaluate_quality_gate", evaluate_in_order)

    summaries, composite_outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=_make_rich_snapshot(run_id="run-post-coordinator-gate"),
        run_id="run-post-coordinator-gate",
        created_at=_CREATED_AT,
    )

    assert "coordinator_agent" not in gate_inputs[0]
    assert "coordinator_agent" in gate_inputs[1]
    assert summaries["final_report"]["pre_coordinator_quality_gate_decision"]["action"] == "pass"
    assert summaries["final_report"]["post_coordinator_quality_gate_decision"]["action"] == "block_publish"
    assert summaries["final_report"]["quality_gate_decision"]["action"] == "block_publish"
    assert summaries["final_report"]["publish_allowed"] is False
    assert composite_outputs["agent_loop_decision"].accepted_output.source == "none"
    assert (
        composite_outputs["agents"]["fallback_synthesis_agent"].input_payload["fallback_of"]["agent_name"]
        == "coordinator_agent"
    )


def test_composite_analysis_pipeline_executes_cme_options_reparse_when_gate_requires_reparse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
    from apps.worker import runner
    from apps.worker.runner import _run_composite_analysis_pipeline

    primary_decision = QualityGateDecision(
        action=QualityGateAction.FALLBACK,
        review_status="needs_review",
        publish_allowed=True,
        fallback_recommended=True,
        manual_review_required=True,
        findings=[
            {
                "code": "parse_or_required_field_quality_gap",
                "severity": "fallback",
                "message": "Parse gap.",
                "evidence": {},
            }
        ],
        fallback_actions=["fallback_reparse"],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.58,
    )
    fallback_decision = QualityGateDecision(
        action=QualityGateAction.PASS,
        review_status="pass",
        publish_allowed=True,
        findings=[],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.55,
    )
    monkeypatch.setattr(runner, "evaluate_quality_gate", lambda **_: primary_decision)
    monkeypatch.setattr("apps.analysis.agents.quality_gate.evaluate_quality_gate", lambda **_: fallback_decision)

    snapshot = _make_rich_snapshot(run_id="run-composite-reparse")
    summaries, composite_outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-composite-reparse",
        created_at=_CREATED_AT,
    )

    task_results = summaries["final_report"]["fallback_task_results"]
    assert task_results[0]["task_type"] == "fallback_reparse"
    assert task_results[0]["status"] == "observation_only"
    assert task_results[0]["execution_status"] == "success"
    assert task_results[0]["fallback_output_agent"] == "cme_options_reparse_agent"
    assert task_results[0]["publish_ready_after_correction"] is False
    assert "cme_options_reparse_agent" in composite_outputs["agents"]
    assert composite_outputs["agents"]["cme_options_reparse_agent"].input_payload["fallback_task"] == "fallback_reparse"
    assert task_results[1]["task_type"] == "fallback_conservative_synthesis"
    assert summaries["final_report"]["publish_allowed"] is False
    assert summaries["final_report"]["output_mode"] == "observe"
    assert composite_outputs["agent_loop_decision"].accepted_output.source == "none"


def test_composite_analysis_pipeline_binds_snapshot_id_to_outputs(tmp_path: Path) -> None:
    """All composite analysis outputs must bind to the input snapshot_id."""
    from apps.worker.runner import _run_composite_analysis_pipeline

    snapshot = _make_rich_snapshot(run_id="run-snapshot-id")
    summaries, _ = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-snapshot-id",
        created_at=_CREATED_AT,
    )

    snapshot_id = snapshot["snapshot_id"]
    assert summaries["final_report"]["snapshot_id"] == snapshot_id
    assert summaries["strategy_card"]["snapshot_id"] == snapshot_id

    # strategy_card input_snapshot_ids must include analysis_snapshot
    input_ids = summaries["strategy_card"]["input_snapshot_ids"]
    assert input_ids["analysis_snapshot"] == snapshot_id


def test_composite_analysis_pipeline_idempotent_rerun_preserves_history(tmp_path: Path) -> None:
    from apps.worker.runner import _run_composite_analysis_pipeline

    snapshot = _make_rich_snapshot(run_id="run-no-overwrite")

    _, first = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-no-overwrite",
        created_at=_CREATED_AT,
    )

    _, second = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-no-overwrite",
        created_at=_CREATED_AT,
    )

    assert first["report_result"]["paths"] == second["report_result"]["paths"]
    assert second["report_result"]["skipped"] is True
    assert second["card_result"]["skipped"] is True


def test_enrich_runner_artifact_metadata_skips_inferred_fields_for_missing_file() -> None:
    from apps.worker.runner import _enrich_runner_artifact_metadata

    artifact = {
        "artifact_id": "run-1:missing",
        "artifact_type": "structured_json",
        "file_path": "/tmp/does-not-exist/premarket_snapshot.json",
        "label": "keep-me",
    }

    enriched = _enrich_runner_artifact_metadata(artifact)

    assert enriched == artifact
    assert "content_type" not in enriched
    assert "byte_size" not in enriched
    assert "generated_at" not in enriched


def test_composite_analysis_pipeline_no_llm_no_network_calls(tmp_path: Path) -> None:
    """composite analysis agents are deterministic rule-based post-processors — no LLM, no network."""
    from apps.worker.runner import _run_composite_analysis_pipeline

    snapshot = _make_rich_snapshot(run_id="run-no-llm")

    # Run without network/LLM — if any agent tries to make an HTTP call
    # or invoke an LLM it will fail because we haven't set up any mocks.
    summaries, _ = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-no-llm",
        created_at=_CREATED_AT,
    )

    assert summaries["domain_agents"]["status"] == "success"


def test_composite_analysis_pipeline_records_partial_when_snapshot_has_missing_data(tmp_path: Path) -> None:
    """When macro data is missing, domain agents should produce partial statuses."""
    from apps.worker.runner import _run_composite_analysis_pipeline

    snapshot = _make_rich_snapshot(run_id="run-partial")
    # Remove macro indicators entirely
    snapshot["macro"] = {"status": "unavailable", "reason": "collector_failed"}
    # Remove options data too
    snapshot["options"] = {"status": "unavailable", "reason": "cme_download_failed"}

    summaries, _ = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-partial",
        created_at=_CREATED_AT,
    )

    assert summaries["domain_agents"]["macro_status"] == "unavailable"
    assert summaries["domain_agents"]["options_status"] == "unavailable"

    # final report still renders even with partial inputs
    report_path = Path(summaries["final_report"]["paths"][0])
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "## 数据质量与限制" in report_text  # unavailable agents produce warnings
    assert "unavailable" in report_text.lower()


def test_composite_analysis_pipeline_no_execution_language_in_outputs(tmp_path: Path) -> None:
    """Strategy card and report must contain no executable trading language."""
    from apps.worker.runner import _run_composite_analysis_pipeline

    snapshot = _make_rich_snapshot(run_id="run-no-exec")
    summaries, _ = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-no-exec",
        created_at=_CREATED_AT,
    )

    # Strategy card
    json_path = Path(summaries["strategy_card"]["paths"][0])
    md_path = Path(summaries["strategy_card"]["paths"][1])
    json_text = json_path.read_text(encoding="utf-8").lower()
    md_text = md_path.read_text(encoding="utf-8").lower()

    for forbidden in ("buy", "sell", "enter", "stop loss", "take profit"):
        assert forbidden not in json_text, f"forbidden '{forbidden}' in strategy_card.json"
        assert forbidden not in md_text, f"forbidden '{forbidden}' in strategy_card.md"

    # Final report
    report_path = Path(summaries["final_report"]["paths"][0])
    report_text = report_path.read_text(encoding="utf-8").lower()
    for forbidden in ("buy", "sell", "enter", "stop loss", "take profit"):
        assert forbidden not in report_text, f"forbidden '{forbidden}' in final_report.md"


def test_composite_analysis_pipeline_source_refs_flow_through(tmp_path: Path) -> None:
    """composite analysis outputs must carry source_refs from snapshot + agents."""
    from apps.worker.runner import _run_composite_analysis_pipeline

    snapshot = _make_rich_snapshot(run_id="run-source-refs")
    summaries, _ = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-source-refs",
        created_at=_CREATED_AT,
    )

    # Check strategy_card.json has source_refs
    json_path = Path(summaries["strategy_card"]["paths"][0])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "source_refs" in data
    assert isinstance(data["source_refs"], list)
    assert len(data["source_refs"]) > 0


def test_composite_analysis_pipeline_strategy_card_consumes_gold_macro_conditions(tmp_path: Path) -> None:
    """GoldMacroOverview should reach strategy_card as conditional research signals."""
    from apps.worker.runner import _run_composite_analysis_pipeline

    snapshot = _make_rich_snapshot(run_id="run-gold-macro-conditions")
    snapshot["news"] = {
        "status": "available",
        "data": {
            "gold_macro_overview": {
                "asset": "XAUUSD",
                "as_of": "2026-06-30T00:00:00Z",
                "phase": "macro_verification",
                "dominant_mainline": "real_rates_usd",
                "net_bias": "mixed",
                "driver_conflict": {"verification_needed": ["real_rate_response_needed"]},
                "verification_matrix": [
                    {"label": "多源确认", "status": "pending"},
                    {"label": "实际利率确认", "status": "pending"},
                ],
            }
        },
    }

    summaries, _ = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=snapshot,
        run_id="run-gold-macro-conditions",
        created_at=_CREATED_AT,
    )

    json_path = Path(summaries["strategy_card"]["paths"][0])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["gold_macro_conditions"]["dominant_mainline"] == "real_rates_usd"
    assert data["gold_macro_conditions"]["net_bias"] == "mixed"
    assert data["trigger_conditions"][0] == ("Gold macro context remains mixed with dominant mainline real_rates_usd.")
    assert any("Gold macro condition" in item for item in data["confirmation_conditions"])
    assert any("GoldMacroOverview dominant mainline changes" in item for item in data["invalid_conditions"])


def test_composite_analysis_pipeline_rejected_fallback_writes_observe_outputs_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
    from apps.worker import runner
    from apps.worker.runner import _run_composite_analysis_pipeline

    primary = QualityGateDecision(
        action=QualityGateAction.FALLBACK,
        review_status="needs_review",
        publish_allowed=True,
        fallback_recommended=True,
        findings=[],
        fallback_actions=["fallback_reanalyze"],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.7,
    )
    rejected = QualityGateDecision(
        action=QualityGateAction.BLOCK_PUBLISH,
        review_status="blocked",
        publish_allowed=False,
        findings=[],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.3,
    )
    monkeypatch.setattr(runner, "evaluate_quality_gate", lambda **_: primary)
    monkeypatch.setattr("apps.analysis.agents.fallback_executor.evaluate_quality_gate", lambda **_: rejected)

    summaries, outputs = _run_composite_analysis_pipeline(
        storage_root=tmp_path,
        snapshot=_make_rich_snapshot(run_id="run-rejected-fallback"),
        run_id="run-rejected-fallback",
        created_at=_CREATED_AT,
    )

    assert summaries["final_report"]["output_mode"] == "observe"
    assert summaries["final_report"]["publish_allowed"] is False
    assert outputs["gold_runtime_summary"]["accepted_outputs"] == {}
    assert outputs["observe_outputs"]["final_report_paths"] == summaries["final_report"]["paths"]
    card = outputs["strategy_card"]
    assert card.bias.value == "neutral"
    assert "Observe and wait" in card.scenario_summary
    assert any("QualityGate passes" in item for item in card.trigger_conditions)
    assert any("publish_allowed is false" in item for item in card.invalid_conditions)
    assert any("observe_wait" in item for item in card.watchlist)
    assert outputs["gold_runtime_summary"]["executed_agents"] == ["report_render_agent"]


def test_composite_analysis_pipeline_renderer_failure_preserves_analysis_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.worker.runner import _run_composite_analysis_pipeline

    overview_path = (
        tmp_path / "analysis" / "gold_mainlines" / _TRADE_DATE / "run-render-fails" / "gold_macro_overview.json"
    )
    overview_path.parent.mkdir(parents=True)
    overview_path.write_text('{"status":"partial"}\n', encoding="utf-8")

    def fail_strategy_card(**_: object) -> dict:
        raise RuntimeError("strategy renderer failed")

    monkeypatch.setattr(
        "apps.worker.composite_analysis_pipeline.write_strategy_card",
        fail_strategy_card,
    )

    with pytest.raises(RuntimeError, match="strategy renderer failed"):
        _run_composite_analysis_pipeline(
            storage_root=tmp_path,
            snapshot=_make_rich_snapshot(run_id="run-render-fails"),
            run_id="run-render-fails",
            created_at=_CREATED_AT,
        )

    assert overview_path.read_text(encoding="utf-8") == '{"status":"partial"}\n'
    assert not (overview_path.parent / "agent_outputs" / "report_render_output.json").exists()


# ═══════════════════════════════════════════════════════════════════════
# Full runner integration tests (with DB + mocked pipelines)
# ═══════════════════════════════════════════════════════════════════════


def test_run_premarket_with_composite_analysis_writes_all_artifacts(tmp_path: Path) -> None:
    """Full premarket run with mocked steps should produce composite analysis outputs."""
    from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision

    db = _make_db_session(tmp_path)
    ensure_execution_tables(db)
    task = _make_task_with_steps(
        db,
        [
            "macro_collect",
            "macro_feature",
            "report_render",
            "cme_download",
            "cme_parse",
            "cme_ingest",
            "option_wall",
        ],
    )

    def mock_cme_step(step_name, state, **kwargs):
        if step_name == "option_wall":
            state.snapshot_dict = {
                "trade_date": _TRADE_DATE,
                "wall_scores": [{"strike": 3300, "wall_score": 0.82, "wall_type": "put", "side": "support"}],
                "support_resistance": {
                    "support": [{"strike": 3250, "score": 0.7}],
                    "resistance": [{"strike": 3400, "score": 0.6}],
                },
                "intent": {"type": "supportive", "score": 0.65},
                "gex": {
                    "netgex_aggregate": {"gamma_zero": {"price": 3350}},
                    "by_expiry": {
                        "2026-06": {
                            "summary": {"net_gex": 2500, "dominant_side": "positive"},
                            "iv_skew": {"risk_reversal_25d": 0.15},
                        }
                    },
                },
                "walls": {"block_pnt_walls": [{"strike": 3320, "block": 120, "pnt": 80}]},
                "data_source": {
                    "status": "FINAL",
                    "input_snapshot_ids": {"raw_file_sha256": "abc123"},
                    "expiries": ["2026-06", "2026-07"],
                },
                "data_quality": {"categories": {"prelim_data": 0}, "warnings": []},
            }
        return {"step": step_name, "status": "success"}

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                    "T10YIE": {"value": 2.15, "change_1w": -0.03, "unit": "percent"},
                    "RRPONTSYD": {"value": 180.5, "change_1w": -12.3, "unit": "billions_usd"},
                    "TGA": {"value": 720.1, "change_1w": 45.2, "unit": "billions_usd"},
                    "SOFR": {"value": 4.33, "change_1w": 0.0, "unit": "percent"},
                    "EFFR": {"value": 4.33, "unit": "percent"},
                    "IORB": {"value": 4.40, "unit": "percent"},
                },
                "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            }
        return {"step": step_name, "status": "success"}

    pass_decision = QualityGateDecision(
        action=QualityGateAction.PASS,
        review_status="pass",
        publish_allowed=True,
        findings=[],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.68,
    )
    with (
        patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        patch("apps.worker.runner.evaluate_quality_gate", return_value=pass_decision),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success

    # ── Verify composite analysis artifacts exist ──
    run_id = str(task.id)
    base = tmp_path / "outputs"

    # Final report
    report_path = base / "final_report" / "XAUUSD" / _TRADE_DATE / run_id / "final_report.md"
    assert report_path.exists(), f"Missing: {report_path}"
    report = report_path.read_text(encoding="utf-8")
    assert "# XAUUSD 相关报告" in report

    # Strategy card may use build_strategy_card's extracted/fallback date.
    sc_json_candidates = list(base.glob(f"strategy_card/XAUUSD/*/{run_id}/strategy_card.json"))
    sc_md_candidates = list(base.glob(f"strategy_card/XAUUSD/*/{run_id}/strategy_card.md"))
    report_agent_path = (
        tmp_path / "analysis" / "gold_mainlines" / _TRADE_DATE / run_id / "agent_outputs" / "report_render_output.json"
    )
    assert len(sc_json_candidates) == 1, f"Expected one strategy_card.json for {run_id}"
    assert len(sc_md_candidates) == 1, f"Expected one strategy_card.md for {run_id}"
    assert report_agent_path.exists()

    # ── Verify step summaries include composite analysis steps ──
    summaries_candidates = list(base.glob(f"run/*/{run_id}/step_summaries.json"))
    assert len(summaries_candidates) == 1, f"Expected one step_summaries.json for {run_id}"
    summaries = json.loads(summaries_candidates[0].read_text(encoding="utf-8"))
    assert "domain_agents" in summaries["steps"]
    assert "final_report" in summaries["steps"]

    support_artifact_paths = {
        row.file_path for row in db.query(RunArtifact).filter(RunArtifact.run_id == task.id).all()
    }
    assert any(path.endswith("premarket_snapshot.json") for path in support_artifact_paths)
    assert any(path.endswith("step_summaries.json") for path in support_artifact_paths)
    assert any(path.endswith("run_provenance.json") for path in support_artifact_paths)
    assert "strategy_card" in summaries["steps"]

    run_artifacts = db.query(RunArtifact).filter(RunArtifact.run_id == task.id).all()
    artifacts_by_path = {artifact.file_path: artifact for artifact in run_artifacts}
    assert str(report_path) in artifacts_by_path
    assert str(sc_json_candidates[0]) in artifacts_by_path
    assert str(sc_md_candidates[0]) in artifacts_by_path
    assert str(report_agent_path) in artifacts_by_path
    report_artifact = artifacts_by_path[str(report_path)]
    strategy_card_json_artifact = artifacts_by_path[str(sc_json_candidates[0])]
    strategy_card_md_artifact = artifacts_by_path[str(sc_md_candidates[0])]
    assert report_artifact.content_type == "text/markdown"
    assert report_artifact.byte_size == report_path.stat().st_size
    assert strategy_card_json_artifact.content_type == "application/json"
    assert strategy_card_json_artifact.byte_size == sc_json_candidates[0].stat().st_size
    assert strategy_card_md_artifact.content_type == "text/markdown"
    assert strategy_card_md_artifact.byte_size == sc_md_candidates[0].stat().st_size
    assert any(artifact.artifact_type == "analysis_md" for artifact in run_artifacts)


def test_run_premarket_with_composite_analysis_registers_report_registry_entries(tmp_path: Path) -> None:
    """Full premarket run should register final report + strategy card into report registry."""
    from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision

    db = _make_db_session(tmp_path)
    ensure_execution_tables(db)
    ensure_report_tables(db)
    task = _make_task_with_steps(
        db,
        [
            "macro_collect",
            "macro_feature",
            "report_render",
            "cme_download",
            "cme_parse",
            "cme_ingest",
            "option_wall",
        ],
    )

    def mock_cme_step(step_name, state, **kwargs):
        if step_name == "option_wall":
            state.snapshot_dict = {
                "trade_date": _TRADE_DATE,
                "wall_scores": [{"strike": 3300, "wall_score": 0.82, "wall_type": "put", "side": "support"}],
                "support_resistance": {
                    "support": [{"strike": 3250, "score": 0.7}],
                    "resistance": [{"strike": 3400, "score": 0.6}],
                },
                "intent": {"type": "supportive", "score": 0.65},
                "gex": {
                    "netgex_aggregate": {"gamma_zero": {"price": 3350}},
                    "by_expiry": {
                        "2026-06": {
                            "summary": {"net_gex": 2500, "dominant_side": "positive"},
                            "iv_skew": {"risk_reversal_25d": 0.15},
                        }
                    },
                },
                "walls": {"block_pnt_walls": [{"strike": 3320, "block": 120, "pnt": 80}]},
                "data_source": {
                    "status": "FINAL",
                    "input_snapshot_ids": {"raw_file_sha256": "abc123"},
                    "expiries": ["2026-06", "2026-07"],
                },
                "data_quality": {"categories": {"prelim_data": 0}, "warnings": []},
            }
        return {"step": step_name, "status": "success"}

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                    "T10YIE": {"value": 2.15, "change_1w": -0.03, "unit": "percent"},
                    "RRPONTSYD": {"value": 180.5, "change_1w": -12.3, "unit": "billions_usd"},
                    "TGA": {"value": 720.1, "change_1w": 45.2, "unit": "billions_usd"},
                    "SOFR": {"value": 4.33, "change_1w": 0.0, "unit": "percent"},
                    "EFFR": {"value": 4.33, "unit": "percent"},
                    "IORB": {"value": 4.40, "unit": "percent"},
                },
                "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            }
        return {"step": step_name, "status": "success"}

    pass_decision = QualityGateDecision(
        action=QualityGateAction.PASS,
        review_status="pass",
        publish_allowed=True,
        findings=[],
        source_ref_count=1,
        evidence_item_count=1,
        max_confidence=0.68,
    )
    with (
        patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        patch("apps.worker.runner.evaluate_quality_gate", return_value=pass_decision),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success

    run_id = str(task.id)
    final_report_id = f"final_report:{run_id}"
    strategy_card_id = f"strategy_card:{run_id}"

    report_items = {row.report_id: row for row in db.query(ReportItem).filter(ReportItem.run_id == run_id).all()}
    assert set(report_items) >= {final_report_id, strategy_card_id}

    final_report_item = report_items[final_report_id]
    strategy_card_item = report_items[strategy_card_id]
    assert final_report_item.family == "final_report_markdown"
    assert strategy_card_item.family == "strategy_card"
    assert final_report_item.trade_date.isoformat() == _TRADE_DATE
    assert strategy_card_item.trade_date.isoformat() == _TRADE_DATE
    assert final_report_item.snapshot_id == strategy_card_item.snapshot_id
    assert final_report_item.source_refs
    assert strategy_card_item.source_refs
    assert final_report_item.report_metadata["publish_allowed"] is True
    assert final_report_item.report_metadata["output_mode"] == "accepted"

    report_artifacts = (
        db.query(ReportArtifact).filter(ReportArtifact.report_id.in_([final_report_id, strategy_card_id])).all()
    )
    artifacts_by_report = {}
    for artifact in report_artifacts:
        artifacts_by_report.setdefault(artifact.report_id, []).append(artifact)
    assert {artifact.artifact_type for artifact in artifacts_by_report[final_report_id]} == {
        "analysis_md",
        "structured_json",
    }
    assert {artifact.artifact_type for artifact in artifacts_by_report[strategy_card_id]} == {
        "analysis_md",
        "structured_json",
    }

    primary_artifacts = {artifact.report_id: artifact for artifact in report_artifacts if artifact.is_primary}
    assert primary_artifacts[final_report_id].content_type == "text/markdown"
    assert primary_artifacts[strategy_card_id].content_type == "application/json"

    for artifact in report_artifacts:
        assert artifact.storage_backend == "local_fs"
        assert artifact.sha256
        assert artifact.byte_size is not None
        assert artifact.generated_at is not None
        assert artifact.source_refs


def test_report_registry_sink_refuses_observation_outputs() -> None:
    from apps.worker.report_registry_sink import register_composite_report_registry_entries

    class ObservationDecision:
        publish_allowed = False

    register_composite_report_registry_entries(
        object(),
        run_id="observe-run",
        composite_outputs={"agent_loop_decision": ObservationDecision()},
        analysis_snapshot={"snapshot_id": "observe-snapshot"},
    )


def test_run_premarket_blocks_composite_analysis_when_pre_analysis_gate_blocks(tmp_path: Path) -> None:
    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(db, ["macro_collect", "macro_feature", "report_render"])
    gate_path = tmp_path / "orchestration" / _TRADE_DATE / "pre_analysis_gate.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(
        json.dumps(
            {
                "trade_date": _TRADE_DATE,
                "decision": "block",
                "status": "blocked",
                "can_run_full_analysis": False,
                "blocked_outputs": ["full analysis", "knowledge distillation"],
                "source_ref": f"monitoring/{_TRADE_DATE}/downstream_readiness.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {"DXY": {"value": 101.5, "unit": "index"}},
                "source_refs": [{"source": "fred", "symbol": "DXY"}],
            }
        return {"step": step_name, "status": "success"}

    def fail_if_composite_runs(*args, **kwargs):
        raise AssertionError("composite analysis should be blocked by pre_analysis_gate")

    with (
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        patch("apps.worker.runner._run_composite_analysis_pipeline", side_effect=fail_if_composite_runs),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.partial_success
    run_id = str(task.id)
    assert not (tmp_path / "outputs" / "final_report" / "XAUUSD" / _TRADE_DATE / run_id / "final_report.md").exists()
    summaries_candidates = list((tmp_path / "outputs").glob(f"run/*/{run_id}/step_summaries.json"))
    assert len(summaries_candidates) == 1
    summaries = json.loads(summaries_candidates[0].read_text(encoding="utf-8"))
    assert summaries["steps"]["pre_analysis_gate"]["decision"] == "block"
    assert summaries["steps"]["composite_analysis_pipeline"]["status"] == "blocked"
    assert summaries["steps"]["composite_analysis_pipeline"]["blocked_outputs"] == [
        "full analysis",
        "knowledge distillation",
    ]


def test_run_premarket_does_not_start_composite_agents_when_readiness_is_missing(tmp_path: Path) -> None:
    from dagster_finance.ops.premarket_gate import evaluate_premarket_readiness

    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(db, ["macro_collect", "macro_feature", "report_render"])

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {"DXY": {"value": 101.5, "unit": "index"}},
                "source_refs": [{"source": "fred", "symbol": "DXY"}],
            }
        return {"step": step_name, "status": "success"}

    def fail_if_composite_runs(*args, **kwargs):
        raise AssertionError("composite agents must not start without downstream readiness")

    with (
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        patch("apps.worker.runner._run_composite_analysis_pipeline", side_effect=fail_if_composite_runs),
        patch("apps.worker.runner._evaluate_premarket_readiness", side_effect=evaluate_premarket_readiness),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.partial_success
    run_id = str(task.id)
    summaries_candidates = list((tmp_path / "outputs").glob(f"run/*/{run_id}/step_summaries.json"))
    assert len(summaries_candidates) == 1
    summaries = json.loads(summaries_candidates[0].read_text(encoding="utf-8"))
    assert summaries["steps"]["pre_analysis_gate"]["reason_code"] == "downstream_readiness_missing"
    assert summaries["steps"]["composite_analysis_pipeline"]["status"] == "blocked"


def test_run_premarket_composite_analysis_not_triggered_when_snapshot_fails(tmp_path: Path) -> None:
    """When analysis snapshot fails, composite analysis should NOT run (no snapshot to consume)."""
    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(db, ["macro_collect", "macro_feature", "report_render"])

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            # Return a snapshot that will cause build_analysis_snapshot to succeed
            # but then we need the _persist_analysis_snapshot call to fail...
            # Actually, let's test composite analysis is skipped when the snapshot build fails.
            # The easiest way: make state.snapshot_dict invalid so build raises.
            state.snapshot_dict = {"as_of": _TRADE_DATE}
        return {"step": step_name, "status": "success"}

    # Force _persist_analysis_snapshot to raise
    def mock_persist(*args, **kwargs):
        raise RuntimeError("simulated snapshot persistence failure")

    with (
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        patch("apps.worker.runner._persist_analysis_snapshot", side_effect=mock_persist),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    # Should be partial_success — steps succeeded but snapshot failed
    assert result == TaskStatus.partial_success

    # composite analysis artifacts must NOT exist
    run_id = str(task.id)
    base = tmp_path / "outputs"
    report_path = base / "final_report" / "XAUUSD" / _TRADE_DATE / run_id / "final_report.md"
    assert not report_path.exists(), "composite analysis should not have run when snapshot failed"

    # Step summaries should record the analysis_snapshot failure.
    summaries_candidates = list(base.glob(f"run/*/{run_id}/step_summaries.json"))
    assert len(summaries_candidates) == 1, f"Expected one step_summaries.json for {run_id}"
    summaries = json.loads(summaries_candidates[0].read_text(encoding="utf-8"))
    assert summaries["steps"]["analysis_snapshot"]["status"] == "failed"
    assert "domain_agents" not in summaries["steps"]


def test_run_premarket_composite_analysis_failure_recorded_in_summaries(tmp_path: Path) -> None:
    """When composite analysis pipeline itself fails, the failure is recorded without losing prior steps."""
    db = _make_db_session(tmp_path)
    task = _make_task_with_steps(db, ["macro_collect", "macro_feature", "report_render"])

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": _TRADE_DATE,
                "indicators": {
                    "DXY": {"value": 101.50, "change_1w": -0.80, "unit": "index"},
                    "DGS10": {"value": 4.42, "change_1w": -0.12, "unit": "percent"},
                    "T10YIE": {"value": 2.15, "change_1w": -0.03, "unit": "percent"},
                    "RRPONTSYD": {"value": 180.5, "change_1w": -12.3, "unit": "billions_usd"},
                    "TGA": {"value": 720.1, "change_1w": 45.2, "unit": "billions_usd"},
                },
                "source_refs": [],
            }
        return {"step": step_name, "status": "success"}

    # Force composite analysis pipeline to fail
    def mock_composite_analysis_fail(*args, **kwargs):
        raise RuntimeError("simulated composite analysis agent pipeline failure")

    with (
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        patch("apps.worker.runner._run_composite_analysis_pipeline", side_effect=mock_composite_analysis_fail),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    # composite analysis failure → partial_success (steps succeeded, composite analysis failed)
    assert result == TaskStatus.partial_success

    run_id = str(task.id)
    base = tmp_path / "outputs"
    summaries_candidates = list(base.glob(f"run/*/{run_id}/step_summaries.json"))
    assert len(summaries_candidates) == 1, f"Expected one step_summaries.json for {run_id}"
    summaries = json.loads(summaries_candidates[0].read_text(encoding="utf-8"))
    assert summaries["steps"]["composite_analysis_pipeline"]["status"] == "failed"
    assert "partial_summary" in summaries["steps"]["composite_analysis_pipeline"]
