"""Deterministic first-state bootstrap, recovery, and legacy retirement gates."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.analysis.agents.quality_gate import AgentLoopDecision
from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
from apps.analysis.state.hashing import canonical_json, content_hash
from apps.analysis.state.repository import (
    CanonicalHeadConflictError,
    advance_canonical_head,
    append_analysis_state,
    get_canonical_state,
)
from apps.analysis.state.schemas import (
    AnalysisStateDocument,
    AnalysisTransitionDocument,
    StateChange,
    StateMaterializationAuthority,
    TransitionAction,
)
from database.models.analysis import FinalAnalysisResult
from database.models.analysis_state import AnalysisStateHead


BOOTSTRAP_SCHEMA_VERSION = "analysis_state_bootstrap.v1"
RECOVERY_SCHEMA_VERSION = "analysis_state_recovery.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BootstrapContractError(ValueError):
    """Accepted artifacts are missing, contradictory, or unsafe to bootstrap."""


class BootstrapApproval(BaseModel):
    """Optional explicit human approval bound to one candidate hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_hash: str
    reviewer: str = Field(min_length=1, max_length=128)
    reviewed_at: datetime
    note: str = Field(default="", max_length=1000)

    @field_validator("candidate_hash")
    @classmethod
    def _valid_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("candidate_hash must be a SHA256 hex digest")
        return normalized

    @field_validator("reviewer")
    @classmethod
    def _reviewer_not_blank(cls, value: str) -> str:
        return _required_text(value, field="reviewer")

    @field_validator("reviewed_at")
    @classmethod
    def _aware_review_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return value.astimezone(UTC)


class BootstrapCandidate(BaseModel):
    """Replayable first-state proposal derived only from accepted outputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["analysis_state_bootstrap.v1"] = BOOTSTRAP_SCHEMA_VERSION
    candidate_hash: str
    source_run_id: str = Field(min_length=1, max_length=255)
    final_analysis_result_id: str | None = None
    analysis_snapshot_db_id: str | None = None
    source_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    document: AnalysisStateDocument
    transition: AnalysisTransitionDocument
    quality_gate: QualityGateDecision
    agent_loop: AgentLoopDecision

    @model_validator(mode="before")
    @classmethod
    def _drop_agent_loop_projection(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        agent_loop = normalized.get("agent_loop")
        if isinstance(agent_loop, dict):
            loop_payload = dict(agent_loop)
            loop_payload.pop("accepted_outputs", None)
            normalized["agent_loop"] = loop_payload
        return normalized

    @model_validator(mode="after")
    def _sealed_candidate(self) -> "BootstrapCandidate":
        expected = _candidate_hash(self.model_dump(mode="json", exclude={"candidate_hash"}))
        if self.candidate_hash != expected:
            raise ValueError("bootstrap candidate content changed after hashing")
        if self.quality_gate.action not in {
            QualityGateAction.PASS,
            QualityGateAction.MANUAL_REVIEW,
        }:
            raise ValueError("bootstrap requires QualityGate PASS or manual_review")
        accepted = self.agent_loop.accepted_output
        if self.quality_gate.action is QualityGateAction.PASS and not self.quality_gate.publish_allowed:
            raise ValueError("PASS bootstrap requires publish_allowed")
        if not self.agent_loop.publish_allowed:
            raise ValueError("bootstrap requires an accepted artifact identity")
        if accepted.source == "none":
            raise ValueError("bootstrap requires authoritative accepted_output")
        if accepted.snapshot_id not in set(self.document.input_snapshot_ids.values()):
            raise ValueError("accepted_output snapshot_id is absent from bootstrap lineage")
        return self


class BootstrapMaterializationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_hash: str
    state_id: str
    canonical_state_id: str
    canonical_version: int
    authorization: Literal["quality_gate", "manual_review"]
    replayed: bool


class CanonicalRecoveryArtifact(BaseModel):
    """Portable Redis/cache recovery payload; PostgreSQL remains authoritative."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["analysis_state_recovery.v1"] = RECOVERY_SCHEMA_VERSION
    asset: str
    canonical_state_id: str
    canonical_version: int = Field(ge=1)
    state_content_hash: str
    document: AnalysisStateDocument
    artifact_hash: str

    @model_validator(mode="after")
    def _validate_hashes(self) -> "CanonicalRecoveryArtifact":
        if self.state_content_hash != content_hash(self.document):
            raise ValueError("recovery state content hash mismatch")
        expected = content_hash(self.model_dump(mode="json", exclude={"artifact_hash"}))
        if self.artifact_hash != expected:
            raise ValueError("recovery artifact hash mismatch")
        if self.asset != self.document.asset:
            raise ValueError("recovery artifact asset mismatch")
        return self


class RecoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["postgresql", "artifact"]
    artifact: CanonicalRecoveryArtifact

    @property
    def cache_payload(self) -> dict[str, Any]:
        return self.artifact.model_dump(mode="json")


class LegacyDeltaSample(BaseModel):
    """One comparable legacy/state+delta shadow observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    conclusion_match: bool
    legacy_input_tokens: int = Field(gt=0)
    state_delta_input_tokens: int = Field(ge=0)
    legacy_latency_ms: int = Field(gt=0)
    state_delta_latency_ms: int = Field(ge=0)
    legacy_quality_pass: bool
    state_delta_quality_pass: bool


class LegacyRetirementThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_samples: int = Field(default=20, ge=1)
    minimum_conclusion_match_rate: float = Field(default=0.98, ge=0, le=1)
    maximum_token_ratio: float = Field(default=0.60, gt=0, le=1)
    maximum_latency_ratio: float = Field(default=0.80, gt=0, le=1)
    minimum_quality_pass_rate: float = Field(default=0.98, ge=0, le=1)
    maximum_quality_regressions: int = Field(default=0, ge=0)


class LegacySampleDiff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    conclusion_match: bool
    token_delta: int
    token_ratio: float
    latency_delta_ms: int
    latency_ratio: float
    legacy_quality_pass: bool
    state_delta_quality_pass: bool
    quality_regression: bool


class LegacyRetirementReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["legacy_state_delta_retirement.v1"] = (
        "legacy_state_delta_retirement.v1"
    )
    sample_count: int
    conclusion_match_rate: float
    token_ratio: float
    latency_ratio: float
    state_delta_quality_pass_rate: float
    quality_regressions: int
    sample_diffs: list[LegacySampleDiff]
    thresholds: LegacyRetirementThresholds
    checks: dict[str, bool]
    retirement_allowed: bool
    blocked_reasons: list[str]

    @model_validator(mode="after")
    def _validate_gate_result(self) -> "LegacyRetirementReport":
        expected = {
            "minimum_samples": self.sample_count >= self.thresholds.minimum_samples,
            "conclusion_consistency": (
                self.conclusion_match_rate >= self.thresholds.minimum_conclusion_match_rate
            ),
            "token_budget": self.token_ratio <= self.thresholds.maximum_token_ratio,
            "latency": self.latency_ratio <= self.thresholds.maximum_latency_ratio,
            "quality": (
                self.state_delta_quality_pass_rate
                >= self.thresholds.minimum_quality_pass_rate
            ),
            "quality_regressions": (
                self.quality_regressions <= self.thresholds.maximum_quality_regressions
            ),
        }
        blocked = [name for name, passed in expected.items() if not passed]
        if self.checks != expected:
            raise ValueError("legacy retirement checks contradict measured metrics")
        if self.blocked_reasons != blocked or self.retirement_allowed != (not blocked):
            raise ValueError("legacy retirement disposition contradicts checks")
        if len(self.sample_diffs) != self.sample_count:
            raise ValueError("legacy retirement sample_count does not match sample_diffs")
        return self


def build_bootstrap_candidate(
    *,
    final_result: FinalAnalysisResult | dict[str, Any],
    gold_macro_overview: BaseModel | dict[str, Any],
    strategy_card: BaseModel | dict[str, Any] | None = None,
) -> BootstrapCandidate:
    """Project one accepted result family into a compact provider-neutral state."""

    final = _final_result_payload(final_result)
    overview = _mapping(gold_macro_overview, field="gold_macro_overview")
    persisted_card = _mapping(final.get("strategy_card"), field="FinalAnalysisResult.strategy_card")
    card = _mapping(strategy_card or persisted_card, field="strategy_card")
    if content_hash(card, exclude_keys=frozenset()) != content_hash(
        persisted_card, exclude_keys=frozenset()
    ):
        raise BootstrapContractError("StrategyCard content does not match FinalAnalysisResult")
    asset = _required_text(final.get("asset"), field="final_result.asset")
    source_run_id = _required_text(final.get("run_id"), field="final_result.run_id")
    for label, payload in (("GoldMacroOverview", overview), ("StrategyCard", card)):
        payload_asset = _required_text(payload.get("asset"), field=f"{label}.asset")
        if payload_asset != asset:
            raise BootstrapContractError(f"{label} asset does not match FinalAnalysisResult")
    if card.get("run_id") and str(card["run_id"]) != source_run_id:
        raise BootstrapContractError("StrategyCard run_id does not match FinalAnalysisResult")
    if _required_text(overview.get("run_id"), field="GoldMacroOverview.run_id") != source_run_id:
        raise BootstrapContractError("GoldMacroOverview run_id does not match FinalAnalysisResult")

    runtime = _mapping(
        _mapping(final.get("run_summaries"), field="run_summaries").get(
            "gold_runtime_summary"
        ),
        field="gold_runtime_summary",
    )
    quality_gate = QualityGateDecision.model_validate(runtime.get("quality_gate_decision"))
    agent_loop = AgentLoopDecision.model_validate(runtime.get("agent_loop_decision"))
    accepted = agent_loop.accepted_output
    if quality_gate.action not in {QualityGateAction.PASS, QualityGateAction.MANUAL_REVIEW}:
        raise BootstrapContractError("FinalAnalysisResult is neither PASS nor manual_review")
    if not agent_loop.publish_allowed or accepted.source == "none":
        raise BootstrapContractError("FinalAnalysisResult has no authoritative accepted_output")

    input_snapshot_ids = _input_snapshot_ids(
        final.get("input_snapshot_ids"), card.get("input_snapshot_ids")
    )
    final_snapshot_id = _required_text(final.get("snapshot_id"), field="FinalAnalysisResult.snapshot_id")
    if accepted.snapshot_id != final_snapshot_id:
        raise BootstrapContractError("accepted_output snapshot_id conflicts with FinalAnalysisResult")
    if final_snapshot_id not in set(input_snapshot_ids.values()):
        raise BootstrapContractError("accepted_output snapshot_id is absent from persisted lineage")
    _require_lineage_subset(
        child=overview.get("input_snapshot_ids"),
        parent=input_snapshot_ids,
        field="GoldMacroOverview.input_snapshot_ids",
    )
    accepted_source_refs = _dedupe_dicts(
        [*_dict_items(final.get("source_refs")), *_dict_items(card.get("source_refs"))]
    )
    overview_source_refs = _dict_items(overview.get("source_refs"))
    _require_source_ref_subset(overview_source_refs, accepted_source_refs)
    source_refs = _dedupe_dicts([*accepted_source_refs, *overview_source_refs])
    if not source_refs:
        raise BootstrapContractError("accepted bootstrap artifacts must retain source_refs")

    document = AnalysisStateDocument(
        asset=asset,
        as_of=_bootstrap_as_of(overview=overview, card=card, final=final),
        market_stage=_bounded_text(
            overview.get("phase") or card.get("market_regime") or final.get("market_state") or "unavailable",
            64,
        ),
        core_thesis=_bounded_text(
            overview.get("one_line_conclusion")
            or final.get("scenario_summary")
            or card.get("scenario_summary"),
            2000,
        ),
        net_bias=_bounded_text(
            overview.get("net_bias") or final.get("final_bias") or card.get("bias"),
            32,
        ),
        dominant_drivers=_dominant_drivers(overview),
        key_levels=_key_levels(card),
        scenario_states=_scenario_states(card),
        unresolved_items=_unresolved_items(overview=overview, card=card),
        invalidation_conditions=[
            {"condition": _bounded_text(item, 500)}
            for item in _text_items(
                card.get("invalid_conditions") or final.get("invalid_conditions"), limit=20
            )
        ],
        evidence_cursors={},
        input_snapshot_ids=input_snapshot_ids,
        source_refs=source_refs,
    )
    transition = AnalysisTransitionDocument(
        summary="Initial canonical bootstrap from accepted analysis artifacts",
        changes=[
            StateChange(
                target="core_thesis",
                action=TransitionAction.MAINTAIN,
                reason="Seed the first canonical state from the accepted output family",
                evidence_refs=source_refs[:10],
            )
        ],
        evidence_refs=source_refs[:20],
    )
    hashes = _source_artifact_hashes(final=final, overview=overview, card=card)
    payload = {
        "schema_version": BOOTSTRAP_SCHEMA_VERSION,
        "source_run_id": source_run_id,
        "final_analysis_result_id": _optional_text(final.get("id")),
        "analysis_snapshot_db_id": _optional_text(final.get("analysis_snapshot_db_id")),
        "source_artifact_hashes": hashes,
        "document": document.model_dump(mode="json"),
        "transition": transition.model_dump(mode="json"),
        "quality_gate": quality_gate.model_dump(mode="json"),
        "agent_loop": agent_loop.model_dump(mode="json", exclude_computed_fields=True),
    }
    return BootstrapCandidate(candidate_hash=_candidate_hash(payload), **payload)


def materialize_bootstrap_candidate(
    session: Session,
    *,
    candidate: BootstrapCandidate | dict[str, Any],
    approval: BootstrapApproval | dict[str, Any] | None = None,
) -> BootstrapMaterializationResult:
    """Idempotently append and establish the first head; never replaces a head."""

    validated = BootstrapCandidate.model_validate(
        candidate.model_dump(mode="json") if isinstance(candidate, BootstrapCandidate) else candidate
    )
    checked_approval = None
    if approval is not None:
        checked_approval = BootstrapApproval.model_validate(
            approval.model_dump(mode="json") if isinstance(approval, BootstrapApproval) else approval
        )
        if checked_approval.candidate_hash != validated.candidate_hash:
            raise BootstrapContractError("manual approval belongs to a different candidate")
    if validated.quality_gate.action is QualityGateAction.MANUAL_REVIEW and checked_approval is None:
        raise PermissionError("manual_review bootstrap requires explicit human approval")
    if validated.quality_gate.action is QualityGateAction.PASS and checked_approval is not None:
        raise PermissionError("PASS bootstrap must use QualityGate authority without manual approval")

    authority = _candidate_authority(validated)
    transition = _authorized_transition(validated, checked_approval)
    current = get_canonical_state(session, validated.document.asset)
    if current is not None:
        expected_id = _bootstrap_state_id(validated, authority, transition=transition)
        if current.id != expected_id:
            raise CanonicalHeadConflictError("canonical head already exists for asset")
        head = session.scalar(
            select(AnalysisStateHead).where(AnalysisStateHead.asset == validated.document.asset)
        )
        if head is None:  # pragma: no cover - get_canonical_state already joined it
            raise CanonicalHeadConflictError("canonical head disappeared")
        return BootstrapMaterializationResult(
            candidate_hash=validated.candidate_hash,
            state_id=current.id,
            canonical_state_id=current.id,
            canonical_version=head.version,
            authorization="manual_review" if checked_approval else "quality_gate",
            replayed=True,
        )

    state_id = _bootstrap_state_id(validated, authority, transition=transition)
    state = append_analysis_state(
        session,
        document=validated.document,
        transition=transition,
        authority=authority,
        previous_state_id=None,
        task_run_id=validated.source_run_id,
        analysis_snapshot_db_id=validated.analysis_snapshot_db_id,
        final_analysis_result_id=validated.final_analysis_result_id,
        state_id=state_id,
    )
    head = advance_canonical_head(
        session,
        asset=validated.document.asset,
        new_state_id=state.id,
        expected_state_id=None,
        expected_version=0,
        authority=authority,
    )
    return BootstrapMaterializationResult(
        candidate_hash=validated.candidate_hash,
        state_id=state.id,
        canonical_state_id=head.canonical_state_id,
        canonical_version=head.version,
        authorization="manual_review" if checked_approval else "quality_gate",
        replayed=False,
    )


def build_recovery_artifact(session: Session, *, asset: str) -> CanonicalRecoveryArtifact:
    """Build a cache recovery payload from the PostgreSQL canonical head."""

    state = get_canonical_state(session, _required_text(asset, field="asset"))
    if state is None:
        raise BootstrapContractError("canonical state not found")
    head = session.scalar(select(AnalysisStateHead).where(AnalysisStateHead.asset == state.asset))
    if head is None:  # pragma: no cover - protected by joined lookup
        raise BootstrapContractError("canonical head not found")
    document = AnalysisStateDocument.model_validate(state.payload)
    payload = {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "asset": state.asset,
        "canonical_state_id": state.id,
        "canonical_version": head.version,
        "state_content_hash": state.content_hash,
        "document": document.model_dump(mode="json"),
    }
    return CanonicalRecoveryArtifact(artifact_hash=content_hash(payload), **payload)


def recover_canonical_cache_payload(
    *,
    asset: str,
    session: Session | None = None,
    artifact_path: Path | None = None,
    allowed_root: Path | None = None,
) -> RecoveryResult:
    """Recover a Redis-ready value from DB first, or a sealed artifact fallback."""

    if session is not None and get_canonical_state(session, asset) is not None:
        return RecoveryResult(source="postgresql", artifact=build_recovery_artifact(session, asset=asset))
    if artifact_path is None or allowed_root is None:
        raise BootstrapContractError("no PostgreSQL head or recovery artifact available")
    path = validate_artifact_path(artifact_path, allowed_root=allowed_root, must_exist=True)
    artifact = CanonicalRecoveryArtifact.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if artifact.asset != asset:
        raise BootstrapContractError("recovery artifact belongs to a different asset")
    return RecoveryResult(source="artifact", artifact=artifact)


def evaluate_legacy_retirement(
    samples: list[LegacyDeltaSample | dict[str, Any]],
    *,
    thresholds: LegacyRetirementThresholds | dict[str, Any] | None = None,
) -> LegacyRetirementReport:
    """Fail closed unless consistency, token, latency, and quality all pass."""

    rows = [LegacyDeltaSample.model_validate(item) for item in samples]
    limits = LegacyRetirementThresholds.model_validate(thresholds or {})
    count = len(rows)
    conclusion_rate = sum(item.conclusion_match for item in rows) / count if count else 0.0
    legacy_tokens = sum(item.legacy_input_tokens for item in rows)
    legacy_latency = sum(item.legacy_latency_ms for item in rows)
    token_ratio = sum(item.state_delta_input_tokens for item in rows) / legacy_tokens if legacy_tokens else 1.0
    latency_ratio = sum(item.state_delta_latency_ms for item in rows) / legacy_latency if legacy_latency else 1.0
    quality_rate = sum(item.state_delta_quality_pass for item in rows) / count if count else 0.0
    regressions = sum(item.legacy_quality_pass and not item.state_delta_quality_pass for item in rows)
    sample_diffs = [
        LegacySampleDiff(
            run_id=item.run_id,
            conclusion_match=item.conclusion_match,
            token_delta=item.state_delta_input_tokens - item.legacy_input_tokens,
            token_ratio=item.state_delta_input_tokens / item.legacy_input_tokens,
            latency_delta_ms=item.state_delta_latency_ms - item.legacy_latency_ms,
            latency_ratio=item.state_delta_latency_ms / item.legacy_latency_ms,
            legacy_quality_pass=item.legacy_quality_pass,
            state_delta_quality_pass=item.state_delta_quality_pass,
            quality_regression=item.legacy_quality_pass and not item.state_delta_quality_pass,
        )
        for item in rows
    ]
    checks = {
        "minimum_samples": count >= limits.minimum_samples,
        "conclusion_consistency": conclusion_rate >= limits.minimum_conclusion_match_rate,
        "token_budget": token_ratio <= limits.maximum_token_ratio,
        "latency": latency_ratio <= limits.maximum_latency_ratio,
        "quality": quality_rate >= limits.minimum_quality_pass_rate,
        "quality_regressions": regressions <= limits.maximum_quality_regressions,
    }
    blocked = [name for name, passed in checks.items() if not passed]
    return LegacyRetirementReport(
        sample_count=count,
        conclusion_match_rate=conclusion_rate,
        token_ratio=token_ratio,
        latency_ratio=latency_ratio,
        state_delta_quality_pass_rate=quality_rate,
        quality_regressions=regressions,
        sample_diffs=sample_diffs,
        thresholds=limits,
        checks=checks,
        retirement_allowed=not blocked,
        blocked_reasons=blocked,
    )


def require_legacy_retirement_allowed(report: LegacyRetirementReport | dict[str, Any]) -> None:
    """Guard the external legacy-off switch; this module never flips it itself."""

    validated = LegacyRetirementReport.model_validate(report)
    if not validated.retirement_allowed or not all(validated.checks.values()):
        raise PermissionError(
            "legacy retirement blocked: " + ", ".join(validated.blocked_reasons or ["unknown"])
        )


def write_json_artifact(
    *,
    payload: BaseModel | dict[str, Any],
    path: Path,
    allowed_root: Path,
) -> bool:
    """Write canonical JSON idempotently and reject conflicting overwrite."""

    destination = validate_artifact_path(path, allowed_root=allowed_root, must_exist=False)
    value = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if destination.exists():
        if destination.read_text(encoding="utf-8") == rendered:
            return False
        raise FileExistsError(f"refusing to overwrite different artifact: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(rendered, encoding="utf-8")
    return True


def validate_artifact_path(path: Path, *, allowed_root: Path, must_exist: bool) -> Path:
    root = allowed_root.expanduser().resolve()
    candidate = path.expanduser().resolve()
    if candidate != root and root not in candidate.parents:
        raise BootstrapContractError(f"artifact path must stay inside allowed root: {root}")
    if must_exist and (not candidate.is_file() or candidate.is_symlink()):
        raise BootstrapContractError(f"artifact file not found or unsafe: {candidate}")
    return candidate


def _candidate_authority(candidate: BootstrapCandidate) -> StateMaterializationAuthority:
    accepted = candidate.agent_loop.accepted_output
    return StateMaterializationAuthority(
        # A sealed human approval promotes a manual-review accepted artifact
        # through the same immutable PASS authority required by the repository.
        quality_gate_action=QualityGateAction.PASS.value,
        publish_allowed=True,
        accepted_output_source=accepted.source,
        accepted_output_agent_name=accepted.agent_name,
        accepted_output_snapshot_id=accepted.snapshot_id,
    )


def _authorized_transition(
    candidate: BootstrapCandidate,
    approval: BootstrapApproval | None,
) -> AnalysisTransitionDocument:
    if approval is None:
        return candidate.transition
    approval_ref = {
        "source": "human_bootstrap_review",
        "candidate_hash": approval.candidate_hash,
        "reviewer": approval.reviewer,
        "reviewed_at": approval.reviewed_at.isoformat(),
        "note_hash": content_hash({"note": approval.note}, exclude_keys=frozenset()),
    }
    return candidate.transition.model_copy(
        update={"evidence_refs": [*candidate.transition.evidence_refs, approval_ref]}
    )


def _bootstrap_state_id(
    candidate: BootstrapCandidate,
    authority: StateMaterializationAuthority,
    *,
    transition: AnalysisTransitionDocument,
) -> str:
    import uuid

    operation = {
        "document": candidate.document.model_dump(mode="json"),
        "transition": transition.model_dump(mode="json"),
        "authority": authority.model_dump(mode="json"),
        "previous_state_id": None,
        "task_run_id": candidate.source_run_id,
        "analysis_snapshot_db_id": candidate.analysis_snapshot_db_id,
        "final_analysis_result_id": candidate.final_analysis_result_id,
    }
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"finance-agent:analysis-state:{content_hash(operation)}"))


def _candidate_hash(payload: dict[str, Any]) -> str:
    normalized = dict(payload)
    agent_loop = normalized.get("agent_loop")
    if agent_loop is not None:
        loop_payload = dict(agent_loop)
        loop_payload.pop("accepted_outputs", None)
        validated_loop = AgentLoopDecision.model_validate(loop_payload)
        normalized["agent_loop"] = validated_loop.model_dump(
            mode="json", exclude_computed_fields=True
        )
    return content_hash(normalized, exclude_keys=frozenset())


def _final_result_payload(value: FinalAnalysisResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    fields = (
        "id", "asset", "trade_date", "run_id", "snapshot_id", "analysis_snapshot_db_id",
        "final_bias", "market_state", "scenario_summary", "input_snapshot_ids", "source_refs",
        "invalid_conditions", "strategy_card", "run_summaries", "payload_sha256",
        "final_report_sha256", "strategy_card_sha256",
    )
    return {field: getattr(value, field) for field in fields}


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise BootstrapContractError(f"{field} must be an object")
    return dict(value)


def _bootstrap_as_of(*, overview: dict[str, Any], card: dict[str, Any], final: dict[str, Any]) -> datetime:
    raw = overview.get("as_of") or card.get("created_at") or final.get("trade_date")
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, date):
        parsed = datetime(raw.year, raw.month, raw.day, tzinfo=UTC)
    else:
        text = _required_text(raw, field="bootstrap as_of")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            text += "T00:00:00+00:00"
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _input_snapshot_ids(*values: Any) -> dict[str, str]:
    merged: dict[str, str] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        for key, item in value.items():
            if item is not None and str(item).strip():
                merged[str(key)] = str(item)
    return merged


def _require_lineage_subset(*, child: Any, parent: dict[str, str], field: str) -> None:
    if not isinstance(child, dict):
        raise BootstrapContractError(f"{field} must be an object")
    extras = [
        str(key)
        for key, value in child.items()
        if str(key) not in parent or str(value) != parent[str(key)]
    ]
    if extras:
        raise BootstrapContractError(f"{field} exceeds accepted lineage: {sorted(extras)}")


def _require_source_ref_subset(
    child: list[dict[str, Any]], parent: list[dict[str, Any]]
) -> None:
    extras = [
        item
        for item in child
        if not any(_mapping_is_subset(item, accepted_item) for accepted_item in parent)
    ]
    if extras:
        raise BootstrapContractError("GoldMacroOverview source_refs exceed accepted lineage")


def _mapping_is_subset(candidate: dict[str, Any], accepted: dict[str, Any]) -> bool:
    return all(
        key in accepted
        and canonical_json(value, exclude_keys=frozenset())
        == canonical_json(accepted[key], exclude_keys=frozenset())
        for key, value in candidate.items()
    )


def _dominant_drivers(overview: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _dict_items(overview.get("theme_rankings"))[:10]
    allowed = ("mainline_id", "theme", "name", "rank", "score", "direction", "coverage_status")
    return [{key: row[key] for key in allowed if key in row} for row in rows]


def _key_levels(card: dict[str, Any]) -> list[dict[str, Any]]:
    values = card.get("key_levels_from_options") or card.get("key_levels") or []
    result: list[dict[str, Any]] = []
    for item in list(values)[:20] if isinstance(values, list) else []:
        if isinstance(item, dict):
            result.append(dict(item))
        elif str(item).strip():
            result.append({"level": _bounded_text(item, 500), "source": "strategy_card"})
    return result


def _scenario_states(card: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for kind, key in (("trigger", "trigger_conditions"), ("confirmation", "confirmation_conditions")):
        rows.extend(
            {"type": kind, "condition": _bounded_text(item, 500), "status": "pending"}
            for item in _text_items(card.get(key), limit=10)
        )
    return rows


def _unresolved_items(*, overview: dict[str, Any], card: dict[str, Any]) -> list[dict[str, Any]]:
    values = [
        *_text_items(overview.get("warnings"), limit=10),
        *_text_items(overview.get("architecture_gaps"), limit=10),
        *_text_items(card.get("watchlist"), limit=10),
    ]
    return [{"item": _bounded_text(item, 500), "status": "pending"} for item in dict.fromkeys(values)]


def _source_artifact_hashes(
    *, final: dict[str, Any], overview: dict[str, Any], card: dict[str, Any]
) -> dict[str, str]:
    hashes = {
        "final_analysis_result": str(
            final.get("payload_sha256")
            or content_hash(final.get("payload") or card, exclude_keys=frozenset())
        ),
        "gold_macro_overview": content_hash(overview, exclude_keys=frozenset()),
        "strategy_card": str(
            final.get("strategy_card_sha256")
            or content_hash(card, exclude_keys=frozenset())
        ),
    }
    for name, digest in hashes.items():
        if not _SHA256_RE.fullmatch(digest.lower()):
            raise BootstrapContractError(f"{name} hash is not SHA256")
    return {name: digest.lower() for name, digest in hashes.items()}


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value] if isinstance(value, list) else []


def _text_items(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value[:limit] if str(item).strip()]


def _dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        key = canonical_json(item, exclude_keys=frozenset())
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _bounded_text(value: Any, limit: int) -> str:
    text = _required_text(value, field="bootstrap text")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _optional_text(value: Any) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _required_text(value: Any, *, field: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise BootstrapContractError(f"{field} must not be blank")
    return normalized
