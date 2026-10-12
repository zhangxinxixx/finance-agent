"""Jin10 market/cache routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter

from apps.api.services import jin10_market_service
from apps.api.services.jin10_web_flash_brief_service import get_jin10_web_flash_briefs_latest
from apps.api.services.page_calendar_read_model_service import get_calendar_summary
from apps.runtime.source_controls import jin10_disabled

router = APIRouter()


@router.get("/api/jin10/quotes/latest")
def api_jin10_quotes_latest():
    """Retained URL with explicit numeric-source retirement semantics."""
    return jin10_market_service.jin10_unavailable("jin10_news_only")


@router.get("/api/jin10/calendar")
def api_jin10_calendar():
    """Compatibility alias for the official DWS calendar read model."""
    return get_calendar_summary()


@router.get("/api/jin10/flash")
def api_jin10_flash():
    """Return the derived Jin10 flash brief read model, never cache input."""
    if jin10_disabled():
        return {
            "status": "disabled",
            "items": [],
            "message": "Jin10 source disabled by runtime settings",
            "reason": "disabled_by_settings: FINANCE_AGENT_DISABLE_JIN10",
        }
    read_model = get_jin10_web_flash_briefs_latest()
    if read_model is None:
        return {
            "status": "unavailable",
            "items": [],
            "message": "A DWS Jin10 flash read model is not available",
            "reason": "dws_flash_unavailable",
            "page_layer": "ADS",
        }
    return {
        "status": read_model.get("status") or "unavailable",
        "items": list(read_model.get("briefs") or []),
        "count": int(read_model.get("brief_count") or 0),
        "as_of": read_model.get("as_of"),
        "date": read_model.get("date"),
        "run_id": read_model.get("run_id"),
        "data_quality": dict(read_model.get("data_quality") or {}),
        "quality_flags": dict(read_model.get("quality_flags") or {}),
        "source_refs": list(read_model.get("source_refs") or []),
        "artifact_refs": list(read_model.get("artifact_refs") or []),
        "page_layer": "ADS",
    }


@router.get("/api/jin10/kline")
def api_jin10_kline(
    symbol: str = "XAUUSD",
    timeframe: str = "1m",
    limit: int = 200,
):
    """Historical Jin10 K-lines cannot be served as current numeric evidence."""
    return {
        "status": "unavailable",
        "reason": "jin10_news_only",
        "symbol": symbol,
        "timeframe": timeframe,
        "count": 0,
        "candles": [],
    }
