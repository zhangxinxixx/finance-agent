"""Jin10 market/cache routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from apps.api.services import jin10_market_service

router = APIRouter()


@router.get("/api/jin10/quotes/latest")
def api_jin10_quotes_latest():
    """返回最新的金十实时报价快照（来自 Analysis Snapshot 的 jin10 分区）。

    从最新的 premarket_snapshot.json 中提取 jin10 字段，
    包含实时行情报价、快讯/文章计数、K 线代码等。
    """
    storage_root = Path("./storage")
    snap_dir = storage_root / "features" / "snapshots" / "XAUUSD"
    if not snap_dir.exists():
        return jin10_market_service.jin10_unavailable("No snapshots directory found")

    date_dirs = sorted([d for d in snap_dir.iterdir() if d.is_dir()], reverse=True)
    if not date_dirs:
        return jin10_market_service.jin10_unavailable("No snapshot dates found")

    for date_dir in date_dirs:
        run_dirs = sorted([d for d in date_dir.iterdir() if d.is_dir()], reverse=True)
        for run_dir in run_dirs:
            snap_path = run_dir / "premarket_snapshot.json"
            if not snap_path.exists():
                continue
            try:
                snap = json.loads(snap_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            jin10_section = snap.get("jin10")
            if jin10_section:
                return jin10_section

    return jin10_market_service.jin10_unavailable("Jin10 section not yet populated in analysis snapshot.")


@router.get("/api/jin10/calendar")
def api_jin10_calendar():
    """返回 Jin10 经济日历（上一周 + 未来两周窗口）。"""
    cache_path = jin10_market_service.JIN10_CALENDAR_CACHE_PATH
    if not cache_path.exists():
        jin10_market_service.refresh_jin10_calendar_cache()
    if not cache_path.exists():
        return {"status": "unavailable", "events": [], "message": "Calendar data not available"}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        payload = jin10_market_service.build_jin10_calendar_payload(data, cache_path)
        if payload["freshness"]["reason"] == "no_upcoming_events":
            jin10_market_service.refresh_jin10_calendar_cache()
            if cache_path.exists():
                refreshed_data = json.loads(cache_path.read_text(encoding="utf-8"))
                return jin10_market_service.build_jin10_calendar_payload(refreshed_data, cache_path)
        return payload
    except Exception as exc:
        return {"status": "error", "events": [], "message": str(exc)}


@router.get("/api/jin10/flash")
def api_jin10_flash():
    """返回 Jin10 最新快讯。"""
    cache_path = jin10_market_service.JIN10_FLASH_CACHE_PATH
    if not cache_path.exists() or jin10_market_service.is_file_stale(
        cache_path,
        max_age_seconds=jin10_market_service.JIN10_FLASH_CACHE_MAX_AGE_SECONDS,
    ):
        try:
            from apps.scheduler.jin10_refresh import refresh_jin10_flash_cache

            refresh_jin10_flash_cache()
        except Exception:
            pass
    if not cache_path.exists():
        return {"status": "unavailable", "items": [], "message": "Flash news not available"}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "error", "items": [], "message": str(exc)}


@router.get("/api/jin10/kline")
def api_jin10_kline(
    symbol: str = "XAUUSD",
    timeframe: str = "1m",
    limit: int = 200,
):
    """返回 Jin10 K 线数据（从 market_candles 表读取），支持多周期聚合。"""
    from database.models.engine import SessionLocal
    from database.queries.market import list_market_candles

    valid_timeframes = {"1m", "5m", "15m", "30m", "1h", "4h", "1D"}
    if timeframe not in valid_timeframes:
        timeframe = "1m"

    if limit < 1 or limit > 1000:
        limit = max(1, min(limit, 1000))

    try:
        with SessionLocal() as session:
            kline_source = "jin10_mcp_kline_1m"
            if timeframe == "1m":
                rows = list_market_candles(session, asset=symbol, timeframe="1m", limit=limit, source=kline_source)
                if not rows:
                    rows = list_market_candles(session, asset=symbol, timeframe="1m", limit=limit, source="yahoo_finance_1m")
                candles = [jin10_market_service.candle_to_dict(row) for row in rows]
            else:
                fetch_limit = jin10_market_service.aggregation_fetch_limit(timeframe, limit)
                rows = list_market_candles(session, asset=symbol, timeframe="1m", limit=fetch_limit, source=kline_source)
                if not rows:
                    rows = list_market_candles(session, asset=symbol, timeframe="1m", limit=fetch_limit, source="yahoo_finance_1m")
                candles = jin10_market_service.aggregate_candles(rows, timeframe)[-limit:]

            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "count": len(candles),
                "candles": candles,
            }
    except Exception as exc:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": 0,
            "candles": [],
            "error": str(exc),
        }
