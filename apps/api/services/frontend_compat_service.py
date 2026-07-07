"""Static frontend compatibility helpers shared by legacy routes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.responses import FileResponse, RedirectResponse

from apps.api.services._storage import _PROJECT_ROOT


_FRONTEND_WEB_URL = os.environ.get("FRONTEND_WEB_URL", "http://localhost:8080").rstrip("/")
_FRONTEND_DIST_DIR = Path(
    os.environ.get("FINANCE_AGENT_FRONTEND_DIST_DIR", str(_PROJECT_ROOT / "apps/frontend-web" / "dist"))
)
_FRONTEND_PUBLIC_DIR = Path(
    os.environ.get("FINANCE_AGENT_FRONTEND_PUBLIC_DIR", str(_PROJECT_ROOT / "apps/frontend-web" / "public"))
)


def serve_frontend_entry(request_path: str) -> FileResponse | RedirectResponse:
    index_path = _FRONTEND_DIST_DIR / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)
    return RedirectResponse(url=f"{_FRONTEND_WEB_URL}{request_path}", status_code=307)


def resolve_frontend_asset(asset_path: str) -> Path | None:
    assets_root = (_FRONTEND_DIST_DIR / "assets").resolve()
    candidate = (assets_root / asset_path).resolve()
    if not str(candidate).startswith(str(assets_root)):
        return None
    if not candidate.is_file():
        return None
    return candidate


def resolve_frontend_root_asset(asset_name: str) -> Path | None:
    for root in (_FRONTEND_DIST_DIR, _FRONTEND_PUBLIC_DIR):
        root_resolved = root.resolve()
        candidate = (root_resolved / asset_name).resolve()
        if not str(candidate).startswith(str(root_resolved)):
            continue
        if candidate.is_file():
            return candidate
    return None
