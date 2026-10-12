"""Read-only probability snapshots; requests never launch collection or DDL."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.worker.fedwatch import fedwatch_settings
from database.models.engine import get_db
from apps.api.services.fedwatch_read_model_service import (
    get_fedwatch_factor_history,
    get_latest_fedwatch_factor_view,
)

router = APIRouter(prefix="/api/market/fedwatch", tags=["FedWatch"])


def cutoff(as_of: datetime | None = None):
    value = as_of or datetime.now(UTC)
    if value.tzinfo is None:
        raise HTTPException(422, "as_of requires a timezone")
    if value > datetime.now(UTC):
        raise HTTPException(422, "as_of cannot be in the future")
    return value.astimezone(UTC).isoformat()


def latest_view(db, at):
    try:
        settings = fedwatch_settings()
        return get_latest_fedwatch_factor_view(
            db,
            as_of=at,
            allowed_staleness_seconds=settings["allowed_staleness_seconds"],
        )
    except SQLAlchemyError as exc:
        raise HTTPException(503, "FedWatch storage unavailable; worker initialization required") from exc


@router.get("/latest")
def latest(db: Session = Depends(get_db), at: str = Depends(cutoff)):
    return latest_view(db, at)


@router.get("/health")
def health(db: Session = Depends(get_db), at: str = Depends(cutoff)):
    return latest_view(db, at)["source_health"]


@router.get("/repricing")
def repricing(db: Session = Depends(get_db), at: str = Depends(cutoff)):
    view = latest_view(db, at)
    return {
        "snapshot_id": view["snapshot_id"],
        "as_of": view["as_of"],
        "source_health": view["source_health"],
        "repricing": view["factor"].get("repricing"),
        "source_refs": view["source_refs"],
    }


@router.get("/meetings")
def meetings(db: Session = Depends(get_db), at: str = Depends(cutoff)):
    view = latest_view(db, at)
    return {
        "snapshot_id": view["snapshot_id"],
        "as_of": view["as_of"],
        "source_health": view["source_health"],
        "meetings": view["factor"].get("market_implied_path", {}).get("meetings", []),
        "source_refs": view["source_refs"],
    }


@router.get("/history")
def history(
    meeting_date: date | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    at: str = Depends(cutoff),
):
    try:
        return get_fedwatch_factor_history(
            db,
            meeting_date=meeting_date.isoformat() if meeting_date else None,
            limit=limit,
            as_of=at,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(503, "FedWatch storage unavailable") from exc
