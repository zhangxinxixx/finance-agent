from __future__ import annotations

from apps.collectors.fred.collector import FRED_SERIES


def test_fred_default_series_include_formal_gold_macro_inputs() -> None:
    assert {"DGS30", "DFII10", "DTWEXBGS"}.issubset(FRED_SERIES)
