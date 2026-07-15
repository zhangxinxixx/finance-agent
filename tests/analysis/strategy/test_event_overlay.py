from __future__ import annotations

from copy import deepcopy

from apps.analysis.strategy.event_overlay import build_event_overlay


STRONG_EVENT = {
    "event_id": "fed-2026-07-18",
    "event_type": "fomc_statement",
    "observed_at": "2026-07-18T12:00:00+00:00",
    "source_reliability": 0.95,
    "event_importance": 0.90,
    "surprise": 0.85,
    "gold_relevance": 0.90,
    "market_reaction_strength": 0.85,
    "reaction_persistence": 0.80,
    "official_source": True,
    "independent_source_count": 2,
    "observed_reaction": {"direction": "up", "window": "30m"},
    "evidence": [{"kind": "release", "id": "fed-2026-07-18"}],
    "source_refs": [
        {"source": "federal_reserve", "id": "release"},
        {"source": "cme", "id": "xauusd-5m"},
    ],
}


def test_absent_event_is_explicitly_unavailable() -> None:
    result = build_event_overlay()

    assert result["status"] == "unavailable"
    assert result["materiality"] is None
    assert result["recompute_candidate"] is False
    assert result["reasons"] == ["event_observation_unavailable"]


def test_missing_identity_or_reaction_is_blocked_without_candidate() -> None:
    result = build_event_overlay({"event_id": "event-1", "event_type": "release"})

    assert result["status"] == "blocked"
    assert result["recompute_candidate"] is False
    assert "event_identity_required" in result["reasons"]
    assert "observed_reaction_required" in result["reasons"]


def test_gate_blocked_observation_is_not_recompute_candidate() -> None:
    event = deepcopy(STRONG_EVENT)
    event["official_source"] = False
    result = build_event_overlay(event)

    assert result["status"] == "observed"
    assert result["recompute_candidate"] is False
    assert "gate_failed:official_source_required" in result["reasons"]


def test_eligible_event_requires_identity_and_observed_reaction() -> None:
    result = build_event_overlay(STRONG_EVENT)

    assert result["status"] == "eligible"
    assert result["recompute_candidate"] is True
    assert result["materiality"]["recompute_eligible"] is True
    assert result["reasons"] == ["eligible:recompute_candidate"]


def test_observed_reaction_aliases_feed_materiality_scorer() -> None:
    event = deepcopy(STRONG_EVENT)
    event.pop("market_reaction_strength")
    event.pop("reaction_persistence")
    event["observed_reaction"] = {"strength": 0.85, "persistence": 0.80}

    result = build_event_overlay(event)

    assert result["recompute_candidate"] is True
    assert result["materiality"]["components"]["market_reaction_strength"]["value"] == 0.85
    assert result["materiality"]["components"]["reaction_persistence"]["value"] == 0.8


def test_materiality_evidence_and_source_refs_are_copied() -> None:
    event = deepcopy(STRONG_EVENT)
    result = build_event_overlay(event)

    assert result["evidence"] == event["evidence"]
    assert result["source_refs"] == event["source_refs"]
    assert result["evidence"] is not event["evidence"]
    assert result["source_refs"] is not event["source_refs"]


def test_pre_scored_materiality_is_read_only_copied() -> None:
    source = deepcopy(STRONG_EVENT)
    scored = build_event_overlay(source)["materiality"]
    source["materiality"] = scored

    result = build_event_overlay(source)

    assert result["materiality"] == scored
    assert result["materiality"] is not scored
    assert result["evidence"] is not scored["evidence"]


def test_identical_inputs_are_deterministic() -> None:
    assert build_event_overlay(STRONG_EVENT) == build_event_overlay(STRONG_EVENT)
