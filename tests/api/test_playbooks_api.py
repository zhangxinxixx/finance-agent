"""TDD: Playbook registry API contract."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from database.models.analysis import ensure_analysis_tables
from database.models.engine import get_db


def _make_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def test_create_and_list_playbook_templates() -> None:
    client = _make_client()

    response = client.post(
        "/api/playbooks",
        json={
            "playbook_id": "pb-range-breakout-long",
            "version": "v1.0",
            "status": "draft",
            "title": "Range breakout long",
            "summary": "Use when price breaks the upper range with confirmation.",
            "conditions": ["price_breaks_range_high", "volume_confirms"],
            "actions": ["watch", "confirm", "avoid_chasing"],
            "invalidations": ["wallscore_too_high"],
            "source_refs": [{"source_ref": "playbook.range_breakout"}],
            "last_validated": "2026-05-30T08:00:00Z",
            "actor": "automation",
            "request_id": "pb-create-001",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["playbook_id"] == "pb-range-breakout-long"
    assert data["version"] == "v1.0"
    assert data["status"] == "draft"

    listing = client.get("/api/playbooks")
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["items"][0]["playbook_id"] == "pb-range-breakout-long"
    assert payload["items"][0]["version"] == "v1.0"


def test_playbook_detail_returns_history() -> None:
    client = _make_client()
    client.post(
        "/api/playbooks",
        json={
            "playbook_id": "pb-range-breakout-long",
            "version": "v1.0",
            "status": "draft",
            "title": "Range breakout long",
            "summary": "Use when price breaks the upper range with confirmation.",
            "conditions": ["price_breaks_range_high", "volume_confirms"],
            "actions": ["watch", "confirm", "avoid_chasing"],
            "invalidations": ["wallscore_too_high"],
            "source_refs": [{"source_ref": "playbook.range_breakout"}],
            "actor": "automation",
            "request_id": "pb-create-001",
        },
    )
    client.post(
        "/api/playbooks",
        json={
            "playbook_id": "pb-range-breakout-long",
            "version": "v1.1",
            "status": "candidate",
            "title": "Range breakout long v1.1",
            "summary": "Updated template with tighter invalidations.",
            "conditions": ["price_breaks_range_high", "volume_confirms"],
            "actions": ["watch", "confirm", "avoid_chasing"],
            "invalidations": ["wallscore_too_high", "volume_drops"],
            "source_refs": [{"source_ref": "playbook.range_breakout"}],
            "actor": "automation",
            "request_id": "pb-create-002",
        },
    )

    response = client.get("/api/playbooks/pb-range-breakout-long")

    assert response.status_code == 200
    data = response.json()
    assert data["playbook_id"] == "pb-range-breakout-long"
    assert data["version"] == "v1.1"
    assert data["versions"][0]["version"] == "v1.1"
    assert data["versions"][1]["version"] == "v1.0"


def test_duplicate_playbook_version_returns_conflict() -> None:
    client = _make_client()
    payload = {
        "playbook_id": "pb-range-breakout-long",
        "version": "v1.0",
        "status": "draft",
        "title": "Range breakout long",
        "summary": "Use when price breaks the upper range with confirmation.",
        "conditions": ["price_breaks_range_high"],
        "actions": ["watch"],
        "invalidations": [],
        "source_refs": [{"source_ref": "playbook.range_breakout"}],
        "actor": "automation",
        "request_id": "pb-create-001",
    }
    first = client.post("/api/playbooks", json=payload)
    second = client.post("/api/playbooks", json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
