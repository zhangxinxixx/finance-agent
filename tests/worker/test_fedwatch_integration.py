"""Isolated normalized-data replay; success cases use synthetic probabilities."""
from copy import deepcopy
from datetime import UTC, datetime
import json
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.routes.fedwatch_routes import router
from apps.features.macro.fedwatch_policy import project_fedwatch_policy
from apps.features.macro.fedwatch import build_fedwatch_factors
from apps.features.research.source_health import build_core_source_health
from apps.renderer.markdown.research_evidence import policy_path_table
from apps.worker.fedwatch import fedwatch_view, refresh_fedwatch
from database.models.engine import get_db
from database.models.fedwatch import FedWatchProbability, ensure_fedwatch_tables
from database.queries.fedwatch import save_fedwatch_snapshot
from tests.features.test_fedwatch import NOW, TARGET, snapshot


@pytest.fixture
def db(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 29, tzinfo=UTC)
    monkeypatch.setattr("apps.api.routes.fedwatch_routes.datetime", Clock)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ensure_fedwatch_tables(engine)
    from database.models.task import TaskRun, TaskStep
    from database.models.warehouse import ensure_warehouse_tables
    from database.models.raw_source import RawSourceBase

    TaskRun.__table__.create(engine, checkfirst=True)
    TaskStep.__table__.create(engine, checkfirst=True)
    ensure_warehouse_tables(engine)
    RawSourceBase.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seeded(db):
    s = snapshot()
    s["target_reference"] = deepcopy(TARGET)
    factor = build_fedwatch_factors(s, as_of=NOW, target_reference=TARGET)
    save_fedwatch_snapshot(db, s, factor=factor)
    db.commit()
    return s


def test_api_reads_persisted_factors_without_network_and_rechecks_age(db):
    s = seeded(db)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        query = {"as_of": NOW}
        latest = client.get("/api/market/fedwatch/latest", params=query)
        assert latest.status_code == 200, latest.text
        body = latest.json()
        assert body["snapshot_id"] == s["snapshot_id"]
        assert body["next_meeting"]["expected_change_bp"] == pytest.approx(15)
        assert body["repricing"]["direction"] == "hawkish"
        assert body["next_meeting"]["prob_above_current_target"] == pytest.approx(.6)
        assert body["quality_summary"]["comparison_coverage"]["current"] == 4
        assert body["quality_summary"]["raw_hash_verified"] is None
        assert client.get("/api/market/fedwatch/health", params=query).json()["quality_summary"] == body["quality_summary"]
        for endpoint in ("health", "meetings", "history", "repricing"):
            assert client.get("/api/market/fedwatch/"+endpoint, params=query).status_code == 200
        stale = client.get("/api/market/fedwatch/latest", params={"as_of": "2026-09-28T14:00:00Z"}).json()
        assert stale["source_health"]["status"] == "stale"
        assert stale["repricing"]["direction"] is None
        assert client.get("/api/market/fedwatch/history?limit=9999").status_code == 422
        assert client.get("/api/market/fedwatch/latest?as_of=2026-09-28T00:00:00").status_code == 422
    assert db.scalar(select(func.count()).select_from(FedWatchProbability)) == 32


def test_latest_failed_attempt_degrades_cached_data_even_inside_sla(db):
    s = seeded(db)
    failed = {**s, "snapshot_id": str(uuid4()), "collected_at": "2026-09-28T12:01:00Z",
              "parse_status": "missing", "reason": "upstream_403", "rows": [], "as_of": None}
    view = fedwatch_view(s, latest_attempt=failed, as_of="2026-09-28T12:02:00Z")
    assert view["source_health"]["status"] == "stale"
    assert view["source_health"]["actionable"] is False
    assert view["factor"]["repricing"]["direction"] is None
    assert view["next_meeting"] is not None


def test_page_factor_never_promotes_blocked_health_or_hides_a_failed_attempt(db):
    from apps.api.services.fedwatch_read_model_service import get_latest_fedwatch_factor_view
    from database.models.fedwatch import FedWatchFactor

    s = seeded(db)
    factor = db.scalars(select(FedWatchFactor)).one()
    payload = deepcopy(factor.payload)
    payload["health"].update(status="parse_failed", actionable=False, reason="quality_rejected")
    factor.payload = payload
    db.commit()
    view = get_latest_fedwatch_factor_view(db, as_of=NOW, allowed_staleness_seconds=3600)
    assert view["source_health"]["status"] == "parse_failed"
    assert view["source_health"]["actionable"] is False
    assert view["repricing"]["direction"] is None

    failed = {**s, "snapshot_id": str(uuid4()), "collected_at": "2026-09-28T12:01:00Z",
              "parse_status": "missing", "reason": "upstream_403", "rows": [], "as_of": None}
    save_fedwatch_snapshot(db, failed)
    db.commit()
    view = get_latest_fedwatch_factor_view(db, as_of="2026-09-28T12:02:00Z", allowed_staleness_seconds=3600)
    assert view["source_health"]["reason"] == "latest_collection_failed_cached_snapshot"
    assert view["source_health"]["actionable"] is False
    assert "rows" not in view["latest_attempt"]


def test_macro_health_and_report_trace(db):
    s = seeded(db)
    view = fedwatch_view(s, latest_attempt=s, as_of=NOW)
    policy = project_fedwatch_policy(view, as_of=NOW)
    text = policy_path_table(policy)
    assert s["snapshot_id"] in text and "偏鹰" in text and "1M" in text
    assert policy["policy_path"]["rows"][1]["meeting_date"] == "2026-12-09"
    report = {"macro": {"data": {"fedwatch": view}}, "snapshot_time": NOW}
    health = build_core_source_health(report)
    assert next(r for r in health["items"] if r["source_key"] == "fedwatch")["source_health"] == "HEALTHY"
    report["snapshot_time"] = "2026-09-28T14:00:00Z"
    assert next(r for r in build_core_source_health(report)["items"] if r["source_key"] == "fedwatch")["source_health"] == "FAILED"


def test_worker_raw_to_parsed_factor_db_and_poll_cache(db, tmp_path):
    s = snapshot()
    raw = tmp_path / "raw/synthetic.json"
    raw.parent.mkdir()
    raw.write_text(json.dumps(s))
    calls = []
    def collector(**kwargs):
        calls.append(1)
        return deepcopy(s)
    def target_collector(**kwargs): return {"status": "available", "reference": TARGET}
    args = dict(storage_root=tmp_path, now=NOW, collector=collector, target_collector=target_collector)
    view = refresh_fedwatch(db, **args)
    db.commit()
    assert view["source_health"]["status"] == "fresh"
    refresh_fedwatch(db, **args)
    assert len(calls) == 1
    assert (tmp_path / "features/fedwatch" / (s["snapshot_id"]+".json")).exists()
    from dagster_finance.jobs.fedwatch_job import run_fedwatch_refresh
    from database.models.task import TaskRun, TaskStep
    run = run_fedwatch_refresh(db, **args)
    assert run["task_run_id"]
    assert db.get(TaskRun, UUID(run["task_run_id"])) is not None
    assert db.scalar(select(func.count()).select_from(TaskStep).where(
        TaskStep.task_run_id == UUID(run["task_run_id"]),
    )) == 1


def test_empty_store_and_historical_cutoff(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get("/api/market/fedwatch/health").json()["status"] == "missing"
        seeded(db)
        response = client.get("/api/market/fedwatch/latest", params={"as_of": "2026-09-27T00:00:00Z"})
        assert response.json()["snapshot_id"] is None


def test_scheduled_refresh_does_not_skip_due_to_collection_duration(db, tmp_path):
    s = seeded(db)  # a preceding run finished seconds after its schedule slot
    calls = []

    def collector(**kwargs):
        calls.append(1)
        value = deepcopy(s)
        value.update(snapshot_id=str(uuid4()), collected_at="2026-09-28T12:29:55Z")
        return value

    args = dict(storage_root=tmp_path, now="2026-09-28T12:29:55Z",
                scheduled_for="2026-09-28T12:29:50Z", collector=collector,
                target_collector=lambda **kwargs: {"reference": TARGET})
    refresh_fedwatch(db, **args)
    db.commit()
    refresh_fedwatch(db, **args)  # same slot is idempotent
    assert len(calls) == 1
    with pytest.raises(ValueError, match="schedule_in_future"):
        refresh_fedwatch(db, **{**args, "scheduled_for": "2026-09-28T13:00:00Z"})


def test_schedule_passes_slot_to_worker(monkeypatch):
    from dagster import build_schedule_context, validate_run_config
    from dagster_finance.jobs.fedwatch_job import fedwatch_refresh_job
    from dagster_finance.schedules.fedwatch_schedule import fedwatch_free_schedule

    monkeypatch.setenv("FEDWATCH_POLL_INTERVAL_MINUTES", "30")
    at = datetime(2026, 9, 28, 12, 30, tzinfo=UTC)
    request = fedwatch_free_schedule(build_schedule_context(scheduled_execution_time=at))
    assert request.run_config["ops"]["fedwatch_refresh_op"]["config"]["scheduled_for"] == at.isoformat()
    validate_run_config(fedwatch_refresh_job, request.run_config)


def test_worker_records_failed_collection_without_persisting_a_market_factor(db, tmp_path):
    from dagster_finance.jobs.fedwatch_job import run_fedwatch_refresh
    from database.models.task import TaskRun, TaskStatus
    from database.queries.fedwatch import get_latest_fedwatch_snapshot

    failed = {**snapshot(), "parse_status": "missing", "as_of": None,
              "rows": [], "reason": "official_parent_unavailable"}
    view = run_fedwatch_refresh(
        db, storage_root=tmp_path, now=NOW, force=True,
        collector=lambda **kwargs: deepcopy(failed),
        target_collector=lambda **kwargs: {"status": "unavailable"},
    )
    assert db.get(TaskRun, UUID(view["task_run_id"])).status == TaskStatus.degraded
    assert view["source_health"]["status"] == "missing"
    assert view["repricing"]["direction"] is None
    latest = get_latest_fedwatch_snapshot(db, as_of=NOW, valid_only=False)
    assert latest["snapshot_id"] == failed["snapshot_id"]
    assert latest["parse_status"] == "missing"
    assert get_latest_fedwatch_snapshot(db, as_of=NOW, valid_only=True) is None
