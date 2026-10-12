"""P4-07: Market odds snapshot tests."""

from __future__ import annotations

import pytest

from apps.features.market_odds.snapshot import (
    MarketOddsEvent,
    MarketOddsSnapshot,
    ProbabilitySource,
    _black76_terminal_probability,
    _derive_cme_price_target_odds,
    _estimate_probability_from_walls,
    _extract_top_wall_strike,
    _placeholder_event,
    _unavailable_prob,
    build_market_odds_snapshot,
)


def _source_ref() -> dict[str, str]:
    return {
        "source": "cme_options",
        "raw_path": "raw/cme/2026-05-16/gold_options.json",
        "retrieved_at": "2026-05-16T20:00:00Z",
    }


def _complete_per_expiry_options(
    *,
    expiry: str = "2026-06-19",
    include_t: bool = True,
    include_expiry_date: bool = True,
    include_source: bool = True,
    put_delta: float = -0.28,
    include_iv: bool = True,
) -> dict:
    expiry_data = {
        "forward_price": 2500.0,
        "strikes": [
            {
                "strike": 2600,
                "call_oi": 800,
                "call_delta": 0.22,
                **({"iv": 0.20} if include_iv else {}),
            },
            {
                "strike": 2300,
                "put_oi": 700,
                "put_delta": put_delta,
                **({"iv": 0.24} if include_iv else {}),
            },
        ],
    }
    if include_t:
        expiry_data["time_to_expiry_years"] = 34 / 365
    if include_expiry_date:
        expiry_data["expiry_date"] = expiry
    if include_source:
        expiry_data["source_refs"] = [_source_ref()]
    return {"per_expiry": {expiry: expiry_data}}


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
    assert prob is None


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
    assert len(snap.events) == 2  # generic Fed + Polymarket source statuses
    assert {event.event_id for event in snap.events} == {"fed_rate", "polymarket_price_target"}
    assert all(event.target_value is None for event in snap.events)
    assert all(event.horizon_end == "" for event in snap.events)


def test_build_with_options_keeps_oi_walls_structural():
    """OI walls remain structure and cannot become probabilities."""
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
    assert snap.status == "partial"
    structural = [e for e in snap.events if e.event_type == "price_structure"]
    assert len(structural) == 2
    assert all(e.status == "partial" for e in structural)
    assert all(e.final_probability is None for e in structural)
    assert all(e.signal_label == "unavailable" for e in structural)
    assert all(e.probabilities["cme_options"].probability is None for e in structural)
    assert all("structural" in e.interpretation for e in structural)


def test_per_expiry_oi_only_is_structural_and_unavailable():
    options = {
        "per_expiry": {
            "202606": {
                "strikes": [
                    {"strike": 2600, "call_oi": 900},
                    {"strike": 2300, "put_oi": 700},
                ],
            }
        }
    }
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="oi-only", options_snapshot=options,
    )
    events = [e for e in snap.events if e.event_id.startswith("gold_")]
    assert {e.event_id for e in events} == {"gold_above_2600_202606", "gold_below_2300_202606"}
    assert all(e.status == "unavailable" for e in events)
    assert all(e.final_probability is None for e in events)


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
    """Complete F/K/IV/T data produces Black-76 N(d2), not delta touch."""
    options = _complete_per_expiry_options()
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="r1", options_snapshot=options,
    )
    cme_events = [e for e in snap.events if e.status == "available"]
    assert len(cme_events) == 2
    for event in cme_events:
        assert event.final_probability is not None
        assert 0.0 <= event.final_probability <= 1.0
        cme = event.probabilities.get("cme_options")
        assert cme is not None
        if cme.probability is not None:
            assert 0.0 <= cme.probability <= 1.0
            assert "risk-neutral" in cme.notes
            assert "futures coordinates" in cme.notes
            assert "not a touch probability" in cme.notes
        assert event.signal_label == "neutral"
        assert "not a gold directional signal" in event.interpretation


@pytest.mark.parametrize("missing_provenance", ["estimated_expiry", "wrong_tenor", "global_forward", "implicit_percent_iv", "lookalike_host"])
def test_probability_requires_matching_tenor_units_and_trusted_lineage(missing_provenance):
    options = _complete_per_expiry_options()
    expiry = options["per_expiry"]["2026-06-19"]
    if missing_provenance == "estimated_expiry":
        expiry["expiry_estimated"] = True
    elif missing_provenance == "wrong_tenor":
        expiry["time_to_expiry_years"] = 1.0
    elif missing_provenance == "global_forward":
        options["forward_price"] = expiry.pop("forward_price")
    elif missing_provenance == "implicit_percent_iv":
        for strike in expiry["strikes"]:
            strike["iv"] *= 100
    elif missing_provenance == "lookalike_host":
        expiry["source_refs"] = [{"source": "cme", "source_url": "https://cmegroup.com.example.test/data"}]
    result = build_market_odds_snapshot(trade_date="2026-05-16", run_id="invalid-model-input", options_snapshot=options)
    assert all(event.final_probability is None for event in result.events)


def test_explicit_percent_iv_matches_decimal_iv():
    decimal = _complete_per_expiry_options()
    percent = _complete_per_expiry_options()
    for row in percent["per_expiry"]["2026-06-19"]["strikes"]:
        row["iv"] *= 100
        row["iv_unit"] = "percent"
    results = [build_market_odds_snapshot(trade_date="2026-05-16", run_id="units", options_snapshot=value) for value in (decimal, percent)]
    assert [event.final_probability for event in results[0].events] == [event.final_probability for event in results[1].events]


def test_black76_n_d2_matches_event_formula():
    options = _complete_per_expiry_options()
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="r1", options_snapshot=options,
    )
    above = next(e for e in snap.events if e.event_id == "gold_above_2600_2026-06-19")
    expected = _black76_terminal_probability(
        F=2500.0, K=2600.0, implied_vol=0.20, T=34 / 365,
        direction="above",
    )
    assert above.final_probability == round(expected, 4)


def test_missing_iv_at_exact_target_does_not_use_nearest_strike():
    options = {
        "per_expiry": {
            "2026-06-19": {
                "expiry_date": "2026-06-19",
                "time_to_expiry_years": 34 / 365,
                "forward_price": 2500.0,
                "source_refs": [_source_ref()],
                "strikes": [
                    {"strike": 2600, "call_oi": 800, "call_delta": 0.22},
                    {"strike": 2550, "iv": 0.20},
                ],
            }
        }
    }
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="exact-target", options_snapshot=options,
    )
    above = next(e for e in snap.events if e.event_id == "gold_above_2600_2026-06-19")
    assert above.status == "unavailable"
    assert above.final_probability is None
    assert "IV" in above.interpretation


def test_arbitrary_url_is_not_source_lineage():
    options = _complete_per_expiry_options(include_source=False)
    options["per_expiry"]["2026-06-19"]["source_refs"] = [
        {"url": "https://example.invalid/claimed-cme-data"}
    ]
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="bad-source", options_snapshot=options,
    )
    events = [e for e in snap.events if e.event_id.startswith("gold_")]
    assert events
    assert all(e.status == "unavailable" for e in events)
    assert all(e.final_probability is None for e in events)
    assert all("source_lineage" in e.interpretation for e in events)


def test_placeholder_events_polymarket_unavailable():
    """Uncollected sources are generic and contain no invented target/date."""
    snap = build_market_odds_snapshot(trade_date="2026-05-16", run_id="r1")
    poly_events = [e for e in snap.events if e.event_id == "polymarket_price_target"]
    assert len(poly_events) == 1
    for event in poly_events:
        assert event.status == "unavailable"
        assert event.target_value is None
        assert event.horizon_end == ""
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


def test_delta_only_is_unavailable_and_never_touch_probability():
    options = _complete_per_expiry_options(include_iv=False)
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="delta-only", options_snapshot=options,
    )
    events = [e for e in snap.events if e.event_id.startswith("gold_")]
    assert events
    assert all(e.status == "unavailable" for e in events)
    assert all(e.final_probability is None for e in events)
    assert all(e.probabilities["cme_options"].probability is None for e in events)
    assert any("delta alone is insufficient" in e.interpretation for e in events)


def test_missing_actual_expiry_date_is_unavailable():
    options = _complete_per_expiry_options(
        expiry="202606", include_expiry_date=False,
    )
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="no-expiry-date", options_snapshot=options,
    )
    events = [e for e in snap.events if e.event_id.startswith("gold_")]
    assert events
    assert all(e.status == "unavailable" for e in events)
    assert all(e.final_probability is None for e in events)
    assert all(e.horizon_end == "" for e in events)
    assert all("actual_expiry_date" in e.interpretation for e in events)


def test_missing_time_to_expiry_is_unavailable():
    options = _complete_per_expiry_options(include_t=False)
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="no-t", options_snapshot=options,
    )
    events = [e for e in snap.events if e.event_id.startswith("gold_")]
    assert events
    assert all(e.status == "unavailable" for e in events)
    assert all(e.final_probability is None for e in events)
    assert all("T" in e.interpretation for e in events)


def test_negative_put_delta_does_not_get_abs_or_touch_probability():
    options = _complete_per_expiry_options(put_delta=-0.42)
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="negative-put-delta", options_snapshot=options,
    )
    below = next(e for e in snap.events if e.event_id == "gold_below_2300_2026-06-19")
    expected = _black76_terminal_probability(
        F=2500.0, K=2300.0, implied_vol=0.24, T=34 / 365,
        direction="below",
    )
    assert below.status == "available"
    assert below.final_probability == round(expected, 4)
    assert below.final_probability != round(abs(-0.42) * 2, 4)
    assert below.signal_label == "neutral"


def test_expired_event_is_unavailable_even_with_complete_inputs():
    options = _complete_per_expiry_options(expiry="2026-05-15")
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="expired", options_snapshot=options,
    )
    events = [e for e in snap.events if e.event_id.startswith("gold_")]
    assert events
    assert all(e.status == "unavailable" for e in events)
    assert all(e.final_probability is None for e in events)
    assert all("future_expiry" in e.interpretation for e in events)


def test_source_lineage_is_required_for_probability():
    options = _complete_per_expiry_options(include_source=False)
    snap = build_market_odds_snapshot(
        trade_date="2026-05-16", run_id="no-lineage", options_snapshot=options,
    )
    events = [e for e in snap.events if e.event_id.startswith("gold_")]
    assert events
    assert all(e.status == "unavailable" for e in events)
    assert all(e.final_probability is None for e in events)
    assert all("source_lineage" in e.interpretation for e in events)


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
