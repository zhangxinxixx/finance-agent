from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.analysis.agents.cme_options import analyze_cme_options
from apps.analysis.agents.fact_review import build_runtime_fact_review_agent_output
from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity
from apps.analysis.agents.market_odds import analyze_market_odds
from apps.analysis.agents.news import analyze_news
from apps.analysis.agents.positioning import analyze_positioning
from apps.analysis.agents.quality_gate import (
    AcceptedOutputArtifactRef,
    evaluate_agent_quality_gate,
    execute_agent_loop_fallback_tasks,
    execute_conservative_synthesis_fallback,
)
from apps.analysis.agents.quality_gate_evaluator import (
    evaluate_quality_gate as _default_evaluate_quality_gate,
    preserve_unresolved_pre_gate,
)
from apps.analysis.agents.gold_runtime_agents import materialize_report_render_agent_artifact
from apps.analysis.agents.gold_artifacts import write_canonical_gold_json
from apps.analysis.agents.schemas import AgentBias
from apps.analysis.agents.source_health import (
    build_gold_v3_source_health,
    source_statuses_from_analysis_snapshot,
)
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
    gold_macro_overview = gold_macro_overview_from_snapshot(snapshot)
    source_health = source_health_from_snapshot(snapshot, gold_macro_overview=gold_macro_overview)
    canonical_run_dir = storage_root / "analysis" / "gold_mainlines" / str(trade_date) / run_id
    canonical_source_health_path = canonical_run_dir / "source_health.json"
    write_canonical_gold_json(
        canonical_source_health_path,
        source_health,
        storage_root=storage_root,
    )

    macro_output = (
        macro_output_prebuilt
        if macro_output_prebuilt is not None
        else analyze_macro_liquidity(snapshot, created_at=created_at)
    )
    options_output = (
        options_output_prebuilt
        if options_output_prebuilt is not None
        else analyze_cme_options(snapshot, created_at=created_at)
    )
    risk_output = (
        risk_output_prebuilt
        if risk_output_prebuilt is not None
        else analyze_risk(
            snapshot,
            macro_output=macro_output,
            options_output=options_output,
            created_at=created_at,
        )
    )
    technical_output = (
        technical_output_prebuilt
        if technical_output_prebuilt is not None
        else analyze_technical(snapshot, created_at=created_at)
    )
    positioning_output = (
        positioning_output_prebuilt
        if positioning_output_prebuilt is not None
        else analyze_positioning(snapshot, created_at=created_at)
    )
    news_output = (
        news_output_prebuilt if news_output_prebuilt is not None else analyze_news(snapshot, created_at=created_at)
    )
    market_odds_output = analyze_market_odds(snapshot, created_at=created_at)
    domain_outputs = [
        macro_output,
        options_output,
        risk_output,
        technical_output,
        positioning_output,
        news_output,
        market_odds_output,
    ]
    fact_review_output = build_runtime_fact_review_agent_output(
        domain_outputs,
        snapshot_id=str(snapshot_id),
        created_at=created_at,
    )
    reviewed_outputs = [*domain_outputs, fact_review_output]
    pre_coordinator_quality_gate_decision = evaluate_quality_gate(
        agent_outputs=reviewed_outputs,
        gold_macro_overview=gold_macro_overview,
        source_health=source_health,
    )
    domain_fallback_execution = execute_agent_loop_fallback_tasks(
        agent_outputs=reviewed_outputs,
        primary_quality_gate_decision=pre_coordinator_quality_gate_decision,
        snapshot=snapshot,
        gold_macro_overview=gold_macro_overview,
        source_health=source_health,
        created_at=created_at,
    )
    from apps.analysis.agents.coordinator import coordinate_agent_outputs

    coordinator_output = (
        coordinator_output_prebuilt
        if coordinator_output_prebuilt is not None
        else coordinate_agent_outputs(
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
    )
    post_coordinator_gate_inputs = [*reviewed_outputs, coordinator_output]
    raw_post_coordinator_quality_gate_decision = evaluate_quality_gate(
        agent_outputs=post_coordinator_gate_inputs,
        gold_macro_overview=gold_macro_overview,
        source_health=source_health,
    )
    post_coordinator_quality_gate_decision = preserve_unresolved_pre_gate(
        pre_coordinator_decision=pre_coordinator_quality_gate_decision,
        post_coordinator_decision=raw_post_coordinator_quality_gate_decision,
    )
    fallback_execution = execute_conservative_synthesis_fallback(
        primary_output=coordinator_output,
        primary_quality_gate_decision=post_coordinator_quality_gate_decision,
        prior_execution=domain_fallback_execution,
        gold_macro_overview=gold_macro_overview,
        source_health=source_health,
        created_at=created_at,
    )
    agent_loop_decision = evaluate_agent_quality_gate(
        agent_outputs=post_coordinator_gate_inputs,
        gold_macro_overview=gold_macro_overview,
        source_health=source_health,
        primary_quality_gate_decision=post_coordinator_quality_gate_decision,
        primary_output=coordinator_output,
        fallback_quality_gate_decision=fallback_execution.fallback_quality_gate_decision,
        corrective_fallback_succeeded=fallback_execution.corrective_fallback_succeeded,
        unresolved_reason_codes=fallback_execution.unresolved_reason_codes,
    )
    canonical_quality_gate_path = canonical_run_dir / "quality_gate_result.json"
    write_canonical_gold_json(
        canonical_quality_gate_path,
        {
            "schema_version": "canonical-analysis-quality-gate-v1",
            "trade_date": str(trade_date),
            "run_id": run_id,
            "snapshot_id": str(snapshot_id),
            "publish_allowed": agent_loop_decision.publish_allowed,
            "quality_gate_decision": post_coordinator_quality_gate_decision.model_dump(mode="json"),
            "agent_loop_decision": agent_loop_decision.model_dump(mode="json"),
        },
        storage_root=storage_root,
    )
    selected_coordinator = report_coordinator_output(
        primary=coordinator_output,
        fallback_execution=fallback_execution,
        agent_loop_decision=agent_loop_decision,
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
        "fact_review_status": fact_review_output.input_payload["fact_review_status"],
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
        coordinator_output=selected_coordinator,
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
            coordinator_output=selected_coordinator,
            created_at=created_at,
        )
        structured_dict = structured.model_dump(mode="json")
    except Exception:
        logger.exception("Failed to build structured report - writing Markdown only")
        structured_dict = None

    output_mode = "accepted" if agent_loop_decision.publish_allowed else "observe"
    report_artifact_type = "final_report" if agent_loop_decision.publish_allowed else "observation_report"
    strategy_artifact_type = (
        "strategy_card" if agent_loop_decision.publish_allowed else "observation_strategy_card"
    )
    report_result = write_final_report(
        storage_root=storage_root,
        markdown=markdown,
        asset="XAUUSD",
        trade_date=str(trade_date),
        run_id=run_id,
        structured_report=structured_dict,
        artifact_type=report_artifact_type,
    )
    card = build_strategy_card(
        snapshot=snapshot,
        coordinator_output=selected_coordinator,
        risk_output=risk_output,
        created_at=created_at,
    )
    if agent_loop_decision.no_strong_conclusion:
        card = observe_strategy_card(card, reason=agent_loop_decision.strategy_card_override.get("reason"))
    card_result = write_strategy_card(
        storage_root=storage_root,
        card=card,
        artifact_type=strategy_artifact_type,
    )
    summaries["strategy_card"] = {
        "step": "strategy_card",
        "status": "success",
        "snapshot_id": str(snapshot_id),
        "input_snapshot_ids": dict(card.input_snapshot_ids),
        "paths": card_result.get("paths", []),
    }
    rendered_outputs = validated_rendered_outputs(
        storage_root=storage_root,
        snapshot_id=str(snapshot_id),
        report_result=report_result,
        card_result=card_result,
        publish_allowed=agent_loop_decision.publish_allowed,
    )
    if agent_loop_decision.accepted_output.source != "none":
        agent_loop_decision = agent_loop_decision.model_copy(
            update={
                "accepted_output": agent_loop_decision.accepted_output.model_copy(
                    update={"artifact_ref": AcceptedOutputArtifactRef.model_validate(rendered_outputs)}
                )
            }
        )
    report_agent_result = materialize_report_render_agent_artifact(
        storage_root=storage_root,
        trade_date=str(trade_date),
        run_id=run_id,
        snapshot_id=str(snapshot_id),
        created_at=created_at,
        input_snapshot_ids=dict(card.input_snapshot_ids),
        source_refs=[dict(item) for item in card.source_refs],
        report_paths=list(report_result.get("paths", [])),
        strategy_card_paths=list(card_result.get("paths", [])),
        report_artifact_type=report_artifact_type,
        strategy_artifact_type=strategy_artifact_type,
    )
    accepted_outputs = agent_loop_decision.accepted_outputs
    observe_outputs = rendered_outputs if not agent_loop_decision.publish_allowed else {}
    prior_declared_agents, prior_stage_envelopes, prior_agent_refs = validated_gold_agent_execution(
        snapshot=snapshot,
        storage_root=storage_root,
    )
    executed_agents = ["report_render_agent"]
    declared_agents = [*prior_declared_agents, "report_render_agent"]
    materialized_stage_envelopes = [*prior_stage_envelopes, "report_render_agent"]
    agent_artifact_refs = {
        **prior_agent_refs,
        "report_render_agent": str(report_agent_result.storage_relative_path),
    }
    summaries["final_report"] = {
        "step": "final_report",
        "status": "success",
        "snapshot_id": str(snapshot_id),
        "paths": report_result.get("paths", []),
        "quality_gate_action": post_coordinator_quality_gate_decision.action.value,
        "review_status": post_coordinator_quality_gate_decision.review_status,
        "publish_allowed": agent_loop_decision.publish_allowed,
        "manual_review_required": post_coordinator_quality_gate_decision.manual_review_required,
        "fallback_recommended": post_coordinator_quality_gate_decision.fallback_recommended,
        "retry_recommended": post_coordinator_quality_gate_decision.retry_recommended,
        "pre_coordinator_quality_gate_decision": pre_coordinator_quality_gate_decision.model_dump(mode="json"),
        "post_coordinator_quality_gate_decision": post_coordinator_quality_gate_decision.model_dump(mode="json"),
        "quality_gate_decision": post_coordinator_quality_gate_decision.model_dump(mode="json"),
        "fallback_task_results": [dict(item) for item in fallback_execution.task_results],
        "agent_loop_decision": agent_loop_decision.model_dump(mode="json"),
        "output_mode": output_mode,
        "report_render_agent_path": report_agent_result.storage_relative_path,
        "source_health_path": canonical_source_health_path.relative_to(storage_root).as_posix(),
        "quality_gate_result_path": canonical_quality_gate_path.relative_to(storage_root).as_posix(),
    }
    gold_runtime_summary = build_gold_runtime_execution_summary(
        run_mode="premarket_full_run",
        trigger_reason="worker_premarket_task",
        quality_gate_decision=post_coordinator_quality_gate_decision,
        agent_loop_decision=agent_loop_decision,
        accepted_outputs=accepted_outputs,
        executed_agents=executed_agents,
        declared_agents=declared_agents,
        materialized_stage_envelopes=materialized_stage_envelopes,
        agent_artifact_refs=agent_artifact_refs,
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
            "fact_review_agent": fact_review_output,
            "coordinator_agent": coordinator_output,
            **fallback_execution.fallback_agent_outputs,
        },
        "strategy_card": card,
        "report_result": report_result,
        "card_result": card_result,
        "pre_coordinator_quality_gate_decision": pre_coordinator_quality_gate_decision,
        "post_coordinator_quality_gate_decision": post_coordinator_quality_gate_decision,
        "quality_gate_decision": post_coordinator_quality_gate_decision,
        "agent_loop_decision": agent_loop_decision,
        "gold_runtime_summary": gold_runtime_summary,
        "observe_outputs": observe_outputs,
        "report_render_agent_result": report_agent_result,
        "source_health": source_health,
        "source_health_path": canonical_source_health_path,
        "quality_gate_result_path": canonical_quality_gate_path,
    }

    return summaries, composite_outputs


def report_coordinator_output(
    *, primary: Any, fallback_execution: Any, agent_loop_decision: Any
) -> Any:
    accepted = agent_loop_decision.accepted_output
    if accepted.source == "primary":
        if primary.agent_name != accepted.agent_name or primary.snapshot_id != accepted.snapshot_id:
            raise ValueError("accepted primary reference does not match coordinator output")
        return primary
    if accepted.source == "corrective_fallback":
        candidate = getattr(fallback_execution, "fallback_agent_outputs", {}).get(accepted.agent_name)
        if candidate is None or candidate.snapshot_id != accepted.snapshot_id:
            raise ValueError("accepted corrective fallback reference does not match an output")
        return candidate
    candidate = getattr(fallback_execution, "fallback_agent_outputs", {}).get("fallback_synthesis_agent") or primary
    return candidate.model_copy(
        update={
            "bias": AgentBias.NEUTRAL,
            "confidence": min(candidate.confidence, 0.35),
            "summary": f"Observe and wait. No strong conclusion. {candidate.summary}",
            "watchlist": [*candidate.watchlist, "observe_wait: await validated source confirmation"],
            "invalid_conditions": [
                *candidate.invalid_conditions,
                "Any directional conclusion remains invalid until QualityGate passes.",
            ],
            "data_quality": [*candidate.data_quality, "no_strong_conclusion"],
        }
    )


def validated_rendered_outputs(
    *,
    storage_root: Path,
    snapshot_id: str,
    report_result: dict[str, Any],
    card_result: dict[str, Any],
    publish_allowed: bool,
) -> dict[str, Any]:
    """Return concrete renderer refs and fail closed for accepted publication.

    Writer summaries are not artifact evidence by themselves.  Accepted output
    authority requires both formal bundles to expose non-empty, existing files
    beneath their canonical storage directories.  Observation-only callers keep
    their existing best-effort behavior and can never populate accepted output.
    """
    rendered = {
        "analysis_snapshot": snapshot_id,
        "final_report_paths": _string_paths(report_result.get("paths")),
        "strategy_card_paths": _string_paths(card_result.get("paths")),
    }
    if not publish_allowed:
        return rendered

    expected = (
        ("final_report", report_result, rendered["final_report_paths"]),
        ("strategy_card", card_result, rendered["strategy_card_paths"]),
    )
    root = storage_root.resolve()
    for artifact_type, result, paths in expected:
        if result.get("artifact_type") != artifact_type:
            raise RuntimeError(
                f"accepted output materialization requires artifact_type={artifact_type}"
            )
        if not paths:
            raise RuntimeError(
                f"accepted output materialization produced no {artifact_type} paths"
            )
        canonical_root = (root / "outputs" / artifact_type).resolve()
        for raw_path in paths:
            path = Path(raw_path).resolve()
            if not path.is_relative_to(canonical_root):
                raise RuntimeError(
                    f"accepted {artifact_type} path is outside canonical storage: {raw_path}"
                )
            if not path.is_file() or path.stat().st_size <= 0:
                raise RuntimeError(
                    f"accepted {artifact_type} artifact is not materialized: {raw_path}"
                )
    return rendered


def _string_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(path) for path in value if isinstance(path, (str, Path)) and str(path)]


def accepted_coordinator_output(*, primary: Any, fallback_execution: Any) -> Any:
    """Deprecated runner compatibility alias; accepted selection requires a decision."""
    del fallback_execution
    return primary


def observe_strategy_card(card: Any, *, reason: Any) -> Any:
    reason_text = str(reason or "quality_gate_not_passed")
    return card.model_copy(
        update={
            "bias": AgentBias.NEUTRAL,
            "confidence": min(card.confidence, 0.35),
            "scenario_summary": (
                f"Observe and wait ({reason_text}). No strong conclusion is permitted until QualityGate passes."
            ),
            "trigger_conditions": [
                *card.trigger_conditions,
                "Resume directional assessment only after QualityGate passes with validated sources.",
            ],
            "invalid_conditions": [
                *card.invalid_conditions,
                "Directional assessment is invalid while publish_allowed is false.",
            ],
            "watchlist": [*card.watchlist, "observe_wait: monitor source recovery and gate status"],
            "data_quality": [*card.data_quality, "no_strong_conclusion", "observe_wait"],
        }
    )


def validated_gold_agent_execution(
    *,
    snapshot: dict[str, Any],
    storage_root: Path,
) -> tuple[list[str], list[str], dict[str, str]]:
    news = snapshot.get("news") if isinstance(snapshot.get("news"), dict) else {}
    data = news.get("data") if isinstance(news.get("data"), dict) else {}
    execution = data.get("gold_agent_execution") if isinstance(data.get("gold_agent_execution"), dict) else {}
    raw_declared = (
        execution.get("declared_agents")
        if isinstance(execution.get("declared_agents"), list)
        else []
    )
    raw_materialized = (
        execution.get("materialized_stage_envelopes")
        if isinstance(execution.get("materialized_stage_envelopes"), list)
        else execution.get("executed_agents")
        if isinstance(execution.get("executed_agents"), list)
        else []
    )
    raw_refs = execution.get("artifact_paths") if isinstance(execution.get("artifact_paths"), dict) else {}
    declared_agents = [str(item) for item in raw_declared or raw_materialized]
    materialized_stage_envelopes: list[str] = []
    refs: dict[str, str] = {}
    root = storage_root.resolve()
    for item in raw_materialized:
        agent_name = str(item)
        raw_path = raw_refs.get(agent_name)
        if not isinstance(raw_path, str) or not raw_path:
            continue
        path = (root / raw_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(envelope, dict) or envelope.get("agent_name") != agent_name:
            continue
        materialized_stage_envelopes.append(agent_name)
        refs[agent_name] = raw_path
    return (
        list(dict.fromkeys(declared_agents)),
        list(dict.fromkeys(materialized_stage_envelopes)),
        refs,
    )


def gold_macro_overview_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    news_data = snapshot.get("news", {}).get("data") if isinstance(snapshot.get("news"), dict) else None
    context_section = snapshot.get("gold_analysis_context")
    context_data = context_section.get("data") if isinstance(context_section, dict) and isinstance(context_section.get("data"), dict) else {}
    context_metadata = {
        "status": context_data.get("status") or (context_section or {}).get("status"),
        "baseline_kind": context_data.get("baseline_kind"),
        "freshness": context_data.get("freshness") or {},
        "input_snapshot_ids": context_data.get("input_snapshot_ids") or {},
    }
    if isinstance(news_data, dict) and isinstance(news_data.get("gold_macro_overview"), dict):
        overview = dict(news_data["gold_macro_overview"])
        overview["gold_analysis_context"] = context_metadata
        return overview
    return {"source_refs": snapshot.get("source_refs") or [], "gold_analysis_context": context_metadata}


def source_health_from_snapshot(
    snapshot: dict[str, Any],
    *,
    gold_macro_overview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_statuses = source_statuses_from_analysis_snapshot(snapshot)
    if source_statuses:
        return build_gold_v3_source_health(
            source_statuses,
            as_of=str(snapshot.get("snapshot_time") or "") or None,
            gold_macro_overview=gold_macro_overview or gold_macro_overview_from_snapshot(snapshot),
        ).to_dict()
    # Missing source-health evidence is a data-quality gap, never a permissive
    # default. The premarket readiness gate blocks before agents; this fallback
    # keeps direct/legacy composite callers fail-closed as well.
    return {
        "overall_status": "unknown",
        "can_build_gold_macro_overview": False,
        "p0_missing": ["source_health_missing"],
    }
