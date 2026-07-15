from __future__ import annotations

from copy import deepcopy

import pytest

from apps.analysis.strategy.event_overlay import build_event_overlay
from apps.analysis.strategy.history_store import StrategyHistoryStore
from apps.api.services import live_strategy_recompute_service as service
from apps.api.services.live_strategy_recompute_service import (
    LiveStrategyRecomputePreviewQueryError,
    preview_live_strategy_recompute,
)


def _strategy(*, strategy_id: str, updated_at: str, price: float = 2360.0) -> dict:
    return {
        "schema_version": "live_strategy.v1",
        "status": "available",
        "strategy_id": strategy_id,
        "baseline_strategy_id": "baseline-a",
        "strategy_version": "live_strategy.rules.v2",
        "asset": "XAUUSD",
        "strategy_status": "WATCHING",
        "updated_at": updated_at,
        "live_market": {"status": "available", "price": price},
        "data_quality": {"canonical_candle": {"status": "available"}},
        "market_state": {
            "gamma_regime": "negative_gamma",
            "nearest_level": {"value": price},
            "latest_price_event": {
                "event_type": "accepted_break",
                "confirmed": True,
            },
        },
        "setups": [],
        "event_overlay": {
            "schema_version": "live_strategy.event_overlay.v1",
            "status": "unavailable",
            "recompute_candidate": False,
        },
    }


def _event_detail(event_id: str = "fed:release:1") -> dict:
    return {
        "status": "partial",
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
            "evidence": [{"source_ref": "fed:release:1", "kind": "release"}],
            "source_refs": [{"source_ref": "fed:release:1"}],
        },
    }


def _market_reaction(event_id: str = "fed:release:1") -> dict:
    return {
        "event_id": event_id,
        "status": "validated",
        "market_reaction_strength": 0.9,
        "reaction_persistence": 0.85,
        "market_snapshot": {"XAUUSD": {"move_pct": 0.5}},
        "source_refs": [{"source_ref": "market:xauusd:5m"}],
    }


def _patch_available_event(monkeypatch, event_id: str = "fed:release:1") -> None:
    monkeypatch.setattr(service, "build_event_flow_event_detail", lambda value: _event_detail(value))
    monkeypatch.setattr(service, "build_event_flow_market_reaction", lambda value: _market_reaction(value))


def test_accepted_preview_uses_latest_history_and_never_writes(monkeypatch, tmp_path) -> None:
    previous = _strategy(
        strategy_id="live-a",
        updated_at="2026-07-18T09:00:00+00:00",
    )
    StrategyHistoryStore(tmp_path).write(previous)
    files_before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    _patch_available_event(monkeypatch)

    candidate = _strategy(
        strategy_id="live-b",
        updated_at="2026-07-18T09:05:00+00:00",
        price=2362.0,
    )
    latest_calls: list[dict] = []

    def fake_latest(**kwargs):
        latest_calls.append(kwargs)
        result = deepcopy(candidate)
        result["event_overlay"] = build_event_overlay(kwargs["event_observation"])
        return result

    monkeypatch.setattr(service, "get_live_strategy_latest", fake_latest)
    monkeypatch.setattr(
        service,
        "get_options_decision",
        lambda **_: {"gamma_summary": {"regime": "negative_gamma"}},
    )

    result = preview_live_strategy_recompute(
        event_id="fed:release:1",
        db=object(),
        storage_root=tmp_path,
    )

    assert result["schema_version"] == "live_strategy.recompute_preview.v1"
    assert result["status"] == "accepted"
    assert result["reasons"] == ["accepted:recompute_preview"]
    assert result["previous_strategy"]["strategy_id"] == "live-a"
    assert result["candidate_strategy"]["strategy_id"] == "live-b"
    assert result["execution"]["status"] == "accepted"
    assert result["execution"]["recompute"]["accepted"] is True
    assert latest_calls[0]["event_observation"]["status"] == "available"
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == files_before


def test_missing_event_returns_unavailable_without_building_candidate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service, "build_event_flow_event_detail", lambda _event_id: None)
    monkeypatch.setattr(
        service,
        "build_event_flow_market_reaction",
        lambda _event_id: pytest.fail("reaction must not be read for a missing event"),
    )
    monkeypatch.setattr(
        service,
        "get_live_strategy_latest",
        lambda **_: pytest.fail("candidate must not be built for a missing event"),
    )

    result = preview_live_strategy_recompute(
        event_id="missing:1",
        storage_root=tmp_path,
    )

    assert result["status"] == "unavailable"
    assert result["reasons"] == ["event_not_found"]
    assert result["candidate_strategy"] is None
    assert list(tmp_path.iterdir()) == []


def test_blocked_observation_does_not_read_history_or_build_candidate(monkeypatch) -> None:
    monkeypatch.setattr(service, "build_event_flow_event_detail", lambda value: _event_detail(value))
    monkeypatch.setattr(
        service,
        "build_event_flow_market_reaction",
        lambda value: {"event_id": value, "status": "unavailable"},
    )
    monkeypatch.setattr(
        service,
        "get_live_strategy_history",
        lambda **_: pytest.fail("history must not be read for a blocked observation"),
    )
    monkeypatch.setattr(
        service,
        "get_live_strategy_latest",
        lambda **_: pytest.fail("candidate must not be built for a blocked observation"),
    )

    result = preview_live_strategy_recompute(event_id="fed:release:1")

    assert result["status"] == "blocked"
    assert "observed_market_reaction_required" in result["reasons"]
    assert result["candidate_strategy"] is None


def test_empty_history_is_read_only_and_does_not_build_candidate(monkeypatch, tmp_path) -> None:
    _patch_available_event(monkeypatch)
    monkeypatch.setattr(
        service,
        "get_live_strategy_latest",
        lambda **_: pytest.fail("candidate must not be built without previous history"),
    )

    result = preview_live_strategy_recompute(
        event_id="fed:release:1",
        storage_root=tmp_path,
    )

    assert result["status"] == "unavailable"
    assert result["reasons"] == ["eligible_strategy_history_unavailable"]
    assert result["previous_strategy"] is None
    assert not (tmp_path / "strategy_history").exists()


def test_unavailable_canonical_candidate_blocks_execution(monkeypatch, tmp_path) -> None:
    StrategyHistoryStore(tmp_path).write(
        _strategy(strategy_id="live-a", updated_at="2026-07-18T09:00:00+00:00")
    )
    _patch_available_event(monkeypatch)
    candidate = _strategy(
        strategy_id="live-b",
        updated_at="2026-07-18T09:05:00+00:00",
    )
    candidate["strategy_status"] = "SUSPENDED_DATA"
    candidate["live_market"]["status"] = "stale"
    candidate["data_quality"]["canonical_candle"]["status"] = "stale"
    monkeypatch.setattr(service, "get_live_strategy_latest", lambda **_: candidate)
    result = preview_live_strategy_recompute(
        event_id="fed:release:1",
        storage_root=tmp_path,
    )

    assert result["status"] == "blocked"
    assert result["reasons"] == [
        "candidate_strategy_suspended_data",
        "candidate_canonical_market_unavailable",
        "candidate_canonical_data_unavailable",
    ]
    assert result["execution"] is None


@pytest.mark.parametrize(
    "event_id",
    [None, "", " leading", "../secret", "event/secret", "a" * 129, "事件:1"],
)
def test_event_id_validation_has_fixed_error_semantics(event_id) -> None:
    with pytest.raises(LiveStrategyRecomputePreviewQueryError) as exc_info:
        preview_live_strategy_recompute(event_id=event_id)  # type: ignore[arg-type]

    assert str(exc_info.value) == "invalid event_id"
    assert "secret" not in str(exc_info.value)


def test_history_storage_error_does_not_leak_path(monkeypatch) -> None:
    _patch_available_event(monkeypatch)
    monkeypatch.setattr(
        service,
        "get_live_strategy_history",
        lambda **_: (_ for _ in ()).throw(
            service.LiveStrategyHistoryStorageError("invalid /secret/history.json")
        ),
    )

    result = preview_live_strategy_recompute(event_id="fed:release:1")

    assert result["status"] == "unavailable"
    assert result["reasons"] == ["strategy_history_invalid"]
    assert "/secret" not in str(result)
