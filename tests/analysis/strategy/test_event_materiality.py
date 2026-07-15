from __future__ import annotations

from copy import deepcopy

import pytest

from apps.analysis.strategy.event_materiality import score_event_materiality


STRONG_COMPONENTS = {
    "source_reliability": 0.95,
    "event_importance": 0.90,
    "surprise": 0.85,
    "gold_relevance": 0.90,
    "market_reaction_strength": 0.85,
    "reaction_persistence": 0.80,
}
EVIDENCE = [{"kind": "release", "id": "fed-2026-07-18"}, {"kind": "market_reaction", "window": "30m"}]
SOURCE_REFS = [{"source": "federal_reserve", "id": "release"}, {"source": "cme", "id": "xauusd-5m"}]


def _score(**overrides: object) -> dict:
    values: dict[str, object] = {
        **STRONG_COMPONENTS,
        "official_source": True,
        "independent_source_count": 2,
        "evidence": EVIDENCE,
        "source_refs": SOURCE_REFS,
    }
    values.update(overrides)
    return score_event_materiality(**values)  # type: ignore[arg-type]


def test_strong_official_multi_source_event_is_recompute_eligible() -> None:
    result = _score()

    assert result["score"] == pytest.approx(88.5)
    assert result["band"] == "critical"
    assert result["recompute_eligible"] is True
    assert result["eligibility_gate"]["failures"] == []
    assert result["reasons"] == ["eligible:confirmed_material_event"]


def test_single_source_unconfirmed_news_is_not_eligible() -> None:
    result = _score(
        official_source=False,
        independent_source_count=1,
        source_refs=[{"source": "social_news", "id": "one-post"}],
    )

    assert result["score"] == pytest.approx(88.5)
    assert result["recompute_eligible"] is False
    assert "gate_failed:official_source_required" in result["reasons"]
    assert "gate_failed:multi_source_confirmation_required" in result["reasons"]
    assert "gate_failed:multi_source_lineage_required" in result["reasons"]


def test_missing_market_reaction_is_explicitly_degraded() -> None:
    result = _score(market_reaction_strength=None)

    component = result["components"]["market_reaction_strength"]
    assert component["value"] is None
    assert component["contribution"] == 0.0
    assert component["status"] == "missing"
    assert result["band"] == "insufficient"
    assert result["coverage"]["missing_components"] == ["market_reaction_strength"]
    assert result["recompute_eligible"] is False


def test_low_reaction_persistence_reduces_score_and_blocks_recompute() -> None:
    strong = _score()
    low_persistence = _score(reaction_persistence=0.20)

    assert low_persistence["score"] < strong["score"]
    assert low_persistence["components"]["reaction_persistence"]["contribution"] == pytest.approx(2.0)
    assert low_persistence["recompute_eligible"] is False
    assert "gate_failed:reaction_persistence_below_threshold" in low_persistence["reasons"]


def test_component_boundaries_are_clamped_and_score_stays_in_range() -> None:
    result = _score(source_reliability=2.0, event_importance=-1.0)

    assert result["components"]["source_reliability"] == {
        "raw": 2.0,
        "value": 1.0,
        "range": [0.0, 1.0],
        "weight": 0.20,
        "contribution": 20.0,
        "status": "clamped",
    }
    assert result["components"]["event_importance"]["value"] == 0.0
    assert result["components"]["event_importance"]["status"] == "clamped"
    assert 0.0 <= result["score"] <= 100.0
    assert "component_clamped:source_reliability" in result["reasons"]
    assert "component_clamped:event_importance" in result["reasons"]


@pytest.mark.parametrize("missing", list(STRONG_COMPONENTS))
def test_each_missing_component_remains_missing_and_blocks_recompute(missing: str) -> None:
    result = _score(**{missing: None})

    assert result["components"][missing]["value"] is None
    assert result["band"] == "insufficient"
    assert result["recompute_eligible"] is False
    assert f"missing_component:{missing}" in result["reasons"]


def test_identical_inputs_are_deterministic() -> None:
    first = _score()
    second = _score()

    assert first == second


def test_evidence_and_source_lineage_are_preserved_without_aliasing() -> None:
    evidence = deepcopy(EVIDENCE)
    source_refs = deepcopy(SOURCE_REFS)
    result = _score(evidence=evidence, source_refs=source_refs)

    assert result["evidence"] == evidence
    assert result["source_refs"] == source_refs
    assert result["evidence"] is not evidence
    assert result["source_refs"] is not source_refs


def test_duplicate_source_lineage_does_not_count_as_multi_source_confirmation() -> None:
    repeated_ref = {"source": "federal_reserve", "id": "release"}
    result = _score(source_refs=[repeated_ref, dict(repeated_ref)])

    assert result["recompute_eligible"] is False
    assert "gate_failed:multi_source_lineage_required" in result["reasons"]


def test_non_finite_values_are_missing_not_fabricated() -> None:
    result = _score(surprise=float("nan"))

    assert result["components"]["surprise"]["value"] is None
    assert result["components"]["surprise"]["contribution"] == 0.0
    assert result["band"] == "insufficient"
    assert result["recompute_eligible"] is False
