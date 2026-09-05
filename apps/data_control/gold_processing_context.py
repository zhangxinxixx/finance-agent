"""DB-backed Gold processing context for the data-control seam."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from apps.analysis.gold_policy.feature_adapter import build_feature_snapshot_from_analysis_snapshot
from apps.runtime.premarket_snapshot_authority import (
    PremarketSnapshotAuthority,
    resolve_authoritative_premarket_snapshot,
)
from apps.runtime.source_controls import jin10_disabled

SessionFactory = Callable[[], Any]

_AUTHORITY_FAILURE_PROHIBITED = ("DIRECTIONAL_ANALYSIS", "DIRECTIONAL_STRATEGY")
_DISABLED_SOURCE_KEYS = (
    "jin10_mcp_market",
    "jin10_mcp_flash",
    "jin10_xnews_public",
    "jin10_daily_report",
    "jin10_svip_reports",
    "jin10_datacenter_reports",
)


class GoldContextError(ValueError):
    """A fail-closed error while materialising the Gold processing context."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class GoldProcessingContext:
    """Validated authority and the feature-layer Gold data-quality decision."""

    authority_status: str
    authority_reason_code: str
    authority_snapshot_id: str | None = None
    authority_run_id: str | None = None
    artifact_path: Path | None = None
    artifact_sha256: str | None = None
    cutoff: datetime | None = None
    feature_snapshot_id: str | None = None
    feature_payload_hash: str | None = None
    readiness: dict[str, Any] = field(default_factory=dict)
    gold_source_ref: dict[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return self.authority_status == "found" and self.feature_snapshot_id is not None

    @property
    def analysis_readiness(self) -> str:
        return str(self.readiness.get("analysis_readiness") or "blocked")

    @property
    def strategy_readiness(self) -> str:
        return str(self.readiness.get("strategy_readiness") or "blocked")

    @property
    def options_readiness(self) -> str:
        return str(self.readiness.get("options_readiness") or "blocked")

    @property
    def event_attribution_readiness(self) -> str:
        return str(self.readiness.get("event_attribution_readiness") or "blocked")

    @property
    def prohibited_outputs(self) -> tuple[str, ...]:
        values = self.readiness.get("prohibited_outputs")
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            return tuple(str(value) for value in values)
        return _AUTHORITY_FAILURE_PROHIBITED

    @property
    def missing_required_inputs(self) -> tuple[str, ...]:
        return _string_tuple(self.readiness.get("missing_required_inputs"))

    @property
    def missing_confirmatory_inputs(self) -> tuple[str, ...]:
        return _string_tuple(self.readiness.get("missing_confirmatory_inputs"))

    @property
    def reason_codes(self) -> tuple[str, ...]:
        values = _string_tuple(self.readiness.get("reason_codes"))
        return values or (self.authority_reason_code,)

    @property
    def source_ref(self) -> dict[str, Any]:
        return dict(self.gold_source_ref)

    def source_refs(self) -> list[dict[str, Any]]:
        return [self.source_ref]

    def action_suggestions(self) -> list[dict[str, Any]]:
        """Project Gold gaps onto existing producers without executing them."""

        from apps.data_control.gold_gap_actions import build_gold_gap_actions

        return build_gold_gap_actions(self)

    def readiness_dict(self) -> dict[str, Any]:
        if self.readiness:
            return dict(self.readiness)
        return {
            "policy_version": "gold_readiness_policy.v1",
            "analysis_readiness": "blocked",
            "strategy_readiness": "blocked",
            "options_readiness": "blocked",
            "event_attribution_readiness": "blocked",
            "missing_required_inputs": [],
            "missing_confirmatory_inputs": [],
            "prohibited_outputs": list(_AUTHORITY_FAILURE_PROHIBITED),
            "reason_codes": [self.authority_reason_code],
        }

    def limits_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis_readiness,
            "strategy": self.strategy_readiness,
            "options": self.options_readiness,
            "event_attribution": self.event_attribution_readiness,
            "blocked_outputs": list(self.prohibited_outputs),
            "missing_required_inputs": list(self.missing_required_inputs),
            "missing_confirmatory_inputs": list(self.missing_confirmatory_inputs),
            "reason_codes": list(self.reason_codes),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": {
                "status": self.authority_status,
                "reason_code": self.authority_reason_code,
                "snapshot_id": self.authority_snapshot_id,
                "run_id": self.authority_run_id,
                "artifact_path": str(self.artifact_path) if self.artifact_path else None,
                "artifact_sha256": self.artifact_sha256,
            },
            "feature": {
                "snapshot_id": self.feature_snapshot_id,
                "payload_hash": self.feature_payload_hash,
            },
            "cutoff": self.cutoff.isoformat() if self.cutoff else None,
            "readiness": self.readiness_dict(),
            "limits": self.limits_dict(),
            "source_refs": self.source_refs(),
            "evidence": {
                "source_health": "unknown",
                "raw_presence": "unknown",
                "parsed_success": "unknown",
                "strategy_availability": "unknown",
            },
            "disabled_sources": list(_DISABLED_SOURCE_KEYS) if jin10_disabled() else [],
            "diagnostics": list(self.diagnostics),
            "actions": self.action_suggestions(),
        }


def build_gold_processing_context(
    *,
    storage_root: Path,
    trade_date: str,
    observed_at: datetime,
    session_factory: SessionFactory | None = None,
) -> GoldProcessingContext:
    """Resolve one DB authority and derive Gold readiness from its exact payload."""

    observed = _ensure_utc(observed_at)
    authority: PremarketSnapshotAuthority | None = None
    try:
        factory = session_factory
        if factory is None:
            from database.models.engine import SessionLocal

            factory = SessionLocal

        with factory() as db:
            authority = resolve_authoritative_premarket_snapshot(
                db,
                storage_root=Path(storage_root),
                trade_date=trade_date,
            )
    except Exception as exc:  # DB/session failures are a blocked diagnostic, never a crash.
        return _blocked_context(
            status="unavailable" if authority is None else "invalid",
            reason_code=(
                "authority_database_unavailable" if authority is None else "authority_integrity_invalid"
            ),
            trade_date=trade_date,
            diagnostics=(type(exc).__name__,),
            authority=authority,
        )

    assert authority is not None
    if authority.status != "found":
        return _blocked_from_authority(authority, trade_date=trade_date)

    cutoff: datetime | None = None
    try:
        payload, cutoff, artifact_path = _load_validated_payload(
            authority=authority,
            storage_root=Path(storage_root),
            trade_date=trade_date,
            observed_at=observed,
        )
        if jin10_disabled() and _uses_disabled_jin10_input(payload):
            raise GoldContextError("jin10_input_disabled")
        feature = build_feature_snapshot_from_analysis_snapshot(payload)
        if feature.as_of != cutoff:
            raise GoldContextError("feature_cutoff_mismatch")
        if feature.as_of > observed:
            raise GoldContextError("feature_snapshot_from_future")
        readiness = feature.data_quality.model_dump(mode="json")
        readiness["policy_version"] = readiness.pop("readiness_policy_version", "gold_readiness_policy.v1")
    except GoldContextError as exc:
        return _blocked_context(
            status="invalid",
            reason_code=exc.reason_code,
            trade_date=trade_date,
            diagnostics=(str(exc),),
            authority=authority,
            cutoff=cutoff,
        )
    except Exception as exc:
        return _blocked_context(
            status="invalid",
            reason_code="gold_feature_snapshot_invalid",
            trade_date=trade_date,
            diagnostics=(type(exc).__name__,),
            authority=authority,
            cutoff=cutoff,
        )

    source_ref = {
        "source": "analysis_snapshot",
        "source_ref": authority.snapshot_id,
        "reference": authority.snapshot_id,
        "data_date": trade_date,
        "retrieved_at": cutoff.isoformat(),
        "artifact_path": str(artifact_path),
        "sha256": authority.file_sha256,
    }
    return GoldProcessingContext(
        authority_status=authority.status,
        authority_reason_code=authority.reason_code,
        authority_snapshot_id=authority.snapshot_id,
        authority_run_id=authority.run_id,
        artifact_path=artifact_path,
        artifact_sha256=authority.file_sha256,
        cutoff=cutoff,
        feature_snapshot_id=feature.snapshot_id,
        feature_payload_hash=feature.payload_hash,
        readiness=readiness,
        gold_source_ref=source_ref,
    )


def _load_validated_payload(
    *,
    authority: PremarketSnapshotAuthority,
    storage_root: Path,
    trade_date: str,
    observed_at: datetime,
) -> tuple[dict[str, Any], datetime, Path]:
    if (
        authority.snapshot_path is None
        or not authority.run_id
        or not authority.snapshot_id
        or not authority.file_sha256
    ):
        raise GoldContextError("authority_identity_missing")
    root = storage_root.resolve(strict=True)
    path = Path(authority.snapshot_path).resolve(strict=True)
    try:
        path.relative_to(root)
        raw = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise GoldContextError("authority_artifact_unreadable") from exc
    if hashlib.sha256(raw).hexdigest() != authority.file_sha256:
        raise GoldContextError("authority_artifact_hash_mismatch")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoldContextError("authority_artifact_invalid_json") from exc
    if not isinstance(payload, dict):
        raise GoldContextError("authority_artifact_not_object")
    expected_identity = {
        "asset": "XAUUSD",
        "trade_date": trade_date,
        "run_id": authority.run_id,
        "snapshot_id": authority.snapshot_id,
    }
    if any(payload.get(key) != value for key, value in expected_identity.items()):
        raise GoldContextError("authority_snapshot_identity_mismatch")
    cutoff = _required_aware_time(payload.get("snapshot_time"), reason_prefix="authority_snapshot_time")
    if cutoff > observed_at:
        raise GoldContextError("authority_snapshot_time_future")
    if cutoff.date().isoformat() != trade_date:
        raise GoldContextError("authority_snapshot_trade_date_mismatch")
    return payload, cutoff, path


def _uses_disabled_jin10_input(payload: Mapping[str, Any]) -> bool:
    technical = payload.get("technical")
    if "market_prices" not in payload and isinstance(technical, Mapping) and technical.get("status") == "available":
        return True
    consumed_sections = (
        "market_prices",
        "macro",
        "oil",
        "cot",
        "positioning",
        "futures",
        "etf_flow",
        "options",
        "official_events",
    )
    return any(
        _contains_jin10_source(payload.get(section))
        for section in consumed_sections
        if isinstance(payload.get(section), Mapping) and payload[section].get("status") == "available"
    )


def _contains_jin10_source(value: object) -> bool:
    reference_keys = {"reference", "source_ref", "raw_path", "source_url"}
    source_keys = {"source", "source_name", "producer"}
    if isinstance(value, Mapping):
        keys = {str(key).casefold() for key in value}
        has_reference = bool(keys & reference_keys)
        for key, nested in value.items():
            normalized_key = str(key).casefold()
            if normalized_key in reference_keys and _contains_jin10_token(nested):
                return True
            if normalized_key in source_keys and has_reference and _contains_jin10_token(nested):
                return True
            if _contains_jin10_source(nested):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_jin10_source(item) for item in value)
    return False


def _contains_jin10_token(value: object) -> bool:
    if not isinstance(value, str):
        return _contains_jin10_source(value)
    normalized = value.casefold()
    if normalized.startswith("jin10") or "jin10_" in normalized:
        return True
    path_segments = normalized.replace("\\", "/").split("/")
    if any(segment == "jin10" for segment in path_segments):
        return True
    if "://" not in normalized and not normalized.startswith("//"):
        return False
    try:
        hostname = urlsplit(normalized).hostname
    except ValueError:
        return False
    return hostname == "jin10.com" or bool(hostname and hostname.endswith(".jin10.com"))


def _required_aware_time(value: object, *, reason_prefix: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise GoldContextError(f"{reason_prefix}_missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoldContextError(f"{reason_prefix}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GoldContextError(f"{reason_prefix}_not_aware")
    return parsed.astimezone(UTC)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _blocked_from_authority(authority: PremarketSnapshotAuthority, *, trade_date: str) -> GoldProcessingContext:
    return _blocked_context(
        status=authority.status,
        reason_code=authority.reason_code,
        trade_date=trade_date,
        authority=authority,
    )


def _blocked_context(
    *,
    status: str,
    reason_code: str,
    trade_date: str,
    diagnostics: tuple[str, ...] = (),
    authority: PremarketSnapshotAuthority | None = None,
    cutoff: datetime | None = None,
) -> GoldProcessingContext:
    source_ref = {
        "source": "gold_premarket_authority",
        "source_ref": f"authority:{reason_code}",
        "data_date": trade_date,
        "status": "blocked",
        "reason_code": reason_code,
    }
    return GoldProcessingContext(
        authority_status=status,
        authority_reason_code=reason_code,
        authority_snapshot_id=authority.snapshot_id if authority else None,
        authority_run_id=authority.run_id if authority else None,
        artifact_path=authority.snapshot_path if authority else None,
        artifact_sha256=authority.file_sha256 if authority else None,
        cutoff=cutoff,
        gold_source_ref=source_ref,
        diagnostics=diagnostics,
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(str(item) for item in value)
    return ()
