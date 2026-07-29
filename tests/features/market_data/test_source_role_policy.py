from __future__ import annotations

import pytest

from apps.features.market_data.source_role_policy import qualify_market_source


def _spot_ref(*, role: str = "market_primary", **extra: object) -> dict[str, object]:
    return {
        "provider_symbol": "XAUUSD",
        "instrument_type": "otc_spot_quote_proxy",
        "source_role": role,
        **extra,
    }


@pytest.mark.parametrize(
    ("source", "source_ref", "quality_status", "normalized_role"),
    [
        ("canonical_xauusd_5m", _spot_ref(), "accepted", "market_primary"),
        (
            "twelvedata_xauusd_5m",
            _spot_ref(role="validation"),
            "observe",
            "validation_fallback",
        ),
        (
            "twelvedata_xauusd_5m",
            _spot_ref(role="fallback"),
            "observe",
            "validation_fallback",
        ),
        ("jin10_mcp_kline_1m", _spot_ref(role="staging_primary"), "blocked", "staging"),
        ("jin10_quote", _spot_ref(role="supplemental"), "blocked", "supplemental"),
        ("jin10_news", _spot_ref(), "blocked", "news"),
        ("unknown", _spot_ref(role="unknown"), "blocked", "unknown"),
    ],
)
def test_xauusd_source_role_matrix(
    source: str, source_ref: dict[str, object], quality_status: str, normalized_role: str
) -> None:
    result = qualify_market_source(asset="XAUUSD", source=source, source_ref=source_ref)
    assert result.quality_status == quality_status
    assert result.normalized_role == normalized_role


def test_xauusd_rejects_futures_before_role_can_make_it_primary() -> None:
    result = qualify_market_source(
        asset="XAUUSD",
        source="yahoo_finance_gc_f",
        source_ref={
            "provider_symbol": "GC=F",
            "instrument_type": "futures_continuous_proxy",
            "source_role": "market_primary",
        },
    )
    assert result.quality_status == "blocked"
    assert result.reason_code == "futures_instrument_blocked"


def test_twelvedata_never_becomes_xauusd_market_primary() -> None:
    result = qualify_market_source(
        asset="XAUUSD",
        source="twelvedata_xauusd_5m",
        source_ref=_spot_ref(role="market_primary"),
    )
    assert (result.quality_status, result.reason_code) == (
        "blocked",
        "twelvedata_cannot_be_market_primary",
    )


def test_gc_is_accepted_only_as_known_yahoo_futures_identity() -> None:
    accepted = qualify_market_source(
        asset="GC",
        source="yahoo_finance_gc_f",
        source_ref={
            "provider_symbol": "GC=F",
            "instrument_type": "futures_continuous_proxy",
            "source_role": "market_primary",
        },
    )
    rejected = qualify_market_source(
        asset="GC",
        source="unknown",
        source_ref={
            "provider_symbol": "GC=F",
            "instrument_type": "futures_continuous_proxy",
        },
    )
    assert accepted.quality_status == "accepted"
    assert accepted.normalized_role == "futures_continuous_proxy"
    assert rejected.quality_status == "blocked"


@pytest.mark.parametrize("asset", ["WTI", "BRENT"])
def test_oil_source_role_matrix(asset: str) -> None:
    primary = qualify_market_source(
        asset=asset,
        source="oil_market",
        source_ref={"source_role": "oil_primary", "instrument_type": "spot"},
    )
    fallback = qualify_market_source(
        asset=asset,
        source="oil_validation",
        source_ref={"source_role": "fallback", "instrument_type": "spot"},
    )
    supplemental = qualify_market_source(
        asset=asset,
        source="news", source_ref={"source_role": "supplemental", "instrument_type": "spot"},
    )
    benchmark_futures = qualify_market_source(
        asset=asset,
        source="official_benchmark_futures",
        source_ref={"source_role": "oil_primary", "instrument_type": "futures_benchmark"},
    )
    assert primary.quality_status == "accepted"
    assert fallback.quality_status == "observe"
    assert supplemental.quality_status == "blocked"
    assert benchmark_futures.quality_status == "accepted"


def test_unqualified_jin10_usoil_quote_stays_blocked() -> None:
    result = qualify_market_source(
        asset="WTI",
        source="jin10_mcp",
        source_ref={"provider_symbol": "USOIL", "instrument_type": "quote"},
    )
    assert (result.quality_status, result.normalized_role) == ("blocked", "unknown")


def test_same_input_is_deterministic_and_output_is_frozen() -> None:
    source_ref = _spot_ref()
    results = [
        qualify_market_source(asset="XAUUSD", source="canonical_xauusd_5m", source_ref=source_ref)
        for _ in range(100)
    ]
    assert len(set(results)) == 1
    with pytest.raises(Exception):
        results[0].quality_status = "blocked"  # type: ignore[misc]
