from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.parsers.macro.models import CollectorResult, MacroPoint
import scripts.backfill_macro as backfill_macro


class _FakeRecorder:
    def __init__(self, events: list[dict[str, object]], *, task_type: str, task_name: str, trade_date: str | None) -> None:
        self._events = events
        self._record = {
            "task_type": task_type,
            "task_name": task_name,
            "trade_date": trade_date,
            "steps": [],
        }

    def __enter__(self):
        self._events.append(self._record)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def step(self, step_name: str, **kwargs):
        self._record["steps"].append({"step_name": step_name, **kwargs})
        return f"step-{step_name}"


def _fake_record_task_factory(events: list[dict[str, object]]):
    def _factory(task_type: str, task_name: str, trade_date: str | None = None):
        return _FakeRecorder(events, task_type=task_type, task_name=task_name, trade_date=trade_date)

    return _factory


def test_backfill_macro_marks_fred_unavailable_without_fixture_fallback(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "storage" / "features" / "macro" / "2026-05-06" / "run-a"
    report_dir = tmp_path / "storage" / "outputs" / "macro" / "2026-05-06" / "run-a"

    with (
        patch("scripts.backfill_macro.Path.read_text", side_effect=AssertionError("fixture fallback must not read tests/fixtures")),
        patch("scripts.backfill_macro.collect_fred_series", side_effect=RuntimeError("fred API timeout")),
        patch(
            "scripts.backfill_macro.collect_fed_series",
            return_value=CollectorResult(points=[], unavailable_symbols=[], source_refs=[]),
        ),
        patch(
            "scripts.backfill_macro.collect_treasury_series",
            return_value=CollectorResult(points=[], unavailable_symbols=[], source_refs=[]),
        ),
    ):
        with patch.object(backfill_macro, "PROJECT_ROOT", tmp_path):
            argv = ["backfill_macro.py", "--date", "2026-05-06", "--run-id", "run-a", "--no-db"]
            with patch.object(sys, "argv", argv):
                backfill_macro.main()

    snapshot_json = snapshot_dir / "macro_snapshot.json"
    snapshot_md = report_dir / "macro_snapshot.md"
    assert snapshot_json.exists()
    assert snapshot_md.exists()

    payload = json.loads(snapshot_json.read_text(encoding="utf-8"))
    assert set(backfill_macro.FRED_SERIES).issubset(set(payload["unavailable_symbols"]))
    assert payload["source_refs"]["DGS10"]["reason"] == "FRED collector failed: RuntimeError: fred API timeout"
    assert payload["source_refs"]["DGS10"]["source_url"].endswith("series_id=DGS10&file_type=json&sort_order=asc")
    assert payload["source_refs"]["T10YIE"]["source_url"].endswith("series_id=T10YIE&file_type=json&sort_order=asc")


def test_backfill_macro_same_date_runs_keep_history(tmp_path: Path) -> None:
    first_snapshot_dir = tmp_path / "storage" / "features" / "macro" / "2026-05-06" / "run-a"
    first_report_dir = tmp_path / "storage" / "outputs" / "macro" / "2026-05-06" / "run-a"
    second_snapshot_dir = tmp_path / "storage" / "features" / "macro" / "2026-05-06" / "run-b"
    second_report_dir = tmp_path / "storage" / "outputs" / "macro" / "2026-05-06" / "run-b"

    with (
        patch("scripts.backfill_macro.collect_fred_series", side_effect=RuntimeError("fred API timeout")),
        patch(
            "scripts.backfill_macro.collect_fed_series",
            return_value=CollectorResult(points=[], unavailable_symbols=[], source_refs=[]),
        ),
        patch(
            "scripts.backfill_macro.collect_treasury_series",
            return_value=CollectorResult(points=[], unavailable_symbols=[], source_refs=[]),
        ),
        patch(
            "scripts.backfill_macro.collect_dxy_series",
            return_value=CollectorResult(points=[], unavailable_symbols=[], source_refs=[]),
        ),
    ):
        with patch.object(backfill_macro, "PROJECT_ROOT", tmp_path):
            for run_id in ("run-a", "run-b"):
                argv = ["backfill_macro.py", "--date", "2026-05-06", "--run-id", run_id, "--no-db"]
                with patch.object(sys, "argv", argv):
                    backfill_macro.main()

    first_snapshot_json = first_snapshot_dir / "macro_snapshot.json"
    first_snapshot_md = first_report_dir / "macro_snapshot.md"
    second_snapshot_json = second_snapshot_dir / "macro_snapshot.json"
    second_snapshot_md = second_report_dir / "macro_snapshot.md"

    assert first_snapshot_json.exists()
    assert first_snapshot_md.exists()
    assert second_snapshot_json.exists()
    assert second_snapshot_md.exists()
    assert first_snapshot_json != second_snapshot_json
    assert first_snapshot_md != second_snapshot_md
    assert first_snapshot_json.read_text(encoding="utf-8") == second_snapshot_json.read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_date", ["../../escape", "2026/05/06", "not-a-date"])
def test_backfill_macro_rejects_unsafe_dates(bad_date: str, tmp_path: Path) -> None:
    with patch.object(backfill_macro, "PROJECT_ROOT", tmp_path):
        argv = ["backfill_macro.py", "--date", bad_date, "--run-id", "run-a", "--no-db"]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit):
            backfill_macro.main()


def test_backfill_macro_rejects_unsafe_run_id(tmp_path: Path) -> None:
    with patch.object(backfill_macro, "PROJECT_ROOT", tmp_path):
        argv = ["backfill_macro.py", "--date", "2026-05-06", "--run-id", "..", "--no-db"]
        with patch.object(sys, "argv", argv), pytest.raises(ValueError):
            backfill_macro.main()


def test_backfill_macro_does_not_record_task_runs_without_flag(tmp_path: Path) -> None:
    record_events: list[dict[str, object]] = []
    collector_result = CollectorResult(points=[], unavailable_symbols=[], source_refs=[])

    with (
        patch("scripts.backfill_macro.record_task", side_effect=_fake_record_task_factory(record_events)),
        patch("scripts.backfill_macro.collect_fred_series", return_value=collector_result),
        patch("scripts.backfill_macro.collect_fed_series", return_value=collector_result),
        patch("scripts.backfill_macro.collect_treasury_series", return_value=collector_result),
        patch("scripts.backfill_macro.collect_dxy_series", return_value=collector_result),
    ):
        with patch.object(backfill_macro, "PROJECT_ROOT", tmp_path):
            argv = ["backfill_macro.py", "--date", "2026-05-06", "--run-id", "run-a", "--no-db"]
            with patch.object(sys, "argv", argv):
                backfill_macro.main()

    assert record_events == []


def test_backfill_macro_records_task_runs_when_flag_enabled(tmp_path: Path) -> None:
    record_events: list[dict[str, object]] = []
    collector_result = CollectorResult(points=[], unavailable_symbols=[], source_refs=[])

    with (
        patch("scripts.backfill_macro.record_task", side_effect=_fake_record_task_factory(record_events)),
        patch("scripts.backfill_macro.collect_fred_series", return_value=collector_result),
        patch("scripts.backfill_macro.collect_fed_series", return_value=collector_result),
        patch("scripts.backfill_macro.collect_treasury_series", return_value=collector_result),
        patch("scripts.backfill_macro.collect_dxy_series", return_value=collector_result),
    ):
        with patch.object(backfill_macro, "PROJECT_ROOT", tmp_path):
            argv = [
                "backfill_macro.py",
                "--date",
                "2026-05-06",
                "--run-id",
                "run-a",
                "--record-task-runs",
                "--no-db",
            ]
            with patch.object(sys, "argv", argv):
                backfill_macro.main()

    assert [event["task_type"] for event in record_events] == [
        "macro_collect",
        "macro_feature",
        "report_render",
    ]
    assert all(event["trade_date"] == "2026-05-06" for event in record_events)
    assert [event["steps"][0]["step_name"] for event in record_events] == [
        "macro_collect",
        "macro_feature",
        "report_render",
    ]


def test_persist_to_database_writes_normalized_points_and_features(tmp_path: Path) -> None:
    class _FakeSession:
        def __init__(self) -> None:
            self.committed = False
            self.rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    session = _FakeSession()
    point = MacroPoint(
        symbol="DGS10",
        date="2026-05-06",
        value=4.2,
        source="fred",
        source_url="https://example.test/fred",
        retrieved_at="2026-05-06T00:00:00+00:00",
        raw_path="raw/macro/fred/2026-05-06.json",
    )

    with (
        patch.object(backfill_macro, "SessionLocal", return_value=session),
        patch.object(backfill_macro, "ensure_analysis_tables") as ensure_tables,
        patch.object(backfill_macro, "persist_macro_points", return_value=(1, 1)) as persist_points,
        patch.object(backfill_macro, "persist_macro_feature_snapshots", return_value=2) as persist_features,
    ):
        result = backfill_macro._persist_to_database(
            enabled=True,
            storage_root=tmp_path / "storage",
            all_points=[point],
            source_refs=[{"symbol": "DGS10", "source": "fred", "raw_path": point.raw_path}],
            run_id="run-a",
            as_of="2026-05-06",
            snapshot_payload={"unavailable_symbols": []},
            conclusion_payload={},
            snapshot_path=tmp_path / "snapshot.json",
            conclusion_path=tmp_path / "conclusion.json",
        )

    ensure_tables.assert_called_once_with(session)
    persist_points.assert_called_once()
    persist_features.assert_called_once()
    assert session.committed is True
    assert session.rolled_back is False
    assert result == {
        "enabled": True,
        "macro_observation_upserts": 1,
        "raw_artifact_registry_upserts": 1,
        "feature_snapshot_upserts": 2,
    }


def test_persist_to_database_skips_without_normalized_data(tmp_path: Path) -> None:
    with patch.object(backfill_macro, "SessionLocal") as session_local:
        result = backfill_macro._persist_to_database(
            enabled=True,
            storage_root=tmp_path / "storage",
            all_points=[],
            source_refs=[{"symbol": "DGS10", "source": "fred", "reason": "timeout"}],
            run_id="run-a",
            as_of="2026-05-06",
            snapshot_payload={"unavailable_symbols": ["DGS10"]},
            conclusion_payload={},
            snapshot_path=tmp_path / "snapshot.json",
            conclusion_path=tmp_path / "conclusion.json",
        )

    session_local.assert_not_called()
    assert result["skipped"] == "no_normalized_data"
