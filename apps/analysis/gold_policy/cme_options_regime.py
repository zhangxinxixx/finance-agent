"""Immutable CME options-regime contract and pure legacy-output adapter.

The adapter consumes only structured fields from ``options_analysis.json``.
It deliberately does not inspect narrative conclusions and does not infer a
direction from the sign of net GEX.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from apps.analysis.gold_policy.schemas import (
    AlignmentStatus,
    FreshnessStatus,
    FrozenContract,
    QualityStatus,
    SourceReference,
)


class CMEOptionsRegime(StrEnum):
    """Regime values compatible with the legacy strategy-options contract."""

    NORMAL = "normal"
    PINNING = "pinning"
    HIGH_GAMMA = "high_gamma"
    STRESS = "stress"
    UNAVAILABLE = "unavailable"


CMEDirectionalBias = Literal["bullish", "bearish", "neutral", "mixed", "unavailable"]
SettlementStatus = Literal["FINAL", "PRELIM", "UNKNOWN"]


class CMEOptionsInputSnapshotId(FrozenContract):
    name: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)


class CMEOptionsExpiryScope(FrozenContract):
    expiry: str = Field(min_length=1)
    expiry_date: date
    dte: int = Field(ge=0)
    expiry_source: str = Field(min_length=1)
    expiry_confidence: str = Field(min_length=1)


class CMEOptionsLevel(FrozenContract):
    strike: float = Field(gt=0.0)
    expiry: str | None = None
    wall_score: float | None = None

    @field_validator("strike", "wall_score")
    @classmethod
    def _finite_number(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("options levels must be finite")
        return value


class CMEOptionsSkew(FrozenContract):
    expiry: str = Field(min_length=1)
    atm_iv: float | None = None
    call_25d_iv: float | None = None
    put_25d_iv: float | None = None
    skew_25d: float | None = None
    call_10d_iv: float | None = None
    put_10d_iv: float | None = None
    tail_skew_10d: float | None = None

    @field_validator(
        "atm_iv",
        "call_25d_iv",
        "put_25d_iv",
        "skew_25d",
        "call_10d_iv",
        "put_10d_iv",
        "tail_skew_10d",
    )
    @classmethod
    def _finite_metric(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("skew metrics must be finite")
        return value

    @model_validator(mode="after")
    def _require_a_structured_metric(self) -> "CMEOptionsSkew":
        values = self.model_dump(exclude={"expiry"}).values()
        if all(value is None for value in values):
            raise ValueError("skew requires at least one structured metric")
        return self


class CMEOptionsModelDisclosure(FrozenContract):
    model: str | None
    used_real_gex: bool | None
    forward_sources: tuple[str, ...]
    proxy_rows: int | None = Field(default=None, ge=0)
    proxy_gex_share: float | None = Field(default=None, ge=0.0, le=1.0)
    proxy_included_in_gamma_flip: bool | None = None


class CMEOptionsRegimeSnapshotInput(FrozenContract):
    """Hashable formal input before deterministic identity is attached."""

    schema_version: Literal["cme_options_regime.v1"] = "cme_options_regime.v1"
    policy_version: Literal["cme_options_regime_policy.v1"] = "cme_options_regime_policy.v1"
    source_snapshot_id: str = Field(pattern=r"^feature_snapshot\.v[12]:[0-9a-f]{64}$")
    options_snapshot_id: str | None = None
    trade_date: date | None
    as_of: datetime
    generated_at: datetime | None
    underlying_price: float | None = Field(gt=0.0)
    underlying_price_source: str | None
    underlying_as_of: datetime | None
    expiry_scope: tuple[CMEOptionsExpiryScope, ...]
    net_gex: float | None
    gamma_flip: float | None = Field(gt=0.0)
    pin: CMEOptionsLevel | None
    call_wall: CMEOptionsLevel | None
    put_wall: CMEOptionsLevel | None
    skew: tuple[CMEOptionsSkew, ...]
    regime: CMEOptionsRegime
    directional_bias: CMEDirectionalBias
    settlement_status: SettlementStatus
    freshness_status: FreshnessStatus
    quality_status: QualityStatus
    alignment_status: AlignmentStatus
    input_snapshot_ids: tuple[CMEOptionsInputSnapshotId, ...]
    source_refs: tuple[SourceReference, ...]
    model_disclosure: CMEOptionsModelDisclosure
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @field_validator("as_of", "generated_at", "underlying_as_of")
    @classmethod
    def _normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CME options timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("underlying_price", "net_gex", "gamma_flip")
    @classmethod
    def _finite_value(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("CME options values must be finite")
        return value

    @model_validator(mode="after")
    def _validate_semantics(self) -> "CMEOptionsRegimeSnapshotInput":
        if self.generated_at is not None and self.generated_at > self.as_of:
            raise ValueError("options output generated_at cannot be after as_of")
        if self.underlying_as_of is not None and self.underlying_as_of > self.as_of:
            raise ValueError("underlying timestamp cannot be after as_of")
        for ref in self.source_refs:
            if ref.retrieved_at.tzinfo is None or ref.retrieved_at.utcoffset() is None:
                raise ValueError("source reference timestamps must be timezone-aware")
            if ref.retrieved_at.astimezone(UTC) > self.as_of:
                raise ValueError("source reference timestamps cannot be after as_of")
        if len({item.name for item in self.input_snapshot_ids}) != len(self.input_snapshot_ids):
            raise ValueError("input snapshot lineage names must be unique")
        if len({item.expiry for item in self.expiry_scope}) != len(self.expiry_scope):
            raise ValueError("expiry scope entries must be unique")
        if len({item.expiry for item in self.skew}) != len(self.skew):
            raise ValueError("skew entries must be unique")
        if self.trade_date is not None:
            for item in self.expiry_scope:
                if item.dte != (item.expiry_date - self.trade_date).days:
                    raise ValueError("expiry DTE must match trade_date and expiry_date")
        if self.regime is CMEOptionsRegime.UNAVAILABLE:
            if self.directional_bias != "unavailable" or self.quality_status == "accepted":
                raise ValueError("unavailable regime cannot carry an accepted direction")
        if self.quality_status == "accepted":
            if (
                self.settlement_status != "FINAL"
                or self.freshness_status != "fresh"
                or self.alignment_status != "aligned"
                or self.directional_bias == "unavailable"
                or not self.source_refs
                or not self.input_snapshot_ids
            ):
                raise ValueError("accepted options regime requires FINAL aligned fresh lineage")
        return self


class CMEOptionsRegimeSnapshot(CMEOptionsRegimeSnapshotInput):
    """Immutable content-addressed CME options-regime snapshot."""

    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = Field(pattern=r"^cme_options_regime\.v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_identity(self) -> "CMEOptionsRegimeSnapshot":
        digest = hashlib.sha256(canonical_cme_options_regime_json(self).encode("utf-8")).hexdigest()
        if self.payload_hash != digest or self.snapshot_id != f"cme_options_regime.v1:{digest}":
            raise ValueError("CME options regime identity does not match canonical payload")
        return self


def canonical_cme_options_regime_json(
    value: CMEOptionsRegimeSnapshotInput | CMEOptionsRegimeSnapshot,
) -> str:
    payload = value.model_dump(mode="json", exclude={"payload_hash", "snapshot_id"})
    payload["expiry_scope"] = sorted(payload["expiry_scope"], key=lambda item: item["expiry"])
    payload["skew"] = sorted(payload["skew"], key=lambda item: item["expiry"])
    payload["input_snapshot_ids"] = sorted(
        payload["input_snapshot_ids"], key=lambda item: (item["name"], item["snapshot_id"])
    )
    payload["source_refs"] = sorted(
        payload["source_refs"],
        key=lambda item: (item["source"], item["reference"], item["retrieved_at"]),
    )
    payload["reason_codes"] = sorted(set(payload["reason_codes"]))
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_cme_options_regime_snapshot(
    options_analysis: Mapping[str, Any] | CMEOptionsRegimeSnapshotInput | CMEOptionsRegimeSnapshot,
    *,
    source_snapshot_id: str | None = None,
    as_of: datetime | None = None,
) -> CMEOptionsRegimeSnapshot:
    """Build a deterministic formal snapshot without I/O or input mutation.

    ``source_snapshot_id`` is the owning Gold FeatureSnapshot identity.  The
    CME artifact's own identities remain in ``options_snapshot_id`` and
    ``input_snapshot_ids``.
    """

    if isinstance(options_analysis, CMEOptionsRegimeSnapshot):
        expected = hashlib.sha256(canonical_cme_options_regime_json(options_analysis).encode("utf-8")).hexdigest()
        if (
            options_analysis.payload_hash != expected
            or options_analysis.snapshot_id != f"cme_options_regime.v1:{expected}"
        ):
            raise ValueError("CME options regime snapshot identity is invalid")
        return options_analysis
    if isinstance(options_analysis, CMEOptionsRegimeSnapshotInput):
        value = options_analysis
    else:
        if source_snapshot_id is None or as_of is None:
            raise ValueError("adapter requires source_snapshot_id and as_of")
        value = _adapt_options_analysis(
            options_analysis,
            source_snapshot_id=source_snapshot_id,
            as_of=as_of,
        )
    normalized = value.model_copy(
        update={
            "expiry_scope": tuple(sorted(value.expiry_scope, key=lambda item: item.expiry)),
            "skew": tuple(sorted(value.skew, key=lambda item: item.expiry)),
            "input_snapshot_ids": tuple(
                sorted(value.input_snapshot_ids, key=lambda item: (item.name, item.snapshot_id))
            ),
            "source_refs": _normalized_source_refs(value.source_refs),
            "reason_codes": tuple(sorted(set(value.reason_codes))),
        }
    )
    digest = hashlib.sha256(canonical_cme_options_regime_json(normalized).encode("utf-8")).hexdigest()
    return CMEOptionsRegimeSnapshot(
        **normalized.model_dump(),
        payload_hash=digest,
        snapshot_id=f"cme_options_regime.v1:{digest}",
    )


def adapt_options_analysis_to_cme_options_regime(
    options_analysis: Mapping[str, Any],
    *,
    source_snapshot_id: str,
    as_of: datetime,
) -> CMEOptionsRegimeSnapshot:
    """Explicit adapter alias for callers crossing the legacy-output boundary."""

    return build_cme_options_regime_snapshot(
        options_analysis,
        source_snapshot_id=source_snapshot_id,
        as_of=as_of,
    )


def _adapt_options_analysis(
    payload: Mapping[str, Any], *, source_snapshot_id: str, as_of: datetime
) -> CMEOptionsRegimeSnapshotInput:
    normalized_as_of = _aware_utc(as_of)
    reasons: set[str] = set()
    trade_date = _parse_date(payload.get("trade_date"))
    generated_at = _parse_datetime(payload.get("generated_at"))
    data_source = _mapping(payload.get("data_source"))
    parameters = _mapping(payload.get("parameters"))
    audit = _mapping(payload.get("audit"))
    normalization = _mapping(payload.get("normalization"))
    data_quality = _mapping(payload.get("data_quality"))
    quality_categories = _mapping(data_quality.get("categories"))

    time_invalid = generated_at is None or generated_at > normalized_as_of
    if time_invalid:
        reasons.add("OPTIONS_GENERATED_AT_INVALID")
        generated_at = None

    settlement_status = _settlement_status(data_source.get("status"))
    if settlement_status != "FINAL":
        reasons.add("FINAL_SETTLEMENT_REQUIRED_FOR_DIRECTION")

    underlying_price = _number(parameters.get("report_p0"))
    if underlying_price is None:
        underlying_price = _number(parameters.get("p0"))
    underlying_source = _text(parameters.get("report_p0_source") or parameters.get("p0_source"))
    underlying_as_of = _parse_datetime(parameters.get("report_p0_timestamp") or parameters.get("p0_timestamp"))
    if underlying_price is None:
        reasons.add("UNDERLYING_PRICE_MISSING")
    if underlying_source is None or underlying_source.lower() == "not_provided":
        reasons.add("UNDERLYING_SOURCE_MISSING")
    if underlying_as_of is None:
        reasons.add("UNDERLYING_TIMESTAMP_MISSING")
    elif underlying_as_of > normalized_as_of:
        reasons.add("UNDERLYING_TIMESTAMP_AFTER_AS_OF")
        underlying_as_of = None

    expiries, expiry_unknown, expiry_invalid = _expiry_scope(data_source, audit, trade_date)
    if not expiries:
        reasons.add("EXPIRY_SCOPE_MISSING")
    if expiry_unknown:
        reasons.add("EXPIRY_ALIGNMENT_UNVERIFIED")
    if expiry_invalid:
        reasons.add("EXPIRY_SCOPE_INVALID")

    net_gex, gex_inconsistent = _net_gex(payload)
    if net_gex is None:
        reasons.add("NET_GEX_MISSING")
    if gex_inconsistent:
        reasons.add("NET_GEX_SCOPE_INCONSISTENT")
    gamma_flip, gamma_scope_valid = _gamma_flip(payload)
    if gamma_flip is None:
        reasons.add("GAMMA_FLIP_MISSING")
    if not gamma_scope_valid:
        reasons.add("GAMMA_FLIP_SCOPE_INVALID")

    pin = _pin(payload)
    call_wall = _wall(payload, kind="call")
    put_wall = _wall(payload, kind="put")
    wall_invalid = False
    if call_wall is None or put_wall is None:
        reasons.add("TWO_SIDED_WALL_STRUCTURE_MISSING")
    elif underlying_price is not None and (call_wall.strike <= underlying_price or put_wall.strike >= underlying_price):
        reasons.add("WALL_STRUCTURE_MISALIGNED")
        wall_invalid = True

    skew = _skew(payload)
    if not skew:
        reasons.add("STRUCTURED_SKEW_MISSING")
    skew_scope_invalid = bool(skew) and {item.expiry for item in skew} != {item.expiry for item in expiries}
    if skew_scope_invalid:
        reasons.add("SKEW_EXPIRY_SCOPE_MISMATCH")

    disclosure = _model_disclosure(parameters, audit)
    disclosure_invalid = (
        (disclosure.model or "").lower() != "black-76"
        or disclosure.used_real_gex is not True
        or disclosure.proxy_rows is None
        or disclosure.proxy_gex_share is None
        or disclosure.proxy_included_in_gamma_flip is not False
        or not disclosure.forward_sources
    )
    if disclosure_invalid:
        reasons.add("MODEL_PROXY_DISCLOSURE_INCOMPLETE")

    options_snapshot_id = _text(payload.get("snapshot_id"))
    input_ids = _input_snapshot_ids(data_source, options_snapshot_id)
    lineage_missing = options_snapshot_id is None or not _mapping(data_source.get("input_snapshot_ids"))
    if lineage_missing:
        reasons.add("CME_INPUT_LINEAGE_MISSING")

    source_refs = _source_refs(
        data_source=data_source,
        options_snapshot_id=options_snapshot_id,
        retrieved_at=generated_at,
    )
    if not source_refs:
        reasons.add("SOURCE_REFS_MISSING")

    quality_metadata_missing = not normalization or not quality_categories
    if quality_metadata_missing:
        reasons.add("OPTIONS_QUALITY_METADATA_MISSING")
    quality_warnings = data_quality.get("warnings")
    quality_degraded = (
        _integer(normalization.get("rows_missing_settlement")) not in {0}
        or not isinstance(quality_warnings, list)
        or bool(quality_warnings)
    )
    if quality_degraded:
        reasons.add("OPTIONS_QUALITY_DEGRADED")

    freshness = _freshness(trade_date, normalized_as_of)
    if freshness != "fresh":
        reasons.add("CME_DATA_NOT_FRESH")

    report_date = _parse_date(data_source.get("report_date"))
    source_scope_invalid = (
        payload.get("version") != "1.0"
        or data_source.get("product") != "OG"
        or report_date is None
        or report_date != trade_date
        or trade_date is None
        or trade_date > normalized_as_of.date()
    )
    if source_scope_invalid:
        reasons.add("CME_OUTPUT_SCOPE_INVALID")

    misaligned = any(
        (
            time_invalid,
            expiry_invalid,
            gex_inconsistent,
            wall_invalid,
            skew_scope_invalid,
            source_scope_invalid,
        )
    )
    unknown_alignment = any(
        (
            expiry_unknown,
            underlying_as_of is None,
        )
    )
    alignment: AlignmentStatus = "misaligned" if misaligned else "unknown" if unknown_alignment else "aligned"

    structural_missing = any(
        (
            underlying_price is None,
            underlying_source is None or underlying_source.lower() == "not_provided",
            not expiries,
            net_gex is None,
            gamma_flip is None,
            call_wall is None,
            put_wall is None,
            not skew,
            disclosure_invalid,
            quality_metadata_missing,
        )
    )
    if structural_missing or lineage_missing or not source_refs or misaligned:
        quality: QualityStatus = "blocked"
    elif settlement_status != "FINAL" or freshness != "fresh" or alignment != "aligned" or quality_degraded:
        quality = "observe"
    else:
        quality = "accepted"

    directional_bias: CMEDirectionalBias = (
        "neutral" if quality == "accepted" and call_wall is not None and put_wall is not None else "unavailable"
    )
    regime = _regime(
        underlying_price=underlying_price,
        net_gex=net_gex,
        gamma_flip=gamma_flip,
        pin=pin,
        complete=not structural_missing,
    )
    if quality == "blocked":
        regime = CMEOptionsRegime.UNAVAILABLE
        directional_bias = "unavailable"
    elif directional_bias == "unavailable":
        reasons.add("DIRECTION_WITHHELD")

    if not reasons:
        reasons.add("FINAL_TWO_SIDED_OPTIONS_STRUCTURE_ACCEPTED")

    return CMEOptionsRegimeSnapshotInput(
        source_snapshot_id=source_snapshot_id,
        options_snapshot_id=options_snapshot_id,
        trade_date=trade_date,
        as_of=normalized_as_of,
        generated_at=generated_at,
        underlying_price=underlying_price,
        underlying_price_source=underlying_source,
        underlying_as_of=underlying_as_of,
        expiry_scope=expiries,
        net_gex=net_gex,
        gamma_flip=gamma_flip,
        pin=pin,
        call_wall=call_wall,
        put_wall=put_wall,
        skew=skew,
        regime=regime,
        directional_bias=directional_bias,
        settlement_status=settlement_status,
        freshness_status=freshness,
        quality_status=quality,
        alignment_status=alignment,
        input_snapshot_ids=input_ids,
        source_refs=source_refs,
        model_disclosure=disclosure,
        reason_codes=tuple(reasons),
    )


def _expiry_scope(
    data_source: Mapping[str, Any], audit: Mapping[str, Any], trade_date: date | None
) -> tuple[tuple[CMEOptionsExpiryScope, ...], bool, bool]:
    names = data_source.get("expiries")
    if not isinstance(names, Sequence) or isinstance(names, (str, bytes)) or trade_date is None:
        return (), False, True
    black76 = _mapping(audit.get("black76_audit"))
    result: list[CMEOptionsExpiryScope] = []
    unknown = False
    invalid = False
    for raw_name in names:
        name = _text(raw_name)
        details = _mapping(black76.get(name)) if name is not None else {}
        expiry_date = _parse_date(details.get("expiry_date"))
        if name is None or expiry_date is None or expiry_date < trade_date:
            invalid = True
            continue
        source = _text(details.get("expiry_source")) or "unknown"
        confidence = _text(details.get("expiry_confidence")) or "unknown"
        if "estimated" in source.lower() or confidence.lower() not in {"high", "confirmed"}:
            unknown = True
        result.append(
            CMEOptionsExpiryScope(
                expiry=name,
                expiry_date=expiry_date,
                dte=(expiry_date - trade_date).days,
                expiry_source=source,
                expiry_confidence=confidence,
            )
        )
    return tuple(result), unknown, invalid


def _net_gex(payload: Mapping[str, Any]) -> tuple[float | None, bool]:
    gex = _mapping(payload.get("gex"))
    aggregate = _mapping(gex.get("netgex_aggregate"))
    audit_gex = _mapping(_mapping(payload.get("audit")).get("gex_audit"))
    direct = _number(aggregate.get("net_gex"))
    audited = _number(audit_gex.get("net_gex"))
    by_expiry = _mapping(gex.get("by_expiry"))
    values = [
        value
        for item in by_expiry.values()
        if isinstance(item, Mapping)
        for value in [_number(_mapping(item.get("summary")).get("net_gex"))]
        if value is not None
    ]
    summed = sum(values) if values and len(values) == len(by_expiry) else None
    chosen = audited if audited is not None else direct if direct is not None else summed
    candidates = [value for value in (audited, direct, summed) if value is not None]
    inconsistent = any(
        not math.isclose(value, chosen, rel_tol=1e-6, abs_tol=0.01) for value in candidates if chosen is not None
    )
    return chosen, inconsistent


def _gamma_flip(payload: Mapping[str, Any]) -> tuple[float | None, bool]:
    aggregate = _mapping(_mapping(_mapping(payload.get("gex")).get("netgex_aggregate")).get("gamma_zero"))
    price = _number(aggregate.get("price"))
    scope = _text(aggregate.get("scope"))
    method = (_text(aggregate.get("method")) or "").lower()
    return price, scope == "aggregate_across_expiries" and method not in {"", "unavailable"}


def _wall(payload: Mapping[str, Any], *, kind: Literal["call", "put"]) -> CMEOptionsLevel | None:
    support_resistance = _mapping(payload.get("support_resistance"))
    key = "resistance" if kind == "call" else "support"
    entries = support_resistance.get(key)
    if isinstance(entries, Sequence) and not isinstance(entries, (str, bytes)):
        for entry in entries:
            level = _level(entry)
            if level is not None:
                return level
    expected_side = "call" if kind == "call" else "put"
    candidates: list[tuple[float, CMEOptionsLevel]] = []
    wall_scores = payload.get("wall_scores")
    if isinstance(wall_scores, Sequence) and not isinstance(wall_scores, (str, bytes)):
        for entry in wall_scores:
            if not isinstance(entry, Mapping):
                continue
            side = str(entry.get("dominant_side") or entry.get("side") or "").lower()
            if expected_side not in side:
                continue
            level = _level(entry)
            if level is not None:
                candidates.append((level.wall_score or 0.0, level))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _pin(payload: Mapping[str, Any]) -> CMEOptionsLevel | None:
    candidates: list[tuple[float, CMEOptionsLevel]] = []
    wall_scores = payload.get("wall_scores")
    if isinstance(wall_scores, Sequence) and not isinstance(wall_scores, (str, bytes)):
        for entry in wall_scores:
            if not isinstance(entry, Mapping) or "pin" not in str(entry.get("wall_type") or "").lower():
                continue
            level = _level(entry)
            if level is not None:
                candidates.append((level.wall_score or 0.0, level))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _level(value: Any) -> CMEOptionsLevel | None:
    if not isinstance(value, Mapping):
        return None
    strike = _number(value.get("strike"))
    if strike is None:
        return None
    return CMEOptionsLevel(
        strike=strike,
        expiry=_text(value.get("expiry")),
        wall_score=_number(value.get("wall_score")),
    )


def _skew(payload: Mapping[str, Any]) -> tuple[CMEOptionsSkew, ...]:
    by_expiry = _mapping(_mapping(payload.get("gex")).get("by_expiry"))
    result: list[CMEOptionsSkew] = []
    fields = (
        "atm_iv",
        "call_25d_iv",
        "put_25d_iv",
        "skew_25d",
        "call_10d_iv",
        "put_10d_iv",
        "tail_skew_10d",
    )
    for raw_expiry, raw_value in by_expiry.items():
        expiry = _text(raw_expiry)
        value = _mapping(raw_value)
        metrics = _mapping(value.get("iv_skew"))
        normalized = {field: _number(metrics.get(field)) for field in fields}
        if expiry is not None and any(item is not None for item in normalized.values()):
            result.append(CMEOptionsSkew(expiry=expiry, **normalized))
    return tuple(result)


def _model_disclosure(parameters: Mapping[str, Any], audit: Mapping[str, Any]) -> CMEOptionsModelDisclosure:
    data_audit = _mapping(audit.get("data_audit"))
    gex_audit = _mapping(audit.get("gex_audit"))
    forward = _mapping(parameters.get("model_f") or parameters.get("forward_by_expiry"))
    sources = {
        source
        for value in forward.values()
        if isinstance(value, Mapping)
        for source in [_text(value.get("f_source"))]
        if source is not None
    }
    fallback_source = _text(parameters.get("f_source"))
    if fallback_source is not None:
        sources.add(fallback_source)
    return CMEOptionsModelDisclosure(
        model=_text(parameters.get("model")),
        used_real_gex=parameters.get("used_real_gex") if isinstance(parameters.get("used_real_gex"), bool) else None,
        forward_sources=tuple(sorted(sources)),
        proxy_rows=_integer(data_audit.get("proxy_rows")),
        proxy_gex_share=_ratio(data_audit.get("proxy_gex_share")),
        proxy_included_in_gamma_flip=gex_audit.get("proxy_included_in_zero")
        if isinstance(gex_audit.get("proxy_included_in_zero"), bool)
        else None,
    )


def _input_snapshot_ids(
    data_source: Mapping[str, Any], options_snapshot_id: str | None
) -> tuple[CMEOptionsInputSnapshotId, ...]:
    raw = _mapping(data_source.get("input_snapshot_ids"))
    values = [
        CMEOptionsInputSnapshotId(name=str(name), snapshot_id=snapshot_id)
        for name, raw_id in raw.items()
        for snapshot_id in [_text(raw_id)]
        if str(name).strip() and snapshot_id is not None
    ]
    if options_snapshot_id is not None and not any(item.name == "options_output" for item in values):
        values.append(CMEOptionsInputSnapshotId(name="options_output", snapshot_id=options_snapshot_id))
    return tuple(values)


def _source_refs(
    *,
    data_source: Mapping[str, Any],
    options_snapshot_id: str | None,
    retrieved_at: datetime | None,
) -> tuple[SourceReference, ...]:
    if retrieved_at is None:
        return ()
    result: list[SourceReference] = []
    source_url = _text(data_source.get("source_url"))
    if source_url is not None:
        result.append(
            SourceReference(
                source="cme_daily_bulletin",
                reference=source_url,
                retrieved_at=retrieved_at,
            )
        )
    if options_snapshot_id is not None:
        result.append(
            SourceReference(
                source="cme_options_analysis",
                reference=options_snapshot_id,
                retrieved_at=retrieved_at,
            )
        )
    return tuple(result)


def _normalized_source_refs(
    refs: tuple[SourceReference, ...],
) -> tuple[SourceReference, ...]:
    unique = {
        (ref.source, ref.reference, ref.retrieved_at.astimezone(UTC)): SourceReference(
            source=ref.source,
            reference=ref.reference,
            retrieved_at=ref.retrieved_at.astimezone(UTC),
        )
        for ref in refs
    }
    return tuple(unique[key] for key in sorted(unique, key=lambda item: (item[0], item[1], item[2])))


def _regime(
    *,
    underlying_price: float | None,
    net_gex: float | None,
    gamma_flip: float | None,
    pin: CMEOptionsLevel | None,
    complete: bool,
) -> CMEOptionsRegime:
    if not complete or underlying_price is None or net_gex is None or gamma_flip is None:
        return CMEOptionsRegime.UNAVAILABLE
    if pin is not None and abs(pin.strike - underlying_price) / underlying_price <= 0.005:
        return CMEOptionsRegime.PINNING
    if underlying_price < gamma_flip and net_gex < 0:
        return CMEOptionsRegime.STRESS
    return CMEOptionsRegime.NORMAL


def _freshness(trade_date: date | None, as_of: datetime) -> FreshnessStatus:
    if trade_date is None or trade_date > as_of.date():
        return "missing"
    return "fresh" if trade_date == as_of.date() else "stale"


def _settlement_status(value: Any) -> SettlementStatus:
    normalized = str(value or "").strip().upper()
    if normalized == "FINAL":
        return "FINAL"
    if normalized.startswith("PRELIM"):
        return "PRELIM"
    return "UNKNOWN"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _ratio(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and 0.0 <= result <= 1.0 else None


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC)
