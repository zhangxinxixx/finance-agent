"""Pure construction and canonical serialization for versioned FeatureSnapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from apps.analysis.gold_policy.schemas import (
    DataQualitySnapshot,
    DataQualitySnapshotV2,
    FeatureSnapshot,
    FeatureSnapshotInput,
    FeatureSnapshotV2,
    FeatureSnapshotV2Input,
    OfficialEventSnapshot,
    Real10YQualityDiagnostics,
    SourceReference,
    VariableObservation,
)
from apps.analysis.gold_policy.readiness_policy import evaluate_gold_readiness


FeatureSnapshotContract = FeatureSnapshot | FeatureSnapshotV2
FeatureSnapshotInputContract = FeatureSnapshotInput | FeatureSnapshotV2Input


def canonical_feature_snapshot_json(snapshot: FeatureSnapshotInputContract | FeatureSnapshotContract) -> str:
    """Return stable JSON for identity calculation; identity fields are excluded."""

    excluded = {"data_quality", "payload_hash", "snapshot_id"}
    if isinstance(snapshot, FeatureSnapshotV2):
        excluded.update(
            {
                "real10y_estimated",
                "real10y_basis_bp",
                "real10y_alignment",
                "real10y_reason_codes",
                "real10y_quality",
            }
        )
    payload = snapshot.model_dump(mode="json", exclude=excluded)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_feature_snapshot(
    payload: Mapping[str, Any] | FeatureSnapshotInputContract | FeatureSnapshotContract,
) -> FeatureSnapshotContract:
    """Build a deterministic snapshot without I/O, clocks, or mutable defaults."""

    if isinstance(payload, FeatureSnapshotV2):
        if not feature_snapshot_integrity_valid(payload):
            raise ValueError("feature_snapshot.v2 derived fields or identity are invalid")
        return payload
    if isinstance(payload, FeatureSnapshot):
        return payload
    if isinstance(payload, (FeatureSnapshotInput, FeatureSnapshotV2Input)):
        input_snapshot = payload
    elif payload.get("schema_version") == "feature_snapshot.v2":
        input_snapshot = FeatureSnapshotV2Input.model_validate(payload)
    else:
        input_snapshot = FeatureSnapshotInput.model_validate(payload)
    canonical_json = canonical_feature_snapshot_json(input_snapshot)
    payload_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    if isinstance(input_snapshot, FeatureSnapshotV2Input):
        estimated, basis_bp, real10y_alignment, reason_codes = _derive_real10y_v2(input_snapshot)
        readiness = evaluate_gold_readiness(
            input_snapshot,
            real10y_estimated=estimated,
        )
        aggregate_quality = derive_data_quality(
            input_snapshot,
            real10y_estimated=estimated,
        )
        data_quality = DataQualitySnapshotV2(
            freshness_status=aggregate_quality.freshness_status,
            completeness_status=aggregate_quality.completeness_status,
            alignment_status=aggregate_quality.alignment_status,
            analysis_readiness=readiness.analysis_readiness,
            readiness_policy_version=readiness.policy_version,
            strategy_readiness=readiness.strategy_readiness,
            options_readiness=readiness.options_readiness,
            event_attribution_readiness=readiness.event_attribution_readiness,
            missing_required_inputs=readiness.missing_required_inputs,
            missing_confirmatory_inputs=readiness.missing_confirmatory_inputs,
            prohibited_outputs=readiness.prohibited_outputs,
            reason_codes=readiness.reason_codes,
        )
        return FeatureSnapshotV2(
            **input_snapshot.model_dump(),
            real10y_estimated=estimated,
            real10y_basis_bp=basis_bp,
            real10y_alignment=real10y_alignment,
            real10y_reason_codes=reason_codes,
            real10y_quality=Real10YQualityDiagnostics(
                real10y_alignment=real10y_alignment,
                reason_codes=reason_codes,
                prohibited_conclusions=(
                    ("STRONG_REAL_YIELD_DIRECTION_CONFIRMATION",)
                    if real10y_alignment == "diverged"
                    else ()
                ),
            ),
            data_quality=data_quality,
            payload_hash=payload_hash,
            snapshot_id=f"feature_snapshot.v2:{payload_hash}",
        )
    data_quality = derive_data_quality(input_snapshot)
    return FeatureSnapshot(
        **input_snapshot.model_dump(),
        data_quality=data_quality,
        payload_hash=payload_hash,
        snapshot_id=f"feature_snapshot.v1:{payload_hash}",
    )


def feature_snapshot_integrity_valid(snapshot: FeatureSnapshotContract) -> bool:
    """Rebuild v2 derivations before a policy consumer trusts them.

    v1 remains byte-for-byte compatible.  v2 readiness and Real10Y fields are
    excluded from the canonical input hash by design, so every authority
    boundary must compare them with a fresh deterministic rebuild.
    """

    if not isinstance(snapshot, FeatureSnapshotV2):
        return True
    excluded = {
        "real10y_estimated",
        "real10y_basis_bp",
        "real10y_alignment",
        "real10y_reason_codes",
        "real10y_quality",
        "data_quality",
        "payload_hash",
        "snapshot_id",
    }
    try:
        input_snapshot = FeatureSnapshotV2Input.model_validate(
            snapshot.model_dump(mode="python", exclude=excluded)
        )
        rebuilt = build_feature_snapshot(input_snapshot)
    except (TypeError, ValueError):
        return False
    return rebuilt == snapshot


def derive_data_quality(
    snapshot: FeatureSnapshotInputContract,
    *,
    real10y_estimated: VariableObservation | None = None,
) -> DataQualitySnapshot:
    """Conservatively derive readiness from every formal input data passport."""

    inputs: tuple[VariableObservation | OfficialEventSnapshot, ...] = (
        snapshot.xauusd_spot,
        snapshot.gc_futures,
        snapshot.us02y,
        snapshot.us10y,
        snapshot.us30y,
        snapshot.t10yie,
        snapshot.real10y
        if isinstance(snapshot, FeatureSnapshotInput)
        else real10y_estimated
        if real10y_estimated is not None
        else snapshot.real10y_direct,
        snapshot.broad_dollar,
        snapshot.wti,
        snapshot.brent,
        snapshot.etf_flow,
        snapshot.cot,
        snapshot.cme_options_regime,
        snapshot.official_events,
    )
    missing_count = sum(item.freshness_status == "missing" for item in inputs)
    has_missing = missing_count > 0
    has_stale = any(item.freshness_status == "stale" for item in inputs)
    has_blocked = any(item.quality_status == "blocked" for item in inputs)
    has_observe = any(item.quality_status == "observe" for item in inputs)
    has_misaligned = any(item.alignment_status == "misaligned" for item in inputs)
    has_unknown_alignment = any(item.alignment_status == "unknown" for item in inputs)

    freshness_status = "missing" if has_missing else "stale" if has_stale else "fresh"
    completeness_status = (
        "missing" if missing_count == len(inputs) else "partial" if has_missing else "complete"
    )
    alignment_status = (
        "misaligned" if has_misaligned else "unknown" if has_unknown_alignment else "aligned"
    )
    if has_missing or has_blocked or has_misaligned:
        analysis_readiness = "blocked"
    elif has_unknown_alignment or has_stale or has_observe:
        analysis_readiness = "observe"
    else:
        analysis_readiness = "ready"
    return DataQualitySnapshot(
        freshness_status=freshness_status,
        completeness_status=completeness_status,
        alignment_status=alignment_status,
        analysis_readiness=analysis_readiness,
    )


def _derive_real10y_v2(
    snapshot: FeatureSnapshotV2Input,
) -> tuple[VariableObservation, float | None, str, tuple[str, ...]]:
    """Derive the estimated real yield and direct-series basis fail-closed.

    US10Y and T10YIE must each be accepted and aligned, and their timestamps
    must be identical. DFII10 is deliberately independent: when it is missing,
    the estimated value remains usable and the basis becomes unavailable.
    """

    us10y, t10yie, direct = snapshot.us10y, snapshot.t10yie, snapshot.real10y_direct
    estimate_reason: str | None = None
    if us10y.value is None or t10yie.value is None:
        estimate_reason = "REAL10Y_ESTIMATED_CORE_INPUT_UNUSABLE"
    elif us10y.quality_status != "accepted" or t10yie.quality_status != "accepted":
        estimate_reason = "REAL10Y_ESTIMATED_CORE_INPUT_UNUSABLE"
    elif us10y.alignment_status != "aligned" or t10yie.alignment_status != "aligned":
        estimate_reason = "REAL10Y_ESTIMATED_CORE_INPUT_UNUSABLE"
    elif us10y.as_of != t10yie.as_of or us10y.as_of > snapshot.as_of:
        estimate_reason = "REAL10Y_ESTIMATED_AS_OF_MISMATCH"

    if estimate_reason is None:
        estimated = VariableObservation(
            series_id="REAL10Y_ESTIMATED",
            market_role="real_yield_estimated",
            value=float(Decimal(str(us10y.value)) - Decimal(str(t10yie.value))),
            unit="percent",
            as_of=us10y.as_of,
            expected_frequency="daily",
            freshness_status="stale" if "stale" in {us10y.freshness_status, t10yie.freshness_status} else "fresh",
            quality_status="accepted",
            alignment_status="aligned",
            source_refs=_merge_source_refs(us10y.source_refs, t10yie.source_refs),
        )
    else:
        estimated = VariableObservation(
            series_id="REAL10Y_ESTIMATED",
            market_role="real_yield_estimated",
            value=None,
            unit="percent",
            as_of=snapshot.as_of,
            expected_frequency="daily",
            freshness_status="missing",
            quality_status="blocked",
            alignment_status="unknown",
            source_refs=_merge_source_refs(us10y.source_refs, t10yie.source_refs),
        )

    reason_codes = [estimate_reason or "REAL10Y_ESTIMATED_AVAILABLE"]
    if estimated.value is None:
        reason_codes.append("REAL10Y_BASIS_UNAVAILABLE")
        return estimated, None, "unavailable", tuple(reason_codes)

    if direct.value is None:
        reason_codes.extend(("REAL10Y_DIRECT_MISSING", "REAL10Y_BASIS_UNAVAILABLE"))
        return estimated, None, "unavailable", tuple(reason_codes)
    if direct.as_of != estimated.as_of:
        reason_codes.extend(("REAL10Y_DIRECT_AS_OF_MISMATCH", "REAL10Y_BASIS_UNAVAILABLE"))
        return estimated, None, "unavailable", tuple(reason_codes)
    if (
        direct.quality_status != "accepted"
        or direct.alignment_status != "aligned"
        or direct.as_of > snapshot.as_of
    ):
        reason_codes.extend(("REAL10Y_DIRECT_UNUSABLE", "REAL10Y_BASIS_UNAVAILABLE"))
        return estimated, None, "unavailable", tuple(reason_codes)

    basis_decimal = (Decimal(str(estimated.value)) - Decimal(str(direct.value))) * Decimal("100")
    basis_bp = float(basis_decimal)
    absolute_basis = abs(basis_decimal)
    if absolute_basis <= Decimal("10"):
        alignment = "aligned"
    elif absolute_basis <= Decimal("20"):
        alignment = "observe"
    else:
        alignment = "diverged"
    reason_codes.extend(("REAL10Y_DIRECT_AVAILABLE", f"REAL10Y_BASIS_{alignment.upper()}"))
    return estimated, basis_bp, alignment, tuple(reason_codes)


def _merge_source_refs(*groups: tuple[SourceReference, ...]) -> tuple[SourceReference, ...]:
    unique: dict[tuple[str, str, str], SourceReference] = {}
    for reference in (item for group in groups for item in group):
        key = (reference.source, reference.reference, reference.retrieved_at.isoformat())
        unique.setdefault(key, reference)
    return tuple(unique.values())
