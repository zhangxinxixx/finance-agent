from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from apps.collectors.twelvedata import (
    TwelveDataClient,
    TwelveDataPayloadError,
    TwelveDataQuotaError,
)


NOW = datetime(2026, 7, 16, 10, 5, tzinfo=UTC)


def _client(tmp_path, *, payload: dict, status_code: int = 200, headers: dict[str, str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "apikey test-key"
        return httpx.Response(status_code, json=payload, headers=headers or {}, request=request)

    return TwelveDataClient(
        api_key="test-key",
        storage_root=tmp_path,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )


def _ok_payload() -> dict:
    return {
        "meta": {"symbol": "XAU/USD", "interval": "5min", "type": "Precious Metal"},
        "values": [
            {"datetime": "2026-07-16 10:00:00", "open": "4031", "high": "4033", "low": "4030", "close": "4032"},
            {"datetime": "2026-07-16 09:55:00", "open": "4029", "high": "4032", "low": "4028", "close": "4031"},
        ],
        "status": "ok",
    }


def test_fetch_time_series_archives_raw_and_parses_ascending_candles(tmp_path):
    client = _client(
        tmp_path,
        payload=_ok_payload(),
        headers={"Api-Credits-Used": "3", "Api-Credits-Left": "5", "Api-Credits-Request": "1"},
    )

    result = client.fetch_time_series(interval="5min", outputsize=20)

    assert result.timeframe == "5m"
    assert [item.open_time.isoformat() for item in result.candles] == [
        "2026-07-16T09:55:00+00:00",
        "2026-07-16T10:00:00+00:00",
    ]
    assert result.credits_used == 3
    assert result.credits_left == 5
    assert result.source_ref()["instrument_type"] == "composite_otc_spot_proxy"

    raw_file = tmp_path / result.raw_path
    archived = json.loads(raw_file.read_text(encoding="utf-8"))
    assert archived["request"]["interval"] == "5min"
    assert archived["response_headers"]["api-credits-left"] == "5"
    assert "test-key" not in raw_file.read_text(encoding="utf-8")


def test_fetch_time_series_archives_and_raises_quota_error(tmp_path):
    client = _client(
        tmp_path,
        payload={"code": 429, "message": "API credits exhausted", "status": "error"},
        status_code=429,
        headers={"Api-Credits-Left": "0"},
    )

    with pytest.raises(TwelveDataQuotaError):
        client.fetch_time_series(interval="15min")

    raw_files = list((tmp_path / "raw" / "market" / "twelvedata" / "2026-07-16").glob("*.json"))
    assert len(raw_files) == 1
    assert json.loads(raw_files[0].read_text(encoding="utf-8"))["http_status"] == 429


def test_fetch_time_series_rejects_invalid_ohlc_after_archival(tmp_path):
    payload = _ok_payload()
    payload["values"][0]["high"] = "4020"
    client = _client(tmp_path, payload=payload)

    with pytest.raises(TwelveDataPayloadError, match="invalid OHLC"):
        client.fetch_time_series(interval="5min")

    assert len(list((tmp_path / "raw" / "market" / "twelvedata" / "2026-07-16").glob("*.json"))) == 1


def test_client_requires_configured_key(tmp_path, monkeypatch):
    monkeypatch.setattr("apps.collectors.twelvedata.client.resolve_runtime_secret", lambda _: None)
    with pytest.raises(RuntimeError, match="TWELVE_DATA_API_KEY"):
        TwelveDataClient(storage_root=tmp_path)
