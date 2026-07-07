"""Read-only system status helpers for the dashboard compatibility endpoint."""

from __future__ import annotations

import json
import socket
import tomllib
from typing import Any

from sqlalchemy.engine import make_url

from apps.api.services._storage import _PROJECT_ROOT
from database.models.engine import SessionLocal


def get_version() -> str:
    """Read project version from pyproject.toml, fallback to a safe default."""
    try:
        with (_PROJECT_ROOT / "pyproject.toml").open("rb") as file:
            data = tomllib.load(file)
        return data["project"]["version"]
    except Exception:
        return "0.0.0"


def get_phases() -> dict[str, Any]:
    """Read phase status mapping from configs/phases.json."""
    try:
        phases_path = _PROJECT_ROOT / "configs" / "phases.json"
        return json.loads(phases_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def database_reachable(timeout: float = 0.2) -> bool:
    """Avoid long DB hangs in local environments without a database."""
    try:
        bind = SessionLocal.kw.get("bind")
        if bind is None:
            return False

        url = make_url(str(bind.url))
        if not url.drivername.startswith("postgresql"):
            return True
        if not url.host or not url.port:
            return True

        with socket.create_connection((url.host, int(url.port)), timeout=timeout):
            return True
    except OSError:
        return False
    except Exception:
        return True
