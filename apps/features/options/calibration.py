"""P4-06: Multi-day wall calibration for CME options.

Computes OI deltas, wall migration, roll detection, and wall stability
by comparing CME option rows across consecutive trading dates.

All functions are deterministic, in-memory, with no DB/file/network access.
Inputs are already-loaded CME option row dicts keyed by trade_date.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OiDelta:
    """OI change for a specific strike/expiry between two trade dates."""

    strike: int
    expiry: str
    prev_oi: int
    curr_oi: int
    delta_oi: int
    option_type: str = ""  # 'C' | 'P'


@dataclass(frozen=True)
class WallMigration:
    """A wall that appears across multiple trade dates."""

    strike: int
    expiry: str
    side: str  # 'call' | 'put'
    wall_type: str  # from structure.WallType
    trade_dates: list[str]  # dates this wall appeared
    oi_trend: list[int]  # OI on each date
    is_stable: bool  # same direction across all dates
    is_growing: bool  # OI is increasing


@dataclass(frozen=True)
class ExpiryRollSignal:
    """Detected roll activity from near-month to next-month."""

    near_month: str
    next_month: str
    near_oi_change: int  # total OI change in near month
    next_oi_change: int  # total OI change in next month
    roll_activity: str = "none"  # 'active' | 'starting' | 'none'
    roll_confidence: float = 0.0


@dataclass(frozen=True)
class CalibrationWarnings:
    """Warnings about calibration data quality."""

    missing_dates: list[str] = field(default_factory=list)
    prelim_only_dates: list[str] = field(default_factory=list)
    single_date_only: bool = False
    low_oi_volatility: bool = False
    messages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CalibrationResult:
    """Complete multi-day wall calibration output."""

    wall_map: dict[str, Any] = field(default_factory=dict)
    # wall_map: strike → {"walls": [{"date": ..., "oi": ...}], "stability": ...}

    wall_score_delta_1d: dict[str, float] = field(default_factory=dict)
    # key (e.g. "3000_call") → score change from previous day

    wall_score_delta_1w: dict[str, float] | None = None
    # Same as above but for 1-week comparison (None if < 1 week of data)

    oi_change_by_strike: dict[int, dict[str, int]] = field(default_factory=dict)
    # strike → {"call_oi_delta": N, "put_oi_delta": M, "total_oi_delta": T}

    expiry_roll_signal: list[ExpiryRollSignal] = field(default_factory=list)

    near_month_vs_next_month: dict[str, Any] = field(default_factory=dict)
    # Comparison of key metrics between near and next month

    calculation_method: str = "unavailable"
    # "black76" | "proxy" | "unavailable"

    calibration_warnings: CalibrationWarnings = field(default_factory=CalibrationWarnings)

    source_refs: list[dict[str, Any]] = field(default_factory=list)


def calibrate_walls(
    rows_by_date: dict[str, list[dict[str, Any]]],
    *,
    current_trade_date: str,
    lookback_days: int = 5,
) -> CalibrationResult:
    """Calibrate CME option walls using multi-day data.

    Args:
        rows_by_date: trade_date → list of row dicts with keys: strike, expiry,
                      option_type, open_interest, oi_change
        current_trade_date: The primary trade date being analyzed.
        lookback_days: Max number of previous dates to compare.

    Returns:
        CalibrationResult with OI deltas, wall migration, roll signals.
    """
    if not rows_by_date:
        return CalibrationResult(
            calculation_method="unavailable",
            calibration_warnings=CalibrationWarnings(
                single_date_only=True,
                messages=["No multi-day data available for calibration."],
            ),
        )

    # Sort dates
    sorted_dates = sorted(rows_by_date.keys())
    if len(sorted_dates) < 2:
        return CalibrationResult(
            calculation_method="unavailable",
            calibration_warnings=CalibrationWarnings(
                single_date_only=True,
                messages=["Only one trade date available; need 2+ dates for calibration."],
            ),
        )

    # Find previous date(s) relative to current_trade_date
    prev_dates = [d for d in sorted_dates if d < current_trade_date]
    if not prev_dates:
        prev_dates = sorted_dates[:lookback_days]  # all dates if current is earliest

    # ── 1. OI deltas ────────────────────────────────────────────────────
    prev_date = prev_dates[-1] if prev_dates else sorted_dates[0]
    oi_change_by_strike = _compute_oi_deltas(
        rows_by_date.get(prev_date, []),
        rows_by_date.get(current_trade_date, []),
    )

    # ── 2. Wall score deltas ────────────────────────────────────────────
    wall_scores_prev = _compute_wall_scores(rows_by_date.get(prev_date, []))
    wall_scores_curr = _compute_wall_scores(rows_by_date.get(current_trade_date, []))
    wall_score_delta_1d = _compute_score_deltas(wall_scores_prev, wall_scores_curr)

    # 1-week delta if we have at least 5 days of data
    wall_score_delta_1w: dict[str, float] | None = None
    if len(sorted_dates) >= 5:
        week_ago = sorted_dates[-5] if len(sorted_dates) >= 5 else sorted_dates[0]
        wall_scores_week = _compute_wall_scores(rows_by_date.get(week_ago, []))
        wall_score_delta_1w = _compute_score_deltas(wall_scores_week, wall_scores_curr)

    # ── 3. Wall migration ───────────────────────────────────────────────
    wall_map = _compute_wall_migration(rows_by_date, current_trade_date)

    # ── 4. Expiry roll detection ────────────────────────────────────────
    expiry_roll_signal = _detect_expiry_rolls(rows_by_date, current_trade_date)

    # ── 5. Near-month vs next-month ─────────────────────────────────────
    near_month_vs_next_month = _compare_near_next_month(
        rows_by_date.get(current_trade_date, [])
    )

    # ── Warnings ────────────────────────────────────────────────────────
    warnings = CalibrationWarnings(
        missing_dates=[],
        prelim_only_dates=[],
        single_date_only=False,
        messages=[],
    )
    if len(sorted_dates) < 3:
        warnings = CalibrationWarnings(
            messages=[f"Only {len(sorted_dates)} dates available; calibration is limited."],
        )

    return CalibrationResult(
        wall_map=wall_map,
        wall_score_delta_1d=wall_score_delta_1d,
        wall_score_delta_1w=wall_score_delta_1w,
        oi_change_by_strike=oi_change_by_strike,
        expiry_roll_signal=expiry_roll_signal,
        near_month_vs_next_month=near_month_vs_next_month,
        calculation_method="proxy",  # no Black-76 in calibration (uses raw OI)
        calibration_warnings=warnings,
        source_refs=[{"source": "cme_multiday_calibration", "version": "1.0.0"}],
    )


# ═══════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════


def _compute_oi_deltas(
    prev_rows: list[dict[str, Any]],
    curr_rows: list[dict[str, Any]],
) -> dict[int, dict[str, int]]:
    """Compute OI changes per strike between two dates."""
    # Build lookup: (strike, option_type) → oi
    prev_oi: dict[tuple[int, str], int] = {}
    for r in prev_rows:
        key = (int(r.get("strike", 0)), str(r.get("option_type", "")))
        prev_oi[key] = int(r.get("open_interest", 0))

    curr_oi: dict[tuple[int, str], int] = {}
    for r in curr_rows:
        key = (int(r.get("strike", 0)), str(r.get("option_type", "")))
        curr_oi[key] = int(r.get("open_interest", 0))

    result: dict[int, dict[str, int]] = defaultdict(lambda: {"call_oi_delta": 0, "put_oi_delta": 0, "total_oi_delta": 0})
    all_strikes = set(k[0] for k in set(prev_oi.keys()) | set(curr_oi.keys()))

    for strike in all_strikes:
        call_prev = prev_oi.get((strike, "C"), 0)
        call_curr = curr_oi.get((strike, "C"), 0)
        put_prev = prev_oi.get((strike, "P"), 0)
        put_curr = curr_oi.get((strike, "P"), 0)
        result[strike]["call_oi_delta"] = call_curr - call_prev
        result[strike]["put_oi_delta"] = put_curr - put_prev
        result[strike]["total_oi_delta"] = (call_curr + put_curr) - (call_prev + put_prev)

    return dict(result)


def _compute_wall_scores(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Compute a wall score for each strike/side from OI and volume.

    Score = normalized OI + volume bonus. This is a proxy score when
    Black-76 GEX is not available across all dates.
    """
    if not rows:
        return {}

    max_oi = max(int(r.get("open_interest", 0)) for r in rows) or 1
    scores: dict[str, float] = {}

    for r in rows:
        oi = int(r.get("open_interest", 0))
        vol = int(r.get("total_volume", 0))
        strike = int(r.get("strike", 0))
        side = str(r.get("option_type", ""))

        oi_score = oi / max_oi
        vol_score = min(vol / (max_oi or 1), 1.0) * 0.3
        key = f"{strike}_{'call' if side == 'C' else 'put'}"
        scores[key] = round(oi_score + vol_score, 4)

    return scores


def _compute_score_deltas(
    prev_scores: dict[str, float],
    curr_scores: dict[str, float],
) -> dict[str, float]:
    """Compute day-over-day wall score changes."""
    deltas: dict[str, float] = {}
    all_keys = set(prev_scores.keys()) | set(curr_scores.keys())
    for key in all_keys:
        deltas[key] = round(curr_scores.get(key, 0) - prev_scores.get(key, 0), 4)
    return deltas


def _compute_wall_migration(
    rows_by_date: dict[str, list[dict[str, Any]]],
    current_trade_date: str,
) -> dict[str, Any]:
    """Build a wall stability map showing which strikes have persistent walls."""
    sorted_dates = sorted(rows_by_date.keys())
    wall_map: dict[str, Any] = {}

    # Find walls (strikes with high OI) for each date
    date_walls: dict[str, set[int]] = {}
    for date, rows in rows_by_date.items():
        walls: set[int] = set()
        if rows:
            avg_oi = sum(int(r.get("open_interest", 0)) for r in rows) / len(rows)
            threshold = avg_oi * 2  # 2x average = wall threshold
            for r in rows:
                if int(r.get("open_interest", 0)) >= threshold:
                    walls.add(int(r.get("strike", 0)))
        date_walls[date] = walls

    # For each strike that appears as a wall, track which dates
    all_wall_strikes: set[int] = set()
    for walls in date_walls.values():
        all_wall_strikes.update(walls)

    for strike in all_wall_strikes:
        dates_present = [d for d in sorted_dates if strike in date_walls.get(d, set())]
        stability = len(dates_present) / max(len(sorted_dates), 1)
        wall_map[str(strike)] = {
            "dates_present": dates_present,
            "date_count": len(dates_present),
            "stability": round(stability, 2),
            "is_current": current_trade_date in dates_present,
            "is_stable": stability >= 0.6,
        }

    return wall_map


def _detect_expiry_rolls(
    rows_by_date: dict[str, list[dict[str, Any]]],
    current_trade_date: str,
) -> list[ExpiryRollSignal]:
    """Detect roll activity from near-month to next-month expiry."""
    curr_rows = rows_by_date.get(current_trade_date, [])
    if not curr_rows:
        return []

    # Find all expiries
    expiries = sorted(set(str(r.get("expiry", "")) for r in curr_rows if r.get("expiry")))
    if len(expiries) < 2:
        return []

    near_month = expiries[0]
    next_month = expiries[1]

    # Compute total OI for each month
    def _total_oi(rows: list[dict[str, Any]], expiry: str) -> int:
        return sum(int(r.get("open_interest", 0)) for r in rows if str(r.get("expiry", "")) == expiry)

    near_curr = _total_oi(curr_rows, near_month)
    next_curr = _total_oi(curr_rows, next_month)

    # Check previous date
    sorted_dates = sorted(rows_by_date.keys())
    prev_date = sorted_dates[-2] if len(sorted_dates) >= 2 else None
    prev_rows = rows_by_date.get(prev_date, []) if prev_date else []

    near_prev = _total_oi(prev_rows, near_month) if prev_rows else near_curr
    next_prev = _total_oi(prev_rows, next_month) if prev_rows else next_curr

    near_change = near_curr - near_prev
    next_change = next_curr - next_prev

    # Detect roll: near OI decreasing, next OI increasing
    roll_activity = "none"
    roll_confidence = 0.0
    near_ratio = near_curr / max(near_prev, 1)
    next_ratio = next_curr / max(next_prev, 1)

    if near_ratio < 0.9 and next_ratio > 1.1:
        roll_activity = "active"
        roll_confidence = min((1 - near_ratio) + (next_ratio - 1), 1.0)
    elif near_ratio < 1.0 and next_ratio > 1.0:
        roll_activity = "starting"
        roll_confidence = 0.3

    return [
        ExpiryRollSignal(
            near_month=near_month,
            next_month=next_month,
            near_oi_change=near_change,
            next_oi_change=next_change,
            roll_activity=roll_activity,
            roll_confidence=round(roll_confidence, 2),
        )
    ]


def _compare_near_next_month(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare near-month vs next-month metrics."""
    if not rows:
        return {}

    expiries = sorted(set(str(r.get("expiry", "")) for r in rows if r.get("expiry")))
    if len(expiries) < 2:
        return {"near_month": expiries[0] if expiries else "", "next_month": "", "oi_ratio": None}

    near_month = expiries[0]
    next_month = expiries[1]

    near_total = sum(int(r.get("open_interest", 0)) for r in rows if str(r.get("expiry", "")) == near_month)
    next_total = sum(int(r.get("open_interest", 0)) for r in rows if str(r.get("expiry", "")) == next_month)

    near_vol = sum(int(r.get("total_volume", 0)) for r in rows if str(r.get("expiry", "")) == near_month)
    next_vol = sum(int(r.get("total_volume", 0)) for r in rows if str(r.get("expiry", "")) == next_month)

    return {
        "near_month": near_month,
        "next_month": next_month,
        "near_total_oi": near_total,
        "next_total_oi": next_total,
        "oi_ratio": round(near_total / max(next_total, 1), 2) if next_total else None,
        "near_total_volume": near_vol,
        "next_total_volume": next_vol,
        "volume_ratio": round(near_vol / max(next_vol, 1), 2) if next_vol else None,
    }
