"""Tests for CME option structure engine."""

from __future__ import annotations

from apps.features.options import (
    IntentType,
    OptionExposure,
    RollType,
    StrikeMetrics,
    Wall,
    WallType,
    aggregate_strike_metrics,
    classify_intent,
    classify_walls,
    detect_rolls,
    score_walls,
)
from apps.features.options.normalize import normalize_option_rows


def _row(
    *,
    trade_date: str = "2026-05-06",
    report_date: str = "2026-05-06",
    expiry: str = "JUN26",
    strike: int = 4200,
    option_type: str = "CALL",
    settlement: float | None = 100.0,
    delta: float | None = 0.5,
    open_interest: int | None = 1000,
    oi_change: int | None = 10,
    total_volume: int | None = 200,
    block_volume: int | None = 20,
    pnt_volume: int | None = 5,
    globex_volume: int | None = 100,
    outcry_volume: int | None = 50,
    exercises: int | None = 0,
    pt_change: float | None = 1.0,
) -> dict:
    return {
        "trade_date": trade_date,
        "report_date": report_date,
        "product_code": "OG",
        "expiry": expiry,
        "strike": strike,
        "option_type": option_type,
        "settlement": settlement,
        "delta": delta,
        "open_interest": open_interest,
        "oi_change": oi_change,
        "total_volume": total_volume,
        "block_volume": block_volume,
        "pnt_volume": pnt_volume,
        "globex_volume": globex_volume,
        "outcry_volume": outcry_volume,
        "exercises": exercises,
        "pt_change": pt_change,
    }


def _metric(
    *,
    strike: int,
    expiry: str = "JUN26",
    trade_date: str = "2026-05-06",
    call_oi: int = 0,
    put_oi: int = 0,
    call_oi_change: int = 0,
    put_oi_change: int = 0,
    call_volume: int = 0,
    put_volume: int = 0,
    call_block: int = 0,
    put_block: int = 0,
    call_pnt: int = 0,
    put_pnt: int = 0,
    call_gex: float = 0.0,
    put_gex: float = 0.0,
    call_delta_exposure: float = 0.0,
    put_delta_exposure: float = 0.0,
    data_quality: list[str] | None = None,
) -> StrikeMetrics:
    return StrikeMetrics(
        strike=strike,
        expiry=expiry,
        call_oi=call_oi,
        put_oi=put_oi,
        call_oi_change=call_oi_change,
        put_oi_change=put_oi_change,
        call_volume=call_volume,
        put_volume=put_volume,
        call_block=call_block,
        put_block=put_block,
        call_pnt=call_pnt,
        put_pnt=put_pnt,
        call_gex=call_gex,
        put_gex=put_gex,
        net_gex=call_gex - put_gex,
        call_delta_exposure=call_delta_exposure,
        put_delta_exposure=put_delta_exposure,
        total_oi=call_oi + put_oi,
        total_volume=call_volume + put_volume,
        trade_date=trade_date,
        data_quality=list(data_quality or []),
    )


def _exposure(
    strike: int,
    option_type: str,
    *,
    gex: float,
    delta_exposure: float,
    trade_date: str = "2026-05-06",
    expiry: str = "JUN26",
    data_quality: list[str] | None = None,
) -> OptionExposure:
    return OptionExposure(
        strike=strike,
        option_type=option_type,
        iv=0.25,
        gamma=1.0,
        gex_1pct=gex,
        delta_exposure=delta_exposure,
        vega_exposure_1vol=0.0,
        theta_exposure_day=0.0,
        method="manual",
        data_quality=list(data_quality or []),
        trade_date=trade_date,
        expiry=expiry,
    )


def test_aggregate_strike_metrics() -> None:
    rows = [
        _row(strike=4000, option_type="CALL", open_interest=100, oi_change=5, total_volume=10, block_volume=2, pnt_volume=1),
        _row(strike=4000, option_type="PUT", open_interest=80, oi_change=-3, total_volume=8, block_volume=1, pnt_volume=2),
        _row(strike=4100, option_type="CALL", open_interest=120, oi_change=7, total_volume=12, block_volume=3, pnt_volume=0),
        _row(strike=4100, option_type="PUT", open_interest=90, oi_change=4, total_volume=9, block_volume=0, pnt_volume=1),
    ]
    normalized, _ = normalize_option_rows(rows, filter_strikes=False, aggregate_duplicates=False)
    exposures = [
        _exposure(4000, "CALL", gex=11.0, delta_exposure=1.5),
        _exposure(4000, "PUT", gex=4.0, delta_exposure=0.5),
        _exposure(4100, "CALL", gex=13.0, delta_exposure=2.5),
        _exposure(4100, "PUT", gex=6.0, delta_exposure=0.75),
    ]

    metrics = aggregate_strike_metrics(normalized, exposures)

    assert [metric.strike for metric in metrics] == [4000, 4100]
    first = metrics[0]
    assert first.expiry == "JUN26"
    assert first.call_oi == 100
    assert first.put_oi == 80
    assert first.call_oi_change == 5
    assert first.put_oi_change == -3
    assert first.call_volume == 10
    assert first.put_volume == 8
    assert first.call_block == 2
    assert first.put_block == 1
    assert first.call_pnt == 1
    assert first.put_pnt == 2
    assert first.call_gex == 11.0
    assert first.put_gex == 4.0
    assert first.net_gex == 7.0
    assert first.call_delta_exposure == 1.5
    assert first.put_delta_exposure == 0.5
    assert first.total_oi == 180
    assert first.total_volume == 18
    assert first.trade_date == "2026-05-06"


def test_aggregate_strike_metrics_scoped_exposures_do_not_leak_across_expiry() -> None:
    rows = [
        _row(expiry="JUN26", strike=4000, option_type="CALL", open_interest=100, oi_change=5, total_volume=10),
        _row(expiry="JUN26", strike=4000, option_type="PUT", open_interest=80, oi_change=-3, total_volume=8),
        _row(expiry="JUL26", strike=4000, option_type="CALL", open_interest=120, oi_change=7, total_volume=12),
        _row(expiry="JUL26", strike=4000, option_type="PUT", open_interest=90, oi_change=4, total_volume=9),
    ]
    normalized, _ = normalize_option_rows(rows, filter_strikes=False, aggregate_duplicates=False)
    exposures = [
        _exposure(4000, "CALL", gex=11.0, delta_exposure=1.5, expiry="JUN26"),
        _exposure(4000, "PUT", gex=4.0, delta_exposure=0.5, expiry="JUN26"),
        _exposure(4000, "CALL", gex=31.0, delta_exposure=2.5, expiry="JUL26"),
        _exposure(4000, "PUT", gex=7.0, delta_exposure=0.75, expiry="JUL26"),
    ]

    metrics = aggregate_strike_metrics(normalized, exposures)

    jun = next(metric for metric in metrics if metric.expiry == "JUN26")
    jul = next(metric for metric in metrics if metric.expiry == "JUL26")

    assert jun.call_gex == 11.0
    assert jun.put_gex == 4.0
    assert jul.call_gex == 31.0
    assert jul.put_gex == 7.0


def test_aggregate_strike_metrics_ignores_unscoped_exposure_across_expiry() -> None:
    rows = [
        _row(expiry="JUN26", strike=4000, option_type="CALL", open_interest=100, oi_change=5, total_volume=10),
        _row(expiry="JUL26", strike=4000, option_type="CALL", open_interest=120, oi_change=7, total_volume=12),
    ]
    normalized, _ = normalize_option_rows(rows, filter_strikes=False, aggregate_duplicates=False)
    exposures = [
        _exposure(4000, "CALL", gex=11.0, delta_exposure=1.5, trade_date="", expiry=""),
    ]

    metrics = aggregate_strike_metrics(normalized, exposures)

    assert all(metric.call_gex == 0.0 for metric in metrics)
    assert all("unscoped_exposure_ignored_for_multi_expiry" in metric.data_quality for metric in metrics)


def test_classify_walls_active() -> None:
    metrics = [
        _metric(strike=4000, call_oi=2400, put_oi=1800, call_oi_change=240, put_oi_change=120, call_volume=260, put_volume=220, call_block=40, put_block=20, call_pnt=10, put_pnt=5),
        _metric(strike=4100, call_oi=200, put_oi=120, call_volume=10, put_volume=8),
        _metric(strike=4200, call_oi=250, put_oi=130, call_volume=12, put_volume=8),
    ]

    walls = classify_walls(metrics, current_price=4050.0)
    active = next(wall for wall in walls if wall.strike == 4000)

    assert active.wall_type == WallType.ACTIVE
    assert any("total_oi" in item for item in active.evidence)


def test_classify_walls_static() -> None:
    metrics = [
        _metric(strike=4000, call_oi=3000, put_oi=700, call_oi_change=2, put_oi_change=-1, call_volume=10, put_volume=8),
        _metric(strike=4100, call_oi=220, put_oi=100, call_volume=120, put_volume=100),
        _metric(strike=4200, call_oi=240, put_oi=120, call_volume=100, put_volume=90),
    ]

    walls = classify_walls(metrics, current_price=4050.0)
    static = next(wall for wall in walls if wall.strike == 4000)

    assert static.wall_type == WallType.STATIC
    assert any("volume_p50" in item or "volume_p25" in item for item in static.evidence)


def test_classify_walls_pin() -> None:
    metrics = [
        _metric(strike=4000, call_oi=500, put_oi=500, call_gex=5000.0, put_gex=4900.0),
        _metric(strike=4100, call_oi=120, put_oi=100, call_gex=200.0, put_gex=100.0),
        _metric(strike=4200, call_oi=150, put_oi=90, call_gex=300.0, put_gex=120.0),
    ]

    walls = classify_walls(metrics, current_price=4050.0)
    pin = next(wall for wall in walls if wall.strike == 4000)

    assert pin.wall_type == WallType.PIN
    assert pin.net_gex == 100.0


def test_classify_walls_support_resistance() -> None:
    metrics = [
        _metric(strike=4000, call_oi=200, put_oi=320, call_gex=100.0, put_gex=260.0),
        _metric(strike=4100, call_oi=340, put_oi=180, call_gex=300.0, put_gex=120.0),
    ]

    walls = classify_walls(metrics, current_price=4050.0)
    support = next(wall for wall in walls if wall.strike == 4000)
    resistance = next(wall for wall in walls if wall.strike == 4100)

    assert support.wall_type == WallType.SUPPORT
    assert resistance.wall_type == WallType.RESISTANCE


def test_classify_walls_uses_per_expiry_thresholds() -> None:
    metrics = [
        _metric(
            strike=4000,
            expiry="JUN26",
            call_oi=3200,
            put_oi=1800,
            call_oi_change=80,
            put_oi_change=40,
            call_volume=300,
            put_volume=240,
            call_block=40,
            put_block=20,
            call_pnt=10,
            put_pnt=5,
        ),
        _metric(strike=4100, expiry="JUN26", call_oi=100, put_oi=80, call_volume=10, put_volume=8),
        _metric(strike=4200, expiry="JUN26", call_oi=120, put_oi=90, call_volume=12, put_volume=9),
        _metric(
            strike=4000,
            expiry="JUL26",
            call_oi=360,
            put_oi=240,
            call_oi_change=30,
            put_oi_change=20,
            call_volume=60,
            put_volume=40,
            call_block=8,
            put_block=6,
            call_pnt=4,
            put_pnt=3,
        ),
        _metric(strike=4100, expiry="JUL26", call_oi=70, put_oi=50, call_volume=8, put_volume=6),
        _metric(strike=4200, expiry="JUL26", call_oi=60, put_oi=40, call_volume=6, put_volume=5),
    ]

    walls = classify_walls(metrics, current_price=4050.0)

    jun = next(wall for wall in walls if wall.expiry == "JUN26" and wall.strike == 4000)
    jul = next(wall for wall in walls if wall.expiry == "JUL26" and wall.strike == 4000)

    assert jun.wall_type == WallType.ACTIVE
    assert jul.wall_type == WallType.ACTIVE


def test_wall_score_ranking() -> None:
    walls = [
        Wall(3900, "JUN26", "BOTH", WallType.ACTIVE, 500, 30, 100, 10, 5, 1000.0, 200.0, []),
        Wall(4050, "JUN26", "BOTH", WallType.ACTIVE, 800, 60, 220, 30, 10, 1400.0, 100.0, []),
        Wall(4300, "JUN26", "BOTH", WallType.ACTIVE, 300, 10, 50, 2, 1, 400.0, 50.0, []),
    ]

    scored = score_walls(walls, current_price=4040.0)

    assert [item.rank for item in scored] == [1, 2, 3]
    assert scored == sorted(scored, key=lambda item: item.wall_score, reverse=True)
    assert scored[0].wall.strike == 4050
    assert scored[1].distance_score > scored[2].distance_score


def test_score_walls_ranks_are_per_expiry() -> None:
    walls = [
        Wall(3900, "JUN26", "BOTH", WallType.ACTIVE, 500, 30, 100, 10, 5, 1000.0, 200.0, []),
        Wall(4050, "JUN26", "BOTH", WallType.ACTIVE, 800, 60, 220, 30, 10, 1400.0, 100.0, []),
        Wall(3900, "JUL26", "BOTH", WallType.ACTIVE, 450, 20, 90, 8, 4, 900.0, 180.0, []),
        Wall(4050, "JUL26", "BOTH", WallType.ACTIVE, 760, 50, 200, 20, 9, 1300.0, 90.0, []),
    ]

    scored = score_walls(walls, current_price=4040.0)

    jun_ranks = {item.rank for item in scored if item.wall.expiry == "JUN26"}
    jul_ranks = {item.rank for item in scored if item.wall.expiry == "JUL26"}

    assert jun_ranks == {1, 2}
    assert jul_ranks == {1, 2}
    assert sum(item.rank == 1 for item in scored) == 2


def test_detect_call_roll_up() -> None:
    metrics = [
        _metric(strike=3900, expiry="JUN26", call_oi_change=-30),
        _metric(strike=4000, expiry="JUN26", call_oi_change=-20),
        _metric(strike=4300, expiry="JUL26", call_oi_change=15),
        _metric(strike=4400, expiry="JUL26", call_oi_change=25),
    ]

    signals = detect_rolls(metrics, ["JUN26", "JUL26"])

    signal = next(item for item in signals if item.roll_type == RollType.CALL_ROLL_UP)
    assert signal.near_expiry == "JUN26"
    assert signal.far_expiry == "JUL26"
    assert signal.confidence > 0.0


def test_detect_put_roll_down() -> None:
    metrics = [
        _metric(strike=3900, expiry="JUN26", put_oi_change=-24),
        _metric(strike=4000, expiry="JUN26", put_oi_change=-18),
        _metric(strike=3900, expiry="JUL26", put_oi_change=20),
        _metric(strike=4000, expiry="JUL26", put_oi_change=14),
    ]

    signals = detect_rolls(metrics, ["JUN26", "JUL26"])

    signal = next(item for item in signals if item.roll_type == RollType.PUT_ROLL_DOWN)
    assert signal.near_expiry == "JUN26"
    assert signal.far_expiry == "JUL26"
    assert signal.confidence > 0.0


def test_classify_intent_defensive() -> None:
    metrics = [
        _metric(strike=4000, call_oi=200, put_oi=900, call_oi_change=5, put_oi_change=60, call_volume=20, put_volume=180, call_gex=100.0, put_gex=700.0),
        _metric(strike=4100, call_oi=180, put_oi=850, call_oi_change=3, put_oi_change=45, call_volume=15, put_volume=140, call_gex=80.0, put_gex=500.0),
    ]

    intent = classify_intent(metrics, [], current_price=4050.0, expiry="JUN26")

    assert intent.primary_intent.intent_type == IntentType.I1_DEFENSIVE
    assert intent.all_scores[IntentType.I1_DEFENSIVE.value] == max(intent.all_scores.values())


def test_classify_intent_trend_launch() -> None:
    metrics = [
        _metric(strike=4000, call_oi=1200, put_oi=250, call_oi_change=120, put_oi_change=-5, call_volume=260, put_volume=20, call_block=50, call_pnt=20, call_gex=900.0, put_gex=70.0),
        _metric(strike=4100, call_oi=1000, put_oi=220, call_oi_change=90, put_oi_change=-4, call_volume=200, put_volume=18, call_block=30, call_pnt=10, call_gex=700.0, put_gex=60.0),
    ]

    intent = classify_intent(metrics, [], current_price=4050.0, expiry="JUN26")

    assert intent.primary_intent.intent_type == IntentType.I4_TREND_LAUNCH


def test_classify_intent_rebalance() -> None:
    metrics = [
        _metric(strike=4000, call_oi=1000, put_oi=980, call_oi_change=55, put_oi_change=48, call_volume=220, put_volume=210, call_block=40, put_block=35, call_pnt=12, put_pnt=11, call_gex=600.0, put_gex=580.0),
        _metric(strike=4100, call_oi=920, put_oi=940, call_oi_change=42, put_oi_change=50, call_volume=180, put_volume=190, call_block=25, put_block=28, call_pnt=9, put_pnt=10, call_gex=540.0, put_gex=560.0),
    ]

    intent = classify_intent(metrics, [], current_price=4050.0, expiry="JUN26")

    assert intent.primary_intent.intent_type == IntentType.I2_STRUCTURED_REBALANCE


def test_classify_intent_propagates_selected_expiry_data_quality() -> None:
    rows = [
        _row(expiry="JUN26", strike=4000, option_type="CALL", open_interest=5, settlement=100.0),
        _row(expiry="JUL26", strike=4100, option_type="CALL", open_interest=5, settlement=None),
    ]
    normalized, _ = normalize_option_rows(rows, filter_strikes=False, aggregate_duplicates=False)
    exposures = [
        _exposure(4000, "CALL", gex=11.0, delta_exposure=1.5, expiry="JUN26", data_quality=["exp_jun"]),
        _exposure(4100, "CALL", gex=31.0, delta_exposure=2.5, expiry="JUL26", data_quality=["exp_jul"]),
    ]

    metrics = aggregate_strike_metrics(normalized, exposures)
    intent = classify_intent(metrics, exposures, current_price=4050.0, expiry="JUN26")

    assert intent.trade_date == "2026-05-06"
    assert "low_oi" in intent.data_quality
    assert "exp_jun" in intent.data_quality
    assert "missing_settlement" not in intent.data_quality
    assert "exp_jul" not in intent.data_quality


def test_no_roll_with_single_expiry() -> None:
    metrics = [
        _metric(strike=4000, expiry="JUN26", call_oi_change=-20),
        _metric(strike=4100, expiry="JUN26", call_oi_change=15),
    ]

    assert detect_rolls(metrics, ["JUN26"]) == []
