"""Read-only Gold v3 runtime orchestration contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from apps.contracts.gold import GOLD_MAINLINE_IDS, GOLD_TRANSMISSION_CHAIN_IDS

GoldRunMode = Literal[
    "premarket_full_run",
    "intraday_event_update",
    "major_event_reprice",
    "postmarket_report_run",
    "system_evolution_check",
    "version_change_validation",
]

ReviewStatus = Literal["pass", "needs_review", "blocked"]
QualityGateStatus = Literal["passed", "fallback_required", "needs_review", "blocked"]

_ALL_GOLD_AGENTS = (
    "source_health_agent",
    "event_attribution_agent",
    "transmission_chain_agent",
    "driver_decomposition_agent",
    "mainline_ranking_agent",
    "gold_macro_overview_agent",
    "review_gate_agent",
    "report_render_agent",
)


@dataclass(frozen=True, slots=True)
class GoldRuntimeModeContract:
    """Pure contract for one Gold v3 runtime mode."""

    run_mode: GoldRunMode
    trigger_mode: str
    default_trigger_reason: str
    agents_executed: tuple[str, ...]
    agents_skipped: tuple[str, ...]
    affected_mainlines: tuple[str, ...]
    affected_chains: tuple[str, ...]
    gold_macro_overview_updated: bool
    report_rendered: bool
    review_status: ReviewStatus
    warnings: tuple[str, ...] = ()
    scheduler_entrypoint: str = "scheduler_worker_main_chain"

    def to_dict(self) -> dict[str, object]:
        return {
            "run_mode": self.run_mode,
            "trigger_mode": self.trigger_mode,
            "default_trigger_reason": self.default_trigger_reason,
            "planned_agents_executed": list(self.agents_executed),
            "planned_agents_skipped": list(self.agents_skipped),
            "affected_mainlines": list(self.affected_mainlines),
            "affected_chains": list(self.affected_chains),
            "gold_macro_overview_updated": self.gold_macro_overview_updated,
            "report_rendered": self.report_rendered,
            "review_status": self.review_status,
            "warnings": list(self.warnings),
            "scheduler_entrypoint": self.scheduler_entrypoint,
            "runtime_contract_only": True,
            "artifact_execution_enabled": False,
            "pipeline_materialized_outputs": False,
            "executed_agents": [],
        }


_MODE_CONTRACTS: dict[GoldRunMode, GoldRuntimeModeContract] = {
    "premarket_full_run": GoldRuntimeModeContract(
        run_mode="premarket_full_run",
        trigger_mode="daily_schedule_or_manual_premarket_job",
        default_trigger_reason="daily_premarket_refresh",
        agents_executed=_ALL_GOLD_AGENTS,
        agents_skipped=(),
        affected_mainlines=GOLD_MAINLINE_IDS,
        affected_chains=GOLD_TRANSMISSION_CHAIN_IDS,
        gold_macro_overview_updated=True,
        report_rendered=True,
        review_status="needs_review",
    ),
    "intraday_event_update": GoldRuntimeModeContract(
        run_mode="intraday_event_update",
        trigger_mode="new_high_impact_event_or_market_breakout",
        default_trigger_reason="intraday_incremental_event",
        agents_executed=(
            "source_health_agent",
            "event_attribution_agent",
            "transmission_chain_agent",
            "driver_decomposition_agent",
            "mainline_ranking_agent",
            "gold_macro_overview_agent",
            "review_gate_agent",
        ),
        agents_skipped=("report_render_agent",),
        affected_mainlines=("geopolitical_war_risk", "oil_prices", "real_rates_usd", "gold_technical_levels"),
        affected_chains=("safe_haven_chain", "war_oil_rate_chain", "rate_chain", "technical_chain"),
        gold_macro_overview_updated=True,
        report_rendered=False,
        review_status="needs_review",
        warnings=("incremental_update_only", "skip_low_frequency_mainlines_when_unaffected"),
    ),
    "major_event_reprice": GoldRuntimeModeContract(
        run_mode="major_event_reprice",
        trigger_mode="macro_release_geopolitical_escalation_or_cross_asset_shock",
        default_trigger_reason="major_event_reprice",
        agents_executed=(
            "event_attribution_agent",
            "transmission_chain_agent",
            "source_health_agent",
            "driver_decomposition_agent",
            "mainline_ranking_agent",
            "gold_macro_overview_agent",
            "review_gate_agent",
        ),
        agents_skipped=("report_render_agent",),
        affected_mainlines=("geopolitical_war_risk", "oil_prices", "real_rates_usd", "gold_technical_levels"),
        affected_chains=("war_oil_rate_chain", "rate_chain", "technical_chain"),
        gold_macro_overview_updated=True,
        report_rendered=False,
        review_status="needs_review",
        warnings=("changed_dominant_theme_must_be_marked_when_detected",),
    ),
    "postmarket_report_run": GoldRuntimeModeContract(
        run_mode="postmarket_report_run",
        trigger_mode="daily_postmarket_or_report_generation",
        default_trigger_reason="daily_postmarket_review",
        agents_executed=(
            "source_health_agent",
            "mainline_ranking_agent",
            "gold_macro_overview_agent",
            "review_gate_agent",
            "report_render_agent",
            "system_evolution_agent",
        ),
        agents_skipped=("event_attribution_agent", "transmission_chain_agent", "driver_decomposition_agent"),
        affected_mainlines=GOLD_MAINLINE_IDS,
        affected_chains=("daily_review_chain", "report_lineage_chain", "system_quality_chain"),
        gold_macro_overview_updated=True,
        report_rendered=True,
        review_status="needs_review",
    ),
    "system_evolution_check": GoldRuntimeModeContract(
        run_mode="system_evolution_check",
        trigger_mode="quality_review_or_prompt_feedback_batch",
        default_trigger_reason="system_quality_review",
        agents_executed=("review_gate_agent", "system_evolution_agent", "prompt_evolution_agent"),
        agents_skipped=(
            "source_health_agent",
            "event_attribution_agent",
            "transmission_chain_agent",
            "driver_decomposition_agent",
            "mainline_ranking_agent",
            "gold_macro_overview_agent",
            "report_render_agent",
        ),
        affected_mainlines=(),
        affected_chains=("system_quality_chain", "prompt_evolution_chain"),
        gold_macro_overview_updated=False,
        report_rendered=False,
        review_status="needs_review",
    ),
    "version_change_validation": GoldRuntimeModeContract(
        run_mode="version_change_validation",
        trigger_mode="prompt_schema_dag_source_or_page_change",
        default_trigger_reason="version_change_validation",
        agents_executed=("schema_agent", "dag_lineage_agent", "test_validation_agent", "review_gate_agent", "system_evolution_agent"),
        agents_skipped=(
            "source_health_agent",
            "event_attribution_agent",
            "transmission_chain_agent",
            "driver_decomposition_agent",
            "mainline_ranking_agent",
            "gold_macro_overview_agent",
            "report_render_agent",
        ),
        affected_mainlines=(),
        affected_chains=("schema_contract_chain", "dag_lineage_chain", "frontend_binding_chain"),
        gold_macro_overview_updated=False,
        report_rendered=False,
        review_status="needs_review",
        warnings=("does_not_mutate_production_prompt_or_schema",),
    ),
}


def get_gold_runtime_mode_contracts() -> tuple[GoldRuntimeModeContract, ...]:
    """Return all Gold v3 runtime mode contracts in canonical order."""
    return tuple(_MODE_CONTRACTS[mode] for mode in _MODE_CONTRACTS)


def get_gold_runtime_mode_contract(run_mode: str) -> GoldRuntimeModeContract | None:
    """Return one runtime mode contract if it exists."""
    return _MODE_CONTRACTS.get(run_mode)  # type: ignore[arg-type]


def build_gold_runtime_orchestration_contract() -> dict[str, object]:
    """Return the read-only Gold v3 runtime orchestration contract."""
    modes = [contract.to_dict() for contract in get_gold_runtime_mode_contracts()]
    return {
        "source": "gold_runtime_orchestration_contract",
        "version": "gold_v3_runtime_orchestration_v1",
        "scheduler_boundary": "api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output",
        "run_modes": modes,
    }


def build_gold_runtime_summary_preview(
    *,
    run_mode: str,
    trigger_reason: str | None = None,
) -> dict[str, object]:
    """Return a JSON-friendly run summary preview for one mode.

    This is a preview contract only; actual execution remains owned by the
    scheduler/worker chain.
    """

    contract = get_gold_runtime_mode_contract(run_mode)
    if contract is None:
        valid_modes = [mode.run_mode for mode in get_gold_runtime_mode_contracts()]
        raise ValueError(f"Unknown Gold runtime mode: {run_mode}. Valid modes: {', '.join(valid_modes)}")

    return {
        "source": "gold_runtime_summary_preview",
        "run_mode": contract.run_mode,
        "trigger_reason": trigger_reason or contract.default_trigger_reason,
        "affected_mainlines": list(contract.affected_mainlines),
        "affected_chains": list(contract.affected_chains),
        "planned_agents_executed": list(contract.agents_executed),
        "planned_agents_skipped": list(contract.agents_skipped),
        "gold_macro_overview_updated": contract.gold_macro_overview_updated,
        "review_status": contract.review_status,
        "warnings": list(contract.warnings),
        "runtime_contract_only": True,
        "artifact_execution_enabled": False,
        "pipeline_materialized_outputs": False,
        "executed_agents": [],
        "writes": [],
    }


def build_gold_runtime_execution_summary(
    *,
    run_mode: str,
    trigger_reason: str | None = None,
    quality_gate_decision: Any = None,
    agent_loop_decision: Any = None,
    accepted_outputs: dict[str, Any] | None = None,
    fallback_tasks_created: list[dict[str, Any]] | None = None,
    fallback_attempts: int = 0,
    warnings: list[str] | None = None,
) -> dict[str, object]:
    """Return a materialized pipeline summary bound to scheduler/worker evidence.

    Gold v3.0 materializes pipeline outputs, but fixed Agent artifact execution
    remains a v3.1 concern. Keep ``runtime_contract_only`` true until that
    artifact execution lane exists, and expose the materialization state
    explicitly so downstream readers do not confuse planned agents with
    executed Agent artifacts.
    """

    summary = build_gold_runtime_summary_preview(run_mode=run_mode, trigger_reason=trigger_reason)
    decision = _quality_gate_decision_dict(quality_gate_decision)
    agent_loop = _agent_loop_decision_dict(agent_loop_decision)
    effective_outputs = _accepted_outputs(accepted_outputs=accepted_outputs, agent_loop=agent_loop)
    quality_gate_status = _quality_gate_status(decision)
    review_status = _review_status_from_quality_gate(quality_gate_status, decision)
    merged_warnings = {
        *[str(item) for item in summary.get("warnings") or []],
        *[str(item) for item in warnings or []],
    }
    if quality_gate_status == "fallback_required":
        merged_warnings.add("quality_gate_fallback_required")
    elif quality_gate_status == "needs_review":
        merged_warnings.add("quality_gate_needs_review")
    elif quality_gate_status == "blocked":
        merged_warnings.add("quality_gate_blocked")

    summary.update(
        {
            "source": "gold_runtime_execution_summary",
            "review_status": review_status,
            "quality_gate_status": quality_gate_status,
            "quality_gate_action": decision.get("action"),
            "quality_gate_decision": decision,
            "agent_loop_decision": agent_loop,
            "fallback_tasks_created": _fallback_tasks(
                explicit=fallback_tasks_created,
                agent_loop=agent_loop,
            ),
            "fallback_attempts": int(fallback_attempts),
            "accepted_outputs": effective_outputs,
            "no_strong_conclusion": quality_gate_status == "blocked" or bool(agent_loop.get("no_strong_conclusion")),
            "strategy_card_override": dict(agent_loop.get("strategy_card_override") or {}),
            "review_item_ids": [],
            "runtime_contract_only": True,
            "artifact_execution_enabled": False,
            "pipeline_materialized_outputs": bool(effective_outputs),
            "executed_agents": [],
            "writes": _accepted_output_paths(effective_outputs),
            "warnings": sorted(merged_warnings),
        }
    )
    return summary


def _quality_gate_decision_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {"action": "pass", "review_status": "pass", "publish_allowed": True}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _agent_loop_decision_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _accepted_outputs(*, accepted_outputs: dict[str, Any] | None, agent_loop: dict[str, Any]) -> dict[str, Any]:
    loop_outputs = agent_loop.get("accepted_outputs")
    if isinstance(loop_outputs, dict) and loop_outputs:
        return dict(loop_outputs)
    return dict(accepted_outputs or {})


def _fallback_tasks(*, explicit: list[dict[str, Any]] | None, agent_loop: dict[str, Any]) -> list[dict[str, Any]]:
    if explicit is not None:
        return list(explicit)
    tasks = agent_loop.get("fallback_tasks")
    if isinstance(tasks, list):
        return [dict(item) for item in tasks if isinstance(item, dict)]
    return []


def _quality_gate_status(decision: dict[str, Any]) -> QualityGateStatus:
    action = str(decision.get("action") or "")
    review_status = str(decision.get("review_status") or "")
    if action == "block_publish" or review_status == "blocked" or decision.get("publish_allowed") is False:
        return "blocked"
    if action in {"fallback", "retry"} or decision.get("fallback_recommended") or decision.get("retry_recommended"):
        return "fallback_required"
    if action == "manual_review" or review_status == "needs_review" or decision.get("manual_review_required"):
        return "needs_review"
    return "passed"


def _review_status_from_quality_gate(status: QualityGateStatus, decision: dict[str, Any]) -> ReviewStatus:
    if status == "blocked":
        return "blocked"
    if status in {"fallback_required", "needs_review"}:
        return "needs_review"
    raw = str(decision.get("review_status") or "pass")
    return raw if raw in {"pass", "needs_review", "blocked"} else "pass"  # type: ignore[return-value]


def _accepted_output_paths(value: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for item in value.values():
        if isinstance(item, str):
            paths.append(item)
        elif isinstance(item, list):
            paths.extend(str(path) for path in item if isinstance(path, str))
    return paths
