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

from apps.analysis.gold_policy.analysis_policy import GoldAnalysisDecision
from apps.analysis.gold_policy.attribution_policy import GoldPriceAttribution
from apps.analysis.gold_policy.consistency_schemas import AnalysisStrategyConsistencyDecision
from apps.analysis.gold_policy.daily_close_loop import evaluate_gold_daily_close_loop
from apps.analysis.gold_policy.daily_close_delivery import (
    GoldDailyCloseContextBundle,
    GoldDailyCloseFinalReport,
    GoldDailyCloseStrategyDiff,
    GoldDailyCloseTokenTrace,
    build_gold_daily_close_delivery,
)
from apps.analysis.gold_policy.daily_close_schemas import (
    CanonicalCommitAction,
    DailyCloseLoopInput,
    DailyCloseLoopResult,
)
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.schemas import FeatureSnapshot, FeatureSnapshotInput
from apps.analysis.gold_policy.state_schemas import AnalysisState, StateTransitionPolicyDecision
from apps.analysis.gold_policy.strategy_schemas import StrategyDecision, StrategyPolicyInput
from apps.runtime.immutable_artifact import (
    ImmutableArtifactConflictError,
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
_FEATURE = "feature_snapshot.v1.json"
_ANALYSIS = "gold_analysis_decision.v1.json"
_ATTRIBUTION = "gold_price_attribution.v1.json"
_TRANSITION = "state_transition_policy_decision.v1.json"
_STATE = "analysis_state.v1.json"
_POLICY_INPUT = "strategy_policy_input.v1.json"
_STRATEGY = "strategy_decision.v1.json"
_CONSISTENCY = "analysis_strategy_consistency_decision.v1.json"
_STRATEGY_DIFF = "strategy_diff.v1.json"
_FINAL_REPORT = "final_report.v1.json"
_CONTEXT_BUNDLE = "context_bundle.v1.json"
_TOKEN_TRACE = "token_trace.v1.json"
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
    feature_snapshot_id: str = Field(pattern=r"^feature_snapshot\.v1:[0-9a-f]{64}$")
    state_id: str = Field(pattern=r"^analysis_state\.v1:[0-9a-f]{64}$")
    transition_decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    strategy_id: str = Field(pattern=r"^strategy_decision\.v1:[0-9a-f]{64}$")
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
    result_id: str = Field(pattern=r"^gold_daily_close_loop_result\.v1:[0-9a-f]{64}$")
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: CanonicalCommitAction
    candidate_state_id: str | None = Field(
        default=None,
        pattern=r"^analysis_state\.v1:[0-9a-f]{64}$",
    )
    candidate_strategy_id: str | None = Field(
        default=None,
        pattern=r"^strategy_decision\.v1:[0-9a-f]{64}$",
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
    feature_snapshot: FeatureSnapshot
    strategy_policy_input: StrategyPolicyInput
    analysis_state: AnalysisState
    transition_decision: StateTransitionPolicyDecision
    strategy_decision: StrategyDecision
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
    head_updated: bool
    artifact_results: tuple[dict[str, Any], ...]


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
    semantic_receipts = {
        (
            item.receipt.result_id,
            item.receipt.action,
            _head_identity(item.receipt.effective_head),
        )
        for item in verified
    }
    if len(semantic_receipts) != 1:
        return DailyCloseHeadLookup(
            status="ambiguous",
            reason_code="daily_close_latest_session_ambiguous",
        )
    selected = min(verified, key=lambda item: item.receipt_path.as_posix())
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
            head_updated=result.canonical_action is not CanonicalCommitAction.HOLD,
            artifact_results=(),
        )

    same_session = _session_bundle_paths(base / session_date.isoformat())
    if same_session:
        raise DailyCloseHeadConflictError("daily-close session already has a committed or partial bundle")

    predecessor = load_gold_daily_close_head(storage_root=root, before_date=session_date)
    predecessor_receipt = _bind_predecessor(loop_input, result, predecessor)
    payloads = _bundle_payloads(loop_input, result)
    pointers = {name: _pointer(root, bundle_path / name, payload) for name, payload in payloads.items()}
    effective_head = _effective_head(result, pointers, predecessor)
    receipt = _build_receipt(
        run_id=run_id,
        result=result,
        current_result=pointers[_RESULT],
        predecessor=predecessor_receipt,
        effective_head=effective_head,
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
                    "result_id": result.result_id,
                },
            )
        ],
        storage_root=root,
    )
    items = [immutable_json_item(bundle_path / name, payload) for name, payload in payloads.items()]
    results = write_immutable_artifact_bundle(items, storage_root=root)
    attempt_path.unlink(missing_ok=True)
    return DailyCloseBundleWriteResult(
        bundle_path=bundle_path,
        result_id=result.result_id,
        receipt_id=receipt.receipt_id,
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
) -> dict[str, dict[str, Any]]:
    payloads = {
        _INPUT: loop_input.model_dump(mode="json"),
        _RESULT: result.model_dump(mode="json"),
        _FEATURE: loop_input.current_feature.model_dump(mode="json"),
        _ANALYSIS: result.analysis_decision.model_dump(mode="json"),
        _ATTRIBUTION: result.price_attribution.model_dump(mode="json"),
        _TRANSITION: result.transition_decision.model_dump(mode="json"),
    }
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
                _STATE: result.analysis_state.model_dump(mode="json"),
                _POLICY_INPUT: result.strategy_policy_input.model_dump(mode="json"),
                _STRATEGY: result.candidate_strategy.model_dump(mode="json"),
                _CONSISTENCY: result.consistency_decision.model_dump(mode="json"),
            }
        )
    return payloads


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
        feature=pointers[_FEATURE],
        state=pointers[_STATE],
        transition=pointers[_TRANSITION],
        strategy_policy_input=pointers[_POLICY_INPUT],
        strategy=pointers[_STRATEGY],
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
) -> DailyCloseCanonicalReceipt:
    value = DailyCloseCanonicalReceiptInput(
        decision_as_of=result.decision_as_of,
        session_date=result.decision_as_of.date(),
        run_id=run_id,
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
        input_payload = _read_payload(resolved / _INPUT, manifest_items)
        result_payload = _read_payload(resolved / _RESULT, manifest_items)
        receipt_payload = _read_payload(resolved / _RECEIPT, manifest_items)
        loop_input = DailyCloseLoopInput.model_validate(input_payload)
        result = DailyCloseLoopResult.model_validate(result_payload)
        receipt = DailyCloseCanonicalReceipt.model_validate(receipt_payload)
        expected_names = set(_bundle_payloads(loop_input, result)) | {_RECEIPT}
        if set(manifest_items) != expected_names:
            return None
        if evaluate_gold_daily_close_loop(loop_input).result_id != result.result_id:
            return None
        _verify_embedded_artifacts(resolved, manifest_items, loop_input, result)
        session = _parse_date(resolved.parents[1].name)
        if (
            session is None
            or receipt.session_date != session
            or receipt.run_id != resolved.parent.name
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
                _FEATURE: receipt.effective_head.feature,
                _STATE: receipt.effective_head.state,
                _TRANSITION: receipt.effective_head.transition,
                _POLICY_INPUT: receipt.effective_head.strategy_policy_input,
                _STRATEGY: receipt.effective_head.strategy,
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
    feature = _read_pointer_model(root, effective.feature, FeatureSnapshot)
    rebuilt = build_feature_snapshot(
        FeatureSnapshotInput.model_validate(
            feature.model_dump(
                mode="python",
                exclude={"data_quality", "payload_hash", "snapshot_id"},
            )
        )
    )
    state = _read_pointer_model(root, effective.state, AnalysisState)
    transition = _read_pointer_model(root, effective.transition, StateTransitionPolicyDecision)
    policy_input = _read_pointer_model(root, effective.strategy_policy_input, StrategyPolicyInput)
    strategy = _read_pointer_model(root, effective.strategy, StrategyDecision)
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
) -> None:
    feature = _read_typed(bundle, _FEATURE, manifest, FeatureSnapshot)
    rebuilt = build_feature_snapshot(
        FeatureSnapshotInput.model_validate(
            feature.model_dump(
                mode="python",
                exclude={"data_quality", "payload_hash", "snapshot_id"},
            )
        )
    )
    if rebuilt != feature or feature != loop_input.current_feature:
        raise ValueError("persisted feature identity is invalid")
    pairs = (
        (_ANALYSIS, GoldAnalysisDecision, result.analysis_decision),
        (_ATTRIBUTION, GoldPriceAttribution, result.price_attribution),
        (_TRANSITION, StateTransitionPolicyDecision, result.transition_decision),
    )
    for name, model, expected in pairs:
        if _read_typed(bundle, name, manifest, model) != expected:
            raise ValueError(f"persisted {name} does not match loop result")
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
            (_STATE, AnalysisState, result.analysis_state),
            (_POLICY_INPUT, StrategyPolicyInput, result.strategy_policy_input),
            (_STRATEGY, StrategyDecision, result.candidate_strategy),
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
