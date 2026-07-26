from __future__ import annotations

from datetime import timedelta

import pytest

from apps.analysis.context_bundle import (
    bind_projection_to_agent_output,
    project_context_bundle,
    validate_consumer_projection,
)
from tests.analysis.test_context_bundle import NOW, _bundle, _evidence


def _projection_bundle():
    macro = _evidence("macro", "shared-id", business_time=NOW, ingested_at=NOW)
    macro["payload"] = {
        "evidence_type": "macro_metric",
        "asset": "XAUUSD",
        "source_quality": "official",
        "metric": "dxy",
        "current_value": 101.0,
        "previous_value": 100.0,
        "unit": "index",
    }
    technical = _evidence("technical", "shared-id", business_time=NOW, ingested_at=NOW + timedelta(minutes=1))
    technical["payload"] = {
        "evidence_type": "key_level_event",
        "asset": "XAUUSD",
        "source_quality": "official",
        "level_id": "support-1",
        "level_role": "support",
        "level_value": 4000.0,
        "observed_value": 4001.0,
        "event": "touch",
        "confirmation_status": "confirmed",
    }
    options = _evidence("options", "options-1", business_time=NOW, ingested_at=NOW + timedelta(minutes=2))
    options["payload"] = {
        "evidence_type": "options_regime",
        "asset": "XAUUSD",
        "source_quality": "official",
        "regime_id": "gamma-1",
        "event": "wall_migration",
        "change_pct": 10.0,
        "confirmation_status": "confirmed",
    }
    material_event = _evidence("news", "event-1", business_time=NOW, ingested_at=NOW + timedelta(minutes=3))
    return _bundle(evidence=[macro, technical, options, material_event])


@pytest.mark.parametrize(
    "consumer",
    [
        "macro",
        "options",
        "risk",
        "technical",
        "positioning",
        "news",
        "market_odds",
        "fact_review",
        "coordinator",
    ],
)
def test_all_consumers_receive_a_valid_typed_projection(consumer: str) -> None:
    projection = project_context_bundle(_projection_bundle(), consumer=consumer)  # type: ignore[arg-type]

    assert validate_consumer_projection(projection, consumer).consumer == consumer
    assert projection.identity_payload.state_scope == "daily_close"
    assert projection.decision_id == projection.decision.decision_id
    assert projection.selection_trace
    assert projection.freshness_sla_seconds is not None
    assert projection.canonical_state["state_scope"] == "daily_close"


def test_projection_filters_by_consumer_and_keeps_source_aware_duplicate_ids() -> None:
    projection = project_context_bundle(_projection_bundle(), consumer="risk")

    assert {item["payload"]["evidence_type"] for item in projection.retained_evidence} == {
        "macro_metric",
        "key_level_event",
        "options_regime",
        "material_event",
    }
    assert {(ref["source"], ref["evidence_id"]) for ref in projection.retained_source_refs} >= {
        ("macro", "shared-id"),
        ("technical", "shared-id"),
    }
    assert projection.identity_payload.source_refs == projection.retained_source_refs


@pytest.mark.parametrize(
    ("consumer", "expected_types"),
    [
        ("macro", {"macro_metric", "material_event"}),
        ("options", {"options_regime", "key_level_event"}),
        ("risk", {"macro_metric", "key_level_event", "options_regime", "material_event"}),
        ("technical", {"key_level_event"}),
        ("positioning", {"material_event"}),
        ("news", {"material_event"}),
        ("market_odds", {"material_event"}),
        ("fact_review", {"macro_metric", "key_level_event", "options_regime", "material_event"}),
        ("coordinator", {"macro_metric", "key_level_event", "options_regime", "material_event"}),
    ],
)
def test_projection_consumer_allowlist_matches_runtime_contract(consumer: str, expected_types: set[str]) -> None:
    projection = project_context_bundle(_projection_bundle(), consumer=consumer)  # type: ignore[arg-type]

    assert {item["payload"]["evidence_type"] for item in projection.retained_evidence} == expected_types


def test_projection_revalidation_rejects_nested_tamper_fake_identity_and_wrong_consumer() -> None:
    projection = project_context_bundle(_projection_bundle(), consumer="macro")
    tampered = projection.model_dump(mode="json")
    tampered["canonical_state"]["asset"] = "GC"
    with pytest.raises(ValueError, match="canonical state"):
        validate_consumer_projection(tampered, "macro")

    fake_identity = projection.model_dump(mode="json")
    fake_identity["identity_payload"]["bundle_id"] = "fake-bundle"
    with pytest.raises(ValueError, match="projection_hash"):
        validate_consumer_projection(fake_identity, "macro")

    with pytest.raises(ValueError, match="expected consumer"):
        validate_consumer_projection(projection, "options")


def test_projection_binding_carries_exact_identity_without_claiming_consumption() -> None:
    projection = project_context_bundle(_projection_bundle(), consumer="technical")
    bound = bind_projection_to_agent_output(
        projection,
        {"input_snapshot_ids": {}, "input_payload": {}, "source_refs": []},
        expected_consumer="technical",
    )

    input_ids = bound["input_snapshot_ids"]
    assert input_ids["context_bundle_id"] == projection.identity_payload.bundle_id
    assert input_ids["context_bundle_hash"] == projection.identity_payload.content_hash
    assert input_ids["canonical_state_id"] == projection.identity_payload.canonical_state_id
    assert input_ids["state_scope"] == projection.identity_payload.state_scope
    assert input_ids["evidence_delta_decision_id"] == projection.decision_id
    assert input_ids["context_bundle_run_id"] == projection.identity_payload.run_id
    assert input_ids["retained_evidence_ids"] == [{"source": "technical", "evidence_id": "shared-id"}]
    assert bound["input_payload"]["context_bundle_identity"] == projection.identity_payload.model_dump(mode="json")
    assert bound["source_refs"][0]["identity"] == projection.identity_payload.model_dump(mode="json")
    assert "consumed" not in bound["input_payload"]
