from __future__ import annotations

import json
from pathlib import Path

from apps.analysis.options.decision import SCHEMA_VERSION, build_options_decision


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/options/decision_rows_2026-07-15.json"


def _rows() -> dict[str, list[dict]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _snapshot(*, gamma_zero: float | None = 4144.7, net_gex: float = -123.0) -> dict:
    return {
        "trade_date": "2026-07-15",
        "data_source": {"product": "OG", "status": "FINAL"},
        "parameters": {
            "report_p0": 4052.0,
            "report_p0_source": "CME settlement",
            "model_f": {"AUG26": 4141.0, "SEP26": 4148.0},
        },
        "gex": {
            "netgex_aggregate": {
                "net_gex": net_gex,
                "gamma_zero": {"price": gamma_zero, "method": "interpolated"},
                "price_grid": [4100, 4125, 4150, 4175],
                "net_gex_values": [-20, -10, 10, 20],
            }
        },
        "support_resistance": {
            "support": [{"strike": 4000, "wall_score": 8.0}],
            "resistance": [{"strike": 4200, "wall_score": 7.5}],
        },
        "wall_scores": [
            {
                "strike": 4050,
                "expiry": "AUG26",
                "wall_type": "pin",
                "dominant_side": "Put",
                "oi": 2200,
                "gex": 90.0,
                "net_gex": -10.0,
                "wall_score": 0.75,
            },
            {
                "strike": 4000,
                "expiry": "AUG26",
                "wall_type": "active",
                "dominant_side": "Put",
                "oi": 5200,
                "gex": 200.0,
                "net_gex": -120.0,
                "wall_score": 0.9,
            },
            {
                "strike": 3900,
                "expiry": "AUG26",
                "wall_type": "active",
                "dominant_side": "Put",
                "oi": 2800,
                "gex": 70.0,
                "net_gex": -45.0,
                "wall_score": 0.6,
            },
            {
                "strike": 4200,
                "expiry": "AUG26",
                "wall_type": "turnover",
                "dominant_side": "Call",
                "oi": 4000,
                "gex": 110.0,
                "net_gex": 35.0,
                "wall_score": 0.7,
            },
        ],
        "intent": {
            "type": "I1_defensive",
            "score": 0.55,
            "confidence": 0.55,
            "evidence": ["put protection remains active"],
        },
        "audit": {
            "intent_audit": {
                "wording": "I1 防守型",
                "defense_score": 0.55,
                "rebalance_score": 0.41,
                "trap_score": 0.20,
                "trend_score": 0.35,
            }
        },
        "source_trace": [{"name": "CME", "source_ref": "cme://bulletin", "file": "storage/raw/cme.pdf"}],
    }


def test_decision_builds_cross_month_oi_roll_and_negative_gamma() -> None:
    rows = _rows()
    rows["2026-07-15"][0]["pnt_volume"] = 150
    rows["2026-07-15"][0]["total_volume"] = 180
    result = build_options_decision(
        _snapshot(),
        current_rows=rows["2026-07-15"],
        previous_rows=rows["2026-07-14"],
        previous_snapshot=_snapshot(gamma_zero=4146.9, net_gex=-100.0),
        history_rows_by_date=rows,
        live_price_context={"price": 4130.0, "timestamp": "2026-07-15T12:00:00Z", "source": "canonical"},
        lookback_days=5,
    )

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["status"] == "available"
    assert result["meta"] == {
        "current_trade_date": "2026-07-15",
        "previous_trade_date": "2026-07-14",
        "product": "OG",
        "lookback_days": 5,
        "comparison_status": "available",
    }
    assert result["oi_summary"]["total"] == {
        "current": 328499.0,
        "previous": 327456.0,
        "delta": 1043.0,
        "pct_change": 1043.0 / 327456.0 * 100,
    }
    aug, sep = result["oi_by_expiry"]
    assert aug["expiry"] == "AUG26" and aug["total"]["current"] == 215236.0 and aug["total"]["delta"] == -254.0
    assert sep["expiry"] == "SEP26" and sep["total"]["current"] == 113263.0 and sep["total"]["delta"] == 1297.0
    roll = result["roll_summary"]["items"][0]
    assert {"near_month_outflow", "far_month_inflow", "put_dominant_roll"} <= set(roll["labels"])
    assert result["gamma_summary"]["regime"] == "negative_gamma"
    assert result["gamma_summary"]["flip_band"] == {"lower": 4132.2, "upper": 4157.2, "step": 25.0}
    assert result["intraday_strategy"]["status"] == "available"
    assert result["intraday_strategy"]["long_setup"]["triggers"]
    assert result["intraday_strategy"]["short_setup"]["invalidation"]
    assert result["swing_strategy"]["status"] == "available"
    assert result["gamma_changes"]["gamma_zero_change_1d"] == 4144.7 - 4146.9
    assert result["gamma_changes"]["net_gex_change_1d"] == -23.0
    assert result["large_oi_levels"]
    assert result["nearby_large_oi_levels"]
    assert all(abs(item["distance_pct"]) <= 6.0 for item in result["nearby_large_oi_levels"])
    assert [item["total_oi"] for item in result["large_oi_levels"]] == sorted(
        (item["total_oi"] for item in result["large_oi_levels"]), reverse=True
    )
    assert {"expiry", "strike", "call_oi", "put_oi", "total_oi", "total_oi_change", "volume"} <= set(
        result["large_oi_levels"][0]
    )
    assert result["pnt_summary"]["status"] == "available"
    assert result["pnt_summary"]["totals"]["total"] == 150.0
    assert result["pnt_summary"]["pnt_totals"]["total"] == 150.0
    assert result["pnt_summary"]["block_totals"]["total"] == 0.0
    assert result["pnt_summary"]["block_coverage_status"] == "not_verified"
    assert result["data_quality"]["position_reference_source"] == "report_p0"
    assert result["data_quality"]["position_reference_price"] == 4052.0
    assert result["data_quality"]["warnings"]
    assert any(item["volume"] >= 180.0 for item in result["large_oi_levels"])
    assert result["intent_summary"]["type"] == "I1_defensive"
    assert result["structure_summary"]["state"] == "negative_gamma_defensive"
    assert result["structure_summary"]["repair_detected"] is False
    assert {path["path_id"] for path in result["scenario_paths"]} == {
        "base_repair_range",
        "bullish_acceptance",
        "bearish_breakdown",
    }
    roles = {level["role"] for level in result["key_levels"]}
    assert {
        "primary_support",
        "primary_resistance",
        "magnet_pin",
        "volatility_hub",
        "gamma_flip",
        "tail_protection",
    } <= roles
    assert all(level["evidence"] and level["invalidation"] for level in result["key_levels"])
    assert result["source_refs"][-1]["source_ref"].startswith("/api/options/decision")


def test_flip_zone_strategy_does_not_claim_positive_gamma() -> None:
    rows = _rows()
    result = build_options_decision(
        _snapshot(),
        current_rows=rows["2026-07-15"],
        previous_rows=rows["2026-07-14"],
        history_rows_by_date=rows,
        live_price_context={
            "price": 4144.7,
            "timestamp": "2026-07-15T12:00:00Z",
            "status": "fresh",
            "coverage_status": "complete",
        },
    )

    assert result["gamma_summary"]["regime"] == "flip_zone"
    assert result["intraday_strategy"]["bias"] == "flip_watch"
    assert "gamma-flip regime" in result["intraday_strategy"]["summary"]
    assert "positive-gamma" not in result["intraday_strategy"]["summary"]


def test_decision_degrades_without_previous_live_gamma_or_history() -> None:
    rows = _rows()
    result = build_options_decision(
        _snapshot(gamma_zero=None),
        current_rows=rows["2026-07-15"],
        previous_rows=None,
        history_rows_by_date={
            "2026-07-15": rows["2026-07-15"],
            "2026-07-14": rows["2026-07-14"],
        },
    )

    assert result["status"] == "partial"
    assert result["oi_summary"]["comparison_status"] == "unavailable"
    assert result["oi_summary"]["total"]["previous"] is None
    assert result["oi_summary"]["put"]["delta"] is None
    assert result["gamma_summary"]["regime"] == "unavailable"
    assert result["intraday_strategy"]["status"] == "unavailable"
    assert result["swing_strategy"] == {
        "status": "unavailable",
        "reason": "insufficient_history",
        "sample_count": 2,
        "required_sample_count": 3,
    }
    assert all(item["total_oi_change"] is None for item in result["large_oi_levels"])
    assert result["scenario_paths"] == []


def test_decision_does_not_use_snapshot_live_price_as_canonical_live_context() -> None:
    rows = _rows()
    snapshot = _snapshot()
    snapshot["parameters"]["live_p0"] = 4130.0
    snapshot["parameters"]["live_p0_source"] = "stale_snapshot"

    result = build_options_decision(
        snapshot,
        current_rows=rows["2026-07-15"],
        previous_rows=rows["2026-07-14"],
        history_rows_by_date=rows,
    )

    assert result["price_context"]["live_p0"] is None
    assert result["gamma_summary"]["regime"] == "unavailable"
    assert result["intraday_strategy"]["status"] == "unavailable"
    assert len(result["scenario_paths"]) == 3
    assert result["large_oi_levels"][0]["distance_pct"] is not None


def test_decision_disables_intraday_for_stale_live_price_and_reclassifies_fresh_levels() -> None:
    rows = _rows()
    stale = build_options_decision(
        _snapshot(),
        current_rows=rows["2026-07-15"],
        previous_rows=rows["2026-07-14"],
        history_rows_by_date=rows,
        live_price_context={
            "price": 4210.0,
            "timestamp": "2026-07-15T10:00:00Z",
            "status": "stale",
            "freshness_seconds": 7200,
            "coverage_status": "complete",
        },
    )
    fresh = build_options_decision(
        _snapshot(),
        current_rows=rows["2026-07-15"],
        previous_rows=rows["2026-07-14"],
        history_rows_by_date=rows,
        live_price_context={
            "price": 4210.0,
            "timestamp": "2026-07-15T12:00:00Z",
            "status": "fresh",
            "freshness_seconds": 30,
            "coverage_status": "complete",
        },
    )

    assert stale["price_context"]["live_price_status"] == "stale"
    assert stale["intraday_strategy"]["status"] == "unavailable"
    resistance = next(level for level in fresh["key_levels"] if level["structural_role_at_report"] == "primary_resistance")
    assert resistance["current_relation"] == "below_price"
    assert resistance["dynamic_role"] == "retest_support_candidate"
