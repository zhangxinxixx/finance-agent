"""The compatibility URL serves official DWS calendar data, never collector cache."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from apps.api import main
from apps.api.routes import jin10_market_routes
from apps.api.services.page_calendar_read_model_service import get_calendar_summary


@pytest.fixture
def calendar_env(monkeypatch, tmp_path):
    artifact = tmp_path / "storage/features/news/2026-06-22/run-1/official_calendar.json"
    artifact.parent.mkdir(parents=True)
    monkeypatch.setattr(jin10_market_routes, "get_calendar_summary", lambda: get_calendar_summary(
        project_root=tmp_path, now=datetime(2026, 6, 22, 2, tzinfo=UTC),
    ))
    monkeypatch.setattr(
        "apps.scheduler.jin10_refresh.refresh_jin10_calendar_cache",
        lambda: pytest.fail("page reads must never collect or refresh raw cache"),
    )
    return artifact


def test_calendar_is_independent_of_optional_jin10_and_requires_dws(calendar_env, monkeypatch):
    monkeypatch.setattr(jin10_market_routes, "jin10_disabled", lambda: True)
    result = main.api_jin10_calendar()
    assert result["status"] == "unavailable"
    assert result["reason"] == "dws_calendar_unavailable"
    assert result["events"] == []


def test_calendar_projects_saved_values_and_sorts_upcoming_before_released(calendar_env):
    calendar_env.write_text(json.dumps({
        "as_of": "2026-06-22T01:00:00Z", "status": "available",
        "window_start_date": "2026-06-17", "window_end_date": "2026-07-06",
        "events": [
            {"title": "美国零售销售", "pub_time": "2026-06-20T20:30:00Z", "star": 4,
             "actual": "0.3", "consensus": "0.2", "previous": "0.1", "affect_txt": "利多"},
            {"title": "FOMC利率决定", "pub_time": "2026-06-24T02:00:00Z", "star": 5, "actual": None},
            {"title": "初请失业金", "pub_time": "2026-06-23T20:30:00Z", "star": 3, "actual": None},
        ],
    }))
    result = main.api_jin10_calendar()
    assert result["status"] == "available"
    assert result["stats"] == {
        "total": 3, "upcoming": 2, "released": 1, "pending": 0, "high_impact": 2,
        "earliest_event_date": "2026-06-20", "latest_event_date": "2026-06-24",
        "window_start_date": "2026-06-17", "window_end_date": "2026-07-06",
    }
    assert [event["title"] for event in result["events"]] == ["初请失业金", "FOMC利率决定", "美国零售销售"]
    assert result["events"][2]["actual"] == "0.3"
    assert result["events"][2]["consensus"] == "0.2"
    assert result["events"][2]["previous"] == "0.1"
    assert result["events"][1]["actual"] is None
    assert result["freshness"]["is_stale"] is False


def test_calendar_stale_feature_does_not_refresh_collection(calendar_env):
    calendar_env.write_text(json.dumps({"as_of": "2026-06-18T01:00:00Z", "status": "available",
        "events": [{"title": "Past release", "pub_time": "2026-06-18T20:00:00Z", "actual": "0.1"}]}))
    result = main.api_jin10_calendar()
    assert result["status"] == "stale"
    assert result["stats"]["released"] == 1
    assert result["freshness"]["is_stale"] is True


def test_calendar_raw_cache_cannot_fill_missing_dws(calendar_env, monkeypatch, tmp_path):
    cache = tmp_path / "storage" / "outputs" / "jin10" / "calendar_cache.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"generated_at": "2026-06-22T01:00:00Z",
                              "events": [{"title": "Unprocessed", "actual": "999"}]}))
    result = main.api_jin10_calendar()
    assert result["events"] == []
    assert result["status"] == "unavailable"
