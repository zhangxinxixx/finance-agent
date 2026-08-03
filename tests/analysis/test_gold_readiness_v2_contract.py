from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "gold_policy" / "readiness_v2"
FIXTURE_PATHS = tuple(sorted(FIXTURE_DIR.glob("*.json")))
READINESS_FIELDS = (
    "analysis_readiness",
    "strategy_readiness",
    "options_readiness",
    "event_attribution_readiness",
    "missing_required_inputs",
    "missing_confirmatory_inputs",
    "prohibited_outputs",
    "reason_codes",
    "readiness_policy_version",
)


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(target)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _load_case(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if "input" in fixture:
        payload = fixture["input"]
    else:
        base = json.loads((FIXTURE_DIR / fixture["base_fixture"]).read_text(encoding="utf-8"))
        payload = _deep_merge(base["input"], fixture["patch"])
    return payload, fixture["expected"], fixture["case_id"]


def _build_v2(payload: dict[str, Any]):
    try:
        snapshot = build_feature_snapshot(payload)
    except ValidationError as exc:
        pytest.fail(
            "FeatureSnapshot v2 multi-domain readiness contract is not available through "
            f"build_feature_snapshot(payload): {exc}"
        )
    missing = [field for field in READINESS_FIELDS if not hasattr(snapshot.data_quality, field)]
    assert not missing, f"FeatureSnapshot v2 data_quality is missing #99 fields: {', '.join(missing)}"
    return snapshot


def test_five_readiness_fixtures_materialize_complete_v2_inputs() -> None:
    assert len(FIXTURE_PATHS) == 5
    assert {path.stem for path in FIXTURE_PATHS} == {
        "ready",
        "confirmatory_missing",
        "required_real10y_missing",
        "no_material_event",
        "options_missing",
    }
    for path in FIXTURE_PATHS:
        payload, expected, case_id = _load_case(path)
        assert payload["schema_version"] == "feature_snapshot.v2", case_id
        assert payload["readiness_policy_version"] == "gold_readiness_policy.v1", case_id
        assert "real10y_estimated" not in payload, case_id
        assert "data_quality" not in payload, case_id
        assert set(READINESS_FIELDS) == set(expected), case_id


@pytest.mark.parametrize("path", FIXTURE_PATHS, ids=lambda path: path.stem)
def test_feature_snapshot_v2_exposes_domain_readiness_contract(path: Path) -> None:
    payload, expected, _ = _load_case(path)
    quality = _build_v2(payload).data_quality

    for field in (
        "analysis_readiness",
        "strategy_readiness",
        "options_readiness",
        "event_attribution_readiness",
        "readiness_policy_version",
    ):
        assert getattr(quality, field) == expected[field]
    assert list(quality.missing_required_inputs) == expected["missing_required_inputs"]
    assert list(quality.missing_confirmatory_inputs) == expected["missing_confirmatory_inputs"]
    assert list(quality.prohibited_outputs) == expected["prohibited_outputs"]
    assert list(quality.reason_codes) == expected["reason_codes"]


def test_confirmatory_gaps_never_block_macro_analysis() -> None:
    payload, _, _ = _load_case(FIXTURE_DIR / "confirmatory_missing.json")
    quality = _build_v2(payload).data_quality

    assert quality.analysis_readiness == "observe"
    assert quality.analysis_readiness != "blocked"


def test_missing_options_only_blocks_options_and_triggered_outputs() -> None:
    payload, _, _ = _load_case(FIXTURE_DIR / "options_missing.json")
    quality = _build_v2(payload).data_quality

    assert quality.analysis_readiness != "blocked"
    assert quality.strategy_readiness == "observe"
    assert quality.options_readiness == "blocked"
    assert {"OPTIONS_CONFIRMATION", "TRIGGERED_STRATEGY"}.issubset(quality.prohibited_outputs)


def test_valid_empty_event_set_is_ready_not_missing() -> None:
    payload, _, _ = _load_case(FIXTURE_DIR / "no_material_event.json")
    quality = _build_v2(payload).data_quality

    assert quality.event_attribution_readiness == "ready"
    assert "NO_MATERIAL_OFFICIAL_EVENT" in quality.reason_codes


def test_required_real10y_gap_blocks_analysis_and_strategy() -> None:
    payload, _, _ = _load_case(FIXTURE_DIR / "required_real10y_missing.json")
    quality = _build_v2(payload).data_quality

    assert quality.analysis_readiness == "blocked"
    assert quality.strategy_readiness == "blocked"
    assert quality.missing_required_inputs == ("US10Y", "REAL10Y_ESTIMATED")


def test_snapshot_id_and_readiness_are_deterministic_across_100_builds() -> None:
    payload, _, _ = _load_case(FIXTURE_DIR / "no_material_event.json")
    snapshots = [
        _build_v2(json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True)))
        for _ in range(100)
    ]
    first = snapshots[0]

    assert {snapshot.snapshot_id for snapshot in snapshots} == {first.snapshot_id}
    assert all(snapshot.data_quality == first.data_quality for snapshot in snapshots)
