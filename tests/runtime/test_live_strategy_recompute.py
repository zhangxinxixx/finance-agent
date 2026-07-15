from __future__ import annotations

from copy import deepcopy

import pytest

from apps.analysis.strategy.event_overlay import build_event_overlay
from apps.runtime.live_strategy_recompute import (
    LiveStrategyRecomputePreviewQueryError,
    preview_live_strategy_recompute,
)


def _strategy(*, strategy_id: str, price: float = 2360.0) -> dict:
    return {
        "schema_version": "live_strategy.v1",
        "status": "available",
        "strategy_id": strategy_id,
        "strategy_version": "live_strategy.rules.v2",
        "strategy_status": "WATCHING",
        "live_market": {"status": "available", "price": price},
        "data_quality": {"canonical_candle": {"status": "available"}},
        "market_state": {
            "gamma_regime": "negative_gamma",
            "nearest_level": {"value": price},
            "latest_price_event": {"event_type": "accepted_break", "confirmed": True},
        },
        "setups": [],
        "event_overlay": {"status": "unavailable", "recompute_candidate": False},
    }


def _event_detail(event_id: str) -> dict:
    return {
        "event": {
            "id": event_id,
            "event_type": "fomc_statement",
            "time": "2026-07-18T09:01:00+00:00",
            "source_reliability": 0.95,
            "event_importance": 0.95,
            "surprise": 0.9,
            "gold_relevance": 0.95,
            "official_source": True,
            "independent_source_count": 2,
            "evidence": [{"source_ref": event_id}],
            "source_refs": [{"source_ref": event_id}],
        }
    }


def _market_reaction(event_id: str) -> dict:
    return {
        "event_id": event_id,
        "status": "validated",
        "market_reaction_strength": 0.9,
        "reaction_persistence": 0.85,
        "market_snapshot": {"XAUUSD": {"move_pct": 0.5}},
        "source_refs": [{"source_ref": "market:xauusd:5m"}],
    }


def _preview(**overrides) -> dict:
    previous = _strategy(strategy_id="previous")
    candidate = _strategy(strategy_id="candidate", price=2362.0)
    loaders = {
        "event_detail_loader": _event_detail,
        "market_reaction_loader": _market_reaction,
        "strategy_history_loader": lambda: {"items": [{"payload": previous}]},
        "candidate_strategy_loader": lambda observation: {
            **deepcopy(candidate),
            "event_overlay": build_event_overlay(observation),
        },
        "options_decision_loader": lambda: {"gamma_summary": {"regime": "negative_gamma"}},
    }
    loaders.update(overrides)
    return preview_live_strategy_recompute(event_id="fed:release:1", **loaders)


def test_preview_accepts_only_injected_read_dependencies() -> None:
    result = _preview()

    assert result["schema_version"] == "live_strategy.recompute_preview.v1"
    assert result["status"] == "accepted"
    assert result["reasons"] == ["accepted:recompute_preview"]
    assert result["previous_strategy"]["strategy_id"] == "previous"
    assert result["candidate_strategy"]["strategy_id"] == "candidate"


def test_preview_missing_event_skips_other_loaders() -> None:
    result = _preview(
        event_detail_loader=lambda _event_id: None,
        market_reaction_loader=lambda _event_id: pytest.fail("market reaction must not load"),
        strategy_history_loader=lambda: pytest.fail("history must not load"),
        candidate_strategy_loader=lambda _observation: pytest.fail("candidate must not load"),
        options_decision_loader=lambda: pytest.fail("options must not load"),
    )

    assert result["status"] == "unavailable"
    assert result["reasons"] == ["event_not_found"]


def test_preview_blocks_unavailable_canonical_candidate_without_options_load() -> None:
    candidate = _strategy(strategy_id="candidate")
    candidate["live_market"]["status"] = "stale"
    result = _preview(
        candidate_strategy_loader=lambda _observation: candidate,
        options_decision_loader=lambda: pytest.fail("options must not load"),
    )

    assert result["status"] == "blocked"
    assert result["reasons"] == ["candidate_canonical_market_unavailable"]
    assert result["execution"] is None


def test_preview_loader_failure_cannot_be_reported_as_accepted() -> None:
    with pytest.raises(RuntimeError, match="options unavailable"):
        _preview(options_decision_loader=lambda: (_ for _ in ()).throw(RuntimeError("options unavailable")))


@pytest.mark.parametrize("event_id", [None, "", "event/secret", "a" * 129])
def test_preview_validates_event_id(event_id: object) -> None:
    with pytest.raises(LiveStrategyRecomputePreviewQueryError, match="invalid event_id"):
        preview_live_strategy_recompute(
            event_id=event_id,  # type: ignore[arg-type]
            event_detail_loader=_event_detail,
            market_reaction_loader=_market_reaction,
            strategy_history_loader=lambda: {"items": []},
            candidate_strategy_loader=lambda _observation: _strategy(strategy_id="candidate"),
            options_decision_loader=lambda: None,
        )
