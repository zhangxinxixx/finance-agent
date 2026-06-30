"""Gold mainline read-model routes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/gold/mainlines/latest")
def api_gold_mainlines_latest():
    """Return the latest gold macro mainline read model."""
    from apps.api import main as api_main

    return api_main.get_gold_mainlines_latest()


@router.get("/api/gold/mainlines")
def api_gold_mainlines(date: str, run_id: str):
    """Return a gold macro mainline read model by date and run_id."""
    from apps.api import main as api_main

    return api_main.get_gold_mainlines(date=date, run_id=run_id)
