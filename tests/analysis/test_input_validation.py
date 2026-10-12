from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.analysis.snapshots.input_validation import prepare_analysis_inputs, research_report_rejection_reasons


def valid_snapshot(storage_root=None):
    cutoff = datetime(2026, 10, 5, 6, 1, tzinfo=timezone.utc)
    ref = {"source": "twelvedata_xauusd_daily", "source_url": "https://example.test/bars", "raw_path": "raw/test.json",
           "retrieved_at": cutoff.isoformat(), "symbol": "XAUUSD", "instrument_type": "spot"}
    bars = []
    for i in range(5):
        closed = cutoff - timedelta(minutes=1 + 15 * (4 - i))
        bars.append({"open_time": (closed - timedelta(minutes=15)).isoformat(), "close_time": closed.isoformat(),
                     "open": 4000 + i, "high": 4002 + i, "low": 3999 + i, "close": 4001 + i})
    frame = {"status": "available", "timeframe": "15m", "interval": "15min", "timezone": "UTC", "ticker": "XAUUSD",
             "instrument_type": "spot", "raw_path": "raw/test.json", "retrieved_at": cutoff.isoformat(),
             "closed_before": (cutoff - timedelta(minutes=1)).isoformat(), "source_refs": [ref], "bars": bars}
    if storage_root is not None:
        archive = storage_root / "raw" / "test.json"
        archive.parent.mkdir(parents=True, exist_ok=True)
        import json
        archive.write_text(json.dumps({"bars": bars}), encoding="utf-8")
    return {"snapshot_id": "test-snapshot", "run_id": "test-run", "asset": "XAUUSD", "trade_date": "2026-10-05",
            "snapshot_time": cutoff.isoformat(), "status": "success", "input_snapshot_ids": {}, "source_refs": [ref],
            "daily_research": {"schema_version": "daily_research.v1", "passport": [],
                "execution_timeframes": {"timeframes": {"15m": frame}}},
            "gold_workflow": {"schema_version": "gold_workflow.v2"}}


def row(**updates):
    return {"symbol": "US10Y", "value": 4.1, "unit": "%", "status": "fresh", "frequency": "daily",
            "observation_date": "2026-10-02", "lineage_status": "verified", "source_refs": [{"source": "fred",
            "source_url": "https://example.test/rates", "raw_path": "raw/rates.json", "retrieved_at": "2026-10-05T06:00:00Z"}], **updates}


def test_native_spot_partial_observation_and_immutability():
    snapshot = valid_snapshot()
    before = deepcopy(snapshot)
    prepared = prepare_analysis_inputs(snapshot)
    assert snapshot == before
    assert prepared["input_validation"]["can_analyze"] is True
    assert prepared["input_validation"]["domains"]["spot"]["completed_timeframes"] == ["15m"]
    assert prepared["daily_research"]["spot_anchor"]["price"] is None
    assert prepare_analysis_inputs(prepared)["input_validation"]["can_analyze"]


@pytest.mark.parametrize("updates,reason", [
    ({"value": float("nan")}, "non_finite_or_missing_value"),
    ({"value": float("inf")}, "non_finite_or_missing_value"),
    ({"source_refs": []}, "unverified_source_lineage"),
    ({"status": "failed"}, "source_failed_or_unavailable"),
    ({"observation_date": "2026-10-06"}, "future_or_invalid_observation_time"),
    ({"observation_date": "2020-01-01"}, "stale_observation"),
    ({"unit": "USD"}, "invalid_unit"),
    ({"retrieved_at": "2026-10-05T10:00:00Z"}, "future_or_invalid_retrieved_at"),
])
def test_rejected_rows_cannot_enter_signals(updates, reason):
    snapshot = valid_snapshot()
    snapshot["daily_research"]["passport"] = [row(**updates)]
    snapshot["daily_research"]["project_signals"] = {"real_rate": {"status": "fresh", "value": 999}}
    snapshot["macro"] = {"status": "available", "data": {"indicators": {"US10Y": {"value": 999}}}}
    prepared = prepare_analysis_inputs(snapshot)
    assert prepared["daily_research"]["passport"][0]["value"] is None
    assert prepared["macro"]["data"]["indicators"] == {}
    assert reason in prepared["input_validation"]["reason_codes"]
    assert prepared["input_validation"]["can_analyze"]  # spot remains usable
    assert prepared["gold_workflow"]["scenario_engine"]["coverage"]["macro"] == 0


@pytest.mark.parametrize("frequency,observed,accepted", [("daily", "2026-09-18", False),
    ("weekly", "2026-09-30", True), ("monthly", "2026-09-01", True), ("monthly", "2025-01-01", False)])
def test_frequency_specific_freshness_and_historical_background(frequency, observed, accepted):
    snapshot = valid_snapshot()
    snapshot["daily_research"]["passport"] = [row(frequency=frequency, observation_date=observed)]
    prepared = prepare_analysis_inputs(snapshot)
    assert (prepared["daily_research"]["passport"][0]["value"] is not None) == accepted
    if not accepted:
        assert prepared["input_validation"]["historical_background"][0]["scope"] == "historical_only"


@pytest.mark.parametrize("field,value", [("ticker", "COMEX:GC1!"), ("instrument_type", "futures"),
    ("retrieved_at", "2026-10-06T06:00:00Z"), ("source_refs", []), ("status", "failed")])
def test_native_bar_rejection_blocks_research(field, value):
    snapshot = valid_snapshot()
    snapshot["daily_research"]["execution_timeframes"]["timeframes"]["15m"][field] = value
    prepared = prepare_analysis_inputs(snapshot)
    assert not prepared["input_validation"]["can_analyze"]
    assert prepared["status"] == "blocked"
    assert prepared["daily_research"]["execution_timeframes"]["timeframes"] == {}


def test_failed_cached_fedwatch_does_not_enter_rebuilt_workflow():
    snapshot = valid_snapshot()
    snapshot["gold_workflow"]["reader_report_version"] = "gold_reader.v4"
    snapshot["macro"] = {"status": "available", "data": {"fedwatch": {"status": "failed", "cached": True,
        "source_health": {"status": "failed"}, "probability": 0.99}}}
    prepared = prepare_analysis_inputs(snapshot)
    assert prepared["macro"]["data"]["fedwatch"]["status"] == "unavailable"
    assert prepared["gold_workflow"]["reader_report_version"] == "gold_reader.v4"
    policy = prepared["gold_workflow"].get("macro_causal", {}).get("engines", {}).get("policy", {})
    assert policy.get("status", "unavailable") != "available"


def test_no_data_blocks_model_before_gateway_creation():
    from apps.analysis.agents.research_synthesis import enrich_research_coordinator
    from tests.analysis.test_research_synthesis import _output
    calls = []
    snapshot = valid_snapshot()
    snapshot["daily_research"]["execution_timeframes"] = {}
    output = enrich_research_coordinator(snapshot, _output(), gateway=lambda **kwargs: calls.append(kwargs))
    assert calls == []
    assert output.input_payload["research_synthesis"]["failure_reason"] == "input_validation_blocked"
    assert output.status.value == "unavailable"
    assert output.input_payload["input_validation"]["can_analyze"] is False


def test_rule_fallback_and_review_rejected_even_with_valid_inputs():
    snapshot = valid_snapshot()
    assert "research_generation_failed" in research_report_rejection_reasons(snapshot, SimpleNamespace(input_payload={"research_synthesis": {"status": "rule_fallback"}}))
    synthesis = {"status": "success", "generated_by": "llm", "analysis": {"dominant_factor": "price observation"},
                 "evidence_ids": ["price"], "macro_review": {"status": "needs_revision"}}
    assert "research_review_not_accepted" in research_report_rejection_reasons(snapshot, SimpleNamespace(input_payload={"research_synthesis": synthesis}))


def test_future_intraday_clock_and_mismatched_components_are_rejected():
    for updates in ({"observation_date": "2026-10-05T12:00:00Z"},
                    {"components": [{"date": "2026-09-30", "value": 2.0}]}):
        snapshot = valid_snapshot()
        snapshot["daily_research"]["passport"] = [row(**updates)]
        derived = prepare_analysis_inputs(snapshot)
        assert derived["daily_research"]["passport"][0]["value"] is None
        assert derived["input_validation"]["field_rejections"]


def test_modified_evidence_cannot_reuse_previous_input_hash():
    prepared = prepare_analysis_inputs(valid_snapshot())
    same = prepare_analysis_inputs(prepared)
    assert same["input_validation"]["input_sha256"] == prepared["input_validation"]["input_sha256"]
    prepared["daily_research"]["execution_timeframes"]["timeframes"]["15m"]["bars"][-1]["close"] = float("nan")
    modified = prepare_analysis_inputs(prepared)
    assert modified["input_validation"]["input_sha256"] != same["input_validation"]["input_sha256"]
    assert not modified["input_validation"]["can_analyze"]
