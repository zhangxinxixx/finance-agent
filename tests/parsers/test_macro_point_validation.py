from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.parsers.macro.models import MacroPoint
from apps.parsers.macro.validation import validate_macro_points
from apps.worker.pipelines.macro import persist_macro_points
from database.models.analysis import AnalysisBase, MacroObservation


CUTOFF = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
POINT = MacroPoint("DGS10", "2026-10-02", 4.3, "fred", "https://api.stlouisfed.org/fred/series/observations",
                   "2026-10-05T11:00:00Z", "raw/macro/fred/DGS10.json")


@pytest.mark.parametrize("changes,reason", [
    ({"value": float("nan")}, "non_finite_or_invalid_value"),
    ({"value": float("inf")}, "non_finite_or_invalid_value"),
    ({"value": True}, "non_finite_or_invalid_value"),
    ({"date": "2026-10-06"}, "future_observation_date"),
    ({"retrieved_at": "2026-10-05T12:01:00Z"}, "future_retrieval_time"),
    ({"retrieved_at": "2026-10-05T11:00:00"}, "retrieval_timezone_missing"),
    ({"raw_path": ""}, "missing_source_lineage"),
    ({"source_url": "not-a-url"}, "invalid_source_url"),
])
def test_invalid_parsed_observation_is_quarantined(changes, reason):
    points = [replace(POINT, **changes)]
    valid, diagnostics = validate_macro_points(points, cutoff=CUTOFF)
    assert valid == []
    assert diagnostics["rejected_count"] == 1
    assert reason in diagnostics["rejections"][0]["reason_codes"]
    assert points == [replace(POINT, **changes)]


def test_valid_history_is_preserved_and_duplicate_revisions_are_deterministic():
    old = replace(POINT, date="2020-01-02")
    revised = replace(POINT, value=4.4, retrieved_at="2026-10-05T11:30:00Z")
    valid, diagnostics = validate_macro_points([POINT, POINT, revised, old], cutoff=CUTOFF)
    assert valid == [old, revised]
    assert diagnostics["duplicate_count"] == 2
    assert diagnostics["rejected_count"] == 0


def test_same_time_conflicting_values_cannot_silently_pick_a_direction():
    valid, diagnostics = validate_macro_points([POINT, replace(POINT, value=7)], cutoff=CUTOFF)
    assert valid == []
    assert diagnostics["rejected_count"] == 2


def test_failed_source_metadata_cannot_promote_a_cached_number():
    valid, diagnostics = validate_macro_points([POINT], cutoff=CUTOFF,
        source_refs=[{"source": "fred", "symbol": "DGS10", "status": "failed"}])
    assert valid == []
    assert diagnostics["rejections"][0]["reason_codes"] == ["source_collection_failed"]


def test_calendar_schedule_preserves_future_release_time_as_event_metadata():
    point = replace(POINT, symbol="NEWS_EVENT:美国CPI", source="jin10_mcp",
                    date="2026-10-14T12:30:00Z", source_url="raw/news/calendar.json",
                    raw_path="raw/news/calendar.json")
    valid, diagnostics = validate_macro_points([point], cutoff=CUTOFF)
    assert valid == [point] and diagnostics["rejected_count"] == 0


def test_invalid_points_do_not_enter_observation_table(tmp_path):
    engine = create_engine("sqlite://")
    AnalysisBase.metadata.create_all(engine)
    with Session(engine) as db:
        stored_point = replace(POINT, retrieved_at="2026-10-02T18:00:00Z")
        count, _ = persist_macro_points(db, storage_root=tmp_path,
            all_points=[stored_point, replace(stored_point, symbol="DGS2", value=float("nan"))],
            all_refs=[], run_id="validation-backfill")
        assert count == 1
        row = db.scalars(select(MacroObservation)).one()
        assert row.symbol == "DGS10" and row.value == 4.3
        assert row.observation_metadata["validation_status"] == "valid"
