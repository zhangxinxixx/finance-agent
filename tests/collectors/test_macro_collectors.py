from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from apps.collectors.dxy.collector import collect_dxy_series
from apps.collectors.fed.collector import collect_fed_series
from apps.collectors.fred.collector import collect_fred_series, collect_fred_series_from_payload
from apps.collectors.treasury.collector import collect_treasury_series
from apps.runtime import secret_resolver

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "macro"


def test_fred_payload_is_normalized_and_raw_response_is_archived(tmp_path: Path) -> None:
    payload = json.loads((FIXTURES / "fred_observations.json").read_text())
    result = collect_fred_series_from_payload(symbol="DGS10", payload=payload, retrieved_date="2026-05-06", storage_root=tmp_path, source_url="fixture://fred/DGS10")
    assert result.unavailable_symbols == []
    assert [point.symbol for point in result.points] == ["DGS10", "DGS10", "DGS10"]
    assert result.points[-1].date == "2026-05-06"
    assert result.points[-1].value == 4.30
    assert result.points[-1].source == "fred"
    assert result.points[-1].source_url == "fixture://fred/DGS10"
    assert result.points[-1].raw_path.startswith("raw/macro/fred/2026-05-06/DGS10-")
    assert (tmp_path / result.points[-1].raw_path).exists()


def test_fred_payload_marks_symbol_unavailable_when_all_values_are_missing(tmp_path: Path) -> None:
    result = collect_fred_series_from_payload(symbol="DGS10", payload={"observations": [{"date": "2026-05-06", "value": "."}]}, retrieved_date="2026-05-06", storage_root=tmp_path, source_url="fixture://fred/DGS10")
    assert result.points == []
    assert result.unavailable_symbols == ["DGS10"]


def test_fred_payload_ignores_observations_after_retrieved_date(tmp_path: Path) -> None:
    payload = {
        "observations": [
            {"date": "2026-06-18", "value": "3.65"},
            {"date": "2026-06-22", "value": "3.70"},
        ]
    }
    result = collect_fred_series_from_payload(
        symbol="IORB",
        payload=payload,
        retrieved_date="2026-06-18",
        storage_root=tmp_path,
        source_url="fixture://fred/IORB",
    )
    assert [point.date for point in result.points] == ["2026-06-18"]
    assert result.points[0].value == 3.65


def test_fred_collector_falls_back_to_csv_when_no_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("SETTINGS_MASTER_KEY", raising=False)
    monkeypatch.setattr(secret_resolver, "_PROJECT_ROOT", tmp_path)
    csv_body = "observation_date,DGS10\r\n2026-05-01,4.25\r\n2026-05-04,4.30\r\n2026-05-05,4.32\n"
    mock_response = httpx.Response(200, content=csv_body.encode(), request=httpx.Request("GET", "https://test/"))
    with patch("httpx.Client.get", return_value=mock_response):
        result = collect_fred_series(retrieved_date="2026-05-06", storage_root=tmp_path, symbols=("DGS10",))
    assert not result.unavailable_symbols
    assert len(result.points) == 3
    assert result.points[-1].value == 4.32


def test_fred_collector_passes_retrieved_date_to_api_request(tmp_path: Path) -> None:
    captured_params: dict[str, str] = {}

    def fake_get(_url: str, *, params: dict[str, str]):
        captured_params.update(params)
        payload = {"observations": [{"date": "2026-06-18", "value": "4.49"}]}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://test/"))

    with patch("httpx.Client.get", side_effect=fake_get):
        result = collect_fred_series(
            retrieved_date="2026-06-18",
            storage_root=tmp_path,
            symbols=("DGS10",),
            api_key="test-key",
        )

    assert not result.unavailable_symbols
    assert captured_params["observation_end"] == "2026-06-18"
    assert result.points[-1].date == "2026-06-18"


def test_fred_collector_marks_unavailable_when_csv_request_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("SETTINGS_MASTER_KEY", raising=False)
    monkeypatch.setattr(secret_resolver, "_PROJECT_ROOT", tmp_path)
    with patch("httpx.Client.get", side_effect=httpx.ReadTimeout("timed out")):
        result = collect_fred_series(retrieved_date="2026-05-06", storage_root=tmp_path, symbols=("DGS10",))
    assert "DGS10" in result.unavailable_symbols
    assert result.points == []


def test_fed_collector_parses_prates_json(tmp_path: Path) -> None:
    payload = json.dumps({"Value": "3.65", "ForDate": "05/13/2026", "EffectiveDate": "12/11/2025", "LastUpdated": "05/12/2026"})
    with patch("httpx.Client.get", return_value=httpx.Response(200, content=payload.encode(), request=httpx.Request("GET", "https://test/"))):
        result = collect_fed_series(retrieved_date="2026-05-13", storage_root=tmp_path)
    assert result.unavailable_symbols == []
    assert result.points[0].symbol == "IORB"
    assert result.points[0].value == 3.65


def test_fed_collector_marks_unavailable_when_http_fails(tmp_path: Path) -> None:
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("connection refused")):
        result = collect_fed_series(retrieved_date="2026-05-13", storage_root=tmp_path)
    assert "IORB" in result.unavailable_symbols
    assert result.points == []


def test_treasury_collector_parses_fiscaldata_json(tmp_path: Path) -> None:
    payload = json.dumps({"data": [{"record_date": "2026-05-11", "open_today_bal": "839161", "close_today_bal": "null"}, {"record_date": "2026-05-08", "open_today_bal": "809500", "close_today_bal": "null"}]})
    with patch("httpx.Client.get", return_value=httpx.Response(200, content=payload.encode(), request=httpx.Request("GET", "https://test/"))):
        result = collect_treasury_series(retrieved_date="2026-05-13", storage_root=tmp_path)
    assert result.unavailable_symbols == []
    assert len(result.points) == 2
    assert result.points[0].value == pytest.approx(839.161, rel=1e-4)
    assert result.points[1].value == pytest.approx(809.500, rel=1e-4)


def test_treasury_collector_marks_unavailable_when_http_fails(tmp_path: Path) -> None:
    with patch("httpx.Client.get", side_effect=httpx.HTTPStatusError("500", request=object(), response=object())):
        result = collect_treasury_series(retrieved_date="2026-05-13", storage_root=tmp_path)
    assert "TGA" in result.unavailable_symbols
    assert result.points == []


def test_dxy_collector_parses_tradingview_scanner(tmp_path: Path) -> None:
    payload = json.dumps({"data": [{"d": [98.504, 0.21, -1.04, "ICE US Dollar Index"]}]})
    with patch("httpx.Client.post", return_value=httpx.Response(200, content=payload.encode(), request=httpx.Request("POST", "https://test/"))):
        result = collect_dxy_series(retrieved_date="2026-05-13", storage_root=tmp_path)
    assert not result.unavailable_symbols
    assert len(result.points) == 3
    latest = [p for p in result.points if p.date == "2026-05-13"][0]
    assert latest.value == pytest.approx(98.504, rel=1e-4)


def test_dxy_collector_falls_back_to_cnbc(tmp_path: Path) -> None:
    tv_fail = httpx.Response(500, content=b"{}", request=httpx.Request("POST", "https://test/"))
    cnbc_ok = httpx.Response(200, content=json.dumps({"QuickQuoteResult": {"QuickQuote": [{"symbol": ".DXY", "last": "97.927"}]}}).encode(), request=httpx.Request("GET", "https://test/"))
    with patch("httpx.Client.post", return_value=tv_fail), patch("httpx.Client.get", return_value=cnbc_ok):
        result = collect_dxy_series(retrieved_date="2026-05-08", storage_root=tmp_path)
    assert not result.unavailable_symbols
    assert result.points[0].value == pytest.approx(97.927, rel=1e-4)
    assert result.points[0].source == "cnbc"


def test_dxy_collector_marks_unavailable_when_all_sources_fail(tmp_path: Path) -> None:
    with patch("httpx.Client.post", side_effect=httpx.ConnectError("no network")), patch("httpx.Client.get", side_effect=httpx.ConnectError("no network")):
        result = collect_dxy_series(retrieved_date="2026-05-13", storage_root=tmp_path)
    assert "DXY" in result.unavailable_symbols
    assert result.points == []
