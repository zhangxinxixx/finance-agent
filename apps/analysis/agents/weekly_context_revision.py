from __future__ import annotations

import json
import os
from typing import Any, Mapping

from apps.analysis.agents.weekly_context_revision_prompt import build_weekly_context_revision_prompt_template
from apps.renderer.contracts import WeeklyContextRevisionPayload

_DEFAULT_PROVIDER = "jojocode"
_DEFAULT_MODEL = "gpt-5.6-sol"
_DEFAULT_REASONING_EFFORT = "high"
_PROMPT_VERSION = "weekly_context_revision_agent_v1"


def invoke_weekly_context_revision_llm(payload: WeeklyContextRevisionPayload) -> dict[str, Any]:
    from apps.llm.gateway import chat_sync

    if _should_skip_live_llm():
        return {
            "skipped": True,
            "payload": None,
            "model": None,
            "provider": None,
            "reasoning_effort": None,
            "prompt_version": _PROMPT_VERSION,
        }
    provider = os.getenv("WEEKLY_CONTEXT_REVISION_LLM_PROVIDER", _DEFAULT_PROVIDER).strip() or _DEFAULT_PROVIDER
    model = os.getenv("WEEKLY_CONTEXT_REVISION_LLM_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    reasoning_effort = (
        os.getenv("WEEKLY_CONTEXT_REVISION_LLM_REASONING_EFFORT", _DEFAULT_REASONING_EFFORT).strip()
        or _DEFAULT_REASONING_EFFORT
    )
    prompt = (
        f"{build_weekly_context_revision_prompt_template()}\n\n"
        "=== 已验证结构化输入 ===\n"
        f"{json.dumps(_compact_prompt_payload(payload), ensure_ascii=False, indent=2)}\n"
    )
    response = chat_sync(
        messages=[
            {"role": "system", "content": "你只输出符合约束的 JSON 对象。"},
            {"role": "user", "content": prompt},
        ],
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        temperature=0.2,
        max_tokens=4096,
        json_mode=True,
        max_retries=1,
        request_timeout=_request_timeout(),
        audit_context={
            "caller": "weekly_context_revision.invoke_weekly_context_revision_llm",
            "trade_date": payload.trade_date,
            "report_id": f"weekly_context_revision:{payload.trade_date}:{payload.anchor.article_id}",
            "input_payload": _compact_prompt_payload(payload),
        },
    )
    return {
        "skipped": False,
        "payload": _parse_json_object(response.content),
        "model": response.model,
        "provider": response.provider,
        "reasoning_effort": response.reasoning_effort,
        "prompt_version": _PROMPT_VERSION,
        "latency_ms": response.latency_ms,
        "tokens": response.usage,
        "audit_id": getattr(response, "audit_id", None),
    }


def apply_weekly_context_revision_llm(
    deterministic: WeeklyContextRevisionPayload,
    result: Mapping[str, Any],
) -> WeeklyContextRevisionPayload:
    if result.get("skipped"):
        payload = deterministic.model_dump(mode="json")
        payload["analysis_provenance"] = {
            "source": "deterministic_fallback",
            "model": None,
            "provider": None,
            "reasoning_effort": None,
            "prompt_version": result.get("prompt_version"),
            "llm_status": "skipped",
        }
        return WeeklyContextRevisionPayload.model_validate(payload)

    llm_payload = result.get("payload")
    if not isinstance(llm_payload, Mapping):
        raise ValueError("weekly revision LLM response must be a JSON object")
    summary = str(llm_payload.get("executive_summary") or "").strip()
    revisions = llm_payload.get("claim_revisions")
    if not summary or not isinstance(revisions, list):
        raise ValueError("weekly revision LLM response is missing executive_summary or claim_revisions")

    deterministic_by_id = {item.claim_id: item for item in deterministic.claim_revisions}
    llm_by_id: dict[str, Mapping[str, Any]] = {}
    for item in revisions:
        if not isinstance(item, Mapping):
            raise ValueError("weekly revision LLM claim revision must be an object")
        claim_id = str(item.get("claim_id") or "")
        if claim_id not in deterministic_by_id or claim_id in llm_by_id:
            raise ValueError(f"weekly revision LLM returned invalid claim_id: {claim_id}")
        llm_by_id[claim_id] = item
    if set(llm_by_id) != set(deterministic_by_id):
        raise ValueError("weekly revision LLM must return every existing claim_id exactly once")

    allowed_actions = {"maintain", "strengthen", "weaken", "invalidate", "pending"}
    merged_revisions: list[dict[str, Any]] = []
    for claim_id, existing in deterministic_by_id.items():
        candidate = llm_by_id[claim_id]
        action = str(candidate.get("action") or "")
        reason = str(candidate.get("reason") or "").strip()
        if action not in allowed_actions or not reason:
            raise ValueError(f"weekly revision LLM returned invalid action/reason for {claim_id}")
        merged = existing.model_dump(mode="json")
        merged["action"] = action
        merged["reason"] = reason
        merged_revisions.append(merged)

    payload = deterministic.model_dump(mode="json")
    payload["executive_summary"] = summary
    payload["claim_revisions"] = merged_revisions
    payload["analysis_provenance"] = {
        "source": "llm_structured_revision",
        "model": result.get("model"),
        "provider": result.get("provider"),
        "reasoning_effort": result.get("reasoning_effort"),
        "prompt_version": result.get("prompt_version"),
        "llm_status": "accepted",
        "latency_ms": result.get("latency_ms"),
        "tokens": result.get("tokens"),
        "audit_id": result.get("audit_id"),
    }
    return WeeklyContextRevisionPayload.model_validate(payload)


def mark_weekly_context_revision_llm_failure(
    deterministic: WeeklyContextRevisionPayload,
    exc: Exception,
) -> WeeklyContextRevisionPayload:
    payload = deterministic.model_dump(mode="json")
    flags = list(payload["revision_risk"].get("quality_flags") or [])
    if "llm_error" not in flags:
        flags.append("llm_error")
    payload["revision_risk"]["quality_flags"] = flags
    payload["revision_risk"]["level"] = "needs_review"
    payload["revision_risk"]["reason"] = "gpt-5.6-sol/high 结构化修正失败，当前仅保留确定性 fallback。"
    payload["quality_status"] = "needs_review"
    payload["publication_status"] = "observe"
    payload["publish_allowed"] = False
    payload["analysis_provenance"] = {
        "source": "deterministic_fallback_after_llm_error",
        "model": os.getenv("WEEKLY_CONTEXT_REVISION_LLM_MODEL", _DEFAULT_MODEL),
        "provider": os.getenv("WEEKLY_CONTEXT_REVISION_LLM_PROVIDER", _DEFAULT_PROVIDER),
        "reasoning_effort": os.getenv(
            "WEEKLY_CONTEXT_REVISION_LLM_REASONING_EFFORT",
            _DEFAULT_REASONING_EFFORT,
        ),
        "prompt_version": _PROMPT_VERSION,
        "llm_status": "error",
        "error_type": type(exc).__name__,
        "error_message": str(exc)[:500],
        "audit_id": None,
    }
    return WeeklyContextRevisionPayload.model_validate(payload)


def _parse_json_object(text: str) -> dict[str, Any]:
    normalized = text.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        lines = lines[1:] if lines else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()
    payload = json.loads(normalized)
    if not isinstance(payload, dict):
        raise ValueError("weekly revision LLM response must decode to an object")
    return payload


def _compact_prompt_payload(payload: WeeklyContextRevisionPayload) -> dict[str, Any]:
    compact = payload.model_dump(mode="json")
    compact["dominant_transmission_chain"] = {
        key: value
        for key, value in compact.get("dominant_transmission_chain", {}).items()
        if key
        in {
            "status",
            "label",
            "dominant_driver",
            "net_effect",
            "path_id",
            "conclusion_code",
            "conclusion_label",
            "summary",
        }
    }
    compact["source_refs"] = [
        {
            key: ref.get(key)
            for key in ("source", "source_ref", "source_type", "title", "published_at")
            if ref.get(key) is not None
        }
        for ref in compact.get("source_refs", [])[:20]
        if isinstance(ref, Mapping)
    ]
    return compact


def _request_timeout() -> float:
    try:
        value = float(os.getenv("WEEKLY_CONTEXT_REVISION_LLM_REQUEST_TIMEOUT", "180"))
    except ValueError:
        return 180.0
    return value if value > 0 else 180.0


def _should_skip_live_llm() -> bool:
    if os.getenv("FINANCE_AGENT_FORCE_LIVE_LLM", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return "PYTEST_CURRENT_TEST" in os.environ
