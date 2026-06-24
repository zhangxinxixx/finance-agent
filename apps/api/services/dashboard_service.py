from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timezone
from typing import Any

from apps.api.services.agent_read_model import build_dashboard_agent_summary
from apps.api.services.macro_service import get_macro_latest
from apps.api.services.market_service import get_market_tickers
from apps.api.services.options_service import get_options_snapshot
from apps.api.services.report_service import list_reports_index
from apps.api.services.source_service import get_data_source_statuses
from apps.api.services.task_service import list_recent_tasks


logger = logging.getLogger(__name__)


def _safe_trade_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _options_confidence(
    *,
    trade_date: str | None,
    data_status: str | None,
    intent_score: float | None,
) -> dict[str, Any]:
    base = float(intent_score or 0.0)
    parsed_trade_date = _safe_trade_date(trade_date)
    age_days: int | None = None
    score = base

    if parsed_trade_date is not None:
        age_days = (datetime.now(UTC).date() - parsed_trade_date).days
        if age_days >= 1:
            score -= min(age_days * 0.08, 0.32)

    if str(data_status or "").upper() == "PRELIM":
        score -= 0.12

    score = max(0.0, min(score, 1.0))
    if score >= 0.7:
        level = "high"
    elif score >= 0.45:
        level = "medium"
    else:
        level = "low"

    reasons: list[str] = []
    if str(data_status or "").upper() == "PRELIM":
        reasons.append("PRELIM")
    if age_days is not None and age_days >= 1:
        reasons.append(f"stale_{age_days}d")

    return {
        "score": score,
        "level": level,
        "trade_date": trade_date,
        "age_days": age_days,
        "data_status": data_status or "UNAVAILABLE",
        "reasons": reasons,
    }


def _select_latest_reports(reports: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    def _sort_key(report: dict[str, Any]) -> tuple[date, str, str]:
        trade_date = _safe_trade_date(str(report.get("trade_date") or ""))
        return (
            trade_date or date.min,
            str(report.get("run_id") or ""),
            str(report.get("report_id") or ""),
        )

    available_reports = []
    for report in reports:
        if not report.get("available"):
            continue
        item = dict(report)
        item.setdefault("status", "ready")
        available_reports.append(item)
    return sorted(available_reports, key=_sort_key, reverse=True)[:limit]


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
    strategy_dates = [
        _safe_trade_date(str(report.get("trade_date") or ""))
        for report in all_reports
        if report.get("available") and report.get("type") == "strategy_card"
    ]
    final_dates = [
        _safe_trade_date(str(report.get("trade_date") or ""))
        for report in all_reports
        if report.get("available") and report.get("type") == "final_report"
    ]
    strategy_dates = [item for item in strategy_dates if item is not None]
    final_dates = [item for item in final_dates if item is not None]
    strategy_date = max(strategy_dates).isoformat() if strategy_dates else None
    final_report_date = max(final_dates).isoformat() if final_dates else None
    composite_date = strategy_date or final_report_date

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
        "strategy_trade_date": strategy_date,
        "final_report_trade_date": final_report_date,
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


def _gate_agent_summary(agent_summary: dict[str, Any], composite_analysis: dict[str, Any]) -> dict[str, Any]:
    synthesis = agent_summary.get("synthesis")
    if not isinstance(synthesis, dict):
        return agent_summary

    degraded_run_ids = {
        str(report.get("run_id"))
        for report in composite_analysis.get("degraded_newer_reports", [])
        if report.get("run_id")
    }
    if str(synthesis.get("run_id") or "") not in degraded_run_ids:
        return agent_summary

    gated = dict(agent_summary)
    gated["synthesis"] = None
    gated["synthesis_gate"] = {
        "status": "degraded",
        "reason": "latest synthesis_agent output is tied to a degraded Jin10 report",
        "run_id": synthesis.get("run_id"),
        "snapshot_id": synthesis.get("snapshot_id"),
    }
    return gated


def get_dashboard_summary() -> dict[str, Any]:
    options_snapshot = get_options_snapshot()
    market_tickers = get_market_tickers()
    walls_summary = None
    if options_snapshot:
        sr = options_snapshot.get("support_resistance", {})
        walls_summary = {
            "resistance": [{"strike": w["strike"], "score": w.get("wall_score", 0), "distance_pct": w.get("distance_pct")} for w in sr.get("resistance", [])[:3]],
            "support": [{"strike": w["strike"], "score": w.get("wall_score", 0), "distance_pct": w.get("distance_pct")} for w in sr.get("support", [])[:3]],
        }

    macro = get_macro_latest()
    tasks = list_recent_tasks(5)
    reports_index = list_reports_index()
    all_reports = reports_index.get("reports", [])
    latest_reports = _select_latest_reports(all_reports)
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

    def step_state(is_done: bool, has_data: bool) -> str:
        if is_done:
            return "done"
        if has_data:
            return "running"
        return "pending"

    warnings: list[str] = []
    if not has_options:
        warnings.append("options: unavailable")
    elif (options_snapshot.get("data_source") or {}).get("status") == "PRELIM":
        warnings.append("options: PRELIM only (FINAL unavailable)")
    if not has_macro:
        warnings.append("macro: unavailable")
    elif macro.get("unavailable_symbols", []):
        warnings.append(f"macro: partial ({len(macro.get('unavailable_symbols', []))} symbols unavailable)")
    if not has_final_report:
        warnings.append("final_report: not yet generated")
    warnings.extend(composite_analysis["warnings"])
    if not tasks:
        warnings.append("tasks: no recent task history")

    risk_alerts: list[str] = []
    if options_snapshot and (options_snapshot.get("data_source") or {}).get("status") == "PRELIM":
        risk_alerts.append("CME data source: PRELIM (FINAL preferred)")
    if macro:
        for sym in macro.get("unavailable_symbols", []):
            if "REAL" in sym.upper() or "YIELD" in sym.upper():
                risk_alerts.append(f"Real yield data missing ({sym})")
                break
    for err_src in [s for s in ds_sources if s.get("status") != "ok" and s.get("source_key")][:3]:
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

    agent_summary = _gate_agent_summary(build_dashboard_agent_summary(), composite_analysis)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "realtime_status": {
            "source": "jin10_mcp" if "jin10_mcp" in market_tickers.get("sources", []) else "degraded",
            "generated_at": market_tickers.get("generated_at"),
            "available_symbols": sorted((market_tickers.get("tickers") or {}).keys()),
        },
        "realtime_quotes": market_tickers.get("tickers", {}),
        "options": None if not options_snapshot else {
            "trade_date": options_snapshot.get("trade_date"),
            "product": (options_snapshot.get("data_source") or {}).get("product"),
            "expiries": (options_snapshot.get("data_source") or {}).get("expiries", []),
            "intent": (options_snapshot.get("intent") or {}).get("type"),
            "intent_score": (options_snapshot.get("intent") or {}).get("score"),
            "gamma_zero": ((options_snapshot.get("gex") or {}).get("netgex_aggregate") or {}).get("gamma_zero", {}).get("price"),
            "forward_price": (options_snapshot.get("parameters") or {}).get("f_value"),
            "walls": walls_summary,
            "data_status": (options_snapshot.get("data_source") or {}).get("status", "UNAVAILABLE"),
            "confidence": _options_confidence(
                trade_date=options_snapshot.get("trade_date"),
                data_status=(options_snapshot.get("data_source") or {}).get("status", "UNAVAILABLE"),
                intent_score=(options_snapshot.get("intent") or {}).get("score"),
            ),
        },
        "macro": None if not macro else {
            "as_of": macro.get("as_of"),
            "available_count": len(macro.get("indicators", {})),
            "unavailable_count": len(macro.get("unavailable_symbols", [])),
            "indicators": macro.get("indicators", {}),
        },
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
        "composite_analysis": composite_analysis,
        "latest_reports": latest_reports,
        "data_source_status": ds_summary,
        "recent_tasks": tasks,
        "source_trace": source_trace,
    }
