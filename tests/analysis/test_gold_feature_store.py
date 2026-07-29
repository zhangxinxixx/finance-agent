from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.feature_store import load_previous_feature_snapshot


def _fixture(name: str) -> dict:
    path = Path(__file__).parents[1] / "fixtures" / "gold_policy" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot(name: str):
    return build_feature_snapshot(_fixture(name))


def _write_snapshot(root: Path, *, trade_date: str, run_id: str, snapshot) -> Path:
    path = root / "analysis" / "gold_mainlines" / trade_date / run_id / "feature_snapshot.v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.model_dump(mode="json")), encoding="utf-8")
    return path


def _current():
    return _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")


def test_previous_feature_snapshot_missing_when_no_prior_candidate(tmp_path: Path) -> None:
    lookup = load_previous_feature_snapshot(storage_root=tmp_path, current=_current())
    assert (lookup.status, lookup.reason_code, lookup.source_path, lookup.snapshot) == (
        "missing",
        "previous_feature_snapshot_missing",
        None,
        None,
    )


def test_previous_feature_snapshot_selects_latest_valid_prior_date(tmp_path: Path) -> None:
    older = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    latest = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, trade_date="2025-01-17", run_id="older", snapshot=older)
    expected_path = _write_snapshot(tmp_path, trade_date="2025-01-21", run_id="latest", snapshot=latest)

    lookup = load_previous_feature_snapshot(storage_root=tmp_path, current=_current())
    assert lookup.status == "found"
    assert lookup.source_path == expected_path
    assert lookup.snapshot == latest


def test_identical_latest_day_duplicates_are_deduplicated_with_stable_path(tmp_path: Path) -> None:
    previous = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    expected_path = _write_snapshot(tmp_path, trade_date="2025-01-21", run_id="a-run", snapshot=previous)
    _write_snapshot(tmp_path, trade_date="2025-01-21", run_id="z-run", snapshot=previous)

    results = [load_previous_feature_snapshot(storage_root=tmp_path, current=_current()) for _ in range(100)]
    assert {result.status for result in results} == {"found"}
    assert {result.source_path for result in results} == {expected_path}
    assert {result.snapshot_id for result in (result.snapshot for result in results) if result is not None} == {
        previous.snapshot_id
    }


def test_different_latest_day_payloads_are_ambiguous(tmp_path: Path) -> None:
    first = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    changed_input = first.model_dump(
        mode="python", exclude={"data_quality", "payload_hash", "snapshot_id"}
    )
    changed_input["broad_dollar"] = {
        **changed_input["broad_dollar"],
        "value": 121.25,
    }
    second = build_feature_snapshot(changed_input)
    _write_snapshot(tmp_path, trade_date="2025-01-17", run_id="one", snapshot=first)
    _write_snapshot(tmp_path, trade_date="2025-01-17", run_id="two", snapshot=second)

    lookup = load_previous_feature_snapshot(storage_root=tmp_path, current=_current())
    assert (lookup.status, lookup.reason_code, lookup.snapshot) == (
        "ambiguous",
        "previous_feature_snapshot_latest_date_ambiguous",
        None,
    )


def test_tampered_hash_is_invalid(tmp_path: Path) -> None:
    previous = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    path = _write_snapshot(tmp_path, trade_date="2025-01-21", run_id="tampered", snapshot=previous)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["payload_hash"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    lookup = load_previous_feature_snapshot(storage_root=tmp_path, current=_current())
    assert (lookup.status, lookup.reason_code) == (
        "invalid",
        "previous_feature_snapshot_latest_date_invalid",
    )


def test_latest_invalid_candidate_does_not_fall_back_to_an_older_date(tmp_path: Path) -> None:
    _write_snapshot(
        tmp_path,
        trade_date="2025-01-17",
        run_id="valid-old",
        snapshot=_snapshot("feature_snapshot_v1_bullish_2025-01-17.json"),
    )
    broken = tmp_path / "analysis" / "gold_mainlines" / "2025-01-21" / "broken" / "feature_snapshot.v1.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("not json", encoding="utf-8")

    lookup = load_previous_feature_snapshot(storage_root=tmp_path, current=_current())
    assert (lookup.status, lookup.reason_code, lookup.snapshot) == (
        "invalid",
        "previous_feature_snapshot_latest_date_invalid",
        None,
    )


def test_future_candidate_is_ignored(tmp_path: Path) -> None:
    _write_snapshot(
        tmp_path,
        trade_date="2030-01-01",
        run_id="future",
        snapshot=_snapshot("feature_snapshot_v1_event_flat_2025-01-29.json"),
    )
    lookup = load_previous_feature_snapshot(storage_root=tmp_path, current=_current())
    assert lookup.status == "missing"


def test_symlink_escape_is_invalid_and_never_read(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-feature-snapshot.json"
    outside.write_text(json.dumps(_current().model_dump(mode="json")), encoding="utf-8")
    target = tmp_path / "analysis" / "gold_mainlines" / "2025-01-21" / "run" / "feature_snapshot.v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(outside)

    lookup = load_previous_feature_snapshot(storage_root=tmp_path, current=_current())
    assert (lookup.status, lookup.reason_code, lookup.snapshot) == (
        "invalid",
        "previous_feature_snapshot_latest_date_invalid",
        None,
    )


def test_runtime_inputs_adapts_current_and_exposes_previous_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.analysis.gold_policy import runtime_inputs

    current = _current()
    previous = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, trade_date="2025-01-21", run_id="previous", snapshot=previous)
    monkeypatch.setattr(
        runtime_inputs,
        "build_feature_snapshot_from_analysis_snapshot",
        lambda _: current,
    )

    result = runtime_inputs.prepare_gold_policy_runtime_inputs(
        storage_root=tmp_path,
        snapshot={"asset": "XAUUSD"},
    )
    assert result.current is current
    assert result.previous == previous
    assert result.lookup.status == "found"
    assert result.lookup.summary() == {
        "status": "found",
        "reason_code": "previous_feature_snapshot_found",
        "source_path": (
            tmp_path
            / "analysis"
            / "gold_mainlines"
            / "2025-01-21"
            / "previous"
            / "feature_snapshot.v1.json"
        ).as_posix(),
    }
