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
    path = root / "analysis" / "gold_mainlines" / trade_date / run_id / f"{snapshot.schema_version}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.model_dump(mode="json")), encoding="utf-8")
    return path


def _current():
    return _snapshot("feature_snapshot_v1_event_flat_2025-01-29.json")


def _v2_snapshot():
    return _to_v2(_snapshot("feature_snapshot_v1_bearish_2025-01-21.json"))


def _readiness_v2_snapshot():
    fixture = _fixture("readiness_v2/ready.json")
    return build_feature_snapshot(fixture["input"])


def _current_v2():
    return _to_v2(_current())


def _to_v2(snapshot):
    payload = snapshot.model_dump(
        mode="python", exclude={"data_quality", "payload_hash", "snapshot_id"}
    )
    direct = payload.pop("real10y")
    direct["market_role"] = "real_yield_direct"
    payload.update(schema_version="feature_snapshot.v2", real10y_direct=direct)
    return build_feature_snapshot(payload)


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


def test_v2_snapshot_is_verified_from_its_own_contract_without_rehashing_v1(tmp_path: Path) -> None:
    snapshot = _v2_snapshot()
    path = tmp_path / "analysis" / "gold_mainlines" / "2025-01-21" / "v2" / "feature_snapshot.v2.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.model_dump(mode="json")), encoding="utf-8")

    lookup = load_previous_feature_snapshot(storage_root=tmp_path, current=_current_v2())

    assert lookup.status == "found"
    assert lookup.snapshot == snapshot

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["real10y_estimated"]["value"] = 999.0
    path.write_text(json.dumps(payload), encoding="utf-8")
    invalid = load_previous_feature_snapshot(storage_root=tmp_path, current=_current_v2())
    assert (invalid.status, invalid.reason_code) == (
        "invalid",
        "previous_feature_snapshot_latest_date_invalid",
    )


def test_v2_readiness_round_trip_is_preserved_and_tampering_is_rejected(tmp_path: Path) -> None:
    snapshot = _readiness_v2_snapshot()
    path = _write_snapshot(
        tmp_path,
        trade_date="2025-01-17",
        run_id="readiness-v2",
        snapshot=snapshot,
    )

    lookup = load_previous_feature_snapshot(storage_root=tmp_path, current=_current_v2())

    assert lookup.status == "found"
    assert lookup.snapshot == snapshot
    assert lookup.snapshot.readiness_policy_version == "gold_readiness_policy.v1"
    assert lookup.snapshot.data_quality == snapshot.data_quality
    assert lookup.snapshot.data_quality.analysis_readiness == "ready"
    assert lookup.snapshot.data_quality.strategy_readiness == "ready"
    assert lookup.snapshot.data_quality.options_readiness == "ready"
    assert lookup.snapshot.data_quality.event_attribution_readiness == "ready"

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["data_quality"]["analysis_readiness"] = "blocked"
    path.write_text(json.dumps(payload), encoding="utf-8")

    invalid = load_previous_feature_snapshot(storage_root=tmp_path, current=_current_v2())
    assert (invalid.status, invalid.reason_code, invalid.snapshot) == (
        "invalid",
        "previous_feature_snapshot_latest_date_invalid",
        None,
    )


def test_lookup_selects_only_the_current_schema_version_when_versions_coexist(tmp_path: Path) -> None:
    v1 = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    v2 = _v2_snapshot()
    v1_path = _write_snapshot(tmp_path, trade_date="2025-01-21", run_id="v1", snapshot=v1)
    v2_path = _write_snapshot(tmp_path, trade_date="2025-01-21", run_id="v2", snapshot=v2)

    v1_lookup = load_previous_feature_snapshot(storage_root=tmp_path, current=_current())
    v2_lookup = load_previous_feature_snapshot(storage_root=tmp_path, current=_current_v2())

    assert (v1_lookup.status, v1_lookup.source_path, v1_lookup.snapshot) == ("found", v1_path, v1)
    assert (v2_lookup.status, v2_lookup.source_path, v2_lookup.snapshot) == ("found", v2_path, v2)


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
