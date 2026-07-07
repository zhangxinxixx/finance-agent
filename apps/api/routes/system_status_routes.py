"""System status route extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.services import system_status_service
from database.models.engine import get_db
from database.models.task import TaskRun

router = APIRouter()


@router.get("/dashboard/system-status")
def system_status(db: Session = Depends(get_db)) -> dict:
    """返回轻量系统状态摘要（MVP 静态状态，非实时生产监控）。"""
    recent_tasks: list[dict] = []
    db_available = False
    if system_status_service.database_reachable():
        try:
            tasks = db.query(TaskRun).order_by(TaskRun.created_at.desc()).limit(5).all()
            recent_tasks = [
                {
                    "id": str(t.id),
                    "name": t.name,
                    "status": t.status.value,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tasks
            ]
            db_available = True
        except Exception:
            db_available = False

    return {
        "service": "finance-agent",
        "version": system_status_service.get_version(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_available": db_available,
        "recent_tasks": recent_tasks,
        "phases": system_status_service.get_phases(),
        "production_chain": [
            "api",
            "scheduler",
            "worker",
            "collectors",
            "parsers",
            "features",
            "analysis",
            "renderer",
            "output",
        ],
        "limitations": {
            "mvp_readonly": True,
            "no_realtime_monitoring": True,
            "no_raw_file_access_from_frontend": True,
            "no_auto_trading": True,
            "status_from_project_docs": True,
        },
    }
