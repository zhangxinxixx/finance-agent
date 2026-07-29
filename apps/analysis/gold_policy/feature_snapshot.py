"""Pure construction and canonical serialization for ``feature_snapshot.v1``."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from apps.analysis.gold_policy.schemas import (
    DataQualitySnapshot,
    FeatureSnapshot,
    FeatureSnapshotInput,
    OfficialEventSnapshot,
    VariableObservation,
)


def canonical_feature_snapshot_json(snapshot: FeatureSnapshotInput | FeatureSnapshot) -> str:
    """Return stable JSON for identity calculation; identity fields are excluded."""

    payload = snapshot.model_dump(mode="json", exclude={"data_quality", "payload_hash", "snapshot_id"})
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_feature_snapshot(payload: Mapping[str, Any] | FeatureSnapshotInput) -> FeatureSnapshot:
    """Build a deterministic snapshot without I/O, clocks, or mutable defaults."""

    if isinstance(payload, FeatureSnapshot):
        return payload
    input_snapshot = (
        payload if isinstance(payload, FeatureSnapshotInput) else FeatureSnapshotInput.model_validate(payload)
    )
    data_quality = derive_data_quality(input_snapshot)
    canonical_json = canonical_feature_snapshot_json(input_snapshot)
    payload_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return FeatureSnapshot(
        **input_snapshot.model_dump(),
        data_quality=data_quality,
        payload_hash=payload_hash,
        snapshot_id=f"feature_snapshot.v1:{payload_hash}",
    )


def derive_data_quality(snapshot: FeatureSnapshotInput) -> DataQualitySnapshot:
    """Conservatively derive readiness from every formal input data passport."""

    inputs: tuple[VariableObservation | OfficialEventSnapshot, ...] = (
        snapshot.xauusd_spot,
        snapshot.gc_futures,
        snapshot.us02y,
        snapshot.us10y,
        snapshot.us30y,
        snapshot.t10yie,
        snapshot.real10y,
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
