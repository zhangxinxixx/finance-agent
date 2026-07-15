"""Read-only runtime orchestration for event-gated strategy recompute previews."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from apps.analysis.strategy.event_observation import build_event_observation
from apps.analysis.strategy.recompute_execution import execute_strategy_recompute


RECOMPUTE_PREVIEW_SCHEMA_VERSION = "live_strategy.recompute_preview.v1"
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

EventDetailLoader = Callable[[str], Mapping[str, Any] | None]
MarketReactionLoader = Callable[[str], Mapping[str, Any] | None]
StrategyHistoryLoader = Callable[[], Mapping[str, Any]]
CandidateStrategyLoader = Callable[[Mapping[str, Any]], Mapping[str, Any]]
OptionsDecisionLoader = Callable[[], Mapping[str, Any] | None]


class LiveStrategyRecomputePreviewQueryError(ValueError):
    """Raised when a recompute-preview query is invalid."""


class LiveStrategyRecomputePreviewUnavailableError(RuntimeError):
    """A dependency adapter can use this to return a typed unavailable result."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def preview_live_strategy_recompute(
    *,
    event_id: str,
    event_detail_loader: EventDetailLoader,
    market_reaction_loader: MarketReactionLoader,
    strategy_history_loader: StrategyHistoryLoader,
    candidate_strategy_loader: CandidateStrategyLoader,
    options_decision_loader: OptionsDecisionLoader,
) -> dict[str, Any]:
    """Preview one recompute using injected read dependencies and no writes."""

    normalized_event_id = _validated_event_id(event_id)
    event_detail = event_detail_loader(normalized_event_id)
    if event_detail is None:
        return _result(
            status="unavailable",
            event_id=normalized_event_id,
            reasons=["event_not_found"],
        )

    market_reaction = market_reaction_loader(normalized_event_id)
    observation = build_event_observation(event_detail, market_reaction)
    observation_status = observation.get("status")
    if observation_status != "available":
        reasons = _text_items(observation.get("reasons")) or ["event_observation_unavailable"]
        return _result(
            status="blocked" if observation_status == "blocked" else "unavailable",
            event_id=normalized_event_id,
            reasons=reasons,
            event_observation=observation,
        )

    try:
        history = strategy_history_loader()
    except LiveStrategyRecomputePreviewUnavailableError as exc:
        return _result(
            status="unavailable",
            event_id=normalized_event_id,
            reasons=[exc.reason],
            event_observation=observation,
        )

    previous = _latest_history_payload(history)
    if previous is None:
        return _result(
            status="unavailable",
            event_id=normalized_event_id,
            reasons=["eligible_strategy_history_unavailable"],
            event_observation=observation,
        )

    candidate = candidate_strategy_loader(observation)
    candidate_reasons = _canonical_candidate_reasons(candidate)
    if candidate_reasons:
        return _result(
            status="blocked",
            event_id=normalized_event_id,
            reasons=candidate_reasons,
            event_observation=observation,
            previous_strategy=previous,
            candidate_strategy=candidate,
        )

    options_decision = options_decision_loader()
    evidence = {
        "event_id": normalized_event_id,
        "observation_id": observation.get("observation_id"),
        "evidence": _mapping_items(observation.get("evidence")),
        "source_refs": _mapping_items(observation.get("source_refs")),
    }
    execution = execute_strategy_recompute(
        previous,
        candidate,
        options_decision=options_decision,
        evidence=evidence,
    )
    accepted = execution.get("status") == "accepted"
    reasons = (
        ["accepted:recompute_preview"]
        if accepted
        else _text_items(_nested(execution, "recompute", "reason_codes"))
        or ["recompute_blocked"]
    )
    return _result(
        status="accepted" if accepted else "blocked",
        event_id=normalized_event_id,
        reasons=reasons,
        event_observation=observation,
        previous_strategy=previous,
        candidate_strategy=candidate,
        execution=execution,
    )


def _validated_event_id(value: Any) -> str:
    if not isinstance(value, str) or not _EVENT_ID_RE.fullmatch(value):
        raise LiveStrategyRecomputePreviewQueryError("invalid event_id")
    return value


def _latest_history_payload(history: Mapping[str, Any]) -> dict[str, Any] | None:
    items = history.get("items")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    payload = first.get("payload") if isinstance(first, Mapping) else None
    return dict(payload) if isinstance(payload, Mapping) else None


def _canonical_candidate_reasons(candidate: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if candidate.get("status") not in {"available", "partial"}:
        reasons.append("candidate_status_unavailable")
    if candidate.get("strategy_status") == "SUSPENDED_DATA":
        reasons.append("candidate_strategy_suspended_data")
    market = candidate.get("live_market")
    if not isinstance(market, Mapping) or market.get("status") != "available":
        reasons.append("candidate_canonical_market_unavailable")
    quality = candidate.get("data_quality")
    canonical = quality.get("canonical_candle") if isinstance(quality, Mapping) else None
    if not isinstance(canonical, Mapping) or canonical.get("status") != "available":
        reasons.append("candidate_canonical_data_unavailable")
    return reasons


def _result(
    *,
    status: str,
    event_id: str,
    reasons: list[str],
    event_observation: Mapping[str, Any] | None = None,
    previous_strategy: Mapping[str, Any] | None = None,
    candidate_strategy: Mapping[str, Any] | None = None,
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": RECOMPUTE_PREVIEW_SCHEMA_VERSION,
        "status": status,
        "event_id": event_id,
        "reasons": list(dict.fromkeys(reasons)),
        "event_observation": dict(event_observation) if event_observation is not None else None,
        "previous_strategy": dict(previous_strategy) if previous_strategy is not None else None,
        "candidate_strategy": dict(candidate_strategy) if candidate_strategy is not None else None,
        "execution": dict(execution) if execution is not None else None,
    }


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, Mapping)]


def _text_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


__all__ = [
    "CandidateStrategyLoader",
    "EventDetailLoader",
    "LiveStrategyRecomputePreviewQueryError",
    "LiveStrategyRecomputePreviewUnavailableError",
    "MarketReactionLoader",
    "OptionsDecisionLoader",
    "RECOMPUTE_PREVIEW_SCHEMA_VERSION",
    "StrategyHistoryLoader",
    "preview_live_strategy_recompute",
]
