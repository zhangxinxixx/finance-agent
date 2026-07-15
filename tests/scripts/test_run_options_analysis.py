from __future__ import annotations

from argparse import Namespace

from scripts.run_options_analysis import _resolve_analysis_expiries


def test_resolve_analysis_expiries_defaults_to_nearest_two() -> None:
    args = Namespace(product="OG", trade_date="2026-06-04", expiries=None, all_expiries=False)
    rows = [
        {"product_code": "OG", "trade_date": "2026-06-04", "expiry": "DEC26"},
        {"product_code": "OG", "trade_date": "2026-06-04", "expiry": "JUL26"},
        {"product_code": "OG", "trade_date": "2026-06-04", "expiry": "AUG26"},
        {"product_code": "OG", "trade_date": "2026-06-04", "expiry": "SEP26"},
        {"product_code": "OG", "trade_date": "2026-06-03", "expiry": "JUN26"},
    ]

    assert _resolve_analysis_expiries(args, rows) == ["JUL26", "AUG26"]


def test_resolve_analysis_expiries_all_expiries_keeps_unfiltered_mode() -> None:
    args = Namespace(product="OG", trade_date="2026-06-04", expiries=None, all_expiries=True)

    assert _resolve_analysis_expiries(args, []) is None


def test_resolve_analysis_expiries_prefers_explicit_cli_value() -> None:
    args = Namespace(product="OG", trade_date="2026-06-04", expiries="SEP26, DEC26", all_expiries=False)

    assert _resolve_analysis_expiries(args, []) == ["SEP26", "DEC26"]
