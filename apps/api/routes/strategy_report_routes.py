"""Strategy/final-report read routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api.schemas.strategy import StrategyAssetListResponse

router = APIRouter()


@router.get("/api/final-report/latest")
def api_final_report_latest():
    """返回最新的 final_report.md 内容。"""
    from apps.api import main as api_main

    data = api_main.get_final_report_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Final report not found")
    return data


@router.get("/api/final-report")
def api_final_report(date: str, run_id: str):
    """按日期和 run_id 返回 final_report.md 内容。"""
    from apps.api import main as api_main

    data = api_main.get_final_report(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Final report not found")
    return data


@router.get("/api/strategy-card/latest")
def api_strategy_card_latest():
    """返回最新的 strategy_card.json + strategy_card.md。"""
    from apps.api import main as api_main

    data = api_main.get_strategy_card_latest()
    if data is None:
        raise HTTPException(status_code=404, detail="Strategy card not found")
    return data


@router.get("/api/strategy-card")
def api_strategy_card(date: str, run_id: str):
    """按日期和 run_id 返回 strategy_card.json + strategy_card.md。"""
    from apps.api import main as api_main

    data = api_main.get_strategy_card(date=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Strategy card not found")
    return data


@router.get("/api/strategy-cards")
def api_strategy_cards(asset: str = "XAUUSD", limit: int = 20):
    """返回策略卡摘要列表，按最新日期排序。"""
    from apps.api import main as api_main

    return api_main.list_strategy_cards(asset=asset, limit=limit)


@router.get("/api/strategy-cards/assets", response_model=StrategyAssetListResponse)
def api_strategy_card_assets() -> StrategyAssetListResponse:
    """返回可用于策略校准的资产列表与样本规模。"""
    from apps.api import main as api_main

    return api_main.list_strategy_assets()


@router.get("/api/strategy-cards/latest")
def api_strategy_cards_latest(asset: str = "XAUUSD"):
    """返回最新策略卡详情（复数 read model）。"""
    from apps.api import main as api_main

    data = api_main.get_strategy_card_read_model_latest(asset=asset)
    if data is None:
        raise HTTPException(status_code=404, detail="Strategy card not found")
    return data


@router.get("/api/strategy-cards/{strategy_card_id}")
def api_strategy_card_detail(strategy_card_id: str, asset: str = "XAUUSD"):
    """按 strategy_card_id / run_id / snapshot_id 返回策略卡详情。"""
    from apps.api import main as api_main

    data = api_main.get_strategy_card_by_id(strategy_card_id, asset=asset)
    if data is None:
        raise HTTPException(status_code=404, detail="Strategy card not found")
    return data
