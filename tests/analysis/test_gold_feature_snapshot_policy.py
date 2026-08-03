from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.feature_snapshot import (
    build_feature_snapshot,
    canonical_feature_snapshot_json,
)
from apps.analysis.gold_policy.schemas import FeatureSnapshotInput, FeatureSnapshotV2Input


FIXTURES = Path(__file__).parents[1] / "fixtures" / "gold_policy"


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text())


def _v2_payload(*, us10y: float = 4.50, t10yie: float = 2.30, direct: float | None = 2.15) -> dict:
    payload = _load_fixture(FIXTURES / "feature_snapshot_v1_bullish_2025-01-17.json")
    direct_observation = payload.pop("real10y")
    direct_observation.update(
        series_id="DFII10",
        market_role="real_yield_direct",
        value=direct,
        freshness_status="missing" if direct is None else "fresh",
        quality_status="blocked" if direct is None else "accepted",
        alignment_status="unknown" if direct is None else "aligned",
    )
    payload.update(
        schema_version="feature_snapshot.v2",
        real10y_direct=direct_observation,
    )
    for value in payload.values():
        if isinstance(value, dict) and "source_refs" in value:
            for reference in value["source_refs"]:
                reference["retrieved_at"] = payload["as_of"]
    payload["us10y"]["value"] = us10y
    payload["t10yie"]["value"] = t10yie
    return payload


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
    assert set(first.data_quality.model_dump()) == {
        "freshness_status",
        "completeness_status",
        "alignment_status",
        "analysis_readiness",
    }
    assert "readiness_policy_version" not in first.model_dump()


def test_builder_returns_existing_feature_snapshot_unchanged() -> None:
    payload = _load_fixture(FIXTURES / "feature_snapshot_v1_bullish_2025-01-17.json")
    snapshot = build_feature_snapshot(payload)

    assert build_feature_snapshot(snapshot) is snapshot


def test_builder_rejects_forged_v2_derived_readiness() -> None:
    snapshot = build_feature_snapshot(_v2_payload())
    forged_quality = snapshot.data_quality.model_copy(
        update={"strategy_readiness": "blocked"}
    )
    forged = snapshot.model_copy(update={"data_quality": forged_quality})

    with pytest.raises(ValueError, match="derived fields or identity are invalid"):
        build_feature_snapshot(forged)


@pytest.mark.parametrize(
    ("field", "value"),
    (("real10y_basis_bp", 999.0), ("payload_hash", "0" * 64)),
)
def test_builder_rejects_forged_v2_real10y_or_identity(field: str, value) -> None:
    snapshot = build_feature_snapshot(_v2_payload())

    with pytest.raises(ValueError, match="derived fields or identity are invalid"):
        build_feature_snapshot(snapshot.model_copy(update={field: value}))


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


def test_v2_derives_exact_estimated_real_yield_and_basis_with_independent_refs() -> None:
    payload = _v2_payload()
    payload["us10y"]["source_refs"][0]["reference"] = "fred://US10Y"
    payload["t10yie"]["source_refs"][0]["reference"] = "fred://T10YIE"
    payload["real10y_direct"]["source_refs"][0]["reference"] = "fred://DFII10"

    snapshot = build_feature_snapshot(payload)

    assert snapshot.schema_version == "feature_snapshot.v2"
    assert snapshot.snapshot_id == f"feature_snapshot.v2:{snapshot.payload_hash}"
    assert snapshot.real10y_estimated.value == 2.2
    assert snapshot.real10y_estimated.as_of == snapshot.us10y.as_of == snapshot.t10yie.as_of
    assert snapshot.real10y_estimated.source_refs != snapshot.real10y_direct.source_refs
    assert [reference.reference for reference in snapshot.real10y_estimated.source_refs] == [
        "fred://US10Y",
        "fred://T10YIE",
    ]
    assert snapshot.real10y_basis_bp == pytest.approx(5.0)
    assert snapshot.real10y_alignment == "aligned"
    assert snapshot.real10y_reason_codes == (
        "REAL10Y_ESTIMATED_AVAILABLE",
        "REAL10Y_DIRECT_AVAILABLE",
        "REAL10Y_BASIS_ALIGNED",
    )


@pytest.mark.parametrize(
    ("direct", "expected_alignment"),
    [(2.10, "aligned"), (2.00, "observe"), (1.95, "diverged")],
)
def test_v2_basis_thresholds_are_explicit(direct: float, expected_alignment: str) -> None:
    snapshot = build_feature_snapshot(_v2_payload(direct=direct))

    assert snapshot.real10y_alignment == expected_alignment
    assert snapshot.real10y_reason_codes[-1] == f"REAL10Y_BASIS_{expected_alignment.upper()}"


def test_v2_date_mismatch_blocks_estimate_without_fabricating_basis() -> None:
    payload = _v2_payload()
    payload["t10yie"]["as_of"] = "2025-01-16T00:00:00+00:00"

    snapshot = build_feature_snapshot(payload)

    assert snapshot.real10y_estimated.value is None
    assert snapshot.real10y_basis_bp is None
    assert snapshot.real10y_alignment == "unavailable"
    assert "REAL10Y_ESTIMATED_AS_OF_MISMATCH" in snapshot.real10y_reason_codes


def test_v2_future_aligned_components_and_direct_are_not_eligible() -> None:
    payload = _v2_payload()
    payload["us10y"]["as_of"] = "2025-01-18T00:00:00+00:00"
    payload["t10yie"]["as_of"] = "2025-01-18T00:00:00+00:00"
    payload["real10y_direct"]["as_of"] = "2025-01-18T00:00:00+00:00"

    snapshot = build_feature_snapshot(payload)

    assert snapshot.real10y_estimated.value is None
    assert snapshot.real10y_basis_bp is None
    assert snapshot.real10y_reason_codes == (
        "REAL10Y_ESTIMATED_AS_OF_MISMATCH",
        "REAL10Y_BASIS_UNAVAILABLE",
    )


def test_v2_unusable_direct_keeps_estimate_and_marks_basis_unavailable() -> None:
    payload = _v2_payload()
    payload["real10y_direct"]["quality_status"] = "observe"

    snapshot = build_feature_snapshot(payload)

    assert snapshot.real10y_estimated.value == 2.2
    assert snapshot.real10y_basis_bp is None
    assert snapshot.real10y_reason_codes[-2:] == (
        "REAL10Y_DIRECT_UNUSABLE",
        "REAL10Y_BASIS_UNAVAILABLE",
    )


def test_v2_direct_as_of_mismatch_keeps_estimate_but_rejects_basis() -> None:
    payload = _v2_payload()
    payload["real10y_direct"]["as_of"] = "2025-01-16T00:00:00+00:00"

    snapshot = build_feature_snapshot(payload)

    assert snapshot.real10y_estimated.value == 2.2
    assert snapshot.real10y_basis_bp is None
    assert snapshot.real10y_reason_codes[-2:] == (
        "REAL10Y_DIRECT_AS_OF_MISMATCH",
        "REAL10Y_BASIS_UNAVAILABLE",
    )


def test_v2_direct_missing_does_not_block_estimated_real_yield() -> None:
    snapshot = build_feature_snapshot(_v2_payload(direct=None))

    assert snapshot.real10y_estimated.value == 2.2
    assert snapshot.real10y_basis_bp is None
    assert snapshot.real10y_alignment == "unavailable"
    assert snapshot.data_quality.analysis_readiness == "ready"
    assert snapshot.real10y_reason_codes[-2:] == (
        "REAL10Y_DIRECT_MISSING",
        "REAL10Y_BASIS_UNAVAILABLE",
    )


def test_v2_diverged_basis_prohibits_strong_real_yield_confirmation() -> None:
    snapshot = build_feature_snapshot(_v2_payload(direct=1.95))

    assert snapshot.real10y_quality.prohibited_conclusions == (
        "STRONG_REAL_YIELD_DIRECTION_CONFIRMATION",
    )
    assert snapshot.real10y_quality.reason_codes == snapshot.real10y_reason_codes


def test_v2_identity_is_stable_and_derived_fields_cannot_be_supplied() -> None:
    payload = _v2_payload()
    first = build_feature_snapshot(payload)
    second = build_feature_snapshot(json.loads(json.dumps(payload, sort_keys=True)))

    assert first.snapshot_id == second.snapshot_id
    assert {build_feature_snapshot(payload).snapshot_id for _ in range(100)} == {first.snapshot_id}
    assert canonical_feature_snapshot_json(first) == canonical_feature_snapshot_json(
        FeatureSnapshotV2Input.model_validate(payload)
    )
    payload["real10y_estimated"] = {"invented": True}
    with pytest.raises(ValidationError, match="real10y_estimated"):
        build_feature_snapshot(payload)


def test_v2_readiness_policy_version_is_part_of_canonical_input_and_output() -> None:
    payload = _v2_payload()
    input_snapshot = FeatureSnapshotV2Input.model_validate(payload)
    canonical = canonical_feature_snapshot_json(input_snapshot)
    snapshot = build_feature_snapshot(input_snapshot)

    assert input_snapshot.readiness_policy_version == "gold_readiness_policy.v1"
    assert '"readiness_policy_version":"gold_readiness_policy.v1"' in canonical
    assert snapshot.readiness_policy_version == "gold_readiness_policy.v1"
    assert snapshot.data_quality.readiness_policy_version == "gold_readiness_policy.v1"
    assert snapshot.data_quality.analysis_readiness == "ready"
