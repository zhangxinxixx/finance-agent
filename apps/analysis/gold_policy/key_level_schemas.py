"""Immutable contracts for the formal XAUUSD key-level lifecycle."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.analysis.gold_policy.schemas import SourceReference
from apps.analysis.gold_policy.state_schemas import EvidenceScope


class KeyLevelKind(StrEnum):
    POINT = "point"
    BAND = "band"


class KeyLevelRole(StrEnum):
    SUPPORT = "support"
    RESISTANCE = "resistance"
    TRIGGER = "trigger"
    INVALIDATION = "invalidation"
    MAGNET_PIN = "magnet_pin"
    VOLATILITY_HUB = "volatility_hub"
    GAMMA_FLIP = "gamma_flip"
    TAIL_PROTECTION = "tail_protection"
    BALANCE_ZONE = "balance_zone"


class KeyLevelComparator(StrEnum):
    ABOVE_OR_EQUAL = "above_or_equal"
    BELOW_OR_EQUAL = "below_or_equal"
    NON_DIRECTIONAL = "non_directional"


class KeyLevelLifecycle(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    TESTED = "tested"
    HOLDING = "holding"
    BROKEN = "broken"
    RECLAIMED = "reclaimed"
    RETIRED = "retired"


class KeyLevelAuthorityStatus(StrEnum):
    CANDIDATE_ONLY = "candidate_only"
    FORMALLY_CONFIRMED = "formally_confirmed"
    CANONICAL_XAUUSD_VALIDATED = "canonical_xauusd_validated"


class KeyLevelQualificationClass(StrEnum):
    PROPOSAL_ONLY = "proposal_only"
    FORMAL_STRUCTURE = "formal_structure"
    CANONICAL_MARKET = "canonical_market"
    SYSTEM_AUTHORITY = "system_authority"


class KeyLevelSourceRole(StrEnum):
    OFFICIAL_MARKET = "official_market"
    CME_OPTIONS_MODEL = "cme_options_model"
    CME_LARGE_OI = "cme_large_oi"
    JIN10_SUPPLEMENTAL = "jin10_supplemental"
    LLM_EXTRACTED = "llm_extracted"
    MANUAL_OBSERVATION = "manual_observation"
    VALIDATION_FALLBACK = "validation_fallback"
    SYSTEM_SCHEDULER = "system_scheduler"


class KeyLevelSourceInstrument(StrEnum):
    XAUUSD_SPOT = "XAUUSD_SPOT"
    GC_FUTURES = "GC_FUTURES"


class KeyLevelEvidenceFactor(StrEnum):
    LEVEL_PROPOSAL = "level_proposal"
    OPEN_INTEREST = "open_interest"
    GEX_WALL = "gex_wall"
    OI_CHANGE = "oi_change"
    VOLUME = "volume"
    PRICE_STRUCTURE = "price_structure"
    REPEATED_REACTION = "repeated_reaction"
    OFFICIAL_CLOSE = "official_close"
    PRICE_TOUCH = "price_touch"
    HOLD_WINDOW = "hold_window"
    BREAK_WINDOW = "break_window"
    RECLAIM_WINDOW = "reclaim_window"
    CONTRACT_EXPIRY = "contract_expiry"
    VALIDITY_EXPIRED = "validity_expired"
    CONFIRMATION_TIMEOUT = "confirmation_timeout"
    FAILURE_WINDOW_ELAPSED = "failure_window_elapsed"


class KeyLevelEvidenceTimeframe(StrEnum):
    M5 = "5m"
    H1 = "1h"
    D1 = "1d"
    W1 = "1w"
    CONTRACT = "contract"
    SYSTEM = "system"


class KeyLevelPublicationStatus(StrEnum):
    FINAL = "FINAL"
    PRELIM = "PRELIM"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class KeyLevelCalculationMethod(StrEnum):
    NONE = "none"
    BLACK76 = "black76"
    PROXY = "proxy"
    OI_INVENTORY = "oi_inventory"
    PRICE_CANDLE = "price_candle"
    SYSTEM_RULE = "system_rule"


class KeyLevelRetirementRule(StrEnum):
    CONTRACT_EXPIRED = "contract_expired"
    VALIDITY_EXPIRED = "validity_expired"
    CONFIRMATION_TIMEOUT = "confirmation_timeout"
    FAILURE_WINDOW_ELAPSED = "failure_window_elapsed"


class KeyLevelRuleCode(StrEnum):
    DISCOVER_PROPOSAL = "discover_proposal.v1"
    CONFIRM_CME_TWO_SNAPSHOT = "confirm_cme_two_snapshot.v1"
    CONFIRM_REPEATED_PRICE = "confirm_repeated_price.v1"
    ACTIVATE_CANONICAL_CLOSE = "activate_canonical_close.v1"
    APPROACH_OBSERVE = "approach_observe.v1"
    TOUCH_CANONICAL_RANGE = "touch_canonical_range.v1"
    HOLD_CANONICAL_WINDOW = "hold_canonical_window.v1"
    BREAK_CANONICAL_WINDOW = "break_canonical_window.v1"
    RECLAIM_CANONICAL_WINDOW = "reclaim_canonical_window.v1"
    RETIRE_SYSTEM_RULE = "retire_system_rule.v1"
    MAINTAIN_NO_OP = "maintain_no_op.v1"
    REJECT_FAIL_CLOSED = "reject_fail_closed.v1"


class KeyLevelEventType(StrEnum):
    DISCOVER = "discover"
    CONFIRM = "confirm"
    ACTIVATE = "activate"
    APPROACH = "approach"
    TOUCH = "touch"
    HOLD_CONFIRMED = "hold_confirmed"
    BREAK_CONFIRMED = "break_confirmed"
    RECLAIM_CONFIRMED = "reclaim_confirmed"
    RECLAIM_HOLD_CONFIRMED = "reclaim_hold_confirmed"
    RETIRE = "retire"
    NO_OP = "no_op"


class KeyLevelTransitionAction(StrEnum):
    DISCOVER = "discover"
    CONFIRM = "confirm"
    ACTIVATE = "activate"
    TEST = "test"
    HOLD = "hold"
    BREAK = "break"
    RECLAIM = "reclaim"
    RETIRE = "retire"
    MAINTAIN = "maintain"
    REJECT = "reject"


QualityStatus = Literal["accepted", "observe", "blocked"]
FreshnessStatus = Literal["fresh", "stale", "missing"]
AlignmentStatus = Literal["aligned", "misaligned", "unknown"]

_PRICE_TICK = Decimal("0.01")
STRATEGY_KEY_LEVEL_ROLES = frozenset(
    {
        KeyLevelRole.SUPPORT,
        KeyLevelRole.RESISTANCE,
        KeyLevelRole.TRIGGER,
        KeyLevelRole.INVALIDATION,
    }
)


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class KeyLevelRuleSet(_FrozenContract):
    schema_version: Literal["key_level_rules.v1"] = "key_level_rules.v1"
    confirmation_rule: Literal["qualified_two_snapshot_or_repeated_price.v1"] = (
        "qualified_two_snapshot_or_repeated_price.v1"
    )
    activation_rule: Literal["canonical_close_structure.v1"] = "canonical_close_structure.v1"
    hold_rule: Literal["canonical_close_window.v1"] = "canonical_close_window.v1"
    break_rule: Literal["canonical_break_window.v1"] = "canonical_break_window.v1"
    reclaim_rule: Literal["canonical_reclaim_window.v1"] = "canonical_reclaim_window.v1"
    failure_rule: Literal["system_failure_window.v1"] = "system_failure_window.v1"
    failure_window_seconds: int = Field(default=86_400, ge=300)
    reaction_tolerance_bps: int = Field(default=10, ge=1, le=100)
    repeated_reaction_min_count: int = Field(default=2, ge=2, le=10)


class KeyLevelSpecInput(_FrozenContract):
    schema_version: Literal["key_level_spec.v1"] = "key_level_spec.v1"
    asset: Literal["XAUUSD"] = "XAUUSD"
    target_instrument: Literal["XAUUSD_SPOT"] = "XAUUSD_SPOT"
    scope: EvidenceScope
    level_kind: KeyLevelKind
    role: KeyLevelRole
    comparator: KeyLevelComparator
    reference_price: Decimal | None = Field(default=None, gt=0)
    band_lower: Decimal | None = Field(default=None, gt=0)
    band_upper: Decimal | None = Field(default=None, gt=0)
    effective_from: datetime
    expires_at: datetime
    origin_key: str = Field(min_length=1)
    origin_source_role: KeyLevelSourceRole
    origin_instrument: KeyLevelSourceInstrument
    origin_contract_id: str | None = None
    rule_set: KeyLevelRuleSet = Field(default_factory=KeyLevelRuleSet)
    identity_policy_version: Literal["key_level_identity.v1"] = "key_level_identity.v1"

    @field_validator("reference_price", "band_lower", "band_upper")
    @classmethod
    def _normalize_price(cls, value: Decimal | None) -> Decimal | None:
        return value.quantize(_PRICE_TICK, rounding=ROUND_HALF_UP) if value is not None else None

    @field_validator("effective_from", "expires_at")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="key level validity time")

    @model_validator(mode="after")
    def _validate_shape(self) -> "KeyLevelSpecInput":
        is_point = self.reference_price is not None
        is_band = self.band_lower is not None or self.band_upper is not None
        if self.level_kind is KeyLevelKind.POINT and (not is_point or is_band):
            raise ValueError("point level requires only reference_price")
        if self.level_kind is KeyLevelKind.BAND and (is_point or self.band_lower is None or self.band_upper is None):
            raise ValueError("band level requires only lower and upper prices")
        if self.band_lower is not None and self.band_upper is not None and self.band_lower >= self.band_upper:
            raise ValueError("band lower must be below band upper")
        if self.effective_from >= self.expires_at:
            raise ValueError("effective_from must be before expires_at")
        cme_origin = self.origin_source_role in {
            KeyLevelSourceRole.CME_OPTIONS_MODEL,
            KeyLevelSourceRole.CME_LARGE_OI,
        }
        if cme_origin and (
            self.origin_instrument is not KeyLevelSourceInstrument.GC_FUTURES or not self.origin_contract_id
        ):
            raise ValueError("CME-origin level requires GC instrument and contract identity")
        if not cme_origin and self.origin_contract_id is not None:
            raise ValueError("non-CME level cannot carry a CME contract identity")
        if (
            self.origin_source_role is KeyLevelSourceRole.OFFICIAL_MARKET
            and self.origin_instrument is not KeyLevelSourceInstrument.XAUUSD_SPOT
        ):
            raise ValueError("official-market origin must preserve XAUUSD spot identity")
        if self.role is KeyLevelRole.SUPPORT and self.comparator is not KeyLevelComparator.ABOVE_OR_EQUAL:
            raise ValueError("support level must hold on the above-or-equal side")
        if self.role is KeyLevelRole.RESISTANCE and self.comparator is not KeyLevelComparator.BELOW_OR_EQUAL:
            raise ValueError("resistance level must hold on the below-or-equal side")
        if self.role in {KeyLevelRole.TRIGGER, KeyLevelRole.INVALIDATION} and (
            self.comparator is KeyLevelComparator.NON_DIRECTIONAL
        ):
            raise ValueError("trigger and invalidation levels require an explicit comparator")
        if (
            self.role
            not in {
                KeyLevelRole.SUPPORT,
                KeyLevelRole.RESISTANCE,
                KeyLevelRole.TRIGGER,
                KeyLevelRole.INVALIDATION,
            }
            and self.comparator is not KeyLevelComparator.NON_DIRECTIONAL
        ):
            raise ValueError("structural display level must remain non-directional")
        return self


class KeyLevelSpec(KeyLevelSpecInput):
    definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    level_id: str = Field(pattern=r"^key_level\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "KeyLevelSpec":
        digest = _sha256(canonical_key_level_spec_json(self))
        if self.definition_hash != digest or self.level_id != f"key_level.v1:{digest}":
            raise ValueError("key level identity does not match its canonical definition")
        return self


class KeyLevelQualificationReceiptInput(_FrozenContract):
    schema_version: Literal["key_level_qualification_receipt.v1"] = "key_level_qualification_receipt.v1"
    source_role: KeyLevelSourceRole
    source_instrument: KeyLevelSourceInstrument
    qualification_class: KeyLevelQualificationClass
    scope: EvidenceScope
    subject_level_id: str = Field(pattern=r"^key_level\.v1:[0-9a-f]{64}$")
    publication_status: KeyLevelPublicationStatus
    calculation_method: KeyLevelCalculationMethod
    qualified_factors: tuple[KeyLevelEvidenceFactor, ...] = Field(min_length=1)
    qualified_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    current_snapshot_id: str
    previous_snapshot_id: str | None = None
    current_snapshot_as_of: datetime
    previous_snapshot_as_of: datetime | None = None
    contract_id: str | None = None
    issued_at: datetime
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    source_role_policy_version: Literal["source_role_policy.v1"] = "source_role_policy.v1"

    @field_validator("issued_at", "current_snapshot_as_of", "previous_snapshot_as_of")
    @classmethod
    def _normalize_issued_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _aware_utc(value, field_name="qualification receipt issued_at")

    @model_validator(mode="after")
    def _validate_receipt(self) -> "KeyLevelQualificationReceiptInput":
        _require_source_refs(self.source_refs, as_of=self.issued_at)
        if len(set(self.qualified_snapshot_ids)) != len(self.qualified_snapshot_ids):
            raise ValueError("qualified snapshot ids must be unique")
        if len(set(self.qualified_factors)) != len(self.qualified_factors):
            raise ValueError("qualified evidence factors must be unique")
        if self.current_snapshot_id not in self.qualified_snapshot_ids:
            raise ValueError("current snapshot must be included in qualified snapshot ids")
        if self.previous_snapshot_id is not None and (
            self.previous_snapshot_id == self.current_snapshot_id
            or self.previous_snapshot_id not in self.qualified_snapshot_ids
        ):
            raise ValueError("previous snapshot must be distinct and qualified")
        if (self.previous_snapshot_id is None) != (self.previous_snapshot_as_of is None):
            raise ValueError("previous snapshot identity and timestamp must be present together")
        if self.current_snapshot_as_of > self.issued_at:
            raise ValueError("current snapshot cannot be after receipt issue time")
        if self.previous_snapshot_as_of is not None and not (
            self.previous_snapshot_as_of < self.current_snapshot_as_of
        ):
            raise ValueError("previous snapshot must predate current snapshot")
        for snapshot_id in self.qualified_snapshot_ids:
            if not any(ref.source == "input_snapshot" and ref.reference == snapshot_id for ref in self.source_refs):
                raise ValueError("every qualified snapshot must have an input_snapshot source ref")

        proposal_roles = {
            KeyLevelSourceRole.JIN10_SUPPLEMENTAL,
            KeyLevelSourceRole.LLM_EXTRACTED,
            KeyLevelSourceRole.MANUAL_OBSERVATION,
            KeyLevelSourceRole.VALIDATION_FALLBACK,
        }
        if self.source_role in proposal_roles and (
            self.qualification_class is not KeyLevelQualificationClass.PROPOSAL_ONLY
            or self.publication_status is not KeyLevelPublicationStatus.NOT_APPLICABLE
            or self.calculation_method
            not in {
                KeyLevelCalculationMethod.NONE,
                KeyLevelCalculationMethod.PRICE_CANDLE,
            }
        ):
            raise ValueError("supplemental and fallback sources are proposal-only")
        if self.source_role is KeyLevelSourceRole.CME_LARGE_OI and (
            self.qualification_class is not KeyLevelQualificationClass.PROPOSAL_ONLY
            or self.source_instrument is not KeyLevelSourceInstrument.GC_FUTURES
            or self.calculation_method is not KeyLevelCalculationMethod.OI_INVENTORY
            or not self.contract_id
        ):
            raise ValueError("single CME OI receipt must remain proposal-only")
        if self.source_role is KeyLevelSourceRole.CME_OPTIONS_MODEL and (
            self.qualification_class is not KeyLevelQualificationClass.FORMAL_STRUCTURE
            or self.source_instrument is not KeyLevelSourceInstrument.GC_FUTURES
            or self.calculation_method not in {KeyLevelCalculationMethod.BLACK76, KeyLevelCalculationMethod.PROXY}
            or not self.contract_id
        ):
            raise ValueError("CME options model receipt requires qualified GC model lineage")
        if self.source_role is KeyLevelSourceRole.OFFICIAL_MARKET and (
            self.qualification_class is not KeyLevelQualificationClass.CANONICAL_MARKET
            or self.source_instrument is not KeyLevelSourceInstrument.XAUUSD_SPOT
            or self.publication_status is not KeyLevelPublicationStatus.NOT_APPLICABLE
            or self.calculation_method is not KeyLevelCalculationMethod.PRICE_CANDLE
        ):
            raise ValueError("official market receipt requires canonical XAUUSD candle lineage")
        if self.source_role is KeyLevelSourceRole.SYSTEM_SCHEDULER and (
            self.qualification_class is not KeyLevelQualificationClass.SYSTEM_AUTHORITY
            or self.publication_status is not KeyLevelPublicationStatus.NOT_APPLICABLE
            or self.calculation_method is not KeyLevelCalculationMethod.SYSTEM_RULE
        ):
            raise ValueError("system scheduler receipt requires system authority")
        return self


class KeyLevelQualificationReceipt(KeyLevelQualificationReceiptInput):
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_id: str = Field(pattern=r"^key_level_qualification\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "KeyLevelQualificationReceipt":
        digest = _sha256(canonical_key_level_qualification_json(self))
        if self.receipt_hash != digest or self.receipt_id != f"key_level_qualification.v1:{digest}":
            raise ValueError("qualification receipt identity does not match its canonical payload")
        return self


class KeyLevelPriceFact(_FrozenContract):
    schema_version: Literal["key_level_price_fact.v1"] = "key_level_price_fact.v1"
    snapshot_id: str
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    window_closes: tuple[Decimal, ...] = Field(min_length=1)
    window_start: datetime
    window_end: datetime
    window_complete: bool
    rule_code: Literal[
        "price_structure",
        "touch",
        "hold",
        "break",
        "reclaim",
    ]

    @field_validator("open", "high", "low", "close", "window_closes")
    @classmethod
    def _normalize_prices(cls, value: Decimal | tuple[Decimal, ...]):
        if isinstance(value, tuple):
            return tuple(item.quantize(_PRICE_TICK, rounding=ROUND_HALF_UP) for item in value)
        return value.quantize(_PRICE_TICK, rounding=ROUND_HALF_UP)

    @field_validator("window_start", "window_end")
    @classmethod
    def _normalize_window_time(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="price fact window time")

    @model_validator(mode="after")
    def _validate_prices(self) -> "KeyLevelPriceFact":
        if self.low > self.high:
            raise ValueError("price fact low cannot exceed high")
        if not self.low <= min(self.open, self.close, *self.window_closes) <= self.high:
            raise ValueError("price fact values must remain inside low/high")
        if not self.low <= max(self.open, self.close, *self.window_closes) <= self.high:
            raise ValueError("price fact values must remain inside low/high")
        if self.window_start >= self.window_end:
            raise ValueError("price fact window must be ordered")
        return self


class KeyLevelEvidence(_FrozenContract):
    evidence_id: str = Field(min_length=1)
    qualification_receipt: KeyLevelQualificationReceipt
    factors: tuple[KeyLevelEvidenceFactor, ...] = Field(min_length=1)
    timeframe: KeyLevelEvidenceTimeframe
    window_start: datetime
    window_end: datetime
    price_fact: KeyLevelPriceFact | None = None
    quality_status: QualityStatus
    freshness_status: FreshnessStatus
    alignment_status: AlignmentStatus
    as_of: datetime
    projection_method: str | None = None
    basis_snapshot_id: str | None = None
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)

    @field_validator("as_of", "window_start", "window_end")
    @classmethod
    def _normalize_as_of(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="key level evidence as_of")

    @property
    def source_role(self) -> KeyLevelSourceRole:
        return self.qualification_receipt.source_role

    @property
    def source_instrument(self) -> KeyLevelSourceInstrument:
        return self.qualification_receipt.source_instrument

    @property
    def scope(self) -> EvidenceScope:
        return self.qualification_receipt.scope

    @model_validator(mode="after")
    def _validate_evidence(self) -> "KeyLevelEvidence":
        _require_source_refs(self.source_refs, as_of=self.as_of)
        if len(set(self.factors)) != len(self.factors):
            raise ValueError("key level evidence factors must be unique")
        if not set(self.factors).issubset(set(self.qualification_receipt.qualified_factors)):
            raise ValueError("evidence factors must be covered by the qualification receipt")
        if not self.window_start < self.window_end <= self.as_of:
            raise ValueError("evidence window must be ordered and no later than as_of")
        if self.qualification_receipt.issued_at > self.as_of:
            raise ValueError("qualification receipt cannot be issued after evidence as_of")
        if not any(
            ref.source == "qualification_receipt" and ref.reference == self.qualification_receipt.receipt_id
            for ref in self.source_refs
        ):
            raise ValueError("evidence must reference its qualification receipt")
        if KeyLevelEvidenceFactor.OI_CHANGE in self.factors and self.qualification_receipt.previous_snapshot_id is None:
            raise ValueError("OI change evidence requires current and previous snapshot lineage")
        expected_market_timeframes = {
            EvidenceScope.INTRADAY: {
                KeyLevelEvidenceTimeframe.M5,
                KeyLevelEvidenceTimeframe.H1,
            },
            EvidenceScope.DAILY_CLOSE: {KeyLevelEvidenceTimeframe.D1},
            EvidenceScope.WEEKLY_FUNDAMENTAL: {KeyLevelEvidenceTimeframe.W1},
        }
        if (
            self.source_role is KeyLevelSourceRole.OFFICIAL_MARKET
            and self.timeframe not in expected_market_timeframes[self.scope]
        ):
            raise ValueError("canonical market timeframe must match evidence scope")
        if self.source_role is KeyLevelSourceRole.OFFICIAL_MARKET:
            if (
                self.price_fact is None
                or self.price_fact.snapshot_id != self.qualification_receipt.current_snapshot_id
                or self.price_fact.window_start != self.window_start
                or self.price_fact.window_end != self.window_end
            ):
                raise ValueError("official market evidence requires matching structured price fact")
        elif self.price_fact is not None:
            raise ValueError("non-market evidence cannot attach a canonical price fact")
        if (
            self.source_role in {KeyLevelSourceRole.CME_OPTIONS_MODEL, KeyLevelSourceRole.CME_LARGE_OI}
            and self.timeframe is not KeyLevelEvidenceTimeframe.CONTRACT
        ):
            raise ValueError("CME evidence must use contract timeframe")
        if self.source_role is KeyLevelSourceRole.SYSTEM_SCHEDULER and (
            self.timeframe is not KeyLevelEvidenceTimeframe.SYSTEM
        ):
            raise ValueError("system authority evidence must use system timeframe")
        if self.source_instrument is KeyLevelSourceInstrument.GC_FUTURES:
            if self.alignment_status == "aligned" and (not self.projection_method or not self.basis_snapshot_id):
                raise ValueError("aligned GC evidence requires projection method and basis snapshot")
        elif self.projection_method is not None or self.basis_snapshot_id is not None:
            raise ValueError("XAUUSD spot evidence cannot claim a GC projection")
        return self


class KeyLevelEventInput(_FrozenContract):
    schema_version: Literal["key_level_event.v1"] = "key_level_event.v1"
    event_type: KeyLevelEventType
    spec: KeyLevelSpec
    evidence: KeyLevelEvidence
    retirement_rule: KeyLevelRetirementRule | None = None

    @model_validator(mode="after")
    def _validate_event_scope_and_retirement(self) -> "KeyLevelEventInput":
        if self.evidence.scope is not self.spec.scope:
            raise ValueError("key level evidence scope must match level scope")
        if self.evidence.qualification_receipt.subject_level_id != self.spec.level_id:
            raise ValueError("qualification receipt subject must match key level identity")
        if self.event_type is not KeyLevelEventType.RETIRE and self.retirement_rule is not None:
            raise ValueError("retirement metadata is only valid for retire events")
        if self.event_type is KeyLevelEventType.RETIRE and self.retirement_rule is None:
            raise ValueError("retire event requires a closed retirement rule")
        return self


class KeyLevelEvent(KeyLevelEventInput):
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_id: str = Field(pattern=r"^key_level_event\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "KeyLevelEvent":
        digest = _sha256(canonical_key_level_event_json(self))
        if self.event_hash != digest or self.event_id != f"key_level_event.v1:{digest}":
            raise ValueError("key level event identity does not match its canonical payload")
        return self


class KeyLevelReadModelInput(_FrozenContract):
    schema_version: Literal["key_level_read_model.v1"] = "key_level_read_model.v1"
    spec: KeyLevelSpec
    lifecycle: KeyLevelLifecycle
    authority_status: KeyLevelAuthorityStatus
    activation_event: KeyLevelEvent | None = None
    strategy_eligible: bool
    as_of: datetime
    quality_status: QualityStatus
    last_event_id: str = Field(pattern=r"^key_level_event\.v1:[0-9a-f]{64}$")
    test_count: int = Field(ge=0)
    previous_state_id: str | None = Field(
        default=None,
        pattern=r"^key_level_read_model\.v1:[0-9a-f]{64}$",
    )
    source_refs: tuple[SourceReference, ...] = Field(min_length=1)
    policy_version: Literal["key_level_lifecycle_policy.v1"] = "key_level_lifecycle_policy.v1"

    @field_validator("as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime) -> datetime:
        return _aware_utc(value, field_name="key level state as_of")

    @model_validator(mode="after")
    def _validate_state(self) -> "KeyLevelReadModelInput":
        _require_source_refs(self.source_refs, as_of=self.as_of)
        expected_eligible = key_level_strategy_eligible(
            spec=self.spec,
            lifecycle=self.lifecycle,
            authority_status=self.authority_status,
            activation_event=self.activation_event,
            quality_status=self.quality_status,
            as_of=self.as_of,
        )
        if self.strategy_eligible != expected_eligible:
            raise ValueError("strategy_eligible must be derived from lifecycle policy")
        if self.lifecycle in {KeyLevelLifecycle.TESTED, KeyLevelLifecycle.HOLDING} and self.test_count < 1:
            raise ValueError("tested or holding level requires a positive test_count")
        if (
            self.lifecycle
            in {
                KeyLevelLifecycle.CANDIDATE,
                KeyLevelLifecycle.CONFIRMED,
                KeyLevelLifecycle.ACTIVE,
            }
            and self.test_count != 0
        ):
            raise ValueError("untested lifecycle states require test_count zero")
        if self.lifecycle is KeyLevelLifecycle.CANDIDATE and (
            self.authority_status is not KeyLevelAuthorityStatus.CANDIDATE_ONLY or self.activation_event is not None
        ):
            raise ValueError("candidate level must remain candidate-only authority")
        if self.lifecycle is KeyLevelLifecycle.CONFIRMED and (
            self.authority_status is not KeyLevelAuthorityStatus.FORMALLY_CONFIRMED or self.activation_event is not None
        ):
            raise ValueError("confirmed level requires formal authority without activation")
        canonical_lifecycles = {
            KeyLevelLifecycle.ACTIVE,
            KeyLevelLifecycle.TESTED,
            KeyLevelLifecycle.HOLDING,
            KeyLevelLifecycle.BROKEN,
            KeyLevelLifecycle.RECLAIMED,
        }
        if self.lifecycle in canonical_lifecycles and (
            self.authority_status is not KeyLevelAuthorityStatus.CANONICAL_XAUUSD_VALIDATED
            or not _is_canonical_activation(self.spec, self.activation_event)
        ):
            raise ValueError("live lifecycle requires canonical XAUUSD activation lineage")
        if self.activation_event is not None and self.activation_event.evidence.as_of > self.as_of:
            raise ValueError("activation event cannot occur after lifecycle state")
        if self.lifecycle is KeyLevelLifecycle.RETIRED:
            canonical_authority = self.authority_status is KeyLevelAuthorityStatus.CANONICAL_XAUUSD_VALIDATED
            if canonical_authority != (self.activation_event is not None):
                raise ValueError("retired level must preserve its prior activation lineage")
            if self.activation_event is not None and not _is_canonical_activation(
                self.spec,
                self.activation_event,
            ):
                raise ValueError("retired level activation lineage must remain canonical")
        if self.previous_state_id is not None and not any(
            ref.source == "key_level_state" and ref.reference == self.previous_state_id for ref in self.source_refs
        ):
            raise ValueError("previous key level state must be present in source_refs")
        if not any(ref.source == "key_level_event" and ref.reference == self.last_event_id for ref in self.source_refs):
            raise ValueError("last key level event must be present in source_refs")
        return self


class KeyLevelReadModel(KeyLevelReadModelInput):
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_id: str = Field(pattern=r"^key_level_read_model\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "KeyLevelReadModel":
        digest = _sha256(canonical_key_level_state_json(self))
        if self.payload_hash != digest or self.state_id != f"key_level_read_model.v1:{digest}":
            raise ValueError("key level state identity does not match its canonical payload")
        return self


class KeyLevelLifecycleDecisionInput(_FrozenContract):
    from_state_id: str | None = Field(
        default=None,
        pattern=r"^key_level_read_model\.v1:[0-9a-f]{64}$",
    )
    to_state_id: str | None = Field(
        default=None,
        pattern=r"^key_level_read_model\.v1:[0-9a-f]{64}$",
    )
    from_lifecycle: KeyLevelLifecycle | None = None
    to_lifecycle: KeyLevelLifecycle | None = None
    action: KeyLevelTransitionAction
    transition_allowed: bool
    advance: bool
    from_strategy_eligible: bool
    to_strategy_eligible: bool
    event: KeyLevelEvent
    triggered_rule: KeyLevelRuleCode
    reasons: tuple[str, ...] = Field(min_length=1)
    policy_version: Literal["key_level_lifecycle_policy.v1"] = "key_level_lifecycle_policy.v1"

    @field_validator("reasons")
    @classmethod
    def _validate_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values) or len(set(values)) != len(values):
            raise ValueError("decision reasons must be unique and non-empty")
        return values

    @model_validator(mode="after")
    def _validate_decision(self) -> "KeyLevelLifecycleDecisionInput":
        if (self.from_state_id is None) != (self.from_lifecycle is None):
            raise ValueError("from state id and lifecycle must both be present or absent")
        if (self.to_state_id is None) != (self.to_lifecycle is None):
            raise ValueError("to state id and lifecycle must both be present or absent")
        same_state = self.from_state_id == self.to_state_id
        if self.advance == same_state:
            raise ValueError("advance must be true exactly when state identity changes")
        if self.advance and (not self.transition_allowed or self.to_state_id is None):
            raise ValueError("advancing lifecycle decision must be allowed and have a state")
        if not self.advance and (
            self.from_lifecycle != self.to_lifecycle or self.from_strategy_eligible != self.to_strategy_eligible
        ):
            raise ValueError("non-advancing lifecycle decision must preserve state semantics")
        if self.event.event_type is KeyLevelEventType.NO_OP and (
            self.action is not KeyLevelTransitionAction.MAINTAIN or self.advance
        ):
            raise ValueError("no_op key level event must maintain without advance")
        return self


class KeyLevelLifecycleDecision(KeyLevelLifecycleDecisionInput):
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "KeyLevelLifecycleDecision":
        digest = _sha256(canonical_key_level_decision_json(self))
        if self.decision_hash != digest:
            raise ValueError("key level decision hash does not match its canonical payload")
        return self


def key_level_strategy_eligible(
    *,
    spec: KeyLevelSpec,
    lifecycle: KeyLevelLifecycle,
    authority_status: KeyLevelAuthorityStatus,
    activation_event: KeyLevelEvent | None,
    quality_status: QualityStatus,
    as_of: datetime,
) -> bool:
    normalized_as_of = _aware_utc(as_of, field_name="eligibility as_of")
    return (
        lifecycle in {KeyLevelLifecycle.ACTIVE, KeyLevelLifecycle.HOLDING}
        and authority_status is KeyLevelAuthorityStatus.CANONICAL_XAUUSD_VALIDATED
        and _is_canonical_activation(spec, activation_event)
        and quality_status == "accepted"
        and spec.role in STRATEGY_KEY_LEVEL_ROLES
        and spec.effective_from <= normalized_as_of < spec.expires_at
    )


def key_level_strategy_eligible_at(
    state: KeyLevelReadModel,
    *,
    decision_as_of: datetime,
    current_quality_status: QualityStatus,
) -> bool:
    """Re-evaluate eligibility at consumption time instead of trusting stale state."""

    normalized_decision_as_of = _aware_utc(decision_as_of, field_name="decision as_of")
    if normalized_decision_as_of < state.as_of:
        return False
    if state.activation_event is None or state.activation_event.evidence.as_of > normalized_decision_as_of:
        return False
    return key_level_strategy_eligible(
        spec=state.spec,
        lifecycle=state.lifecycle,
        authority_status=state.authority_status,
        activation_event=state.activation_event,
        quality_status=current_quality_status,
        as_of=normalized_decision_as_of,
    )


def build_key_level_spec(payload: Mapping[str, Any] | KeyLevelSpecInput | KeyLevelSpec) -> KeyLevelSpec:
    if isinstance(payload, KeyLevelSpec):
        return payload
    value = payload if isinstance(payload, KeyLevelSpecInput) else KeyLevelSpecInput.model_validate(payload)
    digest = _sha256(canonical_key_level_spec_json(value))
    return KeyLevelSpec(
        **value.model_dump(),
        definition_hash=digest,
        level_id=f"key_level.v1:{digest}",
    )


def _build_key_level_qualification_receipt(
    payload: KeyLevelQualificationReceiptInput | KeyLevelQualificationReceipt,
) -> KeyLevelQualificationReceipt:
    if isinstance(payload, KeyLevelQualificationReceipt):
        return payload
    value = payload
    normalized = value.model_copy(
        update={
            "qualified_snapshot_ids": tuple(sorted(value.qualified_snapshot_ids)),
            "qualified_factors": tuple(sorted(value.qualified_factors, key=lambda item: item.value)),
            "source_refs": _normalized_source_refs(value.source_refs),
        }
    )
    digest = _sha256(canonical_key_level_qualification_json(normalized))
    return KeyLevelQualificationReceipt(
        **normalized.model_dump(),
        receipt_hash=digest,
        receipt_id=f"key_level_qualification.v1:{digest}",
    )


def build_key_level_event(payload: Mapping[str, Any] | KeyLevelEventInput | KeyLevelEvent) -> KeyLevelEvent:
    if isinstance(payload, KeyLevelEvent):
        return payload
    value = payload if isinstance(payload, KeyLevelEventInput) else KeyLevelEventInput.model_validate(payload)
    evidence = value.evidence.model_copy(
        update={
            "factors": tuple(sorted(value.evidence.factors, key=lambda item: item.value)),
            "source_refs": _normalized_source_refs(value.evidence.source_refs),
        }
    )
    normalized = value.model_copy(update={"evidence": evidence})
    digest = _sha256(canonical_key_level_event_json(normalized))
    return KeyLevelEvent(
        **normalized.model_dump(),
        event_hash=digest,
        event_id=f"key_level_event.v1:{digest}",
    )


def _build_key_level_read_model(
    payload: Mapping[str, Any] | KeyLevelReadModelInput | KeyLevelReadModel,
) -> KeyLevelReadModel:
    if isinstance(payload, KeyLevelReadModel):
        return payload
    value = payload if isinstance(payload, KeyLevelReadModelInput) else KeyLevelReadModelInput.model_validate(payload)
    normalized = value.model_copy(update={"source_refs": _normalized_source_refs(value.source_refs)})
    digest = _sha256(canonical_key_level_state_json(normalized))
    return KeyLevelReadModel(
        **normalized.model_dump(),
        payload_hash=digest,
        state_id=f"key_level_read_model.v1:{digest}",
    )


def build_key_level_lifecycle_decision(
    payload: Mapping[str, Any] | KeyLevelLifecycleDecisionInput | KeyLevelLifecycleDecision,
) -> KeyLevelLifecycleDecision:
    if isinstance(payload, KeyLevelLifecycleDecision):
        return payload
    value = (
        payload
        if isinstance(payload, KeyLevelLifecycleDecisionInput)
        else KeyLevelLifecycleDecisionInput.model_validate(payload)
    )
    digest = _sha256(canonical_key_level_decision_json(value))
    return KeyLevelLifecycleDecision(**value.model_dump(), decision_hash=digest)


def canonical_key_level_spec_json(value: KeyLevelSpecInput | KeyLevelSpec) -> str:
    payload = value.model_dump(mode="json", exclude={"definition_hash", "level_id"})
    return _canonical_json(payload)


def canonical_key_level_qualification_json(
    value: KeyLevelQualificationReceiptInput | KeyLevelQualificationReceipt,
) -> str:
    payload = value.model_dump(mode="json", exclude={"receipt_hash", "receipt_id"})
    payload["qualified_snapshot_ids"] = sorted(value.qualified_snapshot_ids)
    payload["qualified_factors"] = sorted(item.value for item in value.qualified_factors)
    payload["source_refs"] = _canonical_source_refs(value.source_refs)
    return _canonical_json(payload)


def canonical_key_level_event_json(value: KeyLevelEventInput | KeyLevelEvent) -> str:
    payload = value.model_dump(mode="json", exclude={"event_hash", "event_id"})
    payload["evidence"]["factors"] = sorted(item.value for item in value.evidence.factors)
    payload["evidence"]["source_refs"] = _canonical_source_refs(value.evidence.source_refs)
    return _canonical_json(payload)


def canonical_key_level_state_json(value: KeyLevelReadModelInput | KeyLevelReadModel) -> str:
    payload = value.model_dump(mode="json", exclude={"payload_hash", "state_id"})
    payload["source_refs"] = _canonical_source_refs(value.source_refs)
    return _canonical_json(payload)


def canonical_key_level_decision_json(
    value: KeyLevelLifecycleDecisionInput | KeyLevelLifecycleDecision,
) -> str:
    return _canonical_json(value.model_dump(mode="json", exclude={"decision_hash"}))


def _require_source_refs(source_refs: tuple[SourceReference, ...], *, as_of: datetime) -> None:
    identities: set[tuple[str, str, datetime]] = set()
    for source_ref in source_refs:
        retrieved_at = _aware_utc(source_ref.retrieved_at, field_name="source reference retrieved_at")
        if retrieved_at > as_of:
            raise ValueError("source reference retrieved_at cannot be after as_of")
        identity = (source_ref.source, source_ref.reference, retrieved_at)
        if identity in identities:
            raise ValueError("source_refs must be unique")
        identities.add(identity)


def _is_canonical_activation(
    spec: KeyLevelSpec,
    event: KeyLevelEvent | None,
) -> bool:
    if event is None:
        return False
    receipt = event.evidence.qualification_receipt
    return (
        event.event_type is KeyLevelEventType.ACTIVATE
        and event.spec.level_id == spec.level_id
        and receipt.source_role is KeyLevelSourceRole.OFFICIAL_MARKET
        and receipt.qualification_class is KeyLevelQualificationClass.CANONICAL_MARKET
        and receipt.subject_level_id == spec.level_id
        and event.evidence.quality_status == "accepted"
        and event.evidence.freshness_status == "fresh"
        and event.evidence.alignment_status == "aligned"
        and {
            KeyLevelEvidenceFactor.OFFICIAL_CLOSE,
            KeyLevelEvidenceFactor.PRICE_STRUCTURE,
        }.issubset(set(event.evidence.factors))
        and event.evidence.price_fact is not None
        and event.evidence.price_fact.window_complete
        and event.evidence.price_fact.rule_code == "price_structure"
        and spec.effective_from <= event.evidence.as_of < spec.expires_at
    )


def _normalized_source_refs(source_refs: tuple[SourceReference, ...]) -> tuple[SourceReference, ...]:
    return tuple(
        SourceReference(
            source=source_ref.source,
            reference=source_ref.reference,
            retrieved_at=source_ref.retrieved_at.astimezone(UTC),
        )
        for source_ref in sorted(
            source_refs,
            key=lambda item: (item.source, item.reference, item.retrieved_at.astimezone(UTC)),
        )
    )


def _canonical_source_refs(source_refs: tuple[SourceReference, ...]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in _normalized_source_refs(source_refs)]


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
