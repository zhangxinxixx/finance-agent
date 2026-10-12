from __future__ import annotations

import json
from pathlib import Path

from apps.analysis.options.snapshot import build_options_snapshot, snapshot_to_dict
from apps.features.options.selection import select_expiry_window


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "cme" / "versioned_option_rows.json"


def _row(expiry: str, *, oi: int, expiry_date: str) -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"][0]
    return {
        **payload,
        "expiry": expiry,
        "expiry_date": expiry_date,
        "open_interest": oi,
        "report_date": "2026-09-04",
        "trade_date": "2026-09-04",
        "product_code": "OG",
    }


def test_selection_keeps_nearest_plus_top_two_oi_as_union() -> None:
    rows = [
        _row("SEP26", oi=100, expiry_date="2026-09-20"),
        _row("OCT26", oi=900, expiry_date="2026-10-20"),
        _row("DEC26", oi=3000, expiry_date="2026-12-20"),
    ]

    result = select_expiry_window(rows, trade_date="2026-09-04", max_expiries=3, top_n_oi=2)

    assert result.selected_expiries == ["SEP26", "OCT26", "DEC26"]
    assert result.selection_policy["union_selection"]["is_truncated"] is False
    assert result.selection_policy["top_n_oi_included"] == ["DEC26", "OCT26"]


def test_option_rows_never_infer_front_gc_future() -> None:
    rows = [{**_row("OCT26", oi=100, expiry_date="2026-10-20"), "front_active_future_expiry": "OCT26"}]

    result = select_expiry_window(rows, trade_date="2026-09-04", max_expiries=3, top_n_oi=2)

    policy = result.selection_policy
    assert policy["front_active_future_expiry"] is None
    assert policy["front_active_future_status"] == "unavailable_from_option_rows"
    assert policy["front_active_future_inference"] is False


def test_shape_proxy_is_not_reported_as_usd_gex() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = [
        {
            **fixture["rows"][0],
            "report_date": fixture["trade_date"],
            "trade_date": fixture["trade_date"],
            "product_code": fixture["product"],
        },
        {
            **fixture["rows"][1],
            "settlement": None,
            "report_date": fixture["trade_date"],
            "trade_date": fixture["trade_date"],
            "product_code": fixture["product"],
        },
    ]
    result = build_options_snapshot(rows, trade_date=fixture["trade_date"], p0=4500.0)
    proxy = next(item for item in result.exposures if item.method == "proxy")
    payload = snapshot_to_dict(result)

    assert proxy.gex_1pct == 0.0
    assert proxy.shape_proxy_oi and proxy.shape_proxy_oi > 0
    assert proxy.gex_unit == "unavailable_for_shape_proxy"
    assert payload["gex_semantics"]["shape_proxy_included_in_usd_gex"] is False
    assert payload["audit"]["data_audit"]["shape_proxy_oi_total"] > 0
    assert payload["audit"]["gex_audit"]["proxy_included_in_zero"] is False
