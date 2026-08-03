"""Prepare deterministic runtime inputs for the Gold Policy seam."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.analysis.gold_policy.cme_options_loader import (
    CMEOptionsArtifactLoadResult,
    load_cme_options_artifact,
)
from apps.analysis.gold_policy.cme_options_regime import (
    CMEOptionsRegimeSnapshot,
    adapt_options_analysis_to_cme_options_regime,
)
from apps.analysis.gold_policy.feature_adapter import build_feature_snapshot_from_analysis_snapshot
from apps.analysis.gold_policy.feature_store import (
    PreviousFeatureSnapshotLookup,
    load_previous_feature_snapshot,
)
from apps.analysis.gold_policy.schemas import FeatureSnapshotContract


@dataclass(frozen=True)
class GoldPolicyRuntimeInputs:
    current: FeatureSnapshotContract
    previous: FeatureSnapshotContract | None
    lookup: PreviousFeatureSnapshotLookup


@dataclass(frozen=True)
class GoldPolicyFormalOptionsInputs:
    snapshot: CMEOptionsRegimeSnapshot
    artifact_lookup: CMEOptionsArtifactLoadResult

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.artifact_lookup.status,
            "reason_code": self.artifact_lookup.reason_code,
            "source_status": self.artifact_lookup.source_status,
            "quality": self.artifact_lookup.quality,
            "artifact_path": (
                str(self.artifact_lookup.artifact_path) if self.artifact_lookup.artifact_path is not None else None
            ),
            "run_id": self.artifact_lookup.run_id,
            "snapshot_id": self.snapshot.snapshot_id,
            "regime": self.snapshot.regime.value,
            "directional_bias": self.snapshot.directional_bias,
            "contract_quality": self.snapshot.quality_status,
            "reason_codes": list(self.snapshot.reason_codes),
        }


def prepare_gold_policy_runtime_inputs(*, storage_root: Path, snapshot: Mapping[str, Any]) -> GoldPolicyRuntimeInputs:
    """Adapt current structured inputs and resolve the formal prior-day input."""

    current = build_feature_snapshot_from_analysis_snapshot(snapshot)
    lookup = load_previous_feature_snapshot(storage_root=storage_root, current=current)
    return GoldPolicyRuntimeInputs(current=current, previous=lookup.snapshot, lookup=lookup)


def prepare_gold_policy_formal_options_inputs(
    *,
    storage_root: Path,
    current: FeatureSnapshotContract,
    decision_as_of: datetime,
) -> GoldPolicyFormalOptionsInputs:
    """Load and adapt the exact same-session CME artifact, never a cross-day fallback."""

    if decision_as_of.tzinfo is None or decision_as_of.utcoffset() is None:
        raise ValueError("options decision_as_of must be timezone-aware")
    decision_time = decision_as_of.astimezone(UTC)
    trade_date = current.as_of.astimezone(UTC).date()
    lookup = load_cme_options_artifact(
        storage_root=storage_root,
        trade_date=trade_date,
        decision_as_of=decision_time,
    )
    if lookup.status == "available" and lookup.payload is not None:
        payload = _thaw(lookup.payload)
        if not isinstance(payload, dict) or lookup.artifact_path is None:
            raise ValueError("available CME options lookup must contain a typed artifact")
        digest = hashlib.sha256(lookup.artifact_path.read_bytes()).hexdigest()
        payload.setdefault("snapshot_id", f"cme_options_analysis.v1:{digest}")
        if lookup.run_id is not None:
            payload.setdefault("run_id", lookup.run_id)
    else:
        payload = {
            "trade_date": trade_date.isoformat(),
            "data_source": {"status": "UNKNOWN"},
        }
    snapshot = adapt_options_analysis_to_cme_options_regime(
        payload,
        source_snapshot_id=current.snapshot_id,
        as_of=decision_time,
    )
    return GoldPolicyFormalOptionsInputs(snapshot=snapshot, artifact_lookup=lookup)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
