"""Agent analysis read routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from database.models.engine import get_db

router = APIRouter()


@router.get("/api/agent-analysis/latest")
def api_agent_analysis_latest():
    """返回最新日期的全部 agent 分析结果。"""
    from apps.api import main as api_main
    from database.models.analysis import AgentOutput
    from database.models.engine import SessionLocal

    with SessionLocal() as db:
        latest_date = db.query(func.max(AgentOutput.trade_date)).scalar()
        if not latest_date:
            return api_main._empty_agent_analysis()
        return api_main._build_agent_analysis_response(db, latest_date)


@router.get("/api/agent-analysis")
def api_agent_analysis_by_date(date: str | None = None, run_id: str | None = None):
    """按日期返回 agent 分析结果。"""
    from apps.api import main as api_main
    from database.models.analysis import AgentOutput
    from database.models.engine import SessionLocal

    with SessionLocal() as db:
        if date:
            try:
                target_date = date_type.fromisoformat(date)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid date format: {date}")
        else:
            latest = db.query(func.max(AgentOutput.trade_date)).scalar()
            if not latest:
                return api_main._empty_agent_analysis()
            target_date = latest

        return api_main._build_agent_analysis_response(db, target_date, run_id=run_id)


@router.get("/api/agent-analysis/inspect")
def api_agent_analysis_inspect(
    date: str | None = None,
    run_id: str | None = None,
):
    """返回 Agent 分析的 prompt/input/output 只读检查视图。"""
    from apps.api import main as api_main
    from database.models.analysis import AgentOutput
    from database.models.engine import SessionLocal

    with SessionLocal() as db:
        if date:
            try:
                target_date = date_type.fromisoformat(date)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid date format: {date}")
        else:
            latest = db.query(func.max(AgentOutput.trade_date)).scalar()
            if not latest:
                return {
                    "trade_date": None,
                    "run_id": run_id,
                    "snapshot_id": None,
                    "agents": [],
                    "source": "agent_outputs",
                }
            target_date = latest

        return api_main._build_agent_analysis_inspection(db, target_date, run_id=run_id)


@router.get("/api/agent-analysis/synthesis/latest")
def api_agent_analysis_synthesis_latest(
    date: str | None = None,
    run_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    from apps.api import main as api_main
    from database.models.analysis import AgentOutput

    query = (
        db.query(AgentOutput).filter(AgentOutput.agent_name == "synthesis_agent").order_by(desc(AgentOutput.created_at))
    )
    if run_id:
        query = query.filter(AgentOutput.run_id == run_id)
    if date:
        query = query.filter(AgentOutput.trade_date == date)

    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="No synthesis agent output found")
    return api_main.build_agent_output_summary(row)
