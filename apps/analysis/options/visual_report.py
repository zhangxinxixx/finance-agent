"""Renderer-facing view model for CME options visual reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from apps.analysis.options.snapshot import OptionsAnalysisResult


@dataclass(frozen=True)
class VisualMetricRow:
    label: str
    value: str
    note: str = ""
    tone: str = "neutral"


@dataclass(frozen=True)
class VisualMetricCard:
    label: str
    value: str
    change: str = ""
    tone: str = "neutral"


@dataclass(frozen=True)
class VisualWallRow:
    strike: str
    expiry: str
    wall_type: str
    net_gex: str
    wall_score: str
    tone: str


@dataclass(frozen=True)
class VisualLevelRow:
    strike: str
    wall_type: str
    wall_score: str
    distance_pct: str
    tone: str


@dataclass(frozen=True)
class VisualScenarioRow:
    title: str
    detail: str
    tone: str = "neutral"


@dataclass(frozen=True)
class OptionsVisualReportVM:
    version: str
    trade_date: str
    product: str
    expiries: list[str]
    data_source_status: str
    generated_at: str
    hero_title: str
    hero_subtitle: str
    tags: list[str]
    core_conclusion: str
    model_parameters: list[VisualMetricRow]
    key_metrics: list[VisualMetricCard]
    gex_top_walls: list[VisualWallRow]
    gex_changes: list[VisualMetricRow]
    iv_skew_rows: list[VisualMetricRow]
    greeks: list[VisualMetricCard]
    call_oi_walls: list[VisualMetricRow]
    put_oi_walls: list[VisualMetricRow]
    wall_scores: list[VisualWallRow]
    roll_structure: list[VisualMetricRow]
    support_levels: list[VisualLevelRow]
    resistance_levels: list[VisualLevelRow]
    scenarios: list[VisualScenarioRow]
    switches: list[VisualMetricRow]
    institutional_intent: str
    data_quality_notes: list[str]
    source_refs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_options_visual_report_vm(result: OptionsAnalysisResult) -> OptionsVisualReportVM:
    source_refs = _build_source_refs(result)
    gamma_zero = result.netgex.gamma_zero
    key_metrics = [
        VisualMetricCard("Gamma Zero", _fmt_float(gamma_zero), tone="info"),
        VisualMetricCard("Rows", str(len(result.normalized_rows))),
        VisualMetricCard("Top Walls", str(len(result.scored_walls))),
        VisualMetricCard("Status", result.data_source_status, tone=_status_tone(result.data_source_status)),
    ]
    data_quality_notes = list(result.data_quality.warnings)
    if result.calibration is None:
        data_quality_notes.append("Calibration unavailable for this run.")
    else:
        data_quality_notes.extend(result.calibration.calibration_warnings.messages)

    return OptionsVisualReportVM(
        version="cme_options_visual_report.v1",
        trade_date=result.trade_date,
        product=result.product,
        expiries=result.expiries,
        data_source_status=result.data_source_status,
        generated_at=result.generated_at,
        hero_title=f"CME {result.product} 期权结构视觉报告 · {result.trade_date}",
        hero_subtitle=f"{', '.join(result.expiries)} · {result.data_source_status} · Black-76 / GEX / WallScore",
        tags=_build_tags(result),
        core_conclusion=_build_core_conclusion(result),
        model_parameters=_build_model_parameters(result),
        key_metrics=key_metrics,
        gex_top_walls=_build_top_walls(result),
        gex_changes=_build_gex_changes(result),
        iv_skew_rows=_build_iv_skew_rows(result),
        greeks=_build_greeks(result),
        call_oi_walls=_build_oi_rows(result, side="CALL"),
        put_oi_walls=_build_oi_rows(result, side="PUT"),
        wall_scores=_build_top_walls(result, limit=10),
        roll_structure=_build_roll_structure(result),
        support_levels=_build_levels(result, "support"),
        resistance_levels=_build_levels(result, "resistance"),
        scenarios=_build_scenarios(result),
        switches=_build_switches(result),
        institutional_intent=_build_intent_text(result.intent.primary_intent.evidence),
        data_quality_notes=data_quality_notes,
        source_refs=source_refs,
    )


def _build_source_refs(result: OptionsAnalysisResult) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if result.data_source_url:
        refs.append(
            {
                "source": "cme_bulletin",
                "url": result.data_source_url,
                "status": result.data_source_status,
            }
        )
    if result.input_snapshot_ids:
        refs.append(
            {
                "source": "options_analysis_input",
                "input_snapshot_ids": dict(result.input_snapshot_ids),
            }
        )
    if result.calibration is not None:
        refs.extend(result.calibration.source_refs)
    if not refs:
        refs.append(
            {
                "source": "cme_options_analysis",
                "trade_date": result.trade_date,
                "product": result.product,
                "status": result.data_source_status,
            }
        )
    return refs


def _build_tags(result: OptionsAnalysisResult) -> list[str]:
    tags = [result.data_source_status]
    if result.netgex.gamma_zero is not None:
        tags.append(f"Gamma Zero {_fmt_float(result.netgex.gamma_zero)}")
    if result.intent.primary_intent.intent_type.value:
        tags.append(result.intent.primary_intent.intent_type.value)
    return tags


def _build_core_conclusion(result: OptionsAnalysisResult) -> str:
    intent = result.intent.primary_intent
    gamma_zero = _fmt_float(result.netgex.gamma_zero)
    return (
        f"{result.product} 当前结构信号为 {intent.intent_type.value}，"
        f"Gamma Zero 位于 {gamma_zero}，"
        f"主分析区间为 {result.analysis_strike_min}-{result.analysis_strike_max}。"
    )


def _build_model_parameters(result: OptionsAnalysisResult) -> list[VisualMetricRow]:
    rows = [
        VisualMetricRow("Report P0", _fmt_float(result.report_p0), result.report_p0_source, "neutral"),
        VisualMetricRow("Forward Price", _fmt_float(result.forward_price), result.f_source, "neutral"),
        VisualMetricRow("Gamma Zero", _fmt_float(result.netgex.gamma_zero), result.netgex.gamma_zero_method, "info"),
    ]
    for expiry, forward in result.forward_by_expiry.items():
        rows.append(
            VisualMetricRow(
                f"{expiry} Model F",
                _fmt_float(forward.get("f_value")),
                str(forward.get("f_source") or ""),
                "neutral",
            )
        )
    return rows


def _build_top_walls(result: OptionsAnalysisResult, limit: int = 5) -> list[VisualWallRow]:
    rows: list[VisualWallRow] = []
    for scored in result.scored_walls[:limit]:
        wall = scored.wall
        rows.append(
            VisualWallRow(
                strike=str(wall.strike),
                expiry=wall.expiry,
                wall_type=wall.wall_type.value if hasattr(wall.wall_type, "value") else str(wall.wall_type),
                net_gex=_fmt_signed(wall.net_gex),
                wall_score=_fmt_float(scored.wall_score),
                tone="bullish" if wall.net_gex > 0 else "bearish" if wall.net_gex < 0 else "neutral",
            )
        )
    return rows


def _build_gex_changes(result: OptionsAnalysisResult) -> list[VisualMetricRow]:
    rows: list[VisualMetricRow] = []
    if result.calibration is None:
        return [VisualMetricRow("Calibration", "unavailable", "No multi-day calibration for this run.", "warning")]
    for strike, delta in list(result.calibration.wall_score_delta_1d.items())[:5]:
        rows.append(
            VisualMetricRow(
                f"Strike {strike}",
                _fmt_signed(delta),
                "1d wall score delta",
                "bullish" if delta > 0 else "bearish" if delta < 0 else "neutral",
            )
        )
    return rows or [VisualMetricRow("Calibration", "unavailable", "No 1d deltas available.", "warning")]


def _build_iv_skew_rows(result: OptionsAnalysisResult) -> list[VisualMetricRow]:
    rows: list[VisualMetricRow] = []
    for expiry, skew in result.iv_skew_by_expiry.items():
        rows.append(
            VisualMetricRow(
                f"{expiry} ATM IV",
                _fmt_pct(skew.get("atm_iv")),
                f"25D skew {_fmt_signed(skew.get('skew_25d'))}",
                "warning" if (skew.get("skew_25d") or 0) > 0 else "neutral",
            )
        )
    return rows or [VisualMetricRow("IV Skew", "unavailable", "No skew rows available.", "warning")]


def _build_greeks(result: OptionsAnalysisResult) -> list[VisualMetricCard]:
    aggregate = result.exposure_summary_by_expiry.get("aggregate", {})
    return [
        VisualMetricCard("Net GEX", _fmt_signed(aggregate.get("net_gex")), tone="info"),
        VisualMetricCard("Net DEX", _fmt_signed(aggregate.get("net_dex")), tone="neutral"),
        VisualMetricCard("Vega", _fmt_signed(aggregate.get("vega")), tone="neutral"),
        VisualMetricCard("Theta", _fmt_signed(aggregate.get("theta")), tone="warning"),
    ]


def _build_oi_rows(result: OptionsAnalysisResult, *, side: str) -> list[VisualMetricRow]:
    rows: list[VisualMetricRow] = []
    for wall in result.walls:
        if wall.side != side:
            continue
        rows.append(
            VisualMetricRow(
                f"{wall.strike}",
                f"OI {wall.oi}",
                f"ΔOI {wall.oi_change} / Vol {wall.volume}",
                "bullish" if side == "CALL" else "bearish",
            )
        )
        if len(rows) >= 5:
            break
    return rows


def _build_roll_structure(result: OptionsAnalysisResult) -> list[VisualMetricRow]:
    if not result.roll_signals:
        return [VisualMetricRow("Roll", "unavailable", "No expiry roll signal detected.", "warning")]
    return [
        VisualMetricRow(
            f"{signal.near_expiry} → {signal.far_expiry}",
            signal.roll_type.value if hasattr(signal.roll_type, "value") else str(signal.roll_type),
            f"confidence {_fmt_float(signal.confidence)}",
            "neutral",
        )
        for signal in result.roll_signals[:5]
    ]


def _build_levels(result: OptionsAnalysisResult, kind: str) -> list[VisualLevelRow]:
    source = result.scored_walls
    levels: list[VisualLevelRow] = []
    p0 = result.report_p0 or result.p0
    for scored in source:
        wall = scored.wall
        if p0 is None:
            distance_pct = "n/a"
        else:
            distance_pct = _fmt_pct((wall.strike - p0) / p0)
        if kind == "support" and wall.side != "PUT":
            continue
        if kind == "resistance" and wall.side != "CALL":
            continue
        levels.append(
            VisualLevelRow(
                strike=str(wall.strike),
                wall_type=wall.wall_type.value if hasattr(wall.wall_type, "value") else str(wall.wall_type),
                wall_score=_fmt_float(scored.wall_score),
                distance_pct=distance_pct,
                tone="bullish" if kind == "resistance" else "bearish",
            )
        )
        if len(levels) >= 5:
            break
    if not levels:
        fallback = result.scored_walls[:3]
        for scored in fallback:
            wall = scored.wall
            levels.append(
                VisualLevelRow(
                    strike=str(wall.strike),
                    wall_type=wall.wall_type.value if hasattr(wall.wall_type, "value") else str(wall.wall_type),
                    wall_score=_fmt_float(scored.wall_score),
                    distance_pct="unavailable",
                    tone="warning",
                )
            )
    return levels


def _build_scenarios(result: OptionsAnalysisResult) -> list[VisualScenarioRow]:
    intent = result.intent.primary_intent
    return [
        VisualScenarioRow(
            title="Base Case",
            detail=f"{intent.intent_type.value} with confidence {_fmt_float(intent.confidence)}.",
            tone="neutral",
        ),
        VisualScenarioRow(
            title="Gamma Trigger",
            detail=f"Watch Gamma Zero around {_fmt_float(result.netgex.gamma_zero)}.",
            tone="info",
        ),
    ]


def _build_switches(result: OptionsAnalysisResult) -> list[VisualMetricRow]:
    return [
        VisualMetricRow("Data Status", result.data_source_status, "CME source status", _status_tone(result.data_source_status)),
        VisualMetricRow("Real GEX", "enabled" if result.used_real_gex else "proxy", "Exposure calculation mode", "neutral"),
    ]


def _build_intent_text(evidence: Any) -> str:
    if isinstance(evidence, list):
        return "；".join(str(item) for item in evidence if item)
    return str(evidence or "unavailable")


def _fmt_float(value: Any) -> str:
    if value is None:
        return "unavailable"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_signed(value: Any) -> str:
    if value is None:
        return "unavailable"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{num:+,.2f}"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "unavailable"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _status_tone(status: str) -> str:
    status_upper = status.upper()
    if status_upper.startswith("FINAL"):
        return "bullish"
    if status_upper.startswith("PRELIM"):
        return "warning"
    return "neutral"
