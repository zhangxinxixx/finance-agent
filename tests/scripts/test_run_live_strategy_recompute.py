from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.analysis.strategy.history_store import StrategyHistoryStore
from scripts import run_live_strategy_recompute as cli


class _Session:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _candidate() -> dict:
    return {
        "schema_version": "live_strategy.v1",
        "status": "available",
        "asset": "XAUUSD",
        "strategy_id": "live-event-1",
        "strategy_version": "live_strategy.rules.v2",
        "updated_at": "2026-07-18T09:05:00Z",
        "strategy_status": "WATCHING",
        "live_market": {"status": "available"},
        "data_quality": {"canonical_candle": {"status": "available"}},
    }


def _preview(*, status: str = "accepted") -> dict:
    return {
        "schema_version": "live_strategy.recompute_preview.v1",
        "status": status,
        "event_id": "fed:release:1",
        "reasons": ["accepted:recompute_preview"] if status == "accepted" else ["event_not_ready"],
        "candidate_strategy": _candidate() if status == "accepted" else None,
        "execution": (
            {
                "schema_version": "live_strategy.recompute_execution.v1",
                "status": "accepted",
                "execution_id": "execution-1",
                "recompute": {"accepted": True, "recompute_id": "recompute-1"},
            }
            if status == "accepted"
            else None
        ),
    }


def test_default_dry_run_passes_inputs_and_does_not_write(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    session = _Session()
    calls: list[dict] = []

    def loader(**kwargs):
        calls.append(kwargs)
        return _preview()

    summary = cli.freeze_live_strategy_recompute(
        event_id="fed:release:1",
        as_of=datetime(2026, 7, 18, 9, 5, tzinfo=timezone.utc),
        storage_root=tmp_path,
        session_factory=lambda: session,
        preview_loader=loader,
    )

    assert summary == {
        "status": "dry-run",
        "event_id": "fed:release:1",
        "as_of": "2026-07-18T09:05:00+00:00",
        "dry_run": True,
        "write_requested": False,
        "write_performed": False,
        "strategy_id": "live-event-1",
        "strategy_version": "live_strategy.rules.v2",
        "execution_id": "execution-1",
        "recompute_id": "recompute-1",
        "target_ref": "strategy_history/XAUUSD/2026-07-18/live-event-1/live_strategy.rules.v2.json",
        "artifact_ref": None,
        "created": None,
    }
    assert calls == [
        {
            "event_id": "fed:release:1",
            "db": session,
            "now": datetime(2026, 7, 18, 9, 5, tzinfo=timezone.utc),
            "storage_root": tmp_path,
        }
    ]
    assert session.closed is True
    assert not (tmp_path / "strategy_history").exists()


def test_accepted_write_and_replay_are_idempotent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    kwargs = {
        "event_id": "fed:release:1",
        "storage_root": tmp_path,
        "write": True,
        "session_factory": _Session,
        "preview_loader": lambda **_: _preview(),
    }

    first = cli.freeze_live_strategy_recompute(**kwargs)
    second = cli.freeze_live_strategy_recompute(**kwargs)

    assert first["status"] == "written"
    assert first["created"] is True
    assert second["status"] == "unchanged"
    assert second["created"] is False
    assert first["artifact_ref"] == second["artifact_ref"]
    assert first["execution_id"] == "execution-1"
    assert first["recompute_id"] == "recompute-1"
    assert len(list((tmp_path / "strategy_history").rglob("*.json"))) == 1


@pytest.mark.parametrize("source_status", ["blocked", "unavailable"])
def test_blocked_or_unavailable_write_is_skipped_without_directory(
    monkeypatch, tmp_path: Path, source_status: str
) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)

    summary = cli.freeze_live_strategy_recompute(
        event_id="fed:release:1",
        storage_root=tmp_path,
        write=True,
        session_factory=_Session,
        preview_loader=lambda **_: _preview(status=source_status),
    )

    assert summary == {
        "status": "skipped",
        "source_status": source_status,
        "event_id": "fed:release:1",
        "reasons": ["event_not_ready"],
        "dry_run": False,
        "write_requested": True,
        "write_performed": False,
    }
    assert list(tmp_path.iterdir()) == []


def test_session_is_closed_when_preview_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    session = _Session()

    def loader(**_):
        raise RuntimeError("sensitive /secret/source")

    with pytest.raises(cli.RecomputePreviewError, match="recompute_preview_failed"):
        cli.freeze_live_strategy_recompute(
            event_id="fed:release:1",
            storage_root=tmp_path,
            session_factory=lambda: session,
            preview_loader=loader,
        )
    assert session.closed is True


def test_main_defaults_to_dry_run_and_explicit_dry_run_matches(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(cli, "SessionLocal", _Session)
    monkeypatch.setattr(cli, "preview_live_strategy_recompute", lambda **_: _preview())
    args = ["--event-id", "fed:release:1", "--storage-root", str(tmp_path)]

    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry-run"
    assert cli.main([*args, "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry-run"
    assert not (tmp_path / "strategy_history").exists()


def test_write_and_dry_run_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(["--event-id", "fed:release:1", "--write", "--dry-run"])
    assert exc_info.value.code == 2


def test_event_id_is_required() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args([])
    assert exc_info.value.code == 2


@pytest.mark.parametrize("event_id", ["", "../secret", "event/secret", "a" * 129, "事件:1"])
def test_invalid_event_id_has_fixed_nonzero_error(monkeypatch, tmp_path: Path, capsys, event_id: str) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    result = cli.main(["--event-id", event_id, "--storage-root", str(tmp_path)])
    captured = capsys.readouterr()
    assert result == 2
    assert json.loads(captured.err) == {"status": "error", "error": "invalid_event_id"}
    assert "secret" not in captured.err


@pytest.mark.parametrize("as_of", ["2026-07-18", "not-a-date"])
def test_invalid_as_of_has_fixed_nonzero_error(monkeypatch, tmp_path: Path, capsys, as_of: str) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    result = cli.main(["--event-id", "fed:release:1", "--as-of", as_of, "--storage-root", str(tmp_path)])
    assert result == 2
    assert json.loads(capsys.readouterr().err) == {"status": "error", "error": "invalid_as_of"}


def test_storage_escape_has_fixed_nonzero_error(capsys) -> None:
    result = cli.main(["--event-id", "fed:release:1", "--storage-root", "/tmp/secret"])
    captured = capsys.readouterr()
    assert result == 2
    assert json.loads(captured.err) == {"status": "error", "error": "invalid_storage_root"}
    assert "secret" not in captured.err


def test_preview_failure_has_fixed_nonzero_error(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(cli, "SessionLocal", _Session)

    def loader(**_):
        raise RuntimeError("sensitive /secret/source")

    monkeypatch.setattr(cli, "preview_live_strategy_recompute", loader)
    result = cli.main(["--event-id", "fed:release:1", "--storage-root", str(tmp_path)])
    captured = capsys.readouterr()
    assert result == 1
    assert json.loads(captured.err) == {"status": "error", "error": "recompute_preview_failed"}
    assert "secret" not in captured.err


def test_conflict_has_fixed_nonzero_error(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(cli, "SessionLocal", _Session)
    StrategyHistoryStore(tmp_path).write(_candidate())
    changed = _preview()
    changed["candidate_strategy"] = {**_candidate(), "strategy_status": "ARMED"}
    monkeypatch.setattr(cli, "preview_live_strategy_recompute", lambda **_: changed)

    result = cli.main(["--event-id", "fed:release:1", "--storage-root", str(tmp_path), "--write"])
    assert result == 1
    assert json.loads(capsys.readouterr().err) == {
        "status": "error",
        "error": "strategy_history_conflict",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": "live_strategy.v0"},
        {"strategy_status": "SUSPENDED_DATA"},
        {"live_market": {"status": "stale"}},
        {"data_quality": {"canonical_candle": {"status": "stale"}}},
    ],
)
def test_accepted_preview_with_invalid_candidate_is_rejected_without_write(
    monkeypatch, tmp_path: Path, mutation: dict
) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    preview = _preview()
    preview["candidate_strategy"] = {**_candidate(), **mutation}

    with pytest.raises(cli.RecomputePreviewContractError, match="invalid_candidate_strategy"):
        cli.freeze_live_strategy_recompute(
            event_id="fed:release:1",
            storage_root=tmp_path,
            write=True,
            session_factory=_Session,
            preview_loader=lambda **_: preview,
        )

    assert not (tmp_path / "strategy_history").exists()
