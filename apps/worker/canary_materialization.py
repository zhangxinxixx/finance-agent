"""Fail-closed contracts for the XAUUSD daily-close materialization canary.

This module deliberately does not schedule consumers, rebuild Bundles, or set
``state_delta_primary``.  An orchestrator may perform one fresh-Bundle retry
after a CAS conflict; this contract records its lineage and closes a second
conflict instead of retrying stale work.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.analysis.agents.quality_gate import AgentLoopDecision
from apps.analysis.agents.quality_gate_evaluator import QualityGateDecision
from apps.analysis.agents.schemas import AgentOutput
from apps.analysis.context_bundle.projection import ConsumerProjection
from apps.analysis.state import TransitionReviewResult, materialize_reviewed_transition_scoped
from apps.analysis.state.hashing import content_hash
from apps.analysis.state.repository import CanonicalHeadConflictError
from database.models.analysis_state import AnalysisState, AnalysisStateHead


logger = logging.getLogger(__name__)

CANARY_MATERIALIZATION_REQUEST_SCHEMA_VERSION = "analysis_state_canary_request.v2"
CANARY_MATERIALIZATION_RESULT_SCHEMA_VERSION = "analysis_state_canary_result.v2"
CANARY_ASSET = "XAUUSD"
CANARY_STATE_SCOPE = "daily_close"
CANARY_CONSUMERS = frozenset(
    {
        "macro",
        "options",
        "risk",
        "technical",
        "positioning",
        "news",
        "market_odds",
        "fact_review",
        "coordinator",
    }
)


class CanaryAuthorityPayload(BaseModel):
    """The exact reviewed consumer inputs authorizing one materialization.

    Hashes alone are not authority: the Materializer receives the fully
    validated projections plus the FactReview output and recomputes this
    immutable digest before it considers a PASS decision.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    context_bundle_id: str = Field(min_length=1)
    context_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(min_length=1)
    asset: Literal["XAUUSD"]
    state_scope: Literal["daily_close"]
    canonical_state_id: str = Field(min_length=1)
    consumer_projections: dict[str, ConsumerProjection]
    fact_review_output: AgentOutput
    authority_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_authority_payload(self) -> "CanaryAuthorityPayload":
        if set(self.consumer_projections) != CANARY_CONSUMERS:
            raise ValueError("authority payload must contain exactly the nine canary consumers")
        for name, projection in self.consumer_projections.items():
            identity = projection.identity_payload
            if projection.consumer != name:
                raise ValueError("authority projection key must match consumer")
            if (
                identity.bundle_id != self.context_bundle_id
                or identity.content_hash != self.context_bundle_hash
                or identity.run_id != self.run_id
                or identity.asset != self.asset
                or identity.state_scope != self.state_scope
                or identity.canonical_state_id != self.canonical_state_id
            ):
                raise ValueError("authority projection does not match Bundle identity")
        review = self.fact_review_output
        if review.agent_name != "fact_review_agent":
            raise ValueError("authority payload requires fact_review_agent output")
        fact_projection = self.consumer_projections["fact_review"]
        expected_input_ids = {
            "context_bundle_id": self.context_bundle_id,
            "context_bundle_hash": self.context_bundle_hash,
            "context_bundle_run_id": self.run_id,
            "context_bundle_projection_hash": fact_projection.projection_hash,
            "canonical_state_id": self.canonical_state_id,
            "state_scope": self.state_scope,
        }
        if any(review.input_snapshot_ids.get(key) != value for key, value in expected_input_ids.items()):
            raise ValueError("FactReview output does not match authority Bundle/projection")
        payload = review.input_payload or {}
        if (
            payload.get("context_bundle_consumer") != "fact_review"
            or payload.get("context_bundle_projection") != fact_projection.model_dump(mode="json")
        ):
            raise ValueError("FactReview output did not consume the exact authority projection")
        expected_hash = compute_canary_authority_hash(self)
        if self.authority_hash != expected_hash:
            raise ValueError("authority_hash does not match authority payload")
        return self

    @classmethod
    def build(
        cls,
        *,
        context_bundle_id: str,
        context_bundle_hash: str,
        run_id: str,
        canonical_state_id: str,
        consumer_projections: dict[str, ConsumerProjection],
        fact_review_output: AgentOutput,
    ) -> "CanaryAuthorityPayload":
        payload = {
            "context_bundle_id": context_bundle_id,
            "context_bundle_hash": context_bundle_hash,
            "run_id": run_id,
            "asset": CANARY_ASSET,
            "state_scope": CANARY_STATE_SCOPE,
            "canonical_state_id": canonical_state_id,
            "consumer_projections": consumer_projections,
            "fact_review_output": fact_review_output,
        }
        return cls(authority_hash=_hash_payload(payload), **payload)


class CanaryActivation(BaseModel):
    """Explicit, auditable authority for one XAUUSD/daily-close canary run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset: Literal["XAUUSD"]
    trade_date: date
    run_id: str = Field(min_length=1)
    state_scope: Literal["daily_close"]
    canonical_state_id: str = Field(min_length=1)
    expected_head_version: int = Field(ge=0)
    activation_source: Literal["exact_trade_date", "exact_run_id", "manual_request"]
    activation_identity: str = Field(min_length=1)


class CanaryMaterializationRequest(BaseModel):
    """Scoped hand-off after FactReview and before the single CAS attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["analysis_state_canary_request.v2"] = (
        CANARY_MATERIALIZATION_REQUEST_SCHEMA_VERSION
    )
    asset: Literal["XAUUSD"]
    trade_date: date
    run_id: str = Field(min_length=1)
    state_scope: Literal["daily_close"]
    canonical_state_id: str = Field(min_length=1)
    expected_head_version: int = Field(ge=0)
    activation_source: Literal["exact_trade_date", "exact_run_id", "manual_request"]
    activation_identity: str = Field(min_length=1)
    context_bundle_id: str = Field(min_length=1)
    context_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    consumer_projection_hashes: dict[str, str]
    fact_review_snapshot_id: str = Field(min_length=1)
    quality_gate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    agent_loop_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    manual_request: dict[str, Any] | None = None
    review: TransitionReviewResult

    @field_validator(
        "run_id",
        "canonical_state_id",
        "activation_identity",
        "context_bundle_id",
        "fact_review_snapshot_id",
    )
    @classmethod
    def strip_required_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("canary request identity must not be blank")
        return normalized

    @field_validator("consumer_projection_hashes")
    @classmethod
    def validate_consumer_projection_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != CANARY_CONSUMERS:
            raise ValueError("consumer_projection_hashes must contain exactly the nine canary consumers")
        normalized: dict[str, str] = {}
        for consumer, projection_hash in value.items():
            digest = str(projection_hash).strip().lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError(f"consumer projection hash is invalid: {consumer}")
            normalized[consumer] = digest
        return normalized

    @model_validator(mode="after")
    def validate_review_lineage(self) -> "CanaryMaterializationRequest":
        if self.review.previous_state_id != self.canonical_state_id:
            raise ValueError("review previous_state_id must match canary canonical_state_id")
        if self.review.next_state.asset != self.asset:
            raise ValueError("review asset must match canary asset")
        if getattr(self.review.next_state, "state_scope", None) != self.state_scope:
            raise ValueError("review state_scope must match canary state_scope")
        if self.activation_source == "exact_trade_date":
            if self.activation_identity != self.trade_date.isoformat() or self.manual_request is not None:
                raise ValueError("exact_trade_date activation must bind its request trade_date")
        elif self.activation_source == "exact_run_id":
            if self.activation_identity != self.run_id or self.manual_request is not None:
                raise ValueError("exact_run_id activation must bind its request run_id")
        else:
            if not isinstance(self.manual_request, dict):
                raise ValueError("manual_request activation requires its structured request")
            if not self.activation_identity.startswith("manual:"):
                raise ValueError("manual_request activation identity must be manual:<request_id>")
            _validate_manual_request_binding(
                self.manual_request,
                asset=self.asset,
                trade_date=self.trade_date,
                run_id=self.run_id,
                expected_identity=self.activation_identity,
            )
        return self


class CanaryMaterializationResult(BaseModel):
    """Audit result that never replaces or invalidates legacy output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["analysis_state_canary_result.v2"] = (
        CANARY_MATERIALIZATION_RESULT_SCHEMA_VERSION
    )
    status: Literal[
        "canonical_advanced",
        "candidate_recorded",
        "observe_only",
        "recompute_required",
        "failed",
    ]
    asset: Literal["XAUUSD"]
    trade_date: date
    run_id: str = Field(min_length=1)
    state_scope: Literal["daily_close"]
    activation_source: Literal["exact_trade_date", "exact_run_id", "manual_request"]
    activation_identity: str = Field(min_length=1)
    context_bundle_id: str = Field(min_length=1)
    context_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_canonical_state_id: str = Field(min_length=1)
    expected_head_version: int = Field(ge=0)
    legacy_output_preserved: Literal[True] = True
    canonical_advanced: bool = False
    candidate_state_id: str | None = None
    canonical_state_id: str | None = None
    canonical_version: int | None = None
    recompute_required: bool = False
    latest_canonical_state_id: str | None = None
    latest_head_version: int | None = None
    materialization_disposition: str | None = None
    reason: str | None = None
    recompute_attempt_count: int = Field(default=0, ge=0, le=1)
    superseded_context_bundle_id: str | None = None
    superseded_context_bundle_hash: str | None = None
    superseded_canonical_state_id: str | None = None
    recompute_trace: dict[str, Any] | None = None
    authority_hash: str | None = None
    consumer_projection_hashes: dict[str, str] = Field(default_factory=dict)
    fact_review_snapshot_id: str | None = None
    quality_gate_hash: str | None = None
    agent_loop_hash: str | None = None
    attempt_audit_path: str | None = None
    attempt_audit_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_status_flags(self) -> "CanaryMaterializationResult":
        if self.canonical_advanced != (self.status == "canonical_advanced"):
            raise ValueError("canonical_advanced must match result status")
        if self.recompute_required != (self.status == "recompute_required"):
            raise ValueError("recompute_required must match result status")
        supersession = (
            self.superseded_context_bundle_id,
            self.superseded_context_bundle_hash,
            self.superseded_canonical_state_id,
        )
        if self.recompute_attempt_count == 0 and any(supersession):
            raise ValueError("supersession lineage requires a recompute attempt")
        if self.recompute_attempt_count == 1 and not all(supersession):
            raise ValueError("recompute attempt requires complete supersession lineage")
        if self.recompute_trace is not None and self.recompute_attempt_count != 1:
            raise ValueError("recompute trace requires a recompute attempt")
        if self.status in {"canonical_advanced", "candidate_recorded"}:
            if self.authority_hash is None or set(self.consumer_projection_hashes) != CANARY_CONSUMERS:
                raise ValueError("authoritative materialization result requires complete authority lineage")
            if not all((self.fact_review_snapshot_id, self.quality_gate_hash, self.agent_loop_hash)):
                raise ValueError("authoritative materialization result requires FactReview/Gate lineage")
        return self


def resolve_canary_activation(
    *,
    snapshot_asset: Any,
    snapshot_trade_date: Any,
    run_id: Any,
    shadow_input: dict[str, Any] | None,
) -> CanaryActivation | None:
    """Resolve only explicit exact-date, exact-run, or structured manual authority.

    ``canary_enabled`` is intentionally rejected: a boolean cannot identify a
    date/run or provide an auditable approval record.
    """

    if not isinstance(shadow_input, dict):
        return None
    control_keys = {"canary_trade_dates", "canary_run_ids", "canary_manual_request", "canary_enabled"}
    if not any(key in shadow_input for key in control_keys):
        return None
    if "canary_enabled" in shadow_input:
        raise ValueError("canary_enabled is not a valid canary activation control")

    asset = _required_text(snapshot_asset, field="snapshot_asset")
    trade_date = _date_value(snapshot_trade_date, field="snapshot_trade_date")
    normalized_run_id = _required_text(run_id, field="run_id")
    if asset != CANARY_ASSET:
        raise ValueError("canary activation is limited to asset=XAUUSD")
    if _required_text(shadow_input.get("asset"), field="asset") != asset:
        raise ValueError("canary asset must match analysis snapshot asset")
    if _date_value(shadow_input.get("trade_date"), field="trade_date") != trade_date:
        raise ValueError("canary trade_date must match analysis snapshot trade_date")
    if shadow_input.get("state_scope") != CANARY_STATE_SCOPE:
        raise ValueError("canary activation is limited to state_scope=daily_close")
    canonical_state_id = _required_text(shadow_input.get("canonical_state_id"), field="canonical_state_id")
    expected_head_version = shadow_input.get("expected_head_version")
    if isinstance(expected_head_version, bool) or not isinstance(expected_head_version, int) or expected_head_version < 0:
        raise ValueError("canary expected_head_version must be a non-negative integer")

    matches: list[tuple[str, str]] = []
    if trade_date in _date_allowlist(shadow_input.get("canary_trade_dates")):
        matches.append(("exact_trade_date", trade_date.isoformat()))
    if normalized_run_id in _run_allowlist(shadow_input.get("canary_run_ids")):
        matches.append(("exact_run_id", normalized_run_id))
    manual = shadow_input.get("canary_manual_request")
    if manual is not None and _manual_request_matches(
        manual, asset=asset, trade_date=trade_date, run_id=normalized_run_id
    ):
        matches.append(("manual_request", f"manual:{_required_text(manual.get('request_id'), field='manual request_id')}"))
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("canary activation must use exactly one explicit control")
    source, identity = matches[0]
    return CanaryActivation(
        asset=asset,
        trade_date=trade_date,
        run_id=normalized_run_id,
        state_scope=CANARY_STATE_SCOPE,
        canonical_state_id=canonical_state_id,
        expected_head_version=expected_head_version,
        activation_source=source,
        activation_identity=identity,
    )


def materialize_canary_request(
    session: Session,
    *,
    request: CanaryMaterializationRequest | dict[str, Any],
    quality_gate: QualityGateDecision | dict[str, Any],
    agent_loop: AgentLoopDecision | dict[str, Any],
    task_run_id: str,
    analysis_snapshot_db_id: str | None = None,
    authority_payload: CanaryAuthorityPayload | dict[str, Any] | None = None,
) -> CanaryMaterializationResult:
    """Apply one scoped CAS attempt; stale state yields an auditable retry request."""

    validated = CanaryMaterializationRequest.model_validate(
        request.model_dump(mode="json") if isinstance(request, BaseModel) else request
    )
    if _required_text(task_run_id, field="task_run_id") != validated.run_id:
        raise ValueError("canary materialization task_run_id must match request run_id")
    audit = _audit_fields(validated)
    try:
        authority = _validate_authority_payload(validated, authority_payload)
    except ValueError as exc:
        return CanaryMaterializationResult(
            status="failed", **audit, reason=f"authority_binding_invalid:{str(exc)[:160]}"
        )
    gate = QualityGateDecision.model_validate(
        quality_gate.model_dump(mode="json", exclude_computed_fields=True)
        if isinstance(quality_gate, QualityGateDecision)
        else quality_gate
    )
    loop = AgentLoopDecision.model_validate(
        agent_loop.model_dump(mode="json", exclude_computed_fields=True)
        if isinstance(agent_loop, AgentLoopDecision)
        else agent_loop
    )
    if validated.quality_gate_hash != compute_canary_quality_gate_hash(
        gate, authority_hash=authority.authority_hash
    ):
        return CanaryMaterializationResult(
            status="failed", **audit, reason="canary quality_gate_hash does not match supplied authority-bound QualityGate"
        )
    if validated.agent_loop_hash != compute_canary_agent_loop_hash(
        loop, authority_hash=authority.authority_hash
    ):
        return CanaryMaterializationResult(
            status="failed", **audit, reason="canary agent_loop_hash does not match supplied authority-bound AgentLoop"
        )
    try:
        # Repository append and head CAS are one outer savepoint: a stale CAS
        # rolls back both the new state and its transition before returning.
        with session.begin_nested():
            result = materialize_reviewed_transition_scoped(
                session,
                state_scope=validated.state_scope,
                review=validated.review,
                quality_gate=gate,
                agent_loop=loop,
                task_run_id=validated.run_id,
                expected_head_version=validated.expected_head_version,
                analysis_snapshot_db_id=analysis_snapshot_db_id,
            )
    except CanonicalHeadConflictError:
        session.expire_all()
        latest = _get_latest_head(session)
        return CanaryMaterializationResult(
            status="recompute_required",
            **audit,
            recompute_required=True,
            latest_canonical_state_id=latest.canonical_state_id if latest else None,
            latest_head_version=latest.version if latest else None,
            reason="canonical_head_compare_and_swap_conflict",
        )
    except Exception as exc:
        logger.exception("Canary AnalysisState materialization failed")
        return CanaryMaterializationResult(
            status="failed",
            **audit,
            reason=f"{type(exc).__name__}:canary_materialization_failed",
        )

    if result.canonical_advanced:
        return CanaryMaterializationResult(
            status="canonical_advanced",
            **audit,
            canonical_advanced=True,
            candidate_state_id=result.state_id,
            canonical_state_id=result.canonical_state_id,
            canonical_version=result.canonical_version,
            materialization_disposition=result.disposition,
        )
    if result.disposition == "manual_review_candidate":
        return CanaryMaterializationResult(
            status="candidate_recorded",
            **audit,
            candidate_state_id=result.state_id,
            materialization_disposition=result.disposition,
        )
    return CanaryMaterializationResult(
        status="observe_only", **audit, materialization_disposition=result.disposition
    )


def mark_canary_recompute_result(
    result: CanaryMaterializationResult | dict[str, Any],
    *,
    superseded: CanaryMaterializationResult | dict[str, Any],
    trace: dict[str, Any] | None = None,
) -> CanaryMaterializationResult:
    """Attach one-hop lineage and fail closed if that fresh attempt also conflicts."""

    validated = CanaryMaterializationResult.model_validate(result)
    previous = CanaryMaterializationResult.model_validate(superseded)
    if previous.status != "recompute_required" or previous.recompute_attempt_count != 0:
        raise ValueError("recompute requires an initial recompute_required result")
    payload = {
        **validated.model_dump(mode="json"),
        "recompute_attempt_count": 1,
        "superseded_context_bundle_id": previous.context_bundle_id,
        "superseded_context_bundle_hash": previous.context_bundle_hash,
        "superseded_canonical_state_id": previous.requested_canonical_state_id,
        "recompute_trace": trace,
    }
    if validated.status == "recompute_required":
        payload.update(
            status="failed",
            recompute_required=False,
            reason="canonical_head_compare_and_swap_conflict_after_recompute",
        )
    return CanaryMaterializationResult.model_validate(payload)


def failed_canary_materialization_result(
    request: CanaryMaterializationRequest | dict[str, Any], *, reason: str
) -> CanaryMaterializationResult:
    """Build a fail-closed result without attempting any write."""

    validated = CanaryMaterializationRequest.model_validate(
        request.model_dump(mode="json") if isinstance(request, BaseModel) else request
    )
    return CanaryMaterializationResult(status="failed", **_audit_fields(validated), reason=str(reason)[:200])


def prepare_canary_recompute_shadow_input(
    session: Session,
    *,
    conflict_result: CanaryMaterializationResult | dict[str, Any],
    shadow_input: dict[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    """Rebase one bounded retry input on the latest exact scoped head.

    This function only prepares input. The Runner must execute a complete new
    Composite attempt so the fresh Bundle is consumed by all nine consumers
    and receives fresh FactReview/QualityGate authority.
    """

    conflict = CanaryMaterializationResult.model_validate(conflict_result)
    if conflict.status != "recompute_required" or conflict.recompute_attempt_count != 0:
        raise ValueError("canary recompute requires an initial recompute_required result")
    if not isinstance(shadow_input.get("evidence"), list):
        raise ValueError("fresh canary recompute requires explicit evidence")
    session.expire_all()
    latest = _get_latest_head(session)
    if latest is None:
        raise ValueError("latest scoped canonical head is unavailable")
    if (
        latest.canonical_state_id != conflict.latest_canonical_state_id
        or latest.version != conflict.latest_head_version
    ):
        raise CanonicalHeadConflictError("scoped canonical head changed before recompute preparation")
    latest_state = session.get(AnalysisState, latest.canonical_state_id)
    if latest_state is None:
        raise ValueError("latest scoped canonical state is unavailable")
    if latest_state.asset != CANARY_ASSET or latest_state.state_scope != CANARY_STATE_SCOPE:
        raise ValueError("latest canonical state does not match canary scope")
    payload = dict(latest_state.payload or {})
    if _date_value(payload.get("trade_date"), field="latest_state.trade_date") != conflict.trade_date:
        raise ValueError("latest canonical trade_date changed; stale run cannot recompute")

    refreshed = dict(shadow_input)
    for key in (
        "context_bundle_artifact",
        "previous_context_bundle_artifact",
        "previous_bundle_path",
        "previous_semantic_hashes",
        "deferred_queue",
        "processed_above_frontier",
    ):
        refreshed.pop(key, None)
    refreshed.update(
        {
            "asset": CANARY_ASSET,
            "state_scope": CANARY_STATE_SCOPE,
            "canonical_state_id": latest_state.id,
            "canonical_state": payload,
            "expected_head_version": latest.version,
            "evidence_cursors": dict(latest_state.evidence_cursors or payload.get("evidence_cursors") or {}),
            "previous_semantic_hashes": {},
            "deferred_queue": (),
            "processed_above_frontier": {},
            "assembled_at": created_at,
        }
    )
    return refreshed


def build_canary_recompute_registry_descriptor(
    descriptor: dict[str, Any],
    *,
    conflict_result: CanaryMaterializationResult | dict[str, Any],
) -> dict[str, Any]:
    """Attach the one-hop predecessor authority to a fresh Bundle descriptor."""

    conflict = CanaryMaterializationResult.model_validate(conflict_result)
    if conflict.status != "recompute_required" or conflict.recompute_attempt_count != 0:
        raise ValueError("canary recompute descriptor requires an initial conflict")
    metadata = descriptor.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("fresh Bundle registry descriptor is incomplete")
    if metadata.get("canonical_state_id") != conflict.latest_canonical_state_id:
        raise ValueError("fresh Bundle canonical state does not match latest scoped head")
    return {
        **descriptor,
        "metadata": {
            **metadata,
            "artifact_role": "canary_recompute",
            "canary_recompute_attempt": 1,
            "supersedes_bundle_id": conflict.context_bundle_id,
            "supersedes_bundle_hash": conflict.context_bundle_hash,
            "supersedes_canonical_state_id": conflict.requested_canonical_state_id,
        },
    }


def _audit_fields(request: CanaryMaterializationRequest) -> dict[str, Any]:
    return {
        "asset": request.asset,
        "trade_date": request.trade_date,
        "run_id": request.run_id,
        "state_scope": request.state_scope,
        "activation_source": request.activation_source,
        "activation_identity": request.activation_identity,
        "context_bundle_id": request.context_bundle_id,
        "context_bundle_hash": request.context_bundle_hash,
        "requested_canonical_state_id": request.canonical_state_id,
        "expected_head_version": request.expected_head_version,
        "authority_hash": request.authority_hash,
        "consumer_projection_hashes": dict(request.consumer_projection_hashes),
        "fact_review_snapshot_id": request.fact_review_snapshot_id,
        "quality_gate_hash": request.quality_gate_hash,
        "agent_loop_hash": request.agent_loop_hash,
    }


def _get_latest_head(session: Session) -> AnalysisStateHead | None:
    return session.scalar(
        select(AnalysisStateHead).where(
            AnalysisStateHead.asset == CANARY_ASSET,
            AnalysisStateHead.state_scope == CANARY_STATE_SCOPE,
        )
    )


def compute_canary_quality_gate_hash(
    value: QualityGateDecision | dict[str, Any],
    *,
    authority_hash: str | None = None,
) -> str:
    """Return the stable QualityGate digest required in a canary request."""

    gate = QualityGateDecision.model_validate(
        value.model_dump(mode="json", exclude_computed_fields=True)
        if isinstance(value, QualityGateDecision)
        else value
    )
    return _hash_payload(
        {"quality_gate": gate.model_dump(mode="json", exclude_computed_fields=True), "authority_hash": authority_hash}
    )


def compute_canary_agent_loop_hash(
    value: AgentLoopDecision | dict[str, Any],
    *,
    authority_hash: str | None = None,
) -> str:
    """Return the stable AgentLoop digest required in a canary request."""

    loop = AgentLoopDecision.model_validate(
        value.model_dump(mode="json", exclude_computed_fields=True)
        if isinstance(value, AgentLoopDecision)
        else value
    )
    return _hash_payload(
        {"agent_loop": loop.model_dump(mode="json", exclude_computed_fields=True), "authority_hash": authority_hash}
    )


def _stable_hash(value: BaseModel) -> str:
    return content_hash(value.model_dump(mode="json", exclude_computed_fields=True), exclude_keys=frozenset())


def compute_canary_authority_hash(
    value: CanaryAuthorityPayload | dict[str, Any],
) -> str:
    """Stable digest over the exact FactReview output and nine projections."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    payload.pop("authority_hash", None)
    return _hash_payload(payload)


def _hash_payload(value: dict[str, Any]) -> str:
    return content_hash(value, exclude_keys=frozenset())


def _validate_authority_payload(
    request: CanaryMaterializationRequest,
    payload: CanaryAuthorityPayload | dict[str, Any] | None,
) -> CanaryAuthorityPayload:
    if payload is None:
        raise ValueError("authority payload is required")
    authority = CanaryAuthorityPayload.model_validate(
        payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    )
    if request.authority_hash != authority.authority_hash:
        raise ValueError("request authority_hash does not match authority payload")
    if (
        authority.context_bundle_id != request.context_bundle_id
        or authority.context_bundle_hash != request.context_bundle_hash
        or authority.run_id != request.run_id
        or authority.canonical_state_id != request.canonical_state_id
    ):
        raise ValueError("authority payload does not match request Bundle lineage")
    hashes = {
        name: projection.projection_hash
        for name, projection in authority.consumer_projections.items()
    }
    if hashes != request.consumer_projection_hashes:
        raise ValueError("request projection hashes do not match authority payload")
    if authority.fact_review_output.snapshot_id != request.fact_review_snapshot_id:
        raise ValueError("request FactReview snapshot does not match authority payload")
    return authority


def _date_value(value: Any, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO date") from exc
    raise ValueError(f"{field} must be an ISO date")


def _required_text(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _date_allowlist(value: Any) -> set[date]:
    if value is None:
        return set()
    if not isinstance(value, list):
        raise ValueError("canary_trade_dates must be a list of ISO dates")
    return {_date_value(item, field="canary_trade_dates") for item in value}


def _run_allowlist(value: Any) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list):
        raise ValueError("canary_run_ids must be a list of run IDs")
    return {_required_text(item, field="canary_run_ids") for item in value}


def _manual_request_matches(
    value: Any, *, asset: str, trade_date: date, run_id: str
) -> bool:
    if not isinstance(value, dict):
        raise ValueError("canary_manual_request must be an object")
    _validate_manual_request_binding(
        value,
        asset=asset,
        trade_date=trade_date,
        run_id=run_id,
        expected_identity=None,
    )
    requested_date = value.get("trade_date")
    requested_run = value.get("run_id")
    if requested_date is not None and _date_value(requested_date, field="manual trade_date") != trade_date:
        return False
    if requested_run is not None and _required_text(requested_run, field="manual run_id") != run_id:
        return False
    return True


def _validate_manual_request_binding(
    value: dict[str, Any],
    *,
    asset: str,
    trade_date: date,
    run_id: str,
    expected_identity: str | None,
) -> None:
    request_id = _required_text(value.get("request_id"), field="manual request_id")
    if expected_identity is not None and expected_identity != f"manual:{request_id}":
        raise ValueError("manual_request identity does not match request_id")
    if _required_text(value.get("asset"), field="manual asset") != asset:
        raise ValueError("manual request asset must match analysis snapshot asset")
    if value.get("state_scope") != CANARY_STATE_SCOPE:
        raise ValueError("manual request state_scope must be daily_close")
    requested_date = value.get("trade_date")
    requested_run = value.get("run_id")
    if requested_date is None and requested_run is None:
        raise ValueError("manual request must bind an exact trade_date or run_id")
    if requested_date is not None and _date_value(requested_date, field="manual trade_date") != trade_date:
        raise ValueError("manual request trade_date does not match request")
    if requested_run is not None and _required_text(requested_run, field="manual run_id") != run_id:
        raise ValueError("manual request run_id does not match request")
