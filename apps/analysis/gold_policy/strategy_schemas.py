"""Immutable contracts for the deterministic daily XAUUSD strategy policy."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.analysis.gold_policy.cme_options_regime import CMEOptionsRegimeSnapshot
from apps.analysis.gold_policy.attribution_policy import (
    GoldPriceAttribution,
    GoldPriceAttributionV2,
)
from apps.analysis.gold_policy.key_level_schemas import (
    KeyLevelAuthorityStatus,
    KeyLevelComparator,
    KeyLevelLifecycle,
    KeyLevelLifecycleDecision,
    KeyLevelReadModel,
    KeyLevelRole,
)
from apps.analysis.gold_policy.schemas import (
    AlignmentStatus,
    FeatureSnapshotContract,
    FeatureSnapshotV2,
    FreshnessStatus,
    QualityStatus,
    SourceReference,
)
from apps.analysis.gold_policy.state_schemas import (
    AnalysisStage,
    AnalysisState,
    AnalysisStateV2,
    EvidenceScope,
    StateTransitionPolicyDecision,
    StateTransitionPolicyDecisionV2,
)


class StrategyStatus(StrEnum):
    NO_TRADE = "NO_TRADE"
    OBSERVE = "OBSERVE"
    LONG_WATCH = "LONG_WATCH"
    SHORT_WATCH = "SHORT_WATCH"
    LONG_RESEARCH_TRIGGERED = "LONG_RESEARCH_TRIGGERED"
    SHORT_RESEARCH_TRIGGERED = "SHORT_RESEARCH_TRIGGERED"
    INVALIDATED = "INVALIDATED"


class StrategyDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


class OptionsRegime(StrEnum):
    NORMAL = "normal"
    PINNING = "pinning"
    HIGH_GAMMA = "high_gamma"
    STRESS = "stress"
    UNAVAILABLE = "unavailable"


class EventRiskStatus(StrEnum):
    CLEAR = "clear"
    WATCH = "watch"
    BLACKOUT = "blackout"
    UNAVAILABLE = "unavailable"


class NoTradeReasonCode(StrEnum):
    INPUT_LINEAGE_INVALID = "INPUT_LINEAGE_INVALID"
    INPUT_SCOPE_MISMATCH = "INPUT_SCOPE_MISMATCH"
    INPUT_TIME_INVALID = "INPUT_TIME_INVALID"
    DATA_QUALITY_BLOCKED = "DATA_QUALITY_BLOCKED"
    ANALYSIS_STATE_NOT_ACCEPTED = "ANALYSIS_STATE_NOT_ACCEPTED"
    ANALYSIS_STATE_UNAVAILABLE = "ANALYSIS_STATE_UNAVAILABLE"
    EVENT_RISK_UNAVAILABLE = "EVENT_RISK_UNAVAILABLE"
    MAJOR_EVENT_BLACKOUT = "MAJOR_EVENT_BLACKOUT"
    INVALIDATION_NOT_CANONICAL = "INVALIDATION_NOT_CANONICAL"


class ReleaseConditionCode(StrEnum):
    INPUT_LINEAGE_RECONCILED = "INPUT_LINEAGE_RECONCILED"
    INPUT_SCOPE_RECONCILED = "INPUT_SCOPE_RECONCILED"
    INPUT_TIME_RECONCILED = "INPUT_TIME_RECONCILED"
    DATA_QUALITY_READY = "DATA_QUALITY_READY"
    CANONICAL_STATE_ACCEPTED = "CANONICAL_STATE_ACCEPTED"
    DIRECTION_AUTHORITY_AVAILABLE = "DIRECTION_AUTHORITY_AVAILABLE"
    EVENT_RISK_CONFIRMED_SAFE = "EVENT_RISK_CONFIRMED_SAFE"
    EVENT_WINDOW_CLOSED = "EVENT_WINDOW_CLOSED"
    CANONICAL_INVALIDATION_CONFIRMED = "CANONICAL_INVALIDATION_CONFIRMED"


class ReviewTriggerCode(StrEnum):
    ON_INPUT_REBUILT = "ON_INPUT_REBUILT"
    ON_DATA_QUALITY_CHANGE = "ON_DATA_QUALITY_CHANGE"
    ON_CANONICAL_STATE_CHANGE = "ON_CANONICAL_STATE_CHANGE"
    ON_EVENT_RISK_UPDATE = "ON_EVENT_RISK_UPDATE"
    ON_EVENT_WINDOW_CLOSE = "ON_EVENT_WINDOW_CLOSE"
    ON_NEXT_DAILY_CLOSE = "ON_NEXT_DAILY_CLOSE"


OptionsDirectionalBias = Literal["bullish", "bearish", "neutral", "mixed", "unavailable"]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StrategyOptionsRegimeSnapshotInput(_FrozenContract):
    schema_version: Literal["strategy_options_regime.v1"] = "strategy_options_regime.v1"
    source_snapshot_id: str = Field(min_length=1)
    as_of: datetime
    regime: OptionsRegime
    directional_bias: OptionsDirectionalBias
    freshness_status: FreshnessStatus
    quality_status: QualityStatus
    alignment_status: AlignmentStatus
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    policy_version: Literal["strategy_options_regime_policy.v1"] = "strategy_options_regime_policy.v1"

    @field_validator("as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="options regime as_of")

    @model_validator(mode="after")
    def _validate_semantics(self) -> "StrategyOptionsRegimeSnapshotInput":
        _require_refs_not_after(self.source_refs, self.as_of)
        if self.regime is OptionsRegime.UNAVAILABLE:
            if self.directional_bias != "unavailable" or self.quality_status == "accepted":
                raise ValueError("unavailable options regime must be unavailable and unaccepted")
        elif self.directional_bias == "unavailable" and self.quality_status == "accepted":
            raise ValueError("accepted options regime requires an available directional bias")
        return self


class StrategyOptionsRegimeSnapshot(StrategyOptionsRegimeSnapshotInput):
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = Field(pattern=r"^strategy_options_regime\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "StrategyOptionsRegimeSnapshot":
        digest = _sha256(canonical_options_regime_json(self))
        if self.payload_hash != digest or self.snapshot_id != f"strategy_options_regime.v1:{digest}":
            raise ValueError("options regime identity does not match canonical payload")
        return self


StrategyOptionsRegimeContract = StrategyOptionsRegimeSnapshot | CMEOptionsRegimeSnapshot


class StrategyEventRiskSnapshotInput(_FrozenContract):
    schema_version: Literal["strategy_event_risk.v1"] = "strategy_event_risk.v1"
    as_of: datetime
    risk_status: EventRiskStatus
    active_event_ids: tuple[str, ...] = ()
    window_start: datetime | None = None
    window_end: datetime | None = None
    next_review_at: datetime | None = None
    quality_status: QualityStatus
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    policy_version: Literal["strategy_event_risk_policy.v1"] = "strategy_event_risk_policy.v1"

    @field_validator("as_of", "window_start", "window_end", "next_review_at")
    @classmethod
    def _normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware_utc(value, field_name="event risk timestamp")

    @model_validator(mode="after")
    def _validate_semantics(self) -> "StrategyEventRiskSnapshotInput":
        _require_refs_not_after(self.source_refs, self.as_of)
        if len(set(self.active_event_ids)) != len(self.active_event_ids):
            raise ValueError("active_event_ids must be unique")
        if self.risk_status is EventRiskStatus.BLACKOUT:
            if not self.active_event_ids or self.window_start is None or self.window_end is None:
                raise ValueError("blackout requires active events and a closed time window")
            if not self.window_start <= self.as_of < self.window_end:
                raise ValueError("blackout as_of must fall inside its event window")
            if self.quality_status == "blocked":
                raise ValueError("verified blackout is not a blocked-quality observation")
        elif self.window_start is not None or self.window_end is not None:
            if self.window_start is None or self.window_end is None:
                raise ValueError("event window bounds must be provided together")
            if self.window_start >= self.window_end:
                raise ValueError("event window start must be before its end")
        if self.risk_status is EventRiskStatus.UNAVAILABLE and self.quality_status == "accepted":
            raise ValueError("unavailable event risk cannot be accepted")
        if self.next_review_at is not None and self.next_review_at < self.as_of:
            raise ValueError("next event review cannot be before event risk as_of")
        return self


class StrategyEventRiskSnapshot(StrategyEventRiskSnapshotInput):
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = Field(pattern=r"^strategy_event_risk\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "StrategyEventRiskSnapshot":
        digest = _sha256(canonical_event_risk_json(self))
        if self.payload_hash != digest or self.snapshot_id != f"strategy_event_risk.v1:{digest}":
            raise ValueError("event risk identity does not match canonical payload")
        return self


class StrategyPolicyInput(_FrozenContract):
    schema_version: Literal["strategy_policy_input.v1"] = "strategy_policy_input.v1"
    asset: Literal["XAUUSD"] = "XAUUSD"
    scope: Literal[EvidenceScope.DAILY_CLOSE] = EvidenceScope.DAILY_CLOSE
    decision_as_of: datetime
    feature_snapshot: FeatureSnapshotContract
    analysis_state: AnalysisState
    state_transition: StateTransitionPolicyDecision
    price_attribution: GoldPriceAttribution | GoldPriceAttributionV2
    key_levels: tuple[KeyLevelReadModel, ...] = ()
    key_level_decisions: tuple[KeyLevelLifecycleDecision, ...] = ()
    options_regime: StrategyOptionsRegimeContract
    event_risk: StrategyEventRiskSnapshot

    @field_validator("decision_as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="strategy decision_as_of")

    @model_validator(mode="after")
    def _validate_unique_inputs(self) -> "StrategyPolicyInput":
        if len({level.state_id for level in self.key_levels}) != len(self.key_levels):
            raise ValueError("key_levels must have unique state identities")
        if len({item.decision_hash for item in self.key_level_decisions}) != len(self.key_level_decisions):
            raise ValueError("key_level_decisions must have unique identities")
        return self


class StrategyPolicyInputV2(_FrozenContract):
    """Versioned strategy input bound to the orthogonal AnalysisState v2."""

    schema_version: Literal["strategy_policy_input.v2"] = "strategy_policy_input.v2"
    asset: Literal["XAUUSD"] = "XAUUSD"
    scope: Literal[EvidenceScope.DAILY_CLOSE] = EvidenceScope.DAILY_CLOSE
    decision_as_of: datetime
    feature_snapshot: FeatureSnapshotV2
    analysis_state: AnalysisStateV2
    state_transition: StateTransitionPolicyDecisionV2
    price_attribution: GoldPriceAttributionV2
    key_levels: tuple[KeyLevelReadModel, ...] = ()
    key_level_decisions: tuple[KeyLevelLifecycleDecision, ...] = ()
    options_regime: StrategyOptionsRegimeContract
    event_risk: StrategyEventRiskSnapshot

    @field_validator("decision_as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="strategy v2 decision_as_of")

    @model_validator(mode="after")
    def _validate_v2_lineage_keys(self) -> "StrategyPolicyInputV2":
        if len({level.state_id for level in self.key_levels}) != len(self.key_levels):
            raise ValueError("key_levels must have unique state identities")
        if len({item.decision_hash for item in self.key_level_decisions}) != len(self.key_level_decisions):
            raise ValueError("key_level_decisions must have unique identities")
        if self.analysis_state.scope is not self.scope:
            raise ValueError("strategy v2 scope must match analysis state")
        if self.state_transition.to_state_id != self.analysis_state.state_id:
            raise ValueError("strategy v2 transition must bind its analysis state")
        if (
            self.state_transition.to_direction != self.analysis_state.direction
            or self.state_transition.to_direction_tilt != self.analysis_state.direction_tilt
            or self.state_transition.to_market_regime != self.analysis_state.market_regime
            or self.state_transition.to_trend_maturity != self.analysis_state.trend_maturity
        ):
            raise ValueError("strategy v2 transition projection must match analysis state")
        return self


class StrategyLevelReference(_FrozenContract):
    level_id: str = Field(pattern=r"^key_level\.v1:[0-9a-f]{64}$")
    state_id: str = Field(pattern=r"^key_level_read_model\.v1:[0-9a-f]{64}$")
    role: KeyLevelRole
    comparator: KeyLevelComparator
    lifecycle: KeyLevelLifecycle
    authority_status: KeyLevelAuthorityStatus
    quality_status: QualityStatus
    effective_from: datetime
    expires_at: datetime
    strategy_eligible_at_decision: bool

    @field_validator("effective_from", "expires_at")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="strategy level reference timestamp")

    @model_validator(mode="after")
    def _validate_window(self) -> "StrategyLevelReference":
        if self.effective_from >= self.expires_at:
            raise ValueError("strategy level reference requires a positive validity window")
        return self


class StrategyDecisionInput(_FrozenContract):
    schema_version: Literal["strategy_decision.v1"] = "strategy_decision.v1"
    asset: Literal["XAUUSD"] = "XAUUSD"
    scope: Literal[EvidenceScope.DAILY_CLOSE] = EvidenceScope.DAILY_CLOSE
    decision_as_of: datetime
    analysis_state_id: str = Field(pattern=r"^analysis_state\.v1:[0-9a-f]{64}$")
    transition_decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_snapshot_id: str = Field(min_length=1)
    attribution_snapshot_ids: tuple[str, str]
    options_snapshot_id: str = Field(min_length=1)
    event_risk_snapshot_id: str = Field(min_length=1)
    level_refs: tuple[StrategyLevelReference, ...] = ()
    key_level_state_ids: tuple[str, ...] = ()
    trigger_level_ids: tuple[str, ...] = ()
    invalidation_level_ids: tuple[str, ...] = ()
    status: StrategyStatus
    direction: StrategyDirection
    stage: AnalysisStage
    reason_codes: tuple[str, ...] = Field(min_length=1)
    no_trade_reason_code: NoTradeReasonCode | None = None
    release_conditions: tuple[ReleaseConditionCode, ...] = ()
    review_triggers: tuple[ReviewTriggerCode, ...] = ()
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    is_trade_instruction: Literal[False] = False
    policy_version: Literal["gold_strategy_policy.v1"] = "gold_strategy_policy.v1"

    @field_validator("decision_as_of")
    @classmethod
    def _normalize_decision_as_of(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="strategy decision as_of")

    @model_validator(mode="after")
    def _validate_decision_semantics(self) -> "StrategyDecisionInput":
        _require_refs_not_after(self.source_refs, self.decision_as_of)
        for values, field_name in (
            (self.key_level_state_ids, "key_level_state_ids"),
            (tuple(ref.state_id for ref in self.level_refs), "level_refs.state_id"),
            (tuple(ref.level_id for ref in self.level_refs), "level_refs.level_id"),
            (self.trigger_level_ids, "trigger_level_ids"),
            (self.invalidation_level_ids, "invalidation_level_ids"),
            (self.reason_codes, "reason_codes"),
            (self.release_conditions, "release_conditions"),
            (self.review_triggers, "review_triggers"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must be unique")
        if set(self.key_level_state_ids) != {ref.state_id for ref in self.level_refs}:
            raise ValueError("key_level_state_ids must exactly match structured level_refs")
        if self.status is StrategyStatus.NO_TRADE:
            if (
                self.direction is not StrategyDirection.NONE
                or self.no_trade_reason_code is None
                or not self.release_conditions
                or not self.review_triggers
            ):
                raise ValueError("NO_TRADE requires no direction, reason, release and review")
            if self.no_trade_reason_code.value not in self.reason_codes:
                raise ValueError("NO_TRADE reason code must be present in reason_codes")
        elif self.no_trade_reason_code is not None or self.release_conditions:
            raise ValueError("only NO_TRADE may carry no-trade release semantics")
        directional_statuses = {
            StrategyStatus.LONG_WATCH: StrategyDirection.LONG,
            StrategyStatus.LONG_RESEARCH_TRIGGERED: StrategyDirection.LONG,
            StrategyStatus.SHORT_WATCH: StrategyDirection.SHORT,
            StrategyStatus.SHORT_RESEARCH_TRIGGERED: StrategyDirection.SHORT,
        }
        if self.status in directional_statuses and self.direction is not directional_statuses[self.status]:
            raise ValueError("directional status and direction must agree")
        if (
            self.status in {StrategyStatus.OBSERVE, StrategyStatus.INVALIDATED}
            and self.direction is not StrategyDirection.NONE
        ):
            raise ValueError("observe and invalidated decisions cannot claim a direction")
        if (
            self.status
            in {
                StrategyStatus.LONG_RESEARCH_TRIGGERED,
                StrategyStatus.SHORT_RESEARCH_TRIGGERED,
            }
            and not self.trigger_level_ids
        ):
            raise ValueError("triggered research decision requires a formal trigger level")
        if (
            self.status
            in {
                StrategyStatus.LONG_RESEARCH_TRIGGERED,
                StrategyStatus.SHORT_RESEARCH_TRIGGERED,
            }
            and not self.invalidation_level_ids
        ):
            raise ValueError("triggered research decision requires a formal invalidation level")
        if any(not level_id.startswith("key_level.v1:") for level_id in self.trigger_level_ids):
            raise ValueError("trigger_level_ids must reference formal key-level definitions")
        if any(not level_id.startswith("key_level.v1:") for level_id in self.invalidation_level_ids):
            raise ValueError("invalidation_level_ids must reference formal key-level definitions")
        trigger_refs = {ref.level_id for ref in self.level_refs if ref.role is KeyLevelRole.TRIGGER}
        invalidation_refs = {ref.level_id for ref in self.level_refs if ref.role is KeyLevelRole.INVALIDATION}
        if not set(self.trigger_level_ids).issubset(trigger_refs):
            raise ValueError("trigger levels must bind structured trigger lineage")
        if not set(self.invalidation_level_ids).issubset(invalidation_refs):
            raise ValueError("invalidation levels must bind structured invalidation lineage")
        if set(self.trigger_level_ids).intersection(self.invalidation_level_ids):
            raise ValueError("the same formal level cannot be both trigger and invalidation")
        if self.status in {
            StrategyStatus.LONG_RESEARCH_TRIGGERED,
            StrategyStatus.SHORT_RESEARCH_TRIGGERED,
        }:
            expected_comparator = (
                KeyLevelComparator.ABOVE_OR_EQUAL
                if self.status is StrategyStatus.LONG_RESEARCH_TRIGGERED
                else KeyLevelComparator.BELOW_OR_EQUAL
            )
            selected_ids = set(self.trigger_level_ids).union(self.invalidation_level_ids)
            selected_refs = tuple(ref for ref in self.level_refs if ref.level_id in selected_ids)
            if any(
                ref.authority_status is not KeyLevelAuthorityStatus.CANONICAL_XAUUSD_VALIDATED
                or ref.quality_status != "accepted"
                or not ref.strategy_eligible_at_decision
                or not ref.effective_from <= self.decision_as_of < ref.expires_at
                or ref.comparator is not expected_comparator
                for ref in selected_refs
            ):
                raise ValueError("triggered levels must be current canonical eligible lineage")
            if any(
                ref.lifecycle is not KeyLevelLifecycle.HOLDING
                for ref in selected_refs
                if ref.role is KeyLevelRole.TRIGGER
            ):
                raise ValueError("triggered strategy requires a holding trigger level")
            if any(
                ref.lifecycle not in {KeyLevelLifecycle.ACTIVE, KeyLevelLifecycle.HOLDING}
                for ref in selected_refs
                if ref.role is KeyLevelRole.INVALIDATION
            ):
                raise ValueError("triggered strategy requires an active invalidation level")
        return self


class StrategyDecision(StrategyDecisionInput):
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_id: str = Field(pattern=r"^strategy_decision\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "StrategyDecision":
        digest = _sha256(canonical_strategy_decision_json(self))
        if self.decision_hash != digest or self.decision_id != f"strategy_decision.v1:{digest}":
            raise ValueError("strategy decision identity does not match canonical payload")
        return self


def build_strategy_decision(payload: Mapping[str, Any] | StrategyDecisionInput) -> StrategyDecision:
    value = payload if isinstance(payload, StrategyDecisionInput) else StrategyDecisionInput.model_validate(payload)
    normalized = value.model_copy(
        update={
            "key_level_state_ids": tuple(sorted(value.key_level_state_ids)),
            "level_refs": tuple(sorted(value.level_refs, key=lambda ref: ref.state_id)),
            "trigger_level_ids": tuple(sorted(value.trigger_level_ids)),
            "invalidation_level_ids": tuple(sorted(value.invalidation_level_ids)),
            "reason_codes": tuple(dict.fromkeys(value.reason_codes)),
            "release_conditions": tuple(dict.fromkeys(value.release_conditions)),
            "review_triggers": tuple(dict.fromkeys(value.review_triggers)),
            "source_refs": _normalized_source_refs(value.source_refs),
        }
    )
    digest = _sha256(canonical_strategy_decision_json(normalized))
    return StrategyDecision(
        **normalized.model_dump(),
        decision_hash=digest,
        decision_id=f"strategy_decision.v1:{digest}",
    )


class StrategyDecisionV2Input(_FrozenContract):
    """Immutable StrategyDecision contract for AnalysisState v2 consumers."""

    schema_version: Literal["strategy_decision.v2"] = "strategy_decision.v2"
    asset: Literal["XAUUSD"] = "XAUUSD"
    scope: Literal[EvidenceScope.DAILY_CLOSE] = EvidenceScope.DAILY_CLOSE
    decision_as_of: datetime
    analysis_state_id: str = Field(pattern=r"^analysis_state\.v2:[0-9a-f]{64}$")
    transition_decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_snapshot_id: str = Field(min_length=1)
    attribution_snapshot_ids: tuple[str, str]
    options_snapshot_id: str = Field(min_length=1)
    event_risk_snapshot_id: str = Field(min_length=1)
    level_refs: tuple[StrategyLevelReference, ...] = ()
    key_level_state_ids: tuple[str, ...] = ()
    trigger_level_ids: tuple[str, ...] = ()
    invalidation_level_ids: tuple[str, ...] = ()
    status: StrategyStatus
    direction: StrategyDirection
    state_direction: Literal["bullish", "bearish", "neutral", "mixed", "unavailable"]
    direction_tilt: Literal["bullish", "bearish", "none"]
    market_regime: Literal["pressure", "range", "direction_decision", "repair", "trend"]
    trend_maturity: Literal["forming", "watching", "confirmed", "invalidated"]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    no_trade_reason_code: NoTradeReasonCode | None = None
    release_conditions: tuple[ReleaseConditionCode, ...] = ()
    review_triggers: tuple[ReviewTriggerCode, ...] = ()
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    is_trade_instruction: Literal[False] = False
    policy_version: Literal["gold_strategy_policy.v2"] = "gold_strategy_policy.v2"

    @field_validator("decision_as_of")
    @classmethod
    def _normalize_decision_as_of(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="strategy v2 decision as_of")

    @model_validator(mode="after")
    def _validate_semantics(self) -> "StrategyDecisionV2Input":
        _require_refs_not_after(self.source_refs, self.decision_as_of)
        for values, field_name in (
            (self.reason_codes, "reason_codes"),
            (self.key_level_state_ids, "key_level_state_ids"),
            (tuple(ref.state_id for ref in self.level_refs), "level_refs.state_id"),
            (tuple(ref.level_id for ref in self.level_refs), "level_refs.level_id"),
            (self.trigger_level_ids, "trigger_level_ids"),
            (self.invalidation_level_ids, "invalidation_level_ids"),
            (self.release_conditions, "release_conditions"),
            (self.review_triggers, "review_triggers"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must be unique")
        if set(self.key_level_state_ids) != {ref.state_id for ref in self.level_refs}:
            raise ValueError("key_level_state_ids must exactly match structured level_refs")
        if self.state_direction == "mixed" and self.direction is not StrategyDirection.NONE:
            raise ValueError("mixed state direction cannot produce a directional strategy")
        if self.status is StrategyStatus.NO_TRADE:
            if (
                self.direction is not StrategyDirection.NONE
                or self.no_trade_reason_code is None
                or not self.release_conditions
                or not self.review_triggers
            ):
                raise ValueError("NO_TRADE requires no direction, reason, release and review")
            if self.no_trade_reason_code.value not in self.reason_codes:
                raise ValueError("NO_TRADE reason code must be present in reason_codes")
        elif self.no_trade_reason_code is not None:
            raise ValueError("only NO_TRADE may carry a no-trade reason")
        if self.status is not StrategyStatus.NO_TRADE and (self.release_conditions or self.review_triggers):
            raise ValueError("only NO_TRADE may carry release or review semantics")
        expected = {
            StrategyStatus.LONG_WATCH: StrategyDirection.LONG,
            StrategyStatus.LONG_RESEARCH_TRIGGERED: StrategyDirection.LONG,
            StrategyStatus.SHORT_WATCH: StrategyDirection.SHORT,
            StrategyStatus.SHORT_RESEARCH_TRIGGERED: StrategyDirection.SHORT,
        }
        if self.status in expected and self.direction is not expected[self.status]:
            raise ValueError("directional status and direction must agree")
        if (
            self.status in {StrategyStatus.OBSERVE, StrategyStatus.INVALIDATED}
            and self.direction is not StrategyDirection.NONE
        ):
            raise ValueError("observe and invalidated decisions cannot claim a direction")
        if any(not level_id.startswith("key_level.v1:") for level_id in self.trigger_level_ids):
            raise ValueError("trigger_level_ids must reference formal key-level definitions")
        if any(not level_id.startswith("key_level.v1:") for level_id in self.invalidation_level_ids):
            raise ValueError("invalidation_level_ids must reference formal key-level definitions")
        trigger_refs = {ref.level_id: ref for ref in self.level_refs if ref.role is KeyLevelRole.TRIGGER}
        invalidation_refs = {ref.level_id: ref for ref in self.level_refs if ref.role is KeyLevelRole.INVALIDATION}
        if not set(self.trigger_level_ids).issubset(trigger_refs):
            raise ValueError("trigger levels must bind structured trigger lineage")
        if not set(self.invalidation_level_ids).issubset(invalidation_refs):
            raise ValueError("invalidation levels must bind structured invalidation lineage")
        if set(self.trigger_level_ids).intersection(self.invalidation_level_ids):
            raise ValueError("trigger and invalidation levels cannot overlap")
        if self.status in {StrategyStatus.LONG_RESEARCH_TRIGGERED, StrategyStatus.SHORT_RESEARCH_TRIGGERED}:
            if not self.trigger_level_ids or not self.invalidation_level_ids:
                raise ValueError("triggered v2 strategy requires trigger and invalidation levels")
            selected_trigger = [trigger_refs.get(level_id) for level_id in self.trigger_level_ids]
            selected_invalidation = [invalidation_refs.get(level_id) for level_id in self.invalidation_level_ids]
            expected_comparator = (
                KeyLevelComparator.ABOVE_OR_EQUAL
                if self.status is StrategyStatus.LONG_RESEARCH_TRIGGERED
                else KeyLevelComparator.BELOW_OR_EQUAL
            )
            selected_refs = (*selected_trigger, *selected_invalidation)
            if any(
                ref is None
                or ref.authority_status is not KeyLevelAuthorityStatus.CANONICAL_XAUUSD_VALIDATED
                or ref.quality_status != "accepted"
                or not ref.strategy_eligible_at_decision
                or not ref.effective_from <= self.decision_as_of < ref.expires_at
                or ref.comparator is not expected_comparator
                for ref in selected_refs
            ):
                raise ValueError("triggered v2 levels require current canonical lineage")
            if any(ref is None or ref.lifecycle is not KeyLevelLifecycle.HOLDING for ref in selected_trigger):
                raise ValueError("triggered v2 strategy requires eligible holding trigger lineage")
            if any(
                ref is None or ref.lifecycle not in {KeyLevelLifecycle.ACTIVE, KeyLevelLifecycle.HOLDING}
                for ref in selected_invalidation
            ):
                raise ValueError("triggered v2 strategy requires eligible active invalidation lineage")
        return self


class StrategyDecisionV2(StrategyDecisionV2Input):
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_id: str = Field(pattern=r"^strategy_decision\.v2:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "StrategyDecisionV2":
        digest = _sha256(canonical_strategy_decision_v2_json(self))
        if self.decision_hash != digest or self.decision_id != f"strategy_decision.v2:{digest}":
            raise ValueError("strategy v2 decision identity does not match canonical payload")
        return self


def build_strategy_decision_v2(
    payload: Mapping[str, Any] | StrategyDecisionV2Input,
) -> StrategyDecisionV2:
    value = payload if isinstance(payload, StrategyDecisionV2Input) else StrategyDecisionV2Input.model_validate(payload)
    normalized = value.model_copy(
        update={
            "key_level_state_ids": tuple(sorted(value.key_level_state_ids)),
            "level_refs": tuple(sorted(value.level_refs, key=lambda ref: ref.state_id)),
            "trigger_level_ids": tuple(sorted(value.trigger_level_ids)),
            "invalidation_level_ids": tuple(sorted(value.invalidation_level_ids)),
            "reason_codes": tuple(dict.fromkeys(value.reason_codes)),
            "release_conditions": tuple(dict.fromkeys(value.release_conditions)),
            "review_triggers": tuple(dict.fromkeys(value.review_triggers)),
            "source_refs": _normalized_source_refs(value.source_refs),
        }
    )
    digest = _sha256(canonical_strategy_decision_v2_json(normalized))
    return StrategyDecisionV2(
        **normalized.model_dump(), decision_hash=digest, decision_id=f"strategy_decision.v2:{digest}"
    )


def build_strategy_options_regime(
    payload: Mapping[str, Any] | StrategyOptionsRegimeSnapshotInput | StrategyOptionsRegimeSnapshot,
) -> StrategyOptionsRegimeSnapshot:
    if isinstance(payload, StrategyOptionsRegimeSnapshot):
        return payload
    value = (
        payload
        if isinstance(payload, StrategyOptionsRegimeSnapshotInput)
        else StrategyOptionsRegimeSnapshotInput.model_validate(payload)
    )
    normalized = value.model_copy(update={"source_refs": _normalized_source_refs(value.source_refs)})
    digest = _sha256(canonical_options_regime_json(normalized))
    return StrategyOptionsRegimeSnapshot(
        **normalized.model_dump(),
        payload_hash=digest,
        snapshot_id=f"strategy_options_regime.v1:{digest}",
    )


def build_strategy_event_risk(
    payload: Mapping[str, Any] | StrategyEventRiskSnapshotInput | StrategyEventRiskSnapshot,
) -> StrategyEventRiskSnapshot:
    if isinstance(payload, StrategyEventRiskSnapshot):
        return payload
    value = (
        payload
        if isinstance(payload, StrategyEventRiskSnapshotInput)
        else StrategyEventRiskSnapshotInput.model_validate(payload)
    )
    normalized = value.model_copy(
        update={
            "active_event_ids": tuple(sorted(value.active_event_ids)),
            "source_refs": _normalized_source_refs(value.source_refs),
        }
    )
    digest = _sha256(canonical_event_risk_json(normalized))
    return StrategyEventRiskSnapshot(
        **normalized.model_dump(),
        payload_hash=digest,
        snapshot_id=f"strategy_event_risk.v1:{digest}",
    )


def canonical_strategy_decision_json(value: StrategyDecisionInput | StrategyDecision) -> str:
    payload = value.model_dump(
        mode="json",
        exclude={"decision_hash", "decision_id"},
    )
    payload["key_level_state_ids"] = sorted(value.key_level_state_ids)
    payload["trigger_level_ids"] = sorted(value.trigger_level_ids)
    payload["invalidation_level_ids"] = sorted(value.invalidation_level_ids)
    payload["level_refs"] = [
        ref.model_dump(mode="json") for ref in sorted(value.level_refs, key=lambda ref: ref.state_id)
    ]
    payload["source_refs"] = [ref.model_dump(mode="json") for ref in _normalized_source_refs(value.source_refs)]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_strategy_decision_v2_json(
    value: StrategyDecisionV2Input | StrategyDecisionV2,
) -> str:
    payload = value.model_dump(mode="json", exclude={"decision_hash", "decision_id"})
    payload["reason_codes"] = list(dict.fromkeys(value.reason_codes))
    payload["key_level_state_ids"] = sorted(value.key_level_state_ids)
    payload["trigger_level_ids"] = sorted(value.trigger_level_ids)
    payload["invalidation_level_ids"] = sorted(value.invalidation_level_ids)
    payload["level_refs"] = [
        ref.model_dump(mode="json") for ref in sorted(value.level_refs, key=lambda ref: ref.state_id)
    ]
    payload["release_conditions"] = list(dict.fromkeys(value.release_conditions))
    payload["review_triggers"] = list(dict.fromkeys(value.review_triggers))
    payload["source_refs"] = [ref.model_dump(mode="json") for ref in _normalized_source_refs(value.source_refs)]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_options_regime_json(
    value: StrategyOptionsRegimeSnapshotInput | StrategyOptionsRegimeSnapshot,
) -> str:
    payload = value.model_dump(mode="json", exclude={"payload_hash", "snapshot_id"})
    payload["source_refs"] = [ref.model_dump(mode="json") for ref in _normalized_source_refs(value.source_refs)]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_event_risk_json(
    value: StrategyEventRiskSnapshotInput | StrategyEventRiskSnapshot,
) -> str:
    payload = value.model_dump(mode="json", exclude={"payload_hash", "snapshot_id"})
    payload["active_event_ids"] = sorted(value.active_event_ids)
    payload["source_refs"] = [ref.model_dump(mode="json") for ref in _normalized_source_refs(value.source_refs)]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _require_refs_not_after(refs: tuple[SourceReference, ...], as_of: datetime) -> None:
    if len({(ref.source, ref.reference, ref.retrieved_at) for ref in refs}) != len(refs):
        raise ValueError("source_refs must be unique")
    if any(_aware_utc(ref.retrieved_at, field_name="source retrieved_at") > as_of for ref in refs):
        raise ValueError("source reference cannot be retrieved after its owning snapshot")


def _normalized_source_refs(refs: tuple[SourceReference, ...]) -> tuple[SourceReference, ...]:
    return tuple(sorted(refs, key=lambda ref: (ref.source, ref.reference, ref.retrieved_at)))


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
