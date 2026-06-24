"""Runtime secret resolution for stored settings-managed credentials.

Secret writes land in ``app_secrets`` encrypted storage. Runtime consumers may
prefer process env, but can explicitly fall back to DB-backed secrets when the
env var is absent.
"""

from __future__ import annotations

import logging
import os
from contextlib import suppress
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values
from sqlalchemy.orm import Session

from database.models.engine import SessionLocal
from database.queries.app_secrets import get_app_secret


logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_SECRET_ENV_TO_SOURCE_KEY: dict[str, str] = {
    "DASHSCOPE_API_KEY": "dashscope",
    "FRED_API_KEY": "fred",
    "JIN10_MCP_KEY": "jin10_mcp",
    "MEM0_API_KEY": "mem0",
}


def resolve_runtime_secret(secret_env: str, *, session: Session | None = None) -> str | None:
    """Resolve a runtime secret with env-first, DB-backed fallback.

    The helper never exposes plaintext unless the caller explicitly asks for
    the returned value. If neither env nor DB secret is available, ``None`` is
    returned.
    """

    env_value = (os.getenv(secret_env) or "").strip()
    if not env_value:
        env_path = _PROJECT_ROOT / ".env"
        if env_path.exists():
            env_value = str(dotenv_values(str(env_path)).get(secret_env) or "").strip()
    if env_value:
        return env_value

    source_key = _SECRET_ENV_TO_SOURCE_KEY.get(secret_env)
    if source_key is None:
        return None

    master_key = _get_settings_master_key()
    if not master_key:
        return None

    if session is not None:
        return _load_secret_from_session(session, source_key, master_key)

    try:
        with SessionLocal() as db:
            return _load_secret_from_session(db, source_key, master_key)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.debug("Runtime secret lookup failed for %s: %s", secret_env, exc)
        return None


def _load_secret_from_session(session: Session, source_key: str, master_key: str) -> str | None:
    secret = get_app_secret(session, source_key)
    if secret is None or not secret.encrypted_value:
        return None

    with suppress(Exception):
        fernet = Fernet(master_key.encode("utf-8"))
        decrypted = fernet.decrypt(secret.encrypted_value.encode("utf-8")).decode("utf-8")
        return decrypted.strip() or None
    return None


def _get_settings_master_key() -> str:
    key = (os.getenv("SETTINGS_MASTER_KEY") or "").strip()
    if key:
        return key

    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return ""

    values = dotenv_values(str(env_path))
    return str(values.get("SETTINGS_MASTER_KEY") or "").strip()
