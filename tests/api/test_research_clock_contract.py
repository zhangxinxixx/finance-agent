from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from apps.api.main import app
from apps.api.schemas.report import ReportDetail
from apps.api.services import readiness_service, report_service
from apps.api.services.research_identity import build_research_identity


NOW = datetime(2026, 10, 9, 8, tzinfo=timezone.utc)


def identity(**updates):
    snapshot = {"snapshot_id": "snap-1", "run_id": "run-1", "trade_date": "2026-10-09",
                "snapshot_time": "2026-10-09T07:00:00+00:00",
                "gold_workflow": {"key_levels": [{"status": "Active", "valid_until": "2026-10-09T12:00:00Z",
                    "source_refs": [{"source": "twelvedata"}], "eligible_for_target": True}]}}
    snapshot.update(updates)
    return build_research_identity(report_id="report-1", run_id="run-1", snapshot_id="snap-1",
        trade_date="2026-10-09", snapshot=snapshot, generated_at="2026-10-09T08:00:00Z", now=NOW)


def test_research_time_is_frozen_data_time_not_generation_time():
    result = identity()
    assert result["data_as_of"] == "2026-10-09T07:00:00+00:00"
    assert result["generated_at"] == "2026-10-09T08:00:00+00:00"
    assert result["research_version"] == "snap-1"
    assert result["key_level_validity"]["status"] == "active"


def test_mismatched_snapshot_cannot_supply_data_time():
    result = identity(run_id="different-run")
    assert result["data_as_of"] is None
    assert result["key_level_validity"]["status"] == "unavailable"


def test_unknown_and_expired_level_windows_are_not_current():
    assert identity(gold_workflow={"key_levels": [{"status": "Active"}]})["key_level_validity"]["status"] == "unavailable"
    assert identity(gold_workflow={"key_levels": [{"status": "Active", "valid_until": "2026-10-09T07:59:59Z"}]})["key_level_validity"]["status"] == "expired"
    assert identity(snapshot_time="2026-10-09T07:00:00")["key_level_validity"]["status"] == "unavailable"


def test_latest_background_does_not_overwrite_original_report(monkeypatch):
    old = {"as_of": "2026-10-01", "summary": "original"}
    latest = {"as_of": "2026-10-09", "summary": "new"}
    detail = ReportDetail(report_id="r", family="macro", title="历史研究", structured_payload={"gold_macro_overview": old})
    monkeypatch.setattr(report_service._detail, "get_gold_mainlines_latest", lambda **kwargs: {"gold_macro_overview": latest})
    result = report_service._enrich_report_detail_with_gold_macro_context(detail)
    assert result.gold_macro_overview == old
    assert result.structured_payload == detail.structured_payload
    assert result.current_context["gold_macro_overview"] == latest
    assert result.current_context["relationship"] == "current_context_only"
    monkeypatch.setattr(report_service._detail, "get_gold_mainlines_latest", lambda **kwargs: {})
    unavailable = report_service._enrich_report_detail_with_gold_macro_context(detail)
    assert unavailable.gold_macro_overview == old
    assert unavailable.current_context is None


def test_liveness_does_not_claim_database_readiness(monkeypatch):
    def fail():
        raise OperationalError("secret-db-url", {}, Exception("secret"))
    monkeypatch.setattr(readiness_service, "_probe_database", fail)
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "secret" not in response.text
    monkeypatch.setattr(readiness_service, "_probe_database", lambda: None)
    assert client.get("/ready").status_code == 200


def test_empty_database_is_not_ready_and_probe_does_not_create_schema(tmp_path, monkeypatch):
    from database.models import engine as engine_module
    from sqlalchemy import inspect

    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.setattr(engine_module, "engine", engine)
    assert readiness_service.get_readiness()["status"] == "not_ready"
    assert inspect(engine).get_table_names() == []
