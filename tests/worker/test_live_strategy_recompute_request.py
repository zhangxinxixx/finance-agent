from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.worker.live_strategy_recompute_request import execute_live_strategy_recompute_request
from apps.worker.recompute_result_store import RecomputeResultStore
from apps.analysis.strategy.recompute_execution import execute_strategy_recompute


ATTEMPTED_AT = datetime(2026, 7, 18, 9, 10, tzinfo=timezone.utc)


def _request(**overrides: object) -> dict:
    value = {
        "request_id": "request-1",
        "schema_name": "live_strategy_recompute_request",
        "schema_version": "live_strategy_recompute_request.v1",
        "requested_action": "recompute_live_strategy",
        "event_id": "fed:release:1",
        "event_hash": "event-hash-1",
        "observation_hash": "observation-hash-1",
        "source_key": "fed",
        "trade_date": "2026-07-18",
        "published_at": "2026-07-18T09:00:00Z",
        "evidence_level": "official",
        "quality_status": "allowed",
        "dispatch_status": "pending",
        "reason_codes": ["event_material"],
        "detected_at": "2026-07-18T09:01:00Z",
        "created_at": "2026-07-18T09:02:00Z",
        "source_refs": [{"source_ref": "fed:release:1"}],
        "raw_refs": [],
        "parsed_refs": [],
        "output_refs": [],
    }
    value.update(overrides)
    return value


def _event(event_id: str = "fed:release:1") -> dict:
    return {"event_id": event_id, "source_refs": [{"source_ref": event_id}]}


def _preview(**overrides: object) -> dict:
    previous = _strategy(strategy_id="xauusd-previous", price=2360.0)
    candidate = _strategy(strategy_id="xauusd-live", price=2362.0)
    candidate["event_overlay"] = {
        "schema_version": "live_strategy.event_overlay.v1",
        "status": "eligible",
        "event_id": "fed:release:1",
        "event_type": "fomc_statement",
        "observed_at": "2026-07-18T09:01:00Z",
        "recompute_candidate": True,
        "source_refs": [{"source_ref": "fed:release:1"}],
    }
    value = {
        "schema_version": "live_strategy.recompute_preview.v1",
        "status": "accepted",
        "event_id": "fed:release:1",
        "reasons": ["accepted:recompute_preview"],
        "event_observation": {
            "observation_id": "event-observation-1",
            "status": "available",
            "event_id": "fed:release:1",
            "source_refs": [{"source_ref": "market:xauusd:5m"}],
        },
        "previous_strategy": previous,
        "candidate_strategy": candidate,
        "execution": execute_strategy_recompute(previous, candidate),
    }
    value.update(overrides)
    return value


def _strategy(*, strategy_id: str, price: float) -> dict:
    return {
        "schema_version": "live_strategy.v1",
        "status": "available",
        "asset": "XAUUSD",
        "strategy_id": strategy_id,
        "strategy_version": "v1",
        "updated_at": "2026-07-18T09:05:00Z",
        "live_market": {"status": "available", "price": price},
        "data_quality": {"canonical_candle": {"status": "available"}},
        "market_state": {"nearest_level": {"value": price}},
        "event_overlay": {"status": "unavailable", "recompute_candidate": False},
    }


def test_blocked_and_unresolved_never_call_preview_or_history(tmp_path: Path) -> None:
    calls = 0

    def preview(_event_id: str) -> dict:
        nonlocal calls
        calls += 1
        return _preview()

    storage = tmp_path / "storage"
    result = execute_live_strategy_recompute_request(
        _request(dispatch_status="blocked"), [_event()], preview, storage_root=storage, attempted_at=ATTEMPTED_AT
    )

    assert calls == 0
    assert result["audit_status"] == "planned"
    assert result["result"]["attempt_status"] == "blocked"
    assert not storage.exists()


def test_read_only_accepted_preview_does_not_create_storage(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    result = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: _preview(), storage_root=storage, attempted_at=ATTEMPTED_AT
    )

    assert result["status"] == "planned"
    assert result["result"]["attempt_status"] == "accepted"
    assert result["result_artifact_ref"] is None
    assert not storage.exists()


def test_unavailable_preview_is_audited_without_history(tmp_path: Path) -> None:
    result = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: _preview(status="unavailable", reasons=["event_not_found"]),
        storage_root=tmp_path,
        attempted_at=ATTEMPTED_AT,
        write=True,
    )

    assert result["status"] == "unavailable"
    assert result["result"]["reason_codes"] == ["event_not_found"]
    assert result["audit_status"] == "persisted"
    assert result["history_status"] == "not_applicable"
    assert not (tmp_path / "strategy_history").exists()
    assert (tmp_path / result["result_artifact_ref"]).is_file()


def test_accepted_preview_writes_history_and_exact_replay_is_unchanged(tmp_path: Path) -> None:
    first = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: _preview(), storage_root=tmp_path, attempted_at=ATTEMPTED_AT, write=True
    )
    second = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: _preview(), storage_root=tmp_path, attempted_at=ATTEMPTED_AT, write=True
    )

    assert first["status"] == "accepted"
    assert second["status"] == "unchanged"
    assert second["audit_status"] == "unchanged"
    assert first["result"]["result_id"] == second["result"]["result_id"]
    assert (tmp_path / "strategy_history/XAUUSD/2026-07-18/xauusd-live/v1.json").is_file()


def test_invalid_accepted_preview_cannot_write_history(tmp_path: Path) -> None:
    bad = _preview()
    bad["execution"] = {"status": "accepted", "recompute": {"accepted": True}}

    result = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: bad, storage_root=tmp_path, attempted_at=ATTEMPTED_AT, write=True
    )

    assert result["status"] == "failed"
    assert result["result"]["reason_codes"] == ["accepted_preview_contract_invalid"]
    assert not (tmp_path / "strategy_history").exists()


def test_history_unsafe_strategy_identity_fails_accepted_preview_dry_run(tmp_path: Path) -> None:
    bad = _preview()
    bad["candidate_strategy"]["strategy_id"] = "bad:version"
    storage = tmp_path / "storage"

    result = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: bad, storage_root=storage, attempted_at=ATTEMPTED_AT
    )

    assert result["status"] == "planned"
    assert result["result"]["attempt_status"] == "failed"
    assert result["result"]["reason_codes"] == ["accepted_preview_contract_invalid"]
    assert not storage.exists()


def test_forged_accepted_recompute_cannot_write_history(tmp_path: Path) -> None:
    bad = _preview()
    bad["execution"]["recompute"] = {"accepted": True, "recompute_id": "recompute-forged"}

    result = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: bad, storage_root=tmp_path, attempted_at=ATTEMPTED_AT, write=True
    )

    assert result["status"] == "failed"
    assert result["result"]["reason_codes"] == ["accepted_preview_contract_invalid"]
    assert not (tmp_path / "strategy_history").exists()


def test_candidate_overlay_event_must_match_resolved_event(tmp_path: Path) -> None:
    bad = _preview()
    bad["candidate_strategy"]["event_overlay"]["event_id"] = "fed:other:1"

    result = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: bad, storage_root=tmp_path, attempted_at=ATTEMPTED_AT, write=True
    )

    assert result["status"] == "failed"
    assert not (tmp_path / "strategy_history").exists()


def test_execution_to_ref_must_match_candidate(tmp_path: Path) -> None:
    bad = _preview()
    bad["execution"]["to_ref"] = {"strategy_id": "other", "strategy_version": "v1"}

    result = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: bad, storage_root=tmp_path, attempted_at=ATTEMPTED_AT, write=True
    )

    assert result["status"] == "failed"
    assert not (tmp_path / "strategy_history").exists()


def test_forged_execution_id_cannot_write_history(tmp_path: Path) -> None:
    bad = _preview()
    bad["execution"]["execution_id"] = "execution-forged"

    result = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: bad, storage_root=tmp_path, attempted_at=ATTEMPTED_AT, write=True
    )

    assert result["status"] == "failed"
    assert result["result"]["reason_codes"] == ["accepted_preview_contract_invalid"]
    assert not (tmp_path / "strategy_history").exists()


def test_accepted_preview_binds_previous_candidate_and_recompute(tmp_path: Path) -> None:
    preview = _preview()
    result = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: deepcopy(preview), storage_root=tmp_path, attempted_at=ATTEMPTED_AT, write=True
    )

    assert result["status"] == "accepted"
    assert result["result"]["preview_ref"]["payload_sha256"]
    assert result["result"]["recompute_ref"]["recompute_id"] == preview["execution"]["recompute"]["recompute_id"]


@pytest.mark.parametrize("status", ["blocked", "unavailable"])
def test_preview_unsafe_reasons_are_not_copied_to_audit(tmp_path: Path, status: str) -> None:
    result = execute_live_strategy_recompute_request(
        _request(),
        [_event()],
        lambda _event_id: _preview(status=status, reasons=[f"/secret/{'x' * 200}", "unsafe reason text"]),
        storage_root=tmp_path,
        attempted_at=ATTEMPTED_AT,
        write=True,
    )

    assert result["result"]["reason_codes"] == [f"preview_{status}"]
    assert "/secret" not in str(result["result"])


@pytest.mark.parametrize(
    ("status", "reason"),
    [("blocked", "observed_market_reaction_required"), ("unavailable", "event_not_found")],
)
def test_runtime_preview_reasons_are_preserved_in_audit(tmp_path: Path, status: str, reason: str) -> None:
    result = execute_live_strategy_recompute_request(
        _request(),
        [_event()],
        lambda _event_id: _preview(status=status, reasons=[reason]),
        storage_root=tmp_path,
        attempted_at=ATTEMPTED_AT,
        write=True,
    )

    assert result["result"]["reason_codes"] == [reason]


def test_history_failure_is_a_failed_audit_without_exception_text(tmp_path: Path) -> None:
    class BrokenHistoryStore:
        def write(self, _candidate: dict) -> object:
            raise RuntimeError(f"secret path {tmp_path}")

    result = execute_live_strategy_recompute_request(
        _request(),
        [_event()],
        lambda _event_id: _preview(),
        storage_root=tmp_path,
        attempted_at=ATTEMPTED_AT,
        write=True,
        history_store_factory=lambda _root: BrokenHistoryStore(),  # type: ignore[return-value]
    )

    assert result["status"] == "failed"
    assert result["result"]["reason_codes"] == ["strategy_history_write_failed"]
    assert str(tmp_path) not in str(result)


def test_result_store_error_propagates(tmp_path: Path) -> None:
    class BrokenResultStore:
        def write(self, _attempt: dict) -> object:
            raise OSError("audit unavailable")

    with pytest.raises(OSError, match="audit unavailable"):
        execute_live_strategy_recompute_request(
            _request(),
            [_event()],
            lambda _event_id: _preview(status="blocked", reasons=["candidate_unavailable"]),
            storage_root=tmp_path,
            attempted_at=ATTEMPTED_AT,
            write=True,
            result_store_factory=lambda _root: BrokenResultStore(),  # type: ignore[return-value]
        )


def test_later_attempt_timestamp_produces_a_new_result_version(tmp_path: Path) -> None:
    first = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: _preview(status="blocked", reasons=["candidate_unavailable"]),
        storage_root=tmp_path,
        attempted_at=ATTEMPTED_AT,
        write=True,
    )
    later = execute_live_strategy_recompute_request(
        _request(), [_event()], lambda _event_id: _preview(status="blocked", reasons=["candidate_unavailable"]),
        storage_root=tmp_path,
        attempted_at=datetime(2026, 7, 18, 9, 11, tzinfo=timezone.utc),
        write=True,
    )

    assert first["result"]["result_id"] != later["result"]["result_id"]
    assert RecomputeResultStore(tmp_path).read(first["result"])["attempted_at"] == "2026-07-18T09:10:00Z"
