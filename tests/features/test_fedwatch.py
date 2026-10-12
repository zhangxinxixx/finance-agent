"""Synthetic normalized inputs test formulas; they are not CME captures."""

from copy import deepcopy
from uuid import uuid4

import pytest

from apps.features.macro.fedwatch import build_fedwatch_factors, build_fedwatch_health

NOW = "2026-09-28T12:00:00+00:00"
TARGET = {
    "lower": 3.75,
    "upper": 4,
    "rate_unit": "percent",
    "effective_at": "2026-09-17T00:00:00Z",
    "published_at": "2026-09-16T18:00:00Z",
    "source_refs": [{"source": "synthetic_official_target"}],
}


def snapshot():
    rows = []
    times = {
        "current": "2026-09-28T11:55:00Z",
        "1d": "2026-09-25T11:55:00Z",
        "1w": "2026-09-21T11:55:00Z",
        "1m": "2026-08-28T11:55:00Z",
    }
    for meeting in ("2026-10-28", "2026-12-09", "2027-01-27", "2027-09-15"):
        for window, at in times.items():
            up = 0.6 if window == "current" else 0.4
            for low, high, probability in [(3.75, 4, 1 - up), (4, 4.25, up)]:
                rows.append(
                    dict(
                        meeting_date=meeting,
                        contract_ref=None,
                        comparison_window=window,
                        as_of=at,
                        target_low=low,
                        target_high=high,
                        probability=probability,
                    )
                )
    return {
        "source": "cme_fedwatch_free",
        "snapshot_id": str(uuid4()),
        "collected_at": NOW,
        "as_of": times["current"],
        "source_url": "https://cmegroup-tools.quikstrike.net/",
        "collector_version": "synthetic-test",
        "http_status": 200,
        "content_hash": "a" * 64,
        "raw_artifact_ref": "raw/synthetic.json",
        "parse_status": "ok",
        "reason": None,
        "source_refs": [{"source": "synthetic_fixture", "raw_path": "raw/synthetic.json"}],
        "rows": rows,
        "futures": [],
    }


def test_formulas_units_and_calendar_lookback():
    f = build_fedwatch_factors(snapshot(), as_of=NOW, target_reference=TARGET)
    m = f["market_implied_path"]["next_meeting"]
    assert m["expected_rate_pct"] == pytest.approx(4.025)
    assert m["expected_change_bp"] == pytest.approx(15)
    assert m["expected_hikes_25bp"] == pytest.approx(0.6)
    assert m["expected_cuts_25bp"] == 0
    assert m["hold_probability"] == pytest.approx(0.4)
    assert m["hike_probability"] == pytest.approx(0.6)
    assert m["comparisons"]["1d"]["hike_probability_delta_pp"] == pytest.approx(20)
    assert m["comparisons"]["1d"]["expected_rate_delta_bp"] == pytest.approx(5)
    assert m["comparisons"]["1d"]["elapsed_calendar_days"] == 3
    assert f["repricing"]["direction"] == "hawkish"
    assert f["repricing"]["path_pattern"] == "parallel_path_shift"
    assert f["health"]["last_updated"] == "2026-09-28T11:55:00Z"


def test_year_end_shift_detected_when_next_meeting_flat():
    s = snapshot()
    for r in s["rows"]:
        if r["meeting_date"] == "2026-10-28" and r["comparison_window"] == "current":
            r["probability"] = 0.6 if r["target_low"] == 3.75 else 0.4
    f = build_fedwatch_factors(s, as_of=NOW, target_reference=TARGET)
    assert f["repricing"]["direction"] == "hawkish"
    assert f["repricing"]["meeting_focus"] == "2026-12-09"
    assert f["repricing"]["path_pattern"] == "year_end_terminal_repricing"


def test_missing_target_preserves_market_distribution():
    f = build_fedwatch_factors(snapshot(), as_of=NOW)
    assert f["status"] == "incomplete"
    assert f["market_implied_path"]["next_meeting"]["expected_rate_pct"] > 0
    assert f["market_implied_path"]["next_meeting"]["expected_change_bp"] is None


@pytest.mark.parametrize("mutation", ["nan", "overlap", "gap", "mass", "future", "history", "current_missing"])
def test_bad_inputs_fail_closed(mutation):
    s = snapshot()
    if mutation == "nan":
        s["rows"][0]["probability"] = float("nan")
    elif mutation == "overlap":
        s["rows"][0]["target_high"] = 4.1
    elif mutation == "gap":
        s["rows"][0]["target_high"] = 3.9
    elif mutation == "mass":
        s["rows"][0]["probability"] = 0.9
    elif mutation == "future":
        s["collected_at"] = "2027-01-01T00:00:00Z"
    elif mutation == "history":
        s["rows"][2]["as_of"] = "2026-09-28T11:55:00Z"
    else:
        s["rows"] = [r for r in s["rows"] if r["comparison_window"] != "current"]
    f = build_fedwatch_factors(s, as_of=NOW, target_reference=TARGET)
    assert f["health"]["status"] == "parse_failed"
    assert f["repricing"]["direction"] is None


def test_rounding_and_stale_never_actionable():
    s = snapshot()
    for r in s["rows"]:
        r["probability"] *= 0.999
    f = build_fedwatch_factors(s, as_of=NOW, target_reference=TARGET)
    assert f["market_implied_path"]["next_meeting"]["normalization_applied"]
    f = build_fedwatch_factors(s, as_of="2026-09-28T14:00:00Z", target_reference=TARGET)
    assert f["health"]["status"] == "stale"
    assert f["repricing"]["direction"] is None


def test_no_year_end_or_12m_false_coverage():
    s = snapshot()
    s["rows"] = [r for r in s["rows"] if r["meeting_date"] == "2026-10-28"]
    f = build_fedwatch_factors(s, as_of=NOW, target_reference=TARGET)
    assert f["market_implied_path"]["year_end"] is None
    assert f["market_implied_path"]["horizon12m"]["status"] == "unavailable"


def test_future_target_blocks_direction_and_configurable_health():
    t = deepcopy(TARGET)
    t["effective_at"] = "2027-01-01T00:00:00Z"
    f = build_fedwatch_factors(snapshot(), as_of=NOW, target_reference=t)
    assert f["official_policy"]["status"] == "invalid"
    assert f["repricing"]["direction"] is None
    assert build_fedwatch_health(snapshot(), as_of=NOW, allowed_staleness_seconds=60)["status"] == "stale"
    assert build_fedwatch_health({}, as_of=NOW)["status"] == "missing"


def test_confirmation_does_not_change_score():
    a = build_fedwatch_factors(snapshot(), as_of=NOW, target_reference=TARGET)
    b = build_fedwatch_factors(
        snapshot(),
        as_of=NOW,
        target_reference=TARGET,
        confirmation={"two_year": {"as_of": NOW, "change_bp": -50, "source_refs": [{"source": "synthetic"}]}},
    )
    assert a["repricing"]["score"] == b["repricing"]["score"]
    assert b["confirmation"]["included_in_repricing_score"] is False


def test_state_probabilities_are_not_meeting_actions_and_missing_target_stays_null():
    path = build_fedwatch_factors(snapshot(), as_of=NOW, target_reference=TARGET)["market_implied_path"]
    far = path["meetings"][-1]
    assert far["prob_above_current_target"] == pytest.approx(0.6)
    assert far["prob_below_current_target"] == 0
    assert far["implied_target_midpoint_expected_rate"] == pytest.approx(4.025)
    assert far["comparisons"]["1d"]["prob_above_current_target_delta_pp"] == pytest.approx(20)
    assert path["meeting_action_probabilities"]["status"] == "unavailable"
    unknown = build_fedwatch_factors(snapshot(), as_of=NOW)["market_implied_path"]["next_meeting"]
    assert unknown["prob_below_current_target"] is None
    assert unknown["prob_above_current_target"] is None
    assert unknown["implied_target_midpoint_expected_rate"] == pytest.approx(4.025)


def test_quality_separates_history_gaps_tab_gaps_age_and_archive_proof():
    s = snapshot()
    s["rows"] = [r for r in s["rows"] if not (r["meeting_date"] == "2027-09-15" and r["comparison_window"] == "1m")]
    health = build_fedwatch_health(s, as_of=NOW)
    q = health["quality_summary"]
    assert health["status"] == "fresh"
    assert q["comparison_coverage"] == {"current": 4, "1d": 4, "1w": 4, "1m": 3}
    assert q["probability_row_count"] == 30
    assert q["quality_status"] == "valid_partial_history"
    assert q["missing"] == [{"meeting_date": "2027-09-15", "window": "1m", "availability": "not_provided"}]
    assert q["raw_hash_verified"] is None
    assert q["raw_response_count"] == 0  # fixture reference is not HTTP evidence
    stale = build_fedwatch_health(s, as_of="2026-09-28T14:00:00Z")
    assert stale["status"] == "stale"
    assert stale["quality_summary"] == q
    s["coverage"] = {"all_future_meetings": False, "available_tab_count": 5, "captured_tab_count": 4}
    assert build_fedwatch_health(s, as_of=NOW)["quality_summary"]["quality_status"] == "valid_partial_meetings"
