from __future__ import annotations

import pytest

from database.market_identity import normalize_market_candle_identity


def test_gc_f_passed_as_xauusd_is_reclassified_to_gc() -> None:
    identity = normalize_market_candle_identity(
        asset="XAUUSD",
        source="yahoo_finance_1m",
        source_ref={"provider_symbol": "GC=F"},
    )

    assert identity.asset == "GC"
    assert identity.reclassified_from == "XAUUSD"
    assert identity.source_ref["instrument_type"] == "futures_continuous_proxy"
    assert identity.source_ref["identity_guard"] == "reclassified_xauusd_futures"


def test_gc_f_source_cannot_enter_xauusd_identity() -> None:
    identity = normalize_market_candle_identity(
        asset="XAUUSD",
        source="yahoo_finance_gc_f",
        source_ref={},
    )

    assert identity.asset == "GC"
    assert identity.source_ref["provider_symbol"] == "GC=F"


def test_unknown_futures_identity_fails_closed() -> None:
    with pytest.raises(ValueError, match="asset=XAUUSD"):
        normalize_market_candle_identity(
            asset="XAUUSD",
            source="openbb_futures",
            source_ref={"instrument_type": "futures_contract"},
        )
