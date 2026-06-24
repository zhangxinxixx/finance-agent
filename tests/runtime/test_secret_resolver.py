"""Runtime secret resolution tests."""

from __future__ import annotations

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.collectors.jin10.mcp_client import Jin10MCPClient
from apps.runtime.secret_resolver import resolve_runtime_secret
from database.models.analysis import ensure_analysis_tables
from database.queries.app_secrets import upsert_app_secret


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_resolve_runtime_secret_prefers_env_over_db(monkeypatch) -> None:
    session = _make_session()
    master_key = Fernet.generate_key().decode()
    cipher = Fernet(master_key.encode("utf-8")).encrypt(b"db-secret").decode("utf-8")
    upsert_app_secret(
        session,
        source_key="jin10_mcp",
        secret_name="api_key",
        encrypted_value=cipher,
        masked_value="jin10****cret",
    )
    session.commit()

    monkeypatch.setenv("SETTINGS_MASTER_KEY", master_key)
    monkeypatch.setenv("JIN10_MCP_KEY", "env-secret")

    assert resolve_runtime_secret("JIN10_MCP_KEY", session=session) == "env-secret"


def test_resolve_runtime_secret_falls_back_to_db_secret(monkeypatch) -> None:
    session = _make_session()
    master_key = Fernet.generate_key().decode()
    cipher = Fernet(master_key.encode("utf-8")).encrypt(b"stored-secret").decode("utf-8")
    upsert_app_secret(
        session,
        source_key="jin10_mcp",
        secret_name="api_key",
        encrypted_value=cipher,
        masked_value="jin10****cret",
    )
    session.commit()

    monkeypatch.setenv("SETTINGS_MASTER_KEY", master_key)
    monkeypatch.delenv("JIN10_MCP_KEY", raising=False)
    monkeypatch.setattr("apps.runtime.secret_resolver.dotenv_values", lambda *_args, **_kwargs: {})

    assert resolve_runtime_secret("JIN10_MCP_KEY", session=session) == "stored-secret"


def test_resolve_runtime_secret_supports_fred_db_secret(monkeypatch) -> None:
    session = _make_session()
    master_key = Fernet.generate_key().decode()
    cipher = Fernet(master_key.encode("utf-8")).encrypt(b"fred-db-secret").decode("utf-8")
    upsert_app_secret(
        session,
        source_key="fred",
        secret_name="api_key",
        encrypted_value=cipher,
        masked_value="fred****cret",
    )
    session.commit()

    monkeypatch.setenv("SETTINGS_MASTER_KEY", master_key)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr("apps.runtime.secret_resolver.dotenv_values", lambda *_args, **_kwargs: {})

    assert resolve_runtime_secret("FRED_API_KEY", session=session) == "fred-db-secret"


def test_jin10_client_uses_runtime_secret_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.collectors.jin10.mcp_client.resolve_runtime_secret",
        lambda secret_env: "client-secret" if secret_env == "JIN10_MCP_KEY" else None,
    )

    client = Jin10MCPClient()
    try:
        assert client._mcp_key == "client-secret"
    finally:
        client.close()
