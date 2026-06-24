"""Build an options analysis JSON snapshot from raw CME option rows.

Pipeline: raw dicts → normalize_option_rows → compute_exposures →
aggregate_strike_metrics → classify_walls → score_walls → classify_intent →
compute_netgex_grid → snapshot dict.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from statistics import mean, median, pstdev
from typing import Any

from apps.features.options.black76 import (
    NetGEXResult,
    OptionExposure,
    calc_time_to_expiry,
    compute_exposures,
    compute_iv_skew,
    compute_netgex_grid,
    infer_forward_price,
    sort_expiry_codes,
)
from apps.features.options.normalize import (
    NormalizationReport,
    NormalizedOptionRow,
    normalize_option_rows,
)
from apps.features.options.structure import (
    IntentClassification,
    RollSignal,
    StrikeMetrics,
    Wall,
    WallScoredWall,
    aggregate_strike_metrics,
    classify_intent,
    classify_walls,
    detect_rolls,
    score_walls,
)
from apps.features.options.calibration import CalibrationResult

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataQualityReport:
    """Categorized counts and warnings from the options pipeline."""

    rows_missing_settlement: int = 0
    rows_missing_delta: int = 0
    zero_oi_count: int = 0
    low_oi_count: int = 0
    proxy_strike_count: int = 0
    prelim_data_count: int = 0
    rows_filtered_by_strike: int = 0
    duplicates_merged: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OptionsAnalysisResult:
    """Complete options analysis result ready for JSON/Markdown rendering."""

    trade_date: str
    product: str
    expiries: list[str]
    p0: float | None
    p0_source: str
    p0_timestamp: str | None
    p0_warnings: list[str]
    report_p0: float | None
    report_p0_source: str
    report_p0_timestamp: str | None
    report_p0_warnings: list[str]
    live_p0: float | None
    live_p0_source: str
    live_p0_timestamp: str | None
    live_p0_warnings: list[str]
    generated_at: str
    analysis_strike_min: int
    analysis_strike_max: int
    analysis_range_source: str

    # upstream data
    forward_price: float | None
    forward_warnings: list[str]
    f_source: str  # "user" | "parity_inferred" | "unavailable"

    time_to_expiry: dict[str, float]  # expiry → T (year fraction)
    expiry_dates: dict[str, str]      # expiry → ISO date string
    expiry_warnings: list[str]

    norm_report: NormalizationReport
    normalized_rows: list[NormalizedOptionRow]

    exposures: list[OptionExposure]
    used_real_gex: bool

    strike_metrics: list[StrikeMetrics]
    walls: list[Wall]
    scored_walls: list[WallScoredWall]
    full_chain_walls: list[Wall]
    full_chain_scored_walls: list[WallScoredWall]
    roll_signals: list[RollSignal]
    intent: IntentClassification

    netgex: NetGEXResult

    # per-expiry views for reporting
    gex_top_by_expiry: dict[str, list[dict[str, Any]]]
    exposure_summary_by_expiry: dict[str, dict[str, Any]]

    # provenance
    data_source_status: str  # "PRELIM" / "FINAL" / "UNKNOWN" / "PRELIM_assumed"
    data_source_url: str | None  # CME source PDF URL
    input_snapshot_ids: dict[str, str]  # e.g. raw_file_id, ingest_id

    data_quality: DataQualityReport

    # ── P4-06: multi-day wall calibration ──
    calibration: CalibrationResult | None = None

    # per-expiry enhanced data (M4)
    forward_by_expiry: dict[str, dict[str, Any]] = field(default_factory=dict)
    gex_summary_by_expiry: dict[str, dict[str, Any]] = field(default_factory=dict)
    iv_skew_by_expiry: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_options_snapshot(
    raw_rows: list[dict[str, Any]],
    *,
    product: str = "OG",
    expiries: list[str] | None = None,
    p0: float | None = None,
    p0_source: str = "manual" ,
    p0_timestamp: str | None = None,
    p0_warnings: list[str] | None = None,
    report_p0: float | None = None,
    report_p0_source: str | None = None,
    report_p0_timestamp: str | None = None,
    report_p0_warnings: list[str] | None = None,
    live_p0: float | None = None,
    live_p0_source: str | None = None,
    live_p0_timestamp: str | None = None,
    live_p0_warnings: list[str] | None = None,
    user_f: float | None = None,
    trade_date: str | None = None,
    data_source_status: str = "UNKNOWN",
    data_source_url: str | None = None,
    input_snapshot_ids: dict[str, str] | None = None,
    strike_min: int = 2000,
    strike_max: int = 12000,
    filter_strikes: bool = True,
    analysis_strike_min: int | None = None,
    analysis_strike_max: int | None = None,
    analysis_range_source: str | None = None,
    analysis_range_mode: str = "auto",
    analysis_range_sigma: float = 2.0,
    analysis_range_min_half_width: int = 500,
) -> OptionsAnalysisResult:
    """Run the full options analysis pipeline and return structured result.

    Parameters
    ----------
    raw_rows : list[dict]
        Parsed CME option row dicts (from JSON fixture or DB).
    product : str
        Product code filter (default "OG").
    expiries : list[str] | None
        Expiry codes to include (e.g. ["JUN26", "JUL26"]).
        If None, all expiries present in the data are used.
    p0 : float | None
        Current underlying price for support/resistance and wall scoring.
    user_f : float | None
        User-supplied forward price override.
    trade_date : str | None
        Trade date filter. If None, taken from the first row.
    """
    generated_at = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()

    def _round_down(value: float, step: int = 50) -> int:
        return int(math.floor(value / step) * step)

    def _round_up(value: float, step: int = 50) -> int:
        return int(math.ceil(value / step) * step)

    # The raw normalization universe is the full chain. The main trading universe
    # is a separate analysis range used for GEX Top / WallScore / S-R / strategy.
    # Resolve most modes now; normal mode is resolved after F/T/ATM IV are known.
    normalized_range_mode = (analysis_range_mode or "auto").strip().lower()
    explicit_range = analysis_strike_min is not None or analysis_strike_max is not None
    if explicit_range:
        center = p0 if p0 is not None and p0 > 0 else 4500.0
        analysis_strike_min = analysis_strike_min if analysis_strike_min is not None else _round_down(center - 1000)
        analysis_strike_max = analysis_strike_max if analysis_strike_max is not None else _round_up(center + 1000)
        resolved_range_source = analysis_range_source or "user_explicit"
    elif normalized_range_mode == "normal":
        analysis_strike_min = 3800
        analysis_strike_max = 5000
        resolved_range_source = "pending_normal_distribution"
    elif p0 is not None and p0 > 0:
        analysis_strike_min = _round_down(p0 - 1000)
        analysis_strike_max = _round_up(p0 + 1000)
        resolved_range_source = "p0_plus_minus_1000"
    else:
        analysis_strike_min = 3800
        analysis_strike_max = 5000
        resolved_range_source = "default_3800_5000"
    if analysis_strike_min > analysis_strike_max:
        analysis_strike_min, analysis_strike_max = analysis_strike_max, analysis_strike_min

    # -----------------------------------------------------------------------
    # 1. Normalize
    # -----------------------------------------------------------------------
    # Filter by product
    product_rows = [r for r in raw_rows if r.get("product_code", "") == product]
    if trade_date is None and product_rows:
        trade_date = product_rows[0].get("trade_date", "")

    normalized, norm_report = normalize_option_rows(
        product_rows,
        source=data_source_status,
        strike_min=strike_min,
        strike_max=strike_max,
        filter_strikes=filter_strikes,
    )

    # Filter by expiries
    if expiries is not None:
        expiry_set = {e.upper() for e in expiries}
        normalized = [r for r in normalized if r.expiry.upper() in expiry_set]

    # Filter by trade_date
    if trade_date:
        normalized = [r for r in normalized if r.trade_date == trade_date]

    active_expiries = sort_expiry_codes({r.expiry for r in normalized if r.expiry})

    # -----------------------------------------------------------------------
    # 2. Forward prices — per-expiry inference
    # -----------------------------------------------------------------------
    forward_warnings: list[str] = []
    forward_by_expiry: dict[str, dict[str, Any]] = {}

    if user_f is not None and user_f > 0:
        F = user_f
        f_source = "user"
        for expiry in active_expiries:
            forward_by_expiry[expiry] = {
                "f_value": user_f,
                "f_source": "user",
                "warnings": [],
            }
    else:
        # Infer per-expiry forward from call-put parity
        for expiry in active_expiries:
            exp_forward, exp_warnings = infer_forward_price(
                normalized, trade_date or "", expiry,
            )
            if exp_forward is not None:
                forward_by_expiry[expiry] = {
                    "f_value": exp_forward,
                    "f_source": "parity_inferred",
                    "warnings": exp_warnings,
                }
            else:
                forward_by_expiry[expiry] = {
                    "f_value": None,
                    "f_source": "unavailable",
                    "warnings": exp_warnings,
                }

        # Derive single F for backward-compat: use nearest expiry
        nearest_exp = active_expiries[0] if active_expiries else ""
        nearest_fw = forward_by_expiry.get(nearest_exp, {})
        F = nearest_fw.get("f_value") or 0.0
        f_source = nearest_fw.get("f_source", "unavailable")
        forward_warnings = list(nearest_fw.get("warnings", []))

    # -----------------------------------------------------------------------
    # 2b. Price anchors
    # -----------------------------------------------------------------------
    # Backward-compatible p0 is now the end-of-day structure anchor (report_p0),
    # not an intraday live price. Black-76 still uses per-expiry F above.
    if report_p0 is None:
        report_p0 = p0 if p0 is not None else (F if F > 0 else None)
    if report_p0_source is None:
        if p0 is not None:
            report_p0_source = p0_source or "manual"
        elif F > 0:
            report_p0_source = "near_expiry_parity_fallback"
        else:
            report_p0_source = "not_provided"
    if report_p0_timestamp is None:
        report_p0_timestamp = p0_timestamp
    combined_report_p0_warnings = []
    for warning in [*(report_p0_warnings or []), *(p0_warnings or [])]:
        if warning not in combined_report_p0_warnings:
            combined_report_p0_warnings.append(warning)
    if live_p0_source is None:
        live_p0_source = "not_provided" if live_p0 is None else "manual"
    if live_p0_warnings is None:
        live_p0_warnings = []
    p0 = report_p0
    p0_source = report_p0_source
    p0_timestamp = report_p0_timestamp
    p0_warnings = combined_report_p0_warnings
    if (
        not explicit_range
        and normalized_range_mode != "normal"
        and resolved_range_source == "default_3800_5000"
        and report_p0 is not None
        and report_p0 > 0
    ):
        analysis_strike_min = _round_down(report_p0 - 1000)
        analysis_strike_max = _round_up(report_p0 + 1000)
        resolved_range_source = "report_p0_plus_minus_1000"

    # -----------------------------------------------------------------------
    # 3. Time to expiry
    # -----------------------------------------------------------------------
    time_to_expiry: dict[str, float] = {}
    expiry_dates: dict[str, str] = {}
    expiry_warnings: list[str] = []
    for expiry in active_expiries:
        T, exp_date, warns = calc_time_to_expiry(trade_date or "", expiry=expiry)
        time_to_expiry[expiry] = T
        expiry_dates[expiry] = exp_date.isoformat()
        expiry_warnings.extend(warns)

    # Use the nearest expiry's T for single-T computations
    nearest_expiry = active_expiries[0] if active_expiries else None
    T = time_to_expiry.get(nearest_expiry, 1.0) if nearest_expiry else 1.0

    if not explicit_range and normalized_range_mode == "normal" and nearest_expiry:
        nearest_rows = [row for row in normalized if row.expiry == nearest_expiry]
        nearest_iv = compute_iv_skew(nearest_rows, F or 0.0, T).get("atm_iv")
        if isinstance(nearest_iv, (int, float)) and F > 0 and T > 0:
            one_sigma = F * float(nearest_iv) * math.sqrt(T)
            half_width = max(float(analysis_range_sigma) * one_sigma, float(analysis_range_min_half_width))
            analysis_strike_min = _round_down(F - half_width)
            analysis_strike_max = _round_up(F + half_width)
            resolved_range_source = f"normal_distribution_{analysis_range_sigma:g}sigma_min_width_{analysis_range_min_half_width}"
        elif p0 is not None and p0 > 0:
            analysis_strike_min = _round_down(p0 - 1000)
            analysis_strike_max = _round_up(p0 + 1000)
            resolved_range_source = "normal_unavailable_fallback_p0_plus_minus_1000"
        else:
            analysis_strike_min = 3800
            analysis_strike_max = 5000
            resolved_range_source = "normal_unavailable_fallback_default_3800_5000"

    # -----------------------------------------------------------------------
    # 4. Exposures — per-expiry F and T
    # -----------------------------------------------------------------------
    exposures: list[OptionExposure] = []
    for expiry in active_expiries:
        expiry_rows = [row for row in normalized if row.expiry == expiry]
        expiry_T = time_to_expiry.get(expiry, T)
        expiry_F = forward_by_expiry[expiry]["f_value"]
        if expiry_F is None:
            expiry_F = F  # fallback to nearest-expiry F
        exposures.extend(compute_exposures(expiry_rows, expiry_F or 0.0, expiry_T))
    used_real_gex = any(e.method == "black76" for e in exposures)

    # -----------------------------------------------------------------------
    # 5. Structure analysis
    # -----------------------------------------------------------------------
    full_chain_strike_metrics = aggregate_strike_metrics(normalized, exposures)
    main_normalized = [
        row for row in normalized
        if analysis_strike_min <= row.strike <= analysis_strike_max
    ]
    main_exposures = [
        exposure for exposure in exposures
        if analysis_strike_min <= exposure.strike <= analysis_strike_max
    ]
    strike_metrics = aggregate_strike_metrics(main_normalized, main_exposures)
    walls = classify_walls(strike_metrics, current_price=p0)
    scored_walls = score_walls(walls, current_price=p0 or F or 0.0)
    full_chain_walls = classify_walls(full_chain_strike_metrics, current_price=p0)
    full_chain_scored_walls = score_walls(full_chain_walls, current_price=p0 or F or 0.0)
    roll_signals = detect_rolls(strike_metrics, active_expiries)

    # -----------------------------------------------------------------------
    # 6. Intent classification
    # -----------------------------------------------------------------------
    intent = classify_intent(
        full_chain_strike_metrics, exposures, current_price=p0 or F or 0.0,
        expiry=nearest_expiry or active_expiries[0] if active_expiries else "",
    )

    # -----------------------------------------------------------------------
    # 7. NetGEX grid
    # -----------------------------------------------------------------------
    netgex = compute_netgex_grid(main_normalized, F, T)

    # -----------------------------------------------------------------------
    # 8. Per-expiry aggregated views
    # -----------------------------------------------------------------------
    gex_top_by_expiry: dict[str, list[dict[str, Any]]] = {}
    exposure_summary_by_expiry: dict[str, dict[str, Any]] = {}

    for expiry in active_expiries:
        exp_exposures = [e for e in main_exposures if e.expiry == expiry]
        # GEX by strike
        gex_by_strike: dict[tuple[int, str], float] = {}
        for e in exp_exposures:
            key = (e.strike, e.option_type)
            gex_by_strike[key] = gex_by_strike.get(key, 0.0) + e.gex_1pct

        # Aggregate into per-strike call/put/net
        strikes_set = sorted({k[0] for k in gex_by_strike})
        gex_rows = []
        for strike in strikes_set:
            call_gex = gex_by_strike.get((strike, "CALL"), 0.0)
            put_gex = gex_by_strike.get((strike, "PUT"), 0.0)
            gex_rows.append({
                "strike": strike,
                "call_gex": round(call_gex, 2),
                "put_gex": round(put_gex, 2),
                "net_gex": round(call_gex - put_gex, 2),
                "total_gex": round(abs(call_gex) + abs(put_gex), 2),
            })
        gex_rows.sort(key=lambda x: x["total_gex"], reverse=True)
        gex_top_by_expiry[expiry] = gex_rows[:10]

        # DEX / VEX / Theta summary. Keep both leg-level and strike-level views;
        # strategy/report defaults to strike-level to avoid duplicate strikes.
        net_dex = sum(e.delta_exposure for e in exp_exposures)
        vex_top_by_leg = sorted(
            [(e.strike, e.option_type, e.vega_exposure_1vol) for e in exp_exposures],
            key=lambda x: abs(x[2]), reverse=True,
        )[:10]
        theta_top_by_leg = sorted(
            [(e.strike, e.option_type, e.theta_exposure_day) for e in exp_exposures],
            key=lambda x: abs(x[2]), reverse=True,
        )[:10]
        vex_by_strike: dict[int, float] = {}
        theta_by_strike: dict[int, float] = {}
        for e in exp_exposures:
            vex_by_strike[e.strike] = vex_by_strike.get(e.strike, 0.0) + e.vega_exposure_1vol
            theta_by_strike[e.strike] = theta_by_strike.get(e.strike, 0.0) + e.theta_exposure_day
        vex_top_by_strike = sorted(vex_by_strike.items(), key=lambda x: abs(x[1]), reverse=True)[:10]
        theta_top_by_strike = sorted(theta_by_strike.items(), key=lambda x: abs(x[1]), reverse=True)[:10]
        exposure_summary_by_expiry[expiry] = {
            "net_dex": round(net_dex, 2),
            "vex_top": [{"strike": s, "vex": round(v, 2)} for s, v in vex_top_by_strike],
            "theta_top": [{"strike": s, "theta_exposure": round(t, 2)} for s, t in theta_top_by_strike],
            "vex_top_by_strike": [{"strike": s, "vex": round(v, 2)} for s, v in vex_top_by_strike],
            "theta_top_by_strike": [{"strike": s, "theta_exposure": round(t, 2)} for s, t in theta_top_by_strike],
            "vex_top_by_leg": [
                {"strike": s, "option_type": ot, "vex": round(v, 2)}
                for s, ot, v in vex_top_by_leg
            ],
            "theta_top_by_leg": [
                {"strike": s, "option_type": ot, "theta_exposure": round(t, 2)}
                for s, ot, t in theta_top_by_leg
            ],
        }

    # -----------------------------------------------------------------------
    # 8b. Per-expiry GEX summary (gamma zero, call/put/net GEX)
    # -----------------------------------------------------------------------
    gex_summary_by_expiry: dict[str, dict[str, Any]] = {}
    for expiry in active_expiries:
        expiry_normalized = [r for r in main_normalized if r.expiry == expiry]
        expiry_F = forward_by_expiry[expiry]["f_value"]
        expiry_T = time_to_expiry.get(expiry, T)
        if expiry_F is None:
            expiry_F = F

        # Per-expiry netgex grid → gamma zero
        per_expiry_netgex = compute_netgex_grid(
            expiry_normalized, expiry_F or 0.0, expiry_T,
        )

        # Call/put/net GEX from exposures
        exp_exposures = [e for e in main_exposures if e.expiry == expiry]
        call_gex_sum = sum(e.gex_1pct for e in exp_exposures if e.option_type == "CALL")
        put_gex_sum = sum(e.gex_1pct for e in exp_exposures if e.option_type == "PUT")
        net_gex_sum = call_gex_sum - put_gex_sum
        total_gex_sum = abs(call_gex_sum) + abs(put_gex_sum)

        # Structure classification
        if total_gex_sum == 0:
            structure = "balanced"
        elif net_gex_sum > total_gex_sum * 0.1:
            structure = "net_call_dominated"
        elif net_gex_sum < -total_gex_sum * 0.1:
            structure = "net_put_dominated"
        else:
            structure = "balanced"

        gex_summary_by_expiry[expiry] = {
            "f_value": expiry_F,
            "gamma_zero": per_expiry_netgex.gamma_zero,
            "gamma_zero_method": per_expiry_netgex.gamma_zero_method,
            "net_gex": round(net_gex_sum, 2),
            "call_gex": round(call_gex_sum, 2),
            "put_gex": round(put_gex_sum, 2),
            "total_gex": round(total_gex_sum, 2),
            "structure": structure,
        }

    # -----------------------------------------------------------------------
    # 8c. Per-expiry IV skew
    # -----------------------------------------------------------------------
    iv_skew_by_expiry: dict[str, dict[str, Any]] = {}
    for expiry in active_expiries:
        expiry_normalized = [r for r in main_normalized if r.expiry == expiry]
        expiry_F = forward_by_expiry[expiry]["f_value"]
        expiry_T = time_to_expiry.get(expiry, T)
        if expiry_F is None:
            expiry_F = F
        iv_skew_by_expiry[expiry] = compute_iv_skew(
            expiry_normalized, expiry_F or 0.0, expiry_T,
        )

    # -----------------------------------------------------------------------
    # 9. Collect data quality
    # -----------------------------------------------------------------------
    dq_warnings: list[str] = list(norm_report.warnings)
    if norm_report.rows_missing_settlement > 0:
        dq_warnings.append(f"rows_missing_settlement: {norm_report.rows_missing_settlement} 行")
    if norm_report.rows_missing_delta > 0:
        dq_warnings.append(f"rows_missing_delta: {norm_report.rows_missing_delta} 行")
    proxy_count = sum(1 for e in exposures if e.method == "proxy")
    if proxy_count > 0:
        dq_warnings.append(f"使用 Gamma Proxy 的 strike: {proxy_count} 个")
    dq_warnings.extend(forward_warnings)
    dq_warnings.extend(expiry_warnings)
    dq_warnings.extend(netgex.warnings)
    # deduplicate
    seen: set[str] = set()
    unique_warnings: list[str] = []
    for w in dq_warnings:
        if w not in seen:
            seen.add(w)
            unique_warnings.append(w)

    dq_counts = norm_report.data_quality_counts
    data_quality = DataQualityReport(
        rows_missing_settlement=norm_report.rows_missing_settlement,
        rows_missing_delta=norm_report.rows_missing_delta,
        zero_oi_count=dq_counts.get("zero_oi", 0),
        low_oi_count=dq_counts.get("low_oi", 0),
        proxy_strike_count=proxy_count,
        prelim_data_count=dq_counts.get("prelim_data", 0),
        rows_filtered_by_strike=norm_report.rows_filtered_by_strike,
        duplicates_merged=norm_report.duplicates_merged,
        warnings=unique_warnings,
    )

    return OptionsAnalysisResult(
        trade_date=trade_date or "",
        product=product,
        expiries=active_expiries,
        p0=p0,
        p0_source=p0_source if p0 is not None else "not_provided",
        p0_timestamp=p0_timestamp,
        p0_warnings=p0_warnings or [],
        report_p0=report_p0,
        report_p0_source=report_p0_source,
        report_p0_timestamp=report_p0_timestamp,
        report_p0_warnings=p0_warnings or [],
        live_p0=live_p0,
        live_p0_source=live_p0_source,
        live_p0_timestamp=live_p0_timestamp,
        live_p0_warnings=live_p0_warnings or [],
        generated_at=generated_at,
        analysis_strike_min=analysis_strike_min,
        analysis_strike_max=analysis_strike_max,
        analysis_range_source=resolved_range_source,
        forward_price=F if F > 0 else None,
        forward_warnings=forward_warnings,
        f_source=f_source,
        time_to_expiry=time_to_expiry,
        expiry_dates=expiry_dates,
        expiry_warnings=expiry_warnings,
        norm_report=norm_report,
        normalized_rows=normalized,
        exposures=exposures,
        used_real_gex=used_real_gex,
        strike_metrics=strike_metrics,
        walls=walls,
        scored_walls=scored_walls,
        full_chain_walls=full_chain_walls,
        full_chain_scored_walls=full_chain_scored_walls,
        roll_signals=roll_signals,
        intent=intent,
        netgex=netgex,
        gex_top_by_expiry=gex_top_by_expiry,
        exposure_summary_by_expiry=exposure_summary_by_expiry,
        forward_by_expiry=forward_by_expiry,
        gex_summary_by_expiry=gex_summary_by_expiry,
        iv_skew_by_expiry=iv_skew_by_expiry,
        data_source_status=data_source_status,
        data_source_url=data_source_url,
        input_snapshot_ids=input_snapshot_ids or {},
        data_quality=data_quality,
    )



# ---------------------------------------------------------------------------
# Audit metadata helpers
# ---------------------------------------------------------------------------

_WALL_SCORE_FORMULA = {
    "formula": "0.30*gex_score + 0.20*oi_score + 0.15*doi_score + 0.15*volume_score + 0.10*block_pnt_score + 0.10*distance_score",
    "components": {
        "gex_score": 0.30,
        "oi_score": 0.20,
        "doi_score": 0.15,
        "volume_score": 0.15,
        "block_pnt_score": 0.10,
        "distance_score": 0.10,
    },
    "normalization": "min_max_within_expiry_group",
}


def _safe_round(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _forward_audit_for_expiry(
    normalized_rows: list[NormalizedOptionRow],
    *,
    trade_date: str,
    expiry: str,
    f_value: float | None,
    f_source: str,
) -> dict[str, Any]:
    call_by_strike: dict[int, float] = {}
    put_by_strike: dict[int, float] = {}
    for row in normalized_rows:
        if row.trade_date != trade_date or row.expiry != expiry or row.settlement is None:
            continue
        if row.option_type == "CALL":
            call_by_strike[row.strike] = row.settlement
        elif row.option_type == "PUT":
            put_by_strike[row.strike] = row.settlement

    estimates: list[float] = []
    for strike in sorted(set(call_by_strike) & set(put_by_strike)):
        call_settle = call_by_strike[strike]
        put_settle = put_by_strike[strike]
        estimate = strike + (call_settle - put_settle)
        if estimate <= 0:
            continue
        if abs(call_settle - put_settle) > estimate * 0.5:
            continue
        estimates.append(float(estimate))

    return {
        "F": f_value,
        "F_source": f_source,
        "F_pairs_used": len(estimates),
        "F_median": _safe_round(median(estimates), 4) if estimates else None,
        "F_mean": _safe_round(mean(estimates), 4) if estimates else None,
        "F_std": _safe_round(pstdev(estimates), 4) if len(estimates) > 1 else 0.0 if estimates else None,
        "F_min": _safe_round(min(estimates), 4) if estimates else None,
        "F_max": _safe_round(max(estimates), 4) if estimates else None,
        "manual_override": f_source == "user",
    }


def _intent_wording_text(intent_type: str, confidence: float, all_scores: dict[str, float]) -> str:
    """Generate standard intent wording based on I1-I4 scores.

    When I1 defense score is close to or exceeds I2 rebalance, write
    "I2 防守型再平衡，向 I1 迁移" instead of pure I2 wording.
    """
    i1_score = all_scores.get("I1_defensive", 0.0)
    i2_score = all_scores.get("I2_structured_rebalance", 0.0)
    confidence_tag = "置信度中低" if confidence < 0.6 else ""

    # I1 is leading or very close to I2 → migrate wording
    if intent_type in ("I1_defensive", "I1") or i1_score >= i2_score - 0.1:
        parts = ["I2 防守型再平衡"]
        if i1_score >= i2_score:
            parts.append("向 I1 迁移")
        if confidence_tag:
            parts.append(confidence_tag)
        return "，".join(parts)

    # Normal I2 rebalance
    if confidence < 0.6:
        return "I2 结构化再平衡，偏防守，置信度中低"
    return "I2 结构化再平衡"


def _build_audit_metadata(result: OptionsAnalysisResult) -> dict[str, Any]:
    raw_rows = result.norm_report.total_input_rows
    valid_pricing_rows = len(result.normalized_rows)
    range_rows = sum(
        1 for row in result.normalized_rows
        if result.analysis_strike_min <= row.strike <= result.analysis_strike_max
    )
    excluded_outside_analysis_range = valid_pricing_rows - range_rows
    proxy_exposures = [e for e in result.exposures if e.method == "proxy"]
    black76_exposures = [e for e in result.exposures if e.method == "black76"]
    total_abs_gex = sum(abs(e.gex_1pct) for e in result.exposures)
    proxy_abs_gex = sum(abs(e.gex_1pct) for e in proxy_exposures)
    proxy_gex_share = proxy_abs_gex / total_abs_gex if total_abs_gex > 0 else 0.0

    black76_by_expiry: dict[str, int] = {}
    proxy_by_expiry: dict[str, int] = {}
    for expiry in result.expiries:
        black76_by_expiry[expiry] = sum(1 for e in black76_exposures if e.expiry == expiry)
        proxy_by_expiry[expiry] = sum(1 for e in proxy_exposures if e.expiry == expiry)

    black76_audit: dict[str, Any] = {}
    for expiry in result.expiries:
        fw = result.forward_by_expiry.get(expiry, {})
        T = result.time_to_expiry.get(expiry)
        r = 0.0
        black76_audit[expiry] = {
            "trade_date": result.trade_date,
            "expiry_date": result.expiry_dates.get(expiry),
            "expiry_source": "estimated_from_delivery_month",
            "expiry_confidence": "medium",
            "expiry_manual_override_allowed": True,
            "T": _safe_round(T, 8),
            **_forward_audit_for_expiry(
                result.normalized_rows,
                trade_date=result.trade_date,
                expiry=expiry,
                f_value=fw.get("f_value"),
                f_source=fw.get("f_source", result.f_source),
            ),
            "discount_rate": r,
            "discount_factor": _safe_round(math.exp(-r * T), 8) if T is not None else None,
            "iv_source": "settlement-implied Black-76 IV",
            "iv_selection": "model_delta_nearest_target_abs_delta",
            "iv_outlier_filter": "settlement >= 0, IV between 1% and 300%; rows outside no-arbitrage IV bounds excluded from IV/GammaZero grid",
        }

    total_gex = sum(summary.get("total_gex", 0.0) for summary in result.gex_summary_by_expiry.values())
    net_gex = sum(summary.get("net_gex", 0.0) for summary in result.gex_summary_by_expiry.values())
    return {
        "price_anchor_audit": {
            "model_f_by_expiry": result.forward_by_expiry,
            "report_p0": result.report_p0,
            "report_p0_source": result.report_p0_source,
            "report_p0_timestamp": result.report_p0_timestamp,
            "report_p0_warnings": result.report_p0_warnings,
            "live_p0": result.live_p0,
            "live_p0_source": result.live_p0_source,
            "live_p0_timestamp": result.live_p0_timestamp,
            "live_p0_warnings": result.live_p0_warnings,
            "rule": "Black-76/GEX uses per-expiry model_f; daily structure uses report_p0; intraday strategy uses live_p0 only when provided.",
        },
        "p0_audit": {
            "p0": result.report_p0,
            "p0_source": result.report_p0_source,
            "p0_timestamp": result.report_p0_timestamp,
            "p0_warnings": result.report_p0_warnings,
            "compatibility_note": "legacy p0 aliases report_p0; live price is live_p0",
        },
        "data_audit": {
            "product_rows": raw_rows,
            "raw_rows": raw_rows,
            "raw_detail_rows": raw_rows,
            "valid_rows": valid_pricing_rows,
            "valid_pricing_rows": valid_pricing_rows,
            "analysis_strike_min": result.analysis_strike_min,
            "analysis_strike_max": result.analysis_strike_max,
            "analysis_range_source": result.analysis_range_source,
            "range_rows": range_rows,
            "range_rows_analysis": range_rows,
            "excluded_outside_analysis_range": excluded_outside_analysis_range,
            "excluded_by_full_chain_filter_rows": result.norm_report.rows_filtered_by_strike,
            "excluded_by_missing_pricing_rows": result.norm_report.rows_missing_settlement,
            "missing_delta_rows": result.norm_report.rows_missing_delta,
            "proxy_rows": len(proxy_exposures),
            "proxy_strikes": len({(e.expiry, e.strike, e.option_type) for e in proxy_exposures}),
            "proxy_gex_share": _safe_round(proxy_gex_share, 6),
            "black76_rows": len(black76_exposures),
            "black76_rows_by_expiry": black76_by_expiry,
            "proxy_rows_by_expiry": proxy_by_expiry,
            "row_count_note": "product_rows/raw_rows is after product filter; valid_rows is full-chain normalized rows; range_rows is rows inside analysis_strike_min/max used by main GEX Top/WallScore/S-R/strategy; full-chain rows outside range are retained only for anomaly/tail-risk context.",
        },
        "black76_audit": black76_audit,
        "gex_audit": {
            "gex_scope": "main_analysis_range",
            "analysis_range": [result.analysis_strike_min, result.analysis_strike_max],
            "gex_unit": "USD per 1% move estimated model gamma exposure",
            "gex_definition": "Gamma × OI × contract_multiplier × F^2 × 0.01",
            "notional_warning": "GEX is second-order model exposure, not delta notional and not a direct dealer inventory estimate.",
            "total_call_gex": _safe_round(sum(s.get("call_gex", 0.0) for s in result.gex_summary_by_expiry.values()), 2),
            "total_put_gex": _safe_round(sum(s.get("put_gex", 0.0) for s in result.gex_summary_by_expiry.values()), 2),
            "net_gex": _safe_round(net_gex, 2),
            "total_gex": _safe_round(total_gex, 2),
            "net_gex_ratio": _safe_round(net_gex / total_gex, 6) if total_gex else None,
            "gamma_zero_full": result.netgex.gamma_zero,
            "gamma_zero_range": [result.netgex.price_grid[0], result.netgex.price_grid[-1]] if result.netgex.price_grid else None,
            "proxy_included_in_zero": False,
            "gamma_zero_note": "Gamma Zero grid uses only rows with settlement-implied Black-76 IV; proxy rows are excluded from zero-axis fitting and used only for static exposure/wall context.",
        },
        "wallscore_audit": {
            **_WALL_SCORE_FORMULA,
            "main_range_scope": [result.analysis_strike_min, result.analysis_strike_max],
            "full_chain_anomaly_scope": "outside_main_range_only_not_for_strategy",
        },
        "intent_audit": {
            "intent_scope": "full_chain_regime_classification",
            "intent_label": result.intent.primary_intent.intent_type.value if hasattr(result.intent.primary_intent.intent_type, "value") else str(result.intent.primary_intent.intent_type),
            "intent_confidence": _safe_round(result.intent.primary_intent.confidence, 4),
            "defense_score": _safe_round(result.intent.all_scores.get("I1_defensive"), 4),
            "rebalance_score": _safe_round(result.intent.all_scores.get("I2_structured_rebalance"), 4),
            "trap_score": _safe_round(result.intent.all_scores.get("I3_trap"), 4),
            "trend_score": _safe_round(result.intent.all_scores.get("I4_trend_launch"), 4),
            "roll_score": _safe_round(max((signal.confidence for signal in result.roll_signals), default=0.0), 4),
            "wording": _intent_wording_text(
                result.intent.primary_intent.intent_type.value,
                result.intent.primary_intent.confidence,
                result.intent.all_scores,
            ),
        },
    }

# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------

def snapshot_to_dict(result: OptionsAnalysisResult) -> dict[str, Any]:
    """Convert OptionsAnalysisResult to a JSON-serializable dict."""

    def _wall_dict(w: Wall) -> dict[str, Any]:
        return {
            "strike": w.strike,
            "expiry": w.expiry,
            "side": w.side,
            "wall_type": w.wall_type.value if hasattr(w.wall_type, "value") else str(w.wall_type),
            "oi": w.oi,
            "oi_change": w.oi_change,
            "volume": w.volume,
            "block": w.block,
            "pnt": w.pnt,
            "gex": round(w.gex, 2),
            "net_gex": round(w.net_gex, 2),
        }

    def _scored_wall_dict(sw: WallScoredWall) -> dict[str, Any]:
        return {
            **_wall_dict(sw.wall),
            "dominant_side": (
                "Call" if sw.wall.net_gex > 0 else "Put" if sw.wall.net_gex < 0 else "Balanced"
            ),
            "net_gex_bias": round(sw.wall.net_gex, 2),
            "wall_score": round(sw.wall_score, 2),
            "rank": sw.rank,
            "components": {
                "gex_score": round(sw.gex_score, 4),
                "oi_score": round(sw.oi_score, 4),
                "doi_score": round(sw.doi_score, 4),
                "volume_score": round(sw.volume_score, 4),
                "block_pnt_score": round(sw.block_pnt_score, 4),
                "distance_score": round(sw.distance_score, 4),
            },
        }

    def _roll_dict(r: RollSignal) -> dict[str, Any]:
        return {
            "roll_type": r.roll_type.value if hasattr(r.roll_type, "value") else str(r.roll_type),
            "near_expiry": r.near_expiry,
            "far_expiry": r.far_expiry,
            "evidence": r.evidence,
            "confidence": round(r.confidence, 4),
        }

    # Walls grouped by type for backward compat
    call_oi_walls = [_wall_dict(w) for w in result.walls if w.side == "CALL"]
    put_oi_walls = [_wall_dict(w) for w in result.walls if w.side == "PUT"]
    block_pnt_walls = [_wall_dict(w) for w in result.walls if (w.block + w.pnt) > 0]

    intent = result.intent
    primary = intent.primary_intent
    intent_type_val = primary.intent_type.value if hasattr(primary.intent_type, "value") else str(primary.intent_type)

    # Support / resistance from scored walls near p0
    support_candidates: list[dict[str, Any]] = []
    resistance_candidates: list[dict[str, Any]] = []
    if result.p0 is not None:
        for sw in result.scored_walls:
            w = sw.wall
            dist_pct = (w.strike - result.p0) / result.p0 * 100 if result.p0 else 0.0
            entry = {
                "strike": w.strike,
                "wall_type": w.wall_type.value if hasattr(w.wall_type, "value") else str(w.wall_type),
                "wall_score": round(sw.wall_score, 2),
                "distance_pct": round(dist_pct, 2),
            }
            if w.side == "PUT" and w.strike < result.p0:
                support_candidates.append(entry)
            elif w.side == "CALL" and w.strike > result.p0:
                resistance_candidates.append(entry)

    support_candidates.sort(key=lambda x: abs(x["distance_pct"]))
    resistance_candidates.sort(key=lambda x: abs(x["distance_pct"]))

    return {
        "version": "1.0",
        "trade_date": result.trade_date,
        "generated_at": result.generated_at,
        "data_source": {
            "report_date": result.trade_date,
            "status": result.data_source_status,
            "source_url": result.data_source_url,
            "product": result.product,
            "expiries": result.expiries,
            "row_count": len(result.normalized_rows),
            "input_snapshot_ids": result.input_snapshot_ids,
        },
        "parameters": {
            "p0": result.report_p0,
            "p0_source": result.report_p0_source,
            "p0_timestamp": result.report_p0_timestamp,
            "p0_warnings": result.report_p0_warnings,
            "model_f": result.forward_by_expiry,
            "report_p0": result.report_p0,
            "report_p0_source": result.report_p0_source,
            "report_p0_timestamp": result.report_p0_timestamp,
            "report_p0_warnings": result.report_p0_warnings,
            "live_p0": result.live_p0,
            "live_p0_source": result.live_p0_source,
            "live_p0_timestamp": result.live_p0_timestamp,
            "live_p0_warnings": result.live_p0_warnings,
            "price_anchor_rule": "model_f for Black-76/GEX; report_p0 for end-of-day structure; live_p0 for intraday strategy only",
            "analysis_range": {
                "strike_min": result.analysis_strike_min,
                "strike_max": result.analysis_strike_max,
                "source": result.analysis_range_source,
            },
            "f_source": result.f_source,
            "f_value": result.forward_price,
            "forward_by_expiry": result.forward_by_expiry,
            "r": 0.0,
            "model": "black-76",
            "used_real_gex": result.used_real_gex,
            "netgex_scope": "aggregate_across_expiries",
        },
        "normalization": {
            "total_input_rows": result.norm_report.total_input_rows,
            "duplicates_merged": result.norm_report.duplicates_merged,
            "rows_missing_settlement": result.norm_report.rows_missing_settlement,
            "rows_missing_delta": result.norm_report.rows_missing_delta,
            "rows_filtered_by_full_chain_filter": result.norm_report.rows_filtered_by_strike,
            "analysis_range_rows": sum(
                1 for row in result.normalized_rows
                if result.analysis_strike_min <= row.strike <= result.analysis_strike_max
            ),
            "warnings": list(result.norm_report.warnings),
        },
        "gex": {
            "netgex_aggregate": {
                "gamma_zero": {
                    "price": result.netgex.gamma_zero,
                    "method": result.netgex.gamma_zero_method,
                    "scope": "aggregate_across_expiries",
                },
                "price_grid": result.netgex.price_grid,
                "net_gex_values": result.netgex.net_gex_values,
            },
            "by_expiry": {
                expiry: {
                    "gex_top": result.gex_top_by_expiry.get(expiry, []),
                    "summary": result.gex_summary_by_expiry.get(expiry, {}),
                    "iv_skew": result.iv_skew_by_expiry.get(expiry, {}),
                }
                for expiry in result.expiries
            },
        },
        "exposure": result.exposure_summary_by_expiry,
        "walls": {
            "call_oi_walls": call_oi_walls,
            "put_oi_walls": put_oi_walls,
            "block_pnt_walls": block_pnt_walls,
        },
        "wall_scores": [_scored_wall_dict(sw) for sw in result.scored_walls[:20]],
        "wall_scores_scope": "main_analysis_range",
        "wall_scores_full_chain_anomaly": [
            _scored_wall_dict(sw)
            for sw in result.full_chain_scored_walls
            if not (result.analysis_strike_min <= sw.wall.strike <= result.analysis_strike_max)
        ][:20],
        "roll_signals": [_roll_dict(r) for r in result.roll_signals],
        "intent": {
            "type": intent_type_val,
            "score": round(primary.score, 4),
            "confidence": round(primary.confidence, 4),
            "evidence": primary.evidence,
        },
        "support_resistance": {
            "support": support_candidates[:5],
            "resistance": resistance_candidates[:5],
        },
        "data_quality": {
            "categories": {
                "rows_missing_settlement": result.data_quality.rows_missing_settlement,
                "rows_missing_delta": result.data_quality.rows_missing_delta,
                "zero_oi": result.data_quality.zero_oi_count,
                "low_oi": result.data_quality.low_oi_count,
                "proxy_strikes": result.data_quality.proxy_strike_count,
                "prelim_data": result.data_quality.prelim_data_count,
                "rows_filtered_by_strike": result.data_quality.rows_filtered_by_strike,
                "duplicates_merged": result.data_quality.duplicates_merged,
            },
            "warnings": result.data_quality.warnings,
        },
        "audit": _build_audit_metadata(result),
        # ── P4-06: multi-day calibration ──
        "calibration": _calibration_to_dict(result.calibration),
        # ── T3: data_levels metadata for layered display ──
        "data_levels": {
            "level_1_confirmed": {
                "label": "原始可验证数据",
                "items": [
                    {"field": "wall_scores", "description": "墙位 OI/Volume/Settlement 评分", "count": len(result.scored_walls)},
                    {"field": "gex.netgex_aggregate", "description": "GEX 聚合（基于 Black-76 模型计算）"},
                    {"field": "normalization", "description": "数据规范化报告"},
                    {"field": "data_quality", "description": "数据质量分类统计"},
                ],
            },
            "level_2_computed": {
                "label": "模型计算结果",
                "items": [
                    {"field": "walls", "description": "墙位类型分类（Call/Put/Block/Pin）"},
                    {"field": "intent", "description": "机构意图评分"},
                    {"field": "gex.by_expiry", "description": "按到期日 GEX/IV 偏度"},
                    {"field": "exposure", "description": "按到期日敞口摘要"},
                    {"field": "roll_signals", "description": "换月信号"},
                ],
            },
            "level_3_interpretive": {
                "label": "解释性分析",
                "items": [
                    {"field": "support_resistance", "description": "支撑/阻力位（基于墙位评分与 p0 距离推断）"},
                    {"field": "calibration", "description": "校准变化与墙位迁移检测"},
                    {"field": "wall_scores_full_chain_anomaly", "description": "全链异常墙位（分析范围外）"},
                ],
            },
        },
    }


def _calibration_to_dict(cal: CalibrationResult | None) -> dict[str, Any] | None:
    """Convert CalibrationResult to a JSON-safe dict."""
    if cal is None:
        return None
    return {
        "calculation_method": cal.calculation_method,
        "wall_map": cal.wall_map,
        "wall_score_delta_1d": cal.wall_score_delta_1d,
        "wall_score_delta_1w": cal.wall_score_delta_1w,
        "oi_change_by_strike": cal.oi_change_by_strike,
        "expiry_roll_signal": [
            {
                "near_month": sig.near_month,
                "next_month": sig.next_month,
                "near_oi_change": sig.near_oi_change,
                "next_oi_change": sig.next_oi_change,
                "roll_activity": sig.roll_activity,
                "roll_confidence": sig.roll_confidence,
            }
            for sig in cal.expiry_roll_signal
        ],
        "near_month_vs_next_month": cal.near_month_vs_next_month,
        "calibration_warnings": cal.calibration_warnings.messages,
        "source_refs": cal.source_refs,
    }
