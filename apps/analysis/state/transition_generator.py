"""Model-assisted, scoped TransitionCandidate generation for the canary only."""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.analysis.agents.schemas import AcceptedStateConclusion
from apps.analysis.context_bundle import AnalysisContextBundle
from apps.analysis.prompts.state_transition import (
    build_state_transition_for_conclusion_prompt,
    build_state_transition_prompt,
)
from apps.analysis.state.hashing import content_hash
from apps.analysis.state.materializer import TransitionCandidate
from apps.analysis.state.schemas import DominantDriver


_DEFAULT_PROVIDER = "cockpit"
_DEFAULT_MODEL = "gpt-5.6-sol"
_DEFAULT_REASONING_EFFORT = "high"
_PROMPT_VERSION = "analysis_state_transition_candidate_v1"
_CONCLUSION_PROMPT_VERSION = "analysis_state_transition_for_conclusion_v1"
_CONCLUSION_TARGETS = frozenset(
    {"market_stage", "core_thesis", "net_bias", "dominant_drivers"}
)


class ScopedTransitionCandidate(BaseModel):
    """An untrusted candidate bound to exactly one immutable scoped Bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset: Literal["XAUUSD"]
    state_scope: Literal["daily_close"]
    run_id: str = Field(min_length=1)
    canonical_state_id: str = Field(min_length=1)
    context_bundle_id: str = Field(min_length=1)
    context_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate: TransitionCandidate

    @model_validator(mode="after")
    def validate_candidate_lineage(self) -> "ScopedTransitionCandidate":
        if self.candidate.previous_state_id != self.canonical_state_id:
            raise ValueError("candidate previous_state_id must match canonical_state_id")
        return self


def generate_scoped_transition_candidate(
    bundle: AnalysisContextBundle,
) -> ScopedTransitionCandidate:
    """Generate one validated canary candidate; never write state or choose authority."""

    _require_canary_scope(bundle)
    if _should_skip_live_llm():
        raise RuntimeError("state transition LLM is disabled")

    from apps.llm.gateway import chat_sync

    prompt_payload = bundle.model_dump(mode="json")
    response = chat_sync(
        messages=[
            {
                "role": "system",
                "content": (
                    "你只基于给定 Bundle 输出一个 TransitionCandidate JSON 对象；"
                    "不得写数据库、决定 QualityGate、补造证据或输出交易指令。"
                ),
            },
            {
                "role": "user",
                "content": build_state_transition_prompt(
                    canonical_state_id=bundle.canonical_state_id,
                    state_scope=str(bundle.state_scope),
                    bundle_payload=prompt_payload,
                ),
            },
        ],
        provider=_provider(),
        model=_model(),
        reasoning_effort=_reasoning_effort(),
        temperature=0.1,
        max_tokens=4096,
        json_mode=True,
        max_retries=0,
        audit_context={
            "caller": "state.transition_generator.generate_scoped_transition_candidate",
            "run_id": bundle.run_id,
            "snapshot_id": bundle.canonical_state_id,
            "trade_date": bundle.cutoff_at.date().isoformat(),
            "input_payload": {
                "prompt_version": _PROMPT_VERSION,
                "context_bundle_id": bundle.bundle_id,
                "context_bundle_hash": bundle.content_hash,
                "canonical_state_id": bundle.canonical_state_id,
                "state_scope": bundle.state_scope,
                "retained_evidence_refs": _retained_evidence_refs(bundle),
            },
        },
    )
    return ScopedTransitionCandidate(
        asset=bundle.asset,
        state_scope=bundle.state_scope,
        run_id=bundle.run_id,
        canonical_state_id=bundle.canonical_state_id,
        context_bundle_id=bundle.bundle_id,
        context_bundle_hash=bundle.content_hash,
        candidate=parse_transition_candidate_response(response.content),
    )


def generate_transition_candidate(bundle: AnalysisContextBundle) -> ScopedTransitionCandidate:
    """Return the scoped candidate; canary callers must retain Bundle identity."""

    return generate_scoped_transition_candidate(bundle)


def generate_scoped_transition_candidate_for_conclusion(
    bundle: AnalysisContextBundle,
    accepted_state_conclusion: AcceptedStateConclusion | dict[str, Any],
) -> ScopedTransitionCandidate:
    """Generate a candidate whose state semantics exactly match the accepted output."""

    _require_canary_scope(bundle)
    conclusion = AcceptedStateConclusion.model_validate(accepted_state_conclusion)
    target_patch = _conclusion_target_patch(conclusion)
    available_refs = _available_evidence_refs(bundle)
    if not available_refs:
        raise ValueError("conclusion-targeted transition requires retained Bundle evidence")
    if _should_skip_live_llm():
        raise RuntimeError("state transition LLM is disabled")

    from apps.llm.gateway import chat_sync

    prompt_payload = bundle.model_dump(mode="json")
    response = chat_sync(
        messages=[
            {
                "role": "system",
                "content": (
                    "你只基于给定 Bundle 输出一个与 accepted_state_conclusion 精确对齐的 "
                    "TransitionCandidate JSON；不得补造证据、修改系统元数据或决定写入权限。"
                ),
            },
            {
                "role": "user",
                "content": build_state_transition_for_conclusion_prompt(
                    canonical_state_id=bundle.canonical_state_id,
                    state_scope=str(bundle.state_scope),
                    bundle_payload=prompt_payload,
                    accepted_state_conclusion={
                        **conclusion.model_dump(mode="json"),
                        "dominant_drivers": target_patch["dominant_drivers"],
                    },
                ),
            },
        ],
        provider=_provider(),
        model=_model(),
        reasoning_effort=_reasoning_effort(),
        temperature=0.1,
        max_tokens=4096,
        json_mode=True,
        max_retries=0,
        audit_context={
            "caller": (
                "state.transition_generator."
                "generate_scoped_transition_candidate_for_conclusion"
            ),
            "run_id": bundle.run_id,
            "snapshot_id": bundle.canonical_state_id,
            "trade_date": bundle.cutoff_at.date().isoformat(),
            "input_payload": {
                "prompt_version": _CONCLUSION_PROMPT_VERSION,
                "context_bundle_id": bundle.bundle_id,
                "context_bundle_hash": bundle.content_hash,
                "canonical_state_id": bundle.canonical_state_id,
                "state_scope": bundle.state_scope,
                "accepted_state_conclusion_hash": content_hash(
                    conclusion.model_dump(mode="json"), exclude_keys=frozenset()
                ),
                "retained_evidence_refs": _retained_evidence_refs(bundle),
            },
        },
    )
    candidate = parse_transition_candidate_response(response.content)
    _validate_conclusion_candidate(
        candidate,
        target_patch=target_patch,
        available_refs=available_refs,
    )
    return ScopedTransitionCandidate(
        asset=bundle.asset,
        state_scope=bundle.state_scope,
        run_id=bundle.run_id,
        canonical_state_id=bundle.canonical_state_id,
        context_bundle_id=bundle.bundle_id,
        context_bundle_hash=bundle.content_hash,
        candidate=candidate,
    )


def parse_transition_candidate_response(content: str) -> TransitionCandidate:
    """Parse a JSON-only model response into the frozen candidate boundary."""

    normalized = str(content or "").strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        normalized = "\n".join(lines).strip()
    payload = json.loads(normalized)
    if not isinstance(payload, dict):
        raise ValueError("state transition LLM response must decode to an object")
    return TransitionCandidate.model_validate(payload)


def _require_canary_scope(bundle: AnalysisContextBundle) -> None:
    if bundle.asset != "XAUUSD" or bundle.state_scope != "daily_close":
        raise ValueError("state transition canary is limited to XAUUSD/daily_close")


def _retained_evidence_refs(bundle: AnalysisContextBundle) -> list[dict[str, str]]:
    block = next(item for item in bundle.blocks if item.name == "delta_evidence")
    return [
        {"source": str(item.get("source") or ""), "evidence_id": str(item.get("evidence_id") or "")}
        for item in block.payload
        if isinstance(item, dict)
    ]


def _conclusion_target_patch(conclusion: AcceptedStateConclusion) -> dict[str, Any]:
    drivers = [
        DominantDriver.model_validate(item).model_dump(mode="json")
        for item in conclusion.dominant_drivers
    ]
    return {
        "market_stage": conclusion.market_stage,
        "core_thesis": conclusion.core_thesis,
        "net_bias": conclusion.state_bias,
        "dominant_drivers": drivers,
    }


def _available_evidence_refs(bundle: AnalysisContextBundle) -> dict[str, dict[str, Any]]:
    available: dict[str, dict[str, Any]] = {}
    for block in bundle.blocks:
        if block.name not in {"delta_evidence", "facts"} or not isinstance(block.payload, list):
            continue
        for item in block.payload:
            if not isinstance(item, dict):
                continue
            ref = item.get("source_ref")
            if isinstance(ref, dict) and ref:
                available[_reference_key(ref)] = dict(ref)
    return available


def _validate_conclusion_candidate(
    candidate: TransitionCandidate,
    *,
    target_patch: dict[str, Any],
    available_refs: dict[str, dict[str, Any]],
) -> None:
    patch = candidate.state_patch.explicit_payload()
    if set(patch) != _CONCLUSION_TARGETS:
        raise ValueError("conclusion-targeted state_patch must contain exactly four semantic fields")
    if patch != target_patch:
        raise ValueError("conclusion-targeted state_patch does not match accepted conclusion")
    if {change.target for change in candidate.changes} != _CONCLUSION_TARGETS:
        raise ValueError("conclusion-targeted changes must account for all four semantic fields")
    refs = [
        *candidate.evidence_refs,
        *(ref for change in candidate.changes for ref in change.evidence_refs),
    ]
    if any(_reference_key(ref) not in available_refs for ref in refs):
        raise ValueError("conclusion-targeted transition references evidence outside the Bundle")


def _reference_key(value: dict[str, Any]) -> str:
    return content_hash(value, exclude_keys=frozenset())


def _provider() -> str:
    return os.getenv("STATE_TRANSITION_LLM_PROVIDER", _DEFAULT_PROVIDER).strip() or _DEFAULT_PROVIDER


def _model() -> str:
    return os.getenv("STATE_TRANSITION_LLM_MODEL", os.getenv("LLM_COCKPIT_MODEL", _DEFAULT_MODEL)).strip() or _DEFAULT_MODEL


def _reasoning_effort() -> str:
    return os.getenv("STATE_TRANSITION_LLM_REASONING_EFFORT", os.getenv("LLM_COCKPIT_REASONING_EFFORT", _DEFAULT_REASONING_EFFORT)).strip() or _DEFAULT_REASONING_EFFORT


def _should_skip_live_llm() -> bool:
    return os.getenv("FINANCE_AGENT_SKIP_LIVE_LLM", "").strip().lower() in {"1", "true", "yes"}
