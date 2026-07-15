from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

from scripts.run_options_analysis import _fetch_jin10_quote_p0, _resolve_analysis_expiries


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


def test_fetch_jin10_quote_requires_configured_command(monkeypatch) -> None:
    monkeypatch.delenv("JIN10_QUOTE_COMMAND", raising=False)

    assert _fetch_jin10_quote_p0("XAUUSD", "close") == (
        None,
        None,
        ["jin10_mcp_not_configured"],
    )


def test_fetch_jin10_quote_uses_json_command(monkeypatch, tmp_path: Path) -> None:
    quote_script = tmp_path / "quote.py"
    quote_script.write_text(
        "import json, sys\n"
        "print(json.dumps({'value': 2401.5, 'time': '2026-07-20T12:00:00Z', "
        "'code': sys.argv[1], 'field': sys.argv[2]}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JIN10_QUOTE_COMMAND", f"{sys.executable} {quote_script}")

    value, quote_time, warnings = _fetch_jin10_quote_p0("XAUUSD", "close")

    assert value == 2401.5
    assert quote_time == "2026-07-20T12:00:00Z"
    assert warnings == ["jin10_quote_code:XAUUSD", "jin10_quote_field:close"]
