from __future__ import annotations

import json

from apps.api import main


def test_jin10_calendar_api_normalizes_and_sorts_payload(monkeypatch, tmp_path):
    cache_path = tmp_path / "calendar_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-22T01:00:00+00:00",
                "events": [
                    {
                        "title": "美国6月零售销售月率",
                        "pub_time": "2026-06-20 20:30",
                        "star": 4,
                        "actual": "0.3",
                        "consensus": "0.2",
                        "previous": "0.1",
                        "affect_txt": "利多",
                    },
                    {
                        "title": "美国6月FOMC利率决定",
                        "pub_time": "2026-06-24 02:00",
                        "star": 5,
                        "actual": None,
                        "consensus": "4.50",
                        "previous": "4.50",
                        "affect_txt": "",
                    },
                    {
                        "title": "美国6月初请失业金人数",
                        "pub_time": "2026-06-23 20:30",
                        "star": 3,
                        "actual": None,
                        "consensus": "22.5",
                        "previous": "23.1",
                        "affect_txt": "",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "_JIN10_CALENDAR_CACHE_PATH", cache_path)
    monkeypatch.setattr(main, "_JIN10_CALENDAR_CACHE_MAX_AGE_SECONDS", 10**9)

    result = main.api_jin10_calendar()

    assert result["status"] == "ok"
    assert result["stats"] == {
        "total": 3,
        "upcoming": 2,
        "released": 1,
        "high_impact": 2,
        "earliest_event_date": "2026-06-20",
        "latest_event_date": "2026-06-24",
    }
    assert [event["title"] for event in result["events"]] == [
        "美国6月初请失业金人数",
        "美国6月FOMC利率决定",
        "美国6月零售销售月率",
    ]
    assert result["events"][0]["release_state"] == "upcoming"
    assert result["events"][0]["pub_time"] == "2026-06-23T20:30+00:00"
    assert result["events"][1]["is_high_impact"] is True
    assert result["freshness"]["is_stale"] is False


def test_jin10_calendar_api_marks_past_only_window_as_stale(monkeypatch, tmp_path):
    cache_path = tmp_path / "calendar_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-22T01:00:00+00:00",
                "events": [
                    {
                        "title": "美国5月工业产出月率",
                        "pub_time": "2026-06-18 21:15",
                        "star": 3,
                        "actual": "0.1",
                        "consensus": "0.3",
                        "previous": "0.7",
                        "affect_txt": "利多",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "_JIN10_CALENDAR_CACHE_PATH", cache_path)
    monkeypatch.setattr(main, "_JIN10_CALENDAR_CACHE_MAX_AGE_SECONDS", 10**9)

    result = main.api_jin10_calendar()

    assert result["status"] == "stale"
    assert result["stats"]["upcoming"] == 0
    assert result["stats"]["released"] == 1
    assert result["freshness"]["is_stale"] is True
    assert result["freshness"]["reason"] == "no_upcoming_events"


def test_jin10_calendar_api_refreshes_past_only_window(monkeypatch, tmp_path):
    cache_path = tmp_path / "calendar_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-22T01:00:00+00:00",
                "events": [
                    {
                        "title": "美国5月工业产出月率",
                        "pub_time": "2026-06-18 21:15",
                        "star": 3,
                        "actual": "0.1",
                        "consensus": "0.3",
                        "previous": "0.7",
                        "affect_txt": "利多",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "_JIN10_CALENDAR_CACHE_PATH", cache_path)
    monkeypatch.setattr(main, "_JIN10_CALENDAR_CACHE_MAX_AGE_SECONDS", 10**9)

    def refresh() -> None:
        cache_path.write_text(
            json.dumps(
                {
                    "generated_at": "2026-06-22T03:00:00+00:00",
                    "events": [
                        {
                            "title": "美国6月FOMC利率决定",
                            "pub_time": "2026-06-24 02:00",
                            "star": 5,
                            "actual": None,
                            "consensus": "4.50",
                            "previous": "4.50",
                            "affect_txt": "",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("apps.scheduler.jin10_refresh.refresh_jin10_calendar_cache", refresh)

    result = main.api_jin10_calendar()

    assert result["status"] == "ok"
    assert result["generated_at"] == "2026-06-22T03:00:00+00:00"
    assert result["stats"]["upcoming"] == 1
    assert result["events"][0]["title"] == "美国6月FOMC利率决定"
    assert result["freshness"]["reason"] == "fresh"
