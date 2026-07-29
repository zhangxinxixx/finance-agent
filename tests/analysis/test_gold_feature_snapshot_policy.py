from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.feature_snapshot import (
    build_feature_snapshot,
    canonical_feature_snapshot_json,
)
from apps.analysis.gold_policy.schemas import FeatureSnapshotInput


FIXTURES = Path(__file__).parents[1] / "fixtures" / "gold_policy"


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("feature_snapshot_v1_*.json")))
def test_contract_fixtures_are_strictly_valid_and_auditable(path: Path) -> None:
    payload = _load_fixture(path)
    assert "schema_version" in payload
    assert "overrides" not in payload
    snapshot = build_feature_snapshot(payload)

    assert snapshot.schema_version == "feature_snapshot.v1"
    assert snapshot.asset == "XAUUSD"
    assert snapshot.scope == "daily_close"
    assert snapshot.snapshot_id == f"feature_snapshot.v1:{snapshot.payload_hash}"
    assert snapshot.xauusd_spot.market_role == "spot"
    assert snapshot.gc_futures.market_role == "futures"
    assert snapshot.xauusd_spot.series_id != snapshot.gc_futures.series_id
    assert snapshot.real10y.series_id == "DFII10"
    assert snapshot.broad_dollar.series_id == "DTWEXBGS"
    assert snapshot.real10y.source_refs
    assert snapshot.official_events.source_refs


def test_fixture_set_has_five_historical_contract_cases() -> None:
    paths = sorted(FIXTURES.glob("feature_snapshot_v1_*.json"))
    assert len(paths) == 5
    assert len({build_feature_snapshot(_load_fixture(path)).as_of.date() for path in paths}) == 5


def test_builder_is_stable_and_canonical_json_ignores_identity_fields() -> None:
    payload = json.loads((FIXTURES / "feature_snapshot_v1_bullish_2025-01-17.json").read_text())
    first = build_feature_snapshot(payload)
    second = build_feature_snapshot(json.loads(json.dumps(payload, sort_keys=True)))

    assert first == second
    assert first.payload_hash == second.payload_hash
    assert canonical_feature_snapshot_json(first) == canonical_feature_snapshot_json(second)


def test_builder_returns_existing_feature_snapshot_unchanged() -> None:
    payload = _load_fixture(FIXTURES / "feature_snapshot_v1_bullish_2025-01-17.json")
    snapshot = build_feature_snapshot(payload)

    assert build_feature_snapshot(snapshot) is snapshot


def test_models_are_frozen_and_reject_extra_fields() -> None:
    payload = json.loads((FIXTURES / "feature_snapshot_v1_bullish_2025-01-17.json").read_text())
    snapshot = build_feature_snapshot(payload)
    with pytest.raises(ValidationError):
        snapshot.xauusd_spot.value = 1.0  # type: ignore[misc]

    payload["xauusd_spot"]["invented"] = True
    with pytest.raises(ValidationError, match="invented"):
        build_feature_snapshot(payload)


@pytest.mark.parametrize("field", ["as_of", "expected_frequency", "freshness_status", "quality_status", "alignment_status", "source_refs"])
def test_each_variable_requires_time_quality_and_source_passport(field: str) -> None:
    payload = json.loads((FIXTURES / "feature_snapshot_v1_bullish_2025-01-17.json").read_text())
    del payload["real10y"][field]
    with pytest.raises(ValidationError):
        build_feature_snapshot(payload)


def test_missing_value_and_blocked_input_fail_closed() -> None:
    payload = _load_fixture(FIXTURES / "feature_snapshot_v1_blocked_2025-01-22.json")
    snapshot = build_feature_snapshot(payload)
    assert snapshot.data_quality.analysis_readiness == "blocked"
    assert snapshot.real10y.value is None
    assert snapshot.real10y.freshness_status == "missing"

    payload["real10y"]["freshness_status"] = "fresh"
    with pytest.raises(ValidationError, match="null value"):
        FeatureSnapshotInput.model_validate(payload)


def test_quality_axes_remain_independent_when_fresh_data_is_blocked() -> None:
    payload = _load_fixture(FIXTURES / "feature_snapshot_v1_bullish_2025-01-17.json")
    payload["real10y"]["quality_status"] = "blocked"
    snapshot = build_feature_snapshot(payload)

    assert snapshot.data_quality.freshness_status == "fresh"
    assert snapshot.data_quality.completeness_status == "complete"
    assert snapshot.data_quality.alignment_status == "aligned"
    assert snapshot.data_quality.analysis_readiness == "blocked"
