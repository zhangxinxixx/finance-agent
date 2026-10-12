from __future__ import annotations

import json
from pathlib import Path

import httpx

from apps.collectors.news.fred_calendar import collect_fred_release_calendar


PAYLOADS = {
    10: {
        "release_dates": [
            {"release_id": 10, "date": "2026-09-04"},
            {"release_id": 10, "date": "2026-09-11"},
        ]
    },
    46: {
        "release_dates": [
            {"release_id": 46, "date": "2026-09-03"},
            {"release_id": 46, "date": "2026-09-10"},
        ]
    },
}


class FixtureClient:
    def __init__(self, *, failed_release_ids: set[int] | None = None) -> None:
        self.failed_release_ids = failed_release_ids or set()
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, *, params: dict[str, str]) -> httpx.Response:
        release_id = int(params["release_id"])
        self.calls.append((url, dict(params)))
        request = httpx.Request("GET", url, params=params)
        if release_id in self.failed_release_ids:
            return httpx.Response(503, content=b"blocked", request=request)
        return httpx.Response(200, json=PAYLOADS[release_id], request=request)


def test_fred_calendar_collector_returns_future_cpi_ppi_dates_and_archives_lineage(tmp_path: Path) -> None:
    client = FixtureClient()

    result = collect_fred_release_calendar(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        api_key="fixture-secret",
        client=client,
    )

    assert result.status == "success"
    assert result.unavailable_feeds == []
    assert [(item.title, item.published_at) for item in result.items] == [
        ("PPI release", "2026-09-10"),
        ("CPI release", "2026-09-11"),
    ]
    assert all(item.source_key == "fred_calendar" for item in result.items)
    assert all(item.published_at and "T" not in item.published_at for item in result.items)
    assert all(item.raw_path and (tmp_path / item.raw_path).is_file() for item in result.items)
    assert all(item.parsed_path and (tmp_path / item.parsed_path).is_file() for item in result.items)
    assert len({item.raw_path for item in result.items}) == 2
    assert len({item.parsed_path for item in result.items}) == 2
    assert {ref["release_id"] for ref in result.source_refs} == {10, 46}
    assert all(ref["access_mode"] == "official_fred_api" for ref in result.source_refs)
    assert all("fixture-secret" not in json.dumps(ref) for ref in result.source_refs)
    assert all("fixture-secret" not in path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert all(params["include_release_dates_with_no_data"] == "true" for _, params in client.calls)
    assert all(params["api_key"] == "fixture-secret" for _, params in client.calls)
    assert all("api_key" not in url for url, _ in client.calls)


def test_fred_calendar_collector_keeps_cpi_when_ppi_request_fails(tmp_path: Path) -> None:
    result = collect_fred_release_calendar(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        api_key="fixture-secret",
        client=FixtureClient(failed_release_ids={46}),
    )

    assert result.status == "partial"
    assert [(item.title, item.published_at) for item in result.items] == [("CPI release", "2026-09-11")]
    assert result.unavailable_feeds == ["release_dates:46"]
    failed_ref = next(ref for ref in result.source_refs if ref["release_id"] == 46)
    assert failed_ref["status"] == "failed"
    assert failed_ref["reason_code"] == "fetch_failed"
    assert "fixture-secret" not in json.dumps({"refs": result.source_refs, "warnings": result.warnings})


def test_fred_calendar_collector_marks_missing_credentials_without_archiving(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr("apps.collectors.news.fred_calendar.resolve_runtime_secret", lambda _name: None)
    result = collect_fred_release_calendar(retrieved_date="2026-09-06", storage_root=tmp_path, api_key="")

    assert result.status == "unavailable"
    assert result.items == []
    assert result.unavailable_feeds == ["release_dates:10", "release_dates:46"]
    assert all(ref["reason_code"] == "missing_credentials" for ref in result.source_refs)
    assert list(tmp_path.rglob("*.json")) == []
