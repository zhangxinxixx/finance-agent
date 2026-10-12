"""Public page-response boundary for DWS/features and ADS read models.

Collector, parser, and warehouse services intentionally retain lower-layer
lineage.  This module is the final API projection: browser pages may observe
quality/status metadata and source identity, but never raw/ODS/DWD bodies or
filesystem entry points into those layers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlparse

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


_LOW_LEVEL_ARTIFACT_TYPES = {"raw_file", "parsed_file", "ods", "dwd", "raw", "parsed"}
_PAGE_ARTIFACT_TYPES = {
    "source_md",
    "analysis_md",
    "visual_html",
    "structured_json",
    "feature_json",
    "chart_snapshot",
}
_LOW_LEVEL_SEGMENTS = {"raw", "parsed", "ods", "dwd", "landing", "staging"}
_SOURCE_FILE_SUFFIXES = {".pdf", ".csv", ".xlsx", ".xls", ".zip", ".parquet"}
_PAGE_STORAGE_LAYERS = {"features", "outputs", "analysis", "reports"}
_PAGE_IDENTITY_TYPES = {
    "authority_result", "analysis_decision", "price_attribution", "candidate_state",
    "selected_state", "candidate_strategy", "selected_strategy", "consistency_decision",
    "key_level", "transition_decision", "key_level_decision",
}
_FILESYSTEM_KEYS = {
    "file",
    "file_ref",
    "file_path",
    "path",
    "artifact_path",
    "input_snapshot_path",
    "raw_artifact_ref",
    "parsed_artifact_ref",
    "raw_path",
    "parsed_path",
    "collector_raw_artifact_path",
    "collector_parsed_artifact_path",
    "preferred_artifact_path",
    "source_path",
    "generated_from",
}
_EXECUTION_BODY_KEYS = {"input_json", "output_json", "error_json"}
_RAW_BODY_KEYS = {
    "raw_body",
    "raw_payload",
    "raw_content",
    "raw_text",
    "original_body",
    "source_document",
    "source_content",
}
_INTERNAL_METADATA_KEYS = {"artifact_layers", "database_tables"}
_SEMANTIC_PATH_KEYS = {"market_implied_path", "scenario_path", "trace_path", "transmission_path"}
_CONDITIONAL_FILESYSTEM_KEYS = {"generated_from", "path"}
_SAFE_EVENT_PAYLOAD_KEYS = {
    "status",
    "stage",
    "progress",
    "message",
    "reason",
    "error",
    "error_type",
    "warning",
    "warnings",
    "count",
    "started_at",
    "finished_at",
    "updated_at",
    "snapshot_id",
    "run_id",
    "task_id",
}
_LLM_BODY_KEYS = {
    "prompt_messages",
    "request_messages",
    "input_payload",
    "output_payload",
    "raw_output",
    "llm_raw_output",
    "response_payload",
    "response_text",
    "attempts",
}
_LLM_SUMMARY_KEYS = {
    "audit_id",
    "call_id",
    "available",
    "status",
    "note",
    "caller",
    "provider_requested",
    "provider_resolved",
    "model_requested",
    "model_resolved",
    "reasoning_effort_requested",
    "reasoning_effort_resolved",
    "request_sha256",
    "response_sha256",
    "prompt_message_count",
    "prompt_char_count",
    "response_char_count",
    "usage",
    "latency_ms",
    "attempt_count",
    "error_type",
    "error_message",
    "run_id",
    "snapshot_id",
    "report_id",
    "trade_date",
    "created_at",
    "secrets_redacted",
    "sanitization_performed",
    "immutable",
    "config",
}
_SAFE_FILE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ttf",
}


class PageBoundaryViolation(ValueError):
    """Raised when a page asks for a lower-layer artifact as the target."""


def _is_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return urlparse(value).scheme.lower() in {"http", "https"}


def _is_filesystem_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip() or _is_url(value):
        return False
    normalized = value.strip().replace("\\", "/").lower()
    if normalized.startswith(("/api/", "get /api/", "post /api/")):
        return False
    return (
        is_lower_layer_path(normalized)
        or normalized.startswith(("/", "./", "../", "storage/", "raw/", "parsed/"))
        or re.match(r"^[a-z]:/", normalized) is not None
    )


def _path_parts(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip() or _is_url(value):
        return ()
    normalized = value.strip().replace("\\", "/").lower()
    return tuple(part for part in normalized.split("/") if part not in {"", "."})


def _strip_filesystem_field(key: str, value: Any) -> bool:
    if key in _CONDITIONAL_FILESYSTEM_KEYS:
        return _is_filesystem_reference(value)
    return key in _FILESYSTEM_KEYS or (
        key.endswith("_path") and key not in _SEMANTIC_PATH_KEYS and _is_filesystem_reference(value)
    )


def is_lower_layer_path(value: Any) -> bool:
    parts = _path_parts(value)
    if not parts:
        return False
    if any(part in _LOW_LEVEL_SEGMENTS for part in parts):
        return True
    leaf = parts[-1]
    return any(leaf.endswith(suffix) for suffix in _SOURCE_FILE_SUFFIXES)


def _is_safe_page_artifact_path(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().replace("\\", "/")
    if normalized.startswith(("/", "~/")) or re.match(r"^[a-zA-Z]:/", normalized):
        return False
    parts = _path_parts(value)
    if not parts or ".." in parts or is_lower_layer_path(value):
        return False
    leaf = parts[-1]
    if leaf.startswith("raw") or "raw_article" in leaf:
        return False
    if parts[0] in _PAGE_STORAGE_LAYERS:
        return True
    if "storage" in parts:
        storage_index = parts.index("storage")
        return len(parts) > storage_index + 1 and parts[storage_index + 1] in _PAGE_STORAGE_LAYERS
    return False


def is_page_artifact(value: Any) -> bool:
    """Return whether an artifact reference is eligible for page projection."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        return False
    artifact_type = str(value.get("artifact_type") or "").strip().lower()
    file_path = value.get("file_path") or value.get("path") or value.get("artifact_path")
    if artifact_type in _LOW_LEVEL_ARTIFACT_TYPES or not _is_safe_page_artifact_path(file_path):
        return False
    return artifact_type in _PAGE_ARTIFACT_TYPES


def _looks_like_artifact(value: Mapping[str, Any]) -> bool:
    return "artifact_type" in value and any(key in value for key in ("file_path", "path", "artifact_path"))


def _sanitize_source_ref(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        lower = str(key).lower()
        if _strip_filesystem_field(lower, item):
            continue
        if lower in {"source_ref", "endpoint", "artifact_ref"} and _is_filesystem_reference(item):
            continue
        if item is None:
            result[str(key)] = None
            continue
        projected = sanitize_page_payload(item, parent_key=lower)
        if projected is not None:
            result[str(key)] = projected
    return result


def _sanitize_artifact_ref(value: Any) -> dict[str, Any] | None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        return None
    if not any(key in value for key in ("file_path", "path", "artifact_path")):
        if (
            value.get("artifact_type") in _PAGE_IDENTITY_TYPES
            and value.get("identity_kind") in {"id", "hash"}
            and isinstance(value.get("identity"), str)
            and not _is_filesystem_reference(value["identity"])
        ):
            return {key: value[key] for key in ("artifact_type", "identity_kind", "identity")}
        return None
    if not is_page_artifact(value):
        return None
    result: dict[str, Any] = {}
    for key, item in value.items():
        lower = str(key).lower()
        if _strip_filesystem_field(lower, item):
            continue
        if item is None:
            result[str(key)] = None
            continue
        projected = sanitize_page_payload(item, parent_key=lower)
        if projected is not None:
            result[str(key)] = projected
    return result


def _project_llm_audit_summary(value: Any) -> dict[str, Any] | None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        return None
    return {
        str(key): sanitize_page_payload(item, parent_key=str(key).lower())
        for key, item in value.items()
        if str(key).lower() in _LLM_SUMMARY_KEYS and str(key).lower() not in _LLM_BODY_KEYS
    }


def sanitize_page_payload(value: Any, *, parent_key: str | None = None) -> Any:
    """Recursively remove lower-layer bodies and filesystem entry points.

    The function deliberately keeps business fields, source URLs, timestamps,
    quality flags, and safe report/feature artifact references.
    """
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, list):
        projected = [sanitize_page_payload(item, parent_key=parent_key) for item in value]
        return [item for item in projected if item is not None]
    if not isinstance(value, Mapping):
        return value

    if _looks_like_artifact(value):
        return _sanitize_artifact_ref(value)

    result: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        lower = key_text.lower()
        if (
            lower in _EXECUTION_BODY_KEYS
            or lower in _INTERNAL_METADATA_KEYS
            or lower in _RAW_BODY_KEYS
            or lower in _LLM_BODY_KEYS
            or (parent_key == "prompt" and lower == "messages")
        ):
            continue
        if lower == "llm_audit":
            projected_audit = _project_llm_audit_summary(item)
            if projected_audit is not None:
                result[key_text] = projected_audit
            continue
        if lower == "llm_audits" and isinstance(item, list):
            result[key_text] = [
                projected
                for projected in (_project_llm_audit_summary(audit) for audit in item)
                if projected is not None
            ]
            continue
        if _strip_filesystem_field(lower, item):
            # File paths are transport details. Safe artifacts remain available
            # through typed artifact_refs and report asset URLs.
            continue
        if lower in {"source_ref", "endpoint", "artifact_ref"} and _is_filesystem_reference(item):
            continue
        if lower == "source_refs" and isinstance(item, list):
            result[key_text] = [
                _sanitize_source_ref(ref) if isinstance(ref, Mapping) else ref
                for ref in item
                if isinstance(ref, Mapping) or (isinstance(ref, str) and not _is_filesystem_reference(ref))
            ]
            continue
        if lower in {"artifact_refs", "related_artifacts", "input_refs", "output_refs", "artifacts"} and isinstance(
            item, list
        ):
            refs = [_sanitize_artifact_ref(ref) for ref in item]
            result[key_text] = [ref for ref in refs if ref is not None]
            continue
        if item is None:
            result[key_text] = None
            continue
        projected = sanitize_page_payload(item, parent_key=lower)
        if projected is not None:
            result[key_text] = projected
    return result


def _project_agent_inspection(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = sanitize_page_payload(payload)
    agents: list[dict[str, Any]] = []
    for raw in payload.get("agents") or []:
        if not isinstance(raw, Mapping):
            continue
        item = sanitize_page_payload(raw)
        prompt = item.get("prompt") if isinstance(item.get("prompt"), dict) else {}
        prompt.pop("messages", None)
        if prompt:
            item["prompt"] = prompt
        input_view = item.get("input") if isinstance(item.get("input"), dict) else {}
        input_view.pop("payload", None)
        if input_view:
            item["input"] = input_view
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        for key in ("payload", "llm_raw_output", "raw_output", "response_payload"):
            output.pop(key, None)
        if output:
            item["output"] = output
        agents.append(item)
    result["agents"] = agents
    result["page_layer"] = "ADS"
    return result


def _project_report_analysis_inputs(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = sanitize_page_payload(payload)
    inputs: list[dict[str, Any]] = []
    for raw in payload.get("deterministic_inputs") or []:
        if not isinstance(raw, Mapping):
            continue
        item = sanitize_page_payload(raw)
        item.pop("payload", None)
        inputs.append(item)
    result["deterministic_inputs"] = inputs
    for group in ("agent_outputs", "fact_reviews", "synthesis_outputs"):
        projected: list[dict[str, Any]] = []
        for raw in payload.get(group) or []:
            if not isinstance(raw, Mapping):
                continue
            item = sanitize_page_payload(raw)
            audit = _project_llm_audit_summary(raw.get("llm_audit"))
            if audit is not None:
                item["llm_audit"] = audit
            projected.append(item)
        result[group] = projected
    result["page_layer"] = "ADS"
    return result


def _is_allowed_page_file_route(path: str) -> bool:
    decoded = unquote(path)
    if not (
        re.fullmatch(r"/api/reports/[^/]+/asset/(?:source_md|analysis_md|visual_html)/.+", decoded)
        or re.fullmatch(r"/api/jin10/report-bundle/[^/]+/[^/]+/asset/.+", decoded)
    ):
        return False
    suffix = "." + decoded.rsplit(".", 1)[-1].lower() if "." in decoded.rsplit("/", 1)[-1] else ""
    return suffix in _SAFE_FILE_SUFFIXES


def _project_data_source_status(payload: Mapping[str, Any]) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for raw_source in payload.get("sources") or []:
        if not isinstance(raw_source, Mapping):
            continue
        metadata = raw_source.get("metadata") if isinstance(raw_source.get("metadata"), Mapping) else {}
        safe_metadata = {
            key: metadata.get(key)
            for key in (
                "frontend_label",
                "provider_role",
                "fallback_for",
                "fallback_sources",
                "notes",
                "health_state",
                "freshness_status",
                "freshness_reason",
                "readiness_state",
                "gate_state",
                "gating_reason",
            )
            if metadata.get(key) is not None
        }
        item = {
            key: raw_source.get(key)
            for key in (
                "source_key",
                "source_name",
                "source_group",
                "source_type",
                "configured",
                "raw_ingested",
                "parsed",
                "analysis_ready",
                "latest_raw_time",
                "latest_parsed_time",
                "latest_update_time",
                "latest_health_at",
                "latest_snapshot_id",
                "row_count",
                "status",
                "error_message",
                "last_run_id",
                "next_run_time",
                "health_state",
                "freshness_status",
                "freshness_reason",
                "readiness_state",
                "gate_state",
                "gating_reason",
                "affected_modules",
            )
            if key in raw_source
        }
        item["metadata"] = safe_metadata
        # Publish source identity, never collector access parameters or local paths.
        item["source_url"] = None
        for candidate in (raw_source.get("source_url"), metadata.get("source_url"), metadata.get("latest_raw_url")):
            if _is_url(candidate):
                parsed_url = urlparse(candidate)
                if parsed_url.hostname and not parsed_url.username and not parsed_url.password:
                    item["source_url"] = parsed_url._replace(query="", fragment="").geturl()
                    break
        sources.append(item)
    return {"sources": sources}


def _project_data_source_registry(payload: Mapping[str, Any]) -> dict[str, Any]:
    safe_keys = {
        "source_key",
        "source_name",
        "domain",
        "provider",
        "source_type",
        "expected_frequency",
        "expected_arrival_time",
        "freshness_sla_minutes",
        "required_for",
        "fallback_policy",
        "owner_module",
        "enabled",
    }
    sources = [
        {key: value for key, value in source.items() if key in safe_keys}
        for source in payload.get("sources") or []
        if isinstance(source, Mapping)
    ]
    return {"total": len(sources), "sources": sources}


def _project_fedwatch_history(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("page_layer") == "ADS":
        return sanitize_page_payload(payload)
    items: list[dict[str, Any]] = []
    for raw in payload.get("items") or []:
        if not isinstance(raw, Mapping):
            continue
        factor = raw.get("factor") if isinstance(raw.get("factor"), Mapping) else {}
        health = factor.get("health") if isinstance(factor.get("health"), Mapping) else {}
        path = factor.get("market_implied_path") if isinstance(factor.get("market_implied_path"), Mapping) else {}
        items.append(
            {
                "snapshot_id": raw.get("snapshot_id"),
                "as_of": raw.get("as_of"),
                "collected_at": raw.get("collected_at"),
                "parse_status": raw.get("parse_status"),
                "reason": raw.get("reason"),
                "status": health.get("status") or ("available" if raw.get("parse_status") == "ok" else "unavailable"),
                "quality_summary": health.get("quality_summary") or raw.get("quality_summary"),
                "next_meeting": path.get("next_meeting"),
                "year_end": path.get("year_end"),
                "repricing": factor.get("repricing"),
                "source_refs": [
                    _sanitize_source_ref(ref) for ref in factor.get("source_refs") or [] if isinstance(ref, Mapping)
                ],
            }
        )
    return {"as_of": payload.get("as_of"), "items": items, "count": len(items)}


def _project_feishu_monitor(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: sanitize_page_payload(value, parent_key=key) for key, value in payload.items() if key != "messages"}
    messages: list[dict[str, Any]] = []
    for raw in payload.get("messages") or []:
        if not isinstance(raw, Mapping):
            continue
        trigger = raw.get("trigger") if isinstance(raw.get("trigger"), Mapping) else None
        brief = raw.get("article_brief") if isinstance(raw.get("article_brief"), Mapping) else None
        task = raw.get("task") if isinstance(raw.get("task"), Mapping) else None
        if trigger is None and brief is None and task is None:
            continue
        messages.append(
            sanitize_page_payload(
                {
                    "message_id": raw.get("message_id"),
                    "published_at": raw.get("published_at"),
                    "primary_url": raw.get("primary_url"),
                    "filter_status": raw.get("filter_status"),
                    "content_kind": raw.get("content_kind"),
                    "report_tags": raw.get("report_tags") or [],
                    "title": (brief or {}).get("headline"),
                    "summary": (brief or {}).get("analysis_summary"),
                    "trigger": trigger,
                    "article_brief": brief,
                    "task": task,
                    "blocked": raw.get("blocked"),
                    "actionable": raw.get("actionable"),
                }
            )
        )
    result["messages"] = messages
    result["page_layer"] = "ADS"
    return result


def _project_execution(payload: Mapping[str, Any], path: str) -> dict[str, Any]:
    if path.endswith("/events"):
        result = dict(payload)
        result["events"] = [
            {
                **{key: value for key, value in event.items() if key != "payload"},
                "payload": sanitize_page_payload(
                    {
                        key: value
                        for key, value in (event.get("payload") or {}).items()
                        if key in _SAFE_EVENT_PAYLOAD_KEYS
                    }
                ),
            }
            for event in payload.get("events") or []
            if isinstance(event, Mapping)
        ]
        return sanitize_page_payload(result)
    return sanitize_page_payload(payload)


def project_http_payload(path: str, payload: Any) -> Any:
    """Project one JSON response or reject a direct lower-layer lookup."""
    if not isinstance(payload, Mapping):
        return sanitize_page_payload(payload)

    if path == "/api/llm/audits":
        return {
            "count": payload.get("count", 0),
            "limit": payload.get("limit", 0),
            "offset": payload.get("offset", 0),
            "audits": [
                projected
                for projected in (_project_llm_audit_summary(item) for item in payload.get("audits") or [])
                if projected is not None
            ],
        }
    if re.fullmatch(r"/api/llm/audits/[^/]+", path):
        return _project_llm_audit_summary(payload) or {}
    if path == "/api/agent-analysis/inspect":
        return _project_agent_inspection(payload)
    if re.fullmatch(r"/api/reports/[^/]+/analysis-inputs", path):
        return _project_report_analysis_inputs(payload)

    if re.fullmatch(r"/api/artifacts/[^/]+", path):
        artifact = payload.get("artifact")
        if not is_page_artifact(artifact):
            raise PageBoundaryViolation("Lower-layer artifacts are not available to page clients")

    if path.startswith("/api/source-trace/by-artifact/"):
        requested_id = unquote(path.rsplit("/", 1)[-1])
        candidates = [
            payload.get("artifact"),
            *(payload.get("artifact_refs") or []),
            *(payload.get("related_artifacts") or []),
        ]
        for candidate in candidates:
            if isinstance(candidate, Mapping) and str(candidate.get("artifact_id")) == requested_id:
                if not is_page_artifact(candidate):
                    raise PageBoundaryViolation("Lower-layer artifacts are not available to page clients")

    if path == "/api/data-sources/status":
        return _project_data_source_status(payload)
    if path == "/api/data-sources/registry":
        return _project_data_source_registry(payload)
    if path.startswith("/api/ingestion/sources/") and path.endswith("/test"):
        result = sanitize_page_payload(payload)
        result["preview"] = []
        result["artifacts"] = {}
        result["page_layer"] = "ADS"
        return result
    if path == "/api/market/fedwatch/history":
        return _project_fedwatch_history(payload)
    if path in {"/api/news/feishu-jin10/messages", "/api/news/feishu-jin10/messages/latest"}:
        return _project_feishu_monitor(payload)
    if path == "/api/runs" or path.startswith("/api/runs/") or path.startswith("/api/artifacts/"):
        return _project_execution(payload, path)
    return sanitize_page_payload(payload)


class PageDataBoundaryMiddleware(BaseHTTPMiddleware):
    """Enforce the page projection after FastAPI response-model validation."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        path = request.url.path
        if not path.startswith("/api/") or response.status_code in {204, 304}:
            return response

        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        is_json = content_type == "application/json" or content_type.endswith("+json")
        if not is_json:
            if _is_allowed_page_file_route(path):
                return response
            return JSONResponse(
                {"detail": "API file response is not available to page clients", "status": "forbidden", "page_layer": "ADS"},
                status_code=403,
            )

        body = b"".join([chunk async for chunk in response.body_iterator])
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "content-type"}
        }
        try:
            payload = json.loads(body)
            projected = project_http_payload(path, payload)
        except PageBoundaryViolation as exc:
            return JSONResponse(
                {"detail": str(exc), "status": "forbidden", "page_layer": "ADS"},
                status_code=403,
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(
                {"detail": "Invalid JSON response", "status": "unavailable", "page_layer": "ADS"},
                status_code=500,
            )
        return JSONResponse(
            projected,
            status_code=response.status_code,
            headers=headers,
            background=response.background,
        )
