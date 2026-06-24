"""
P2-04: Settings read/write service.

Non-sensitive preferences, source enable/disable requests, and encrypted secret
storage metadata are writable. Runtime connectivity still comes from local
env/evidence and stored secrets are never returned in plaintext.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from apps.api.schemas.settings import (
    SettingsActionResponse,
    SettingsHistoryEvent,
    SettingsHistoryResponse,
    SettingsPreferencesResetRequest,
    SettingsPreferencesUpdateRequest,
    SettingsRollbackRequest,
    SettingsSecretResetRequest,
    SettingsSecretUpdateRequest,
    SettingsSourceResetRequest,
    SettingsSourceUpdateRequest,
)
from apps.api.services._storage import _PROJECT_ROOT
from apps.runtime.secret_resolver import resolve_runtime_secret
from database.models.analysis import AppSetting, AppSettingEvent
from database.queries.app_secrets import get_app_secret, reset_app_secret, upsert_app_secret
from database.queries.app_settings import (
    get_app_setting_event_by_audit_id,
    list_app_setting_events,
    list_app_settings,
    reset_app_setting,
    rollback_app_setting,
    upsert_app_setting,
)


class SettingsValidationError(ValueError):
    """Raised when a settings write request is invalid."""


class SettingsSourceNotFoundError(LookupError):
    """Raised when a source toggle targets an unknown settings source."""


class SettingsSecretStorageNotConfiguredError(RuntimeError):
    """Raised when encrypted secret storage is not configured."""


class SettingsHistoryEventNotFoundError(LookupError):
    """Raised when a rollback targets an unknown history event."""


@dataclass(frozen=True)
class PreferenceDefinition:
    key: str
    label: str
    default: str
    options: tuple[str, ...]


_PREFERENCES: tuple[PreferenceDefinition, ...] = (
    PreferenceDefinition("language", "语言", "zh-CN", ("zh-CN", "en-US")),
    PreferenceDefinition("timezone", "时区", "Asia/Shanghai", ("Asia/Shanghai", "UTC")),
    PreferenceDefinition("report_template", "报告模板", "standard", ("standard", "institutional_focus")),
)

_PREFERENCE_BY_KEY = {item.key: item for item in _PREFERENCES}

_SOURCE_META: dict[str, dict[str, str | None]] = {
    "fred": {"name": "FRED API", "description": "美联储经济数据 (FRED)", "secret_env": "FRED_API_KEY"},
    "openbb": {"name": "OpenBB SDK", "description": "聚合数据平台", "secret_env": None},
    "jin10_mcp": {"name": "Jin10 MCP", "description": "金十数据 MCP 服务", "secret_env": "JIN10_MCP_KEY"},
    "cme_bulletin": {"name": "CME Daily Bulletin", "description": "CME 官方每日公告 PDF", "secret_env": None},
    "treasury": {"name": "Treasury FiscalData", "description": "美国财政部财政数据 API", "secret_env": None},
    "fed_prates": {"name": "Fed PRATES", "description": "美联储准备金利率数据", "secret_env": None},
    "dashscope": {"name": "DashScope (Qwen-VL)", "description": "阿里云视觉模型 (Jin10 解析)", "secret_env": "DASHSCOPE_API_KEY"},
    "mem0": {"name": "Mem0 记忆层", "description": "项目记忆与上下文", "secret_env": "MEM0_API_KEY"},
}

_SECRET_BACKED_SOURCES = {"fred", "dashscope", "mem0"}
_EVIDENCE_BACKED_SOURCES = {"openbb", "jin10_mcp", "cme_bulletin", "treasury", "fed_prates"}


def build_settings_status(*, db: Session | None = None) -> dict[str, Any]:
    """返回设置状态，runtime status 优先看可用 secret 解析结果，writable overlay 来自 DB。"""
    records = list_app_settings(db) if db is not None else []
    secret_records = _build_secret_records(db)
    preference_overlays = _build_preference_overlays(records)
    source_overlays = _build_source_overlays(records)
    return {
        "status": "available",
        "source": "local_env",
        "preferences": _collect_preferences(preference_overlays),
        "sources": _collect_source_status(source_overlays, secret_records, db),
        "global_config": _collect_global_config(),
        "system_info": _collect_system_info(),
        "source_refs": [],
    }


def build_settings_history(
    db: Session,
    *,
    limit: int = 50,
    setting_key: str | None = None,
    source_key: str | None = None,
    scope: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    q: str | None = None,
    days: int | None = None,
) -> SettingsHistoryResponse:
    since = datetime.now(UTC) - timedelta(days=days) if days is not None else None
    events = [
        SettingsHistoryEvent(
            setting_key=item.setting_key,
            scope=item.scope,
            source_key=item.source_key,
            action=item.action,
            old_value_json=item.old_value_json,
            new_value_json=item.new_value_json,
            actor=item.actor,
            reason=item.reason,
            request_id=item.request_id,
            audit_id=item.audit_id,
            created_at=item.created_at,
        )
        for item in list_app_setting_events(
            db,
            limit=min(limit, 200),
            setting_key=setting_key,
            source_key=source_key,
            scope=scope,
            action=action,
            actor=actor,
            q=q,
            since=since,
        )
    ]
    return SettingsHistoryResponse(events=events, total=len(events))


def update_preferences(db: Session, body: SettingsPreferencesUpdateRequest) -> SettingsActionResponse:
    updates = {
        key: value
        for key, value in (
            ("language", body.language),
            ("timezone", body.timezone),
            ("report_template", body.report_template),
        )
        if value is not None
    }
    if not updates:
        raise SettingsValidationError("No settings preference updates provided")

    for key, value in updates.items():
        _validate_preference_value(key, value)

    request_id = body.request_id or "preferences"
    audit_id = f"settings-action:preferences:{request_id}"
    last_record: AppSetting | None = None
    for key, value in updates.items():
        last_record = upsert_app_setting(
            db,
            setting_key=f"global.{key}",
            scope="global",
            value_json={"value": value},
            actor=body.actor,
            reason=body.reason,
            request_id=body.request_id,
            audit_id=audit_id,
        )
    db.commit()
    if last_record is not None:
        db.refresh(last_record)
    return SettingsActionResponse(
        status="accepted",
        audit_id=audit_id,
        updated_keys=sorted(updates.keys()),
        updated_at=last_record.updated_at if last_record is not None else None,
    )


def update_source_enabled(db: Session, source_key: str, body: SettingsSourceUpdateRequest) -> SettingsActionResponse:
    if source_key not in _SOURCE_META:
        raise SettingsSourceNotFoundError(source_key)

    request_id = body.request_id or "source-toggle"
    audit_id = f"settings-action:source:{source_key}:{request_id}"
    record = upsert_app_setting(
        db,
        setting_key=f"source.{source_key}.enabled",
        scope="source",
        source_key=source_key,
        value_json={"enabled": body.enabled},
        actor=body.actor,
        reason=body.reason,
        request_id=body.request_id,
        audit_id=audit_id,
    )
    db.commit()
    db.refresh(record)
    return SettingsActionResponse(
        status="accepted",
        audit_id=audit_id,
        updated_keys=[record.setting_key],
        source_key=source_key,
        enabled=body.enabled,
        updated_at=record.updated_at,
    )


def reset_preferences(db: Session, body: SettingsPreferencesResetRequest) -> SettingsActionResponse:
    keys = body.keys or [item.key for item in _PREFERENCES]
    for key in keys:
        if key not in _PREFERENCE_BY_KEY:
            raise SettingsValidationError(f"Unsupported settings preference: {key}")

    request_id = body.request_id or "preferences-reset"
    audit_id = f"settings-action:preferences-reset:{request_id}"
    updated_keys: list[str] = []
    for key in keys:
        was_reset = reset_app_setting(
            db,
            setting_key=f"global.{key}",
            actor=body.actor,
            reason=body.reason,
            request_id=body.request_id,
            audit_id=audit_id,
        )
        if was_reset:
            updated_keys.append(key)
    db.commit()
    return SettingsActionResponse(
        status="accepted",
        audit_id=audit_id,
        updated_keys=sorted(updated_keys),
    )


def reset_source_enabled(db: Session, source_key: str, body: SettingsSourceResetRequest) -> SettingsActionResponse:
    if source_key not in _SOURCE_META:
        raise SettingsSourceNotFoundError(source_key)

    request_id = body.request_id or "source-reset"
    audit_id = f"settings-action:source-reset:{source_key}:{request_id}"
    reset_app_setting(
        db,
        setting_key=f"source.{source_key}.enabled",
        actor=body.actor,
        reason=body.reason,
        request_id=body.request_id,
        audit_id=audit_id,
    )
    db.commit()
    return SettingsActionResponse(
        status="accepted",
        audit_id=audit_id,
        updated_keys=[f"source.{source_key}.enabled"],
        source_key=source_key,
    )


def update_secret(db: Session, source_key: str, body: SettingsSecretUpdateRequest) -> SettingsActionResponse:
    meta = _SOURCE_META.get(source_key)
    if meta is None:
        raise SettingsSourceNotFoundError(source_key)
    if meta["secret_env"] is None:
        raise SettingsValidationError(f"Source does not support secret write: {source_key}")
    secret_value = body.secret_value.strip()
    if not secret_value:
        raise SettingsValidationError("Secret value must not be empty")

    encrypted_value = _encrypt_secret(secret_value)
    masked_value = _mask(secret_value)
    request_id = body.request_id or "secret-write"
    audit_id = f"settings-action:secret:{source_key}:{request_id}"
    old_secret = get_app_secret(db, source_key)
    record = upsert_app_secret(
        db,
        source_key=source_key,
        secret_name="api_key",
        encrypted_value=encrypted_value,
        masked_value=masked_value or "***",
        actor=body.actor,
        reason=body.reason,
        request_id=body.request_id,
        audit_id=audit_id,
    )
    _record_secret_event(
        db,
        source_key=source_key,
        old_masked=old_secret.masked_value if old_secret is not None else None,
        new_masked=record.masked_value,
        actor=body.actor,
        reason=body.reason,
        request_id=body.request_id,
        audit_id=audit_id,
        action="set",
    )
    db.commit()
    db.refresh(record)
    return SettingsActionResponse(
        status="accepted",
        audit_id=audit_id,
        updated_keys=[f"secret.{source_key}.api_key"],
        source_key=source_key,
        updated_at=record.updated_at,
    )


def reset_secret(db: Session, source_key: str, body: SettingsSecretResetRequest) -> SettingsActionResponse:
    meta = _SOURCE_META.get(source_key)
    if meta is None:
        raise SettingsSourceNotFoundError(source_key)
    if meta["secret_env"] is None:
        raise SettingsValidationError(f"Source does not support secret reset: {source_key}")

    request_id = body.request_id or "secret-reset"
    audit_id = f"settings-action:secret-reset:{source_key}:{request_id}"
    old_secret = get_app_secret(db, source_key)
    reset_app_secret(db, source_key)
    _record_secret_event(
        db,
        source_key=source_key,
        old_masked=old_secret.masked_value if old_secret is not None else None,
        new_masked=None,
        actor=body.actor,
        reason=body.reason,
        request_id=body.request_id,
        audit_id=audit_id,
        action="reset",
    )
    db.commit()
    return SettingsActionResponse(
        status="accepted",
        audit_id=audit_id,
        updated_keys=[f"secret.{source_key}.api_key"],
        source_key=source_key,
    )


def rollback_settings_event(db: Session, audit_id: str, body: SettingsRollbackRequest) -> SettingsActionResponse:
    event = get_app_setting_event_by_audit_id(db, audit_id)
    if event is None:
        raise SettingsHistoryEventNotFoundError(audit_id)
    if event.scope == "secret" or event.setting_key.startswith("secret."):
        raise SettingsValidationError("Secret rollback is not supported; re-enter the secret instead")
    if not event.setting_key.startswith(("global.", "source.")):
        raise SettingsValidationError(f"Rollback is not supported for setting: {event.setting_key}")

    request_id = body.request_id or f"rollback-{audit_id}"
    rollback_audit_id = f"settings-action:rollback:{audit_id}:{request_id}"
    restored_value = event.old_value_json
    if restored_value is None:
        rolled_back_record = rollback_app_setting(
            db,
            setting_key=event.setting_key,
            scope=event.scope,
            source_key=event.source_key,
            value_json=None,
            actor=body.actor,
            reason=body.reason,
            request_id=body.request_id,
            audit_id=rollback_audit_id,
        )
    else:
        rolled_back_record = rollback_app_setting(
            db,
            setting_key=event.setting_key,
            scope=event.scope,
            source_key=event.source_key,
            value_json=restored_value,
            actor=body.actor,
            reason=body.reason,
            request_id=body.request_id,
            audit_id=rollback_audit_id,
        )
    db.commit()
    updated_at = rolled_back_record.updated_at if rolled_back_record is not None else None
    return SettingsActionResponse(
        status="accepted",
        audit_id=rollback_audit_id,
        rolled_back_audit_id=audit_id,
        updated_keys=[event.setting_key],
        source_key=event.source_key,
        updated_at=updated_at,
    )


def _collect_source_status(
    source_overlays: dict[str, bool],
    secret_records: dict[str, dict[str, Any]],
    db: Session | None,
) -> list[dict[str, Any]]:
    openbb_available = _has_local_evidence("storage/features/macro") or _has_local_evidence("storage/outputs/macro")
    jin10_available = _runtime_secret_available("JIN10_MCP_KEY", db=db) or _has_local_evidence("storage/outputs/jin10")
    cme_available = _has_local_evidence("storage/raw/cme")
    macro_available = _has_local_evidence("storage/features/macro") or _has_local_evidence("storage/outputs/macro")
    actual_enabled = {
        "fred": _runtime_secret_available("FRED_API_KEY", db=db),
        "openbb": openbb_available,
        "jin10_mcp": jin10_available,
        "cme_bulletin": cme_available,
        "treasury": macro_available,
        "fed_prates": macro_available,
        "dashscope": _runtime_secret_available("DASHSCOPE_API_KEY", db=db),
        "mem0": _runtime_secret_available("MEM0_API_KEY", db=db),
    }

    return [
        {
            "id": source_key,
            "name": meta["name"],
            "description": meta["description"],
            "enabled": source_overlays.get(source_key, actual_enabled[source_key]),
            "default_enabled": actual_enabled[source_key],
            "is_overridden": source_key in source_overlays,
            "status": _resolve_source_status(
                source_key=source_key,
                enabled=source_overlays.get(source_key, actual_enabled[source_key]),
                actual_enabled=actual_enabled[source_key],
                explicit_override=source_key in source_overlays,
            ),
            "api_key_masked": _resolve_secret_mask(source_key, meta, secret_records),
            "secret_configured": _resolve_secret_configured(source_key, meta, secret_records),
            "secret_last_updated_at": secret_records.get(source_key, {}).get("updated_at"),
            "secret_writable": meta["secret_env"] is not None,
        }
        for source_key, meta in _SOURCE_META.items()
    ]


def _has_local_evidence(path_rel: str) -> bool:
    path = _PROJECT_ROOT / path_rel
    return path.exists() and any(path.iterdir()) if path.is_dir() else path.exists()


def _runtime_secret_available(secret_env: str, *, db: Session | None) -> bool:
    if db is not None:
        return bool(resolve_runtime_secret(secret_env, session=db))
    return bool(os.getenv(secret_env))


def _resolve_source_status(
    *,
    source_key: str,
    enabled: bool,
    actual_enabled: bool,
    explicit_override: bool,
) -> str:
    if explicit_override and not enabled:
        return "DISCONNECTED"
    if source_key in _SECRET_BACKED_SOURCES:
        return "CONNECTED" if actual_enabled and enabled else "DISCONNECTED"
    if source_key in _EVIDENCE_BACKED_SOURCES:
        return "CONNECTED" if actual_enabled and enabled else ("DISCONNECTED" if explicit_override and not enabled else "UNKNOWN")
    return "CONNECTED" if actual_enabled and enabled else "UNKNOWN"


def _collect_preferences(overlays: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "key": item.key,
            "label": item.label,
            "value": overlays.get(item.key, item.default),
            "options": list(item.options),
        }
        for item in _PREFERENCES
    ]


def _collect_global_config() -> list[dict[str, str]]:
    db_url = os.getenv("DATABASE_URL", "")
    return [
        {"label": "PostgreSQL", "value": "127.0.0.1:5432" if "5432" in db_url else "default"},
        {"label": "Redis", "value": "已连接" if os.getenv("REDIS_URL") else "未配置"},
        {"label": "Storage Root", "value": str(_PROJECT_ROOT / "storage")},
        {"label": "Output Root", "value": str(_PROJECT_ROOT / "storage" / "outputs")},
        {"label": "Knowledge Vault", "value": os.path.expanduser(os.getenv("FINANCE_AGENT_VAULT_ROOT", "~/Finance-Agent-Knowledge-Vault"))},
        {"label": "Jin10 Reports Dir", "value": os.path.expanduser("~/jin10-reports")},
    ]


def _collect_system_info() -> list[dict[str, str]]:
    return [
        {"label": "Python", "value": "3.11"},
        {"label": "Package Manager", "value": "uv"},
        {"label": "Frontend", "value": "Vite + React 18 + Tailwind"},
        {"label": "API Framework", "value": "FastAPI"},
    ]


def _validate_preference_value(key: str, value: str) -> None:
    item = _PREFERENCE_BY_KEY.get(key)
    if item is None:
        raise SettingsValidationError(f"Unsupported settings preference: {key}")
    if value not in item.options:
        raise SettingsValidationError(f"Unsupported value for settings preference: {key}")


def _build_preference_overlays(records: list[AppSetting]) -> dict[str, str]:
    overlays: dict[str, str] = {}
    for record in records:
        if record.scope != "global":
            continue
        if not record.setting_key.startswith("global."):
            continue
        key = record.setting_key.removeprefix("global.")
        value = record.value_json.get("value")
        if isinstance(value, str):
            overlays[key] = value
    return overlays


def _build_source_overlays(records: list[AppSetting]) -> dict[str, bool]:
    overlays: dict[str, bool] = {}
    for record in records:
        if record.scope != "source":
            continue
        enabled = record.value_json.get("enabled")
        if isinstance(enabled, bool) and record.source_key:
            overlays[record.source_key] = enabled
    return overlays


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "***"
    return value[:4] + "****" + value[-4:]


def _encrypt_secret(value: str) -> str:
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def _get_fernet() -> Fernet:
    key = (os.getenv("SETTINGS_MASTER_KEY") or "").strip()
    if not key:
        raise SettingsSecretStorageNotConfiguredError
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise SettingsSecretStorageNotConfiguredError from exc


def _build_secret_records(db: Session | None) -> dict[str, dict[str, Any]]:
    if db is None:
        return {}
    records: dict[str, dict[str, Any]] = {}
    for source_key in _SOURCE_META:
        secret = get_app_secret(db, source_key)
        if secret is None:
            continue
        records[source_key] = {
            "masked": secret.masked_value,
            "updated_at": secret.updated_at.isoformat() if secret.updated_at else None,
        }
    return records


def _resolve_secret_mask(
    source_key: str,
    meta: dict[str, str | None],
    secret_records: dict[str, dict[str, Any]],
) -> str | None:
    env_name = meta["secret_env"]
    env_value = _mask(os.getenv(env_name)) if env_name else None
    if env_value:
        return env_value
    secret_record = secret_records.get(source_key)
    if secret_record is None:
        return None
    return secret_record.get("masked")


def _resolve_secret_configured(
    source_key: str,
    meta: dict[str, str | None],
    secret_records: dict[str, dict[str, Any]],
) -> bool:
    env_name = meta["secret_env"]
    if env_name and os.getenv(env_name):
        return True
    return source_key in secret_records


def _record_secret_event(
    db: Session,
    *,
    source_key: str,
    old_masked: str | None,
    new_masked: str | None,
    actor: str | None,
    reason: str | None,
    request_id: str | None,
    audit_id: str | None,
    action: str,
) -> None:
    db.add(
        AppSettingEvent(
            setting_key=f"secret.{source_key}.api_key",
            scope="secret",
            source_key=source_key,
            action=action,
            old_value_json={"configured": old_masked is not None, "masked": old_masked} if old_masked is not None else None,
            new_value_json={"configured": new_masked is not None, "masked": new_masked} if new_masked is not None else None,
            actor=actor,
            reason=reason,
            request_id=request_id,
            audit_id=audit_id,
            created_at=datetime.now(UTC),
        )
    )
