"""Event flow routes extracted from the main FastAPI entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.schemas.event_flow import EventFlowActionRequest, EventFlowActionResponse, EventFlowBriefLinkRequest
from database.models.engine import get_db

router = APIRouter()


@router.get("/api/events/flow/overview")
def api_event_flow_overview():
    """返回事件流只读 overview（Jin10 快讯 + 财经日历 + 文章）。"""
    from apps.api.services.event_flow_service import build_event_flow_overview

    return build_event_flow_overview()


@router.get("/api/events/briefs")
def api_event_flow_briefs():
    """返回事件流当日快讯 / 金十文章只读 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_briefs

    return build_event_flow_briefs()


@router.get("/api/events")
def api_event_flow_events():
    """返回事件流事件列表只读 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_events

    return build_event_flow_events()


@router.get("/api/events/report-inputs")
def api_event_flow_report_inputs():
    """返回事件流报告输入只读 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_report_inputs

    return build_event_flow_report_inputs()


@router.get("/api/events/{event_id}")
def api_event_flow_event_detail(event_id: str):
    """返回单条事件详情 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_event_detail

    data = build_event_flow_event_detail(event_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return data


@router.get("/api/events/{event_id}/impact")
def api_event_flow_event_impact(event_id: str):
    """返回单条事件影响分析 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_impact

    data = build_event_flow_impact(event_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return data


@router.get("/api/events/{event_id}/market-reaction")
def api_event_flow_event_market_reaction(event_id: str):
    """返回单条事件行情反应 read model。"""
    from apps.api.services.event_flow_service import build_event_flow_market_reaction

    data = build_event_flow_market_reaction(event_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return data


@router.post("/api/events/briefs/{brief_id}/link", response_model=EventFlowActionResponse)
def api_event_flow_brief_link(
    brief_id: str,
    body: EventFlowBriefLinkRequest,
    db: Session = Depends(get_db),
) -> EventFlowActionResponse:
    """登记 brief -> event 归并请求。"""
    from apps.api import main as api_main

    return api_main.event_flow_action_service.register_brief_link(db, brief_id, body)


@router.post("/api/events/briefs/{brief_id}/ignore", response_model=EventFlowActionResponse)
def api_event_flow_brief_ignore(
    brief_id: str,
    body: EventFlowActionRequest,
    db: Session = Depends(get_db),
) -> EventFlowActionResponse:
    """登记 brief 忽略请求。"""
    from apps.api import main as api_main

    return api_main.event_flow_action_service.register_brief_ignore(db, brief_id, body)


@router.post("/api/events/report-inputs/{input_id}/include", response_model=EventFlowActionResponse)
def api_event_flow_report_input_include(
    input_id: str,
    body: EventFlowActionRequest,
    db: Session = Depends(get_db),
) -> EventFlowActionResponse:
    """登记 report input 纳入请求。"""
    from apps.api import main as api_main

    return api_main.event_flow_action_service.register_report_input_include(db, input_id, body)


@router.post("/api/events/report-inputs/{input_id}/exclude", response_model=EventFlowActionResponse)
def api_event_flow_report_input_exclude(
    input_id: str,
    body: EventFlowActionRequest,
    db: Session = Depends(get_db),
) -> EventFlowActionResponse:
    """登记 report input 排除请求。"""
    from apps.api import main as api_main

    return api_main.event_flow_action_service.register_report_input_exclude(db, input_id, body)


@router.post("/api/events/{event_id}/review", response_model=EventFlowActionResponse)
def api_event_flow_event_review(
    event_id: str,
    body: EventFlowActionRequest,
    db: Session = Depends(get_db),
) -> EventFlowActionResponse:
    """登记单事件人工复核请求。"""
    from apps.api import main as api_main

    return api_main.event_flow_action_service.register_event_review(db, event_id, body)
