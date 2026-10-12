from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timezone
from math import isfinite
from typing import Any

from apps.api.services.agent_read_model import build_dashboard_agent_summary
from apps.api.services.dashboard_analysis_service import build_dashboard_integrated_analysis
from apps.api.services.dashboard_research_service import get_dashboard_research_context
from apps.api.services.gold_mainline_service import get_gold_macro_overview_latest
from apps.api.services.macro_service import get_macro_latest, get_market_macro_latest
from apps.api.services.market_service import get_market_tickers
from apps.api.services.options_service import get_options_snapshot
from apps.api.services.report_service import get_jin10_agent_analysis_latest, get_strategy_card_latest, list_reports_index
from apps.api.services.source_service import get_data_source_statuses
from apps.api.services.task_service import list_recent_tasks
from apps.features.research.price_action import cme_weight


logger = logging.getLogger(__name__)


def _explicit_pin_level(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _safe_trade_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _options_confidence(
    *,
    options_snapshot: dict[str, Any],
    intent_score: float | None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    base = float(intent_score or 0.0)
    evaluated_at = as_of or datetime.now(UTC)
    weight = cme_weight(
        {"status": "available", "data": options_snapshot},
        as_of=evaluated_at.isoformat(),
    )
    multiplier = float(weight.get("weight_multiplier") or 0.0)
    score = max(0.0, min(base * multiplier, 1.0))
    if score >= 0.7:
        level = "high"
    elif score >= 0.45:
        level = "medium"
    else:
        level = "low"

    data_source = options_snapshot.get("data_source") or {}
    data_status = str(data_source.get("status") or "UNAVAILABLE").upper()
    reasons = [f"cme_evidence_weight_{multiplier:g}"]
    if data_status in {"PRELIM", "PRELIMINARY"}:
        reasons.append("PRELIM_usable_without_extra_discount")
    if weight.get("role") == "background_only":
        reasons.append("background_only")
    if multiplier == 0.0:
        reasons.append("unavailable_or_unverified_source_age")

    return {
        "score": score,
        "level": level,
        "trade_date": weight.get("report_date"),
        "age_days": weight.get("calendar_days"),
        "calendar_days": weight.get("calendar_days"),
        "trading_days": weight.get("trading_days"),
        "weight_multiplier": multiplier,
        "role": weight.get("role"),
        "rule": weight.get("rule"),
        "source_version": weight.get("source_version", "unknown"),
        "is_probability": False,
        "data_status": data_status,
        "reasons": reasons,
    }


def _report_recency(report: dict[str, Any]) -> tuple[date, datetime, str]:
    generated_at = datetime.min.replace(tzinfo=UTC)
    for field in ("generated_at", "created_at"):
        try:
            value = datetime.fromisoformat(str(report.get(field) or "").replace("Z", "+00:00"))
            generated_at = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
            break
        except ValueError:
            continue
    return (
        _safe_trade_date(str(report.get("trade_date") or "")) or date.min,
        generated_at,
        str(report.get("report_id") or ""),
    )


def _select_latest_reports(reports: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:

    available_reports = []
    for report in reports:
        if not report.get("available"):
            continue
        item = dict(report)
        item.setdefault("status", "ready")
        available_reports.append(item)
    return sorted(available_reports, key=_report_recency, reverse=True)[:limit]


def _select_latest_supplemental_report(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    supplemental = [
        dict(report)
        for report in reports
        if report.get("available") and report.get("type") == "macro_event_followup"
    ]
    if not supplemental:
        return None

    for report in supplemental:
        report.setdefault("status", "ready")

    return sorted(supplemental, key=_report_recency, reverse=True)[0]


def _latest_report_date(reports: list[dict[str, Any]], *, include_degraded: bool) -> str | None:
    dates: list[date] = []
    for report in reports:
        if not report.get("available"):
            continue
        if not include_degraded and str(report.get("status") or "ready") == "degraded":
            continue
        parsed = _safe_trade_date(str(report.get("trade_date") or ""))
        if parsed is not None:
            dates.append(parsed)
    return max(dates).isoformat() if dates else None


def _build_composite_analysis_status(
    *,
    latest_reports: list[dict[str, Any]],
    all_reports: list[dict[str, Any]],
    options_trade_date: str | None,
) -> dict[str, Any]:
    strategy_ref = _latest_report_ref(all_reports, report_type="strategy_card")
    final_report_ref = _latest_report_ref(all_reports, report_type="final_report")
    strategy_date = strategy_ref.get("trade_date") if strategy_ref else None
    final_report_date = final_report_ref.get("trade_date") if final_report_ref else None
    composite_date = strategy_date or final_report_date
    composite_run_id = (
        strategy_ref.get("run_id")
        if strategy_ref and strategy_date == composite_date
        else final_report_ref.get("run_id") if final_report_ref else None
    )

    context_dates = [
        _safe_trade_date(value)
        for value in [
            _latest_report_date(all_reports, include_degraded=False),
            options_trade_date,
        ]
        if value
    ]
    context_dates = [item for item in context_dates if item is not None]
    latest_eligible_context_date = max(context_dates).isoformat() if context_dates else None
    latest_report_date = _latest_report_date(all_reports, include_degraded=True)

    warnings: list[str] = []
    degraded_newer_reports = [
        report
        for report in latest_reports
        if str(report.get("status") or "ready") == "degraded"
        and composite_date
        and (parsed := _safe_trade_date(str(report.get("trade_date") or ""))) is not None
        and parsed > date.fromisoformat(composite_date)
    ]

    if composite_date is None:
        status = "missing"
        warnings.append("composite: strategy_card/final_report not generated")
    elif latest_eligible_context_date and date.fromisoformat(composite_date) < date.fromisoformat(latest_eligible_context_date):
        status = "stale"
        warnings.append(f"composite: stale vs latest eligible context {latest_eligible_context_date}")
    elif degraded_newer_reports:
        status = "partial"
        warnings.append("composite: newer Jin10 reports are degraded and excluded from daily composite")
    else:
        status = "available"

    return {
        "status": status,
        "trade_date": composite_date,
        "run_id": composite_run_id,
        "strategy_trade_date": strategy_date,
        "strategy_run_id": strategy_ref.get("run_id") if strategy_ref else None,
        "final_report_trade_date": final_report_date,
        "final_report_run_id": final_report_ref.get("run_id") if final_report_ref else None,
        "latest_report_date": latest_report_date,
        "latest_eligible_context_date": latest_eligible_context_date,
        "degraded_newer_reports": [
            {
                "type": report.get("type"),
                "trade_date": report.get("trade_date"),
                "run_id": report.get("run_id"),
                "title": report.get("title"),
                "quality_status": ((report.get("quality_audit") or {}) if isinstance(report.get("quality_audit"), dict) else {}).get("status"),
            }
            for report in degraded_newer_reports
        ],
        "warnings": warnings,
    }


def _latest_report_ref(reports: list[dict[str, Any]], *, report_type: str) -> dict[str, Any] | None:
    candidates = [
        report
        for report in reports
        if report.get("available")
        and report.get("type") == report_type
        and _safe_trade_date(str(report.get("trade_date") or "")) is not None
    ]
    if not candidates:
        return None
    latest = max(
        candidates,
        key=lambda report: (
            _safe_trade_date(str(report.get("trade_date") or "")) or date.min,
            str(report.get("run_id") or ""),
        ),
    )
    return {
        "trade_date": str(latest.get("trade_date") or ""),
        "run_id": latest.get("run_id"),
    }


def _gate_agent_summary(agent_summary: dict[str, Any], composite_analysis: dict[str, Any]) -> dict[str, Any]:
    accepted_run_id = str(composite_analysis.get("run_id") or "")
    degraded_run_ids = {
        str(report.get("run_id"))
        for report in composite_analysis.get("degraded_newer_reports", [])
        if report.get("run_id")
    }
    gated = dict(agent_summary)
    for key in ("synthesis", "coordinator"):
        item = agent_summary.get(key)
        if not isinstance(item, dict):
            continue
        # Detailed source payloads belong to the report/audit endpoint. This
        # card only needs bounded references, never entire article bodies.
        gated[key] = {**item, "source_refs": _compact_strategy_evidence_refs(item.get("source_refs"))}
        item_run_id = str(item.get("run_id") or "")
        if item_run_id in degraded_run_ids:
            status = "degraded"
            reason = f"latest {key} output is tied to a degraded report"
        elif accepted_run_id and item_run_id != accepted_run_id:
            status = "stale"
            reason = f"latest {key} output does not belong to the accepted composite run"
        else:
            continue
        gated[key] = None
        gated[f"{key}_gate"] = {
            "status": status,
            "reason": reason,
            "run_id": item.get("run_id"),
            "snapshot_id": item.get("snapshot_id"),
            "accepted_run_id": accepted_run_id or None,
        }
    return gated


def _load_dashboard_strategy(composite_analysis: dict[str, Any]) -> dict[str, Any]:
    accepted_run_id = str(composite_analysis.get("run_id") or "")
    accepted_trade_date = str(composite_analysis.get("trade_date") or "")
    if not accepted_run_id:
        return {}
    try:
        payload = get_strategy_card_latest()
    except Exception as exc:
        logger.warning(
            "Failed to load accepted strategy card for dashboard summary",
            exc_info=exc,
            extra={"service": "dashboard_summary", "stage": "strategy_card", "degraded": True},
        )
        return {}
    if not isinstance(payload, dict):
        return {}
    card = payload.get("json")
    if not isinstance(card, dict):
        return {}
    if str(card.get("run_id") or payload.get("run_id") or "") != accepted_run_id:
        return {}
    if accepted_trade_date and str(card.get("trade_date") or payload.get("trade_date") or "") != accepted_trade_date:
        return {}
    return {
        "bias": card.get("bias"),
        "direction": card.get("bias"),
        "confidence": card.get("confidence"),
        "macro_phase": card.get("market_regime"),
        "scenario_summary": card.get("scenario_summary"),
        "key_levels": {"resistance": [], "support": []},
        "triggers": card.get("trigger_conditions") or [],
        "invalid_conditions": card.get("invalid_conditions") or [],
        "risk_points": card.get("risk_points") or [],
        "run_id": accepted_run_id,
        "snapshot_id": (card.get("input_snapshot_ids") or {}).get("analysis_snapshot"),
        "evidence_refs": _compact_strategy_evidence_refs(card.get("evidence_refs")),
        "data_quality": card.get("data_quality") or [],
        "data_category_summary": card.get("data_category_summary"),
    }


def _compact_strategy_evidence_refs(value: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    compact: list[dict[str, Any]] = []
    for item in value:
        if len(compact) >= limit:
            break
        if isinstance(item, str):
            compact.append({"source": "strategy_evidence", "ref": item, "description": item})
            continue
        if not isinstance(item, dict):
            continue
        source = item.get("source") or item.get("factor_id")
        ref = item.get("ref") or item.get("snapshot_id")
        description = item.get("description") or item.get("label") or source
        if source or ref or description:
            compact.append(
                {
                    "source": str(source) if source else None,
                    "ref": str(ref) if ref else None,
                    "description": str(description) if description else None,
                }
            )
    return compact


def _load_gold_macro_overview() -> dict[str, Any] | None:
    try:
        overview = get_gold_macro_overview_latest()
    except Exception as exc:
        logger.warning(
            "Failed to load gold macro overview for dashboard summary",
            exc_info=exc,
            extra={"service": "dashboard_summary", "stage": "gold_macro_overview", "degraded": True},
        )
        return None
    return overview if isinstance(overview, dict) and overview else None


def _dashboard_gold_macro_overview(overview: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project the full Gold overview onto fields rendered by Dashboard cards."""

    if not isinstance(overview, dict) or not overview:
        return None

    rankings: list[dict[str, Any]] = []
    for item in overview.get("theme_rankings") or []:
        if not isinstance(item, dict):
            continue
        rankings.append(
            {
                key: item.get(key)
                for key in (
                    "mainline_id",
                    "mainline",
                    "label",
                    "rank",
                    "score",
                    "theme_score",
                    "direction",
                    "direction_score",
                    "impact_score",
                    "confidence_score",
                    "freshness_score",
                )
            }
        )

    conflict = overview.get("driver_conflict")
    projected_conflict = None
    if isinstance(conflict, dict):
        projected_conflict = {
            "status": conflict.get("status"),
            "dominant_driver": conflict.get("dominant_driver"),
            "bullish_drivers": list(conflict.get("bullish_drivers") or [])[:4],
            "bearish_drivers": list(conflict.get("bearish_drivers") or [])[:4],
            "net_effect": conflict.get("net_effect"),
            "explanation": conflict.get("explanation"),
            "verification_needed": list(conflict.get("verification_needed") or [])[:5],
            "source_refs": [],
        }

    chain = overview.get("war_oil_rate_chain")
    projected_chain = None
    if isinstance(chain, dict):
        projected_chain = {
            key: chain.get(key)
            for key in (
                "path_id",
                "label",
                "status",
                "conclusion_code",
                "conclusion_label",
                "net_effect",
                "summary",
            )
        }
        projected_chain.update({"steps": [], "source_refs": [], "artifact_refs": []})

    verification_matrix: list[dict[str, Any]] = []
    for item in overview.get("verification_matrix") or []:
        if not isinstance(item, dict):
            continue
        verification_matrix.append(
            {
                "id": item.get("id"),
                "label": item.get("label"),
                "status": item.get("status"),
                "mainline_id": item.get("mainline_id"),
                "event_id": item.get("event_id"),
                "required_source": item.get("required_source"),
                "reason": item.get("reason"),
                "source_refs": [],
            }
        )
        if len(verification_matrix) >= 5:
            break

    return {
        key: overview.get(key)
        for key in (
            "status",
            "asset",
            "as_of",
            "phase",
            "dominant_mainline",
            "priority_regime",
            "priority_reason",
            "net_bias",
            "risk_score",
            "one_line_conclusion",
        )
    } | {
        "theme_rankings": rankings,
        "driver_conflict": projected_conflict,
        "war_oil_rate_chain": projected_chain,
        "verification_matrix": verification_matrix,
        "key_events": [],
        "source_refs": [],
        "artifact_refs": [],
    }


def _load_latest_jin10_analysis() -> dict[str, Any] | None:
    try:
        return get_jin10_agent_analysis_latest()
    except Exception as exc:
        logger.warning(
            "Failed to load latest Jin10 analysis for dashboard summary",
            exc_info=exc,
            extra={"service": "dashboard_summary", "stage": "jin10_analysis", "degraded": True},
        )
        return None


def _dashboard_options_summary(options_snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    walls_summary = None
    wall_strengths = []
    if options_snapshot:
        for wall in options_snapshot.get("wall_scores") or []:
            score = _explicit_pin_level(wall.get("wall_score"))
            if score is not None and 0 <= score <= 1:
                wall_strengths.append(score)
        sr = options_snapshot.get("support_resistance", {})
        walls_summary = {
            "resistance": [{"strike": w["strike"], "score": w.get("wall_score", 0), "distance_pct": w.get("distance_pct")} for w in sr.get("resistance", [])[:3]],
            "support": [{"strike": w["strike"], "score": w.get("wall_score", 0), "distance_pct": w.get("distance_pct")} for w in sr.get("support", [])[:3]],
        }

    return None if not options_snapshot else {
        "trade_date": options_snapshot.get("trade_date"),
        "product": (options_snapshot.get("data_source") or {}).get("product"),
        "expiries": (options_snapshot.get("data_source") or {}).get("expiries", []),
        "intent": (options_snapshot.get("intent") or {}).get("type"),
        "intent_score": (options_snapshot.get("intent") or {}).get("score"),
        "gamma_zero": ((options_snapshot.get("gex") or {}).get("netgex_aggregate") or {}).get("gamma_zero", {}).get("price"),
        "gamma_flip_label": ((options_snapshot.get("gex") or {}).get("gamma_flip") or {}).get("label"),
        "gex_semantics_label": (options_snapshot.get("gex_semantics") or {}).get("label"),
        "dealer_position_unknown": (options_snapshot.get("gex_semantics") or {}).get(
            "dealer_position_unknown", options_snapshot.get("dealer_position_unknown", True)
        ),
        "coordinate_space": "GC futures",
        "pin_level": _explicit_pin_level(options_snapshot.get("pin_level")),
        "forward_price": (options_snapshot.get("parameters") or {}).get("f_value"),
        # Absolute strength in the selected analysis window, never a side probability.
        "wall_score": max(wall_strengths, default=None),
        "walls": walls_summary,
        "data_status": (options_snapshot.get("data_source") or {}).get("status", "UNAVAILABLE"),
        "confidence": _options_confidence(
            options_snapshot=options_snapshot,
            intent_score=(options_snapshot.get("intent") or {}).get("score"),
        ),
    }


def _get_dashboard_current_market() -> dict[str, Any]:
    """Latest observed facts, separate from the frozen research/strategy context."""
    def read_source(loader, fallback):
        try:
            return loader() or fallback
        except Exception:
            logger.warning("Dashboard current market source unavailable: %s", loader.__name__, exc_info=True)
            return fallback

    macro = read_source(get_market_macro_latest, None)
    options = read_source(get_options_snapshot, None)
    market = read_source(get_market_tickers, {})
    tickers = market.get("tickers") or {}
    return {
        "source": "latest_collected_data",
        "macro": macro,
        "options": _dashboard_options_summary(options),
        "realtime_quotes": tickers,
        "realtime_status": {
            "source": "latest_collected_data" if tickers else "unavailable",
            "generated_at": market.get("generated_at"),
            "available_symbols": sorted(tickers),
            "message": "最新采集数据，各指标以观测日期为准；研究结论独立校验。",
        },
    }


def get_dashboard_summary() -> dict[str, Any]:
    reports_index = list_reports_index()
    all_reports = reports_index.get("reports", [])
    research = get_dashboard_research_context()
    research_available = bool(research and research.get("status") == "available")
    facts_available = bool(research and research.get("facts_status", research.get("status")) == "available")
    options_snapshot = (research.get("options") if facts_available else None) if research is not None else get_options_snapshot()
    market_tickers = {} if research is not None else get_market_tickers()
    # A report view must consume that report's frozen facts. The legacy macro
    # store may be older even when a new research report has completed.
    macro = (research.get("macro") if facts_available else None) if research is not None else get_macro_latest()
    if research is not None:
        anchor = research.get("price_anchor") or {} if research_available else {}
        market_tickers = {**market_tickers, "tickers": {}}
        if anchor.get("instrument_type") == "spot" and anchor.get("price") is not None:
            market_tickers["tickers"]["xauusd"] = {
                "price": anchor["price"], "source": "research_snapshot_spot",
                "price_time": anchor.get("price_time"), "trade_date": research.get("trade_date"),
                "instrument_kind": "spot", "snapshot_id": research.get("snapshot_id"),
            }
    tasks = list_recent_tasks(5)
    latest_reports = _select_latest_reports(all_reports)
    latest_supplemental_report = _select_latest_supplemental_report(all_reports)
    try:
        ds_sources = get_data_source_statuses().get("sources", [])
    except Exception as exc:
        logger.warning("Failed to load data source statuses for dashboard summary; falling back to empty list", exc_info=exc, extra={"service": "dashboard_summary", "stage": "data_source_statuses", "degraded": True})
        ds_sources = []

    has_options = options_snapshot is not None
    has_macro = macro is not None and len(macro.get("indicators", {})) > 0
    has_raw = has_options or has_macro
    has_final_report = any(r.get("type") == "final_report" for r in latest_reports) or any(
        r.get("available") for r in all_reports if r.get("type") == "final_report"
    )
    has_strategy = any(r.get("type") == "strategy_card" for r in latest_reports) or any(
        r.get("available") for r in all_reports if r.get("type") == "strategy_card"
    )
    composite_analysis = _build_composite_analysis_status(
        latest_reports=latest_reports,
        all_reports=all_reports,
        options_trade_date=options_snapshot.get("trade_date") if options_snapshot else None,
    )
    historical_strategy = _load_dashboard_strategy(composite_analysis)
    strategy = {} if research is not None else historical_strategy

    def step_state(is_done: bool, has_data: bool) -> str:
        if is_done:
            return "done"
        if has_data:
            return "running"
        return "pending"

    warnings: list[str] = []
    if research is not None and not research_available:
        warnings.append(
            "research: latest registered report has no complete narrative; no new direction is inferred"
            if research.get("reason") == "research_narrative_unavailable" else
            "research: latest registered research could not be verified; old macro is not substituted"
        )
    if not has_options:
        warnings.append("options: unavailable")
    elif str((options_snapshot.get("data_source") or {}).get("status") or "").upper().startswith("PRELIM"):
        warnings.append("options: PRELIM usable")
    if not has_macro:
        warnings.append("macro: unavailable")
    elif macro.get("unavailable_symbols", []):
        warnings.append(f"macro: partial ({len(macro.get('unavailable_symbols', []))} symbols unavailable)")
    if not has_final_report:
        warnings.append("final_report: not yet generated")
    if research_available:
        warnings.append(f"历史正式策略截至 {composite_analysis.get('trade_date') or '未建立'}；首页展示最新研究观察，不代表正式状态迁移。")
    else:
        warnings.extend(composite_analysis["warnings"])
    if not tasks:
        warnings.append("tasks: no recent task history")

    risk_alerts: list[str] = []
    if macro:
        for sym in macro.get("unavailable_symbols", []):
            if "REAL" in sym.upper() or "YIELD" in sym.upper():
                risk_alerts.append(f"Real yield data missing ({sym})")
                break
    for err_src in [s for s in ds_sources
                    if s.get("status") not in {"ok", "ready", "disabled"} and s.get("source_key")][:3]:
        risk_alerts.append(f"Data source {err_src['source_key']}: {err_src.get('status', 'error')}")

    ds_summary = {
        s.get("source_key", "unknown"): {
            "name": s.get("source_name", s.get("source_key", "unknown")),
            "status": s.get("status", "unknown"),
            "configured": s.get("configured", False),
            "analysis_ready": s.get("analysis_ready", False),
        }
        for s in ds_sources
    }

    # Build source_trace from data source statuses
    source_trace = [
        {
            "name": s.get("source_name", s.get("source_key", "unknown")),
            "trade_date": s.get("latest_date", ""),
            "file": s.get("source_url", ""),
            "snapshot_id": s.get("snapshot_id"),
            "source_ref": s.get("source_key", ""),
            "status": s.get("status", "unavailable"),
        }
        for s in ds_sources
    ]

    agent_summary = ({} if research is not None else
                     _gate_agent_summary(build_dashboard_agent_summary(), composite_analysis))
    gold_macro_overview = None if research is not None else _load_gold_macro_overview()
    latest_jin10_analysis = None if research is not None else _load_latest_jin10_analysis()
    integrated_macro = build_dashboard_integrated_analysis(
        macro_snapshot=macro,
        options_snapshot=options_snapshot,
        market_tickers=market_tickers,
        gold_macro_overview=gold_macro_overview,
        agent_summary=agent_summary,
        composite_analysis=({"status": "observation_only", "trade_date": research.get("trade_date"),
                             "run_id": research.get("run_id")} if research_available else composite_analysis),
        source_trace=source_trace,
        jin10_analysis=latest_jin10_analysis,
        strategy_summary=strategy,
    )
    if research_available and integrated_macro:
        state = research.get("state") or {}
        integrated_macro.update({
            "report_type": "research_observation_summary", "source": "registered_research_snapshot",
            "research_identity": research.get("research_identity"),
            "trade_date": research["trade_date"], "run_id": research["run_id"],
            "as_of": research.get("as_of"),
            "overall_bias": "研究观察（未确认正式迁移）", "direction": research["bias"],
            "macro_regime": "研究观察 · 正式状态未迁移",
            "confidence": research["confidence"],
            "reasoning": research['summary'],
            "trade_implication": (research.get("execution") or {}).get("flat") or "本次仅作研究观察。",
            "trigger_upgrade": [], "trigger_downgrade": [],
            "invalidation": research["invalid_conditions"], "risks": research["risks"],
            "accepted_state": state.get("accepted_state"), "candidate_state": state.get("candidate_state"),
            "transition_status": state.get("transition_status"), "authority": "observation_only",
            "publish_allowed": False,
            "source_refs": [{"name": "最新研究快照", "snapshot_id": research["snapshot_id"],
                             "source_ref": research["report_id"], "trade_date": research["trade_date"]}],
        })
        if research.get("final_trade_plan") is not None:
            integrated_macro["final_trade_plan"] = research["final_trade_plan"]
    elif research is not None:
        narrative_missing = research.get("reason") == "research_narrative_unavailable"
        integrated_macro = {
            "report_type": "research_observation_summary", "source": "unavailable",
            "overall_bias": "本次完整分析尚未生成" if narrative_missing else "最新研究校验未通过",
            "direction": "neutral", "confidence": None,
            "reasoning": (
                "最新报告与快照已核验，但尚无完整研究正文；当前仅展示已采集数据，不给出新的方向判断。"
                if narrative_missing else
                "最新研究产物或快照无法核验，暂停展示其结论，不使用旧宏观数据替代。"
            ),
            "macro_regime": "研究正文待生成" if narrative_missing else "研究数据待核验",
            "trade_implication": "等待完整研究分析。" if narrative_missing else "等待研究证据恢复。",
            "trade_date": research.get("trade_date"), "run_id": research.get("run_id"),
            "as_of": research.get("as_of"),
            "source_refs": [{"name": "最新研究报告", "snapshot_id": research.get("snapshot_id"),
                             "source_ref": research["report_id"], "trade_date": research.get("trade_date")}]
                           if research.get("report_id") else [],
            "authority": "observation_only", "publish_allowed": False,
        }
        agent_summary = {}
    dashboard_gold_macro_overview = _dashboard_gold_macro_overview(gold_macro_overview)

    return {
        "current_market": _get_dashboard_current_market(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "realtime_status": {
            "source": "research_snapshot" if research_available else "unavailable" if research is not None else "jin10_mcp" if "jin10_mcp" in market_tickers.get("sources", []) else "degraded",
            "generated_at": research.get("as_of") if research_available else market_tickers.get("generated_at"),
            "available_symbols": [] if research_available else sorted((market_tickers.get("tickers") or {}).keys()),
            "message": "研究快照报价，非当前实时报价" if research_available else "",
        },
        "realtime_quotes": market_tickers.get("tickers", {}),
        "options": (None if not options_snapshot else {
            **(_dashboard_options_summary(options_snapshot) or {}),
            **({"run_id": research.get("run_id"), "snapshot_id": research.get("snapshot_id"),
                "source": "registered_research_snapshot", "facts_status": "available",
                "source_refs": options_snapshot.get("source_refs") or research.get("source_refs", [])}
               if facts_available else {}),
        }),
        "macro": None if not macro else {
            "as_of": macro.get("as_of"),
            "snapshot_id": research.get("snapshot_id") if facts_available else None,
            "run_id": research.get("run_id") if facts_available else None,
            **({"trade_date": research.get("trade_date"), "source": "registered_research_snapshot",
                "facts_status": "available",
                "source_refs": macro.get("source_refs") or research.get("source_refs", [])}
               if facts_available else {}),
            "available_count": len(macro.get("indicators", {})),
            "unavailable_count": len(macro.get("unavailable_symbols", [])),
            "indicators": macro.get("indicators", {}),
        },
        "strategy": strategy,
        "pipeline": {
            "raw": step_state(has_raw, has_raw),
            "parsed": step_state(has_options, has_macro),
            "features": step_state(has_options, has_macro),
            "agent": step_state(has_strategy, has_options or has_macro),
            "report": step_state(has_final_report, has_strategy),
            "knowledge": "pending",
        },
        "module_status": {
            "options": "available" if has_options else "unavailable",
            "macro": "partial" if has_macro and macro and macro.get("unavailable_symbols") else ("available" if has_macro else "unavailable"),
            "reports": "available" if has_final_report else "unavailable",
            "strategy": composite_analysis["status"] if has_strategy else "unavailable",
            "events": "partial",
            "knowledge": "unavailable",
        },
        "data_quality": {
            "confirmed_data": sum(1 for s in ds_sources if s.get("status") == "ok"),
            "external_opinion": 0,
            "system_inference": 0,
            "total_sources": len(ds_sources),
        },
        "warnings": warnings,
        "risk_alerts": risk_alerts,
        "agent_summary": agent_summary,
        "integrated_macro": integrated_macro,
        "gold_macro_overview": dashboard_gold_macro_overview,
        "composite_analysis": composite_analysis,
        "research_context": {k: v for k, v in (research or {}).items()
                             if k in {"research_identity", "status", "facts_status", "source_refs", "authority", "publish_allowed", "report_id", "run_id", "snapshot_id", "as_of", "trade_date", "state", "reason"}},
        "historical_strategy": historical_strategy if research_available else None,
        "latest_supplemental_report": latest_supplemental_report,
        "latest_reports": latest_reports,
        "data_source_status": ds_summary,
        "recent_tasks": tasks,
        "source_trace": source_trace,
    }
