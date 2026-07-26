from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import pytest

from apps.analysis.agents import macro_liquidity
from apps.analysis.agents.cme_options import analyze_cme_options
from apps.analysis.agents.coordinator import coordinate_agent_outputs
from apps.analysis.agents.fact_review import build_runtime_fact_review_agent_output
from apps.analysis.agents.macro_liquidity import (
    analyze_macro_liquidity,
    build_macro_liquidity_structured_payload,
)
from apps.analysis.agents.market_odds import analyze_market_odds
from apps.analysis.agents.news import analyze_news
from apps.analysis.agents.positioning import analyze_positioning
from apps.analysis.agents.risk import analyze_risk
from apps.analysis.agents.technical import analyze_technical
from apps.analysis.context_bundle import project_context_bundle
from tests.analysis.test_context_bundle import NOW as BUNDLE_NOW
from tests.analysis.test_context_bundle import _bundle, _evidence
from tests.analysis.test_context_bundle_projection import _projection_bundle


NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)


def _projection(consumer: str):
    return project_context_bundle(_projection_bundle(), consumer=consumer)  # type: ignore[arg-type]


def _snapshot() -> dict[str, Any]:
    return {"snapshot_id": "consumer-test", "source_refs": []}


def _assert_bound(output: Any, projection: Any) -> None:
    assert output.input_snapshot_ids["context_bundle_id"] == projection.identity_payload.bundle_id
    assert output.input_snapshot_ids["context_bundle_hash"] == projection.identity_payload.content_hash
    assert output.input_snapshot_ids["canonical_state_id"] == projection.identity_payload.canonical_state_id
    assert output.input_snapshot_ids["state_scope"] == projection.identity_payload.state_scope
    assert output.input_snapshot_ids["evidence_delta_decision_id"] == projection.decision_id
    summary = output.input_payload["context_bundle_summary"]
    assert summary["decision_id"] == projection.decision_id
    assert summary["decision_action"] == projection.decision.recommended_action.value
    assert summary["retained_refs"] == projection.retained_source_refs
    assert summary["accepted_fact_count"] == len(projection.accepted_facts)
    assert output.input_payload["context_bundle_projection"] == projection.model_dump(mode="json")


@pytest.mark.parametrize(
    ("consumer", "invoke"),
    [
        (
            "macro",
            lambda projection: analyze_macro_liquidity(_snapshot(), created_at=NOW, context_projection=projection),
        ),
        ("options", lambda projection: analyze_cme_options(_snapshot(), created_at=NOW, context_projection=projection)),
        (
            "risk",
            lambda projection: analyze_risk(
                _snapshot(),
                macro_output=analyze_macro_liquidity(_snapshot(), created_at=NOW),
                options_output=analyze_cme_options(_snapshot(), created_at=NOW),
                created_at=NOW,
                context_projection=projection,
            ),
        ),
        ("technical", lambda projection: analyze_technical(_snapshot(), created_at=NOW, context_projection=projection)),
        (
            "positioning",
            lambda projection: analyze_positioning(_snapshot(), created_at=NOW, context_projection=projection),
        ),
        ("news", lambda projection: analyze_news(_snapshot(), created_at=NOW, context_projection=projection)),
        (
            "market_odds",
            lambda projection: analyze_market_odds(_snapshot(), created_at=NOW, context_projection=projection),
        ),
        (
            "fact_review",
            lambda projection: build_runtime_fact_review_agent_output(
                [analyze_macro_liquidity(_snapshot(), created_at=NOW)],
                snapshot_id="consumer-test",
                created_at=NOW,
                context_projection=projection,
            ),
        ),
        (
            "coordinator",
            lambda projection: coordinate_agent_outputs(
                _snapshot(),
                macro_output=analyze_macro_liquidity(_snapshot(), created_at=NOW),
                options_output=analyze_cme_options(_snapshot(), created_at=NOW),
                risk_output=analyze_risk(
                    _snapshot(),
                    macro_output=analyze_macro_liquidity(_snapshot(), created_at=NOW),
                    options_output=analyze_cme_options(_snapshot(), created_at=NOW),
                    created_at=NOW,
                ),
                created_at=NOW,
                context_projection=projection,
            ),
        ),
    ],
)
def test_agent_consumers_validate_and_bind_exact_projection(
    consumer: str,
    invoke: Callable[[Any], Any],
) -> None:
    projection = _projection(consumer)

    _assert_bound(invoke(projection), projection)


def test_agent_consumer_rejects_wrong_consumer_and_tamper_before_work() -> None:
    wrong = _projection("options")
    with pytest.raises(ValueError, match="expected consumer"):
        analyze_macro_liquidity(_snapshot(), context_projection=wrong)

    tampered = _projection("technical").model_dump(mode="json")
    tampered["identity_payload"]["bundle_id"] = "tampered"
    with pytest.raises(ValueError, match="projection_hash"):
        analyze_technical(_snapshot(), context_projection=tampered)


def test_macro_projection_enters_structured_prompt_payload() -> None:
    projection = _projection("macro")
    snapshot = {
        "snapshot_id": "macro-projection",
        "trade_date": "2026-07-26",
        "macro": {"status": "available", "data": {"indicators": {}}},
    }

    payload = build_macro_liquidity_structured_payload(
        snapshot,
        context_projection=projection,
    )

    assert payload["context_bundle_summary"]["decision_id"] == projection.decision_id
    assert payload["context_bundle_summary"]["retained_refs"] == projection.retained_source_refs
    assert payload["context_bundle_projection"] == projection.model_dump(mode="json")


def test_non_macro_consumer_uses_projection_content_and_manual_review_policy() -> None:
    evidence = _evidence(
        "macro",
        "dxy-unverified",
        business_time=BUNDLE_NOW,
        ingested_at=BUNDLE_NOW,
    )
    evidence["payload"] = {
        "evidence_type": "macro_metric",
        "asset": "XAUUSD",
        "source_quality": "unverified",
        "metric": "dxy",
        "current_value": 101.0,
        "previous_value": 100.0,
        "unit": "index",
    }
    projection = project_context_bundle(
        _bundle(evidence=[evidence], facts=[]),
        consumer="risk",
    )
    output = analyze_risk(
        _snapshot(),
        macro_output=analyze_macro_liquidity(_snapshot(), created_at=NOW),
        options_output=analyze_cme_options(_snapshot(), created_at=NOW),
        created_at=NOW,
        context_projection=projection,
    )

    consumed = output.input_payload["context_bundle_projection"]
    assert consumed["retained_evidence"][0]["payload"]["current_value"] == 101.0
    assert consumed["decision"]["recommended_action"] == "manual_review"
    assert output.confidence <= 0.35
    assert "ContextBundle evidence delta requires manual review." in output.risk_points
    assert projection.retained_source_refs[0] in output.evidence_refs


def test_macro_invocation_chain_carries_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    projection = _projection("macro")
    received: dict[str, Any] = {}

    def fake_invoke(snapshot: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        received["projection"] = kwargs["context_projection"]
        return {"markdown": "", "prompt_version": "test", "skipped": True}

    monkeypatch.setattr(macro_liquidity, "invoke_macro_liquidity_llm", fake_invoke)
    output = macro_liquidity.analyze_macro_liquidity(
        {
            "snapshot_id": "macro-invocation",
            "macro": {"status": "available", "data": {"indicators": {}}},
        },
        created_at=NOW,
        context_projection=projection,
    )

    assert received["projection"] == projection
    _assert_bound(output, projection)


def test_legacy_agent_call_does_not_add_context_bundle_lineage() -> None:
    output = analyze_technical(_snapshot(), created_at=NOW)

    assert "context_bundle_id" not in output.input_snapshot_ids
    assert output.input_payload is None or "context_bundle_summary" not in output.input_payload
