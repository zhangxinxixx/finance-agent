from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.collectors.market.tradingview_chart import collect_tradingview_chart

FIXTURE = Path("tests/fixtures/research/tradingview_chart_protocol.json")


def _fixture_frames() -> list[str]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payloads = [json.dumps(message, separators=(",", ":")) for message in fixture["messages"]]
    return ["".join(f"~m~{len(payload.encode('utf-8'))}~m~{payload}" for payload in payloads)]


def test_collects_and_archives_raw_frames_and_immutable_parsed(tmp_path: Path) -> None:
    calls = []

    def connector(**kwargs):
        calls.append(kwargs)
        return _fixture_frames()

    result = collect_tradingview_chart(
        retrieved_date="2026-09-17",
        storage_root=tmp_path,
        symbols=["NYMEX:CL1!"],
        connector=connector,
    )

    assert calls == [{"ticker": "NYMEX:CL1!", "resolution": "15", "bar_count": 64}]
    assert result["series"][0]["status"] == "available"
    assert result["series"][0]["retrieved_at"] <= result["retrieved_at"]
    assert (tmp_path / result["parsed_path"]).is_file()
    raw_path = tmp_path / result["source_refs"][0]["raw_path"]
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    assert raw["frames"] == _fixture_frames()
    assert raw["retrieved_at"] == result["series"][0]["retrieved_at"]
    assert raw["transport_url"] == "wss://data.tradingview.com/socket.io/websocket"
    assert result["source_refs"][0]["source_url"].endswith("symbol=NYMEX%3ACL1%21")


def test_connector_failure_is_archived_without_exception_text(tmp_path: Path) -> None:
    def connector(**_kwargs):
        raise RuntimeError("secret provider details")

    result = collect_tradingview_chart(
        retrieved_date="2026-09-17",
        storage_root=tmp_path,
        symbols=["NYMEX:CL1!"],
        connector=connector,
    )

    assert result["series"][0]["status"] == "unavailable"
    assert result["series"][0]["error"] == "RuntimeError"
    raw_path = tmp_path / result["source_refs"][0]["raw_path"]
    raw_text = raw_path.read_text(encoding="utf-8")
    assert "secret provider details" not in raw_text
    assert json.loads(raw_text)["error_class"] == "RuntimeError"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"symbols": ["UNKNOWN:X"]},
        {"symbols": ["NYMEX:CL1!"], "resolution": "5"},
        {"symbols": ["NYMEX:CL1!"], "bar_count": 257},
        {"symbols": ["NYMEX:CL1!"], "retrieved_date": "../../escape"},
    ],
)
def test_rejects_out_of_bounds_requests(tmp_path: Path, kwargs: dict) -> None:
    request = {"retrieved_date": "2026-09-17", "symbols": ["NYMEX:CL1!"]}
    request.update(kwargs)
    with pytest.raises(ValueError):
        collect_tradingview_chart(storage_root=tmp_path, connector=lambda **_: [], **request)


def test_slow_successful_handshake_has_time_to_read_series(monkeypatch):
    from apps.collectors.market.tradingview_chart import _request_chart_frames
    class Socket:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def send(self,value):pass
        def recv(self,timeout):return _fixture_frames()[0]
    def connect(*args,**kwargs):
        # Reproduce the measured ten-second connection without sleeping.
        if kwargs['open_timeout'] < 10:
            raise TimeoutError('handshake')
        return Socket()
    monkeypatch.setattr('websockets.sync.client.connect',connect)
    assert _request_chart_frames(ticker='NYMEX:CL1!',resolution='15',bar_count=64) == _fixture_frames()
