"""Market odds routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api.data_service import get_market_odds_report, get_market_odds_snapshot
from apps.api.schemas.market_odds_evidence import MarketOddsEvidenceViewModel
from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.report_market_odds_service import load_latest_report_market_odds_view

router = APIRouter()


@router.get("/api/market-odds/snapshot")
def api_market_odds_snapshot(date: str | None = None, run_id: str | None = None):
    """返回 market_odds section from analysis snapshot."""
    data = get_market_odds_snapshot(date_str=date, run_id=run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Market odds snapshot not found")
    return data


@router.get("/api/market-odds/report")
def api_market_odds_report(date: str | None = None, run_id: str | None = None):
    """返回 market_odds 结构化报告摘要。无数据时返回 unavailable 状态而非 404."""
    return get_market_odds_report(date_str=date, run_id=run_id)


@router.get("/api/market-odds/external/latest", response_model=MarketOddsEvidenceViewModel)
def api_latest_external_market_odds():
    """Return the latest Jin10 external-odds read model for first-level monitoring."""
    view = load_latest_report_market_odds_view(storage_root=_PROJECT_ROOT / "storage")
    if view is None:
        raise HTTPException(status_code=404, detail="External market odds evidence not found")
    return view
