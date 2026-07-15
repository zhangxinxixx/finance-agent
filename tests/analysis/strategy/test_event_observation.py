from __future__ import annotations

from copy import deepcopy

from apps.analysis.strategy.event_observation import build_event_observation
from apps.analysis.strategy.event_overlay import build_event_overlay


EVENT_DETAIL = {
    "status": "partial",
    "updated_at": "2026-07-18T12:05:00+00:00",
    "event": {
        "id": "evt:fed:1",
        "event_type": "fed_speech",
        "time": "2026-07-18T12:00:00+00:00",
        "source_reliability": 0.95,
        "event_importance": 0.8,
        "surprise": 0.7,
        "gold_relevance": 0.9,
        "official_source": True,
        "independent_source_count": 2,
        "evidence": [
            {"kind": "release", "source_ref": "fed:release:1"},
            {"kind": "unsupported-note"},
        ],
        "source_refs": [
            {"source_ref": "fed:release:1", "source": "federal_reserve"},
            {"source_ref": "fed:release:1", "source": "federal_reserve"},
        ],
    },
    "source_refs": [
        {"source_ref": "fed:release:1", "source": "federal_reserve"},
        {"source_ref": "cme:xauusd:5m", "source": "cme"},
        {"label": "not-lineage"},
    ],
}

MARKET_REACTION = {
    "event_id": "evt:fed:1",
    "status": "validated",
    "updated_at": "2026-07-18T12:30:00+00:00",
    "market_reaction_strength": 0.85,
    "reaction_persistence": 0.75,
    "market_validation": {"status": "validated"},
    "market_snapshot": {"XAUUSD": {"move_pct": -0.4}},
    "source_refs": [{"source_ref": "cme:xauusd:5m", "source": "cme"}],
}


def test_available_observation_feeds_event_overlay() -> None:
    result = build_event_observation(EVENT_DETAIL, MARKET_REACTION)

    assert result["schema_version"] == "live_strategy.event_observation.v1"
    assert result["status"] == "available"
    assert result["event_id"] == "evt:fed:1"
    assert result["event_type"] == "fed_speech"
    assert result["observed_at"] == "2026-07-18T12:00:00+00:00"
    assert result["observed_reaction"]["observed"] is True
    assert result["observed_reaction"]["market_snapshot"] == {
        "XAUUSD": {"move_pct": -0.4}
    }
    assert result["materiality_inputs"]["market_reaction_strength"] == 0.85
    assert build_event_overlay(result)["status"] == "eligible"


def test_missing_event_identity_is_blocked() -> None:
    detail = deepcopy(EVENT_DETAIL)
    detail["event"].pop("id")

    result = build_event_observation(detail, MARKET_REACTION)

    assert result["status"] == "blocked"
    assert result["event_id"] is None
    assert "event_identity_required" in result["reasons"]


def test_missing_observed_at_is_blocked() -> None:
    detail = deepcopy(EVENT_DETAIL)
    detail["event"].pop("time")

    result = build_event_observation(detail, MARKET_REACTION)

    assert result["status"] == "blocked"
    assert result["observed_at"] is None
    assert "observed_at_required" in result["reasons"]


def test_missing_real_market_reaction_does_not_fabricate_reaction() -> None:
    result = build_event_observation(
        EVENT_DETAIL,
        {
            "status": "validated",
            "market_validation": {"status": "validated"},
            "market_snapshot": {},
        },
    )

    assert result["status"] == "blocked"
    assert result["observed_reaction"] is None
    assert "observed_market_reaction_required" in result["reasons"]

    empty_windows = build_event_observation(
        EVENT_DETAIL,
        {"status": "available", "windows": {"30m": {}}},
    )
    assert empty_windows["observed_reaction"] is None


def test_sources_are_deduplicated_and_unsupported_evidence_is_dropped() -> None:
    result = build_event_observation(EVENT_DETAIL, MARKET_REACTION)

    assert result["evidence"] == [
        {"kind": "release", "source_ref": "fed:release:1"}
    ]
    assert result["source_refs"] == [
        {"source_ref": "fed:release:1", "source": "federal_reserve"},
        {"source_ref": "cme:xauusd:5m", "source": "cme"},
    ]

    detail = deepcopy(EVENT_DETAIL)
    detail["source_refs"].append({"source": None, "note": "not-lineage"})
    assert build_event_observation(detail, MARKET_REACTION)["source_refs"] == result["source_refs"]


def test_observation_id_is_stable_and_inputs_are_not_mutated() -> None:
    detail = deepcopy(EVENT_DETAIL)
    reaction = deepcopy(MARKET_REACTION)
    detail_before = deepcopy(detail)
    reaction_before = deepcopy(reaction)

    first = build_event_observation(detail, reaction)
    second = build_event_observation(detail, reaction)

    assert first == second
    assert first["observation_id"].startswith("event-observation-")
    assert detail == detail_before
    assert reaction == reaction_before


def test_absent_event_detail_is_unavailable() -> None:
    result = build_event_observation(None, MARKET_REACTION)

    assert result["status"] == "unavailable"
    assert result["observed_reaction"] is None
    assert result["reasons"] == ["event_detail_unavailable"]
