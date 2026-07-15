"""API dependency adapter for read-only live-strategy recompute previews."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from apps.api.services.event_flow_service import (
    build_event_flow_event_detail,
    build_event_flow_market_reaction,
)
from apps.api.services.live_strategy_service import (
    LiveStrategyHistoryStorageError,
    get_live_strategy_history,
    get_live_strategy_latest,
)
from apps.api.services.options_service import get_options_decision
from apps.runtime.live_strategy_recompute import (
    LiveStrategyRecomputePreviewQueryError,
    LiveStrategyRecomputePreviewUnavailableError,
    RECOMPUTE_PREVIEW_SCHEMA_VERSION,
    preview_live_strategy_recompute as preview_runtime_live_strategy_recompute,
)


def preview_live_strategy_recompute(
    *,
    event_id: str,
    db: Any | None = None,
    now: datetime | None = None,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    """Adapt API read models to the runtime-owned, read-only preview."""

    def load_history() -> dict[str, Any]:
        try:
            return get_live_strategy_history(
                asset="XAUUSD",
                limit=1,
                storage_root=storage_root,
            )
        except LiveStrategyHistoryStorageError as exc:
            raise LiveStrategyRecomputePreviewUnavailableError(
                "strategy_history_invalid"
            ) from exc

    return preview_runtime_live_strategy_recompute(
        event_id=event_id,
        event_detail_loader=build_event_flow_event_detail,
        market_reaction_loader=build_event_flow_market_reaction,
        strategy_history_loader=load_history,
        candidate_strategy_loader=lambda observation: get_live_strategy_latest(
            asset="XAUUSD",
            db=db,
            now=now,
            event_observation=observation,
        ),
        options_decision_loader=lambda: get_options_decision(db=db),
    )


__all__ = [
    "LiveStrategyRecomputePreviewQueryError",
    "RECOMPUTE_PREVIEW_SCHEMA_VERSION",
    "preview_live_strategy_recompute",
]
