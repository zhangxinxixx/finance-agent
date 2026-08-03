"""Prepare deterministic runtime inputs for the Gold Policy seam."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def prepare_gold_policy_runtime_inputs(
    *, storage_root: Path, snapshot: Mapping[str, Any]
) -> GoldPolicyRuntimeInputs:
    """Adapt current structured inputs and resolve the formal prior-day input."""

    current = build_feature_snapshot_from_analysis_snapshot(snapshot)
    lookup = load_previous_feature_snapshot(storage_root=storage_root, current=current)
    return GoldPolicyRuntimeInputs(current=current, previous=lookup.snapshot, lookup=lookup)
