"""TDD: Settings persistence model and repository helpers."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.models.analysis import AppSetting, AppSettingEvent, ensure_analysis_tables
from database.queries.app_settings import (
    get_app_setting,
    list_app_setting_events,
    list_app_settings,
    reset_app_setting,
    upsert_app_setting,
)


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_app_settings_table_is_created_by_analysis_metadata() -> None:
    session = _make_session()

    tables = inspect(session.get_bind()).get_table_names()

    assert "app_settings" in tables
    assert AppSetting.__tablename__ == "app_settings"


def test_upsert_app_setting_persists_value_and_audit_fields() -> None:
    session = _make_session()

    record = upsert_app_setting(
        session,
        setting_key="global.language",
        scope="global",
        value_json={"value": "en-US"},
        actor="codex",
        reason="testing",
        request_id="app-setting-001",
        audit_id="settings-action:preferences:app-setting-001",
    )
    session.commit()

    fetched = get_app_setting(session, "global.language")

    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.scope == "global"
    assert fetched.value_json == {"value": "en-US"}
    assert fetched.updated_by == "codex"
    assert fetched.update_reason == "testing"
    assert fetched.request_id == "app-setting-001"
    assert fetched.audit_id == "settings-action:preferences:app-setting-001"


def test_list_app_settings_returns_saved_source_overlay() -> None:
    session = _make_session()
    upsert_app_setting(
        session,
        setting_key="source.fred.enabled",
        scope="source",
        source_key="fred",
        value_json={"enabled": False},
        actor="codex",
    )
    session.commit()

    rows = list_app_settings(session)

    assert len(rows) == 1
    assert rows[0].setting_key == "source.fred.enabled"
    assert rows[0].source_key == "fred"
    assert rows[0].value_json == {"enabled": False}


def test_app_setting_events_are_recorded_for_set_and_reset() -> None:
    session = _make_session()

    upsert_app_setting(
        session,
        setting_key="global.language",
        scope="global",
        value_json={"value": "en-US"},
        actor="codex",
        request_id="set-001",
        audit_id="settings-action:preferences:set-001",
    )
    reset_app_setting(
        session,
        setting_key="global.language",
        actor="codex",
        request_id="reset-001",
        audit_id="settings-action:preferences-reset:reset-001",
    )
    session.commit()

    rows = list_app_setting_events(session)
    actions = [row.action for row in rows]

    assert AppSettingEvent.__tablename__ == "app_setting_events"
    assert len(rows) == 2
    assert "set" in actions
    assert "reset" in actions
    reset_event = next(row for row in rows if row.action == "reset")
    set_event = next(row for row in rows if row.action == "set")
    assert reset_event.setting_key == "global.language"
    assert reset_event.old_value_json == {"value": "en-US"}
    assert reset_event.new_value_json is None
    assert set_event.setting_key == "global.language"


def test_reset_app_setting_removes_current_overlay() -> None:
    session = _make_session()

    upsert_app_setting(
        session,
        setting_key="source.fred.enabled",
        scope="source",
        source_key="fred",
        value_json={"enabled": False},
        actor="codex",
    )
    session.commit()

    reset_app_setting(session, setting_key="source.fred.enabled", actor="codex")
    session.commit()

    assert get_app_setting(session, "source.fred.enabled") is None
