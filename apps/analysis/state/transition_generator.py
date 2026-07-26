"""Model-assisted, scoped TransitionCandidate generation for the canary only."""

from __future__ import annotations

import json
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.analysis.context_bundle import AnalysisContextBundle
from apps.analysis.prompts.state_transition import build_state_transition_prompt
from apps.analysis.state.materializer import TransitionCandidate


_DEFAULT_PROVIDER = "cockpit"
_DEFAULT_MODEL = "gpt-5.6-sol"
_DEFAULT_REASONING_EFFORT = "high"
_PROMPT_VERSION = "analysis_state_transition_candidate_v1"


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


def _provider() -> str:
    return os.getenv("STATE_TRANSITION_LLM_PROVIDER", _DEFAULT_PROVIDER).strip() or _DEFAULT_PROVIDER


def _model() -> str:
    return os.getenv("STATE_TRANSITION_LLM_MODEL", os.getenv("LLM_COCKPIT_MODEL", _DEFAULT_MODEL)).strip() or _DEFAULT_MODEL


def _reasoning_effort() -> str:
    return os.getenv("STATE_TRANSITION_LLM_REASONING_EFFORT", os.getenv("LLM_COCKPIT_REASONING_EFFORT", _DEFAULT_REASONING_EFFORT)).strip() or _DEFAULT_REASONING_EFFORT


def _should_skip_live_llm() -> bool:
    return os.getenv("FINANCE_AGENT_SKIP_LIVE_LLM", "").strip().lower() in {"1", "true", "yes"}
