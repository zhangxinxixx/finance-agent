from __future__ import annotations

import json
from pathlib import Path

import httpx

from apps.collectors.news.fomc_calendar import collect_fomc_calendar

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "news" / "fomc_calendar.html"


class FixtureClient:
    def __init__(self, body: str | Exception) -> None:
        self.body = body
        self.urls: list[str] = []

    def get(self, url: str) -> httpx.Response:
        self.urls.append(url)
        if isinstance(self.body, Exception):
            raise self.body
        return httpx.Response(200, text=self.body, request=httpx.Request("GET", url))


def test_fomc_collector_archives_unique_raw_and_parsed_payloads(tmp_path: Path) -> None:
    client = FixtureClient(FIXTURE.read_text(encoding="utf-8"))

    first = collect_fomc_calendar(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        calendar_url="https://fed.test/fomccalendars.htm",
        year=2026,
        client=client,
    )
    second = collect_fomc_calendar(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        calendar_url="https://fed.test/fomccalendars.htm",
        year=2026,
        client=client,
    )

    assert first.status == "success"
    assert first.unavailable_feeds == []
    assert len(first.items) == 3
    item = first.items[1]
    assert item.source_key == "fomc_calendar"
    assert item.feed_key == "fomc_meetings"
    assert item.source_type == "official"
    assert item.domain == "fed.test"
    assert item.published_at == "2026-09-15"
    assert item.raw_path.startswith("raw/news/fomc_calendar/2026-09-06/meeting_calendar-")
    assert item.parsed_path.startswith("parsed/news/fomc_calendar/2026-09-06/meeting_calendar-")
    assert item.raw_path != item.parsed_path
    assert (tmp_path / item.raw_path).is_file()
    assert (tmp_path / item.parsed_path).is_file()
    assert first.source_refs[0]["status"] == "available"
    assert first.source_refs[0]["raw_path"] == item.raw_path
    assert first.source_refs[0]["parsed_path"] == item.parsed_path
    assert first.source_refs[0]["year"] == 2026
    assert first.warnings == []
    assert client.urls == ["https://fed.test/fomccalendars.htm"] * 2
    assert second.items[0].raw_path != item.raw_path

    parsed_payload = json.loads((tmp_path / item.parsed_path).read_text(encoding="utf-8"))
    assert parsed_payload["filters"]["year"] == 2026
    assert parsed_payload["items"][1]["raw_path"] is None


def test_fomc_collector_marks_fetch_failure_without_writing_archives(tmp_path: Path) -> None:
    client = FixtureClient(httpx.ConnectError("offline"))

    result = collect_fomc_calendar(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        calendar_url="https://fed.test/fomccalendars.htm",
        client=client,
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.unavailable_feeds == ["fomc_meetings"]
    assert result.source_refs[0]["status"] == "failed"
    assert result.source_refs[0]["reason_code"] == "fetch_failed"
    assert list(tmp_path.rglob("*.json")) == []
    assert result.warnings


def test_fomc_collector_keeps_raw_and_parsed_empty_result_for_filter_miss(tmp_path: Path) -> None:
    client = FixtureClient(FIXTURE.read_text(encoding="utf-8"))

    result = collect_fomc_calendar(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        calendar_url="https://fed.test/fomccalendars.htm",
        start_date="2030-01-01",
        end_date="2030-12-31",
        client=client,
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.unavailable_feeds == ["fomc_meetings"]
    assert result.source_refs[0]["status"] == "empty"
    assert result.source_refs[0]["reason_code"] == "no_items"
    assert result.source_refs[0]["raw_path"]
    assert result.source_refs[0]["parsed_path"]
