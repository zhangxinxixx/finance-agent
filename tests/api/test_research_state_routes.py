from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.routes.research_state_routes import router
from apps.api.routes.research_state_routes import research_source_health
from database.models.analysis import ensure_analysis_tables
from database.models.engine import get_db


def test_read_state_empty_is_explicit_and_route_cannot_accept():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    app = FastAPI()
    app.include_router(router)

    def db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = db
    with TestClient(app) as client:
        r = client.get("/api/gold/research-state")
        assert r.status_code == 200
        assert r.json()["accepted"]["status"] == "initialization_required"
        assert r.json()["automatic_trading_allowed"] is False
        assert client.post("/api/gold/research-state", json={"accepted_state": "S5"}).status_code == 405


def test_source_health_route_preserves_recorded_judgment_and_exposes_current_fields():
    record = {
        "source_key": "fedwatch",
        "status": "not_configured",
        "configured": False,
        "error_message": None,
        "source_metadata": {
            "source_key": "fedwatch",
            "collector_status": "not_configured",
            "source_health": "FAILED",
            "staleness": "unknown",
            "reason": "fedwatch_collector_not_configured",
        },
    }

    with patch(
        "database.queries.data_source_status.list_data_source_statuses",
        return_value=[record],
    ) as query:
        payload = research_source_health(db=object())

    query.assert_called_once()
    assert query.call_args.kwargs == {"source_group": "gold_core"}
    assert payload["schema_version"] == "gold_core_source_health_view.v2"
    assert payload["evaluated_at"]
    assert payload["items"][0]["source_key"] == "fedwatch"
    assert payload["items"][0]["recorded_source_health"] == "FAILED"
    assert payload["items"][0]["recorded_staleness"] == "unknown"
    assert payload["items"][0]["current"]["source_health"] == "FAILED"
