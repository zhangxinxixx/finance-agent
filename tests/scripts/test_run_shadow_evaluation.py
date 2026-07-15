from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

from scripts import run_shadow_evaluation as cli


AS_OF = datetime(2026, 7, 17, 12, tzinfo=UTC)


def _live(*, approved: bool = False) -> dict[str, object]:
    return {
        "schema_version": "live_strategy.v1",
        "status": "available" if approved else "partial",
        "strategy_id": "live-1",
        "strategy_version": "live_strategy.rules.v2",
        "asset": "XAUUSD",
        "strategy_status": "WAITING" if approved else "SUSPENDED_DATA",
        "baseline": {
            "run_id": "run-1",
            "trade_date": "2026-07-17",
            "bias": "bullish",
        },
        "live_market": {"status": "available" if approved else "stale", "price": 2400.0},
        "market_state": {"key_levels": []},
        "feasibility": {},
        "setups": [],
        "no_trade": {},
        "source_refs": [{"source": "canonical_5m", "status": "ok"}],
        "artifact_refs": [],
        "data_quality": {
            "canonical_candle": {"status": "available" if approved else "stale"},
            "warnings": [] if approved else ["canonical_candle_stale"],
        },
    }


def _market(*, complete: bool = False) -> dict[str, object]:
    points = [AS_OF + timedelta(minutes=5)]
    if complete:
        points.extend(
            [
                AS_OF + timedelta(hours=1),
                AS_OF + timedelta(hours=4),
                datetime.combine(AS_OF.date(), time.max, tzinfo=UTC),
                AS_OF + timedelta(hours=24),
            ]
        )
    return {
        "candles": [
            {
                "time": point.isoformat(),
                "high": 2401.0,
                "low": 2399.0,
                "close": 2400.5,
                "partial": False,
            }
            for point in points
        ]
    }


def _run_kwargs(tmp_path: Path, *, approved: bool = False) -> dict[str, object]:
    return {
        "trade_date": "2026-07-17",
        "as_of": AS_OF,
        "evaluated_at": AS_OF,
        "storage_root": tmp_path,
        "live_output": _live(approved=approved),
        "market_candles": _market(),
    }


def test_blocked_snapshot_writes_all_horizons_immediately_and_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    kwargs = _run_kwargs(tmp_path)

    dry = cli.run_shadow_evaluation(**kwargs)
    assert dry["dry_run"] is True
    assert dry["snapshot_write_performed"] is False
    assert all(item["maturity_status"] == "persistable" for item in dry["outcomes"].values())
    assert all(item["status"] == "blocked" for item in dry["outcomes"].values())
    assert all(item["classification"] == "blocked" for item in dry["outcomes"].values())
    assert all(item["write_performed"] is False for item in dry["outcomes"].values())
    assert all(item["path"] is not None for item in dry["outcomes"].values())
    assert not (tmp_path / "evaluation").exists()

    written = cli.run_shadow_evaluation(**kwargs, write=True)
    replay = cli.run_shadow_evaluation(**kwargs, write=True)

    assert written["snapshot_created"] is True
    assert replay["snapshot_created"] is False
    assert replay["evaluation_id"] == written["evaluation_id"]
    assert all(item["write_performed"] is True for item in written["outcomes"].values())
    assert all(item["created"] is True for item in written["outcomes"].values())
    assert all(item["created"] is False for item in replay["outcomes"].values())
    assert len(list((tmp_path / "evaluation").rglob("strategy_snapshot.json"))) == 1
    assert len(list((tmp_path / "evaluation").rglob("outcomes/*.json"))) == 4


def test_approved_immature_horizons_have_no_outcome_or_path(tmp_path: Path) -> None:
    summary = cli.run_shadow_evaluation(**_run_kwargs(tmp_path, approved=True), write=True)

    assert summary["snapshot_write_performed"] is True
    assert all(item["maturity_status"] == "pending" for item in summary["outcomes"].values())
    assert all(item["status"] is None for item in summary["outcomes"].values())
    assert all(item["classification"] is None for item in summary["outcomes"].values())
    assert all(item["write_performed"] is False for item in summary["outcomes"].values())
    assert all(item["path"] is None for item in summary["outcomes"].values())
    assert not list((tmp_path / "evaluation").rglob("outcomes/*.json"))


def test_retryable_candle_gap_stays_pending_then_later_complete_data_is_scored(
    tmp_path: Path,
) -> None:
    kwargs = _run_kwargs(tmp_path, approved=True) | {
        "evaluated_at": AS_OF + timedelta(hours=1),
        "write": True,
    }
    pending = cli.run_shadow_evaluation(**kwargs)

    one_hour = pending["outcomes"]["1h"]
    assert one_hour["maturity_status"] == "pending"
    assert one_hour["status"] == "unscorable"
    assert one_hour["classification"] == "unscorable"
    assert one_hour["maturity_reasons"] == ["horizon_data_incomplete"]
    assert one_hour["write_performed"] is False
    assert one_hour["path"] is None
    assert not list((tmp_path / "evaluation").rglob("outcomes/*.json"))

    scored = cli.run_shadow_evaluation(**(kwargs | {"market_candles": _market(complete=True)}))
    one_hour = scored["outcomes"]["1h"]
    assert scored["snapshot_created"] is False
    assert one_hour["maturity_status"] == "persistable"
    assert one_hour["status"] == "scored"
    assert one_hour["classification"] == "hold"
    assert one_hour["write_performed"] is True
    assert one_hour["created"] is True
    assert one_hour["path"].endswith("/outcomes/1h.json")
    assert len(list((tmp_path / "evaluation").rglob("outcomes/*.json"))) == 1


def test_now_alias_controls_maturity_and_conflicts_with_evaluated_at(tmp_path: Path) -> None:
    kwargs = _run_kwargs(tmp_path, approved=True)
    kwargs.pop("evaluated_at")
    kwargs["market_candles"] = _market(complete=True)
    summary = cli.run_shadow_evaluation(
        **kwargs,
        now=AS_OF + timedelta(hours=1),
    )
    assert summary["evaluated_at"] == "2026-07-17T13:00:00+00:00"
    assert summary["outcomes"]["1h"]["maturity_status"] == "persistable"

    with pytest.raises(ValueError, match="only one"):
        cli.run_shadow_evaluation(
            **kwargs,
            evaluated_at=AS_OF,
            now=AS_OF,
        )


@pytest.mark.parametrize("field", ["as_of", "evaluated_at"])
def test_programmatic_naive_timestamp_is_rejected(tmp_path: Path, field: str) -> None:
    kwargs = _run_kwargs(tmp_path)
    kwargs[field] = datetime(2026, 7, 17, 12)
    with pytest.raises(ValueError, match=f"{field} must include a timezone"):
        cli.run_shadow_evaluation(**kwargs)


def test_runtime_session_closes_when_maturity_evaluation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Session:
        closed = False

        def close(self) -> None:
            self.closed = True

    session = Session()
    monkeypatch.setattr(
        cli,
        "_load_runtime_inputs",
        lambda **_: (_live(), _market(), session),
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("maturity failed")

    monkeypatch.setattr(cli, "_run_shadow_evaluation", fail)
    with pytest.raises(RuntimeError, match="maturity failed"):
        cli.run_shadow_evaluation(
            trade_date="2026-07-17",
            as_of=AS_OF,
            evaluated_at=AS_OF,
            storage_root=tmp_path,
        )
    assert session.closed is True


def test_wrapper_loads_runtime_inputs_sets_database_url_and_closes_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Session:
        closed = False

        def close(self) -> None:
            self.closed = True

    session = Session()
    captured = {}
    monkeypatch.setattr(
        cli,
        "_load_runtime_inputs",
        lambda **_: (_live(), _market(), session),
    )

    def run(**kwargs):
        captured.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(cli, "_run_shadow_evaluation", run)
    summary = cli.run_shadow_evaluation(
        trade_date="2026-07-17",
        as_of=AS_OF,
        evaluated_at=AS_OF,
        storage_root=tmp_path,
        database_url="postgresql://runtime",
    )

    assert summary == {"status": "ok"}
    assert captured["live_output"] == _live()
    assert captured["market_candles"] == _market()
    assert captured["write"] is False
    assert cli.os.environ["DATABASE_URL"] == "postgresql://runtime"
    assert session.closed is True


def test_cli_passes_distinct_snapshot_and_maturity_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = {}
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)

    def run(**kwargs):
        captured.update(kwargs)
        return {"status": "ok"}

    monkeypatch.setattr(cli, "run_shadow_evaluation", run)
    assert (
        cli.main(
            [
                "--date",
                "2026-07-17",
                "--as-of",
                "2026-07-17T12:00:00+08:00",
                "--evaluated-at",
                "2026-07-18T01:00:00+08:00",
                "--storage-root",
                str(tmp_path),
                "--write",
            ]
        )
        == 0
    )
    assert captured["as_of"] == datetime(2026, 7, 17, 4, tzinfo=UTC)
    assert captured["evaluated_at"] == datetime(2026, 7, 17, 17, tzinfo=UTC)
    assert captured["write"] is True


@pytest.mark.parametrize("argument", ["--as-of", "--evaluated-at"])
@pytest.mark.parametrize("value", ["2026-07-18", "not-a-date"])
def test_cli_rejects_naive_or_invalid_timestamps(argument: str, value: str) -> None:
    with pytest.raises(SystemExit, match=argument):
        cli.main(["--date", "2026-07-17", argument, value])


def test_cli_rejects_storage_escape_without_leaking_allowed_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--date", "2026-07-17", "--storage-root", "/tmp/outside"])
    message = str(exc_info.value)
    assert "storage-root" in message
    assert str(tmp_path) not in message


def test_storage_root_rejects_symlink_component(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "storage"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = allowed / "link"
    link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(cli, "_DEFAULT_STORAGE_ROOT", allowed)

    with pytest.raises(SystemExit, match="safe directory"):
        cli._validate_storage_root(link / "child")


def test_cli_rejects_invalid_date() -> None:
    with pytest.raises(SystemExit, match="YYYY-MM-DD"):
        cli.main(["--date", "2026-7-17"])
