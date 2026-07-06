"""Market ticker and monitor routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/market/tickers")
def api_market_tickers():
    """返回市场指标实时快照（XAUUSD/DXY/宏观指标）。"""
    from apps.api import main as api_main

    return api_main.get_market_tickers()


@router.get("/api/market/monitor")
def api_market_monitor():
    """返回市场监控页只读聚合视图。"""
    from apps.api import main as api_main

    return api_main.get_market_monitor_overview()


@router.get("/api/market/monitor/history")
def api_market_monitor_history(limit: int = 30, timeframe: str = "1M"):
    """返回市场监控页历史序列。"""
    from apps.api import main as api_main

    return api_main.get_market_monitor_history(limit=limit, timeframe=timeframe)


@router.get("/api/market/candles")
def api_market_candles(asset: str = "XAUUSD", timeframe: str = "1m", limit: int = 500):
    """返回统一 K 线 read model，包含覆盖率、缺口和来源追踪。"""
    from apps.api.services.market_candle_service import get_market_candles

    return get_market_candles(asset=asset, timeframe=timeframe, limit=limit)
