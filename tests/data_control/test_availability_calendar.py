from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.data_control.availability_calendar import build_data_availability_snapshot
from apps.data_control.schemas import AvailabilityRule


OBSERVED_AT = datetime(2026, 7, 8, 10, 15, tzinfo=timezone.utc)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _item(*, storage_root: Path, artifact_glob: str, payload: object, suffix: str = ".json", threshold: int | None = 5) -> dict:
    path = storage_root / artifact_glob.replace("*", "artifact", 1)
    if suffix == ".pdf":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.7")
    else:
        _write_json(path, payload)
    rule = AvailabilityRule(
        source_key="fixture",
        label="fixture",
        source_type="fixture",
        artifact_globs=(artifact_glob,),
        freshness_threshold_minutes=threshold,
    )
    snapshot = build_data_availability_snapshot(
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        rules=(rule,),
    )
    return snapshot["items"][0]


def test_primary_observation_time_wins_over_generated_or_updated(tmp_path: Path) -> None:
    item = _item(
        storage_root=tmp_path,
        artifact_glob="quotes/*.json",
        payload={
            "observed_at": "2026-07-08T09:00:00+00:00",
            "generated_at": "2026-07-08T10:14:00+00:00",
            "updated_at": "2026-07-08T10:14:30+00:00",
        },
    )

    assert item["state"] == "stale"
    assert item["reason_code"] == "freshness_stale"
    assert item["latest_observed_at"] == "2026-07-08T09:00:00+00:00"
    assert item["metadata"]["freshness_basis"] == "observed_at"


def test_recent_mtime_does_not_refresh_stale_payload(tmp_path: Path) -> None:
    path = tmp_path / "quotes" / "artifact.json"
    _write_json(path, {"observed_at": "2026-07-08T09:00:00+00:00"})
    recent_epoch = OBSERVED_AT.timestamp()
    os.utime(path, (recent_epoch, recent_epoch))

    rule = AvailabilityRule(
        source_key="fixture",
        label="fixture",
        source_type="fixture",
        artifact_globs=("quotes/*.json",),
        freshness_threshold_minutes=5,
    )
    snapshot = build_data_availability_snapshot(
        storage_root=tmp_path,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        rules=(rule,),
    )

    item = snapshot["items"][0]
    assert item["state"] == "stale"
    assert item["lag_minutes"] == 75


def test_payload_time_selects_latest_candidate_when_mtime_order_is_reversed(tmp_path: Path) -> None:
    older = tmp_path / "quotes" / "older.json"
    newer = tmp_path / "quotes" / "newer.json"
    _write_json(older, {"observed_at": "2026-07-08T10:00:00+00:00"})
    _write_json(newer, {"observed_at": "2026-07-08T10:14:00+00:00"})
    os.utime(older, (OBSERVED_AT.timestamp(), OBSERVED_AT.timestamp()))
    os.utime(newer, (OBSERVED_AT.timestamp() - 300, OBSERVED_AT.timestamp() - 300))

    rule = AvailabilityRule(
        source_key="fixture",
        label="fixture",
        source_type="fixture",
        artifact_globs=("quotes/*.json",),
        freshness_threshold_minutes=5,
    )
    snapshot = build_data_availability_snapshot(
        storage_root=tmp_path,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        rules=(rule,),
    )

    item = snapshot["items"][0]
    assert item["state"] == "available"
    assert item["latest_artifact_ref"] == "quotes/newer.json"
    assert item["latest_observed_at"] == "2026-07-08T10:14:00+00:00"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"generated_at": "2026-07-08T10:14:00+00:00"},
        {"updated_at": "2026-07-08T10:14:00+00:00"},
        {"metadata": {"updated_at": "2026-07-08T10:14:00+00:00"}},
    ],
)
def test_without_trusted_observation_time_is_blocked(tmp_path: Path, payload: object) -> None:
    item = _item(
        storage_root=tmp_path,
        artifact_glob="quotes/*.json",
        payload=payload,
    )

    assert item["state"] == "blocked"
    assert item["reason_code"] == "evidence_time_missing"
    assert item["metadata"]["freshness_basis"] in {"metadata_time_unknown", "generated_at", "updated_at"}


def test_future_only_candidate_is_fail_closed_and_not_selected(tmp_path: Path) -> None:
    item = _item(
        storage_root=tmp_path,
        artifact_glob="quotes/*.json",
        payload={"observed_at": "2026-07-08T10:16:00+00:00"},
    )

    assert item["state"] == "blocked"
    assert item["reason_code"] == "evidence_time_future"
    assert item["latest_artifact_ref"] is None
    assert item["latest_observed_at"] is None
    assert item["metadata"]["ignored_future_artifact_refs"] == ["quotes/artifact.json"]


def test_future_candidate_cannot_suppress_current_valid_candidate(tmp_path: Path) -> None:
    _write_json(tmp_path / "quotes" / "current.json", {"observed_at": "2026-07-08T10:14:00+00:00"})
    _write_json(tmp_path / "quotes" / "future.json", {"observed_at": "2026-07-08T10:16:00+00:00"})
    rule = AvailabilityRule(
        source_key="fixture",
        label="fixture",
        source_type="fixture",
        artifact_globs=("quotes/*.json",),
        freshness_threshold_minutes=5,
    )

    snapshot = build_data_availability_snapshot(
        storage_root=tmp_path,
        trade_date="2026-07-08",
        observed_at=OBSERVED_AT,
        rules=(rule,),
    )
    item = snapshot["items"][0]

    assert item["state"] == "available"
    assert item["latest_artifact_ref"] == "quotes/current.json"
    assert item["latest_observed_at"] == "2026-07-08T10:14:00+00:00"
    assert item["metadata"]["ignored_future_artifact_refs"] == ["quotes/future.json"]


def test_pdf_without_payload_observation_time_is_not_fresh(tmp_path: Path) -> None:
    item = _item(
        storage_root=tmp_path,
        artifact_glob="raw/cme/*.pdf",
        payload={},
        suffix=".pdf",
    )

    assert item["state"] == "blocked"
    assert item["reason_code"] == "evidence_time_missing"
    assert item["latest_artifact_ref"] == "raw/cme/artifact.pdf"
    assert item["latest_observed_at"] is None
    assert item["metadata"]["freshness_basis"] == "metadata_time_unknown"


def test_pdf_without_payload_observation_time_is_presence_only_without_threshold(tmp_path: Path) -> None:
    item = _item(
        storage_root=tmp_path,
        artifact_glob="raw/cme/*.pdf",
        payload={},
        suffix=".pdf",
        threshold=None,
    )

    assert item["state"] == "available"
    assert item["reason_code"] is None
    assert item["latest_artifact_ref"] == "raw/cme/artifact.pdf"
    assert item["latest_observed_at"] is None
    assert item["lag_minutes"] is None
    assert item["metadata"]["artifact_presence_only"] is True
    assert item["metadata"]["metadata_time_unknown"] is True
