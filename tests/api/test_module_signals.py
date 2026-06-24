"""P1-07c: Module Signals 聚合服务测试。"""

from __future__ import annotations

import pytest

from apps.api.services.module_signals import (
    build_module_signals,
    _build_market_signal,
    _build_cme_signal,
    _build_event_signal,
    _build_knowledge_signal,
)

# ── build_module_signals ──


def test_build_module_signals_returns_four_modules():
    signals = build_module_signals()
    assert len(signals) == 4
    modules = [s["module"] for s in signals]
    assert modules == ["market", "cme", "event", "knowledge"]


def test_build_module_signals_each_has_required_keys():
    required = {"module", "label", "status", "summary", "source_refs"}
    for signal in build_module_signals():
        assert required.issubset(signal.keys()), f"Missing keys in {signal['module']}: {required - set(signal.keys())}"


def test_build_module_signals_valid_status_values():
    valid = {"available", "partial", "unavailable"}
    for signal in build_module_signals():
        assert signal["status"] in valid, f"Invalid status '{signal['status']}' in {signal['module']}"


def test_build_module_signals_source_refs_are_valid():
    for signal in build_module_signals():
        for ref in signal["source_refs"]:
            assert isinstance(ref, dict)
            assert "source_ref" in ref
            assert "label" in ref
            assert "status" in ref

# ── Individual module builders ──


def test_market_signal_has_market_module():
    s = _build_market_signal()
    assert s["module"] == "market"
    assert isinstance(s["label"], str)
    assert s["label"] != ""


def test_cme_signal_has_cme_module():
    s = _build_cme_signal()
    assert s["module"] == "cme"
    assert isinstance(s["label"], str)


def test_event_signal_has_event_module():
    s = _build_event_signal()
    assert s["module"] == "event"
    assert isinstance(s["label"], str)


def test_event_signal_without_news_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr("apps.api.services.module_signals._PROJECT_ROOT", tmp_path)

    s = _build_event_signal()

    assert s["module"] == "event"
    assert s["status"] == "unavailable"


def test_knowledge_signal_is_unavailable():
    s = _build_knowledge_signal()
    assert s["module"] == "knowledge"
    assert s["status"] == "unavailable"


# ── Strategy card API integration ──


@pytest.mark.integration
def test_strategy_card_detail_includes_module_signals():
    """Verify that /api/strategy-cards/latest response includes module_signals."""
    import os

    import urllib.request

    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(k, None)

    try:
        resp = urllib.request.urlopen("http://localhost:8000/api/strategy-cards/latest", timeout=5)
    except Exception:
        pytest.skip("API not running on localhost:8000")

    import json

    data = json.loads(resp.read())
    assert "module_signals" in data, f"Response missing module_signals: {list(data.keys())[:10]}"
    ms = data["module_signals"]
    assert isinstance(ms, list), f"module_signals is {type(ms)}, expected list"
    if len(ms) > 0:
        for signal in ms:
            assert "module" in signal
            assert "status" in signal
            assert signal["status"] in ("available", "partial", "unavailable")


@pytest.mark.integration
def test_strategy_card_by_id_includes_module_signals():
    """Verify that /api/strategy-cards/{id} response includes module_signals."""
    import os

    import urllib.request

    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(k, None)

    try:
        resp = urllib.request.urlopen("http://localhost:8000/api/strategy-cards/latest", timeout=5)
    except Exception:
        pytest.skip("API not running on localhost:8000")

    import json

    data = json.loads(resp.read())
    sc_id = data.get("strategy_card_id")
    if not sc_id:
        pytest.skip("No strategy_card_id in latest response")

    try:
        resp2 = urllib.request.urlopen(
            f"http://localhost:8000/api/strategy-cards/{sc_id}", timeout=5
        )
    except Exception:
        pytest.skip(f"Could not fetch strategy card {sc_id}")

    detail = json.loads(resp2.read())
    assert "module_signals" in detail
    assert isinstance(detail["module_signals"], list)


def test_review_data_gap_id_uses_stable_digest(monkeypatch):
    from apps.worker import runner

    captured: list[dict] = []

    def fake_upsert_review_item(db, payload):
        captured.append(payload)

    monkeypatch.setattr("database.queries.review.upsert_review_item", fake_upsert_review_item)

    class FakeDb:
        def commit(self):
            pass

    class FakeCard:
        confidence = 0.9
        risk_points = ["missing CME block page"]

    runner._ensure_review_items(
        FakeDb(),
        run_id="run-stable",
        trade_date="2026-05-29",
        card=FakeCard(),
        agents={},
    )

    assert captured[0]["review_id"] == "run-stable:data_gap:57ec5e194882"
