from datetime import date

from dagster_finance.graphs.premarket import _resolve_analysis_trade_date


def test_analysis_trade_date_uses_freshest_source_anchor() -> None:
    trade_date = _resolve_analysis_trade_date(
        macro_snapshot={"as_of": "2026-07-17"},
        options_snapshot={"trade_date": "2026-07-15"},
        news_snapshot={"daily_market_brief": {"as_of": "2026-07-17T02:34:58+00:00"}},
        fallback_date=date(2026, 7, 18),
    )

    assert trade_date == "2026-07-17"


def test_analysis_trade_date_falls_back_to_options_when_other_sources_are_missing() -> None:
    trade_date = _resolve_analysis_trade_date(
        macro_snapshot=None,
        options_snapshot={"trade_date": "2026-07-15"},
        news_snapshot=None,
        fallback_date=date(2026, 7, 18),
    )

    assert trade_date == "2026-07-15"


def test_analysis_trade_date_uses_fallback_when_source_dates_are_invalid() -> None:
    trade_date = _resolve_analysis_trade_date(
        macro_snapshot={"as_of": "unknown"},
        options_snapshot={},
        news_snapshot={"daily_brief_input_snapshot": {"retrieved_date": None}},
        fallback_date=date(2026, 7, 18),
    )

    assert trade_date == "2026-07-18"
