"""Settings status service should not invent connection states."""

from __future__ import annotations

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.services.settings_service import build_settings_status
from database.models.analysis import ensure_analysis_tables
from database.queries.app_settings import upsert_app_setting
from database.queries.app_secrets import upsert_app_secret


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_settings_keyless_sources_are_unknown_without_local_evidence(monkeypatch, tmp_path):
    for key in ("FRED_API_KEY", "DASHSCOPE_API_KEY", "MEM0_API_KEY", "JIN10_MCP_KEY", "REDIS_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)

    payload = build_settings_status()
    sources = {source["id"]: source for source in payload["sources"]}

    assert sources["openbb"]["status"] == "UNKNOWN"
    assert sources["jin10_mcp"]["status"] == "UNKNOWN"
    assert sources["cme_bulletin"]["status"] == "UNKNOWN"
    assert sources["treasury"]["status"] == "UNKNOWN"
    assert sources["fed_prates"]["status"] == "UNKNOWN"


def test_settings_status_overlays_saved_preferences_and_source_enabled(monkeypatch, tmp_path):
    session = _make_session()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    monkeypatch.delenv("JIN10_MCP_KEY", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.runtime.secret_resolver._PROJECT_ROOT", tmp_path)

    upsert_app_setting(
        session,
        setting_key="global.language",
        scope="global",
        value_json={"value": "en-US"},
        actor="codex",
    )
    upsert_app_setting(
        session,
        setting_key="source.fred.enabled",
        scope="source",
        source_key="fred",
        value_json={"enabled": False},
        actor="codex",
    )
    session.commit()

    payload = build_settings_status(db=session)

    prefs = {item["key"]: item for item in payload["preferences"]}
    sources = {source["id"]: source for source in payload["sources"]}

    assert prefs["language"]["value"] == "en-US"
    assert sources["fred"]["enabled"] is False
    assert sources["fred"]["status"] == "DISCONNECTED"
    assert sources["fred"]["is_overridden"] is True


def test_settings_status_includes_masked_stored_secret(monkeypatch, tmp_path):
    session = _make_session()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.runtime.secret_resolver._PROJECT_ROOT", tmp_path)
    master_key = Fernet.generate_key().decode()
    cipher = Fernet(master_key.encode("utf-8")).encrypt(b"stored-secret").decode("utf-8")
    monkeypatch.setenv("SETTINGS_MASTER_KEY", master_key)

    upsert_app_secret(
        session,
        source_key="fred",
        secret_name="api_key",
        encrypted_value=cipher,
        masked_value="fred****1234",
        actor="codex",
    )
    session.commit()

    payload = build_settings_status(db=session)
    sources = {source["id"]: source for source in payload["sources"]}

    assert sources["fred"]["api_key_masked"] == "fred****1234"
    assert sources["fred"]["secret_configured"] is True
    assert sources["fred"]["secret_last_updated_at"] is not None
    assert sources["fred"]["status"] == "CONNECTED"
