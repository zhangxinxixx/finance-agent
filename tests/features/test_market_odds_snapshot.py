"""P4-07: Market odds snapshot tests."""

from __future__ import annotations

from apps.features.market_odds.snapshot import (
    MarketOddsEvent,
    MarketOddsSnapshot,
    ProbabilitySource,
    _derive_cme_price_target_odds,
    _estimate_probability_from_walls,
    _extract_top_wall_strike,
    _placeholder_event,
    _unavailable_prob,
    build_market_odds_snapshot,
)


# ── Unit: helpers ─────────────────────────────────────────────────────


def test_extract_top_wall_strike():
    walls = [
        {"strike": 2400, "oi": 100},
        {"strike": 2500, "oi": 500},
        {"strike": 2600, "oi": 200},
    ]
    assert _extract_top_wall_strike(walls) == 2500


def test_extract_top_wall_strike_empty():
    assert _extract_top_wall_strike([]) is None


def test_estimate_probability_from_walls_call():
    call_walls = [{"strike": 2500, "oi": 500}]
    put_walls = [{"strike": 2400, "oi": 300}]
    prob = _estimate_probability_from_walls(2500, call_walls, put_walls, side="call")
    assert prob is not None
    assert 0.0 < prob <= 0.7


def test_estimate_probability_from_walls_no_data():
    prob = _estimate_probability_from_walls(2500, [], [], side="call")
    assert prob is None


def test_placeholder_event():
    event = _placeholder_event("test_id", "Test Event", source_note="No data.")
    assert event.status == "unavailable"
    assert event.signal_label == "unavailable"
    assert "No data" in event.interpretation


def test_unavailable_prob():
    prob = _unavailable_prob("Not ready")
    assert prob.probability is None
    assert prob.confidence == 0.0


# ── Integration: build snapshot ────────────────────────────────────────


def test_build_empty_no_options():
    """Without options data, snapshot should be unavailable."""
    snap = build_market_odds_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-16",
        run_id="test-run",
    )
    assert snap.status == "unavailable"
    assert snap.aggregate_signal == "unavailable"
    assert len(snap.events) == 2  # 2 placeholders (Fed + Polymarket)


def test_build_with_options():
    """With options walls, should derive CME-based probabilities."""
    options = {
        "expiries": ["202606", "202608", "202612"],
        "walls": {
            "call_oi_walls": [
                {"strike": 2500, "oi": 800, "side": "CALL"},
                {"strike": 2600, "oi": 300, "side": "CALL"},
            ],
            "put_oi_walls": [
                {"strike": 2300, "oi": 600, "side": "PUT"},
                {"strike": 2200, "oi": 200, "side": "PUT"},
            ],
        },
    }
    snap = build_market_odds_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-16",
        run_id="test-run",
        options_snapshot=options,
    )
    assert snap.status in ("available", "partial")
    # Should have 4+ events (2 CME + 2 placeholders)
    available = [e for e in snap.events if e.status == "available"]
    assert len(available) >= 1  # at least one CME event
    assert len(snap.events) >= 3  # CME events + placeholders


def test_snapshot_fields():
    """Verify all required fields are present."""
    options = {
        "expiries": ["202606"],
        "walls": {
            "call_oi_walls": [{"strike": 2500, "oi": 500}],
            "put_oi_walls": [{"strike": 2300, "oi": 400}],
        },
    }
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16",
        run_id="r1",
        options_snapshot=options,
    )
    assert snap.snapshot_id
    assert snap.version == "1.0.0"
    assert snap.trade_date == "2026-05-16"
    assert snap.source_refs
    assert snap.input_snapshot_ids

    for event in snap.events:
        assert event.event_id
        assert event.event_name
        assert event.status in ("available", "partial", "unavailable")
        assert "cme_options" in event.probabilities
        assert "polymarket" in event.probabilities
        assert "bloomberg" in event.probabilities
        assert "internal_model" in event.probabilities


def test_cme_event_has_valid_probabilities():
    """CME-derived events should have valid probability range."""
    options = {
        "expiries": ["202606"],
        "walls": {
            "call_oi_walls": [{"strike": 2500, "oi": 500}],
            "put_oi_walls": [{"strike": 2300, "oi": 400}],
        },
    }
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="r1", options_snapshot=options,
    )
    cme_events = [e for e in snap.events if e.status == "available"]
    for event in cme_events:
        assert event.final_probability is not None
        assert 0.0 <= event.final_probability <= 1.0
        cme = event.probabilities.get("cme_options")
        assert cme is not None
        if cme.probability is not None:
            assert 0.0 <= cme.probability <= 1.0


def test_placeholder_events_polymarket_unavailable():
    """Polymarket events should be explicitly unavailable."""
    snap = build_market_odds_snapshot(trade_date="2026-05-16", run_id="r1")
    poly_events = [e for e in snap.events if "polymarket" in e.event_id.lower()]
    for event in poly_events:
        assert event.status == "unavailable"
        poly = event.probabilities.get("polymarket")
        if poly:
            assert poly.probability is None


def test_derive_cme_empty_options():
    events = _derive_cme_price_target_odds({}, "XAUUSD", "2026-05-16")
    assert events == []


def test_derive_cme_no_walls():
    options = {"expiries": ["202606"], "walls": {"call_oi_walls": [], "put_oi_walls": []}}
    events = _derive_cme_price_target_odds(options, "XAUUSD", "2026-05-16")
    assert events == []


# ── Schema unit tests ─────────────────────────────────────────────────


def test_probability_source_creation():
    ps = ProbabilitySource(
        source="cme_options",
        probability=0.65,
        confidence=0.7,
        last_updated="2026-05-16",
        source_ref="cmegroup.com/test",
    )
    assert ps.probability == 0.65
    assert ps.confidence == 0.7


def test_market_odds_event_defaults():
    event = MarketOddsEvent(
        event_id="test",
        event_name="Test Event",
    )
    assert event.status == "unavailable"
    assert event.signal_label == "neutral"
    assert event.confidence == 0.0


def test_market_odds_snapshot_defaults():
    snap = MarketOddsSnapshot(snapshot_id="test:snap")
    assert snap.status == "unavailable"
    assert snap.aggregate_signal == "unavailable"
    assert snap.events == []


# ── Integration: analysis snapshot builder includes market_odds ────────


def test_analysis_snapshot_includes_market_odds():
    """The unified analysis snapshot builder should include a market_odds section."""
    from apps.analysis.snapshots.builder import build_analysis_snapshot

    options = {
        "expiries": ["202606"],
        "walls": {
            "call_oi_walls": [{"strike": 2500, "oi": 500}],
            "put_oi_walls": [{"strike": 2300, "oi": 400}],
        },
    }
    snap = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-16",
        run_id="test-run",
        macro_snapshot=None,
        options_snapshot=options,
    )
    assert "market_odds" in snap
    mo = snap["market_odds"]
    assert isinstance(mo, dict)
    assert "status" in mo
    assert mo["status"] in ("available", "partial", "unavailable")


def test_analysis_snapshot_market_odds_unavailable():
    """Without options data, market_odds should be unavailable."""
    from apps.analysis.snapshots.builder import build_analysis_snapshot

    snap = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-16",
        run_id="test-run",
        macro_snapshot=None,
        options_snapshot=None,
    )
    assert "market_odds" in snap
    assert snap["market_odds"]["status"] == "unavailable"
