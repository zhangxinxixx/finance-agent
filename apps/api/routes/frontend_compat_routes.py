"""Frontend compatibility and static asset routes extracted from the main entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/assets/{asset_path:path}")
def serve_frontend_asset(asset_path: str) -> FileResponse:
    from apps.api import main as api_main

    asset = api_main._resolve_frontend_asset(asset_path)
    if asset is None:
        raise HTTPException(status_code=404, detail="Frontend asset not found")
    return FileResponse(asset)


@router.get("/favicon.svg")
def serve_frontend_favicon() -> FileResponse:
    from apps.api import main as api_main

    asset = api_main._resolve_frontend_root_asset("favicon.svg")
    if asset is None:
        raise HTTPException(status_code=404, detail="Frontend favicon not found")
    return FileResponse(asset, media_type="image/svg+xml")


@router.get("/dashboard")
def serve_dashboard():
    """本地稳定模式优先直接提供前端构建产物；dist 缺失时回退到 Vite。"""
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/dashboard")


@router.get("/dashboard/analysis")
def serve_dashboard_analysis():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/dashboard/analysis")


@router.get("/data-ingestion")
def serve_data_ingestion():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/data-ingestion")


@router.get("/data-sources/{path:path}")
def serve_data_sources_subpath(path: str):
    from apps.api import main as api_main

    return api_main._serve_frontend_entry(f"/data-sources/{path}")


@router.get("/market-monitor")
def serve_market_monitor():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/market-monitor")


@router.get("/cme-options")
def serve_cme_options():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/cme-options")


@router.get("/reports")
def serve_reports():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/reports")


@router.get("/reports/{path:path}")
def serve_reports_subpath(path: str):
    from apps.api import main as api_main

    return api_main._serve_frontend_entry(f"/reports/{path}")


@router.get("/event-flow")
def serve_event_flow():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/event-flow")


@router.get("/event-flow/{path:path}")
def serve_event_flow_subpath(path: str):
    from apps.api import main as api_main

    return api_main._serve_frontend_entry(f"/event-flow/{path}")


@router.get("/knowledge-base")
def serve_knowledge_base():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/knowledge-base")


@router.get("/agent-tasks")
def serve_agent_tasks():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/scheduler")


@router.get("/scheduler")
def serve_scheduler():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/scheduler")


@router.get("/scheduler/{path:path}")
def serve_scheduler_subpath(path: str):
    from apps.api import main as api_main

    return api_main._serve_frontend_entry(f"/scheduler/{path}")


@router.get("/agent-tasks/{path:path}")
def serve_agent_tasks_subpath(path: str):
    from apps.api import main as api_main

    return api_main._serve_frontend_entry(f"/agent-tasks/{path}")


@router.get("/review-center")
def serve_review_center():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/review-center")


@router.get("/settings")
def serve_settings():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/settings")


@router.get("/settings/audit")
def serve_settings_audit():
    from apps.api import main as api_main

    return api_main._serve_frontend_entry("/settings/audit")
