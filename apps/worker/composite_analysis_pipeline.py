from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.analysis.agents.cme_options import analyze_cme_options
from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity
from apps.analysis.agents.market_odds import analyze_market_odds
from apps.analysis.agents.news import analyze_news
from apps.analysis.agents.positioning import analyze_positioning
from apps.analysis.agents.quality_gate import evaluate_agent_quality_gate, execute_agent_loop_fallback_tasks
from apps.analysis.agents.quality_gate_evaluator import evaluate_quality_gate as _default_evaluate_quality_gate
from apps.analysis.agents.risk import analyze_risk
from apps.analysis.agents.technical import analyze_technical
from apps.analysis.strategy.card import build_strategy_card
from apps.gold_runtime_orchestration import build_gold_runtime_execution_summary
from apps.output.final_report import write_final_report, write_strategy_card
from apps.renderer.markdown.final_report import build_structured_report, render_final_report_markdown

logger = logging.getLogger(__name__)


def evaluate_quality_gate(**kwargs: Any) -> Any:
    from apps.worker import runner

    patched = getattr(runner, "evaluate_quality_gate", None)
    if patched is not None and patched is not evaluate_quality_gate:
        return patched(**kwargs)
    return _default_evaluate_quality_gate(**kwargs)


def run_composite_analysis_pipeline(
    *,
    storage_root: Path,
    snapshot: dict[str, Any],
    run_id: str,
    created_at: datetime | None = None,
    macro_output_prebuilt: Any = None,
    options_output_prebuilt: Any = None,
    risk_output_prebuilt: Any = None,
    technical_output_prebuilt: Any = None,
    positioning_output_prebuilt: Any = None,
    news_output_prebuilt: Any = None,
    coordinator_output_prebuilt: Any = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Run the composite analysis pipeline on an already-persisted analysis snapshot."""

    created_at = created_at or datetime.now(timezone.utc)
    summaries: dict[str, dict[str, Any]] = {}
    trade_date = snapshot.get("trade_date", "")
    snapshot_id = snapshot.get("snapshot_id", "unknown")

    macro_output = analyze_macro_liquidity(snapshot, created_at=created_at)
    options_output = analyze_cme_options(snapshot, created_at=created_at)
    risk_output = analyze_risk(
        snapshot,
        macro_output=macro_output,
        options_output=options_output,
        created_at=created_at,
    )
    technical_output = analyze_technical(snapshot, created_at=created_at)
    positioning_output = analyze_positioning(snapshot, created_at=created_at)
    news_output = analyze_news(snapshot, created_at=created_at)
    market_odds_output = analyze_market_odds(snapshot, created_at=created_at)
    from apps.analysis.agents.coordinator import coordinate_agent_outputs

    coordinator_output = coordinate_agent_outputs(
        snapshot,
        macro_output=macro_output,
        options_output=options_output,
        risk_output=risk_output,
        technical_output=technical_output,
        positioning_output=positioning_output,
        news_output=news_output,
        market_odds_output=market_odds_output,
        created_at=created_at,
    )
    agent_outputs = [
        macro_output,
        options_output,
        risk_output,
        technical_output,
        positioning_output,
        news_output,
        market_odds_output,
        coordinator_output,
    ]
    quality_gate_decision = evaluate_quality_gate(
        agent_outputs=agent_outputs,
        gold_macro_overview=gold_macro_overview_from_snapshot(snapshot),
        source_health=source_health_from_snapshot(snapshot),
    )
    fallback_execution = execute_agent_loop_fallback_tasks(
        agent_outputs=agent_outputs,
        primary_quality_gate_decision=quality_gate_decision,
        snapshot=snapshot,
        gold_macro_overview=gold_macro_overview_from_snapshot(snapshot),
        source_health=source_health_from_snapshot(snapshot),
        created_at=created_at,
    )
    accepted_coordinator = accepted_coordinator_output(
        primary=coordinator_output,
        fallback_execution=fallback_execution,
    )

    summaries["domain_agents"] = {
        "step": "domain_agents",
        "status": "success",
        "macro_status": macro_output.status.value,
        "options_status": options_output.status.value,
        "risk_status": risk_output.status.value,
        "technical_status": technical_output.status.value,
        "positioning_status": positioning_output.status.value,
        "news_status": news_output.status.value,
        "market_odds_status": market_odds_output.status.value,
        "coordinator_status": coordinator_output.status.value,
    }

    markdown = render_final_report_markdown(
        snapshot=snapshot,
        macro_output=macro_output,
        options_output=options_output,
        risk_output=risk_output,
        technical_output=technical_output,
        positioning_output=positioning_output,
        news_output=news_output,
        coordinator_output=accepted_coordinator,
        created_at=created_at,
    )

    try:
        structured = build_structured_report(
            snapshot=snapshot,
            macro_output=macro_output,
            options_output=options_output,
            risk_output=risk_output,
            technical_output=technical_output,
            positioning_output=positioning_output,
            news_output=news_output,
            coordinator_output=accepted_coordinator,
            created_at=created_at,
        )
        structured_dict = structured.model_dump(mode="json")
    except Exception:
        logger.exception("Failed to build structured report - writing Markdown only")
        structured_dict = None

    report_result = write_final_report(
        storage_root=storage_root,
        markdown=markdown,
        asset="XAUUSD",
        trade_date=str(trade_date),
        run_id=run_id,
        structured_report=structured_dict,
    )
    card = build_strategy_card(
        snapshot=snapshot,
        coordinator_output=accepted_coordinator,
        risk_output=risk_output,
        created_at=created_at,
    )
    card_result = write_strategy_card(
        storage_root=storage_root,
        card=card,
    )
    summaries["strategy_card"] = {
        "step": "strategy_card",
        "status": "success",
        "snapshot_id": str(snapshot_id),
        "input_snapshot_ids": dict(card.input_snapshot_ids),
        "paths": card_result.get("paths", []),
    }
    fallback_outputs = (
        {
            "analysis_snapshot": snapshot_id,
            "final_report_paths": report_result.get("paths", []),
            "strategy_card_paths": card_result.get("paths", []),
        }
        if fallback_execution.attempted
        else None
    )
    agent_loop_decision = evaluate_agent_quality_gate(
        agent_outputs=agent_outputs,
        gold_macro_overview=gold_macro_overview_from_snapshot(snapshot),
        source_health=source_health_from_snapshot(snapshot),
        primary_quality_gate_decision=quality_gate_decision,
        fallback_outputs=fallback_outputs,
        fallback_quality_gate_decision=fallback_execution.fallback_quality_gate_decision,
    )
    summaries["final_report"] = {
        "step": "final_report",
        "status": "success",
        "snapshot_id": str(snapshot_id),
        "paths": report_result.get("paths", []),
        "quality_gate_action": quality_gate_decision.action.value,
        "review_status": quality_gate_decision.review_status,
        "publish_allowed": quality_gate_decision.publish_allowed,
        "manual_review_required": quality_gate_decision.manual_review_required,
        "fallback_recommended": quality_gate_decision.fallback_recommended,
        "retry_recommended": quality_gate_decision.retry_recommended,
        "quality_gate_decision": quality_gate_decision.model_dump(mode="json"),
        "fallback_task_results": [dict(item) for item in fallback_execution.task_results],
        "agent_loop_decision": agent_loop_decision.model_dump(mode="json"),
    }
    gold_runtime_summary = build_gold_runtime_execution_summary(
        run_mode="premarket_full_run",
        trigger_reason="worker_premarket_task",
        quality_gate_decision=quality_gate_decision,
        agent_loop_decision=agent_loop_decision,
        accepted_outputs={
            "analysis_snapshot": snapshot_id,
            "final_report_paths": report_result.get("paths", []),
            "strategy_card_paths": card_result.get("paths", []),
        },
    )
    summaries["gold_runtime_summary"] = {
        "step": "gold_runtime_summary",
        "status": "success",
        **gold_runtime_summary,
    }

    composite_outputs: dict[str, Any] = {
        "agents": {
            "macro_liquidity_agent": macro_output,
            "cme_options_agent": options_output,
            "risk_agent": risk_output,
            "technical_agent": technical_output,
            "positioning_agent": positioning_output,
            "news_agent": news_output,
            "market_odds_agent": market_odds_output,
            "coordinator_agent": coordinator_output,
            **fallback_execution.fallback_agent_outputs,
        },
        "strategy_card": card,
        "report_result": report_result,
        "card_result": card_result,
        "quality_gate_decision": quality_gate_decision,
        "agent_loop_decision": agent_loop_decision,
        "gold_runtime_summary": gold_runtime_summary,
    }

    return summaries, composite_outputs


def accepted_coordinator_output(*, primary: Any, fallback_execution: Any) -> Any:
    fallback = getattr(fallback_execution, "fallback_agent_outputs", {}).get("fallback_synthesis_agent")
    return fallback or primary


def gold_macro_overview_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    news_data = snapshot.get("news", {}).get("data") if isinstance(snapshot.get("news"), dict) else None
    if isinstance(news_data, dict) and isinstance(news_data.get("gold_macro_overview"), dict):
        return dict(news_data["gold_macro_overview"])
    return {"source_refs": snapshot.get("source_refs") or []}


def source_health_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    news_data = snapshot.get("news", {}).get("data") if isinstance(snapshot.get("news"), dict) else None
    if isinstance(news_data, dict):
        overview = news_data.get("gold_macro_overview")
        if isinstance(overview, dict) and isinstance(overview.get("source_health"), dict):
            return dict(overview["source_health"])
        if isinstance(news_data.get("source_health"), dict):
            return dict(news_data["source_health"])
    return {"overall_status": "unknown", "can_build_gold_macro_overview": True, "p0_missing": []}
