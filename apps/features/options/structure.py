"""CME option structure engine: walls, roll detection, and intent scoring."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from statistics import median

from apps.features.options.black76 import OptionExposure, sort_expiry_codes
from apps.features.options.normalize import NormalizedOptionRow


@dataclass(frozen=True)
class StrikeMetrics:
    strike: int
    expiry: str
    call_oi: int
    put_oi: int
    call_oi_change: int
    put_oi_change: int
    call_volume: int
    put_volume: int
    call_block: int
    put_block: int
    call_pnt: int
    put_pnt: int
    call_gex: float
    put_gex: float
    net_gex: float
    call_delta_exposure: float
    put_delta_exposure: float
    total_oi: int
    total_volume: int
    trade_date: str = ""
    data_quality: list[str] = field(default_factory=list)


class WallType(str, Enum):
    ACTIVE = "active"
    STATIC = "static"
    TURNOVER = "turnover"
    NEW = "new"
    PIN = "pin"
    RESISTANCE = "resistance"
    SUPPORT = "support"


@dataclass(frozen=True)
class Wall:
    strike: int
    expiry: str
    side: str
    wall_type: WallType
    oi: int
    oi_change: int
    volume: int
    block: int
    pnt: int
    gex: float
    net_gex: float
    evidence: list[str]


@dataclass(frozen=True)
class WallScoredWall:
    wall: Wall
    gex_score: float
    oi_score: float
    doi_score: float
    volume_score: float
    block_pnt_score: float
    distance_score: float
    wall_score: float
    rank: int


class RollType(str, Enum):
    CALL_ROLL_UP = "call_roll_up"
    PUT_ROLL_DOWN = "put_roll_down"
    PROTECTION_UPSHIFT = "protection_upshift"
    UPSIDE_TAIL_MIGRATION = "upside_tail_migration"


@dataclass(frozen=True)
class RollSignal:
    roll_type: RollType
    near_expiry: str
    far_expiry: str
    evidence: list[str]
    confidence: float


class IntentType(str, Enum):
    I1_DEFENSIVE = "I1_defensive"
    I2_STRUCTURED_REBALANCE = "I2_structured_rebalance"
    I3_TRAP = "I3_trap"
    I4_TREND_LAUNCH = "I4_trend_launch"


@dataclass(frozen=True)
class IntentScore:
    intent_type: IntentType
    score: float
    evidence: list[str]
    confidence: float


@dataclass(frozen=True)
class IntentClassification:
    trade_date: str
    expiry: str
    primary_intent: IntentScore
    secondary_intent: IntentScore | None
    all_scores: dict[str, float]
    data_quality: list[str]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if percentile <= 0:
        return ordered[0]
    if percentile >= 100:
        return ordered[-1]
    index = (len(ordered) - 1) * (percentile / 100.0)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _min_max(value: float, low: float, high: float) -> float:
    if high <= low:
        return 1.0
    return max(0.0, min((value - low) / (high - low), 1.0))


def _safe_sum(values: list[int]) -> int:
    return int(sum(values))


def _unique_extend(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def aggregate_strike_metrics(
    normalized_rows: list[NormalizedOptionRow],
    exposures: list[OptionExposure],
) -> list[StrikeMetrics]:
    exposure_map: dict[tuple[str, str, int, str], dict[str, object]] = defaultdict(
        lambda: {"gex_1pct": 0.0, "delta_exposure": 0.0, "data_quality": []}
    )
    unscoped_exposures: list[OptionExposure] = []
    for exposure in exposures:
        option_type = exposure.option_type.upper()
        if exposure.trade_date and exposure.expiry:
            key = (exposure.trade_date, exposure.expiry, exposure.strike, option_type)
            exposure_map[key]["gex_1pct"] = float(exposure_map[key]["gex_1pct"]) + float(exposure.gex_1pct)
            exposure_map[key]["delta_exposure"] = float(exposure_map[key]["delta_exposure"]) + float(exposure.delta_exposure)
            _unique_extend(exposure_map[key]["data_quality"], exposure.data_quality)
        else:
            unscoped_exposures.append(exposure)

    grouped: dict[tuple[str, str, int], list[NormalizedOptionRow]] = defaultdict(list)
    for row in normalized_rows:
        grouped[(row.trade_date, row.expiry, row.strike)].append(row)

    unique_trade_dates = sorted({row.trade_date for row in normalized_rows if row.trade_date})
    unique_expiries = sort_expiry_codes({row.expiry for row in normalized_rows if row.expiry})
    expiry_rank = {expiry: index for index, expiry in enumerate(unique_expiries)}
    single_scope = len(unique_trade_dates) == 1 and len(unique_expiries) == 1

    metrics: list[StrikeMetrics] = []
    for trade_date, expiry, strike in sorted(
        grouped,
        key=lambda item: (item[0], expiry_rank.get(item[1], len(expiry_rank)), item[2]),
    ):
        rows = grouped[(trade_date, expiry, strike)]
        call_rows = [row for row in rows if row.option_type == "CALL"]
        put_rows = [row for row in rows if row.option_type == "PUT"]
        row_option_types = {row.option_type for row in rows}

        call_oi = _safe_sum([row.open_interest for row in call_rows])
        put_oi = _safe_sum([row.open_interest for row in put_rows])
        call_oi_change = _safe_sum([row.oi_change for row in call_rows])
        put_oi_change = _safe_sum([row.oi_change for row in put_rows])
        call_volume = _safe_sum([row.total_volume for row in call_rows])
        put_volume = _safe_sum([row.total_volume for row in put_rows])
        call_block = _safe_sum([row.block_volume for row in call_rows])
        put_block = _safe_sum([row.block_volume for row in put_rows])
        call_pnt = _safe_sum([row.pnt_volume for row in call_rows])
        put_pnt = _safe_sum([row.pnt_volume for row in put_rows])

        metric_quality: list[str] = []
        for row in rows:
            _unique_extend(metric_quality, row.data_quality)

        call_key = (trade_date, expiry, strike, "CALL")
        put_key = (trade_date, expiry, strike, "PUT")
        call_gex = float(exposure_map[call_key]["gex_1pct"])
        put_gex = float(exposure_map[put_key]["gex_1pct"])
        call_delta_exposure = float(exposure_map[call_key]["delta_exposure"])
        put_delta_exposure = float(exposure_map[put_key]["delta_exposure"])
        _unique_extend(metric_quality, exposure_map[call_key]["data_quality"])
        _unique_extend(metric_quality, exposure_map[put_key]["data_quality"])

        for exposure in unscoped_exposures:
            option_type = exposure.option_type.upper()
            if option_type not in row_option_types:
                continue
            if single_scope:
                if exposure.strike != strike:
                    continue
                if not exposure.trade_date or not exposure.expiry:
                    _unique_extend(metric_quality, exposure.data_quality)
                    _unique_extend(metric_quality, ["unscoped_exposure_used"])
                    if option_type == "CALL":
                        call_gex += float(exposure.gex_1pct)
                        call_delta_exposure += float(exposure.delta_exposure)
                    else:
                        put_gex += float(exposure.gex_1pct)
                        put_delta_exposure += float(exposure.delta_exposure)
            else:
                if exposure.strike == strike:
                    _unique_extend(metric_quality, exposure.data_quality)
                    _unique_extend(metric_quality, ["unscoped_exposure_ignored_for_multi_expiry"])

        metrics.append(
            StrikeMetrics(
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
                data_quality=metric_quality,
            )
        )

    return metrics


def classify_walls(
    metrics: list[StrikeMetrics],
    current_price: float | None = None,
    *,
    oi_threshold_percentile: float = 75,
    volume_threshold_percentile: float = 75,
    gex_threshold_percentile: float = 75,
) -> list[Wall]:
    if not metrics:
        return []

    walls: list[Wall] = []
    for expiry in sort_expiry_codes({metric.expiry for metric in metrics}):
        expiry_metrics = sorted(_expiry_group(metrics, expiry), key=lambda item: item.strike)
        if not expiry_metrics:
            continue

        oi_values = [float(metric.total_oi) for metric in expiry_metrics]
        volume_values = [float(metric.total_volume) for metric in expiry_metrics]
        oi_change_values = [abs(float(metric.call_oi_change + metric.put_oi_change)) for metric in expiry_metrics]
        gex_values = [abs(float(metric.call_gex + metric.put_gex)) for metric in expiry_metrics]

        oi_p75 = _percentile(oi_values, oi_threshold_percentile)
        volume_p25 = _percentile(volume_values, 25)
        volume_p50 = _percentile(volume_values, 50)
        volume_p75 = _percentile(volume_values, volume_threshold_percentile)
        gex_p75 = _percentile(gex_values, gex_threshold_percentile)
        oi_change_p75 = _percentile(oi_change_values, 75)

        for metric in expiry_metrics:
            total_gex = metric.call_gex + metric.put_gex
            total_change = metric.call_oi_change + metric.put_oi_change
            net_gex_ratio = abs(metric.net_gex) / max(abs(total_gex), 1.0)
            call_dominant = metric.call_gex > metric.put_gex and metric.call_oi > metric.put_oi
            put_dominant = metric.put_gex > metric.call_gex and metric.put_oi > metric.call_oi
            pin_like = total_gex > 0 and gex_p75 > 0 and total_gex >= gex_p75 and net_gex_ratio < 0.2
            evidence: list[str] = []
            wall_type: WallType | None = None
            side = "BOTH"

            if pin_like:
                wall_type = WallType.PIN
                evidence.append(f"total_gex {total_gex:.2f} >= gex_p75 {gex_p75:.2f}")
                evidence.append(f"net_gex ratio {net_gex_ratio:.2f} < 0.20")
            elif metric.total_oi >= oi_p75 and (
                abs(total_change) >= max(volume_p50, 1.0)
                or metric.total_volume >= max(volume_p50, 1.0)
                or (metric.call_block + metric.put_block + metric.call_pnt + metric.put_pnt) > 0
            ) and not pin_like:
                wall_type = WallType.ACTIVE
                block_pnt = metric.call_block + metric.put_block + metric.call_pnt + metric.put_pnt
                evidence.append(f"total_oi {metric.total_oi} >= oi_p75 {oi_p75:.2f}")
                evidence.append(
                    "activity signal: "
                    f"abs(oi_change) {abs(total_change)}, "
                    f"volume {metric.total_volume}, block+pnt {block_pnt}"
                )
            elif metric.total_oi >= oi_p75 and abs(total_change) < volume_p25 and metric.total_volume < volume_p50:
                wall_type = WallType.STATIC
                evidence.append(f"total_oi {metric.total_oi} >= oi_p75 {oi_p75:.2f}")
                evidence.append(
                    f"abs(oi_change) {abs(total_change)} < volume_p25 {volume_p25:.2f}"
                )
                evidence.append(f"total_volume {metric.total_volume} < volume_p50 {volume_p50:.2f}")
            elif metric.total_volume > 0 and metric.total_volume >= volume_p75 and total_change <= 0:
                wall_type = WallType.TURNOVER
                evidence.append(f"total_volume {metric.total_volume} >= volume_p75 {volume_p75:.2f}")
                evidence.append(f"oi_change {total_change} <= 0")
            elif abs(total_change) >= max(oi_change_p75, 1.0) and metric.total_volume >= max(volume_p50, 1.0):
                wall_type = WallType.NEW
                evidence.append(
                    f"abs(oi_change) {abs(total_change)} >= oi_change_p75 {oi_change_p75:.2f}"
                )
                evidence.append(f"total_volume {metric.total_volume} >= volume_p50 {volume_p50:.2f}")
            elif call_dominant:
                wall_type = WallType.RESISTANCE
                side = "CALL"
                evidence.append(f"call_gex {metric.call_gex:.2f} > put_gex {metric.put_gex:.2f}")
                evidence.append(f"call_oi {metric.call_oi} > put_oi {metric.put_oi}")
            elif put_dominant:
                wall_type = WallType.SUPPORT
                side = "PUT"
                evidence.append(f"put_gex {metric.put_gex:.2f} > call_gex {metric.call_gex:.2f}")
                evidence.append(f"put_oi {metric.put_oi} > call_oi {metric.call_oi}")

            if wall_type is None:
                continue
            if current_price is not None:
                evidence.append(f"current_price {current_price:.2f} vs strike {metric.strike}")
            walls.append(
                Wall(
                    strike=metric.strike,
                    expiry=metric.expiry,
                    side=side,
                    wall_type=wall_type,
                    oi=metric.total_oi,
                    oi_change=metric.call_oi_change + metric.put_oi_change,
                    volume=metric.total_volume,
                    block=metric.call_block + metric.put_block,
                    pnt=metric.call_pnt + metric.put_pnt,
                    gex=total_gex,
                    net_gex=metric.net_gex,
                    evidence=evidence,
                )
            )

    return walls


def score_walls(
    walls: list[Wall],
    current_price: float,
    *,
    weights: dict | None = None,
    group_by_expiry: bool = True,
) -> list[WallScoredWall]:
    if not walls:
        return []

    weight_map = {
        "gex": 0.30,
        "oi": 0.20,
        "doi": 0.15,
        "volume": 0.15,
        "block_pnt": 0.10,
        "distance": 0.10,
    }
    if weights:
        weight_map.update(weights)

    def _score_group(group: list[Wall]) -> list[WallScoredWall]:
        gex_values = [abs(wall.gex) for wall in group]
        oi_values = [float(wall.oi) for wall in group]
        doi_values = [abs(float(wall.oi_change)) for wall in group]
        volume_values = [float(wall.volume) for wall in group]
        block_pnt_values = [float(wall.block + wall.pnt) for wall in group]
        strikes = [wall.strike for wall in group]
        strike_range = max(strikes) - min(strikes)

        scored: list[WallScoredWall] = []
        for wall in group:
            gex_score = _min_max(abs(wall.gex), min(gex_values), max(gex_values))
            oi_score = _min_max(float(wall.oi), min(oi_values), max(oi_values))
            doi_score = _min_max(abs(float(wall.oi_change)), min(doi_values), max(doi_values))
            volume_score = _min_max(float(wall.volume), min(volume_values), max(volume_values))
            block_pnt_score = _min_max(float(wall.block + wall.pnt), min(block_pnt_values), max(block_pnt_values))
            if strike_range <= 0:
                distance_score = 1.0
            else:
                distance_score = 1.0 - min(abs(wall.strike - current_price) / strike_range, 1.0)

            wall_score = (
                gex_score * weight_map["gex"]
                + oi_score * weight_map["oi"]
                + doi_score * weight_map["doi"]
                + volume_score * weight_map["volume"]
                + block_pnt_score * weight_map["block_pnt"]
                + distance_score * weight_map["distance"]
            )
            scored.append(
                WallScoredWall(
                    wall=wall,
                    gex_score=gex_score,
                    oi_score=oi_score,
                    doi_score=doi_score,
                    volume_score=volume_score,
                    block_pnt_score=block_pnt_score,
                    distance_score=distance_score,
                    wall_score=wall_score,
                    rank=0,
                )
            )

        ordered = sorted(scored, key=lambda item: item.wall_score, reverse=True)
        return [
            WallScoredWall(
                wall=item.wall,
                gex_score=item.gex_score,
                oi_score=item.oi_score,
                doi_score=item.doi_score,
                volume_score=item.volume_score,
                block_pnt_score=item.block_pnt_score,
                distance_score=item.distance_score,
                wall_score=item.wall_score,
                rank=index + 1,
            )
            for index, item in enumerate(ordered)
        ]

    if not group_by_expiry:
        return _score_group(walls)

    scored: list[WallScoredWall] = []
    for expiry in sort_expiry_codes({wall.expiry for wall in walls}):
        expiry_group = [wall for wall in walls if wall.expiry == expiry]
        scored.extend(_score_group(expiry_group))
    return scored


def _expiry_group(metrics: list[StrikeMetrics], expiry: str) -> list[StrikeMetrics]:
    return [metric for metric in metrics if metric.expiry == expiry]


def _strike_bands(strikes: list[int]) -> tuple[float, float, float]:
    ordered = sorted(strikes)
    if not ordered:
        return 0.0, 0.0, 0.0
    if len(ordered) == 1:
        value = float(ordered[0])
        return value, value, value
    lower = float(_percentile([float(value) for value in ordered], 33.333333))
    middle = float(_percentile([float(value) for value in ordered], 50))
    upper = float(_percentile([float(value) for value in ordered], 66.666667))
    return lower, middle, upper


def _roll_confidence(shift: float, total_oi: float) -> float:
    denominator = max(total_oi, shift, 1.0)
    return max(0.0, min(shift / denominator, 1.0))


def detect_rolls(metrics: list[StrikeMetrics], expiry_order: list[str]) -> list[RollSignal]:
    if len(expiry_order) < 2:
        return []

    signals: list[RollSignal] = []
    for near_expiry, far_expiry in zip(expiry_order, expiry_order[1:]):
        near_metrics = _expiry_group(metrics, near_expiry)
        far_metrics = _expiry_group(metrics, far_expiry)
        if not near_metrics or not far_metrics:
            continue

        strikes = sorted({metric.strike for metric in near_metrics + far_metrics})
        if not strikes:
            continue
        low_band, mid_band, high_band = _strike_bands(strikes)
        near_by_strike = {metric.strike: metric for metric in near_metrics}
        far_by_strike = {metric.strike: metric for metric in far_metrics}

        near_low_call_drop = 0.0
        far_high_call_build = 0.0
        near_low_put_drop = 0.0
        far_low_put_build = 0.0
        near_deep_put_drop = 0.0
        near_atm_put_build = 0.0
        near_high_call_weak = 0.0
        far_high_call_strong = 0.0

        for strike in strikes:
            near_metric = near_by_strike.get(strike)
            far_metric = far_by_strike.get(strike)
            if near_metric is not None:
                if strike <= low_band:
                    near_low_call_drop += max(-near_metric.call_oi_change, 0)
                    near_low_put_drop += max(-near_metric.put_oi_change, 0)
                    near_deep_put_drop += max(-near_metric.put_oi_change, 0)
                if abs(strike - mid_band) <= (high_band - low_band) / 6.0:
                    near_atm_put_build += max(near_metric.put_oi_change, 0)
                if strike >= high_band:
                    near_high_call_weak += max(-near_metric.call_oi_change, 0)
            if far_metric is not None:
                if strike >= high_band:
                    far_high_call_build += max(far_metric.call_oi_change, 0)
                    far_high_call_strong += max(far_metric.call_oi_change, 0)
                if strike <= low_band:
                    far_low_put_build += max(far_metric.put_oi_change, 0)

        total_near_call_oi = sum(metric.call_oi for metric in near_metrics)
        total_far_call_oi = sum(metric.call_oi for metric in far_metrics)
        total_near_put_oi = sum(metric.put_oi for metric in near_metrics)
        total_far_put_oi = sum(metric.put_oi for metric in far_metrics)

        if near_low_call_drop > 0 and far_high_call_build > 0:
            total_shift = near_low_call_drop + far_high_call_build
            confidence = _roll_confidence(total_shift, total_near_call_oi + total_far_call_oi)
            signals.append(
                RollSignal(
                    roll_type=RollType.CALL_ROLL_UP,
                    near_expiry=near_expiry,
                    far_expiry=far_expiry,
                    evidence=[
                        f"near low-strike call OI down {near_low_call_drop}",
                        f"far high-strike call OI up {far_high_call_build}",
                    ],
                    confidence=confidence,
                )
            )

        if near_low_put_drop > 0 and far_low_put_build > 0:
            total_shift = near_low_put_drop + far_low_put_build
            confidence = _roll_confidence(total_shift, total_near_put_oi + total_far_put_oi)
            signals.append(
                RollSignal(
                    roll_type=RollType.PUT_ROLL_DOWN,
                    near_expiry=near_expiry,
                    far_expiry=far_expiry,
                    evidence=[
                        f"near low-strike put OI down {near_low_put_drop}",
                        f"far low-strike put OI up {far_low_put_build}",
                    ],
                    confidence=confidence,
                )
            )

        if near_deep_put_drop > 0 and near_atm_put_build > 0:
            total_shift = near_deep_put_drop + near_atm_put_build
            confidence = _roll_confidence(total_shift, total_near_put_oi + total_far_put_oi)
            signals.append(
                RollSignal(
                    roll_type=RollType.PROTECTION_UPSHIFT,
                    near_expiry=near_expiry,
                    far_expiry=far_expiry,
                    evidence=[
                        f"near deep-OTM put OI down {near_deep_put_drop}",
                        f"near ATM put OI up {near_atm_put_build}",
                    ],
                    confidence=confidence,
                )
            )

        if near_high_call_weak > 0 and far_high_call_strong > 0:
            total_shift = near_high_call_weak + far_high_call_strong
            confidence = _roll_confidence(total_shift, total_near_call_oi + total_far_call_oi)
            signals.append(
                RollSignal(
                    roll_type=RollType.UPSIDE_TAIL_MIGRATION,
                    near_expiry=near_expiry,
                    far_expiry=far_expiry,
                    evidence=[
                        f"near high-strike call OI down {near_high_call_weak}",
                        f"far high-strike call OI up {far_high_call_strong}",
                    ],
                    confidence=confidence,
                )
            )

    return signals


def _aggregate_data_quality(metrics: list[StrikeMetrics], exposures: list[OptionExposure]) -> list[str]:
    warnings: list[str] = []
    for metric in metrics:
        _unique_extend(warnings, metric.data_quality)
    for exposure in exposures:
        _unique_extend(warnings, exposure.data_quality)
    return warnings


def classify_intent(
    metrics: list[StrikeMetrics],
    exposures: list[OptionExposure],
    current_price: float,
    expiry: str,
) -> IntentClassification:
    selected_metrics = sorted([metric for metric in metrics if metric.expiry == expiry], key=lambda metric: (metric.trade_date, metric.strike))
    selected_trade_date = next((metric.trade_date for metric in selected_metrics if metric.trade_date), "")
    selected_exposures = [
        exposure
        for exposure in exposures
        if exposure.expiry == expiry and (not selected_trade_date or exposure.trade_date in ("", selected_trade_date))
    ]
    data_quality = _aggregate_data_quality(selected_metrics, selected_exposures)

    if not selected_metrics:
        empty = IntentScore(IntentType.I1_DEFENSIVE, 0.0, ["no_metrics"], 0.0)
        return IntentClassification(
            trade_date=selected_trade_date,
            expiry=expiry,
            primary_intent=empty,
            secondary_intent=None,
            all_scores={intent.value: 0.0 for intent in IntentType},
            data_quality=data_quality,
        )

    call_oi = sum(metric.call_oi for metric in selected_metrics)
    put_oi = sum(metric.put_oi for metric in selected_metrics)
    call_oi_change = sum(metric.call_oi_change for metric in selected_metrics)
    put_oi_change = sum(metric.put_oi_change for metric in selected_metrics)
    call_volume = sum(metric.call_volume for metric in selected_metrics)
    put_volume = sum(metric.put_volume for metric in selected_metrics)
    call_block = sum(metric.call_block for metric in selected_metrics)
    put_block = sum(metric.put_block for metric in selected_metrics)
    call_pnt = sum(metric.call_pnt for metric in selected_metrics)
    put_pnt = sum(metric.put_pnt for metric in selected_metrics)
    call_gex = sum(metric.call_gex for metric in selected_metrics)
    put_gex = sum(metric.put_gex for metric in selected_metrics)
    total_gex = call_gex + put_gex
    total_oi = call_oi + put_oi
    total_volume = call_volume + put_volume
    strikes = [metric.strike for metric in selected_metrics]
    nearest_metric = min(selected_metrics, key=lambda metric: abs(metric.strike - current_price))
    strike_median = median(strikes)
    nearest_total_change = nearest_metric.call_oi_change + nearest_metric.put_oi_change

    defensive_parts = [
        _min_max(float(put_oi), 0.0, max(float(call_oi + put_oi), 1.0)),
        _min_max(
            float(put_oi_change - call_oi_change),
            -float(abs(put_oi_change) + abs(call_oi_change)),
            float(abs(put_oi_change) + abs(call_oi_change) or 1.0),
        ),
        _min_max(float(put_volume), 0.0, max(float(call_volume + put_volume), 1.0)),
        _min_max(float(put_gex), 0.0, max(float(total_gex), 1.0)),
    ]
    defensive_score = sum(defensive_parts) / len(defensive_parts)

    balance_score = 1.0 - abs(call_oi - put_oi) / max(float(total_oi), 1.0)
    change_balance_score = min(
        _min_max(float(call_oi_change), 0.0, max(float(abs(call_oi_change) + abs(put_oi_change)), 1.0)),
        _min_max(float(put_oi_change), 0.0, max(float(abs(call_oi_change) + abs(put_oi_change)), 1.0)),
    )
    participation_score = min(
        _min_max(float(call_block + call_pnt), 0.0, max(float(call_volume), 1.0)),
        _min_max(float(put_block + put_pnt), 0.0, max(float(put_volume), 1.0)),
    )
    gex_balance_score = 1.0 - abs(call_gex - put_gex) / max(float(total_gex), 1.0)
    structured_rebalance_score = (balance_score + change_balance_score + participation_score + gex_balance_score) / 4.0

    trap_wall_weakness = 1.0 if nearest_total_change < 0 else 0.0
    trap_turnover = (
        1.0
        if selected_metrics
        and total_volume >= median([metric.total_volume for metric in selected_metrics])
        else 0.0
    )
    trap_direction_mismatch = 0.0
    if current_price >= strike_median and nearest_metric.put_oi_change < 0:
        trap_direction_mismatch = 1.0
    elif current_price < strike_median and nearest_metric.call_oi_change < 0:
        trap_direction_mismatch = 1.0
    trap_score = (trap_wall_weakness + trap_turnover + trap_direction_mismatch) / 3.0

    call_trend_parts = [
        _min_max(float(call_oi_change), 0.0, max(float(abs(call_oi_change) + abs(put_oi_change)), 1.0)),
        _min_max(float(call_volume), 0.0, max(float(call_volume + put_volume), 1.0)),
        _min_max(float(call_gex), 0.0, max(float(total_gex), 1.0)),
        _min_max(float(call_block + call_pnt), 0.0, max(float(call_volume), 1.0)),
    ]
    put_trend_parts = [
        _min_max(float(put_oi_change), 0.0, max(float(abs(call_oi_change) + abs(put_oi_change)), 1.0)),
        _min_max(float(put_volume), 0.0, max(float(call_volume + put_volume), 1.0)),
        _min_max(float(put_gex), 0.0, max(float(total_gex), 1.0)),
        _min_max(float(put_block + put_pnt), 0.0, max(float(put_volume), 1.0)),
    ]
    trend_score = max(sum(call_trend_parts) / len(call_trend_parts), sum(put_trend_parts) / len(put_trend_parts))

    scores = {
        IntentType.I1_DEFENSIVE.value: max(0.0, min(defensive_score, 1.0)),
        IntentType.I2_STRUCTURED_REBALANCE.value: max(0.0, min(structured_rebalance_score, 1.0)),
        IntentType.I3_TRAP.value: max(0.0, min(trap_score, 1.0)),
        IntentType.I4_TREND_LAUNCH.value: max(0.0, min(trend_score, 1.0)),
    }

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    primary_type = IntentType(ordered[0][0])
    primary_score = ordered[0][1]
    primary = IntentScore(
        intent_type=primary_type,
        score=primary_score,
        confidence=primary_score,
        evidence=[
            f"expiry {expiry}",
            f"call_oi {call_oi} put_oi {put_oi}",
            f"call_change {call_oi_change} put_change {put_oi_change}",
        ],
    )

    secondary = None
    if len(ordered) > 1 and ordered[1][1] > 0.3:
        secondary_type = IntentType(ordered[1][0])
        secondary = IntentScore(
            intent_type=secondary_type,
            score=ordered[1][1],
            confidence=ordered[1][1],
            evidence=[f"secondary score {ordered[1][1]:.2f}"],
        )

    return IntentClassification(
        trade_date=selected_trade_date,
        expiry=expiry,
        primary_intent=primary,
        secondary_intent=secondary,
        all_scores=scores,
        data_quality=data_quality,
    )


__all__ = [
    "IntentClassification",
    "IntentScore",
    "IntentType",
    "RollSignal",
    "RollType",
    "StrikeMetrics",
    "Wall",
    "WallScoredWall",
    "WallType",
    "aggregate_strike_metrics",
    "classify_intent",
    "classify_walls",
    "detect_rolls",
    "score_walls",
]
