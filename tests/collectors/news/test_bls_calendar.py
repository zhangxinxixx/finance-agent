from __future__ import annotations

from pathlib import Path

import httpx

from apps.collectors.news.bls import collect_bls_calendar


BLS_ICS_FIXTURE = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20260610T083000
DTEND;TZID=America/New_York:20260610T083000
SUMMARY:Consumer Price Index
DESCRIPTION:May 2026
URL:https://www.bls.gov/news.release/cpi.htm
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20260630T100000
SUMMARY:Job Openings and Labor Turnover Survey
DESCRIPTION:May 2026
URL:https://www.bls.gov/news.release/jolts.htm
END:VEVENT
END:VCALENDAR
"""


def test_bls_calendar_maps_high_impact_releases(tmp_path: Path) -> None:
    response = httpx.Response(
        200,
        content=BLS_ICS_FIXTURE.encode("utf-8"),
        request=httpx.Request("GET", "https://bls.test/bls.ics"),
    )

    result = collect_bls_calendar(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        calendar_url="https://bls.test/bls.ics",
        client=type("Client", (), {"get": lambda self, url: response})(),
    )

    assert result.status == "success"
    assert len(result.items) == 2
    assert result.items[0].source_key == "bls_calendar"
    assert result.items[0].source_type == "official"
    assert result.items[0].title == "Consumer Price Index"
    assert result.items[0].summary == "May 2026"
    assert result.items[0].published_at == "2026-06-10T12:30:00+00:00"
    assert result.items[0].event_type == "inflation_release"
    assert result.items[1].event_type == "labor_demand_release"
    assert result.items[0].raw_path.startswith("raw/news/bls/2026-06-10/release_calendar-")
    assert result.items[0].parsed_path.startswith("parsed/news/bls/2026-06-10/release_calendar-")
    assert (tmp_path / result.items[0].raw_path).exists()
    assert (tmp_path / result.items[0].parsed_path).exists()
    assert result.warnings == []
    assert result.unavailable_feeds == []
    assert result.source_refs[0]["source_ref"] == "bls_calendar:release_calendar"
    assert result.source_refs[0]["access_mode"] == "direct_official_ics"
    assert result.source_refs[0]["status"] == "available"
    assert result.source_refs[0]["raw_path"].startswith("raw/news/bls/2026-06-10/release_calendar-")
    assert result.source_refs[0]["parsed_path"].startswith("parsed/news/bls/2026-06-10/release_calendar-")
    assert "warning" not in result.source_refs[0]


def test_bls_calendar_uses_internal_http_client_runtime_controls(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeHttpxClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def __enter__(self) -> "FakeHttpxClient":
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def get(self, url: str) -> httpx.Response:
            return httpx.Response(
                200,
                content=BLS_ICS_FIXTURE.encode("utf-8"),
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr("apps.collectors.news.bls.httpx.Client", FakeHttpxClient)

    result = collect_bls_calendar(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        calendar_url="https://bls.test/bls.ics",
        request_timeout=3.5,
        request_proxy="http://127.0.0.1:7890",
        trust_env=False,
    )

    assert result.status == "success"
    assert captured["timeout"] == 3.5
    assert captured["headers"] == {"User-Agent": "finance-agent/0.1"}
    assert captured["proxy"] == "http://127.0.0.1:7890"
    assert captured["trust_env"] is False


def test_bls_calendar_marks_unavailable_when_request_fails(tmp_path: Path) -> None:
    client = type("Client", (), {"get": lambda self, url: (_ for _ in ()).throw(httpx.ConnectError("offline"))})()

    result = collect_bls_calendar(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        calendar_url="https://bls.test/bls.ics",
        client=client,
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.unavailable_feeds == ["release_calendar"]
    assert result.source_refs == [{
        "source_ref": "bls_calendar:release_calendar",
        "source": "bls_calendar",
        "source_url": "https://bls.test/bls.ics",
        "access_mode": "direct_official_ics",
        "status": "network_blocked",
        "reason_code": "network_blocked",
        "reason": "ConnectError: offline",
        "warning": "bls_calendar:release_calendar network_blocked: ConnectError: offline",
    }]
    assert result.warnings == [
        "bls_calendar:release_calendar network_blocked: ConnectError: offline",
    ]


def test_bls_calendar_marks_akamai_403_as_upstream_access_block(tmp_path: Path) -> None:
    request = httpx.Request("GET", "https://bls.test/bls.ics")
    response = httpx.Response(
        403,
        headers={"server": "AkamaiGHost"},
        text="<html>Access Denied</html>",
        request=request,
    )

    def _get(_self: object, _url: str) -> httpx.Response:
        raise httpx.HTTPStatusError("403 Forbidden", request=request, response=response)

    client = type("Client", (), {"get": _get})()

    result = collect_bls_calendar(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        calendar_url="https://bls.test/bls.ics",
        client=client,
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.unavailable_feeds == ["release_calendar"]
    assert result.source_refs == [{
        "source_ref": "bls_calendar:release_calendar",
        "source": "bls_calendar",
        "source_url": "https://bls.test/bls.ics",
        "access_mode": "direct_official_ics",
        "status": "unavailable",
        "reason_code": "upstream_access_blocked",
        "reason": "HTTP 403 from official BLS ICS (Akamai)",
        "warning": "bls_calendar:release_calendar upstream_access_blocked: HTTP 403 from official BLS ICS (Akamai)",
        "http_status": 403,
        "upstream_edge": "akamai",
    }]
    assert result.warnings == [
        "bls_calendar:release_calendar upstream_access_blocked: HTTP 403 from official BLS ICS (Akamai)",
    ]


def test_bls_calendar_marks_empty_calendar_as_unavailable_without_fake_data(tmp_path: Path) -> None:
    response = httpx.Response(
        200,
        content=b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n",
        request=httpx.Request("GET", "https://bls.test/bls.ics"),
    )

    result = collect_bls_calendar(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        calendar_url="https://bls.test/bls.ics",
        client=type("Client", (), {"get": lambda self, url: response})(),
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.unavailable_feeds == ["release_calendar"]
    assert result.source_refs[0]["status"] == "empty"
    assert result.source_refs[0]["reason_code"] == "no_items"
    assert result.source_refs[0]["reason"] == "BLS release calendar returned no parseable release events"
    assert result.source_refs[0]["access_mode"] == "direct_official_ics"
    assert result.source_refs[0]["warning"] == (
        "bls_calendar:release_calendar no_items: "
        "BLS release calendar returned no parseable release events"
    )
    assert result.warnings == [
        "bls_calendar:release_calendar no_items: "
        "BLS release calendar returned no parseable release events",
    ]


def test_bls_calendar_marks_rate_limit_as_explicit_source_ref_status(tmp_path: Path) -> None:
    request = httpx.Request("GET", "https://bls.test/bls.ics")
    response = httpx.Response(429, request=request)

    def _get(_self: object, _url: str) -> httpx.Response:
        raise httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)

    client = type("Client", (), {"get": _get})()

    result = collect_bls_calendar(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        calendar_url="https://bls.test/bls.ics",
        client=client,
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.unavailable_feeds == ["release_calendar"]
    assert result.source_refs == [{
        "source_ref": "bls_calendar:release_calendar",
        "source": "bls_calendar",
        "source_url": "https://bls.test/bls.ics",
        "access_mode": "direct_official_ics",
        "status": "rate_limited",
        "reason_code": "rate_limited",
        "reason": "HTTP 429 from https://www.bls.gov/schedule/news_release/bls.ics",
        "warning": "bls_calendar:release_calendar rate_limited: HTTP 429 from https://www.bls.gov/schedule/news_release/bls.ics",
        "http_status": 429,
    }]
    assert result.warnings == [
        "bls_calendar:release_calendar rate_limited: HTTP 429 from https://www.bls.gov/schedule/news_release/bls.ics",
    ]
