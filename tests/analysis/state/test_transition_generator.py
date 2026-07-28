from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.analysis.agents.schemas import AcceptedStateConclusion, AgentBias
from apps.analysis.context_bundle import assemble_context_bundle
from apps.analysis.state.transition_generator import (
    generate_scoped_transition_candidate,
    generate_scoped_transition_candidate_for_conclusion,
)


NOW = datetime(2026, 7, 28, 8, tzinfo=UTC)
REF = {"source": "fred", "snapshot_id": "macro-current"}


def _bundle(*, with_evidence: bool = True):
    evidence = []
    if with_evidence:
        evidence.append(
            {
                "source": "fred",
                "evidence_id": "dxy-current",
                "business_time": NOW,
                "ingested_at": NOW + timedelta(minutes=1),
                "session": "daily_close",
                "payload": {
                    "evidence_type": "macro_metric",
                    "asset": "XAUUSD",
                    "source_quality": "official",
                    "metric": "dxy",
                    "current_value": 101.0,
                    "previous_value": 100.0,
                    "unit": "index",
                },
                "source_ref": REF,
            }
        )
    return assemble_context_bundle(
        run_id="run-conclusion",
        asset="XAUUSD",
        state_scope="daily_close",
        canonical_state_id="state-previous",
        canonical_state={
            "schema_version": "1.1",
            "state_scope": "daily_close",
            "state_machine_version": "analysis_state.v1.1",
            "session": "daily_close",
            "trade_date": "2026-07-27",
            "asset": "XAUUSD",
            "as_of": "2026-07-27T08:00:00+00:00",
            "market_stage": "direction_decision",
            "core_thesis": "Await confirmation.",
            "net_bias": "mixed",
            "dominant_drivers": [],
            "key_levels": [
                {
                    "value": 4000.0,
                    "role": "resistance",
                    "source": "canonical_market",
                    "meaning": "breakout threshold",
                }
            ],
            "scenario_states": [
                {
                    "scenario_id": "breakout",
                    "condition": "close above resistance",
                    "status": "pending",
                }
            ],
            "unresolved_items": [],
            "invalidation_conditions": [],
            "evidence_cursors": {},
            "input_snapshot_ids": {},
            "source_refs": [],
        },
        evidence=evidence,
        evidence_cursors={},
        cutoff_at=NOW + timedelta(minutes=2),
        assembled_at=NOW + timedelta(minutes=3),
        expected_session="daily_close",
    )


def _conclusion() -> AcceptedStateConclusion:
    return AcceptedStateConclusion(
        direction=AgentBias.MIXED,
        direction_tilt="bullish",
        state_bias="mixed_bullish",
        market_stage="macro_verification",
        core_thesis="Dollar strength is material, but gold still holds its breakout threshold.",
        dominant_drivers=[
            {
                "driver_id": "real_rates_usd",
                "label": "Real rates and USD",
                "rank": 1,
                "score": 0.82,
                "direction": "headwind",
                "coverage_status": "covered",
            }
        ],
    )


def _candidate(*, thesis: str | None = None, ref: dict | None = None) -> dict:
    conclusion = _conclusion()
    evidence_ref = ref or REF
    changes = [
        {
            "target": target,
            "action": "maintain" if target == "dominant_drivers" else "pending",
            "reason": "The retained DXY evidence is the only available update.",
            "evidence_refs": [evidence_ref],
        }
        for target in ("market_stage", "core_thesis", "net_bias", "dominant_drivers")
    ]
    return {
        "schema_version": "analysis_transition_candidate.v2",
        "previous_state_id": "state-previous",
        "summary": "Align typed state semantics while keeping unsupported implications pending.",
        "changes": changes,
        "state_patch": {
            "market_stage": conclusion.market_stage,
            "core_thesis": thesis or conclusion.core_thesis,
            "net_bias": conclusion.state_bias,
            "dominant_drivers": conclusion.dominant_drivers,
        },
        "evidence_refs": [evidence_ref],
    }


def test_conclusion_targeted_generator_binds_exact_patch_and_complete_nested_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_chat_sync(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content=json.dumps(_candidate()))

    monkeypatch.delenv("FINANCE_AGENT_SKIP_LIVE_LLM", raising=False)
    monkeypatch.setattr("apps.llm.gateway.chat_sync", fake_chat_sync)

    result = generate_scoped_transition_candidate_for_conclusion(
        _bundle(), _conclusion()
    )

    assert result.candidate.state_patch.explicit_payload() == {
        "market_stage": _conclusion().market_stage,
        "core_thesis": _conclusion().core_thesis,
        "net_bias": _conclusion().state_bias,
        "dominant_drivers": _conclusion().dominant_drivers,
    }
    prompt = captured["messages"][1]["content"]
    assert all(
        field in prompt
        for field in (
            "driver_id",
            "coverage_status",
            "KeyLevel",
            "meaning",
            "ScenarioState",
            "scenario_id",
            "active|pending|confirmed|invalidated",
        )
    )
    assert "action 必须使用 maintain 或 pending" in prompt
    assert "严禁在输出顶层或 state_patch 中输出 state_scope" in prompt
    assert "输出顶层必须且只能包含" in prompt
    audit = captured["audit_context"]["input_payload"]
    assert audit["context_bundle_hash"] == result.context_bundle_hash
    assert len(audit["accepted_state_conclusion_hash"]) == 64


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_candidate(thesis="LLM rewrote the accepted thesis."), "does not match accepted"),
        (
            _candidate(ref={"source": "invented", "snapshot_id": "outside-bundle"}),
            "outside the Bundle",
        ),
    ],
)
def test_conclusion_targeted_generator_rejects_semantic_or_evidence_drift(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
    message: str,
) -> None:
    monkeypatch.delenv("FINANCE_AGENT_SKIP_LIVE_LLM", raising=False)
    monkeypatch.setattr(
        "apps.llm.gateway.chat_sync",
        lambda **_kwargs: SimpleNamespace(content=json.dumps(payload)),
    )

    with pytest.raises(ValueError, match=message):
        generate_scoped_transition_candidate_for_conclusion(_bundle(), _conclusion())


def test_conclusion_targeted_generator_fails_closed_without_retained_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_chat_sync(**_kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(content=json.dumps(_candidate()))

    monkeypatch.setattr("apps.llm.gateway.chat_sync", fake_chat_sync)

    with pytest.raises(ValueError, match="requires retained Bundle evidence"):
        generate_scoped_transition_candidate_for_conclusion(
            _bundle(with_evidence=False), _conclusion()
        )
    assert called is False


def test_existing_scoped_generator_entry_remains_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_payload = {
        "schema_version": "analysis_transition_candidate.v2",
        "previous_state_id": "state-previous",
        "summary": "Keep current state pending on retained DXY evidence.",
        "changes": [
            {
                "target": "core_thesis",
                "action": "pending",
                "reason": "One DXY observation is insufficient to rewrite the thesis.",
                "evidence_refs": [REF],
            }
        ],
        "state_patch": {},
        "evidence_refs": [REF],
    }
    monkeypatch.delenv("FINANCE_AGENT_SKIP_LIVE_LLM", raising=False)
    monkeypatch.setattr(
        "apps.llm.gateway.chat_sync",
        lambda **_kwargs: SimpleNamespace(content=json.dumps(legacy_payload)),
    )

    result = generate_scoped_transition_candidate(_bundle())

    assert result.candidate.changes[0].action.value == "pending"
    assert result.candidate.state_patch.explicit_payload() == {}
