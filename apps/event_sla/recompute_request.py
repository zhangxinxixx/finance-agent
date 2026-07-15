from __future__ import annotations

import hashlib
import json
from typing import Any

from apps.event_sla.schemas import EventSnapshot


SCHEMA_NAME = "live_strategy_recompute_request"
SCHEMA_VERSION = "live_strategy_recompute_request.v1"
REQUESTED_ACTION = "recompute_live_strategy"


def build_live_strategy_recompute_request(
    *,
    event: EventSnapshot,
    observation_hash: str,
    evidence_level: str,
    event_status: str,
    quality_gate: dict[str, Any] | None,
    created_at: str,
) -> dict[str, Any]:
    quality_status, dispatch_status, reason_codes = _dispatch_decision(
        evidence_level=evidence_level,
        event_status=event_status,
        parsed_refs=event.parsed_refs,
        quality_gate=quality_gate,
    )
    contract_payload = {
        "schema_version": SCHEMA_VERSION,
        "requested_action": REQUESTED_ACTION,
        "event_id": event.event_id,
        "event_hash": event.event_hash,
        "observation_hash": observation_hash,
        "source_key": event.source_key,
        "trade_date": event.trade_date,
        "published_at": event.published_at,
        "evidence_level": evidence_level,
        "quality_status": quality_status,
        "source_refs": event.source_refs,
        "raw_refs": event.raw_refs,
        "parsed_refs": event.parsed_refs,
        "output_refs": event.output_refs,
        "dispatch_status": dispatch_status,
        "reason_codes": reason_codes,
    }
    request_id = _stable_request_id(contract_payload)
    return {
        "request_id": request_id,
        "schema_name": SCHEMA_NAME,
        **contract_payload,
        "detected_at": event.detected_at,
        "created_at": created_at,
    }


def _dispatch_decision(
    *,
    evidence_level: str,
    event_status: str,
    parsed_refs: list[dict[str, Any]],
    quality_gate: dict[str, Any] | None,
) -> tuple[str, str, list[str]]:
    reason_codes: list[str] = []
    if evidence_level != "full":
        reason_codes.append(f"evidence_{evidence_level}")
    if not parsed_refs:
        reason_codes.append("missing_parsed_refs")
    readiness = str((quality_gate or {}).get("readiness") or "allowed")
    quality_blocked = readiness == "blocked" or (quality_gate or {}).get("can_run_full_analysis") is False
    if quality_blocked:
        reason_codes.append("quality_gate_blocked")
    if event_status != "success":
        reason_codes.append(f"event_status_{event_status}")

    if reason_codes:
        return ("blocked" if quality_blocked else "degraded", "blocked", reason_codes)
    return "allowed", "pending", []


def _stable_request_id(contract_payload: dict[str, Any]) -> str:
    encoded = json.dumps(contract_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"{SCHEMA_NAME}_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:24]}"
