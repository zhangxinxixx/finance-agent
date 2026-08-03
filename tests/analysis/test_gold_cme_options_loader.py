from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from apps.analysis.gold_policy.cme_options_loader import load_cme_options_artifact
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.runtime_inputs import (
    prepare_gold_policy_formal_options_inputs,
)
from tests.analysis.test_gold_cme_options_regime import _options_output


TRADE_DATE = date(2026, 8, 7)
AS_OF = datetime(2026, 8, 7, 23, tzinfo=timezone.utc)


def _payload(*, status: str = "FINAL", generated_at: str = "2026-08-07T20:00:00+00:00", **overrides: object) -> dict:
    payload = {
        "trade_date": TRADE_DATE.isoformat(),
        "generated_at": generated_at,
        "run_id": "run-a",
        "data_source": {
            "report_date": TRADE_DATE.isoformat(),
            "status": status,
            "source_url": "https://www.cmegroup.com/bulletin.pdf",
            "product": "OG",
            "input_snapshot_ids": {"raw_file_sha256": "a" * 64},
        },
    }
    payload.update(overrides)
    return payload


def _write(root: Path, relative: str, payload: dict | None = None) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload if payload is not None else _payload()), encoding="utf-8")
    return path


def test_loads_final_from_highest_priority_and_freezes_payload(tmp_path: Path) -> None:
    preferred = _write(tmp_path, "features/cme/2026-08-07/run-a/options_analysis.json")
    _write(tmp_path, "outputs/cme/2026-08-07/run-b/options_analysis.json", _payload(run_id="run-b"))

    result = load_cme_options_artifact(storage_root=tmp_path, trade_date=TRADE_DATE, decision_as_of=AS_OF)

    assert result.status == "available"
    assert result.reason_code == "cme_options_artifact_final"
    assert result.quality == "accepted"
    assert result.artifact_path == preferred.resolve()
    assert result.run_id == "run-a"
    assert result.payload is not None
    with pytest.raises(TypeError):
        result.payload["trade_date"] = "mutated"  # type: ignore[index]


def test_derives_run_id_from_the_artifact_path_when_payload_omits_it(tmp_path: Path) -> None:
    payload = _payload()
    payload.pop("run_id")
    _write(tmp_path, "features/cme/2026-08-07/path-run/options_analysis.json", payload)

    result = load_cme_options_artifact(
        storage_root=tmp_path,
        trade_date=TRADE_DATE,
        decision_as_of=AS_OF,
    )

    assert result.status == "available"
    assert result.run_id == "path-run"


def test_prelim_is_available_but_observe(tmp_path: Path) -> None:
    _write(tmp_path, "outputs/cme_options/2026-08-07/options_analysis.json", _payload(status="PRELIM"))

    result = load_cme_options_artifact(storage_root=tmp_path, trade_date=TRADE_DATE, decision_as_of=AS_OF)

    assert (result.status, result.reason_code, result.quality, result.source_status) == (
        "available",
        "cme_options_artifact_prelim_observe",
        "observe",
        "PRELIM",
    )


def test_source_trace_is_accepted_as_lineage_when_input_ids_are_empty(tmp_path: Path) -> None:
    payload = _payload(
        data_source={
            **_payload()["data_source"],
            "input_snapshot_ids": {},
        },
        source_trace=[{"source_ref": "cme://daily-bulletin/2026-08-07"}],
    )
    _write(tmp_path, "outputs/cme_options/2026-08-07/options_analysis.json", payload)

    result = load_cme_options_artifact(storage_root=tmp_path, trade_date=TRADE_DATE, decision_as_of=AS_OF)

    assert result.status == "available"
    assert result.input_snapshot_ids == {}


def test_same_priority_valid_candidates_are_blocked_deterministically(tmp_path: Path) -> None:
    _write(tmp_path, "features/cme/2026-08-07/run-a/options_analysis.json")
    _write(tmp_path, "features/cme/2026-08-07/run-z/options_analysis.json", _payload(run_id="run-z"))

    result = load_cme_options_artifact(storage_root=tmp_path, trade_date=TRADE_DATE, decision_as_of=AS_OF)

    assert (result.status, result.reason_code, result.artifact_path) == (
        "blocked",
        "cme_options_artifact_ambiguous",
        None,
    )


@pytest.mark.parametrize(
    ("relative", "payload"),
    [
        ("outputs/cme/2026-08-06/run-a/options_analysis.json", _payload()),
        ("outputs/cme/2026-08-07/run-a/options_analysis.json", _payload(trade_date="2026-08-06")),
        ("outputs/cme/2026-08-07/run-a/options_analysis.json", _payload(generated_at="2026-08-08T00:00:00+00:00")),
        ("outputs/cme/2026-08-07/run-a/options_analysis.json", _payload(generated_at="2026-08-07T20:00:00")),
        ("outputs/cme/2026-08-07/run-a/options_analysis.json", _payload(data_source={"status": "FINAL"})),
        (
            "outputs/cme/2026-08-07/run-a/options_analysis.json",
            _payload(
                data_source={
                    **_payload()["data_source"],
                    "source_url": "https://example.com/not-cme.pdf",
                }
            ),
        ),
        ("outputs/cme/2026-08-07/run-a/options_analysis.json", _payload(run_id="")),
    ],
)
def test_rejects_cross_day_and_invalid_contracts(tmp_path: Path, relative: str, payload: dict) -> None:
    _write(tmp_path, relative, payload)

    result = load_cme_options_artifact(storage_root=tmp_path, trade_date=TRADE_DATE, decision_as_of=AS_OF)

    assert (result.status, result.reason_code, result.payload) == (
        "unavailable",
        "cme_options_artifact_invalid" if "2026-08-07" in relative else "cme_options_artifact_missing",
        None,
    )


def test_rejects_symlink_candidate(tmp_path: Path) -> None:
    target = _write(tmp_path, "outside/options_analysis.json")
    link = tmp_path / "features/cme/2026-08-07/run-a/options_analysis.json"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)

    result = load_cme_options_artifact(storage_root=tmp_path, trade_date=TRADE_DATE, decision_as_of=AS_OF)

    assert (result.status, result.reason_code) == ("unavailable", "cme_options_artifact_invalid")


def test_requires_aware_decision_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        load_cme_options_artifact(
            storage_root=tmp_path,
            trade_date=TRADE_DATE,
            decision_as_of=datetime(2026, 8, 7, 23),
        )


def test_rejects_a_decision_time_from_another_session(tmp_path: Path) -> None:
    _write(tmp_path, "features/cme/2026-08-07/run-a/options_analysis.json")

    result = load_cme_options_artifact(
        storage_root=tmp_path,
        trade_date=TRADE_DATE,
        decision_as_of=datetime(2026, 8, 8, 1, tzinfo=timezone.utc),
    )

    assert (result.status, result.reason_code) == (
        "blocked",
        "cme_options_decision_session_mismatch",
    )


def test_shared_runtime_preparer_is_deterministic_for_both_daily_close_entries(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).parents[1] / "fixtures/gold_policy/readiness_v2/ready.json"
    feature_payload = json.loads(fixture.read_text(encoding="utf-8"))["input"]
    feature_payload = json.loads(json.dumps(feature_payload).replace("2025-01-17", "2026-07-29"))
    current = build_feature_snapshot(feature_payload)
    path = tmp_path / "features/cme/2026-07-29/shared/options_analysis.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_options_output()), encoding="utf-8")

    first = prepare_gold_policy_formal_options_inputs(
        storage_root=tmp_path,
        current=current,
        decision_as_of=current.as_of,
    )
    second = prepare_gold_policy_formal_options_inputs(
        storage_root=tmp_path,
        current=current,
        decision_as_of=current.as_of,
    )

    assert first.snapshot == second.snapshot
    assert first.summary() == second.summary()
    assert first.snapshot.source_snapshot_id == current.snapshot_id
    assert first.snapshot.quality_status == "accepted"
