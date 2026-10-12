from __future__ import annotations

import json
from pathlib import Path

import httpx

from apps.collectors.bls.employment import BLS_API_BASE_URL, collect_bls_employment
from apps.parsers.bls.employment import BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL


API_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "macro" / "bls_employment_api.json"
RELEASE_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "macro" / "bls_employment_release.html"


class _ApiClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def post(self, url: str, *, json: dict) -> httpx.Response:
        assert url == BLS_API_BASE_URL
        request = httpx.Request("POST", url)
        return httpx.Response(200, json=self.payload, request=request)


class _ReleaseClient:
    def __init__(self, body: str, *, archive_only: bool = False, block_all: bool = False) -> None:
        self.body = body
        self.archive_only = archive_only
        self.block_all = block_all
        self.urls: list[str] = []

    def get(self, url: str) -> httpx.Response:
        self.urls.append(url)
        request = httpx.Request("GET", url)
        if self.block_all or (self.archive_only and "/archives/" not in url):
            return httpx.Response(403, text="blocked", request=request)
        return httpx.Response(200, text=self.body, request=request)


class _FredVintageClient:
    def __init__(self, *, fail_status: int | None = None, omit_may: bool = False) -> None:
        self.fail_status = fail_status
        self.omit_may = omit_may
        self.requests: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, *, params: dict[str, object], **_: object) -> httpx.Response:
        self.requests.append((url, dict(params)))
        request = httpx.Request("GET", url)
        if self.fail_status is not None:
            return httpx.Response(self.fail_status, json={"error_code": "blocked"}, request=request)
        if url.endswith("/vintagedates"):
            return httpx.Response(
                200,
                json={
                    "vintage_dates": [
                        "2026-08-07",
                        "2026-09-04",
                        "2026-12-04",
                        "not-a-date",
                    ]
                },
                request=request,
            )
        vintage = str(params["realtime_start"])
        observations = {
            "2026-08-07": [
                {"date": "2026-05-01", "value": "158861"},
                {"date": "2026-06-01", "value": "158881"},
                {"date": "2026-07-01", "value": "158858"},
            ],
            "2026-09-04": [
                {"date": "2026-05-01", "value": "158861"},
                {"date": "2026-06-01", "value": "158892"},
                {"date": "2026-07-01", "value": "158913"},
                {"date": "2026-08-01", "value": "159075"},
            ],
        }
        if self.omit_may:
            observations[vintage] = [
                row for row in observations[vintage] if row["date"] != "2026-05-01"
            ]
        return httpx.Response(200, json={"observations": observations[vintage]}, request=request)


def test_collector_archives_and_exposes_release_context_without_changing_old_points(tmp_path: Path) -> None:
    result = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        client=_ApiClient(json.loads(API_FIXTURE.read_text(encoding="utf-8"))),
        release_client=_ReleaseClient(RELEASE_FIXTURE.read_text(encoding="utf-8")),
        start_year=2025,
        end_year=2026,
    )

    assert result.unavailable_symbols == []
    release_ref = next(ref for ref in result.source_refs if ref["symbol"] == BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL)
    assert release_ref["status"] == "available"
    assert release_ref["release_date"] == "2026-09-04"
    assert release_ref["observation_month"] == "2026-08"
    assert release_ref["release_context"]["revisions"][0]["delta_thousands"] == 10.0
    assert release_ref["release_context"]["sector_contributions"]
    raw_path = tmp_path / release_ref["raw_path"]
    assert raw_path.is_file()
    assert (tmp_path / f"{release_ref['raw_path']}.meta.json").is_file()
    assert all(point.symbol != BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL for point in result.points)


def test_collector_uses_bounded_archive_fallback_and_keeps_each_release_raw(tmp_path: Path) -> None:
    client = _ReleaseClient(RELEASE_FIXTURE.read_text(encoding="utf-8"), archive_only=True)
    kwargs = {
        "retrieved_date": "2026-09-06",
        "storage_root": tmp_path,
        "client": _ApiClient(json.loads(API_FIXTURE.read_text(encoding="utf-8"))),
        "release_client": client,
        "start_year": 2025,
        "end_year": 2026,
    }
    first = collect_bls_employment(**kwargs)
    second = collect_bls_employment(**kwargs)

    for result in (first, second):
        ref = next(ref for ref in result.source_refs if ref["symbol"] == BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL)
        assert ref["status"] == "available"
        assert ref["archive_fallback_used"] is True
        assert len(ref["attempted_raw_paths"]) == 2
        assert all((tmp_path / path).is_file() for path in ref["attempted_raw_paths"])
    assert set(first.source_refs[-1]["attempted_raw_paths"]).isdisjoint(second.source_refs[-1]["attempted_raw_paths"])


def test_collector_uses_dated_fred_vintages_after_bls_html_block(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("apps.collectors.bls.employment.resolve_runtime_secret", lambda _: "test-key")
    fred_client = _FredVintageClient()
    result = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        client=_ApiClient(json.loads(API_FIXTURE.read_text(encoding="utf-8"))),
        release_client=_ReleaseClient("blocked", block_all=True),
        fred_vintage_client=fred_client,
        series_ids=("CES0000000001",),
        start_year=2025,
        end_year=2026,
    )

    release_ref = next(ref for ref in result.source_refs if ref["symbol"] == BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL)
    assert release_ref["source"] == "fred_vintage"
    assert release_ref["source_kind"] == "fred_vintage"
    assert release_ref["status"] == "partial"
    assert release_ref["release_date"] == "2026-09-04"
    assert release_ref["release_date_kind"] == "fred_vintage_date"
    assert release_ref["release_context"]["release_time_local"] is None
    assert release_ref["release_context"]["headline"]["new_jobs_thousands"] == 162.0
    revisions = release_ref["release_context"]["revisions"]
    assert [item["observation_month"] for item in revisions] == ["2026-07", "2026-06"]
    assert revisions[0]["previous_value_thousands"] == -23.0
    assert revisions[0]["revised_value_thousands"] == 21.0
    assert revisions[0]["delta_thousands"] == 44.0
    assert revisions[0]["value_kind"] == "monthly_change"
    assert revisions[0]["level_components"]["previous_vintage"]["observation_level_thousands"] == 158858.0
    assert revisions[0]["level_components"]["previous_vintage"]["prior_month_level_thousands"] == 158881.0
    assert revisions[0]["level_components"]["current_vintage"]["observation_level_thousands"] == 158913.0
    assert revisions[0]["level_components"]["current_vintage"]["prior_month_level_thousands"] == 158892.0
    assert revisions[0]["delta_thousands"] != 55.0
    assert revisions[0]["baseline_kind"] == "previous_fred_vintage"
    assert release_ref["release_context"]["sector_contributions"] == []
    assert release_ref["release_context"]["source_refs"]
    assert any(ref.get("source") == "bls_employment_situation" for ref in release_ref["release_context"]["source_refs"])
    assert len(fred_client.requests) == 3
    assert all(params.get("api_key") == "test-key" for _, params in fred_client.requests)
    assert all("api_key" not in str(ref.get("source_url")) for ref in release_ref["release_context"]["source_refs"])
    raw_paths = release_ref["fred_vintage_raw_paths"]
    assert len(raw_paths) == len(set(raw_paths)) == 3
    assert all((tmp_path / path).is_file() for path in raw_paths)


def test_fred_vintage_revision_requires_both_months_in_each_vintage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("apps.collectors.bls.employment.resolve_runtime_secret", lambda _: "test-key")
    result = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        client=_ApiClient(json.loads(API_FIXTURE.read_text(encoding="utf-8"))),
        release_client=_ReleaseClient("blocked", block_all=True),
        fred_vintage_client=_FredVintageClient(omit_may=True),
        series_ids=("CES0000000001",),
        start_year=2025,
        end_year=2026,
    )

    release_ref = next(ref for ref in result.source_refs if ref["symbol"] == BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL)
    revisions = release_ref["release_context"]["revisions"]
    assert [item["observation_month"] for item in revisions] == ["2026-07"]
    assert "2026-06" not in {item["observation_month"] for item in revisions}


def test_collector_keeps_bls_unavailable_when_fred_vintage_is_forbidden(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("apps.collectors.bls.employment.resolve_runtime_secret", lambda _: "test-key")
    fred_client = _FredVintageClient(fail_status=403)
    result = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        client=_ApiClient(json.loads(API_FIXTURE.read_text(encoding="utf-8"))),
        release_client=_ReleaseClient("blocked", block_all=True),
        fred_vintage_client=fred_client,
        series_ids=("CES0000000001",),
        start_year=2025,
        end_year=2026,
    )

    release_ref = next(ref for ref in result.source_refs if ref["symbol"] == BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL)
    assert release_ref["status"] == "unavailable"
    assert release_ref["source"] == "bls_employment_situation"
    assert release_ref["fallback_source_kind"] == "fred_vintage"
    assert release_ref["fallback_failure_kind"] == "http_forbidden"
    assert release_ref["release_context"]["status"] == "unavailable"
    assert release_ref["fallback_context"]["source_kind"] == "fred_vintage"
    assert release_ref["fallback_context"]["status"] == "unavailable"
