from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "gold_policy" / "real10y_v2_cases.json"
DERIVATION_CASE_IDS = (
    "aligned",
    "aligned_at_10bp",
    "observe_basis",
    "observe_at_20bp",
    "diverged_basis",
    "direct_missing",
    "core_date_mismatch",
    "direct_as_of_mismatch",
    "us10y_after_cutoff",
    "t10yie_after_cutoff",
    "rejected_core_input",
    "direct_blocked",
    "direct_misaligned",
    "direct_after_cutoff",
)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _merge_payload(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(base)
    for field, changes in patch.items():
        assert isinstance(changes, dict), f"{field} patch must be an object"
        assert isinstance(payload[field], dict), f"{field} must be an object in the base payload"
        payload[field].update(changes)
    return payload


def _case_payload(case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = _fixture()
    cases = {case["id"]: case for case in fixture["cases"]}
    case = cases[case_id]
    if "repeat_of" in case:
        case = cases[case["repeat_of"]]
    return _merge_payload(fixture["base_payload"], case["patch"]), case["expected"]


def _build_v2(payload: dict[str, Any]) -> Any:
    try:
        snapshot = build_feature_snapshot(payload)
    except ValidationError as exc:
        pytest.fail(
            "FeatureSnapshot v2 is not available through build_feature_snapshot(payload); "
            "the v2 builder must accept the full fixture payload and derive Real10Y fields. "
            f"Validation error: {exc}"
        )
    assert snapshot.schema_version == "feature_snapshot.v2"
    return snapshot


def _references(observation: Any) -> list[str]:
    return [reference.reference for reference in observation.source_refs]


def test_real10y_v2_fixture_is_parseable_and_never_supplies_derived_values() -> None:
    fixture = _fixture()
    assert fixture["base_payload"]["schema_version"] == "feature_snapshot.v2"
    assert "real10y_estimated" not in fixture["base_payload"]
    assert "real10y_basis_bp" not in fixture["base_payload"]
    assert {case["id"] for case in fixture["cases"]} == {
        "aligned",
        "aligned_at_10bp",
        "observe_basis",
        "observe_at_20bp",
        "diverged_basis",
        "direct_missing",
        "core_date_mismatch",
        "direct_as_of_mismatch",
        "us10y_after_cutoff",
        "t10yie_after_cutoff",
        "rejected_core_input",
        "direct_blocked",
        "direct_misaligned",
        "direct_after_cutoff",
        "deterministic_repeat",
    }


@pytest.mark.parametrize("case_id", DERIVATION_CASE_IDS)
def test_real10y_v2_derives_dual_basis_contract(case_id: str) -> None:
    payload, expected = _case_payload(case_id)
    snapshot = _build_v2(payload)

    assert snapshot.real10y_estimated.value == expected["real10y_estimated"]
    assert snapshot.real10y_direct.value == expected["real10y_direct"]
    assert snapshot.real10y_basis_bp == expected["real10y_basis_bp"]
    assert snapshot.real10y_alignment == expected["real10y_alignment"]
    assert snapshot.real10y_reason_codes
    assert set(expected["real10y_reason_codes"]).issubset(snapshot.real10y_reason_codes)

    assert _references(snapshot.real10y_estimated) == [
        "contract://real10y/us10y",
        "contract://real10y/t10yie",
    ]
    assert _references(snapshot.real10y_direct) == ["contract://real10y/dfii10"]


@pytest.mark.parametrize(
    "case_id",
    (
        "core_date_mismatch",
        "us10y_after_cutoff",
        "t10yie_after_cutoff",
        "rejected_core_input",
    ),
)
def test_real10y_direct_never_substitutes_for_a_missing_estimate(case_id: str) -> None:
    payload, _ = _case_payload(case_id)
    snapshot = _build_v2(payload)

    assert snapshot.real10y_estimated.value is None
    assert snapshot.real10y_direct.value == 2.2
    assert snapshot.real10y_estimated.source_refs != snapshot.real10y_direct.source_refs


@pytest.mark.parametrize(
    "case_id",
    ("direct_as_of_mismatch", "direct_blocked", "direct_misaligned", "direct_after_cutoff"),
)
def test_unusable_direct_rate_never_confirms_the_estimated_direction(case_id: str) -> None:
    payload, _ = _case_payload(case_id)
    snapshot = _build_v2(payload)

    assert snapshot.real10y_estimated.value == 2.2
    assert snapshot.real10y_basis_bp is None
    assert snapshot.real10y_alignment == "unavailable"
    assert _references(snapshot.real10y_estimated) == [
        "contract://real10y/us10y",
        "contract://real10y/t10yie",
    ]
    assert _references(snapshot.real10y_direct) == ["contract://real10y/dfii10"]


def test_real10y_v2_is_deterministic_for_identical_input() -> None:
    payload, expected = _case_payload("deterministic_repeat")

    snapshots = [_build_v2(json.loads(json.dumps(payload, sort_keys=True))) for _ in range(100)]
    first = snapshots[0]

    assert all(snapshot == first for snapshot in snapshots)
    assert {snapshot.snapshot_id for snapshot in snapshots} == {first.snapshot_id}
    assert first.real10y_estimated.value == expected["real10y_estimated"]
    assert first.real10y_basis_bp == expected["real10y_basis_bp"]
