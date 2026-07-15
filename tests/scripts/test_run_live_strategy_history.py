from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.analysis.strategy.history_store import StrategyHistoryConflictError, StrategyHistoryStore
from scripts import run_live_strategy_history as cli


def _payload(*, strategy_version: str = "live_strategy.rules.v2") -> dict:
    return {
        "schema_version": "live_strategy.v1",
        "asset": "XAUUSD",
        "strategy_id": "live-strategy-test",
        "strategy_version": strategy_version,
        "updated_at": "2026-07-18T01:02:03Z",
        "strategy_status": "WAITING",
        "live_market": {"status": "available"},
        "data_quality": {"canonical_candle": {"status": "available"}},
    }


class _Session:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_dry_run_loads_service_and_does_not_write(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    session = _Session()
    calls: list[dict] = []

    def loader(**kwargs):
        calls.append(kwargs)
        return _payload()

    summary = cli.freeze_live_strategy(
        storage_root=tmp_path,
        as_of=datetime(2026, 7, 18, tzinfo=timezone.utc),
        session_factory=lambda: session,
        live_strategy_loader=loader,
    )

    assert summary["dry_run"] is True
    assert summary["created"] is None
    assert summary["target_ref"].endswith("live_strategy.rules.v2.json")
    assert calls[0]["asset"] == "XAUUSD"
    assert calls[0]["now"].isoformat() == "2026-07-18T00:00:00+00:00"
    assert session.closed is True
    assert not (tmp_path / "strategy_history").exists()


def test_write_and_replay_are_idempotent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    kwargs = {
        "storage_root": tmp_path,
        "session_factory": _Session,
        "live_strategy_loader": lambda **_: _payload(),
        "write": True,
    }
    first = cli.freeze_live_strategy(**kwargs)
    second = cli.freeze_live_strategy(**kwargs)
    assert first["created"] is True
    assert second["created"] is False
    assert len(list((tmp_path / "strategy_history").rglob("*.json"))) == 1


@pytest.mark.parametrize(
    ("mutations", "expected_reason"),
    [
        ({"live_market": {"status": "stale"}, "data_quality": {"canonical_candle": {"status": "stale"}}}, "canonical_market_unavailable"),
        ({"strategy_status": "SUSPENDED_DATA"}, "strategy_suspended_data"),
    ],
)
@pytest.mark.parametrize("write", [False, True])
def test_history_gate_skips_stale_or_suspended_without_writing(
    monkeypatch, tmp_path: Path, mutations: dict, expected_reason: str, write: bool
) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    payload = _payload() | mutations
    summary = cli.freeze_live_strategy(
        storage_root=tmp_path,
        write=write,
        session_factory=_Session,
        live_strategy_loader=lambda **_: payload,
    )
    assert summary["status"] == "skipped"
    assert expected_reason in summary["reasons"]
    assert not (tmp_path / "strategy_history").exists()


def test_conflicting_immutable_version_raises(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    store = StrategyHistoryStore(tmp_path)
    store.write(_payload())
    with pytest.raises(StrategyHistoryConflictError):
        cli.freeze_live_strategy(
            storage_root=tmp_path,
            write=True,
            session_factory=_Session,
            live_strategy_loader=lambda **_: _payload(strategy_version="live_strategy.rules.v2") | {"strategy_status": "ARMED"},
        )


@pytest.mark.parametrize("asset", ["GC", "", "XAUUSD/evil"])
def test_invalid_asset_returns_nonzero(capsys, asset: str) -> None:
    assert cli.main(["--asset", asset]) == 1
    assert "asset" in capsys.readouterr().err


@pytest.mark.parametrize("as_of", ["2026-07-18", "not-a-date"])
def test_invalid_as_of_returns_nonzero(capsys, as_of: str) -> None:
    assert cli.main(["--as-of", as_of]) == 1
    assert "as-of" in capsys.readouterr().err


def test_default_and_explicit_dry_run_do_not_write(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(cli, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(cli, "get_live_strategy_latest", lambda **_: _payload())

    assert cli.main([]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert cli.main(["--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert not (tmp_path / "strategy_history").exists()


def test_write_and_dry_run_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(["--write", "--dry-run"])
    assert exc_info.value.code == 2


def test_main_service_failure_returns_nonzero(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(cli, "SessionLocal", lambda: _Session())

    def loader(**_):
        raise RuntimeError("service unavailable")

    monkeypatch.setattr(cli, "get_live_strategy_latest", loader)
    assert cli.main([]) == 1
    assert "service unavailable" in capsys.readouterr().err


def test_storage_root_rejects_escape_and_symlink(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        cli._validate_storage_root(Path("/tmp"))
    link = cli._DEFAULT_STORAGE_ROOT / "_cli-test-link"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
        with pytest.raises(ValueError):
            cli._validate_storage_root(link)
    finally:
        link.unlink(missing_ok=True)


def test_main_write_prints_json_summary(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(cli, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(cli, "get_live_strategy_latest", lambda **_: _payload())
    assert cli.main(["--storage-root", str(tmp_path), "--write"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] is False
    assert summary["created"] is True
