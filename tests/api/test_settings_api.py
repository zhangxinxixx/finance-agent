"""P2-04 Settings write contract tests."""

from __future__ import annotations

from fastapi import HTTPException
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import (
    api_settings_reset_secret,
    api_settings_history,
    api_settings_reset_preferences,
    api_settings_reset_source,
    api_settings_rollback_history_event,
    api_settings_update_secret,
    api_settings_status,
    api_settings_update_preferences,
    api_settings_update_source,
)
from apps.api.schemas.settings import (
    SettingsSecretResetRequest,
    SettingsSecretUpdateRequest,
    SettingsPreferencesResetRequest,
    SettingsPreferencesUpdateRequest,
    SettingsRollbackRequest,
    SettingsSourceResetRequest,
    SettingsSourceUpdateRequest,
)
from database.models.analysis import ensure_analysis_tables


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_settings_preferences_write_is_reflected_in_status(monkeypatch, tmp_path) -> None:
    session = _make_session()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    monkeypatch.delenv("JIN10_MCP_KEY", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)

    response = api_settings_update_preferences(
        body=SettingsPreferencesUpdateRequest(
            language="en-US",
            timezone="UTC",
            report_template="institutional_focus",
            actor="automation",
            reason="normalize analyst defaults",
            request_id="settings-pref-001",
        ),
        db=session,
    )
    payload = api_settings_status(db=session)

    assert response.status == "accepted"
    assert response.audit_id == "settings-action:preferences:settings-pref-001"
    prefs = {item["key"]: item for item in payload["preferences"]}
    assert prefs["language"]["value"] == "en-US"
    assert prefs["timezone"]["value"] == "UTC"
    assert prefs["report_template"]["value"] == "institutional_focus"


def test_settings_source_toggle_overrides_enabled_without_faking_connectivity(monkeypatch, tmp_path) -> None:
    session = _make_session()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.runtime.secret_resolver._PROJECT_ROOT", tmp_path)

    response = api_settings_update_source(
        "fred",
        body=SettingsSourceUpdateRequest(
            enabled=False,
            actor="automation",
            reason="disable unused data source",
            request_id="settings-source-001",
        ),
        db=session,
    )
    payload = api_settings_status(db=session)

    assert response.status == "accepted"
    assert response.audit_id == "settings-action:source:fred:settings-source-001"
    sources = {item["id"]: item for item in payload["sources"]}
    assert sources["fred"]["enabled"] is False
    assert sources["fred"]["status"] == "DISCONNECTED"
    assert sources["fred"]["api_key_masked"] is None


def test_settings_source_update_rejects_unknown_source() -> None:
    session = _make_session()

    try:
        api_settings_update_source(
            "unknown_source",
            body=SettingsSourceUpdateRequest(enabled=True, actor="automation", request_id="settings-source-404"),
            db=session,
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Settings source not found"
        return

    raise AssertionError("Expected HTTPException for unknown settings source")


def test_settings_preferences_reset_restores_defaults_and_history(monkeypatch, tmp_path) -> None:
    session = _make_session()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    monkeypatch.delenv("JIN10_MCP_KEY", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)

    api_settings_update_preferences(
        body=SettingsPreferencesUpdateRequest(
            language="en-US",
            timezone="UTC",
            actor="automation",
            request_id="settings-pref-set-001",
        ),
        db=session,
    )

    response = api_settings_reset_preferences(
        body=SettingsPreferencesResetRequest(
            keys=["language", "timezone"],
            actor="automation",
            reason="rollback to defaults",
            request_id="settings-pref-reset-001",
        ),
        db=session,
    )
    payload = api_settings_status(db=session)
    history = api_settings_history(limit=10, db=session)

    prefs = {item["key"]: item for item in payload["preferences"]}
    assert response.status == "accepted"
    assert response.audit_id == "settings-action:preferences-reset:settings-pref-reset-001"
    assert prefs["language"]["value"] == "zh-CN"
    assert prefs["timezone"]["value"] == "Asia/Shanghai"
    reset_events = [event for event in history.events if event.action == "reset"]
    assert reset_events
    assert reset_events[0].setting_key in {"global.language", "global.timezone"}


def test_settings_source_reset_clears_override(monkeypatch, tmp_path) -> None:
    session = _make_session()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.runtime.secret_resolver._PROJECT_ROOT", tmp_path)

    api_settings_update_source(
        "fred",
        body=SettingsSourceUpdateRequest(
            enabled=False,
            actor="automation",
            request_id="settings-source-set-001",
        ),
        db=session,
    )

    response = api_settings_reset_source(
        "fred",
        body=SettingsSourceResetRequest(actor="automation", request_id="settings-source-reset-001"),
        db=session,
    )
    payload = api_settings_status(db=session)

    sources = {item["id"]: item for item in payload["sources"]}
    assert response.status == "accepted"
    assert response.audit_id == "settings-action:source-reset:fred:settings-source-reset-001"
    assert sources["fred"]["enabled"] is False
    assert sources["fred"]["is_overridden"] is False


def test_settings_history_rollback_restores_previous_source_state(monkeypatch, tmp_path) -> None:
    session = _make_session()
    monkeypatch.setenv("FRED_API_KEY", "fred-runtime-key")
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)

    source_response = api_settings_update_source(
        "fred",
        body=SettingsSourceUpdateRequest(
            enabled=False,
            actor="automation",
            request_id="settings-source-set-rollback-001",
        ),
        db=session,
    )
    rollback_response = api_settings_rollback_history_event(
        source_response.audit_id,
        body=SettingsRollbackRequest(actor="automation", reason="undo source toggle", request_id="settings-rollback-001"),
        db=session,
    )
    payload = api_settings_status(db=session)
    history = api_settings_history(limit=10, db=session)

    sources = {item["id"]: item for item in payload["sources"]}
    assert rollback_response.status == "accepted"
    assert rollback_response.rolled_back_audit_id == source_response.audit_id
    assert sources["fred"]["enabled"] is True
    assert sources["fred"]["is_overridden"] is False
    assert any(event.action == "rollback" and event.audit_id == rollback_response.audit_id for event in history.events)


def test_settings_history_rollback_restores_previous_preference_value(monkeypatch, tmp_path) -> None:
    session = _make_session()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    monkeypatch.delenv("JIN10_MCP_KEY", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)

    api_settings_update_preferences(
        body=SettingsPreferencesUpdateRequest(
            language="en-US",
            timezone="UTC",
            actor="automation",
            request_id="settings-pref-set-rollback-001",
        ),
        db=session,
    )
    reset_response = api_settings_reset_preferences(
        body=SettingsPreferencesResetRequest(
            keys=["language"],
            actor="automation",
            reason="reset language to default",
            request_id="settings-pref-reset-rollback-001",
        ),
        db=session,
    )
    rollback_response = api_settings_rollback_history_event(
        reset_response.audit_id,
        body=SettingsRollbackRequest(actor="automation", reason="undo language reset", request_id="settings-rollback-002"),
        db=session,
    )
    payload = api_settings_status(db=session)
    history = api_settings_history(limit=10, db=session)

    prefs = {item["key"]: item for item in payload["preferences"]}
    assert rollback_response.status == "accepted"
    assert rollback_response.rolled_back_audit_id == reset_response.audit_id
    assert prefs["language"]["value"] == "en-US"
    assert any(event.action == "rollback" and event.audit_id == rollback_response.audit_id for event in history.events)


def test_settings_history_rollback_rejects_secret_events(monkeypatch, tmp_path) -> None:
    session = _make_session()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("SETTINGS_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)

    secret_response = api_settings_update_secret(
        "fred",
        body=SettingsSecretUpdateRequest(
            secret_value="fred-secret-1234",
            actor="automation",
            request_id="settings-secret-rollback-blocked-001",
        ),
        db=session,
    )

    try:
        api_settings_rollback_history_event(
            secret_response.audit_id,
            body=SettingsRollbackRequest(actor="automation", request_id="settings-secret-rollback-blocked-001"),
            db=session,
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "Secret rollback is not supported; re-enter the secret instead"
        return

    raise AssertionError("Expected HTTPException for secret rollback")


def test_settings_history_supports_scope_action_and_actor_filters(monkeypatch, tmp_path) -> None:
    session = _make_session()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    monkeypatch.delenv("JIN10_MCP_KEY", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)

    api_settings_update_preferences(
        body=SettingsPreferencesUpdateRequest(
            language="en-US",
            actor="automation",
            request_id="settings-pref-filter-001",
        ),
        db=session,
    )
    api_settings_update_source(
        "fred",
        body=SettingsSourceUpdateRequest(
            enabled=False,
            actor="automation",
            request_id="settings-source-filter-001",
        ),
        db=session,
    )

    source_history = api_settings_history(limit=10, scope="source", actor="automation", db=session)
    set_history = api_settings_history(limit=10, action="set", setting_key="source.fred.enabled", db=session)

    assert all(event.scope == "source" for event in source_history.events)
    assert all(event.actor == "automation" for event in source_history.events)
    assert len(set_history.events) == 1
    assert set_history.events[0].setting_key == "source.fred.enabled"


def test_settings_secret_write_is_masked_in_status_and_kept_off_runtime_env(monkeypatch, tmp_path) -> None:
    session = _make_session()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("SETTINGS_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.runtime.secret_resolver._PROJECT_ROOT", tmp_path)

    response = api_settings_update_secret(
        "fred",
        body=SettingsSecretUpdateRequest(
            secret_value="fred-secret-1234",
            actor="automation",
            reason="configure fred key",
            request_id="settings-secret-001",
        ),
        db=session,
    )
    payload = api_settings_status(db=session)

    sources = {item["id"]: item for item in payload["sources"]}
    assert response.status == "accepted"
    assert response.audit_id == "settings-action:secret:fred:settings-secret-001"
    assert sources["fred"]["api_key_masked"] == "fred****1234"
    assert sources["fred"]["secret_configured"] is True
    assert sources["fred"]["secret_last_updated_at"] is not None
    assert sources["fred"]["status"] == "CONNECTED"


def test_settings_secret_write_requires_master_key(monkeypatch) -> None:
    session = _make_session()
    monkeypatch.delenv("SETTINGS_MASTER_KEY", raising=False)

    try:
        api_settings_update_secret(
            "fred",
            body=SettingsSecretUpdateRequest(secret_value="fred-secret-1234", actor="automation", request_id="secret-no-key"),
            db=session,
        )
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail == "Settings secret storage is not configured"
        return

    raise AssertionError("Expected HTTPException when secret storage key is missing")


def test_settings_secret_write_rejects_blank_value(monkeypatch) -> None:
    session = _make_session()
    monkeypatch.setenv("SETTINGS_MASTER_KEY", Fernet.generate_key().decode())

    try:
        api_settings_update_secret(
            "fred",
            body=SettingsSecretUpdateRequest(secret_value="   ", actor="automation", request_id="secret-blank-001"),
            db=session,
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "Secret value must not be empty"
        return

    raise AssertionError("Expected HTTPException for blank secret value")


def test_settings_secret_reset_clears_stored_secret(monkeypatch, tmp_path) -> None:
    session = _make_session()
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("SETTINGS_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr("apps.api.services.settings_service._PROJECT_ROOT", tmp_path)

    api_settings_update_secret(
        "fred",
        body=SettingsSecretUpdateRequest(secret_value="fred-secret-1234", actor="automation", request_id="secret-set-001"),
        db=session,
    )
    response = api_settings_reset_secret(
        "fred",
        body=SettingsSecretResetRequest(actor="automation", request_id="secret-reset-001"),
        db=session,
    )
    payload = api_settings_status(db=session)

    sources = {item["id"]: item for item in payload["sources"]}
    assert response.status == "accepted"
    assert response.audit_id == "settings-action:secret-reset:fred:secret-reset-001"
    assert sources["fred"]["secret_configured"] is False
    assert sources["fred"]["api_key_masked"] is None
