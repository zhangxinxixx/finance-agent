"""Pure resolution for Event Flow live-strategy recompute requests.

This module only establishes whether a request identifies one Event Flow event.
It neither executes a recompute nor makes any claim about market reaction or
strategy acceptance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping


REQUEST_SCHEMA_VERSION = "live_strategy_recompute_request.v1"
RESOLUTION_SCHEMA_VERSION = "live_strategy_recompute_resolution.v1"
_REQUEST_SCHEMA_NAME = "live_strategy_recompute_request"
_REQUEST_ACTION = "recompute_live_strategy"
_REF_COLLECTIONS = ("source_refs", "raw_refs", "parsed_refs", "output_refs")
_REF_KEYS = ("artifact_id", "sha256", "snapshot_id", "source_ref", "uri", "url")
_PATH_REF_KEYS = ("artifact_path", "file_path", "parsed_path", "path", "raw_path")


class RecomputeRequestValidationError(ValueError):
    """Raised when a recompute request or Event Flow candidate is malformed."""


@dataclass(frozen=True, slots=True)
class RecomputeRequestResolution:
    """Deterministic, audit-only resolution outcome."""

    request_id: str
    resolution_status: str
    reason_codes: tuple[str, ...]
    resolved_event_flow_id: str | None
    matched_event_ids: tuple[str, ...]
    schema_version: str = RESOLUTION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "resolution_status": self.resolution_status,
            "reason_codes": list(self.reason_codes),
            "resolved_event_flow_id": self.resolved_event_flow_id,
            "matched_event_ids": list(self.matched_event_ids),
        }


def validate_recompute_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe normalized request or raise a validation error."""

    if not isinstance(request, Mapping):
        raise RecomputeRequestValidationError("request must be a JSON object")
    payload = _json_object(request, "request")
    required = (
        "request_id",
        "schema_name",
        "schema_version",
        "requested_action",
        "event_id",
        "event_hash",
        "observation_hash",
        "source_key",
        "trade_date",
        "published_at",
        "evidence_level",
        "quality_status",
        "dispatch_status",
        "reason_codes",
        "detected_at",
        "created_at",
        *_REF_COLLECTIONS,
    )
    _require_fields(payload, required, "request")
    for field in ("request_id", "event_id", "event_hash", "observation_hash", "source_key", "evidence_level"):
        payload[field] = _nonempty_string(payload[field], field)
    if payload["schema_name"] != _REQUEST_SCHEMA_NAME:
        raise RecomputeRequestValidationError("schema_name must be live_strategy_recompute_request")
    if payload["schema_version"] != REQUEST_SCHEMA_VERSION:
        raise RecomputeRequestValidationError(f"schema_version must be {REQUEST_SCHEMA_VERSION}")
    if payload["requested_action"] != _REQUEST_ACTION:
        raise RecomputeRequestValidationError("requested_action must be recompute_live_strategy")
    payload["trade_date"] = _trade_date(payload["trade_date"])
    payload["published_at"] = _optional_timestamp(payload["published_at"], "published_at")
    payload["detected_at"] = _timestamp(payload["detected_at"], "detected_at")
    payload["created_at"] = _timestamp(payload["created_at"], "created_at")
    if payload["quality_status"] not in {"allowed", "degraded", "blocked"}:
        raise RecomputeRequestValidationError("quality_status is invalid")
    if payload["dispatch_status"] not in {"pending", "blocked"}:
        raise RecomputeRequestValidationError("dispatch_status is invalid")
    payload["reason_codes"] = _string_list(payload["reason_codes"], "reason_codes")
    for field in _REF_COLLECTIONS:
        payload[field] = _ref_collection(payload[field], field)
    return payload


def resolve_recompute_request(
    request: Mapping[str, Any],
    event_flow_events: Iterable[Mapping[str, Any]],
) -> RecomputeRequestResolution:
    """Resolve a request by unique exact ID, then unique lineage intersection.

    Candidate events are deliberately never matched by title, text, basename, or
    inferred path. A blocked request is terminal for this resolver.
    """

    normalized_request = validate_recompute_request(request)
    request_id = normalized_request["request_id"]
    if normalized_request["dispatch_status"] == "blocked":
        return RecomputeRequestResolution(
            request_id=request_id,
            resolution_status="blocked",
            reason_codes=("request_dispatch_blocked",),
            resolved_event_flow_id=None,
            matched_event_ids=(),
        )

    candidates = [_event_candidate(value) for value in event_flow_events]
    exact = [item for item in candidates if item["event_id"] == normalized_request["event_id"]]
    if len(exact) == 1:
        return RecomputeRequestResolution(
            request_id=request_id,
            resolution_status="eligible",
            reason_codes=("exact_event_id_match",),
            resolved_event_flow_id=exact[0]["event_id"],
            matched_event_ids=(exact[0]["event_id"],),
        )
    if len(exact) > 1:
        return RecomputeRequestResolution(
            request_id=request_id,
            resolution_status="unresolved",
            reason_codes=("ambiguous_exact_event_id",),
            resolved_event_flow_id=None,
            matched_event_ids=tuple(sorted(item["event_id"] for item in exact)),
        )

    request_refs = _lineage_tokens(normalized_request)
    if not request_refs:
        return RecomputeRequestResolution(
            request_id=request_id,
            resolution_status="unresolved",
            reason_codes=("missing_request_lineage_refs",),
            resolved_event_flow_id=None,
            matched_event_ids=(),
        )
    lineage_matches = [item for item in candidates if request_refs & _lineage_tokens(item)]
    if len(lineage_matches) == 1:
        return RecomputeRequestResolution(
            request_id=request_id,
            resolution_status="eligible",
            reason_codes=("unique_lineage_ref_match",),
            resolved_event_flow_id=lineage_matches[0]["event_id"],
            matched_event_ids=(lineage_matches[0]["event_id"],),
        )
    if lineage_matches:
        return RecomputeRequestResolution(
            request_id=request_id,
            resolution_status="unresolved",
            reason_codes=("ambiguous_lineage_ref_match",),
            resolved_event_flow_id=None,
            matched_event_ids=tuple(sorted(item["event_id"] for item in lineage_matches)),
        )
    return RecomputeRequestResolution(
        request_id=request_id,
        resolution_status="unresolved",
        reason_codes=("event_flow_event_not_found",),
        resolved_event_flow_id=None,
        matched_event_ids=(),
    )


def _event_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RecomputeRequestValidationError("Event Flow candidate must be a JSON object")
    payload = _json_object(value, "Event Flow candidate")
    event_id = payload.get("event_id") or payload.get("id")
    payload["event_id"] = _nonempty_string(event_id, "event_id")
    for field in _REF_COLLECTIONS:
        payload[field] = _ref_collection(payload.get(field, []), field)
    return payload


def _lineage_tokens(payload: Mapping[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for collection_name in _REF_COLLECTIONS:
        for ref in payload[collection_name]:
            canonical = json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            tokens.add(f"ref:{canonical}")
            for key in _REF_KEYS:
                value = ref.get(key)
                if isinstance(value, str) and value.strip():
                    tokens.add(f"{key}:{value.strip()}")
            for key in _PATH_REF_KEYS:
                normalized_path = _normalized_lineage_path(ref.get(key))
                if normalized_path is not None:
                    tokens.add(f"path:{normalized_path}")
    return tokens


def _normalized_lineage_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if text.startswith("storage/"):
        text = text[len("storage/") :]
    parts = text.split("/")
    if not text or text.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        return None
    return "/".join(parts)


def _json_object(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    payload = {str(key): item for key, item in value.items()}
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise RecomputeRequestValidationError(f"{name} must be JSON serializable with finite values") from exc
    if not isinstance(decoded, dict):
        raise RecomputeRequestValidationError(f"{name} must be a JSON object")
    return decoded


def _require_fields(payload: Mapping[str, Any], fields: tuple[str, ...], name: str) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise RecomputeRequestValidationError(f"{name} missing required fields: {', '.join(missing)}")


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecomputeRequestValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _trade_date(value: Any) -> str:
    text = _nonempty_string(value, "trade_date")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise RecomputeRequestValidationError("trade_date must be an ISO-8601 date") from exc


def _timestamp(value: Any, field: str) -> str:
    text = _nonempty_string(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecomputeRequestValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RecomputeRequestValidationError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_timestamp(value: Any, field: str) -> str | None:
    return None if value is None else _timestamp(value, field)


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise RecomputeRequestValidationError(f"{field} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _ref_collection(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RecomputeRequestValidationError(f"{field} must be a list")
    refs: list[dict[str, Any]] = []
    for index, ref in enumerate(value):
        if not isinstance(ref, Mapping) or not ref:
            raise RecomputeRequestValidationError(f"{field}[{index}] must be a non-empty JSON object")
        refs.append(_json_object(ref, f"{field}[{index}]"))
    return refs


__all__ = [
    "REQUEST_SCHEMA_VERSION",
    "RESOLUTION_SCHEMA_VERSION",
    "RecomputeRequestResolution",
    "RecomputeRequestValidationError",
    "resolve_recompute_request",
    "validate_recompute_request",
]
