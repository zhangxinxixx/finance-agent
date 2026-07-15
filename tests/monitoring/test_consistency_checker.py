from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apps.monitoring.consistency_checker import (
    ConsistencyRule,
    MarketConsistencyChecker,
    NumericObservation,
    build_numeric_consistency_check,
)

OBSERVED_AT = datetime(2026, 7, 14, 3, 0, tzinfo=timezone.utc)
RULE = ConsistencyRule(metric="XAUUSD", tolerance_pct=0.5, critical_tolerance_pct=2.0, max_time_gap_minutes=15)


def _observation(*, source: str, value: float, minutes: int = 0) -> NumericObservation:
    return NumericObservation(
        metric="XAUUSD",
        source=source,
        value=value,
        observed_at=OBSERVED_AT + timedelta(minutes=minutes),
        source_ref=f"{source}:XAUUSD",
    )


def test_consistency_check_accepts_time_aligned_values_within_tolerance() -> None:
    check = build_numeric_consistency_check(
        primary=_observation(source="jin10_mcp_market", value=4000.0),
        secondary=_observation(source="yahoo_finance", value=4008.0, minutes=2),
        rule=RULE,
        observed_at=OBSERVED_AT,
    )

    assert check.status == "ok"
    assert check.metadata["comparison_performed"] is True
    assert check.metadata["diff_pct"] < 0.5


def test_consistency_check_degrades_warning_divergence() -> None:
    check = build_numeric_consistency_check(
        primary=_observation(source="jin10_mcp_market", value=4000.0),
        secondary=_observation(source="yahoo_finance", value=4040.0),
        rule=RULE,
        observed_at=OBSERVED_AT,
    )

    assert check.status == "partial"
    assert check.reason_code == "consistency_divergence"
    assert "full_daily_analysis" in check.degraded_capabilities
    assert check.metadata["primary_value"] == 4000.0
    assert check.metadata["secondary_value"] == 4040.0


def test_consistency_check_blocks_critical_divergence() -> None:
    check = build_numeric_consistency_check(
        primary=_observation(source="jin10_mcp_market", value=4000.0),
        secondary=_observation(source="openbb_market", value=4100.0),
        rule=RULE,
        observed_at=OBSERVED_AT,
    )

    assert check.status == "blocked"
    assert check.reason_code == "consistency_critical_divergence"
    assert "daily_market_snapshot" in check.blocked_capabilities


def test_consistency_check_skips_stale_or_same_source_comparisons() -> None:
    stale = build_numeric_consistency_check(
        primary=_observation(source="jin10_mcp_market", value=4000.0),
        secondary=_observation(source="yahoo_finance", value=4100.0, minutes=30),
        rule=RULE,
        observed_at=OBSERVED_AT,
    )
    same_source = build_numeric_consistency_check(
        primary=_observation(source="jin10_mcp_market", value=4000.0),
        secondary=_observation(source="jin10_candle", value=4100.0),
        rule=RULE,
        observed_at=OBSERVED_AT,
    )

    assert stale.status == "waiting"
    assert stale.reason_code == "consistency_time_mismatch"
    assert stale.metadata["comparison_performed"] is False
    assert same_source.status == "waiting"
    assert same_source.reason_code == "consistency_sources_not_independent"


def test_market_consistency_checker_reads_quote_cache_and_candle_payload(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    quote_path = storage_root / "outputs" / "jin10" / "quotes_cache.json"
    quote_path.parent.mkdir(parents=True)
    quote_path.write_text(
        '{"quotes":{"XAUUSD":{"price":4000.0,"time":"2026-07-14T03:00:00+00:00"}}}',
        encoding="utf-8",
    )
    checker = MarketConsistencyChecker(
        storage_root=storage_root,
        candle_loader=lambda: {
            "provider": "yahoo_finance",
            "candles": [{"time": "2026-07-14T03:02:00+00:00", "close": 4004.0}],
            "source_trace": {"primary_source": "market_candles:XAUUSD:1m"},
        },
    )

    checks = checker.run(observed_at=OBSERVED_AT)

    assert len(checks) == 1
    assert checks[0].status == "ok"
    assert checks[0].artifact_refs[0]["path"] == "outputs/jin10/quotes_cache.json"


def test_market_consistency_checker_contains_candle_loader_failure(tmp_path) -> None:
    def failing_loader():
        raise RuntimeError("market database unavailable")

    checks = MarketConsistencyChecker(storage_root=tmp_path / "storage", candle_loader=failing_loader).run(
        observed_at=OBSERVED_AT
    )

    assert len(checks) == 1
    assert checks[0].status == "waiting"
    assert checks[0].reason_code == "consistency_secondary_load_failed"
    assert checks[0].metadata["error_type"] == "RuntimeError"
