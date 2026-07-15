"""I/O adapter for the Issue 63-A live strategy read model."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.analysis.strategy.history_store import StrategyHistoryStore
from apps.analysis.strategy.live import build_live_strategy
from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.market_candle_service import get_market_candles
from apps.api.services.options_service import get_options_decision
from apps.api.services.report_service import get_strategy_card_read_model_latest


LIVE_STRATEGY_HISTORY_SCHEMA_VERSION = "live_strategy.history_api.v1"
LIVE_STRATEGY_HISTORY_MAX_LIMIT = 100


class LiveStrategyHistoryQueryError(ValueError):
    """Raised when a live-strategy history query is invalid."""


class LiveStrategyHistoryStorageError(RuntimeError):
    """Raised when a persisted live-strategy history artifact is unsafe."""


def get_live_strategy_history(
    *,
    asset: str = "XAUUSD",
    limit: int = 20,
    storage_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return immutable live-strategy history without creating new artifacts."""
    if not isinstance(asset, str):
        raise LiveStrategyHistoryQueryError("invalid asset")
    normalized_asset = asset.upper()
    if normalized_asset != "XAUUSD":
        raise LiveStrategyHistoryQueryError("live strategy history supports only XAUUSD")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= LIVE_STRATEGY_HISTORY_MAX_LIMIT:
        raise LiveStrategyHistoryQueryError(
            f"limit must be an integer between 1 and {LIVE_STRATEGY_HISTORY_MAX_LIMIT}"
        )

    root = Path(storage_root) if storage_root is not None else _PROJECT_ROOT / "storage"
    probe_limit = min(limit + 1, LIVE_STRATEGY_HISTORY_MAX_LIMIT)
    try:
        records = StrategyHistoryStore(root).list_latest(asset=normalized_asset, limit=probe_limit)
    except (OSError, TypeError, ValueError) as exc:
        raise LiveStrategyHistoryStorageError("live strategy history artifacts are invalid") from exc
    eligible_records = [record for record in records if _history_record_is_eligible(record)]
    truncated = len(eligible_records) > limit
    return {
        "schema_version": LIVE_STRATEGY_HISTORY_SCHEMA_VERSION,
        "asset": normalized_asset,
        "limit": limit,
        "items": eligible_records[:limit],
        "truncated": truncated,
    }


def _history_record_is_eligible(record: Any) -> bool:
    """Hide legacy artifacts that were written before the freeze gate existed."""
    if not isinstance(record, dict):
        return False
    payload = record.get("payload")
    if not isinstance(payload, dict):
        # Keep the read model tolerant of test/legacy metadata-only records;
        # the immutable store has already validated their required identity.
        return True
    if payload.get("schema_version") != "live_strategy.v1":
        return False
    if payload.get("strategy_status") == "SUSPENDED_DATA":
        return False
    market = payload.get("live_market")
    quality = payload.get("data_quality")
    canonical = quality.get("canonical_candle") if isinstance(quality, dict) else None
    return (
        isinstance(market, dict)
        and market.get("status") == "available"
        and isinstance(canonical, dict)
        and canonical.get("status") == "available"
    )


def get_live_strategy_latest(
    asset: str = "XAUUSD",
    *,
    db: Any | None = None,
    now: datetime | None = None,
    event_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load immutable inputs and build the current read-only live state."""
    normalized_asset = str(asset or "XAUUSD").upper()
    if normalized_asset != "XAUUSD":
        raise ValueError("live_strategy.v1 supports only XAUUSD")
    baseline = get_strategy_card_read_model_latest(asset=normalized_asset)
    canonical_market = get_market_candles(
        asset=normalized_asset,
        timeframe="5m",
        limit=30,
        session=db,
    )
    canonical_market_15m = get_market_candles(
        asset=normalized_asset,
        timeframe="15m",
        limit=5,
        session=db,
    )
    options_decision = get_options_decision(db=db)
    return build_live_strategy(
        asset=normalized_asset,
        baseline=baseline,
        canonical_market=canonical_market,
        canonical_market_15m=canonical_market_15m,
        options_decision=options_decision,
        quote_cache=_load_quote_cache(_PROJECT_ROOT),
        event_observation=event_observation,
        now=now,
    )


def _load_quote_cache(project_root: Path) -> dict[str, Any] | None:
    path = project_root / "storage" / "outputs" / "jin10" / "quotes_cache.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
