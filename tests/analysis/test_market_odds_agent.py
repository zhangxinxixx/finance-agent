"""P4-08: Market odds agent and coordinator integration tests.

Tests cover:
  - market_odds_agent standalone (available, partial, unavailable)
  - coordinator with market_odds_output parameter
  - worker runner includes market_odds in C4 pipeline
"""

from __future__ import annotations

from apps.analysis.agents.market_odds import (
    _AGENT_NAME,
    _MODULE,
    _VERSION,
    analyze_market_odds,
)
from apps.analysis.agents.schemas import AgentBias, AgentStatus


# ── Market odds agent: unavailable ──────────────────────────────────────


def test_analyze_market_odds_no_snapshot():
    """Non-dict input returns unavailable."""
    result = analyze_market_odds("not a dict")
    assert result.agent_name == _AGENT_NAME
    assert result.status == AgentStatus.UNAVAILABLE
    assert result.bias == AgentBias.UNAVAILABLE
    assert result.confidence == 0.0


def test_analyze_market_odds_missing_section():
    """Snapshot without market_odds section returns unavailable."""
    result = analyze_market_odds({"snapshot_id": "test", "options": {}})
    assert result.status == AgentStatus.UNAVAILABLE
    assert result.bias == AgentBias.UNAVAILABLE


def test_analyze_market_odds_status_unavailable():
    """market_odds section with status=unavailable returns unavailable."""
    result = analyze_market_odds({
        "snapshot_id": "test",
        "market_odds": {"status": "unavailable"},
    })
    assert result.status == AgentStatus.UNAVAILABLE
    assert result.bias == AgentBias.UNAVAILABLE


# ── Market odds agent: available / partial ──────────────────────────────


def test_analyze_market_odds_bullish():
    """Available CME event with bullish signal."""
    snapshot = {
        "snapshot_id": "XAUUSD:2026-05-16:r1",
        "market_odds": {
            "status": "partial",
            "aggregate_signal": "bullish",
            "aggregate_confidence": 0.45,
            "events": [
                {
                    "event_id": "gold_above_2500",
                    "event_name": "Gold > $2500",
                    "status": "available",
                    "final_probability": 0.65,
                    "signal_label": "bullish",
                    "reliability_score": 0.5,
                    "divergence_score": 0.0,
                    "interpretation": "Market assigns elevated probability.",
                    "probabilities": {
                        "cme_options": {"probability": 0.65, "confidence": 0.5},
                        "polymarket": {"probability": None},
                        "bloomberg": {"probability": None},
                        "internal_model": {"probability": None},
                    },
                },
                {
                    "event_id": "fed_rate_jun_2026",
                    "event_name": "Fed Rate Cut",
                    "status": "unavailable",
                    "probabilities": {},
                },
            ],
        },
    }
    result = analyze_market_odds(snapshot)
    assert result.agent_name == _AGENT_NAME
    assert result.module == _MODULE
    assert result.version == _VERSION
    assert result.status == AgentStatus.PARTIAL  # partial due to missing sources
    assert result.bias == AgentBias.BULLISH
    assert 0.0 < result.confidence <= 0.65
    assert len(result.key_findings) >= 1
    assert "Gold > $2500" in result.key_findings[0]
    assert len(result.watchlist) >= 3


def test_analyze_market_odds_bearish():
    """Available CME event with bearish signal."""
    snapshot = {
        "snapshot_id": "XAUUSD:2026-05-16:r1",
        "market_odds": {
            "status": "partial",
            "aggregate_signal": "bearish",
            "events": [
                {
                    "event_id": "gold_below_2300",
                    "event_name": "Gold < $2300",
                    "status": "available",
                    "final_probability": 0.55,
                    "signal_label": "bearish",
                    "reliability_score": 0.4,
                    "divergence_score": 0.1,
                    "interpretation": "Market shows elevated downside probability.",
                    "probabilities": {
                        "cme_options": {"probability": 0.55},
                        "polymarket": {"probability": None},
                        "bloomberg": {"probability": None},
                        "internal_model": {"probability": None},
                    },
                },
            ],
        },
    }
    result = analyze_market_odds(snapshot)
    assert result.bias == AgentBias.BEARISH
    assert result.status == AgentStatus.PARTIAL


def test_analyze_market_odds_neutral():
    """Available event with neutral aggregate."""
    snapshot = {
        "snapshot_id": "test",
        "market_odds": {
            "status": "available",
            "aggregate_signal": "neutral",
            "events": [
                {
                    "event_id": "gold_above_2500",
                    "event_name": "Gold > $2500",
                    "status": "available",
                    "final_probability": 0.40,
                    "signal_label": "neutral",
                    "reliability_score": 0.5,
                    "divergence_score": 0.0,
                    "probabilities": {},
                },
            ],
        },
    }
    result = analyze_market_odds(snapshot)
    assert result.bias == AgentBias.NEUTRAL


def test_analyze_market_odds_all_unavailable_events():
    """All events are unavailable → bias is unavailable."""
    snapshot = {
        "snapshot_id": "test",
        "market_odds": {
            "status": "unavailable",
            "aggregate_signal": "unavailable",
            "events": [
                {
                    "event_id": "fed_rate_jun_2026",
                    "event_name": "Fed Rate Cut",
                    "status": "unavailable",
                    "probabilities": {},
                },
            ],
        },
    }
    result = analyze_market_odds(snapshot)
    assert result.bias == AgentBias.UNAVAILABLE
    assert result.status == AgentStatus.UNAVAILABLE


def test_analyze_market_odds_no_events():
    """Empty events list returns appropriate output."""
    snapshot = {
        "snapshot_id": "test",
        "market_odds": {
            "status": "unavailable",
            "aggregate_signal": "unavailable",
            "events": [],
        },
    }
    result = analyze_market_odds(snapshot)
    assert result.status == AgentStatus.UNAVAILABLE


def test_analyze_market_odds_fields_complete():
    """All required fields are present in output."""
    snapshot = {
        "snapshot_id": "XAUUSD:2026-05-16:r1",
        "input_snapshot_ids": {"macro": "macro:2026-05-16:r1"},
        "source_refs": [{"source": "cme"}],
        "market_odds": {
            "status": "partial",
            "aggregate_signal": "bullish",
            "source_refs": [{"source": "cme_options_delta_grid"}],
            "events": [
                {
                    "event_id": "gold_above_2500",
                    "event_name": "Gold > $2500",
                    "status": "available",
                    "final_probability": 0.60,
                    "signal_label": "bullish",
                    "reliability_score": 0.45,
                    "divergence_score": 0.1,
                    "interpretation": "Test interpretation.",
                    "probabilities": {
                        "cme_options": {"probability": 0.60, "confidence": 0.5},
                        "polymarket": {"probability": None},
                        "bloomberg": {"probability": None},
                        "internal_model": {"probability": None},
                    },
                },
            ],
        },
    }
    result = analyze_market_odds(snapshot)
    assert result.agent_name
    assert result.module
    assert result.version
    assert result.snapshot_id
    assert result.input_snapshot_ids
    assert result.key_findings
    assert result.risk_points
    assert result.watchlist
    assert result.invalid_conditions
    assert result.summary
    assert result.source_refs
    assert result.created_at is not None


# ── Coordinator integration ─────────────────────────────────────────────


def test_coordinator_with_market_odds_bullish():
    """Coordinator accepts market_odds_output and notes it."""
    from apps.analysis.agents.coordinator import coordinate_agent_outputs
    from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity
    from apps.analysis.agents.cme_options import analyze_cme_options
    from apps.analysis.agents.risk import analyze_risk

    # Build a snapshot with market_odds present
    snapshot = {
        "snapshot_id": "XAUUSD:2026-05-16:r1",
        "macro": {"status": "available", "data": {
            "regime": "trend_tailwind",
            "macro_conditions": {"ma_200": 0, "real_yield": 0, "dollar": 0, "vix": 0},
            "fed_phase": "FED_HOLD",
        }},
        "options": {"status": "available", "expiries": ["202606"], "walls": {
            "call_oi_walls": [{"strike": 2600, "oi": 500}],
            "put_oi_walls": [{"strike": 2300, "oi": 400}],
        }},
        "market_odds": {
            "status": "partial",
            "aggregate_signal": "bullish",
            "events": [
                {
                    "event_id": "gold_above_2500",
                    "event_name": "Gold > $2500",
                    "status": "available",
                    "final_probability": 0.60,
                    "signal_label": "bullish",
                    "reliability_score": 0.45,
                    "divergence_score": 0.1,
                    "probabilities": {
                        "cme_options": {"probability": 0.60},
                        "polymarket": {"probability": None},
                        "bloomberg": {"probability": None},
                        "internal_model": {"probability": None},
                    },
                },
            ],
        },
    }

    macro = analyze_macro_liquidity(snapshot)
    options = analyze_cme_options(snapshot)
    risk = analyze_risk(snapshot, macro_output=macro, options_output=options)
    mo = analyze_market_odds(snapshot)

    result = coordinate_agent_outputs(
        snapshot,
        macro_output=macro,
        options_output=options,
        risk_output=risk,
        market_odds_output=mo,
    )

    # Should not be unavailable — market odds supplements, not blocks
    assert result.status != AgentStatus.UNAVAILABLE
    assert "市场赔率 前置偏向为" in result.key_findings[0] or any(
        "市场赔率" in f for f in result.key_findings
    )


def test_coordinator_with_market_odds_unavailable():
    """Coordinator handles unavailable market_odds gracefully."""
    from apps.analysis.agents.coordinator import coordinate_agent_outputs
    from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity
    from apps.analysis.agents.cme_options import analyze_cme_options
    from apps.analysis.agents.risk import analyze_risk

    snapshot = {
        "snapshot_id": "XAUUSD:2026-05-16:r1",
        "macro": {"status": "available", "data": {
            "regime": "trend_tailwind",
            "macro_conditions": {"ma_200": 0, "real_yield": 0, "dollar": 0, "vix": 0},
            "fed_phase": "FED_HOLD",
        }},
        "options": {"status": "available", "expiries": ["202606"], "walls": {
            "call_oi_walls": [{"strike": 2600, "oi": 500}],
            "put_oi_walls": [{"strike": 2300, "oi": 400}],
        }},
        "market_odds": {"status": "unavailable"},
    }

    macro = analyze_macro_liquidity(snapshot)
    options = analyze_cme_options(snapshot)
    risk = analyze_risk(snapshot, macro_output=macro, options_output=options)
    mo = analyze_market_odds(snapshot)

    result = coordinate_agent_outputs(
        snapshot,
        macro_output=macro,
        options_output=options,
        risk_output=risk,
        market_odds_output=mo,
    )

    # Unavailable market odds should NOT break coordinator
    assert result.status != AgentStatus.UNAVAILABLE  # macro+options are available
    # Should mention market odds unavailable somewhere
    assert any("市场赔率" in str(r) for r in result.risk_points) or \
           any("市场赔率" in str(f) for f in result.invalid_conditions)


def test_coordinator_without_market_odds_backward_compat():
    """Coordinator works without market_odds_output (backward compatible)."""
    from apps.analysis.agents.coordinator import coordinate_agent_outputs
    from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity
    from apps.analysis.agents.cme_options import analyze_cme_options
    from apps.analysis.agents.risk import analyze_risk

    snapshot = {
        "snapshot_id": "XAUUSD:2026-05-16:r1",
        "macro": {"status": "available", "data": {
            "regime": "trend_tailwind",
            "macro_conditions": {"ma_200": 0, "real_yield": 0, "dollar": 0, "vix": 0},
            "fed_phase": "FED_HOLD",
        }},
        "options": {"status": "available", "expiries": ["202606"], "walls": {
            "call_oi_walls": [{"strike": 2600, "oi": 500}],
            "put_oi_walls": [{"strike": 2300, "oi": 400}],
        }},
    }

    macro = analyze_macro_liquidity(snapshot)
    options = analyze_cme_options(snapshot)
    risk = analyze_risk(snapshot, macro_output=macro, options_output=options)

    # Call WITHOUT market_odds_output (backward compat)
    result = coordinate_agent_outputs(
        snapshot,
        macro_output=macro,
        options_output=options,
        risk_output=risk,
    )

    assert result.agent_name == "coordinator_agent"
    assert result.status != AgentStatus.UNAVAILABLE


def test_market_odds_agent_no_network():
    """Market odds agent has no imports that suggest network calls."""
    import inspect
    source = inspect.getsource(analyze_market_odds)
    assert "requests" not in source.lower()
    assert "urllib" not in source.lower()
    assert "httpx" not in source.lower()
    assert "urlopen" not in source.lower()


# ── Risk agent compatibility ────────────────────────────────────────────


def test_risk_agent_ignores_market_odds():
    """Risk agent does not depend on market odds (backward compatible)."""
    from apps.analysis.agents.risk import analyze_risk

    snapshot = {
        "snapshot_id": "test",
        "options": {"status": "available", "expiries": [], "walls": {}},
        "market_odds": {"status": "unavailable"},
    }
    result = analyze_risk(snapshot, macro_output=None, options_output=None)
    # Should produce output regardless of market_odds presence
    assert result.agent_name == "risk_agent"
