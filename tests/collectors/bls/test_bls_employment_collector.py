from __future__ import annotations

import json
from pathlib import Path

import httpx

import apps.collectors.bls.employment as employment
from apps.collectors.bls.employment import (
    BLS_API_BASE_URL,
    BLS_EMPLOYMENT_SERIES,
    BLS_INDUSTRY_SERIES,
    FRED_GRAPH_CSV_URL,
    bls_series_url,
    collect_bls_employment,
    collect_bls_series_from_payload,
)
from apps.parsers.macro.models import CollectorResult, MacroPoint

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "macro" / "bls_employment_api.json"


class FixtureClient:
    def __init__(self, payload: dict, *, failing_symbols: set[str] | None = None) -> None:
        self.payload = payload
        self.failing_symbols = failing_symbols or set()
        self.urls: list[str] = []

    def get(self, url: str) -> httpx.Response:
        self.urls.append(url)
        symbol = url.split("/")[-1].split("?")[0]
        request = httpx.Request("GET", url)
        if symbol in self.failing_symbols:
            return httpx.Response(503, json={"status": "REQUEST_FAILED"}, request=request)
        return httpx.Response(200, json=self.payload, request=request)


class BatchFixtureClient:
    def __init__(self, payload: dict, *, fred_csv: str | None = None) -> None:
        self.payload = payload
        self.fred_csv = fred_csv
        self.post_calls: list[tuple[str, dict]] = []
        self.get_urls: list[str] = []

    def post(self, url: str, *, json: dict) -> httpx.Response:
        self.post_calls.append((url, json))
        request = httpx.Request("POST", url)
        return httpx.Response(200, json=self.payload, request=request)

    def get(self, url: str) -> httpx.Response:
        self.get_urls.append(url)
        request = httpx.Request("GET", url)
        if self.fred_csv is None:
            raise AssertionError(f"unexpected GET: {url}")
        return httpx.Response(200, text=self.fred_csv, request=request)


class RateLimitBatchClient:
    def __init__(self, *, fred_csv: str | None = None) -> None:
        self.fred_csv = fred_csv
        self.post_calls: list[tuple[str, dict]] = []
        self.get_urls: list[str] = []

    def post(self, url: str, *, json: dict) -> httpx.Response:
        self.post_calls.append((url, json))
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={
                "status": "REQUEST_NOT_PROCESSED",
                "message": ["daily threshold reached"],
                "Results": {},
            },
            request=request,
        )

    def get(self, url: str) -> httpx.Response:
        self.get_urls.append(url)
        request = httpx.Request("GET", url)
        if self.fred_csv is None:
            raise AssertionError(f"unexpected GET: {url}")
        return httpx.Response(200, text=self.fred_csv, request=request)


class NoGetClient:
    def post(self, url: str, *, json: dict) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={
                "status": "REQUEST_NOT_PROCESSED",
                "message": ["daily threshold reached"],
                "Results": {},
            },
            request=request,
        )


class ConnectErrorBatchClient:
    def __init__(self, fred_csv: str) -> None:
        self.fred_csv = fred_csv
        self.post_calls: list[tuple[str, dict]] = []
        self.get_urls: list[str] = []

    def post(self, url: str, *, json: dict) -> httpx.Response:
        self.post_calls.append((url, json))
        request = httpx.Request("POST", url)
        raise httpx.ConnectError("BLS TLS connection closed", request=request)

    def get(self, url: str) -> httpx.Response:
        self.get_urls.append(url)
        request = httpx.Request("GET", url)
        return httpx.Response(200, text=self.fred_csv, request=request)


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _seed_successful_cache(
    *,
    storage_root: Path,
    payload: dict,
    retrieved_at: str = "2026-09-05T12:00:00+00:00",
    retrieved_date: str = "2026-09-05",
) -> None:
    cache_payload = json.loads(json.dumps(payload))
    for series in cache_payload.get("Results", {}).get("series", []):
        series["data"] = [
            row
            for row in series.get("data", [])
            if f"{row.get('year')}-{str(row.get('period') or '')[1:]}" <= retrieved_date[:7]
        ]
    for symbol in BLS_EMPLOYMENT_SERIES:
        collect_bls_series_from_payload(
            symbol=symbol,
            payload=cache_payload,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            source_url=bls_series_url(symbol, 2025, 2026),
            retrieved_at=retrieved_at,
        )


def _fred_csv() -> str:
    return "\n".join(
        [
            "observation_date,PAYEMS,CES0500000003,UNRATE,CIVPART",
            "2026-07-01,160000,36.50,4.2,62.1",
            "2026-08-01,161000,36.75,4.1,62.2",
            "2026-10-01,999999,99.99,9.9,99.9",
        ]
    )


def _fred_csv_with_industries() -> str:
    return "\n".join(
        [
            "observation_date,PAYEMS,CES0500000003,UNRATE,CIVPART,MANEMP,USINFO,CES7072200001,CES9093161101,CES6562000101",
            "2026-07-01,158913,37.65,4.1,61.4,12622,2768,12367.6,8151.9,18507.8",
            "2026-08-01,159075,37.75,4.1,61.6,12638,2745,12426.8,8193.8,18520.7",
        ]
    )


def test_bls_collector_archives_raw_payload_and_keeps_cutoff_passport(tmp_path: Path) -> None:
    payload = _load_fixture()
    client = FixtureClient(payload)

    result = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        start_year=2025,
        end_year=2026,
        client=client,
    )

    assert result.unavailable_symbols == []
    assert {point.symbol for point in result.points} == set(BLS_EMPLOYMENT_SERIES)
    assert all(point.date <= "2026-09-01" for point in result.points)
    assert all(point.source == "bls_public_api_v2" for point in result.points)
    assert all((tmp_path / point.raw_path).is_file() for point in result.points)
    assert len({point.raw_path for point in result.points}) == 4
    assert len(client.urls) == 4
    assert all(url.startswith(f"{BLS_API_BASE_URL}/") for url in client.urls)
    assert all("startyear=2025&endyear=2026" in url for url in client.urls)

    refs = {ref["symbol"]: ref for ref in result.source_refs}
    assert set(refs) == set(BLS_EMPLOYMENT_SERIES)
    assert all(ref["observation_cutoff_date"] == "2026-09-06" for ref in refs.values())
    assert all(ref["observation_cutoff_month"] == "2026-09" for ref in refs.values())
    assert all(ref["release_date"] == "unavailable" for ref in refs.values())
    assert all(ref["vintage_status"] == "unavailable" for ref in refs.values())
    assert all(ref["status"] == "available" for ref in refs.values())
    assert all(ref["cache_used"] is False for ref in refs.values())
    assert all(
        (tmp_path / f"{ref['raw_path']}.meta.json").is_file()
        for ref in refs.values()
    )
    metadata = json.loads(
        (tmp_path / f"{refs['CES0000000001']['raw_path']}.meta.json").read_text(encoding="utf-8")
    )
    assert metadata["schema_version"] == "bls_raw_metadata.v1"
    assert metadata["status"] == "available"
    assert metadata["retrieved_at"] == refs["CES0000000001"]["retrieved_at"]


def test_bls_collector_marks_only_failed_series_unavailable(tmp_path: Path) -> None:
    payload = _load_fixture()
    client = FixtureClient(payload, failing_symbols={"LNS14000000"})

    result = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        client=client,
    )

    assert result.unavailable_symbols == ["LNS14000000"]
    assert {point.symbol for point in result.points} == {
        "CES0000000001",
        "CES0500000003",
        "LNS11300000",
    }
    failed_ref = next(ref for ref in result.source_refs if ref["symbol"] == "LNS14000000")
    assert failed_ref["status"] == "unavailable"
    assert failed_ref["reason"].startswith("BLS request or parse failed")
    assert failed_ref["failure_kind"] == "http_error"


def test_bls_payload_collector_archives_api_failure_before_marking_unavailable(tmp_path: Path) -> None:
    source_url = bls_series_url("CES0000000001", 2025, 2026)
    result = collect_bls_series_from_payload(
        symbol="CES0000000001",
        payload={"status": "REQUEST_FAILED", "message": ["rate limit"]},
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        source_url=source_url,
    )

    assert result.points == []
    assert result.unavailable_symbols == ["CES0000000001"]
    ref = result.source_refs[0]
    assert ref["raw_path"].startswith("raw/macro/bls/2026-09-06/CES0000000001-")
    assert (tmp_path / ref["raw_path"]).is_file()
    assert ref["release_date"] == "unavailable"
    assert ref["failure_kind"] == "rate_limit"


def test_repeated_bls_archive_keeps_each_raw_response_and_sidecar(tmp_path: Path) -> None:
    kwargs = {
        "symbol": "CES0000000001",
        "payload": _load_fixture(),
        "retrieved_date": "2026-09-06",
        "storage_root": tmp_path,
        "source_url": bls_series_url("CES0000000001", 2025, 2026),
        "retrieved_at": "2026-09-06T12:00:00+00:00",
    }
    first = collect_bls_series_from_payload(**kwargs)
    second = collect_bls_series_from_payload(**kwargs)

    first_path = first.source_refs[0]["raw_path"]
    second_path = second.source_refs[0]["raw_path"]
    assert first_path != second_path
    assert (tmp_path / first_path).is_file()
    assert (tmp_path / second_path).is_file()
    assert (tmp_path / f"{first_path}.meta.json").is_file()
    assert (tmp_path / f"{second_path}.meta.json").is_file()


def test_bls_batch_client_uses_one_post_and_keeps_per_series_raw_lineage(tmp_path: Path) -> None:
    client = BatchFixtureClient(_load_fixture())

    result = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        start_year=2025,
        end_year=2026,
        client=client,
    )

    assert result.unavailable_symbols == []
    assert len(client.post_calls) == 1
    assert client.get_urls == []
    url, body = client.post_calls[0]
    assert url == BLS_API_BASE_URL
    assert body == {
        "seriesid": list(BLS_EMPLOYMENT_SERIES),
        "startyear": "2025",
        "endyear": "2026",
    }
    assert len({point.raw_path for point in result.points}) == 4


def test_rate_limit_uses_only_recent_successful_same_storage_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(employment, "utc_now_iso", lambda: "2026-09-06T12:00:00+00:00")
    payload = _load_fixture()
    _seed_successful_cache(storage_root=tmp_path, payload=payload)
    client = RateLimitBatchClient()

    result = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        client=client,
        fred_client=NoGetClient(),
    )

    assert result.unavailable_symbols == []
    assert len(client.post_calls) == 1
    assert client.get_urls == []
    refs = {ref["symbol"]: ref for ref in result.source_refs}
    assert all(ref["status"] == "available" for ref in refs.values())
    assert all(ref["cache_used"] is True for ref in refs.values())
    assert all(ref["fallback_source"] == "same_storage_raw" for ref in refs.values())
    assert all(ref["cache_original_retrieved_at"] == "2026-09-05T12:00:00+00:00" for ref in refs.values())
    assert all(point.source == "bls_public_api_v2" for point in result.points)
    assert all(point.retrieved_at == "2026-09-05T12:00:00+00:00" for point in result.points)


def test_rate_limit_rejects_future_and_expired_cache_without_marking_available(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(employment, "utc_now_iso", lambda: "2026-09-06T12:00:00+00:00")
    payload = _load_fixture()
    _seed_successful_cache(
        storage_root=tmp_path / "future",
        payload=payload,
        retrieved_at="2026-09-07T12:00:00+00:00",
    )
    _seed_successful_cache(
        storage_root=tmp_path / "expired",
        payload=payload,
        retrieved_at="2026-07-01T12:00:00+00:00",
    )

    for root, expected_reason in ((tmp_path / "future", "future_retrieved_at"), (tmp_path / "expired", "expired")):
        result = collect_bls_employment(
            retrieved_date="2026-09-06",
            storage_root=root,
            client=NoGetClient(),
            fred_client=NoGetClient(),
        )
        assert set(result.unavailable_symbols) == set(BLS_EMPLOYMENT_SERIES)
        refs = {ref["symbol"]: ref for ref in result.source_refs}
        assert all(ref["cache_used"] is False for ref in refs.values())
        assert all(ref["failure_kind"] == "rate_limit" for ref in refs.values())
        assert all(expected_reason in ref["cache_rejection_reason"] for ref in refs.values())


def test_cache_rejects_future_report_month_even_with_valid_retrieval_provenance(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(employment, "utc_now_iso", lambda: "2026-09-06T12:00:00+00:00")
    payload = _load_fixture()
    # Archive one auditable raw response with the future row and align its
    # sidecar so the rejection comes from the report-month cutoff itself.
    raw_ref = collect_bls_series_from_payload(
        symbol="CES0000000001",
        payload=payload,
        retrieved_date="2026-09-05",
        storage_root=tmp_path,
        source_url=bls_series_url("CES0000000001", 2025, 2026),
        retrieved_at="2026-09-05T12:00:00+00:00",
    ).source_refs[0]
    metadata_path = tmp_path / f"{raw_ref['raw_path']}.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["latest_observation_month"] = "2026-10"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    result = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        series_ids=("CES0000000001",),
        client=NoGetClient(),
        fred_client=NoGetClient(),
    )

    assert result.unavailable_symbols == ["CES0000000001"]
    ref = result.source_refs[0]
    assert ref["cache_used"] is False
    assert "future_report_month" in ref["cache_rejection_reason"]


def test_cache_rejects_recent_raw_when_latest_report_is_older_than_previous_full_month(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(employment, "utc_now_iso", lambda: "2026-09-06T12:00:00+00:00")
    _seed_successful_cache(
        storage_root=tmp_path,
        payload=_load_fixture(),
        retrieved_at="2026-08-15T12:00:00+00:00",
        retrieved_date="2026-07-31",
    )

    result = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        client=NoGetClient(),
        fred_client=NoGetClient(),
    )

    assert set(result.unavailable_symbols) == set(BLS_EMPLOYMENT_SERIES)
    assert all(ref["cache_used"] is False for ref in result.source_refs)
    assert all("stale_report_month" in ref["cache_rejection_reason"] for ref in result.source_refs)


def test_rate_limit_without_cache_uses_one_official_fred_csv_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(employment, "utc_now_iso", lambda: "2026-09-06T12:00:00+00:00")
    client = RateLimitBatchClient(fred_csv=_fred_csv())

    result = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        client=client,
    )

    assert result.unavailable_symbols == []
    assert len(client.post_calls) == 1
    assert len(client.get_urls) == 1
    assert client.get_urls[0].startswith(FRED_GRAPH_CSV_URL)
    refs = {ref["symbol"]: ref for ref in result.source_refs}
    assert set(refs) == set(BLS_EMPLOYMENT_SERIES)
    assert all(ref["source"] == "fred" for ref in refs.values())
    assert all(ref["cache_used"] is False for ref in refs.values())
    assert all(ref["fallback_source"] == "official_fred_graph_csv" for ref in refs.values())
    assert all(ref["upstream_failure_kind"] == "rate_limit" for ref in refs.values())
    assert all("not_successful_bls_raw" in ref["cache_rejection_reason"] for ref in refs.values())
    assert refs["CES0000000001"]["source_series"] == "PAYEMS"
    assert refs["CES0000000001"]["unit"] == "thousand_persons"
    assert all(point.source == "fred" for point in result.points)
    assert all(point.date <= "2026-09-01" for point in result.points)
    assert all((tmp_path / point.raw_path).suffix == ".csv" for point in result.points)


def test_bls_connection_error_falls_back_to_fred_for_core_and_industry_series(tmp_path: Path) -> None:
    requested = BLS_EMPLOYMENT_SERIES + BLS_INDUSTRY_SERIES
    client = ConnectErrorBatchClient(_fred_csv_with_industries())

    result = collect_bls_employment(
        retrieved_date="2026-09-08",
        storage_root=tmp_path,
        series_ids=requested,
        client=client,
        start_year=2025,
        end_year=2026,
    )

    assert result.unavailable_symbols == []
    assert {point.symbol for point in result.points} == set(requested)
    assert len(client.post_calls) == 1
    assert len(client.get_urls) == 1
    refs = {str(ref["symbol"]): ref for ref in result.source_refs}
    assert refs["CES0000000001"]["source"] == "fred"
    assert refs["CES0000000001"]["fallback_source"] == "official_fred_graph_csv"
    assert refs["CES0000000001"]["upstream_failure_kind"] == "http_error"
    assert refs["CES0000000001"]["upstream_source"] == "bls_public_api_v2"
    assert refs["CES0000000001"]["upstream_source_url"].startswith(BLS_API_BASE_URL)
    assert "upstream_raw_path" in refs["CES0000000001"]
    assert refs["CES3000000001"]["source_series"] == "MANEMP"
    assert refs["CES3000000001"]["latest_observation_month"] == "2026-08"
    assert all(point.source == "fred" for point in result.points)


def test_live_fred_api_collector_mapping_keeps_real_fred_lineage(tmp_path: Path, monkeypatch) -> None:
    def fake_collect_fred_series(*, retrieved_date: str, storage_root: Path, symbols: tuple[str, ...]) -> CollectorResult:
        points = [
            MacroPoint(
                symbol=symbol,
                date="2026-08-01",
                value=float(index + 1),
                source="fred",
                source_url=f"https://api.stlouisfed.org/fred/series/observations?series_id={symbol}",
                retrieved_at="2026-09-06T12:00:01+00:00",
                raw_path=f"raw/macro/fred/{retrieved_date}/{symbol}.json",
            )
            for index, symbol in enumerate(symbols)
        ]
        refs = [
            {
                "symbol": symbol,
                "source": "fred",
                "source_url": point.source_url,
                "raw_path": point.raw_path,
                "retrieved_at": point.retrieved_at,
            }
            for symbol, point in zip(symbols, points, strict=True)
        ]
        return CollectorResult(points=points, unavailable_symbols=[], source_refs=refs)

    monkeypatch.setattr("apps.collectors.fred.collector.collect_fred_series", fake_collect_fred_series)
    outcome = employment._collect_fred_api_series(
        requested_series=BLS_EMPLOYMENT_SERIES,
        retrieved_date="2026-09-06",
        storage_root=tmp_path,
        attempted_at="2026-09-06T12:00:00+00:00",
        upstream_reasons={symbol: "BLS daily threshold" for symbol in BLS_EMPLOYMENT_SERIES},
    )

    assert outcome.failure_kind is None
    assert set(outcome.points_by_symbol) == set(BLS_EMPLOYMENT_SERIES)
    assert all(ref["source"] == "fred" for ref in outcome.refs_by_symbol.values())
    assert all(ref["fallback_source"] == "official_fred_api_collector" for ref in outcome.refs_by_symbol.values())
    assert all(ref["cache_used"] is False for ref in outcome.refs_by_symbol.values())
    assert outcome.refs_by_symbol["CES0000000001"]["source_series"] == "PAYEMS"


def test_missing_fields_and_http_failures_are_classified_without_cache_fallback(tmp_path: Path) -> None:
    missing_client = FixtureClient({"status": "REQUEST_SUCCEEDED"})
    missing = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path / "missing",
        client=missing_client,
        fred_client=NoGetClient(),
    )
    assert set(missing.unavailable_symbols) == set(BLS_EMPLOYMENT_SERIES)
    assert all(ref["failure_kind"] == "missing_fields" for ref in missing.source_refs)
    assert all(ref["cache_used"] is False for ref in missing.source_refs)

    class Http429Client(FixtureClient):
        def get(self, url: str) -> httpx.Response:
            self.urls.append(url)
            return httpx.Response(429, text="daily threshold", request=httpx.Request("GET", url))

    limited = collect_bls_employment(
        retrieved_date="2026-09-06",
        storage_root=tmp_path / "limited",
        client=Http429Client({}),
        fred_client=NoGetClient(),
    )
    assert set(limited.unavailable_symbols) == set(BLS_EMPLOYMENT_SERIES)
    assert all(ref["failure_kind"] == "rate_limit" for ref in limited.source_refs)
