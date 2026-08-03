"""Immutable persistence and fail-closed canonical lookup for daily-close runs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from apps.analysis.gold_policy.analysis_policy import (
    GoldAnalysisDecision,
    GoldAnalysisDecisionV2,
)
from apps.analysis.gold_policy.attribution_policy import (
    GoldPriceAttribution,
    GoldPriceAttributionV2,
)
from apps.analysis.gold_policy.consistency_schemas import AnalysisStrategyConsistencyDecision
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_delivery import (
    GoldDailyCloseContextBundle,
    GoldDailyCloseFinalReport,
    GoldDailyCloseStrategyDiff,
    GoldDailyCloseTokenTrace,
    build_gold_daily_close_delivery,
)
from apps.analysis.gold_policy.report_context import (
    GoldReportContext,
    GoldReportContextContract,
    GoldReportContextV1,
    build_gold_report_context,
    build_gold_report_context_v1,
)
from apps.renderer.gold_policy_report import (
    GoldReportRender,
    GoldReportRenderV2,
    build_gold_policy_report_render,
    rebuild_gold_policy_report_render,
)
from apps.renderer.gold_policy_report_bundle import build_gold_policy_report_bundle
from apps.analysis.gold_policy.daily_close_schemas import (
    AnalysisStateContract,
    CanonicalCommitAction,
    DailyCloseLoopInput,
    DailyCloseLoopResult,
    StateTransitionDecisionContract,
    StrategyDecisionContract,
    StrategyPolicyInputContract,
)
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.schemas import (
    FeatureSnapshot,
    FeatureSnapshotContract,
    FeatureSnapshotInput,
    FeatureSnapshotV2,
    FeatureSnapshotV2Input,
)
from apps.analysis.gold_policy.state_schemas import (
    AnalysisState,
    AnalysisStateV2,
    StateTransitionPolicyDecision,
    StateTransitionPolicyDecisionV2,
)
from apps.analysis.gold_policy.strategy_schemas import (
    StrategyDecision,
    StrategyDecisionV2,
    StrategyPolicyInput,
    StrategyPolicyInputV2,
)
from apps.runtime.immutable_artifact import (
    ImmutableArtifactConflictError,
    ImmutableArtifactItem,
    immutable_json_item,
    write_immutable_artifact_bundle,
)


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_BASE = Path("analysis") / "gold_mainlines"
_BUNDLE_DIR = "daily_close"
_ATTEMPT = ".daily-close-attempt.json"
_MANIFEST = ".bundle-manifest.json"
_INPUT = "gold_daily_close_loop_input.v1.json"
_RESULT = "gold_daily_close_loop_result.v1.json"
_CONSISTENCY = "analysis_strategy_consistency_decision.v1.json"
_STRATEGY_DIFF = "strategy_diff.v1.json"
_FINAL_REPORT = "final_report.v1.json"
_CONTEXT_BUNDLE = "context_bundle.v1.json"
_TOKEN_TRACE = "token_trace.v1.json"
_REPORT_CONTEXT = "gold_report_context.v1.json"
_REPORT_RENDER_PREFIX = "gold_policy_report_render."
_REPORT_RENDER_V1 = "gold_policy_report_render.v1.json"
_REPORT_RENDER_V2 = "gold_policy_report_render.v2.json"
_REPORT_RENDER_SCHEMAS = {
    "gold_policy_report_render.v1": (_REPORT_RENDER_V1, GoldReportRender),
    "gold_policy_report_render.v2": (_REPORT_RENDER_V2, GoldReportRenderV2),
}
_RECEIPT = "canonical_receipt.v1.json"


class DailyCloseStoreError(RuntimeError):
    """Raised when a run cannot be persisted without weakening authority."""


class DailyCloseHeadConflictError(DailyCloseStoreError):
    """Raised when canonical head compare-and-set validation fails."""


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DailyCloseArtifactPointer(_FrozenContract):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def _relative_safe_path(cls, value: str) -> str:
        candidate = PurePosixPath(value)
        if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
            raise ValueError("artifact pointer must be a normalized relative path")
        return candidate.as_posix()


class DailyCloseEffectiveHead(_FrozenContract):
    result_id: str = Field(pattern=r"^gold_daily_close_loop_result\.v1:[0-9a-f]{64}$")
    feature_snapshot_id: str = Field(pattern=r"^feature_snapshot\.v[12]:[0-9a-f]{64}$")
    state_id: str = Field(pattern=r"^analysis_state\.v[12]:[0-9a-f]{64}$")
    transition_decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategy_id: str = Field(pattern=r"^strategy_decision\.v[12]:[0-9a-f]{64}$")
    consistency_decision_id: str = Field(pattern=r"^analysis_strategy_consistency_decision\.v1:[0-9a-f]{64}$")
    feature: DailyCloseArtifactPointer
    state: DailyCloseArtifactPointer
    transition: DailyCloseArtifactPointer
    strategy_policy_input: DailyCloseArtifactPointer
    strategy: DailyCloseArtifactPointer
    consistency: DailyCloseArtifactPointer
    result: DailyCloseArtifactPointer


class DailyCloseCanonicalReceiptInput(_FrozenContract):
    schema_version: Literal["gold_daily_close_canonical_receipt.v1"] = "gold_daily_close_canonical_receipt.v1"
    decision_as_of: datetime
    session_date: date
    run_id: str = Field(min_length=1, max_length=128)
    revision_no: int = Field(ge=1)
    finalization_status: Literal["finalized"] = "finalized"
    supersedes_receipt_id: str | None = Field(
        default=None,
        pattern=r"^gold_daily_close_canonical_receipt\.v1:[0-9a-f]{64}$",
    )
    result_id: str = Field(pattern=r"^gold_daily_close_loop_result\.v1:[0-9a-f]{64}$")
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: CanonicalCommitAction
    candidate_state_id: str | None = Field(
        default=None,
        pattern=r"^analysis_state\.v[12]:[0-9a-f]{64}$",
    )
    candidate_strategy_id: str | None = Field(
        default=None,
        pattern=r"^strategy_decision\.v[12]:[0-9a-f]{64}$",
    )
    consistency_decision_id: str | None = Field(
        default=None,
        pattern=r"^analysis_strategy_consistency_decision\.v1:[0-9a-f]{64}$",
    )
    predecessor_receipt_id: str | None = Field(
        default=None,
        pattern=r"^gold_daily_close_canonical_receipt\.v1:[0-9a-f]{64}$",
    )
    predecessor_receipt: DailyCloseArtifactPointer | None = None
    effective_head: DailyCloseEffectiveHead | None = None
    current_result: DailyCloseArtifactPointer

    @field_validator("decision_as_of")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receipt decision_as_of must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("run_id")
    @classmethod
    def _safe_run_id(cls, value: str) -> str:
        if not _RUN_ID.fullmatch(value):
            raise ValueError("run_id contains unsafe path characters")
        return value

    @model_validator(mode="after")
    def _receipt_semantics(self) -> "DailyCloseCanonicalReceiptInput":
        if self.decision_as_of.date() != self.session_date:
            raise ValueError("receipt session_date must match decision_as_of")
        if self.revision_no == 1 and self.supersedes_receipt_id is not None:
            raise ValueError("first session revision cannot supersede another receipt")
        if self.revision_no > 1 and self.supersedes_receipt_id is None:
            raise ValueError("later session revisions must name the superseded receipt")
        predecessor_pair = self.predecessor_receipt_id is not None, self.predecessor_receipt is not None
        if predecessor_pair[0] != predecessor_pair[1]:
            raise ValueError("predecessor receipt identity and pointer must be paired")
        if self.action is CanonicalCommitAction.BOOTSTRAP and any(predecessor_pair):
            raise ValueError("bootstrap cannot claim a predecessor receipt")
        if self.action in {CanonicalCommitAction.ADVANCE, CanonicalCommitAction.MAINTAIN} and not all(predecessor_pair):
            raise ValueError("advance and maintain require a predecessor receipt")
        if self.action is CanonicalCommitAction.HOLD:
            if self.effective_head is None and any(predecessor_pair):
                raise ValueError("a prebootstrap hold cannot claim a predecessor")
            if self.effective_head is not None and not all(predecessor_pair):
                raise ValueError("a retained hold requires its predecessor receipt")
        elif self.effective_head is None:
            raise ValueError("a selected receipt requires an effective canonical head")
        return self


class DailyCloseCanonicalReceipt(DailyCloseCanonicalReceiptInput):
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_id: str = Field(pattern=r"^gold_daily_close_canonical_receipt\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _content_identity(self) -> "DailyCloseCanonicalReceipt":
        digest = _sha256(_canonical_json(self, exclude={"receipt_hash", "receipt_id"}))
        if self.receipt_hash != digest or self.receipt_id != (f"gold_daily_close_canonical_receipt.v1:{digest}"):
            raise ValueError("canonical receipt identity does not match its payload")
        return self


class DailyCloseCanonicalHead(_FrozenContract):
    latest_receipt_path: Path
    latest_receipt: DailyCloseCanonicalReceipt
    selected_bundle_path: Path
    feature_snapshot: FeatureSnapshotContract
    strategy_policy_input: StrategyPolicyInputContract
    analysis_state: AnalysisStateContract
    transition_decision: StateTransitionDecisionContract
    strategy_decision: StrategyDecisionContract
    consistency_decision: AnalysisStrategyConsistencyDecision
    loop_result: DailyCloseLoopResult


class DailyCloseHeadLookup(_FrozenContract):
    status: Literal["found", "missing", "ambiguous", "invalid"]
    reason_code: str
    head: DailyCloseCanonicalHead | None = None
    latest_receipt: DailyCloseCanonicalReceipt | None = None
    source_path: Path | None = None

    @model_validator(mode="after")
    def _lookup_shape(self) -> "DailyCloseHeadLookup":
        if (self.status == "found") != (self.head is not None):
            raise ValueError("only found lookup may contain a canonical head")
        return self


class DailyCloseBundleWriteResult(_FrozenContract):
    bundle_path: Path
    result_id: str
    receipt_id: str
    revision_no: int = Field(ge=1)
    finalization_status: Literal["finalized"] = "finalized"
    head_updated: bool
    artifact_results: tuple[dict[str, Any], ...]


class DailyCloseBundleVerification(_FrozenContract):
    """Result of a complete, read-only verification of one persisted bundle."""

    status: Literal["valid", "invalid"]
    reason_code: str
    bundle_path: Path
    receipt: DailyCloseCanonicalReceipt | None = None
    head: DailyCloseCanonicalHead | None = None

    @model_validator(mode="after")
    def _verification_shape(self) -> "DailyCloseBundleVerification":
        if (self.status == "valid") != (self.receipt is not None):
            raise ValueError("only valid verification may contain a receipt")
        return self


def persist_gold_daily_close_run(
    *,
    storage_root: Path,
    run_id: str,
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
) -> DailyCloseBundleWriteResult:
    """Persist one complete audit bundle under a store-level canonical-head lock."""

    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsafe path characters")
    expected = evaluate_gold_daily_close_loop(loop_input)
    if expected.result_id != result.result_id:
        raise DailyCloseStoreError("loop result does not match deterministic re-evaluation")

    root = storage_root.resolve()
    base = root / _BASE
    _reject_symlink_components(root, base)
    base.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(root, base)
    lock_path = base / ".daily-close-head.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            return _persist_locked(
                root=root,
                base=base,
                run_id=run_id,
                loop_input=loop_input,
                result=result,
            )
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def load_gold_daily_close_head(
    *,
    storage_root: Path,
    before_date: date | None = None,
) -> DailyCloseHeadLookup:
    """Load the latest committed receipt without falling back past a bad session."""

    root = storage_root.resolve()
    base = root / _BASE
    try:
        _reject_symlink_components(root, base)
    except ValueError:
        return DailyCloseHeadLookup(
            status="invalid",
            reason_code="daily_close_storage_path_invalid",
            source_path=base,
        )
    if not base.is_dir() or base.is_symlink():
        return _missing_lookup("daily_close_head_missing")
    sessions: dict[date, list[Path]] = {}
    for date_dir in base.iterdir():
        session = _parse_date(date_dir.name)
        if session is None or (before_date is not None and session >= before_date):
            continue
        if date_dir.is_symlink():
            sessions.setdefault(session, []).append(date_dir / "invalid" / _BUNDLE_DIR)
            continue
        if not date_dir.is_dir():
            continue
        bundles = _session_bundle_paths(date_dir)
        if bundles:
            sessions[session] = sorted(bundles, key=lambda path: path.as_posix())
    if not sessions:
        return _missing_lookup("daily_close_head_missing")

    latest_date = max(sessions)
    verified: list[_VerifiedBundle] = []
    for bundle_path in sessions[latest_date]:
        bundle = _read_verified_bundle(bundle_path, root=root, visited=set())
        if bundle is None:
            return DailyCloseHeadLookup(
                status="invalid",
                reason_code="daily_close_latest_session_invalid",
                source_path=bundle_path,
            )
        verified.append(bundle)
    ordered = sorted(verified, key=lambda item: item.receipt.revision_no)
    if not _valid_revision_chain(ordered):
        return DailyCloseHeadLookup(
            status="invalid",
            reason_code="daily_close_latest_session_revision_chain_invalid",
        )
    selected = ordered[-1]
    if selected.head is None:
        return DailyCloseHeadLookup(
            status="missing",
            reason_code="daily_close_prebootstrap_hold",
            latest_receipt=selected.receipt,
            source_path=selected.receipt_path,
        )
    head = selected.head.model_copy(
        update={
            "latest_receipt_path": selected.receipt_path,
            "latest_receipt": selected.receipt,
        }
    )
    return DailyCloseHeadLookup(
        status="found",
        reason_code="daily_close_head_found",
        head=head,
        latest_receipt=selected.receipt,
        source_path=selected.receipt_path,
    )


def verify_gold_daily_close_bundle(
    *,
    storage_root: Path,
    bundle_path: Path,
) -> DailyCloseBundleVerification:
    """Fully verify exactly one daily-close bundle without repairing or selecting a head.

    Relative ``bundle_path`` values are resolved from ``storage_root``.  The path must
    identify one canonical ``analysis/gold_mainlines/<date>/<run>/daily_close`` bundle;
    this verifier never substitutes another session's latest receipt.
    """

    root = storage_root.resolve()
    candidate = bundle_path if bundle_path.is_absolute() else root / bundle_path
    try:
        _reject_symlink_components(root, candidate)
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root / _BASE)
        if (
            len(relative.parts) != 3
            or _parse_date(relative.parts[0]) is None
            or not _RUN_ID.fullmatch(relative.parts[1])
            or relative.parts[2] != _BUNDLE_DIR
            or candidate.is_symlink()
        ):
            raise ValueError("bundle path is not a canonical daily-close bundle")
        verified = _read_verified_bundle(resolved, root=root, visited=set())
        if verified is None:
            raise ValueError("bundle failed complete verification")
    except (OSError, ValueError):
        return DailyCloseBundleVerification(
            status="invalid",
            reason_code="daily_close_bundle_verification_failed",
            bundle_path=candidate,
        )
    return DailyCloseBundleVerification(
        status="valid",
        reason_code="daily_close_bundle_verified",
        bundle_path=resolved,
        receipt=verified.receipt,
        head=verified.head,
    )


class _VerifiedBundle:
    def __init__(
        self,
        *,
        receipt_path: Path,
        receipt: DailyCloseCanonicalReceipt,
        loop_input: DailyCloseLoopInput,
        result: DailyCloseLoopResult,
        head: DailyCloseCanonicalHead | None,
    ) -> None:
        self.receipt_path = receipt_path
        self.receipt = receipt
        self.loop_input = loop_input
        self.result = result
        self.head = head


def _persist_locked(
    *,
    root: Path,
    base: Path,
    run_id: str,
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
) -> DailyCloseBundleWriteResult:
    session_date = result.decision_as_of.date()
    bundle_path = base / session_date.isoformat() / run_id / _BUNDLE_DIR
    _require_contained(root, bundle_path)
    _reject_symlink_components(root, bundle_path)

    if bundle_path.exists():
        existing = _read_verified_bundle(bundle_path, root=root, visited=set())
        if existing is None:
            raise DailyCloseStoreError("existing daily-close bundle is incomplete or invalid")
        if existing.result.result_id != result.result_id or existing.loop_input != loop_input:
            raise ImmutableArtifactConflictError(
                f"Immutable daily-close bundle already contains another result: {bundle_path}"
            )
        return DailyCloseBundleWriteResult(
            bundle_path=bundle_path,
            result_id=result.result_id,
            receipt_id=existing.receipt.receipt_id,
            revision_no=existing.receipt.revision_no,
            head_updated=result.canonical_action is not CanonicalCommitAction.HOLD,
            artifact_results=(),
        )

    same_session: list[_VerifiedBundle] = []
    for existing_path in _session_bundle_paths(base / session_date.isoformat()):
        existing = _read_verified_bundle(existing_path, root=root, visited=set())
        if existing is None:
            raise DailyCloseHeadConflictError("daily-close session contains an incomplete or invalid revision")
        same_session.append(existing)
    ordered_session = sorted(same_session, key=lambda item: item.receipt.revision_no)
    if ordered_session and not _valid_revision_chain(ordered_session):
        raise DailyCloseHeadConflictError("daily-close session revision chain is invalid")
    revision_no = len(ordered_session) + 1
    supersedes = ordered_session[-1].receipt if ordered_session else None
    predecessor = (
        _lookup_from_verified(ordered_session[-1])
        if ordered_session
        else load_gold_daily_close_head(storage_root=root, before_date=session_date)
    )
    predecessor_receipt = _bind_predecessor(loop_input, result, predecessor)
    payloads = _bundle_payloads(loop_input, result, run_id=run_id)
    pointers = {name: _pointer(root, bundle_path / name, payload) for name, payload in payloads.items()}
    effective_head = _effective_head(result, pointers, predecessor)
    receipt = _build_receipt(
        run_id=run_id,
        result=result,
        current_result=pointers[_RESULT],
        predecessor=predecessor_receipt,
        effective_head=effective_head,
        revision_no=revision_no,
        supersedes=supersedes,
    )
    payloads[_RECEIPT] = receipt.model_dump(mode="json")
    attempt_path = bundle_path.parent / _ATTEMPT
    write_immutable_artifact_bundle(
        [
            immutable_json_item(
                attempt_path,
                {
                    "schema_version": "gold_daily_close_commit_attempt.v1",
                    "session_date": session_date.isoformat(),
                    "run_id": run_id,
                    "revision_no": revision_no,
                    "result_id": result.result_id,
                },
            )
        ],
        storage_root=root,
    )
    report_context = build_gold_report_context(loop_input, result, run_id=run_id)
    report_render = build_gold_policy_report_render(report_context)
    report_items = build_gold_policy_report_bundle(report_context, report_render)
    items = [immutable_json_item(bundle_path / name, payload) for name, payload in payloads.items()]
    items.extend(
        ImmutableArtifactItem(
            path=bundle_path / item.path,
            content=item.content,
            encoding=item.encoding,
        )
        for item in report_items
    )
    results = write_immutable_artifact_bundle(items, storage_root=root)
    attempt_path.unlink(missing_ok=True)
    return DailyCloseBundleWriteResult(
        bundle_path=bundle_path,
        result_id=result.result_id,
        receipt_id=receipt.receipt_id,
        revision_no=receipt.revision_no,
        head_updated=result.canonical_action is not CanonicalCommitAction.HOLD,
        artifact_results=tuple(asdict(item) for item in results),
    )


def _bind_predecessor(
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
    lookup: DailyCloseHeadLookup,
) -> DailyCloseCanonicalReceipt | None:
    has_predecessor = loop_input.previous_state is not None
    if lookup.status in {"invalid", "ambiguous"}:
        raise DailyCloseHeadConflictError(f"cannot commit after {lookup.reason_code}")
    if has_predecessor:
        if lookup.status != "found" or lookup.head is None:
            raise DailyCloseHeadConflictError("canonical predecessor is not durably available")
        head = lookup.head
        if (
            loop_input.previous_feature != head.feature_snapshot
            or loop_input.previous_policy_input != head.strategy_policy_input
            or loop_input.previous_state != head.analysis_state
            or loop_input.previous_transition != head.transition_decision
            or loop_input.previous_strategy != head.strategy_decision
            or result.previous_state_id != head.analysis_state.state_id
            or result.previous_strategy_id != head.strategy_decision.decision_id
        ):
            raise DailyCloseHeadConflictError("loop predecessor does not match the durable canonical head")
        return lookup.latest_receipt
    if lookup.status == "found":
        raise DailyCloseHeadConflictError("cannot bootstrap over an existing canonical head")
    return None


def _bundle_payloads(
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
    *,
    run_id: str,
    report_context_schema: str = "gold_report_context.v1.1",
    report_render_schema: str | None = None,
) -> dict[str, dict[str, Any]]:
    report_context = _build_versioned_report_context(
        loop_input,
        result,
        run_id=run_id,
        schema_version=report_context_schema,
    )
    report_render = (
        build_gold_policy_report_render(report_context)
        if report_render_schema is None
        else rebuild_gold_policy_report_render(
            report_context,
            schema_version=report_render_schema,
        )
    )
    report_render_name = _report_render_artifact_name(report_render.schema_version)
    payloads = {
        _INPUT: loop_input.model_dump(mode="json"),
        _RESULT: result.model_dump(mode="json"),
        _feature_artifact_name(loop_input.current_feature): loop_input.current_feature.model_dump(mode="json"),
        _analysis_artifact_name(result.analysis_decision): result.analysis_decision.model_dump(mode="json"),
        _attribution_artifact_name(result.price_attribution): result.price_attribution.model_dump(mode="json"),
        _transition_artifact_name(result.transition_decision): result.transition_decision.model_dump(mode="json"),
        _REPORT_CONTEXT: report_context.model_dump(mode="json"),
        report_render_name: report_render.model_dump(mode="json"),
    }
    if result.analysis_decision.policy_version == "gold_analysis_policy.v1":
        delivery = build_gold_daily_close_delivery(loop_input, result)
        payloads.update(
            {
                _STRATEGY_DIFF: delivery.strategy_diff.model_dump(mode="json"),
                _FINAL_REPORT: delivery.final_report.model_dump(mode="json"),
                _CONTEXT_BUNDLE: delivery.context_bundle.model_dump(mode="json"),
                _TOKEN_TRACE: delivery.token_trace.model_dump(mode="json"),
            }
        )
    if result.analysis_state is not None:
        payloads.update(
            {
                _state_artifact_name(result.analysis_state): result.analysis_state.model_dump(mode="json"),
                _policy_input_artifact_name(result.strategy_policy_input): result.strategy_policy_input.model_dump(
                    mode="json"
                ),
                _strategy_artifact_name(result.candidate_strategy): result.candidate_strategy.model_dump(mode="json"),
                _CONSISTENCY: result.consistency_decision.model_dump(mode="json"),
            }
        )
    return payloads


def _build_versioned_report_context(
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
    *,
    run_id: str,
    schema_version: str,
) -> GoldReportContextContract:
    if schema_version == "gold_report_context.v1":
        return build_gold_report_context_v1(loop_input, result)
    if schema_version == "gold_report_context.v1.1":
        return build_gold_report_context(loop_input, result, run_id=run_id)
    raise ValueError("unsupported gold report context schema")


def _effective_head(
    result: DailyCloseLoopResult,
    pointers: dict[str, DailyCloseArtifactPointer],
    predecessor: DailyCloseHeadLookup,
) -> DailyCloseEffectiveHead | None:
    if result.canonical_action is CanonicalCommitAction.HOLD:
        return predecessor.head.latest_receipt.effective_head if predecessor.head is not None else None
    return DailyCloseEffectiveHead(
        result_id=result.result_id,
        feature_snapshot_id=result.current_feature_id,
        state_id=result.selected_state_id,
        transition_decision_hash=result.transition_decision.decision_hash,
        strategy_id=result.selected_strategy_id,
        consistency_decision_id=result.consistency_decision.decision_id,
        feature=pointers[_feature_artifact_name(result.current_feature_id)],
        state=pointers[_state_artifact_name(result.analysis_state)],
        transition=pointers[_transition_artifact_name(result.transition_decision)],
        strategy_policy_input=pointers[_policy_input_artifact_name(result.strategy_policy_input)],
        strategy=pointers[_strategy_artifact_name(result.candidate_strategy)],
        consistency=pointers[_CONSISTENCY],
        result=pointers[_RESULT],
    )


def _build_receipt(
    *,
    run_id: str,
    result: DailyCloseLoopResult,
    current_result: DailyCloseArtifactPointer,
    predecessor: DailyCloseCanonicalReceipt | None,
    effective_head: DailyCloseEffectiveHead | None,
    revision_no: int,
    supersedes: DailyCloseCanonicalReceipt | None,
) -> DailyCloseCanonicalReceipt:
    value = DailyCloseCanonicalReceiptInput(
        decision_as_of=result.decision_as_of,
        session_date=result.decision_as_of.date(),
        run_id=run_id,
        revision_no=revision_no,
        supersedes_receipt_id=(supersedes.receipt_id if supersedes else None),
        result_id=result.result_id,
        result_hash=result.result_hash,
        action=result.canonical_action,
        candidate_state_id=(result.analysis_state.state_id if result.analysis_state else None),
        candidate_strategy_id=(result.candidate_strategy.decision_id if result.candidate_strategy else None),
        consistency_decision_id=(result.consistency_decision.decision_id if result.consistency_decision else None),
        predecessor_receipt_id=(predecessor.receipt_id if predecessor else None),
        predecessor_receipt=(_pointer_from_existing(predecessor) if predecessor else None),
        effective_head=effective_head,
        current_result=current_result,
    )
    digest = _sha256(_canonical_json(value))
    return DailyCloseCanonicalReceipt(
        **value.model_dump(),
        receipt_hash=digest,
        receipt_id=f"gold_daily_close_canonical_receipt.v1:{digest}",
    )


def _pointer_from_existing(receipt: DailyCloseCanonicalReceipt) -> DailyCloseArtifactPointer:
    predecessor_path = receipt.current_result.path.rsplit("/", 1)[0] + f"/{_RECEIPT}"
    return DailyCloseArtifactPointer(path=predecessor_path, sha256=_json_sha(receipt.model_dump(mode="json")))


def _canonical_bundle_run_id(bundle: Path, *, root: Path) -> str:
    relative = bundle.relative_to(root / _BASE)
    if (
        len(relative.parts) != 3
        or _parse_date(relative.parts[0]) is None
        or not _RUN_ID.fullmatch(relative.parts[1])
        or relative.parts[2] != _BUNDLE_DIR
    ):
        raise ValueError("bundle path is not a canonical daily-close bundle")
    return relative.parts[1]


def _read_verified_bundle(
    bundle_path: Path,
    *,
    root: Path,
    visited: set[str],
) -> _VerifiedBundle | None:
    try:
        _reject_symlink_components(root, bundle_path)
        resolved = bundle_path.resolve(strict=True)
        if not resolved.is_dir() or not resolved.is_relative_to(root) or bundle_path.is_symlink():
            return None
        manifest_items = _verified_manifest(resolved)
        run_id = _canonical_bundle_run_id(resolved, root=root)
        input_payload = _read_payload(resolved / _INPUT, manifest_items)
        result_payload = _read_payload(resolved / _RESULT, manifest_items)
        receipt_payload = _read_payload(resolved / _RECEIPT, manifest_items)
        report_context_payload = _read_payload(resolved / _REPORT_CONTEXT, manifest_items)
        report_render_name, report_render_schema = _detect_report_render_artifact(
            resolved,
            manifest_items,
        )
        loop_input = DailyCloseLoopInput.model_validate(input_payload)
        result = DailyCloseLoopResult.model_validate(result_payload)
        receipt = DailyCloseCanonicalReceipt.model_validate(receipt_payload)
        report_context_schema = report_context_payload.get("schema_version")
        report_context = _build_versioned_report_context(
            loop_input,
            result,
            run_id=run_id,
            schema_version=report_context_schema,
        )
        report_render = rebuild_gold_policy_report_render(
            report_context,
            schema_version=report_render_schema,
        )
        expected_names = (
            set(
                _bundle_payloads(
                    loop_input,
                    result,
                    run_id=run_id,
                    report_context_schema=report_context_schema,
                    report_render_schema=report_render_schema,
                )
            )
            | {item.path.as_posix() for item in build_gold_policy_report_bundle(report_context, report_render)}
            | {_RECEIPT}
        )
        if set(manifest_items) != expected_names:
            return None
        if evaluate_gold_daily_close_loop(loop_input).result_id != result.result_id:
            return None
        _verify_embedded_artifacts(
            resolved,
            manifest_items,
            loop_input,
            result,
            run_id=run_id,
            report_context_schema=report_context_schema,
            report_render_name=report_render_name,
            report_render_schema=report_render_schema,
        )
        session = _parse_date(resolved.parents[1].name)
        if (
            session is None
            or receipt.session_date != session
            or receipt.run_id != run_id
            or receipt.result_id != result.result_id
            or receipt.result_hash != result.result_hash
            or receipt.action is not result.canonical_action
            or receipt.current_result.path != (resolved / _RESULT).relative_to(root).as_posix()
            or receipt.current_result.sha256 != manifest_items[_RESULT]
            or receipt.candidate_state_id != (result.analysis_state.state_id if result.analysis_state else None)
            or receipt.candidate_strategy_id
            != (result.candidate_strategy.decision_id if result.candidate_strategy else None)
            or receipt.consistency_decision_id
            != (result.consistency_decision.decision_id if result.consistency_decision else None)
        ):
            return None
        head = _resolve_receipt_head(receipt, resolved / _RECEIPT, root=root, visited=visited)
        if (receipt.effective_head is None) != (head is None):
            return None
        if receipt.effective_head is not None and (
            receipt.effective_head.state_id != result.selected_state_id
            or receipt.effective_head.strategy_id != result.selected_strategy_id
        ):
            return None
        if receipt.action is not CanonicalCommitAction.HOLD:
            expected_pointers = {
                _feature_artifact_name(result.current_feature_id): receipt.effective_head.feature,
                _state_artifact_name(result.analysis_state): receipt.effective_head.state,
                _transition_artifact_name(result.transition_decision): receipt.effective_head.transition,
                _policy_input_artifact_name(result.strategy_policy_input): receipt.effective_head.strategy_policy_input,
                _strategy_artifact_name(result.candidate_strategy): receipt.effective_head.strategy,
                _CONSISTENCY: receipt.effective_head.consistency,
                _RESULT: receipt.effective_head.result,
            }
            for name, pointer in expected_pointers.items():
                if (
                    pointer.path != (resolved / name).relative_to(root).as_posix()
                    or pointer.sha256 != manifest_items[name]
                ):
                    return None
        if receipt.predecessor_receipt is not None:
            predecessor_path = _resolve_pointer(root, receipt.predecessor_receipt)
            predecessor = _read_verified_bundle(
                predecessor_path.parent,
                root=root,
                visited={*visited, receipt.receipt_id},
            )
            if (
                predecessor is None
                or predecessor.receipt.receipt_id != receipt.predecessor_receipt_id
                or predecessor.head is None
                or loop_input.previous_feature != predecessor.head.feature_snapshot
                or loop_input.previous_policy_input != predecessor.head.strategy_policy_input
                or loop_input.previous_state != predecessor.head.analysis_state
                or loop_input.previous_transition != predecessor.head.transition_decision
                or loop_input.previous_strategy != predecessor.head.strategy_decision
            ):
                return None
        return _VerifiedBundle(
            receipt_path=resolved / _RECEIPT,
            receipt=receipt,
            loop_input=loop_input,
            result=result,
            head=head,
        )
    except (OSError, ValueError, ValidationError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _resolve_receipt_head(
    receipt: DailyCloseCanonicalReceipt,
    receipt_path: Path,
    *,
    root: Path,
    visited: set[str],
) -> DailyCloseCanonicalHead | None:
    if receipt.receipt_id in visited:
        raise ValueError("canonical receipt lineage contains a cycle")
    next_visited = {*visited, receipt.receipt_id}
    if receipt.action is CanonicalCommitAction.HOLD:
        if receipt.effective_head is None:
            return None
        predecessor_path = _resolve_pointer(root, receipt.predecessor_receipt)
        predecessor_bundle = _read_verified_bundle(
            predecessor_path.parent,
            root=root,
            visited=next_visited,
        )
        if (
            predecessor_bundle is None
            or predecessor_bundle.receipt.receipt_id != receipt.predecessor_receipt_id
            or predecessor_bundle.receipt.effective_head != receipt.effective_head
            or predecessor_bundle.head is None
        ):
            raise ValueError("hold receipt does not resolve to its predecessor head")
        return predecessor_bundle.head
    if receipt.action is not CanonicalCommitAction.BOOTSTRAP:
        predecessor_path = _resolve_pointer(root, receipt.predecessor_receipt)
        predecessor_bundle = _read_verified_bundle(
            predecessor_path.parent,
            root=root,
            visited=next_visited,
        )
        if predecessor_bundle is None or predecessor_bundle.receipt.receipt_id != receipt.predecessor_receipt_id:
            raise ValueError("selected receipt predecessor is unavailable")
    return _load_effective_head(receipt, receipt_path, root=root)


def _load_effective_head(
    receipt: DailyCloseCanonicalReceipt,
    receipt_path: Path,
    *,
    root: Path,
) -> DailyCloseCanonicalHead:
    effective = receipt.effective_head
    feature = _read_feature_pointer(root, effective.feature)
    rebuilt = _rebuild_feature(feature)
    state = _read_versioned_pointer(
        root,
        effective.state,
        {
            "analysis_state.v1.json": AnalysisState,
            "analysis_state.v2.json": AnalysisStateV2,
        },
    )
    transition = _read_versioned_pointer(
        root,
        effective.transition,
        {
            "state_transition_policy_decision.v1.json": StateTransitionPolicyDecision,
            "state_transition_policy_decision.v2.json": StateTransitionPolicyDecisionV2,
        },
    )
    policy_input = _read_versioned_pointer(
        root,
        effective.strategy_policy_input,
        {
            "strategy_policy_input.v1.json": StrategyPolicyInput,
            "strategy_policy_input.v2.json": StrategyPolicyInputV2,
        },
    )
    strategy = _read_versioned_pointer(
        root,
        effective.strategy,
        {
            "strategy_decision.v1.json": StrategyDecision,
            "strategy_decision.v2.json": StrategyDecisionV2,
        },
    )
    consistency = _read_pointer_model(
        root,
        effective.consistency,
        AnalysisStrategyConsistencyDecision,
    )
    result = _read_pointer_model(root, effective.result, DailyCloseLoopResult)
    if (
        rebuilt != feature
        or feature.snapshot_id != effective.feature_snapshot_id
        or state.state_id != effective.state_id
        or transition.decision_hash != effective.transition_decision_hash
        or strategy.decision_id != effective.strategy_id
        or consistency.decision_id != effective.consistency_decision_id
        or result.result_id != effective.result_id
        or result.selected_state_id != state.state_id
        or result.selected_strategy_id != strategy.decision_id
        or result.analysis_state != state
        or result.transition_decision != transition
        or result.strategy_policy_input != policy_input
        or result.candidate_strategy != strategy
        or result.consistency_decision != consistency
        or policy_input.feature_snapshot != feature
        or policy_input.analysis_state != state
        or policy_input.state_transition != transition
    ):
        raise ValueError("effective canonical head artifacts are inconsistent")
    return DailyCloseCanonicalHead(
        latest_receipt_path=receipt_path,
        latest_receipt=receipt,
        selected_bundle_path=_resolve_pointer(root, effective.result).parent,
        feature_snapshot=feature,
        strategy_policy_input=policy_input,
        analysis_state=state,
        transition_decision=transition,
        strategy_decision=strategy,
        consistency_decision=consistency,
        loop_result=result,
    )


def _verify_embedded_artifacts(
    bundle: Path,
    manifest: dict[str, str],
    loop_input: DailyCloseLoopInput,
    result: DailyCloseLoopResult,
    *,
    run_id: str,
    report_context_schema: str,
    report_render_name: str,
    report_render_schema: str,
) -> None:
    feature = _read_feature_artifact(bundle, loop_input.current_feature, manifest)
    rebuilt = _rebuild_feature(feature)
    if rebuilt != feature or feature != loop_input.current_feature:
        raise ValueError("persisted feature identity is invalid")
    pairs = (
        (
            _analysis_artifact_name(result.analysis_decision),
            type(result.analysis_decision),
            result.analysis_decision,
        ),
        (
            _attribution_artifact_name(result.price_attribution),
            type(result.price_attribution),
            result.price_attribution,
        ),
        (
            _transition_artifact_name(result.transition_decision),
            type(result.transition_decision),
            result.transition_decision,
        ),
    )
    for name, model, expected in pairs:
        if _read_typed(bundle, name, manifest, model) != expected:
            raise ValueError(f"persisted {name} does not match loop result")
    report_context = _build_versioned_report_context(
        loop_input,
        result,
        run_id=run_id,
        schema_version=report_context_schema,
    )
    report_render = rebuild_gold_policy_report_render(
        report_context,
        schema_version=report_render_schema,
    )
    report_context_model = (
        GoldReportContextV1 if report_context_schema == "gold_report_context.v1" else GoldReportContext
    )
    for name, model, expected in (
        (_REPORT_CONTEXT, report_context_model, report_context),
        (
            report_render_name,
            _REPORT_RENDER_SCHEMAS[report_render_schema][1],
            report_render,
        ),
    ):
        if _read_typed(bundle, name, manifest, model) != expected:
            raise ValueError(f"persisted {name} does not match report renderer")
    for item in build_gold_policy_report_bundle(report_context, report_render):
        path = bundle / item.path
        if path.name not in manifest or path.is_symlink() or path.read_bytes() != item.content:
            raise ValueError(f"persisted {item.path} does not match report bundle")
    if result.analysis_decision.policy_version == "gold_analysis_policy.v1":
        delivery = build_gold_daily_close_delivery(loop_input, result)
        delivery_pairs = (
            (_STRATEGY_DIFF, GoldDailyCloseStrategyDiff, delivery.strategy_diff),
            (_FINAL_REPORT, GoldDailyCloseFinalReport, delivery.final_report),
            (_CONTEXT_BUNDLE, GoldDailyCloseContextBundle, delivery.context_bundle),
            (_TOKEN_TRACE, GoldDailyCloseTokenTrace, delivery.token_trace),
        )
        for name, model, expected in delivery_pairs:
            if _read_typed(bundle, name, manifest, model) != expected:
                raise ValueError(f"persisted {name} does not match loop delivery")
    if result.analysis_state is not None:
        downstream = (
            (
                _state_artifact_name(result.analysis_state),
                type(result.analysis_state),
                result.analysis_state,
            ),
            (
                _policy_input_artifact_name(result.strategy_policy_input),
                type(result.strategy_policy_input),
                result.strategy_policy_input,
            ),
            (
                _strategy_artifact_name(result.candidate_strategy),
                type(result.candidate_strategy),
                result.candidate_strategy,
            ),
            (_CONSISTENCY, AnalysisStrategyConsistencyDecision, result.consistency_decision),
        )
        for name, model, expected in downstream:
            if _read_typed(bundle, name, manifest, model) != expected:
                raise ValueError(f"persisted {name} does not match loop result")


def _verified_manifest(bundle: Path) -> dict[str, str]:
    path = bundle / _MANIFEST
    if path.is_symlink():
        raise ValueError("bundle manifest cannot be a symlink")
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    canonical = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if raw != canonical:
        raise ValueError("bundle manifest bytes are not canonical")
    if payload.get("version") != 1 or payload.get("status") != "committed":
        raise ValueError("bundle manifest is not committed")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("bundle manifest items are invalid")
    result: dict[str, str] = {}
    for item in items:
        name = item.get("path") if isinstance(item, dict) else None
        digest = item.get("sha256") if isinstance(item, dict) else None
        if (
            not isinstance(name, str)
            or PurePosixPath(name).name != name
            or name in result
            or not isinstance(digest, str)
        ):
            raise ValueError("bundle manifest item is invalid")
        artifact = bundle / name
        if artifact.is_symlink() or hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
            raise ValueError("bundle artifact sha does not match manifest")
        result[name] = digest
    return result


def _read_payload(path: Path, manifest: dict[str, str]) -> dict[str, Any]:
    if path.name not in manifest or path.is_symlink():
        raise ValueError("required artifact is absent from manifest")
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("daily-close artifact must be a JSON object")
    if raw != immutable_json_item(path, payload).content:
        raise ValueError("daily-close artifact bytes are not canonical")
    return payload


def _report_render_artifact_name(schema_version: str) -> str:
    try:
        return _REPORT_RENDER_SCHEMAS[schema_version][0]
    except KeyError as exc:
        raise ValueError("unsupported gold report render schema") from exc


def _detect_report_render_artifact(
    bundle: Path,
    manifest: dict[str, str],
) -> tuple[str, str]:
    candidates = tuple(name for name in manifest if name.startswith(_REPORT_RENDER_PREFIX) and name.endswith(".json"))
    if len(candidates) != 1:
        raise ValueError("daily-close bundle must contain exactly one report render artifact")
    name = candidates[0]
    payload = _read_payload(bundle / name, manifest)
    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str):
        raise ValueError("report render schema version is missing")
    if name != _report_render_artifact_name(schema_version):
        raise ValueError("report render filename does not match its schema version")
    return name, schema_version


def _feature_artifact_name(feature: FeatureSnapshotContract | str) -> str:
    schema_version = feature.split(":", 1)[0] if isinstance(feature, str) else feature.schema_version
    if schema_version not in {"feature_snapshot.v1", "feature_snapshot.v2"}:
        raise ValueError("unsupported feature snapshot schema version")
    return f"{schema_version}.json"


def _analysis_artifact_name(
    decision: GoldAnalysisDecision | GoldAnalysisDecisionV2,
) -> str:
    versions = {
        "gold_analysis_policy.v1": "v1",
        "gold_analysis_policy.v2": "v2",
    }
    try:
        version = versions[decision.policy_version]
    except KeyError as exc:
        raise ValueError("unsupported gold analysis policy version") from exc
    return f"gold_analysis_decision.{version}.json"


def _attribution_artifact_name(
    attribution: GoldPriceAttribution | GoldPriceAttributionV2,
) -> str:
    versions = {
        "gold_price_attribution.v1": "v1",
        "gold_price_attribution.v2": "v2",
    }
    try:
        version = versions[attribution.policy_version]
    except KeyError as exc:
        raise ValueError("unsupported gold attribution policy version") from exc
    return f"gold_price_attribution.{version}.json"


def _state_artifact_name(state: AnalysisStateContract) -> str:
    if state.schema_version not in {"analysis_state.v1", "analysis_state.v2"}:
        raise ValueError("unsupported analysis state schema version")
    return f"{state.schema_version}.json"


def _transition_artifact_name(
    transition: StateTransitionDecisionContract,
) -> str:
    versions = {
        "analysis_state_transition_policy.v1": "v1",
        "analysis_state_transition_policy.v2": "v2",
    }
    try:
        version = versions[transition.policy_version]
    except KeyError as exc:
        raise ValueError("unsupported state transition policy version") from exc
    return f"state_transition_policy_decision.{version}.json"


def _policy_input_artifact_name(
    policy_input: StrategyPolicyInputContract,
) -> str:
    if policy_input.schema_version not in {
        "strategy_policy_input.v1",
        "strategy_policy_input.v2",
    }:
        raise ValueError("unsupported strategy policy input schema version")
    return f"{policy_input.schema_version}.json"


def _strategy_artifact_name(strategy: StrategyDecisionContract) -> str:
    if strategy.schema_version not in {"strategy_decision.v1", "strategy_decision.v2"}:
        raise ValueError("unsupported strategy decision schema version")
    return f"{strategy.schema_version}.json"


def _feature_from_payload(payload: dict[str, Any]) -> FeatureSnapshotContract:
    if payload.get("schema_version") == "feature_snapshot.v2":
        return FeatureSnapshotV2.model_validate(payload)
    if payload.get("schema_version") == "feature_snapshot.v1":
        return FeatureSnapshot.model_validate(payload)
    raise ValueError("unsupported feature snapshot schema version")


def _rebuild_feature(feature: FeatureSnapshotContract) -> FeatureSnapshotContract:
    excluded = {"data_quality", "payload_hash", "snapshot_id"}
    if isinstance(feature, FeatureSnapshotV2):
        excluded.update(
            {
                "real10y_estimated",
                "real10y_basis_bp",
                "real10y_alignment",
                "real10y_reason_codes",
                "real10y_quality",
            }
        )
        rebuilt = build_feature_snapshot(
            FeatureSnapshotV2Input.model_validate(feature.model_dump(mode="python", exclude=excluded))
        )
    else:
        rebuilt = build_feature_snapshot(
            FeatureSnapshotInput.model_validate(feature.model_dump(mode="python", exclude=excluded))
        )
    if rebuilt != feature:
        raise ValueError("feature snapshot derived fields or identity are invalid")
    return rebuilt


def _read_feature_artifact(
    bundle: Path,
    expected_feature: FeatureSnapshotContract,
    manifest: dict[str, str],
) -> FeatureSnapshotContract:
    name = _feature_artifact_name(expected_feature)
    path = bundle / name
    value = _feature_from_payload(_read_payload(path, manifest))
    if immutable_json_item(path, value.model_dump(mode="json")).content != path.read_bytes():
        raise ValueError("typed feature artifact bytes are not canonical")
    return value


def _read_feature_pointer(
    root: Path,
    pointer: DailyCloseArtifactPointer,
) -> FeatureSnapshotContract:
    path = _resolve_pointer(root, pointer)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("canonical feature pointer must resolve to an object")
    value = _feature_from_payload(payload)
    if immutable_json_item(path, value.model_dump(mode="json")).content != path.read_bytes():
        raise ValueError("canonical feature pointer bytes are not canonical")
    return value


def _read_typed(bundle: Path, name: str, manifest: dict[str, str], model):
    payload = _read_payload(bundle / name, manifest)
    value = model.model_validate(payload)
    if immutable_json_item(bundle / name, value.model_dump(mode="json")).content != (bundle / name).read_bytes():
        raise ValueError("typed artifact bytes are not canonical")
    return value


def _read_pointer_model(root: Path, pointer: DailyCloseArtifactPointer, model):
    path = _resolve_pointer(root, pointer)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("canonical artifact pointer must resolve to an object")
    value = model.model_validate(payload)
    if immutable_json_item(path, value.model_dump(mode="json")).content != path.read_bytes():
        raise ValueError("canonical artifact pointer bytes are not canonical")
    return value


def _read_versioned_pointer(
    root: Path,
    pointer: DailyCloseArtifactPointer,
    models: dict[str, type[BaseModel]],
):
    name = PurePosixPath(pointer.path).name
    model = models.get(name)
    if model is None:
        raise ValueError("versioned artifact pointer filename is unsupported")
    return _read_pointer_model(root, pointer, model)


def _resolve_pointer(root: Path, pointer: DailyCloseArtifactPointer | None) -> Path:
    if pointer is None:
        raise ValueError("required artifact pointer is missing")
    path = root / pointer.path
    _reject_symlink_components(root, path)
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("artifact pointer escapes storage root")
    if hashlib.sha256(resolved.read_bytes()).hexdigest() != pointer.sha256:
        raise ValueError("artifact pointer sha mismatch")
    return resolved


def _pointer(
    root: Path,
    path: Path,
    payload: dict[str, Any],
) -> DailyCloseArtifactPointer:
    _require_contained(root, path)
    return DailyCloseArtifactPointer(
        path=path.relative_to(root).as_posix(),
        sha256=_json_sha(payload),
    )


def _session_bundle_paths(date_dir: Path) -> list[Path]:
    if not date_dir.exists():
        return []
    if date_dir.is_symlink() or not date_dir.is_dir():
        return [date_dir]
    candidates: list[Path] = []
    for run_dir in date_dir.iterdir():
        if run_dir.name.startswith(".") or run_dir.is_symlink() or not run_dir.is_dir():
            continue
        bundle = run_dir / _BUNDLE_DIR
        if bundle.exists() or (run_dir / _ATTEMPT).exists():
            candidates.append(bundle)
    return sorted(candidates, key=lambda path: path.as_posix())


def _valid_revision_chain(values: list[_VerifiedBundle]) -> bool:
    if [item.receipt.revision_no for item in values] != list(range(1, len(values) + 1)):
        return False
    if values and values[0].receipt.supersedes_receipt_id is not None:
        return False
    return all(
        current.receipt.supersedes_receipt_id == previous.receipt.receipt_id
        for previous, current in zip(values, values[1:], strict=False)
    )


def _lookup_from_verified(value: _VerifiedBundle) -> DailyCloseHeadLookup:
    if value.head is None:
        return DailyCloseHeadLookup(
            status="missing",
            reason_code="daily_close_prebootstrap_hold",
            latest_receipt=value.receipt,
            source_path=value.receipt_path,
        )
    head = value.head.model_copy(
        update={
            "latest_receipt_path": value.receipt_path,
            "latest_receipt": value.receipt,
        }
    )
    return DailyCloseHeadLookup(
        status="found",
        reason_code="daily_close_head_found",
        head=head,
        latest_receipt=value.receipt,
        source_path=value.receipt_path,
    )


def _reject_symlink_components(root: Path, target: Path) -> None:
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"daily-close storage path cannot contain symlinks: {current}")


def _require_contained(root: Path, target: Path) -> None:
    if not target.resolve().is_relative_to(root):
        raise ValueError("daily-close artifact path must stay inside storage_root")


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _missing_lookup(reason: str) -> DailyCloseHeadLookup:
    return DailyCloseHeadLookup(status="missing", reason_code=reason)


def _head_identity(head: DailyCloseEffectiveHead | None) -> tuple[str, str] | None:
    return (head.state_id, head.strategy_id) if head is not None else None


def _canonical_json(value: BaseModel, *, exclude: set[str] | None = None) -> str:
    return json.dumps(
        value.model_dump(mode="json", exclude=exclude),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(immutable_json_item("artifact.json", payload).content).hexdigest()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
