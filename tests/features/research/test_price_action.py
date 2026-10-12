from datetime import datetime, UTC, timedelta

from apps.features.research.price_action import analyze_bars, cme_weight, build_price_action


def bars(values):
    start = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
    return [
        {
            "open": v,
            "high": v + 1,
            "low": v - 1,
            "close": v,
            "close_time": (start + timedelta(minutes=15 * i)).isoformat(),
        }
        for i, v in enumerate(values)
    ]


def test_pivots_need_right_confirmation_and_prefix_replay():
    seq = bars([5, 6, 10, 7, 6, 4, 6, 7, 12, 8, 7, 5, 7, 8, 14, 2])
    assert not analyze_bars(seq[:4])["pivots"]
    pivot = analyze_bars(seq[:5])["pivots"][0]
    assert pivot["pivot_time"] == seq[2]["close_time"]
    assert pivot["confirmed_at"] == seq[4]["close_time"]
    full = analyze_bars(seq)
    for end in range(5, len(seq)):
        prefix = analyze_bars(seq[:end])
        assert prefix["pivots"] == [p for p in full["pivots"] if p["confirmed_at"] <= seq[end - 1]["close_time"]]
        assert prefix["events"] == [e for e in full["events"] if e["time"] <= seq[end - 1]["close_time"]]
    assert any(e["type"] == "BOS" for e in full["events"])
    assert any(e["type"] == "CHoCH" for e in full["events"])


def test_zone_break_waits_later_retest_and_respects_known_time():
    zone = {
        "price": 11,
        "display_lower": 10,
        "display_upper": 12,
        "role": "support",
        "zone_status": "available",
        "eligible_for_target": True,
    }
    seq = bars([11, 9, 9])
    seq[2].update(high=11, low=8)
    result = analyze_bars(seq, zones=[zone], known_at="2026-09-10T23:00:00Z")["zone_states"][0]
    assert result["state"] == "FLIPPED" and result["role"] == "resistance"
    assert [e["type"] for e in result["events"]][-2:] == ["ZONE_BREAK", "RETEST_FAILED"]
    assert analyze_bars(seq, zones=[zone], known_at=seq[-1]["close_time"])["zone_states"][0]["events"] == []
    assert analyze_bars(seq, zones=[zone])["zone_states"][0]["events"] == []


def test_zone_reclaim_and_no_equal_pivot_invention():
    zone = {
        "price": 11,
        "display_lower": 10,
        "display_upper": 12,
        "role": "support",
        "zone_status": "available",
        "eligible_for_target": True,
    }
    result = analyze_bars(bars([11, 9, 11]), zones=[zone], known_at="2026-09-10T23:00:00Z")
    assert result["zone_states"][0]["state"] == "RECLAIMED"
    assert not analyze_bars(bars([5] * 8))["pivots"]


def test_cme_trading_age_prelim_missing_future_and_weekend():
    options = {
        "status": "available",
        "data": {"data_source": {"report_date": "2026-09-09", "status": "FINAL", "source_refs": [{"source": "cme"}]}},
    }
    assert cme_weight(options, as_of="2026-09-10T16:00:00Z")["weight_multiplier"] == 1
    assert cme_weight(options, as_of="2026-09-11T16:00:00Z")["weight_multiplier"] == 0.5
    result = cme_weight(options, as_of="2026-09-14T16:00:00Z")
    assert result["trading_days"] == 3 and result["weight_multiplier"] == 0.2 and result["role"] == "background_only"
    options["data"]["data_source"]["status"] = "PRELIMINARY"
    assert cme_weight(options, as_of="2026-09-11T16:00:00Z")["weight_multiplier"] == 0.5
    assert cme_weight(options, as_of="2026-09-10T16:00:00Z")["weight_multiplier"] == 1
    options["data"]["data_source"]["status"] = "PRELIM"
    assert cme_weight(options, as_of="2026-09-10T16:00:00Z")["weight_multiplier"] == 1
    options["data"]["data_source"]["status"] = "UNKNOWN"
    assert cme_weight(options, as_of="2026-09-11T16:00:00Z")["weight_multiplier"] == 0.25
    assert cme_weight(options, as_of="2026-09-08T16:00:00Z")["weight_multiplier"] == 0
    assert cme_weight({}, as_of="2026-09-11T16:00:00Z")["weight_multiplier"] == 0
    options["data"]["data_source"]["report_date"] = "2026-09-04"
    assert cme_weight(options, as_of="2026-09-08T16:00:00Z")["trading_days"] == 1


def test_pa_never_enables_five_minute_and_missing_bars_fail_closed():
    result = build_price_action({"trade_date": "2026-09-11", "snapshot_time": "2026-09-11T16:00:00Z"})
    assert set(result["timeframes"]) == {"4h", "1h", "15m"}
    assert not result["five_minute_enabled"]
    assert all(v["status"] == "unavailable" for v in result["timeframes"].values())
