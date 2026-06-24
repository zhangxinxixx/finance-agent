"""P4-09: Market odds API tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


# ── Fixtures: create a temp analysis snapshot with market_odds ──────────


@pytest.fixture
def temp_storage_with_market_odds(tmp_path: Path, monkeypatch):
    """Create a fake storage tree with a premarket_snapshot containing market_odds."""
    snap_dir = tmp_path / "storage" / "features" / "snapshots" / "XAUUSD" / "2026-05-16" / "test-run"
    snap_dir.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "version": "1.0",
        "snapshot_id": "XAUUSD:2026-05-16:test-run",
        "asset": "XAUUSD",
        "trade_date": "2026-05-16",
        "run_id": "test-run",
        "market_odds": {
            "status": "partial",
            "aggregate_signal": "bullish",
            "aggregate_confidence": 0.45,
            "events": [
                {
                    "event_id": "gold_above_2500",
                    "event_name": "Gold > $2500",
                    "event_type": "price_target",
                    "target_value": 2500,
                    "signal_label": "bullish",
                    "final_probability": 0.60,
                    "confidence": 0.5,
                    "reliability_score": 0.45,
                    "divergence_score": 0.1,
                    "interpretation": "Market assigns elevated probability.",
                    "probabilities": {
                        "cme_options": {"probability": 0.60, "confidence": 0.5},
                        "polymarket": {"probability": None, "confidence": 0.0},
                        "bloomberg": {"probability": None, "confidence": 0.0},
                        "internal_model": {"probability": None, "confidence": 0.0},
                    },
                    "status": "available",
                },
                {
                    "event_id": "fed_rate_jun_2026",
                    "event_name": "Fed Rate Cut by Jun 2026",
                    "event_type": "rate_cut",
                    "signal_label": "unavailable",
                    "status": "unavailable",
                    "interpretation": "Placeholder: FedWatch collector not yet implemented.",
                    "probabilities": {},
                },
            ],
            "source_refs": [{"source": "cme_options_delta_grid"}],
        },
    }
    (snap_dir / "premarket_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )

    # Override _PROJECT_ROOT in data_service
    import apps.api.data_service as ds

    monkeypatch.setattr(ds, "_PROJECT_ROOT", tmp_path)

    return tmp_path


# ── Tests ───────────────────────────────────────────────────────────────


def test_market_odds_snapshot_returns_data(temp_storage_with_market_odds):
    resp = client.get("/api/market-odds/snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "partial"
    assert data["aggregate_signal"] == "bullish"
    assert len(data["events"]) == 2


def test_market_odds_report_returns_structured(temp_storage_with_market_odds):
    resp = client.get("/api/market-odds/report")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "aggregate_signal" in data
    assert "source_status" in data
    assert "available_events" in data
    assert "unavailable_events" in data

    # Available events should have the CME event
    assert len(data["available_events"]) == 1
    assert data["available_events"][0]["event_id"] == "gold_above_2500"

    # Unavailable should have the Fed event
    assert len(data["unavailable_events"]) == 1
    assert "fed_rate" in data["unavailable_events"][0]["event_id"]

    # Source status: cme_options available, others unavailable
    assert data["source_status"]["cme_options"] == "available"
    assert data["source_status"].get("polymarket") == "unavailable"


def test_market_odds_snapshot_404_no_data(tmp_path: Path, monkeypatch):
    """Snapshot without data returns 404."""
    import apps.api.data_service as ds
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(ds, "_PROJECT_ROOT", tmp_path)
    resp = client.get("/api/market-odds/snapshot")
    assert resp.status_code == 404


def test_market_odds_report_unavailable_when_no_data(tmp_path: Path, monkeypatch):
    """Report without data returns 200 with 'unavailable' status."""
    import apps.api.data_service as ds
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(ds, "_PROJECT_ROOT", tmp_path)
    resp = client.get("/api/market-odds/report")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unavailable"
    assert data["available_events"] == []


def test_market_odds_report_with_unavailable_market_odds(
    tmp_path: Path, monkeypatch,
):
    """When market_odds is explicitly unavailable, report should reflect that."""
    snap_dir = tmp_path / "storage" / "features" / "snapshots" / "XAUUSD" / "2026-05-16" / "test-run"
    snap_dir.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "version": "1.0",
        "snapshot_id": "XAUUSD:2026-05-16:test-run",
        "market_odds": {"status": "unavailable", "events": []},
    }
    (snap_dir / "premarket_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )

    import apps.api.data_service as ds

    monkeypatch.setattr(ds, "_PROJECT_ROOT", tmp_path)

    resp = client.get("/api/market-odds/report")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unavailable"
    assert data["aggregate_signal"] == "unavailable"
    assert data["available_events"] == []


def test_market_odds_no_snapshot_file_returns_none(tmp_path: Path, monkeypatch):
    """No data at all should return None/404."""
    # Override with empty tmp_path
    import apps.api.data_service as ds

    monkeypatch.setattr(ds, "_PROJECT_ROOT", tmp_path)

    # Ensure storage dir doesn't exist
    resp = client.get("/api/market-odds/snapshot")
    assert resp.status_code == 404


def test_market_odds_report_fields_not_none(temp_storage_with_market_odds):
    """All report fields should be non-None / valid."""
    resp = client.get("/api/market-odds/report")
    data = resp.json()

    for event in data["available_events"]:
        assert event["event_id"] is not None
        assert event["event_name"] is not None
        assert event["final_probability"] is not None
        assert isinstance(event["final_probability"], (int, float))
        assert 0.0 <= event["final_probability"] <= 1.0
