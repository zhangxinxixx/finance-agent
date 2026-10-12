from __future__ import annotations

import pytest

from apps.features.options.reconcile import reconcile_cme_versions
from apps.features.options.selection import select_expiry_window
from apps.analysis.options.snapshot import build_options_snapshot, snapshot_to_dict


def _row(expiry: str, *, oi: int, strike: int = 4200, settlement: float = 10.0) -> dict:
    return {
        "report_date": "2026-09-04",
        "trade_date": "2026-09-04",
        "product_code": "OG",
        "expiry": expiry,
        "strike": strike,
        "option_type": "CALL",
        "open_interest": oi,
        "settlement": settlement,
        "delta": 0.5,
        "oi_change": 0,
    }


def test_expiry_selection_is_dynamic_and_keeps_front_active_expiry() -> None:
    rows = [
        {**_row("SEP26", oi=100), "expiry_date": "2026-09-20"},
        _row("OCT26", oi=900),
        _row("DEC26", oi=3_000),
        _row("AUG26", oi=5_000),  # estimated expiry is before the report date
    ]

    result = select_expiry_window(rows, trade_date="2026-09-04", max_expiries=2)

    assert result.selected_expiries == ["SEP26", "DEC26"]
    assert result.eligible_expiries == ["SEP26", "OCT26", "DEC26"]
    assert result.excluded_expiries["AUG26"] == "expired_before_trade_date"
    assert result.selection_policy["name"] == "nearest_eligible_plus_top_open_interest"
    assert result.selection_policy["front_active_future_expiry"] is None
    assert result.selection_policy["front_active_future_status"] == "unavailable_from_option_rows"
    assert result.selection_policy["available_front_future_expiries"] == []
    assert result.selection_policy["available_option_expiries"] == ["SEP26", "OCT26", "DEC26"]
    assert result.open_interest_coverage == pytest.approx(3_100 / 4_000)
    assert result.row_coverage == pytest.approx(0.5)


def test_reconcile_same_report_date_preserves_final_as_current_and_exposes_delta() -> None:
    prelim = [_row("OCT26", oi=100, settlement=10.0)]
    final = [
        _row("OCT26", oi=120, settlement=11.0),
        _row("DEC26", oi=50, strike=4300),
    ]

    result = reconcile_cme_versions(prelim, final, report_date="2026-09-04")

    assert result["status"] == "final_reconciled"
    assert result["current_selection"] == "FINAL"
    assert result["feature_version"] == "cme_options_analysis.v2"
    assert result["delta"]["changed"] == 1
    assert result["delta"]["added_in_final"] == 1
    assert result["delta"]["changed_fields"] == {"open_interest": 1, "settlement": 1}


def test_reconcile_rejects_neighboring_report_date() -> None:
    with pytest.raises(ValueError, match="does not match report_date"):
        reconcile_cme_versions(
            [_row("OCT26", oi=100)],
            [],
            report_date="2026-09-05",
        )


def test_snapshot_publishes_proxy_semantics_and_signed_leg_fields() -> None:
    rows = [
        _row("OCT26", oi=100, settlement=100.0),
        {**_row("OCT26", oi=200, strike=4300, settlement=20.0), "option_type": "PUT", "delta": 0.4},
    ]
    snapshot = snapshot_to_dict(build_options_snapshot(rows, trade_date="2026-09-04", p0=4200.0))

    assert snapshot["gex_semantics"]["label"] == "OI-Signed GEX Proxy"
    assert snapshot["dealer_position_unknown"] is True
    assert snapshot["gex"]["gamma_flip"]["label"] == "Selected Expiry Window Proxy Gamma Flip"
    assert snapshot["oi_gamma_concentration_zone"]["label"] == "OI/Gamma Concentration Zone"
    top = snapshot["gex"]["by_expiry"]["OCT26"]["gex_top"]
    assert top
    assert all("put_gex_signed" in row and "call_gex_signed" in row for row in top)


def test_snapshot_does_not_call_explicit_partial_expiry_window_full_chain() -> None:
    rows = [_row("OCT26", oi=100), _row("DEC26", oi=200)]
    snapshot = snapshot_to_dict(
        build_options_snapshot(rows, trade_date="2026-09-04", expiries=["OCT26"])
    )

    assert snapshot["expiry_selection"]["selected_is_full_chain"] is False
    assert snapshot["expiry_selection"]["all_expiries"] == ["OCT26", "DEC26"]
    assert snapshot["expiry_selection"]["selection_policy"]["name"] == "caller_supplied"
