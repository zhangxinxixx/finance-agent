"""Worker-owned execution of an Event Flow live-strategy recompute request.

The module is deliberately a thin, injected-dependency handoff: request
resolution and the runtime preview remain their own contracts, while this
worker owns the append-only audit attempt and accepted-only history write.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.analysis.strategy.history_store import StrategyHistoryStore
from apps.analysis.strategy.recompute import (
    RECOMPUTE_SCHEMA_VERSION,
    evaluate_strategy_recompute,
)
from apps.analysis.strategy.recompute_request_resolution import (
    RecomputeRequestResolution,
    resolve_recompute_request,
    validate_recompute_request,
)
from apps.runtime.live_strategy_recompute import RECOMPUTE_PREVIEW_SCHEMA_VERSION
from apps.worker.recompute_result_store import (
    RESULT_SCHEMA_NAME,
    RESULT_SCHEMA_VERSION,
    RecomputeResultStore,
    validate_recompute_result,
)


REQUEST_EXECUTION_SCHEMA_VERSION = "live_strategy.recompute_request_execution.v1"
_EXECUTION_SCHEMA_VERSION = "live_strategy.recompute_execution.v1"
_EVENT_EXECUTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_HISTORY_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_REASON_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_SAFE_PREVIEW_REASON_CODES = frozenset(
    {
        "candidate_canonical_data_unavailable",
        "candidate_canonical_market_unavailable",
        "candidate_event_overlay_required",
        "candidate_status_unavailable",
        "candidate_strategy_suspended_data",
        "decision_diff_unchanged",
        "eligible_strategy_history_unavailable",
        "event_detail_unavailable",
        "event_identity_required",
        "event_not_found",
        "event_observation_unavailable",
        "event_recompute_candidate_required",
        "observed_at_required",
        "observed_market_reaction_required",
        "observed_reaction_required",
        "previous_canonical_data_unavailable",
        "previous_canonical_market_unavailable",
        "previous_schema_version_required",
        "previous_status_unavailable",
        "previous_strategy_id_required",
        "previous_strategy_suspended_data",
        "previous_strategy_version_required",
        "recompute_blocked",
        "strategy_history_invalid",
        "candidate_schema_version_required",
        "candidate_strategy_id_required",
        "candidate_strategy_version_required",
    }
)

PreviewLoader = Callable[[str], Mapping[str, Any]]
HistoryStoreFactory = Callable[[str | Path], StrategyHistoryStore]
ResultStoreFactory = Callable[[str | Path], RecomputeResultStore]


def execute_live_strategy_recompute_request(
    request: Mapping[str, Any],
    event_flow_events: Iterable[Mapping[str, Any]],
    preview_loader: PreviewLoader,
    *,
    storage_root: str | Path,
    attempted_at: datetime,
    write: bool = False,
    history_store_factory: HistoryStoreFactory = StrategyHistoryStore,
    result_store_factory: ResultStoreFactory = RecomputeResultStore,
) -> dict[str, Any]:
    """Execute one validated request using an injected preview loader.

    ``write=False`` is intentionally a completely read-only planning mode.  A
    result is still built and validated conceptually, but no store is created
    or called.  In write mode, a result-store error is deliberately allowed to
    propagate: a success response without its immutable audit artifact is not
    a valid worker outcome.
    """

    normalized_request = validate_recompute_request(request)
    normalized_attempted_at = _timestamp(attempted_at)
    resolution = resolve_recompute_request(normalized_request, event_flow_events)
    attempt = _base_attempt(normalized_request, resolution, normalized_attempted_at)

    candidate: dict[str, Any] | None = None
    if resolution.resolution_status == "blocked":
        attempt.update(attempt_status="blocked", reason_codes=list(resolution.reason_codes))
    elif resolution.resolution_status != "eligible" or resolution.resolved_event_flow_id is None:
        attempt.update(attempt_status="blocked", reason_codes=list(resolution.reason_codes))
    else:
        attempt, candidate = _preview_attempt(attempt, resolution.resolved_event_flow_id, preview_loader)

    _finalize_result_id(attempt)
    if not write:
        return _summary(attempt, audit_status="planned", history_status="not_written", result_artifact_ref=None)

    history_status = "not_applicable"
    if attempt["attempt_status"] == "accepted":
        # candidate is set only by _preview_attempt after strict validation.
        assert candidate is not None
        # Validate before constructing the history store so an invalid result
        # payload can never produce a strategy-history side effect.
        validate_recompute_result(attempt)
        try:
            history_write = history_store_factory(storage_root).write(candidate)
        except Exception:
            # Audit a fixed failure code rather than exposing exception details
            # (which commonly include local artifact paths).
            attempt["attempt_status"] = "failed"
            attempt["reason_codes"] = ["strategy_history_write_failed"]
            attempt["history_ref"] = None
            _finalize_result_id(attempt)
            history_status = "failed"
        else:
            attempt["history_ref"] = {
                "artifact_ref": history_write.artifact_ref,
                "strategy_version": history_write.strategy_version,
                "schema_version": history_write.schema_version,
            }
            history_status = "accepted" if history_write.created else "unchanged"
            # The immutable result records accepted execution.  ``history_status``
            # carries replay idempotency, retaining an identical result payload
            # and therefore an identical result id on an exact replay.
            _finalize_result_id(attempt)

    result_write = result_store_factory(storage_root).write(attempt)
    audit_status = "persisted" if result_write.created else "unchanged"
    return _summary(
        attempt,
        audit_status=audit_status,
        history_status=history_status,
        result_artifact_ref=result_write.artifact_ref,
    )


def run_live_strategy_recompute_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Compatibility-oriented verb alias for worker callers."""

    return execute_live_strategy_recompute_request(*args, **kwargs)


def _preview_attempt(
    attempt: dict[str, Any], event_id: str, preview_loader: PreviewLoader
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        preview = _json_object(preview_loader(event_id))
    except Exception:
        attempt.update(attempt_status="failed", reason_codes=["preview_loader_failed"])
        return attempt, None

    if preview.get("schema_version") != RECOMPUTE_PREVIEW_SCHEMA_VERSION or preview.get("event_id") != event_id:
        attempt.update(attempt_status="failed", reason_codes=["preview_contract_invalid"])
        return attempt, None
    status = preview.get("status")
    if status in {"blocked", "unavailable"}:
        attempt.update(
            attempt_status=status,
            reason_codes=_safe_preview_reason_codes(preview.get("reasons"), fallback=f"preview_{status}"),
            preview_ref={"event_id": event_id, "status": status},
        )
        return attempt, None
    if status != "accepted":
        attempt.update(attempt_status="failed", reason_codes=["preview_status_invalid"])
        return attempt, None

    previous = _accepted_previous(preview.get("previous_strategy"))
    candidate = _accepted_candidate(preview.get("candidate_strategy"), event_id)
    execution = _accepted_execution(preview.get("execution"), previous, candidate, event_id)
    observation = _accepted_observation(preview.get("event_observation"), event_id)
    if previous is None or candidate is None or execution is None or observation is None:
        attempt.update(attempt_status="failed", reason_codes=["accepted_preview_contract_invalid"])
        return attempt, None
    attempt.update(
        attempt_status="accepted",
        reason_codes=["accepted:recompute_preview"],
        observation_ref={"observation_id": observation["observation_id"], "event_id": event_id},
        execution_ref={"execution_id": execution["execution_id"], "status": "accepted"},
        recompute_ref={
            "recompute_id": execution["recompute"]["recompute_id"],
            "accepted": True,
            "execution_id": execution["execution_id"],
        },
        preview_ref={
            "event_id": event_id,
            "status": "accepted",
            "payload_sha256": _digest(
                {"previous": previous, "observation": observation, "candidate": candidate, "execution": execution}
            ),
        },
    )
    attempt["input_snapshot_ids"]["event_observation_id"] = observation["observation_id"]
    attempt["source_refs"] = _dedupe_refs(attempt["source_refs"] + _refs(observation.get("source_refs")))
    return attempt, candidate


def _base_attempt(
    request: Mapping[str, Any], resolution: RecomputeRequestResolution, attempted_at: str) -> dict[str, Any]:
    source_refs = _dedupe_refs(
        [
            {"source_ref": f"recompute_request:{request['request_id']}"},
            *(_refs(request.get("source_refs"))),
            *(_refs(request.get("raw_refs"))),
            *(_refs(request.get("parsed_refs"))),
            *(_refs(request.get("output_refs"))),
        ]
    )
    return {
        "schema_name": RESULT_SCHEMA_NAME,
        "schema_version": RESULT_SCHEMA_VERSION,
        "result_id": "pending",
        "request_id": request["request_id"],
        # RecomputeResultStore partitions with a deliberately stricter safe
        # component alphabet than Event Flow IDs (which may contain ``:``).
        # Keep the original identifier as a typed ref, never by dropping it.
        "event_id": _result_event_id(request["event_id"]),
        "trade_date": request["trade_date"],
        "attempted_at": attempted_at,
        "attempt_status": "unavailable",
        "resolution_status": resolution.resolution_status,
        "reason_codes": list(resolution.reason_codes),
        "input_snapshot_ids": {
            "request_event_hash": request["event_hash"],
            "request_observation_hash": request["observation_hash"],
        },
        "source_refs": source_refs,
        "request_lineage_refs": {
            name: deepcopy(request[name]) for name in ("source_refs", "raw_refs", "parsed_refs", "output_refs")
        },
        "resolution": resolution.to_dict(),
        "event_ref": {"event_id": request["event_id"]},
        "observation_ref": None,
        "execution_ref": None,
        "recompute_ref": None,
        "history_ref": None,
        "preview_ref": None,
    }


def _accepted_previous(value: Any) -> dict[str, Any] | None:
    return _accepted_strategy(value, require_candidate_overlay=False, event_id=None)


def _accepted_candidate(value: Any, event_id: str) -> dict[str, Any] | None:
    return _accepted_strategy(value, require_candidate_overlay=True, event_id=event_id)


def _accepted_strategy(
    value: Any, *, require_candidate_overlay: bool, event_id: str | None
) -> dict[str, Any] | None:
    try:
        candidate = _json_object(value)
    except ValueError:
        return None
    required = ("schema_version", "status", "asset", "strategy_id", "strategy_version", "updated_at", "live_market", "data_quality")
    if any(field not in candidate for field in required):
        return None
    if (
        candidate["schema_version"] != "live_strategy.v1"
        or candidate["status"] not in {"available", "partial"}
        or candidate.get("asset") != "XAUUSD"
    ):
        return None
    if not all(_safe_history_component(candidate[field]) for field in ("strategy_id", "strategy_version")):
        return None
    if not isinstance(candidate.get("live_market"), Mapping) or candidate["live_market"].get("status") != "available":
        return None
    quality = candidate.get("data_quality")
    canonical = quality.get("canonical_candle") if isinstance(quality, Mapping) else None
    if not isinstance(canonical, Mapping) or canonical.get("status") != "available":
        return None
    try:
        _timestamp_text(candidate["updated_at"])
    except ValueError:
        return None
    if require_candidate_overlay:
        overlay = candidate.get("event_overlay")
        if (
            not isinstance(overlay, Mapping)
            or overlay.get("schema_version") != "live_strategy.event_overlay.v1"
            or overlay.get("status") != "eligible"
            or overlay.get("recompute_candidate") is not True
            or overlay.get("event_id") != event_id
        ):
            return None
    return candidate


def _accepted_execution(
    value: Any, previous: Mapping[str, Any] | None, candidate: Mapping[str, Any] | None, event_id: str
) -> dict[str, Any] | None:
    try:
        execution = _json_object(value)
    except ValueError:
        return None
    recompute = execution.get("recompute")
    if previous is None or candidate is None:
        return None
    expected_recompute = evaluate_strategy_recompute(previous, candidate)
    if (
        execution.get("schema_version") != _EXECUTION_SCHEMA_VERSION
        or execution.get("status") != "accepted"
        or not _safe_event_execution_id(execution.get("execution_id"))
        or not isinstance(recompute, Mapping)
        or execution.get("from_ref") != _strategy_ref(previous)
        or execution.get("to_ref") != _strategy_ref(candidate)
        or recompute != expected_recompute
        or recompute.get("schema_version") != RECOMPUTE_SCHEMA_VERSION
        or recompute.get("accepted") is not True
        or recompute.get("decision_changed") is not True
        or recompute.get("from_strategy_id") != previous.get("strategy_id")
        or recompute.get("to_strategy_id") != candidate.get("strategy_id")
        or recompute.get("from_strategy_version") != previous.get("strategy_version")
        or recompute.get("to_strategy_version") != candidate.get("strategy_version")
        or not _safe_event_execution_id(recompute.get("recompute_id"))
    ):
        return None
    canonical_execution = dict(execution)
    canonical_execution.pop("execution_id", None)
    expected_execution_id = f"execution-{_digest(canonical_execution)}"
    if execution["execution_id"] != expected_execution_id:
        return None
    overlay_ref = recompute.get("event_overlay_ref")
    overlay = candidate["event_overlay"]
    if (
        not isinstance(overlay_ref, Mapping)
        or overlay_ref.get("schema_version") != overlay.get("schema_version")
        or overlay_ref.get("event_id") != event_id
        or overlay_ref.get("status") != overlay.get("status")
    ):
        return None
    return execution


def _strategy_ref(strategy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": strategy.get("strategy_id"),
        "strategy_version": strategy.get("strategy_version"),
    }


def _safe_preview_reason_codes(value: Any, *, fallback: str) -> list[str]:
    if isinstance(value, list):
        safe = [
            item
            for item in value
            if isinstance(item, str)
            and _SAFE_REASON_CODE_RE.fullmatch(item)
            and item in _SAFE_PREVIEW_REASON_CODES
        ]
        if safe:
            return list(dict.fromkeys(safe))
    return [fallback]


def _accepted_observation(value: Any, event_id: str) -> dict[str, Any] | None:
    try:
        observation = _json_object(value)
    except ValueError:
        return None
    if observation.get("status") != "available" or observation.get("event_id") != event_id:
        return None
    if not _safe_event_execution_id(observation.get("observation_id")):
        return None
    return observation


def _finalize_result_id(attempt: dict[str, Any]) -> None:
    canonical = dict(attempt)
    canonical.pop("result_id", None)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    attempt["result_id"] = f"result-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _summary(
    attempt: Mapping[str, Any], *, audit_status: str, history_status: str, result_artifact_ref: str | None
) -> dict[str, Any]:
    return {
        "schema_version": REQUEST_EXECUTION_SCHEMA_VERSION,
        "status": "planned" if audit_status == "planned" else history_status if history_status in {"unchanged", "failed"} else attempt["attempt_status"],
        "audit_status": audit_status,
        "history_status": history_status,
        "result_artifact_ref": result_artifact_ref,
        "result": deepcopy(dict(attempt)),
    }


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("attempted_at must be a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a timezone-aware ISO-8601 string")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("value must be a JSON object")
    try:
        return json.loads(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be finite JSON") from exc


def _safe_event_execution_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_EVENT_EXECUTION_ID_RE.fullmatch(value))


def _safe_history_component(value: Any) -> bool:
    return isinstance(value, str) and bool(_HISTORY_COMPONENT_RE.fullmatch(value))


def _result_event_id(event_id: str) -> str:
    """Return the safe result partition while preserving the real ID in event_ref."""

    if isinstance(event_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", event_id):
        return event_id
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
    return f"event-{digest}"


def _refs(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, Mapping) and item] if isinstance(value, list) else []


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        try:
            key = json.dumps(ref, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            continue
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "HistoryStoreFactory",
    "PreviewLoader",
    "REQUEST_EXECUTION_SCHEMA_VERSION",
    "ResultStoreFactory",
    "execute_live_strategy_recompute_request",
    "run_live_strategy_recompute_request",
]
