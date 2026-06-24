from __future__ import annotations

from pathlib import Path

from apps.features.news.market_binding import archive_market_reactions, build_market_reaction


EVENT = {
    "event_id": "event:hormuz_risk:abc123",
    "event_time": "2026-06-10T08:15:00+00:00",
    "event_type": "hormuz_risk",
    "asset_tags": ["XAUUSD", "WTI", "DXY", "US10Y"],
}

HORMUZ_ASSESSMENT = {
    "event_id": "event:hormuz_risk:abc123",
    "gold_impact": "mixed",
    "dollar_impact": "dollar_strength",
    "yield_impact": "yield_up",
    "oil_impact": "oil_up",
    "pricing_status": "unpriced",
}


def _candle(asset: str, open_time: str, close: float, timeframe: str = "1m") -> dict[str, object]:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "open_time": open_time,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "source": "fixture",
    }


def test_market_reaction_marks_partially_priced_when_expected_assets_move() -> None:
    candles = {
        "WTI": [
            _candle("WTI", "2026-06-10T08:14:00+00:00", 80.0),
            _candle("WTI", "2026-06-10T08:45:00+00:00", 80.7),
            _candle("WTI", "2026-06-10T10:15:00+00:00", 81.0),
        ],
        "DXY": [
            _candle("DXY", "2026-06-10T08:14:00+00:00", 104.0),
            _candle("DXY", "2026-06-10T08:45:00+00:00", 104.15),
            _candle("DXY", "2026-06-10T10:15:00+00:00", 104.28),
        ],
        "US10Y": [
            _candle("US10Y", "2026-06-10T08:14:00+00:00", 4.40),
            _candle("US10Y", "2026-06-10T08:45:00+00:00", 4.45),
            _candle("US10Y", "2026-06-10T10:15:00+00:00", 4.48),
        ],
    }

    reaction = build_market_reaction(EVENT, HORMUZ_ASSESSMENT, candles, windows=("30m", "2h"))
    data = reaction.to_dict()

    assert data["status"] == "available"
    assert data["pricing_status"] == "partially_priced"
    assert data["baseline_time"] == "2026-06-10T08:14:00+00:00"
    assert data["market_snapshot"]["requested_assets"] == ["XAUUSD", "DXY", "US10Y", "WTI", "USDJPY", "Brent", "US02Y"]
    assert data["market_snapshot"]["observed_assets"] == ["DXY", "US10Y", "WTI"]
    assert data["market_snapshot"]["missing_assets"] == ["XAUUSD", "USDJPY", "Brent", "US02Y"]
    assert data["market_snapshot"]["primary_window"] == "30m"
    assert data["windows"]["30m"]["WTI"]["pct_change"] == 0.88
    assert data["windows"]["30m"]["WTI"]["expected_direction"] == "up"
    assert data["windows"]["30m"]["WTI"]["confirms_expected_direction"] is True
    assert data["windows"]["30m"]["DXY"]["threshold_hit"] is True
    assert data["windows"]["30m"]["US10Y"]["change_bp"] == 5.0
    assert data["windows"]["30m"]["US10Y"]["threshold_unit"] == "bp"
    assert data["confirmation_summary"]["confirmed_count"] >= 2


def test_market_reaction_returns_unavailable_without_candles() -> None:
    reaction = build_market_reaction(EVENT, HORMUZ_ASSESSMENT, {}, windows=("30m",))
    data = reaction.to_dict()

    assert data["status"] == "unavailable"
    assert data["pricing_status"] == "unknown"
    assert data["windows"] == {}
    assert data["market_snapshot"]["requested_assets"] == ["XAUUSD", "DXY", "US10Y", "WTI", "USDJPY", "Brent", "US02Y"]
    assert data["market_snapshot"]["missing_assets"] == ["XAUUSD", "DXY", "US10Y", "WTI", "USDJPY", "Brent", "US02Y"]
    assert data["warnings"] == ["No market candles available for event assets."]


def test_market_reaction_marks_contradicted_when_market_moves_against_expected_direction() -> None:
    candles = {
        "WTI": [
            _candle("WTI", "2026-06-10T08:14:00+00:00", 80.0),
            _candle("WTI", "2026-06-10T08:45:00+00:00", 79.2),
        ],
        "DXY": [
            _candle("DXY", "2026-06-10T08:14:00+00:00", 104.0),
            _candle("DXY", "2026-06-10T08:45:00+00:00", 103.8),
        ],
    }

    reaction = build_market_reaction(EVENT, HORMUZ_ASSESSMENT, candles, windows=("30m",))
    data = reaction.to_dict()

    assert data["status"] == "available"
    assert data["pricing_status"] == "contradicted_by_market"
    assert data["market_snapshot"]["primary_window"] == "30m"
    assert data["windows"]["30m"]["WTI"]["direction"] == "down"
    assert data["windows"]["30m"]["WTI"]["contradicts_expected_direction"] is True
    assert data["confirmation_summary"]["contradicted_count"] == 2


def test_market_reaction_uses_default_5m_window_and_observes_usdjpy_in_core_snapshot() -> None:
    candles = {
        "USDJPY": [
            _candle("USDJPY", "2026-06-10T08:14:00+00:00", 156.0),
            _candle("USDJPY", "2026-06-10T08:19:00+00:00", 156.2),
        ],
        "WTI": [
            _candle("WTI", "2026-06-10T08:14:00+00:00", 80.0),
            _candle("WTI", "2026-06-10T08:19:00+00:00", 80.4),
        ],
    }

    reaction = build_market_reaction(EVENT, HORMUZ_ASSESSMENT, candles)
    data = reaction.to_dict()

    assert data["market_snapshot"]["primary_window"] == "5m"
    assert "USDJPY" in data["market_snapshot"]["requested_assets"]
    assert "USDJPY" in data["market_snapshot"]["observed_assets"]
    assert data["windows"]["5m"]["USDJPY"]["direction"] == "up"
    usdjpy_snapshot = next(item for item in data["market_snapshot"]["assets"] if item["asset"] == "USDJPY")
    assert usdjpy_snapshot["status"] == "observed"
    assert usdjpy_snapshot["latest_window"] == "2h"
    assert usdjpy_snapshot["observed_window_count"] == 3


def test_archive_market_reactions_writes_feature_artifact(tmp_path: Path) -> None:
    reaction = build_market_reaction(EVENT, HORMUZ_ASSESSMENT, {}, windows=("30m",))

    artifact_path = archive_market_reactions(
        storage_root=tmp_path,
        retrieved_date="2026-06-10",
        run_id="run-001",
        reactions=[reaction],
    )

    assert artifact_path == "features/news/2026-06-10/run-001/market_reactions.json"
    assert (tmp_path / artifact_path).exists()
    assert '"market_reactions"' in (tmp_path / artifact_path).read_text(encoding="utf-8")
