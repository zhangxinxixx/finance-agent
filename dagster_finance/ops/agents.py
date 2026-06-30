"""Dagster ops for the C4 agent pipeline.

Wraps the C3 agents, coordinator, and strategy card builder.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dagster import Config, op
from pydantic import ValidationError

from dagster_finance.ops.artifact_registration import register_dagster_output_artifacts
from apps.runtime.execution_event_bridge import emit_task_event


class AgentConfig(Config):
    storage_root: str = "./storage"


def _to_dict(result: Any) -> dict[str, Any]:
    """Serialize AgentOutput (Pydantic) to dict for Dagster IO."""
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
    tags={"pipeline": "c4", "step": "macro_liquidity"},
)
def macro_liquidity_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity
    created_at = datetime.now(timezone.utc)
    context.log.info("Running macro_liquidity agent")
    result = analyze_macro_liquidity(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "c4", "step": "cme_options"},
)
def cme_options_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.cme_options import analyze_cme_options
    created_at = datetime.now(timezone.utc)
    context.log.info("Running cme_options agent")
    result = analyze_cme_options(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "c4", "step": "risk"},
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
    tags={"pipeline": "c4", "step": "technical"},
)
def technical_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.technical import analyze_technical
    created_at = datetime.now(timezone.utc)
    context.log.info("Running technical agent")
    result = analyze_technical(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "c4", "step": "positioning"},
)
def positioning_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.positioning import analyze_positioning
    created_at = datetime.now(timezone.utc)
    context.log.info("Running positioning agent")
    result = analyze_positioning(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "c4", "step": "news"},
)
def news_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.news import analyze_news
    created_at = datetime.now(timezone.utc)
    context.log.info("Running news agent")
    result = analyze_news(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "c4", "step": "market_odds"},
)
def market_odds_agent_op(context, snapshot: dict[str, Any]) -> dict[str, Any]:
    from apps.analysis.agents.market_odds import analyze_market_odds
    created_at = datetime.now(timezone.utc)
    context.log.info("Running market_odds agent")
    result = analyze_market_odds(snapshot, created_at=created_at)
    return _to_dict(result)


@op(
    tags={"pipeline": "c4", "step": "coordinator"},
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
    required_resource_keys={"db_session"},
    tags={"pipeline": "c4", "step": "strategy_card"},
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
    task_id = _register_strategy_card_artifacts(
        context,
        result=result,
        card=card,
        snapshot=snapshot,
    )
    _emit_strategy_card_timeline_events(context, task_id=task_id, result=result, card=card, snapshot=snapshot)
    context.log.info("Strategy card built")
    return result


def _register_strategy_card_artifacts(
    context,
    *,
    result: dict[str, Any],
    card: Any,
    snapshot: dict[str, Any],
) -> str | None:
    paths = result.get("paths") if isinstance(result, dict) else None
    if not isinstance(paths, list) or not paths:
        return None

    return register_dagster_output_artifacts(
        context,
        db=context.resources.db_session,
        paths=paths,
        step_name="strategy_card",
        stage="c4",
        task_kind="agent",
        source_refs=_strategy_card_source_refs(card=card, snapshot=snapshot),
        input_snapshot_ids=_strategy_card_input_snapshot_ids(card=card, snapshot=snapshot),
        snapshot_id=_optional_str(snapshot.get("snapshot_id")),
        trade_date=_optional_str(snapshot.get("trade_date")),
    )


def _emit_strategy_card_timeline_events(
    context,
    *,
    task_id: str | None,
    result: dict[str, Any],
    card: Any,
    snapshot: dict[str, Any],
) -> None:
    if not task_id:
        return
    paths = result.get("paths") if isinstance(result, dict) else []
    output_artifacts = [Path(path).name for path in paths if isinstance(path, str) and path]
    db = context.resources.db_session
    emit_task_event(
        db,
        run_id=str(context.run_id),
        task_id=task_id,
        event_type="AGENT_EXECUTED",
        payload={
            "agent_name": "strategy_card_agent",
            "module": "strategy",
            "status": "success",
            "snapshot_id": _optional_str(snapshot.get("snapshot_id")),
            "output_artifacts": output_artifacts,
        },
    )
    emit_task_event(
        db,
        run_id=str(context.run_id),
        task_id=task_id,
        event_type="DECISION_COMPUTED",
        payload={
            "decision_type": "strategy_card",
            "asset": getattr(card, "asset", None),
            "trade_date": getattr(card, "trade_date", None),
            "bias": getattr(getattr(card, "bias", None), "value", getattr(card, "bias", None)),
            "confidence": getattr(card, "confidence", None),
            "is_trade_instruction": getattr(card, "is_trade_instruction", None),
        },
    )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        context.log.warning("Skipping strategy card timeline event commit: %s", exc)


def _strategy_card_source_refs(*, card: Any, snapshot: dict[str, Any]) -> list[dict[str, Any]] | None:
    refs: list[dict[str, Any]] = []
    refs.extend(ref for ref in snapshot.get("source_refs", []) if isinstance(ref, dict))
    refs.extend(
        _normalize_strategy_card_source_ref(ref)
        for ref in getattr(card, "source_refs", [])
        if isinstance(ref, dict)
    )
    return _dedupe_dicts(refs)


def _strategy_card_input_snapshot_ids(*, card: Any, snapshot: dict[str, Any]) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    snapshot_ids = snapshot.get("input_snapshot_ids")
    if isinstance(snapshot_ids, dict):
        merged.update({str(key): value for key, value in snapshot_ids.items() if str(key)})
    card_ids = getattr(card, "input_snapshot_ids", None)
    if isinstance(card_ids, dict):
        merged["strategy_card_input_snapshot_ids"] = {
            str(key): value for key, value in card_ids.items() if str(key)
        }
    return merged or None


def _normalize_strategy_card_source_ref(ref: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(ref)
    source = normalized.pop("source", None)
    if source is not None:
        normalized["source_ref"] = str(source)
    return normalized


def _dedupe_dicts(refs: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for ref in refs:
        normalized = {str(key): value for key, value in ref.items() if value is not None}
        key = tuple(sorted((str(item_key), str(item_value)) for item_key, item_value in normalized.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped or None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
