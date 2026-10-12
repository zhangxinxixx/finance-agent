"""Dagster ops for the canonical analysis pipeline.

Wraps the C3 agents, coordinator, and strategy card builder.
"""

import uuid
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from dagster import Config, op
from pydantic import ValidationError

from apps.output.final_report import write_final_report
from apps.renderer.markdown.final_report import build_structured_report, render_final_report_markdown


class AgentConfig(Config):
    storage_root: str = "./storage"


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "canonical_analysis", "step": "canonical_composite_analysis"},
)
def canonical_composite_analysis_op(
    context,
    config: AgentConfig,
    snapshot: dict[str, Any],
    readiness_gate: dict[str, Any],
) -> dict[str, Any]:
    """Delegate Dagster execution to the canonical gated composite pipeline."""

    if readiness_gate.get("decision") != "allow":
        reason_code = readiness_gate.get("reason_code") or "premarket_readiness_blocked"
        context.log.warning("Premarket readiness gate blocked domain agents: %s", reason_code)
        return {
            "premarket_readiness_gate": readiness_gate,
            "summaries": {
                "premarket": {
                    "step": "premarket_readiness_gate",
                    "status": "blocked",
                    "reason_code": reason_code,
                },
                "final_report": {
                    "output_mode": "blocked",
                    "status": "blocked",
                    "reason_code": reason_code,
                },
            },
            "quality_gate_decision": {
                "action": "block_publish",
                "reason_codes": [reason_code],
            },
            "agent_loop_decision": {"decision": "blocked", "reason_code": reason_code},
            "output_mode": "blocked",
            "report_result": None,
            "card_result": None,
        }

    from apps.worker.composite_analysis_pipeline import run_composite_analysis_pipeline

    context.log.info("Running canonical FactReview/QualityGate composite analysis")
    runtime_kwargs, runtime_summary = _gold_policy_runtime_kwargs(
        storage_root=Path(config.storage_root),
        snapshot=snapshot,
    )
    summaries, outputs = run_composite_analysis_pipeline(
        storage_root=Path(config.storage_root),
        snapshot=snapshot,
        run_id=context.run_id,
        created_at=_canonical_created_at(snapshot),
        **runtime_kwargs,
    )
    summaries = {**summaries, "gold_policy_runtime": runtime_summary}
    snapshot = outputs.get("analysis_snapshot") or snapshot
    _persist_canonical_composite_outputs(
        context,
        snapshot=snapshot,
        composite_outputs=outputs,
    )
    final_summary = summaries["final_report"]
    blocked = final_summary.get("status") == "blocked"
    quality_gate = _to_dict(outputs.get("quality_gate_decision"))
    if blocked:
        quality_gate = {**quality_gate, "action": "block_publish",
                        "reason_codes": final_summary.get("reason_codes") or ["research_generation_blocked"]}
    return {
        "premarket_readiness_gate": readiness_gate,
        "summaries": summaries,
        "gold_policy_runtime": runtime_summary,
        "quality_gate_decision": quality_gate,
        "agent_loop_decision": _to_dict(outputs["agent_loop_decision"]),
        "output_mode": "blocked" if blocked else final_summary["output_mode"],
        "diagnostic_result": outputs.get("diagnostic_result"),
        "input_validation": snapshot.get("input_validation"),
        "report_result": outputs["report_result"],
        "card_result": outputs["card_result"],
    }


def _persist_canonical_composite_outputs(
    context: Any,
    *,
    snapshot: dict[str, Any],
    composite_outputs: dict[str, Any],
) -> None:
    """Persist Dagster composite outputs through the established worker sinks.

    The canonical composite implementation is shared with the worker runner,
    but Dagster reaches it through this adapter. Keeping persistence at this
    boundary ensures the same run owns the AgentOutput, report artifacts, and
    accepted report registry rows as the files written by the composite.
    """

    db = getattr(context.resources, "db_session", None)
    if db is None:
        # Direct unit invocation of this op has no DB resource. A real
        # premarket job always supplies it via premarket_job.resource_defs.
        context.log.warning("Canonical composite persistence skipped: db_session resource unavailable")
        return

    from apps.worker.artifact_registration import register_composite_output_artifacts
    from apps.worker.db_persistence import (
        db_persist_agent_outputs,
        db_persist_final_result,
        ensure_review_items,
    )
    from apps.worker.report_registry_sink import register_composite_report_registry_entries
    from database.models.task import TaskStep

    run_id = str(context.run_id)
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        # Dagster's direct invocation context uses the sentinel EPHEMERAL id;
        # a real job run always has the UUID that owns the TaskRun steps.
        steps = []
    else:
        steps = (
            db.query(TaskStep)
            .filter(TaskStep.task_run_id == run_uuid)
            .all()
        )
    agents = composite_outputs["agents"]
    snapshot = composite_outputs.get("analysis_snapshot") or snapshot
    snapshot_db_id = db_persist_agent_outputs(db, snapshot, agents, run_id)

    agent_loop_decision = composite_outputs.get("agent_loop_decision")
    publish_allowed = bool(agent_loop_decision.get("publish_allowed", False)) if isinstance(agent_loop_decision, dict) else bool(getattr(agent_loop_decision, "publish_allowed", False))
    if publish_allowed:
        db_persist_final_result(db, snapshot, composite_outputs, snapshot_db_id)
    elif composite_outputs.get("strategy_card") is not None:
        ensure_review_items(
            db,
            run_id=run_id,
            trade_date=str(snapshot.get("trade_date") or ""),
            card=composite_outputs["strategy_card"],
            agents=agents,
        )

    register_composite_output_artifacts(
        db,
        run_id=run_id,
        steps=steps,
        composite_outputs=composite_outputs,
        analysis_snapshot=snapshot,
    )
    register_composite_report_registry_entries(
        db,
        run_id=run_id,
        composite_outputs=composite_outputs,
        analysis_snapshot=snapshot,
    )
    db.commit()


def _gold_policy_runtime_kwargs(*, storage_root: Path, snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prepare optional formal-policy inputs without affecting legacy publication."""

    try:
        from apps.analysis.gold_policy.runtime_inputs import prepare_gold_policy_runtime_inputs

        runtime = prepare_gold_policy_runtime_inputs(storage_root=storage_root, snapshot=snapshot)
        return (
            {
                "gold_feature_snapshot_prebuilt": runtime.current,
                "previous_gold_feature_snapshot_prebuilt": runtime.previous,
                "gold_policy_execution_mode": "shadow",
            },
            {"status": "ready", "lookup": runtime.lookup.summary()},
        )
    except Exception as exc:
        return (
            {},
            {
                "status": "failed",
                "reason_code": "gold_policy_runtime_prepare_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "lookup": {},
            },
        )


def _canonical_created_at(snapshot: dict[str, Any]) -> datetime:
    """Return the snapshot's stable, timezone-aware canonical artifact time.

    Canonical composite artifacts are immutable for a Dagster run/snapshot pair,
    so a retry must not take its timestamp from the worker's wall clock.
    """

    metadata = snapshot.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    snapshot_time = snapshot.get("snapshot_time")
    if snapshot_time is None:
        snapshot_time = metadata.get("snapshot_time")
    if snapshot_time is not None:
        return _parse_snapshot_datetime(snapshot_time, field_name="snapshot_time")

    as_of = snapshot.get("as_of")
    if as_of is None:
        as_of = metadata.get("as_of")
    if as_of is None:
        raise ValueError("canonical composite analysis requires snapshot_time or as_of")
    return _parse_snapshot_datetime(as_of, field_name="as_of")


def _parse_snapshot_datetime(value: Any, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        if field_name == "as_of":
            try:
                parsed_date = date.fromisoformat(value)
            except ValueError:
                pass
            else:
                return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"canonical composite analysis has invalid {field_name}: {value!r}") from exc
    else:
        raise ValueError(f"canonical composite analysis has invalid {field_name}: {value!r}")

    if parsed.tzinfo is not None:
        return parsed
    raise ValueError(f"canonical composite analysis {field_name} must include a timezone")


def _to_dict(result: Any) -> dict[str, Any]:
    """Serialize AgentOutput (Pydantic) to dict for Dagster IO."""
    if result is None:
        return {}
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if isinstance(result, dict):
        return result
    return {"value": str(result)}


def _coerce_agent_output(value: Any, *, name: str):
    """Restore AgentOutput models after Dagster IO serializes them to dicts."""
    from apps.analysis.agents.schemas import AgentOutput

    if isinstance(value, AgentOutput):
        return value
    if isinstance(value, dict):
        try:
            return AgentOutput.model_validate(value)
        except ValidationError as exc:
            raise ValueError(f"Invalid {name} payload for strategy card") from exc
    raise TypeError(f"{name} must be an AgentOutput or dict payload")


@op(
    tags={"pipeline": "canonical_analysis", "step": "macro_liquidity"},
)
def macro_liquidity_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity
    created_at = datetime.now(timezone.utc)
    context.log.info("Running macro_liquidity agent")
    result = analyze_macro_liquidity(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "canonical_analysis", "step": "cme_options"},
)
def cme_options_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.cme_options import analyze_cme_options
    created_at = datetime.now(timezone.utc)
    context.log.info("Running cme_options agent")
    result = analyze_cme_options(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "canonical_analysis", "step": "risk"},
)
def risk_agent_op(
    context,
    snapshot: dict[str, Any],
    macro_output: dict[str, Any],
    options_output: dict[str, Any],
) -> dict[str, Any]:
    from apps.analysis.agents.risk import analyze_risk
    created_at = datetime.now(timezone.utc)
    context.log.info("Running risk agent")
    result = analyze_risk(
        snapshot,
        macro_output=macro_output,
        options_output=options_output,
        created_at=created_at,
    )
    return _to_dict(result)


@op(
    tags={"pipeline": "canonical_analysis", "step": "technical"},
)
def technical_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.technical import analyze_technical
    created_at = datetime.now(timezone.utc)
    context.log.info("Running technical agent")
    result = analyze_technical(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "canonical_analysis", "step": "positioning"},
)
def positioning_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.positioning import analyze_positioning
    created_at = datetime.now(timezone.utc)
    context.log.info("Running positioning agent")
    result = analyze_positioning(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "canonical_analysis", "step": "news"},
)
def news_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.news import analyze_news
    created_at = datetime.now(timezone.utc)
    context.log.info("Running news agent")
    result = analyze_news(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "canonical_analysis", "step": "market_odds"},
)
def market_odds_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.market_odds import analyze_market_odds
    created_at = datetime.now(timezone.utc)
    context.log.info("Running market_odds agent")
    result = analyze_market_odds(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "canonical_analysis", "step": "coordinator"},
)
def coordinator_op(
    context,
    snapshot: dict[str, Any],
    macro_output: dict[str, Any],
    options_output: dict[str, Any],
    risk_output: dict[str, Any],
    technical_output: dict[str, Any],
    positioning_output: dict[str, Any],
    news_output: dict[str, Any],
    market_odds_output: dict[str, Any],
) -> dict[str, Any]:
    from apps.analysis.agents.coordinator import coordinate_agent_outputs
    created_at = datetime.now(timezone.utc)
    context.log.info("Running coordinator")
    result = coordinate_agent_outputs(
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
    return _to_dict(result)


@op(
    tags={"pipeline": "canonical_analysis", "step": "final_report"},
)
def final_report_op(
    context,
    snapshot: dict[str, Any],
    macro_output: dict[str, Any],
    options_output: dict[str, Any],
    risk_output: dict[str, Any],
    technical_output: dict[str, Any],
    positioning_output: dict[str, Any],
    news_output: dict[str, Any],
    coordinator_output: dict[str, Any],
) -> dict[str, Any]:
    """Render the composite analysis report from this Dagster run's agent outputs."""
    created_at = datetime.now(timezone.utc)
    outputs = {
        "macro": _coerce_agent_output(macro_output, name="macro_output"),
        "options": _coerce_agent_output(options_output, name="options_output"),
        "risk": _coerce_agent_output(risk_output, name="risk_output"),
        "technical": _coerce_agent_output(technical_output, name="technical_output"),
        "positioning": _coerce_agent_output(positioning_output, name="positioning_output"),
        "news": _coerce_agent_output(news_output, name="news_output"),
        "coordinator": _coerce_agent_output(coordinator_output, name="coordinator_output"),
    }
    context.log.info("Rendering final report")
    markdown = render_final_report_markdown(
        snapshot=snapshot,
        macro_output=outputs["macro"],
        options_output=outputs["options"],
        risk_output=outputs["risk"],
        technical_output=outputs["technical"],
        positioning_output=outputs["positioning"],
        news_output=outputs["news"],
        coordinator_output=outputs["coordinator"],
        created_at=created_at,
    )
    structured = build_structured_report(
        snapshot=snapshot,
        macro_output=outputs["macro"],
        options_output=outputs["options"],
        risk_output=outputs["risk"],
        technical_output=outputs["technical"],
        positioning_output=outputs["positioning"],
        news_output=outputs["news"],
        coordinator_output=outputs["coordinator"],
        created_at=created_at,
    )
    result = write_final_report(
        storage_root=Path("./storage"),
        markdown=markdown,
        asset=str(snapshot.get("asset") or "XAUUSD"),
        trade_date=str(snapshot["trade_date"]),
        run_id=context.run_id,
        structured_report=structured.model_dump(mode="json"),
    )
    context.log.info("Final report rendered")
    return result


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "canonical_analysis", "step": "strategy_card"},
)
def strategy_card_op(
    context,
    snapshot: dict[str, Any],
    coordinator_output: dict[str, Any],
    risk_output: dict[str, Any],
) -> dict[str, Any]:
    from apps.analysis.strategy.card import build_strategy_card
    from apps.output.final_report import write_strategy_card
    storage = Path("./storage")
    created_at = datetime.now(timezone.utc)
    context.log.info("Building strategy card")
    coordinator = _coerce_agent_output(coordinator_output, name="coordinator_output")
    risk = _coerce_agent_output(risk_output, name="risk_output")
    card = build_strategy_card(
        snapshot=snapshot,
        coordinator_output=coordinator,
        risk_output=risk,
        created_at=created_at,
    )
    result = write_strategy_card(storage_root=storage, card=card)
    context.log.info("Strategy card built")
    return result
