from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from apps.parsers.market.tradingview_chart import TradingViewChartParseError, parse_tradingview_chart

FIXTURE = Path("tests/fixtures/research/tradingview_chart_protocol.json")
RETRIEVED_AT = "2026-09-17T11:26:15+00:00"
SOURCE_REF = {"source": "tradingview_chart", "raw_path": "raw/probe.json"}


def _wire(messages: list[dict]) -> list[str]:
    payloads = [json.dumps(message, separators=(",", ":")) for message in messages]
    return ["".join(f"~m~{len(payload.encode('utf-8'))}~m~{payload}" for payload in payloads)]


def _payload() -> dict:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {
        "ticker": fixture["ticker"],
        "resolution": fixture["resolution"],
        "frames": _wire(fixture["messages"]),
    }


def _parse(payload: dict) -> dict:
    return parse_tradingview_chart(
        payload,
        ticker="NYMEX:CL1!",
        resolution="15",
        retrieved_at=RETRIEVED_AT,
        source_ref=SOURCE_REF,
    )


def test_parses_completed_delayed_continuous_futures_series() -> None:
    result = _parse(_payload())

    assert result["status"] == "available"
    assert result["delay_seconds"] == 600
    assert result["front_contract"] == "CLV2026"
    assert result["continuous_contract"] is True
    assert result["metadata"]["update_mode"] == "delayed_streaming_600"
    assert result["bars"][-1] == {
        "time": "2026-09-17T10:45:00+00:00",
        "open": 100.7,
        "high": 100.9,
        "low": 100.5,
        "close": 100.6,
        "volume": 2515.0,
    }


def test_native_gold_four_hour_bars_keep_new_york_session_alignment():
    fixture = json.loads(Path('tests/fixtures/research/tradingview_gold_4h.json').read_text())
    parsed = parse_tradingview_chart(
        {**fixture, 'frames': _wire(fixture['messages'])}, ticker=fixture['ticker'], resolution='240',
        retrieved_at=fixture['retrieved_at'], source_ref=SOURCE_REF)
    assert parsed['resolution_seconds'] == 14400
    assert parsed['metadata']['timezone'] == 'America/New_York'
    assert parsed['metadata']['session'] == '1700-1700'
    assert parsed['bars'][-1]['time'] == '2026-09-28T09:00:00+00:00'
    assert parsed['bars'][-2]['time'] == '2026-09-28T05:00:00+00:00'


def test_native_four_hour_bars_still_reject_subhour_timestamps():
    fixture = json.loads(Path('tests/fixtures/research/tradingview_gold_4h.json').read_text())
    for message in fixture['messages']:
        if message['m'] == 'timescale_update':
            message['p'][1]['s1']['s'][0]['v'][0] += 60
    with pytest.raises(TradingViewChartParseError, match='BarValidationError'):
        parse_tradingview_chart({**fixture,'frames':_wire(fixture['messages'])},
                               ticker=fixture['ticker'],resolution='240',
                               retrieved_at=fixture['retrieved_at'],source_ref=SOURCE_REF)


def test_accepts_missing_volume_and_explicit_completed_delay() -> None:
    payload = _payload()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    messages = fixture["messages"]
    metadata = messages[1]["p"][2]
    metadata.pop("delay")
    messages[2]["p"][1]["s1"]["s"][0]["v"].pop()
    messages[3]["p"][2] = "delayed_streaming_900"
    payload["frames"] = _wire(messages)

    result = _parse(payload)

    assert result["delay_seconds"] == 900
    assert result["bars"][0]["volume"] is None


def test_validates_usdjpy_against_jpy_quote_currency() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    messages = fixture["messages"]
    metadata = messages[1]["p"][2]
    metadata.update(
        pro_name="OANDA:USDJPY",
        base_name=["OANDA:USDJPY"],
        exchange="OANDA",
        type="forex",
        currency_code="JPY",
    )
    metadata.pop("front_contract")
    metadata.pop("delay")
    messages[3]["p"][2] = "streaming"
    payload = {"ticker": "OANDA:USDJPY", "resolution": "15", "frames": _wire(messages)}

    result = parse_tradingview_chart(
        payload,
        ticker="OANDA:USDJPY",
        resolution="15",
        retrieved_at=RETRIEVED_AT,
        source_ref=SOURCE_REF,
    )
    assert result["metadata"]["currency"] == "JPY"
    assert result["delay_seconds"] == 0

    messages[1]["p"][2]["currency_code"] = "USD"
    payload["frames"] = _wire(messages)
    with pytest.raises(TradingViewChartParseError, match="IdentityMismatch"):
        parse_tradingview_chart(
            payload,
            ticker="OANDA:USDJPY",
            resolution="15",
            retrieved_at=RETRIEVED_AT,
            source_ref=SOURCE_REF,
        )


@pytest.mark.parametrize(
    ("mutation", "error_class"),
    [
        (lambda messages: messages[1]["p"][2].update(exchange="CME"), "IdentityMismatch"),
        (lambda messages: messages.pop(), "SeriesIncomplete"),
        (lambda messages: messages[3]["p"].__setitem__(2, "streaming"), "UpdateModeMismatch"),
        (lambda messages: messages.append({"m": "series_error", "p": ["redacted"]}), "ProviderError"),
        (lambda messages: messages[2]["p"][1]["s1"]["s"][0]["v"].__setitem__(2, 99.0), "BarValidationError"),
    ],
)
def test_fails_closed_on_invalid_provider_evidence(mutation, error_class: str) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    messages = copy.deepcopy(fixture["messages"])
    mutation(messages)
    payload = {"ticker": fixture["ticker"], "resolution": fixture["resolution"], "frames": _wire(messages)}

    with pytest.raises(TradingViewChartParseError, match=error_class):
        _parse(payload)


def test_rejects_conflicting_duplicate_bar_and_oversized_timestamp() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    messages = copy.deepcopy(fixture["messages"])
    duplicate = copy.deepcopy(messages[2]["p"][1]["s1"]["s"][0])
    duplicate["v"][5] += 1
    messages[2]["p"][1]["s1"]["s"].append(duplicate)
    with pytest.raises(TradingViewChartParseError, match="BarConflictError"):
        _parse({"ticker": fixture["ticker"], "resolution": fixture["resolution"], "frames": _wire(messages)})

    messages = copy.deepcopy(fixture["messages"])
    messages[2]["p"][1]["s1"]["s"][0]["v"][0] = 10**30
    with pytest.raises(TradingViewChartParseError, match="BarValidationError"):
        _parse({"ticker": fixture["ticker"], "resolution": fixture["resolution"], "frames": _wire(messages)})
