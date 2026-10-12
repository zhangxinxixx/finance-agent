from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

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
from apps.analysis.gold_policy.daily_close_delivery import build_gold_daily_close_delivery
from apps.analysis.strategy.card import build_strategy_card
from apps.gold_runtime_orchestration import build_gold_runtime_execution_summary
from apps.output.final_report import write_final_report, write_strategy_card
from apps.renderer.markdown.final_report import build_structured_report, render_final_report_markdown

logger = logging.getLogger(__name__)


def _build_gold_daily_close_summary(*, execution: Any, storage_root: Path) -> dict[str, Any]:
    result = execution.result
    delivery = build_gold_daily_close_delivery(execution.loop_input, result)
    return {
        "daily_close_result_id": result.result_id,
        "daily_close_action": result.canonical_action.value,
        "daily_close_strategy_status": delivery.strategy_diff.selected_status,
        "daily_close_candidate_strategy_status": delivery.strategy_diff.candidate_status,
        "daily_close_bundle_path": execution.write_result.bundle_path.relative_to(
            storage_root
        ).as_posix(),
        "daily_close_model_invocations": result.model_invocations,
    }


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
    gold_feature_snapshot_prebuilt: Any = None,
    previous_gold_feature_snapshot_prebuilt: Any = None,
    gold_daily_close_controls_prebuilt: Any = None,
    gold_policy_execution_mode: Literal["authoritative", "shadow"] = "shadow",
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Run the composite analysis pipeline on an already-persisted analysis snapshot."""

    if gold_policy_execution_mode not in {"authoritative", "shadow"}:
        raise ValueError("gold_policy_execution_mode must be authoritative or shadow")

    created_at = created_at or datetime.now(timezone.utc)
    summaries: dict[str, dict[str, Any]] = {}
    trade_date = snapshot.get("trade_date", "")
    snapshot_id = snapshot.get("snapshot_id", "unknown")
    from apps.analysis.snapshots.input_validation import prepare_analysis_inputs, research_report_rejection_reasons
    snapshot = prepare_analysis_inputs(snapshot, storage_root=storage_root)
    validation = snapshot["input_validation"]
    summaries["input_validation"] = {"step": "input_validation", "status": validation["status"],
                                     "snapshot_id": snapshot_id, "input_validation": validation}
    if validation["status"] != "legacy":
        # Only domain outputs tied to this exact validated input may be reused.
        def bound(output):
            return output if output is not None and (getattr(output, "input_payload", None) or {}).get("input_validation", {}).get("input_sha256") == validation["input_sha256"] else None
        macro_output_prebuilt = bound(macro_output_prebuilt)
        options_output_prebuilt = bound(options_output_prebuilt)
        risk_output_prebuilt = bound(risk_output_prebuilt)
        technical_output_prebuilt = bound(technical_output_prebuilt)
        positioning_output_prebuilt = bound(positioning_output_prebuilt)
        news_output_prebuilt = bound(news_output_prebuilt)
        coordinator_output_prebuilt = bound(coordinator_output_prebuilt)
    if not validation["can_analyze"]:
        return blocked_research_result(storage_root=storage_root, snapshot=snapshot, run_id=run_id,
            summaries=summaries, reasons=validation["reason_codes"])
    gold_macro_overview = gold_macro_overview_from_snapshot(snapshot)
    source_health = source_health_from_snapshot(snapshot, gold_macro_overview=gold_macro_overview)
    core_health = snapshot.get("gold_workflow", {}).get("core_source_health")
    if core_health:
        source_health["core_freshness_sla"] = core_health
        if not core_health.get("production_ready"):
            source_health["can_emit_strong_conclusion"] = False
    canonical_run_dir = storage_root / "analysis" / "gold_mainlines" / str(trade_date) / run_id
    canonical_source_health_path = canonical_run_dir / "source_health.json"
    if snapshot.get("daily_research"):
        # News builds a preliminary overview before macro/CME join. Archive
        # the integrated view under a distinct immutable name for this run.
        write_canonical_gold_json(canonical_run_dir / "integrated_gold_macro_overview.json", gold_macro_overview, storage_root=storage_root)
    write_canonical_gold_json(
        canonical_source_health_path,
        source_health,
        storage_root=storage_root,
    )

    gold_feature_snapshot = None
    previous_gold_feature_snapshot = None
    gold_analysis_decision = None
    gold_price_attribution = None
    gold_daily_close_execution = None
    gold_policy_artifact_paths: dict[str, str] = {}
    if gold_feature_snapshot_prebuilt is not None:
        # This seam deliberately accepts only an explicit, typed FeatureSnapshot
        # input.  It must never infer formal policy state from the free-text
        # analysis snapshot or from report output.
        from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot

        gold_feature_snapshot = build_feature_snapshot(gold_feature_snapshot_prebuilt)
        previous_gold_feature_snapshot = (
            build_feature_snapshot(previous_gold_feature_snapshot_prebuilt)
            if previous_gold_feature_snapshot_prebuilt is not None
            else None
        )

    if gold_daily_close_controls_prebuilt is not None:
        if gold_policy_execution_mode != "authoritative":
            raise ValueError("daily-close canonical execution requires authoritative mode")
        if gold_feature_snapshot is None:
            raise ValueError("daily-close canonical execution requires a typed FeatureSnapshot")
        from apps.analysis.gold_policy.daily_close_runtime import (
            GoldDailyCloseRuntimeControls,
            execute_gold_daily_close_runtime,
        )

        controls = GoldDailyCloseRuntimeControls.model_validate(gold_daily_close_controls_prebuilt)
        gold_daily_close_execution = execute_gold_daily_close_runtime(
            storage_root=storage_root,
            run_id=run_id,
            current_feature=gold_feature_snapshot,
            controls=controls,
            bootstrap_previous_feature=previous_gold_feature_snapshot,
        )
        gold_analysis_decision = gold_daily_close_execution.result.analysis_decision
        gold_price_attribution = gold_daily_close_execution.result.price_attribution
    elif gold_feature_snapshot is not None:
        from apps.analysis.gold_policy.analysis_policy import evaluate_gold_analysis_policy
        from apps.analysis.gold_policy.attribution_policy import attribute_gold_price

        gold_analysis_decision = evaluate_gold_analysis_policy(
            gold_feature_snapshot,
            previous_gold_feature_snapshot,
        )
        gold_price_attribution = attribute_gold_price(
            gold_feature_snapshot,
            previous_gold_feature_snapshot,
        )

    if gold_feature_snapshot is not None:
        feature_artifact_name = f"{gold_feature_snapshot.schema_version}.json"
        analysis_version = gold_analysis_decision.policy_version.rsplit(".", 1)[-1]
        attribution_version = gold_price_attribution.policy_version.rsplit(".", 1)[-1]
        if analysis_version not in {"v1", "v2"} or attribution_version not in {
            "v1",
            "v2",
        }:
            raise ValueError("unsupported Gold Policy output version")
        analysis_artifact_name = f"gold_analysis_decision.{analysis_version}.json"
        attribution_artifact_name = (
            f"gold_price_attribution.{attribution_version}.json"
        )
        for filename, payload in (
            (feature_artifact_name, gold_feature_snapshot.model_dump(mode="json")),
            (analysis_artifact_name, gold_analysis_decision.model_dump(mode="json")),
            (
                attribution_artifact_name,
                gold_price_attribution.model_dump(mode="json"),
            ),
        ):
            target_path = canonical_run_dir / filename
            write_canonical_gold_json(target_path, payload, storage_root=storage_root)
            gold_policy_artifact_paths[filename] = target_path.relative_to(storage_root).as_posix()

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
            # Shadow policy output is evidence-only.  It must not advance the
            # Coordinator's typed authority or alter legacy report gating.
            accepted_state_conclusion=(
                gold_analysis_decision
                if gold_policy_execution_mode == "authoritative"
                else None
            ),
            created_at=created_at,
        )
    )
    if snapshot.get("gold_workflow", {}).get("schema_version") == "gold_workflow.v2":
        from apps.analysis.agents.research_synthesis import enrich_research_coordinator

        if coordinator_output_prebuilt is None:
            coordinator_output = coordinator_output.model_copy(update={"input_payload": {
                **(coordinator_output.input_payload or {}), "input_validation": validation}})
        coordinator_output = enrich_research_coordinator(snapshot, coordinator_output)
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
    if gold_feature_snapshot is not None:
        summaries["gold_policy"] = {
            "step": "gold_policy",
            "status": "success",
            "quality_status": gold_analysis_decision.quality_status,
            "direction": gold_analysis_decision.direction,
            "attribution_status": gold_price_attribution.attribution_status,
            "execution_mode": gold_policy_execution_mode,
            "output_mode": "observe" if gold_policy_execution_mode == "shadow" else "authoritative",
            "feature_snapshot_path": gold_policy_artifact_paths[feature_artifact_name],
            "gold_analysis_decision_path": gold_policy_artifact_paths[
                analysis_artifact_name
            ],
            "gold_price_attribution_path": gold_policy_artifact_paths[
                attribution_artifact_name
            ],
        }
        if gold_daily_close_execution is not None:
            summaries["gold_policy"].update(
                _build_gold_daily_close_summary(
                    execution=gold_daily_close_execution,
                    storage_root=storage_root,
                )
            )

    from apps.analysis.agents.research_context import build_research_assessment

    research_assessment = dict((selected_coordinator.input_payload or {}).get("daily_research_assessment") or build_research_assessment(snapshot))
    if research_assessment:
        research_assessment["report_controls"] = {
            "source_health": {key: source_health.get(key) for key in ("overall_status", "can_build_gold_macro_overview", "can_emit_strong_conclusion", "blocked_mainlines", "stale_sources")},
            "quality_gate": {"action": post_coordinator_quality_gate_decision.action.value, "publish_allowed": agent_loop_decision.publish_allowed},
            "agent_loop": {"no_strong_conclusion": agent_loop_decision.no_strong_conclusion},
            "gold_policy": {
                "execution_mode": gold_policy_execution_mode,
                "decision": gold_analysis_decision.model_dump(mode="json") if gold_analysis_decision is not None else None,
                "artifact_refs": dict(gold_policy_artifact_paths),
            },
            "fact_review": {"status": fact_review_output.status.value, "summary": fact_review_output.summary},
            "market_odds": {"status": market_odds_output.status.value, "summary": market_odds_output.summary},
            "integrated_mainlines": [{key: row.get(key) for key in ("mainline_id", "coverage_status", "direction", "summary", "missing_data", "feature_fields")} for row in gold_macro_overview.get("theme_rankings", [])],
            "source_refs": [
                {"source": "source_health", "artifact_ref": canonical_source_health_path.relative_to(storage_root).as_posix()},
                {"source": "quality_gate", "artifact_ref": canonical_quality_gate_path.relative_to(storage_root).as_posix()},
            ],
        }
    shadow_record_path = None
    if snapshot.get("gold_workflow", {}).get("production_shadow"):
        from apps.analysis.research_shadow import build_shadow_record

        shadow_record = build_shadow_record(
            snapshot,
            coordinator_output,
            created_at=created_at,
            report_output=selected_coordinator,
        )
        shadow_record_path = canonical_run_dir / "production_shadow_record.v1.json"
        write_canonical_gold_json(shadow_record_path, shadow_record, storage_root=storage_root)
        research_assessment["report_controls"]["production_shadow"] = {
            "record": shadow_record, "artifact_ref": shadow_record_path.relative_to(storage_root).as_posix(),
            "production_v1_approved": False,
        }
    rejection_reasons = research_report_rejection_reasons(snapshot, coordinator_output)
    if rejection_reasons:
        return blocked_research_result(storage_root=storage_root, snapshot=snapshot, run_id=run_id,
            summaries=summaries, reasons=rejection_reasons,
            agents={output.agent_name: output for output in [*reviewed_outputs, coordinator_output]},
            quality_gate_decision=post_coordinator_quality_gate_decision)
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
        research_assessment=research_assessment,
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
            research_assessment=research_assessment,
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
    audit_kwargs = {}
    if snapshot.get('gold_workflow', {}).get('reader_report_version') in {'gold_reader.v1', 'gold_reader.v2', 'gold_reader.v3', 'gold_reader.v4'}:
        from apps.renderer.markdown.gold_workflow import gold_workflow_sections
        from apps.renderer.markdown.daily_research import render_daily_research_report

        audit_outputs = {'macro': macro_output, 'options': options_output, 'risk': risk_output,
                         'technical': technical_output, 'positioning': positioning_output,
                         'news': news_output, 'coordinator': selected_coordinator}
        audit_kwargs['audit_markdown'] = render_daily_research_report(
            snapshot, gold_workflow_sections(snapshot, audit_outputs, research_assessment))
        if snapshot['gold_workflow']['reader_report_version'] in {'gold_reader.v3', 'gold_reader.v4'}:
            from apps.renderer.markdown.gold_reader import reader_audit_details
            audit_kwargs['audit_markdown'] += reader_audit_details(snapshot, audit_outputs)
    report_result = write_final_report(
        storage_root=storage_root,
        markdown=markdown,
        asset="XAUUSD",
        trade_date=str(trade_date),
        run_id=run_id,
        structured_report=structured_dict,
        artifact_type=report_artifact_type,
        **audit_kwargs,
    )
    card = build_strategy_card(
        snapshot=snapshot,
        coordinator_output=selected_coordinator,
        risk_output=risk_output,
        created_at=created_at,
    )
    if agent_loop_decision.no_strong_conclusion:
        card = observe_strategy_card(card, reason=agent_loop_decision.strategy_card_override.get("reason"), keep_research_context=bool(research_assessment))
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
            # Persist the exact observation projection consumed by the renderer.
            # Keep its pre-projection model/fallback output independently intact.
            **({selected_coordinator.agent_name: selected_coordinator}
               if selected_coordinator.module == "report_observation_projection" else {}),
        },
        "analysis_snapshot": snapshot,
        "structured_report": structured_dict,
        "input_validation": validation,
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
        "gold_feature_snapshot": gold_feature_snapshot,
        "gold_analysis_decision": gold_analysis_decision,
        "gold_price_attribution": gold_price_attribution,
        "gold_policy_artifact_paths": gold_policy_artifact_paths,
        "gold_policy_execution_mode": gold_policy_execution_mode,
        "gold_daily_close_execution": gold_daily_close_execution,
        "production_shadow_record_path": str(shadow_record_path) if shadow_record_path else None,
    }

    # Store the complete structured renderer output in the existing output table.
    # Observation archives have no FinalAnalysisResult row, so this is their DB owner too.
    from apps.analysis.agents.schemas import AgentOutput, AgentStatus
    composite_outputs["agents"]["report_render_agent"] = AgentOutput(
        version="1.0", agent_name="report_render_agent", module="report_render",
        snapshot_id=str(snapshot_id), input_snapshot_ids=dict(snapshot.get("input_snapshot_ids") or {}),
        bias=AgentBias.NEUTRAL, confidence=0.0, status=AgentStatus.SUCCESS,
        key_findings=[], risk_points=[], watchlist=[], invalid_conditions=[],
        summary="报告渲染完成；结构化正文与校验记录已绑定本次输入。",
        source_refs=list(snapshot.get("source_refs") or []), created_at=created_at or datetime.now(timezone.utc),
        input_payload={"structured_report": structured_dict, "input_validation": validation},
    )

    return summaries, composite_outputs


def blocked_research_result(*, storage_root, snapshot, run_id, summaries, reasons,
                            agents=None, quality_gate_decision=None):
    """Materialize only a run-bound diagnostic; callers must tolerate absent reports."""
    path = storage_root / "analysis" / "input_validation" / str(snapshot.get("trade_date", "")) / run_id / "research_diagnostic.json"
    diagnostic = {"schema_version": "research_generation_diagnostic.v1", "status": "blocked",
        "run_id": run_id, "snapshot_id": snapshot.get("snapshot_id"),
        "input_validation": snapshot.get("input_validation"), "reason_codes": sorted(set(reasons)),
        "publish_allowed": False, "report_generated": False}
    write_canonical_gold_json(path, diagnostic, storage_root=storage_root)
    result = {"paths": [str(path)], "status": "blocked", "artifact_type": "research_diagnostic"}
    summary = {"status": "blocked", "snapshot_id": snapshot.get("snapshot_id"),
        "run_id": run_id, "reason_codes": diagnostic["reason_codes"], "paths": [str(path)],
        "output_refs": [{"file_path": str(path), "artifact_type": "structured_json", "status": "blocked"}],
        "publish_allowed": False, "output_mode": "diagnostic"}
    for step in ("final_report", "strategy_card", "research_generation"):
        summaries[step] = {"step": step, **summary}
    if not agents:
        from apps.analysis.agents.schemas import AgentOutput, AgentStatus
        diagnostic_agent = AgentOutput(version="1.0", agent_name="research_input_validation", module="input_validation",
            snapshot_id=str(snapshot.get("snapshot_id", "unknown")), input_snapshot_ids=dict(snapshot.get("input_snapshot_ids") or {}),
            bias=AgentBias.UNAVAILABLE, confidence=0.0, key_findings=[], risk_points=[], watchlist=[],
            invalid_conditions=[], summary="研究输入校验阻断，详见诊断 artifact。", source_refs=list(snapshot.get("source_refs") or []),
            status=AgentStatus.UNAVAILABLE, created_at=datetime.now(timezone.utc), input_payload=diagnostic)
        agents = {diagnostic_agent.agent_name: diagnostic_agent}
    # Rejected synthesis is not a research body worth persisting. Keep successful
    # domain work, but replace the failed composite opinion with its diagnostic.
    agents = {
        name: _rejected_research_diagnostic(output, diagnostic)
        if name in {"coordinator_agent", "report_render_agent", "research_input_validation"}
        else output
        for name, output in agents.items()
    }
    return summaries, {"agents": agents, "analysis_snapshot": snapshot,
        "input_validation": snapshot.get("input_validation"), "diagnostic_result": result,
        "report_result": None, "card_result": None, "strategy_card": None,
        "agent_loop_decision": None, "quality_gate_decision": quality_gate_decision,
        "post_coordinator_quality_gate_decision": quality_gate_decision,
        "gold_runtime_summary": {"status": "blocked", "publish_allowed": False}, "observe_outputs": {}}


def _rejected_research_diagnostic(output, diagnostic):
    import hashlib
    import json

    from apps.analysis.agents.schemas import AgentOutput, AgentStatus

    original = output.model_dump(mode="json")
    marker = {
        "schema_version": 1,
        "status": "purged",
        "reason_codes": diagnostic["reason_codes"],
        "purged_at": datetime.now(timezone.utc).isoformat(),
        "original_payload_sha256": hashlib.sha256(
            json.dumps(original, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "run_id": diagnostic["run_id"],
        "snapshot_id": diagnostic["snapshot_id"],
    }
    return AgentOutput(
        version=output.version, agent_name=output.agent_name, module=output.module,
        snapshot_id=output.snapshot_id, input_snapshot_ids=output.input_snapshot_ids,
        source_refs=output.source_refs, created_at=output.created_at,
        status=AgentStatus.UNAVAILABLE, bias=AgentBias.UNAVAILABLE, confidence=0.0,
        summary="研究未通过校验，正文未保留。", key_findings=[], risk_points=[],
        watchlist=[], invalid_conditions=[], llm_model=output.llm_model,
        llm_provider=output.llm_provider, llm_usage=output.llm_usage,
        llm_latency_ms=output.llm_latency_ms, llm_audit_id=output.llm_audit_id,
        input_payload={**diagnostic, "output_cleanup": marker},
    )


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
            "agent_name": "report_observation_projection",
            "module": "report_observation_projection",
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
    report_result: dict[str, Any] | None,
    card_result: dict[str, Any] | None,
    publish_allowed: bool,
) -> dict[str, Any]:
    """Return concrete renderer refs and fail closed for accepted publication.

    Writer summaries are not artifact evidence by themselves.  Accepted output
    authority requires both formal bundles to expose non-empty, existing files
    beneath their canonical storage directories.  Observation-only callers keep
    their existing best-effort behavior and can never populate accepted output.
    """
    report_result = report_result or {}
    card_result = card_result or {}
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


def observe_strategy_card(card: Any, *, reason: Any, keep_research_context: bool = False) -> Any:
    reason_text = str(reason or "quality_gate_not_passed")
    return card.model_copy(
        update={
            "bias": AgentBias.NEUTRAL,
            "confidence": min(card.confidence, 0.35),
            "scenario_summary": (
                f"Observe and wait ({reason_text}). No strong conclusion is permitted until QualityGate passes."
                + (f" 研究观察（不构成正式方向）：{card.scenario_summary}" if keep_research_context else "")
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
    if context_metadata["status"] == "disabled" and "jin10" in snapshot.get("disabled_sources", []):
        context_metadata = {"status": "disabled", "reason": "jin10_disabled", "disabled_sources": ["jin10"]}
    if snapshot.get("daily_research"):
        from apps.analysis.gold_mainline_engine import build_gold_macro_overview

        macro = snapshot.get("macro", {}).get("data", {})
        rows = snapshot["daily_research"].get("passport", [])
        allowed = {row["symbol"] for row in rows if row.get("status") == "fresh" and row.get("lineage_status", "verified") == "verified"}
        macro_context = {"indicators": {key: value for key, value in macro.get("indicators", {}).items() if key in allowed}, "source_refs": macro.get("source_refs", {}), "project_signals": snapshot["daily_research"].get("project_signals", {})}
        event_mainlines = (news_data or {}).get("gold_event_mainlines", {})
        integrated = build_gold_macro_overview(event_mainlines, macro_context=macro_context).to_dict()
        integrated["source_refs"] = [*(integrated.get("source_refs") or []), *(ref for row in rows if row["symbol"] in allowed for ref in row.get("source_refs", []))]
        integrated["input_snapshot_ids"] = dict(snapshot.get("input_snapshot_ids") or {})
        integrated["gold_analysis_context"] = context_metadata
        integrated["as_of"] = snapshot.get("snapshot_time")
        return integrated
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
