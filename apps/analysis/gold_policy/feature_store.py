"""Read-only lookup for immutable historical ``FeatureSnapshot`` artifacts."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.schemas import (
    FeatureSnapshot,
    FeatureSnapshotContract,
    FeatureSnapshotInput,
    FeatureSnapshotV2,
    FeatureSnapshotV2Input,
)


LookupStatus = Literal["found", "missing", "ambiguous", "invalid"]


class PreviousFeatureSnapshotLookup(BaseModel):
    """Explicit outcome of the bounded historical snapshot lookup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: LookupStatus
    reason_code: str
    source_path: Path | None
    snapshot: FeatureSnapshotContract | None

    def summary(self) -> dict[str, str | None]:
        """Return compact JSON-safe audit metadata without duplicating payloads."""

        return self.model_dump(mode="json", exclude={"snapshot"})


def load_previous_feature_snapshot(
    *, storage_root: Path, current: FeatureSnapshotContract
) -> PreviousFeatureSnapshotLookup:
    """Load the latest valid prior-day snapshot without falling back past a bad day.

    Only formal canonical artifacts under ``analysis/gold_mainlines`` are
    eligible.  The result is intentionally explicit so callers can fail closed
    when a prior daily-close input cannot be established.
    """

    root = storage_root.resolve()
    base = root / "analysis" / "gold_mainlines"
    if not base.is_dir():
        return _missing()

    candidates_by_date: dict[date, list[Path]] = {}
    artifact_name = f"{current.schema_version}.json"
    for date_dir in sorted(base.iterdir(), key=lambda path: path.name):
        candidate_date = _parse_directory_date_name(date_dir)
        if candidate_date is None or candidate_date >= current.as_of.date():
            continue
        if date_dir.is_symlink():
            # A date-directory symlink could redirect the whole lookup outside
            # the storage root. Treat that date as invalid, never as absent.
            candidates_by_date[candidate_date] = [date_dir / artifact_name]
            continue
        if not date_dir.is_dir():
            continue
        candidates = sorted(date_dir.glob(f"*/{artifact_name}"), key=lambda path: path.as_posix())
        if candidates:
            candidates_by_date[candidate_date] = candidates

    if not candidates_by_date:
        return _missing()

    latest_date = max(candidates_by_date)
    valid: list[tuple[Path, FeatureSnapshot | FeatureSnapshotV2]] = []
    for candidate in candidates_by_date[latest_date]:
        snapshot = _read_verified_snapshot(candidate, root=root, expected_date=latest_date)
        if snapshot is not None:
            valid.append((candidate, snapshot))

    if not valid:
        return PreviousFeatureSnapshotLookup(
            status="invalid",
            reason_code="previous_feature_snapshot_latest_date_invalid",
            source_path=None,
            snapshot=None,
        )

    identities = {snapshot.snapshot_id for _, snapshot in valid}
    if len(identities) != 1:
        return PreviousFeatureSnapshotLookup(
            status="ambiguous",
            reason_code="previous_feature_snapshot_latest_date_ambiguous",
            source_path=None,
            snapshot=None,
        )

    source_path, snapshot = min(valid, key=lambda item: item[0].as_posix())
    return PreviousFeatureSnapshotLookup(
        status="found",
        reason_code="previous_feature_snapshot_found",
        source_path=source_path,
        snapshot=snapshot,
    )


def _missing() -> PreviousFeatureSnapshotLookup:
    return PreviousFeatureSnapshotLookup(
        status="missing",
        reason_code="previous_feature_snapshot_missing",
        source_path=None,
        snapshot=None,
    )


def _parse_directory_date_name(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.name)
    except ValueError:
        return None


def _read_verified_snapshot(
    path: Path, *, root: Path, expected_date: date
) -> FeatureSnapshot | FeatureSnapshotV2 | None:
    """Validate a candidate's containment, contract, and deterministic identity."""

    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            return None
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if payload.get("schema_version") == "feature_snapshot.v2":
            persisted = FeatureSnapshotV2.model_validate(payload)
            input_payload = persisted.model_dump(
                mode="python",
                exclude={
                    "real10y_estimated",
                    "real10y_basis_bp",
                    "real10y_alignment",
                    "real10y_reason_codes",
                    "real10y_quality",
                    "data_quality",
                    "payload_hash",
                    "snapshot_id",
                },
            )
            rebuilt = build_feature_snapshot(FeatureSnapshotV2Input.model_validate(input_payload))
        else:
            persisted = FeatureSnapshot.model_validate(payload)
            input_payload = persisted.model_dump(
                mode="python", exclude={"data_quality", "payload_hash", "snapshot_id"}
            )
            rebuilt = build_feature_snapshot(FeatureSnapshotInput.model_validate(input_payload))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError):
        return None
    if (
        persisted != rebuilt
        or persisted.payload_hash != rebuilt.payload_hash
        or persisted.snapshot_id != rebuilt.snapshot_id
        or persisted.data_quality != rebuilt.data_quality
        or persisted.asset != "XAUUSD"
        or persisted.scope != "daily_close"
        or persisted.as_of.date() != expected_date
    ):
        return None
    return rebuilt
