from __future__ import annotations

from pathlib import Path

import httpx

from apps.collectors.news.bea import collect_bea_schedule


BEA_RELEASE_DATES_FIXTURE = {
    "Personal Income and Outlays": {
        "release_dates": [
            "2026-06-25T12:30:00+00:00",
            "2026-07-30T12:30:00+00:00",
        ],
        "url": "https://www.bea.gov/news/glance",
    },
    "Gross Domestic Product": {
        "release_dates": [
            "2026-06-25T12:30:00+00:00",
        ],
        "url": "https://www.bea.gov/news/glance",
    },
    "U.S. International Trade in Goods and Services": {
        "release_dates": [
            "2026-07-07T12:30:00+00:00",
        ],
    },
}


def test_bea_schedule_maps_pce_and_gdp_releases(tmp_path: Path) -> None:
    response = httpx.Response(
        200,
        json=BEA_RELEASE_DATES_FIXTURE,
        request=httpx.Request("GET", "https://bea.test/release_dates.json"),
    )

    result = collect_bea_schedule(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        schedule_url="https://bea.test/release_dates.json",
        client=type("Client", (), {"get": lambda self, url: response})(),
    )

    assert result.status == "success"
    assert len(result.items) == 3
    titles = [item.title for item in result.items]
    assert titles.count("Personal Income and Outlays") == 2
    assert "Gross Domestic Product" in titles
    assert {item.event_type for item in result.items} == {"pce_release", "gdp_release"}
    assert result.items[0].source_key == "bea_calendar"
    assert result.items[0].source_type == "official"
    assert result.items[0].published_at == "2026-06-25T12:30:00+00:00"
    assert result.items[0].verification_status == "official_confirmed"
    assert result.items[0].raw_path.startswith("raw/news/bea/2026-06-10/schedule-")
    assert result.items[0].parsed_path.startswith("parsed/news/bea/2026-06-10/schedule-")
    assert (tmp_path / result.items[0].raw_path).exists()
    assert (tmp_path / result.items[0].parsed_path).exists()


def test_bea_schedule_marks_unavailable_when_request_fails(tmp_path: Path) -> None:
    client = type("Client", (), {"get": lambda self, url: (_ for _ in ()).throw(httpx.ConnectError("offline"))})()

    result = collect_bea_schedule(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        schedule_url="https://bea.test/release_dates.json",
        client=client,
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.unavailable_feeds == ["release_schedule"]
