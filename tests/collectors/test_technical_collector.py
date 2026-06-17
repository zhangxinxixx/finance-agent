from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from apps.collectors.technical.collector import collect_technical
from apps.runtime import secret_resolver


def _sse_result(structured_content: dict) -> str:
    return "data:" + json.dumps({"result": {"structuredContent": structured_content}}) + "\n\n"


def test_technical_collector_prefers_jin10_xauusd_quote(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JIN10_MCP_KEY", "test-key")

    def fake_post(self, url, *, json=None, headers=None):
        method = (json or {}).get("method")
        if method == "initialize":
            return httpx.Response(200, content=b"{}", headers={"Mcp-Session-Id": "sid"}, request=httpx.Request("POST", url))
        if method == "notifications/initialized":
            return httpx.Response(202, content=b"{}", request=httpx.Request("POST", url))
        if method == "tools/call":
            params = (json or {}).get("params") or {}
            assert params["name"] == "get_quote"
            assert params["arguments"] == {"code": "XAUUSD"}
            return httpx.Response(
                200,
                content=_sse_result({
                    "status": 200,
                    "data": {
                        "code": "XAUUSD",
                        "name": "现货黄金",
                        "close": "4508.11",
                        "open": "4547.18",
                        "high": "4570.76",
                        "low": "4505.15",
                        "ups_percent": "-0.79",
                        "ups_price": "-35.70",
                        "time": "2026-05-21T20:22:33+08:00",
                    },
                }).encode(),
                request=httpx.Request("POST", url),
            )
        raise AssertionError(f"unexpected method: {method}")

    with patch("httpx.Client.post", new=fake_post), patch("httpx.Client.get") as yahoo_get:
        result = collect_technical(retrieved_date="2026-05-21", storage_root=tmp_path)

    yahoo_get.assert_not_called()
    assert result.unavailable_symbols == []
    assert len(result.points) == 1
    point = result.points[0]
    assert point.symbol == "XAUUSD"
    assert point.value == pytest.approx(4508.11)
    assert point.source == "jin10_quote"
    assert point.date == "2026-05-21"
    ref = result.source_refs[0]
    assert ref["source"] == "jin10_quote"
    assert ref["notes"]["open"] == 4547.18
    assert ref["notes"]["change_pct"] == -0.79


def test_technical_collector_falls_back_to_yahoo_when_jin10_missing_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("JIN10_MCP_KEY", raising=False)
    monkeypatch.delenv("SETTINGS_MASTER_KEY", raising=False)
    monkeypatch.setattr(secret_resolver, "_PROJECT_ROOT", tmp_path)
    payload = {
        "chart": {
            "result": [{
                "meta": {"regularMarketPrice": 4510.5, "chartPreviousClose": 4500.0},
                "indicators": {"quote": [{"close": [4490.0, 4510.5], "open": [4480.0, 4501.0], "high": [4520.0, 4525.0], "low": [4475.0, 4495.0]}]},
            }]
        }
    }
    response = httpx.Response(200, content=json.dumps(payload).encode(), request=httpx.Request("GET", "https://test/"))

    with patch("httpx.Client.get", return_value=response):
        result = collect_technical(retrieved_date="2026-05-21", storage_root=tmp_path)

    assert result.unavailable_symbols == []
    assert result.points[0].source == "yahoo_finance"
    assert result.points[0].value == 4510.5
