from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx

from apps.collectors.fred.collector import (
    FRED_MONTHLY_OBSERVATION_WINDOW_DAYS,
    FRED_MONTHLY_SERIES,
    FRED_SERIES,
    collect_fred_series,
    fred_graph_csv_url,
)
from apps.collectors.fred.collector import collect_fred_series_from_payload


def test_fred_default_series_include_formal_gold_macro_inputs() -> None:
    assert {"DGS5", "DGS30", "DFII5", "DFII10", "DFII30", "T5YIE", "T5YIFR", "DTWEXBGS"}.issubset(FRED_SERIES)
    assert {"CPIAUCSL", "PPIFIS", "PCEPI", "JTSJOL", "ICSA", "NAPM", "WALCL"}.issubset(FRED_SERIES)


def test_tga_week_average_is_converted_once_and_credit_spread_retains_percent(tmp_path) -> None:
    tga = collect_fred_series_from_payload(
        symbol="WTREGEN", payload={"observations": [{"date": "2026-09-02", "value": "967935"}]},
        retrieved_date="2026-09-05", storage_root=tmp_path,
        source_url="https://fred.stlouisfed.org/series/WTREGEN",
    )
    credit = collect_fred_series_from_payload(
        symbol="BAMLH0A0HYM2", payload={"observations": [{"date": "2026-09-03", "value": "2.66"}]},
        retrieved_date="2026-09-05", storage_root=tmp_path,
        source_url="https://fred.stlouisfed.org/series/BAMLH0A0HYM2",
    )
    assert tga.points[0].value == 967.935
    assert tga.points[0].symbol == "WTREGEN"
    assert credit.points[0].value == 2.66
    assert (tmp_path / tga.points[0].raw_path).is_file()
    assert (tmp_path / credit.points[0].raw_path).is_file()


def test_walcl_is_converted_from_fred_millions_to_billions(tmp_path) -> None:
    result = collect_fred_series_from_payload(
        symbol="WALCL", payload={"observations": [{"date": "2026-09-02", "value": "7123456.7"}]},
        retrieved_date="2026-09-08", storage_root=tmp_path,
        source_url="https://fred.stlouisfed.org/series/WALCL",
    )
    assert result.points[0].value == 7123.4567


def test_monthly_series_use_450_day_api_window_for_yoy_coverage(tmp_path: Path) -> None:
    captured_params: dict[str, str] = {}

    def fake_get(_url: str, *, params: dict[str, str]):
        captured_params.update(params)
        return httpx.Response(
            200,
            json={"observations": [{"date": "2026-09-01", "value": "100"}]},
            request=httpx.Request("GET", "https://test/"),
        )

    with patch("httpx.Client.get", side_effect=fake_get):
        result = collect_fred_series(
            retrieved_date="2026-09-06",
            storage_root=tmp_path,
            symbols=("PAYEMS",),
            api_key="test-key",
        )

    expected_start = (date(2026, 9, 6) - timedelta(days=FRED_MONTHLY_OBSERVATION_WINDOW_DAYS)).isoformat()
    assert captured_params["observation_start"] == expected_start
    assert captured_params["observation_end"] == "2026-09-06"
    assert {"PAYEMS", "CES0500000003", "UNRATE", "CIVPART"}.issubset(FRED_MONTHLY_SERIES)
    assert result.unavailable_symbols == []


def test_monthly_series_use_450_day_csv_window_and_non_monthly_remains_90_days(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("SETTINGS_MASTER_KEY", raising=False)
    csv_params: dict[str, str] = {}

    def fake_get(_url: str, *, params: dict[str, str]):
        csv_params.update(params)
        csv_body = "observation_date,PAYEMS\n2026-09-01,100\n"
        return httpx.Response(
            200,
            content=csv_body.encode(),
            request=httpx.Request("GET", fred_graph_csv_url("PAYEMS")),
        )

    with (
        patch("apps.collectors.fred.collector.resolve_runtime_secret", return_value=None),
        patch("httpx.Client.get", side_effect=fake_get),
    ):
        result = collect_fred_series(
            retrieved_date="2026-09-06",
            storage_root=tmp_path,
            symbols=("PAYEMS",),
        )

    expected_monthly_start = (date(2026, 9, 6) - timedelta(days=FRED_MONTHLY_OBSERVATION_WINDOW_DAYS)).isoformat()
    assert csv_params["cosd"] == expected_monthly_start
    assert csv_params["coed"] == "2026-09-06"
    assert result.unavailable_symbols == []

    non_monthly_params: dict[str, str] = {}

    def fake_non_monthly_get(_url: str, *, params: dict[str, str]):
        non_monthly_params.update(params)
        return httpx.Response(
            200,
            content=b"observation_date,DGS10\n2026-09-01,4.2\n",
            request=httpx.Request("GET", fred_graph_csv_url("DGS10")),
        )

    with (
        patch("apps.collectors.fred.collector.resolve_runtime_secret", return_value=None),
        patch("httpx.Client.get", side_effect=fake_non_monthly_get),
    ):
        collect_fred_series(
            retrieved_date="2026-09-06",
            storage_root=tmp_path,
            symbols=("DGS10",),
        )

    expected_non_monthly_start = (date(2026, 9, 6) - timedelta(days=90)).isoformat()
    assert non_monthly_params["cosd"] == expected_non_monthly_start
    assert non_monthly_params["coed"] == "2026-09-06"


def test_fred_http_error_ref_preserves_status_without_request_credentials(tmp_path: Path) -> None:
    credential = "fixture-fred-api-key"
    request = httpx.Request(
        "GET",
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": "NAPM", "api_key": credential},
    )
    response = httpx.Response(400, request=request)

    with (
        patch("httpx.Client.get", return_value=response),
        patch("apps.collectors.fred.collector.time.sleep"),
    ):
        result = collect_fred_series(
            retrieved_date="2026-09-16",
            storage_root=tmp_path,
            symbols=("NAPM",),
            api_key=credential,
        )

    assert result.unavailable_symbols == ["NAPM"]
    assert result.source_refs == [
        {
            "symbol": "NAPM",
            "source": "fred",
            "source_url": "https://api.stlouisfed.org/fred/series/observations?series_id=NAPM&file_type=json&sort_order=asc",
            "status": "unavailable",
            "reason_code": "http_error",
            "error_type": "HTTPStatusError",
            "reason": "FRED request failed: http_error; series_id=NAPM; error_type=HTTPStatusError; http_status=400",
            "http_status": "400",
        }
    ]
    assert credential not in str(result.to_dict())
    assert "api_key" not in result.source_refs[0]["reason"]


def test_fred_transport_error_ref_does_not_copy_exception_url(tmp_path: Path) -> None:
    credential = "fixture-transport-key"
    request_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=NAPM&api_key={credential}"
    error = httpx.ConnectError(f"connect failed for {request_url}", request=httpx.Request("GET", request_url))

    with (
        patch("httpx.Client.get", side_effect=error),
        patch("apps.collectors.fred.collector.time.sleep"),
    ):
        result = collect_fred_series(
            retrieved_date="2026-09-16",
            storage_root=tmp_path,
            symbols=("NAPM",),
            api_key=credential,
        )

    ref = result.source_refs[0]
    assert ref["status"] == "unavailable"
    assert ref["reason_code"] == "transport_error"
    assert ref["error_type"] == "ConnectError"
    assert ref["reason"] == "FRED request failed: transport_error; series_id=NAPM; error_type=ConnectError"
    assert credential not in str(result.to_dict())
    assert request_url not in str(result.to_dict())
