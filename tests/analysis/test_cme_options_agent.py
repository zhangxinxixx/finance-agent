from __future__ import annotations

import copy
from datetime import datetime, timezone

from apps.analysis.agents import AgentBias, AgentOutput, AgentStatus
from apps.analysis.agents.cme_options import analyze_cme_options


def _available_snapshot() -> dict:
    """Build a test snapshot matching the production {status, data} wrapper."""
    return {
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "input_snapshot_ids": {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "options": "cme-options:2026-05-14",
        },
        "options": {
            "status": "available",
            "data": {
                "data_source": {
                    "status": "FINAL",
                    "source_url": "https://www.cmegroup.com/example/daily-bulletin.pdf",
                    "product": "OG",
                    "expiries": ["JUN26", "JUL26"],
                    "input_snapshot_ids": {"raw_file_sha256": "abc123"},
                },
                "parameters": {"p0": 4200.0, "f_source": "parity_inferred", "used_real_gex": True},
                "gex": {
                    "netgex_aggregate": {
                        "gamma_zero": {"price": 4195.0, "method": "interpolated", "scope": "aggregate_across_expiries"},
                    },
                    "by_expiry": {
                        "JUN26": {
                            "summary": {"net_gex": 1250000.0, "dominant_side": "positive"},
                            "iv_skew": {"risk_reversal_25d": -0.12, "put_call_skew": 0.08},
                        }
                    },
                },
                "wall_scores": [
                    {"strike": 4300, "side": "CALL", "wall_type": "call_resistance", "wall_score": 0.91, "rank": 1},
                    {"strike": 4100, "side": "PUT", "wall_type": "put_support", "wall_score": 0.84, "rank": 2},
                ],
                "walls": {
                    "block_pnt_walls": [
                        {"strike": 4250, "side": "CALL", "block": 12, "pnt": 3, "volume": 120}
                    ]
                },
                "support_resistance": {
                    "support": [{"strike": 4100, "wall_type": "put_support", "wall_score": 0.84}],
                    "resistance": [{"strike": 4300, "wall_type": "call_resistance", "wall_score": 0.91}],
                },
                "intent": {"type": "I2", "score": 0.62, "confidence": 0.72, "evidence": ["call wall dominates"]},
                "exposure": {"JUN26": {"net_delta": 1200.0, "net_vega": 850.0}},
                "roll_signals": [{"roll_type": "near_to_far", "confidence": 0.55}],
                "data_quality": {"categories": {"prelim_data": 0, "proxy_strikes": 1}, "warnings": []},
            },
        },
        "source_refs": [{"source": "cme_daily_bulletin", "url": "https://www.cmegroup.com/example/daily-bulletin.pdf"}],
    }


# Shortcut to access options data inside the wrapper
def _opt_data(snap: dict) -> dict:
    return snap["options"]["data"]


def test_available_options_returns_schema_valid_agent_output_bound_to_snapshot_and_sources():
    created_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    snapshot = _available_snapshot()

    output = analyze_cme_options(snapshot, created_at=created_at)

    assert isinstance(output, AgentOutput)
    assert output.version == "1.0"
    assert output.agent_name == "cme_options_agent"
    assert output.module == "options"
    assert output.snapshot_id == "XAUUSD:2026-05-14:analysis"
    assert output.input_snapshot_ids == {
        "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
        "options": "cme-options:2026-05-14",
    }
    assert output.source_refs == snapshot["source_refs"]
    # With data properly unwrapped, status should be SUCCESS (FINAL source, no quality warnings)
    assert output.status is AgentStatus.SUCCESS
    assert output.bias in {AgentBias.BULLISH, AgentBias.BEARISH, AgentBias.NEUTRAL, AgentBias.MIXED}
    assert 0.0 <= output.confidence <= 1.0
    assert output.created_at == created_at
    assert any("wall" in finding.lower() for finding in output.key_findings)
    assert any("gamma zero" in item.lower() for item in output.watchlist + output.key_findings)
    assert any("IV skew" in finding or "skew" in finding.lower() for finding in output.key_findings)


def test_prelim_source_uncertainty_reduces_confidence_or_records_risk_note():
    snapshot = _available_snapshot()
    _opt_data(snapshot)["data_source"]["status"] = "PRELIM"
    _opt_data(snapshot)["data_quality"]["categories"]["prelim_data"] = 3

    output = analyze_cme_options(snapshot, created_at=datetime(2026, 5, 14, tzinfo=timezone.utc))

    notes = output.risk_points + output.invalid_conditions
    assert output.status is AgentStatus.PARTIAL
    assert output.confidence < 0.75 or any("PRELIM" in note or "prelim" in note.lower() for note in notes)


def test_missing_options_section_returns_unavailable_without_exception():
    output = analyze_cme_options(
        {
            "snapshot_id": "XAUUSD:2026-05-14:missing",
            "input_snapshot_ids": {"analysis_snapshot": "XAUUSD:2026-05-14:missing"},
            "source_refs": [],
        },
        created_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )

    assert output.status is AgentStatus.UNAVAILABLE
    assert output.bias is AgentBias.UNAVAILABLE
    assert output.confidence == 0.0
    assert output.key_findings == []
    assert output.risk_points
    assert output.invalid_conditions


def test_options_status_not_available_returns_unavailable_without_fake_conclusion():
    snapshot = _available_snapshot()
    snapshot["options"] = {"status": "unavailable", "reason": "options_snapshot_missing"}

    output = analyze_cme_options(snapshot, created_at=datetime(2026, 5, 14, tzinfo=timezone.utc))

    assert output.status is AgentStatus.UNAVAILABLE
    assert output.bias is AgentBias.UNAVAILABLE
    assert output.confidence == 0.0
    assert output.summary == "CME options input is unavailable; no read-only conclusion was generated."


def test_analyze_cme_options_rejects_path_like_input_without_file_reads():
    output = analyze_cme_options("storage/features/options/example.json")  # type: ignore[arg-type]

    assert output.status is AgentStatus.UNAVAILABLE
    assert output.bias is AgentBias.UNAVAILABLE
    assert output.confidence == 0.0
    assert "analysis_snapshot" not in output.input_snapshot_ids
    assert any("file/path reads" in note or "文件/路径" in note for note in output.invalid_conditions)


def test_analyze_cme_options_does_not_mutate_input_snapshot():
    snapshot = _available_snapshot()
    before = copy.deepcopy(snapshot)

    analyze_cme_options(snapshot, created_at=datetime(2026, 5, 14, tzinfo=timezone.utc))

    assert snapshot == before


def test_missing_precise_levels_do_not_invent_price_level():
    snapshot = _available_snapshot()
    _opt_data(snapshot)["wall_scores"] = [{"side": "CALL", "wall_type": "call_resistance", "wall_score": 0.77, "rank": 1}]
    _opt_data(snapshot)["support_resistance"] = {"support": [{}], "resistance": [{}]}
    _opt_data(snapshot)["gex"]["netgex_aggregate"]["gamma_zero"] = {"method": "unavailable"}

    output = analyze_cme_options(snapshot, created_at=datetime(2026, 5, 14, tzinfo=timezone.utc))

    combined = "\n".join(output.key_findings + output.watchlist + [output.summary])
    assert "4100" not in combined
    assert "4195" not in combined
    assert "4300" not in combined
    assert any("price" in note.lower() or "level" in note.lower() for note in output.invalid_conditions + output.risk_points)
