"""Dagster ops for the C4 agent pipeline.

Wraps the C3 agents, coordinator, and strategy card builder.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dagster import Config, op
from pydantic import ValidationError


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
    context.log.info("Strategy card built")
    return result
