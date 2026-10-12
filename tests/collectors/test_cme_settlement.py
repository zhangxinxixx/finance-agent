from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path

import pytest
from curl_cffi import requests
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.collectors.macro.cme_fed_funds import CMEFedFundsSettlementProvider
from apps.parsers.macro.cme_fed_funds import parse_settlements
from apps.worker.cme_settlement import run_settlement_ingestion
from database.models.cme_settlement import CmeSettlementSnapshot, CmeSettlementContract
from database.models.task import TaskRun, TaskStep, TaskStatus
from database.queries.cme_settlement import (
    expected_trade_date,
    preferred_settlement,
    save_settlement,
    settlement_health,
    settlement_stability,
)

RAW = Path("tests/fixtures/cme_settlement/20260925-final.json").read_bytes()
DAY = date(2026, 9, 25)
NOW = datetime(2026, 9, 28, 14, tzinfo=UTC)


class Response:
    def __init__(self, body=RAW, status=200):
        self.body, self.status_code = body, status
        self.headers = {"content-type": "application/json"}

    def iter_content(self):
        yield self.body


class Client:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    @contextmanager
    def stream(self, method, url, **kwargs):
        assert method == "GET" and "tradeDate=" in url
        assert kwargs == {"timeout": 20, "allow_redirects": False}
        if isinstance(self.response, Exception):
            raise self.response
        yield self.response


def provider(body=RAW, status=200):
    return CMEFedFundsSettlementProvider(session_factory=lambda: Client(Response(body, status)))


def test_real_fixture_identity():
    parsed = parse_settlements(RAW, trade_date=DAY)
    assert len(parsed["rows"]) == 60
    assert parsed["settlement_status"] == "FINAL"
    assert parsed["rows"][0] == {
        "contract": "SEP 26",
        "contract_month": "2026-09-01",
        "settle": 96.255,
        "volume": 9672,
        "open_interest": 320697,
    }
    assert parsed["source_time_timezone"] is None


def test_default_transport_explicitly_disables_libcurl_proxy(monkeypatch):
    from curl_cffi import CurlOpt

    captured = {}
    monkeypatch.setattr("apps.collectors.macro.cme_fed_funds.requests.Session", lambda **kw: captured.update(kw))
    CMEFedFundsSettlementProvider().session_factory()
    assert captured["curl_options"][CurlOpt.PROXY] == ""
    assert captured["trust_env"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(dsHeader="Gold"),
        lambda p: p.update(tradeDate="09/24/2026"),
        lambda p: p.update(reportType="SomethingNew"),
        lambda p: p.update(empty=True),
        lambda p: p.pop("settlements"),
        lambda p: p["settlements"].append(p["settlements"][0]),
        lambda p: p["settlements"][0].update(settle="NaN"),
        lambda p: p["settlements"][0].update(volume="-1"),
        lambda p: p["settlements"][0].pop("openInterest"),
    ],
)
def test_rejects_wrong_product_date_and_schema(mutation):
    payload = json.loads(RAW)
    mutation(payload)
    with pytest.raises((ValueError, KeyError, TypeError)):
        parse_settlements(json.dumps(payload).encode(), trade_date=DAY)


def test_missing_value_not_zero_and_extra_fields_visible():
    p = json.loads(RAW)
    p["extra"] = "new"
    p["settlements"][0].update(volume="-", openInterest=None)
    parsed = parse_settlements(json.dumps(p).encode(), trade_date=DAY)
    assert parsed["rows"][0]["volume"] is None and parsed["rows"][0]["open_interest"] is None
    assert "missing_contract_values" in parsed["warnings"]
    assert "additional_top_level_fields" in parsed["warnings"]


@pytest.mark.parametrize("status,health", [(403, "blocked"), (429, "blocked"), (500, "unavailable")])
def test_http_failure_not_parsed_and_raw_archived(tmp_path, status, health):
    result = provider(status=status).collect(trade_date=DAY, storage_root=tmp_path, now=NOW)
    assert result["request_status"] == "failed" and result["health"] == health
    assert not result["rows"]
    assert hashlib.sha256((tmp_path / result["raw_artifact_ref"]).read_bytes()).hexdigest() == result["content_hash"]


def test_parse_failed_is_successful_http(tmp_path):
    result = provider(b"<html>not data</html>").collect(trade_date=DAY, storage_root=tmp_path, now=NOW)
    assert result["request_status"] == "success" and result["health"] == "parse_failed"


def test_oversize_response_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr("apps.collectors.macro.cme_fed_funds.MAX_BYTES", 8)
    result = provider().collect(trade_date=DAY, storage_root=tmp_path, now=NOW)
    assert result["bytes"] == 8 and result["truncated"]
    assert result["health"] == "parse_failed"


def test_transport_error_is_redacted(tmp_path):
    p = CMEFedFundsSettlementProvider(session_factory=lambda: Client(requests.RequestsError("secret=do-not-store")))
    result = p.collect(trade_date=DAY, storage_root=tmp_path, now=NOW)
    assert "do-not-store" not in json.dumps(result)
    assert result["request_status"] == "failed"


def test_empty_is_not_retention_without_evidence(tmp_path):
    p = json.loads(RAW)
    p.update(empty=True, settlements=[])
    row = provider(json.dumps(p).encode()).collect(trade_date=DAY, storage_root=tmp_path, now=NOW)
    assert row["request_status"] == "success" and row["health"] == "upstream_empty"
    assert settlement_health(row, as_of=NOW, retention_start=date(2026, 9, 26))["status"] == "upstream_empty"
    assert (
        settlement_health(
            row, as_of=NOW, retention_start=date(2026, 9, 26), retention_evidence="verified-public-retention-policy"
        )["status"]
        == "outside_free_retention"
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_worker_history_versions_cutoff_and_tasks(db, tmp_path):
    payload = json.loads(RAW)
    payload["reportType"] = "Preliminary"
    pre = run_settlement_ingestion(
        db, storage_root=tmp_path, trade_date=DAY, now=NOW, provider=provider(json.dumps(payload).encode())
    )
    final_time = NOW.replace(minute=1)
    final = run_settlement_ingestion(db, storage_root=tmp_path, trade_date=DAY, now=final_time, provider=provider())
    later = run_settlement_ingestion(
        db,
        storage_root=tmp_path,
        trade_date=DAY,
        now=NOW.replace(minute=2),
        provider=provider(json.dumps(payload).encode()),
    )
    assert preferred_settlement(db, trade_date=DAY, as_of=NOW)["snapshot_id"] == pre["snapshot_id"]
    assert preferred_settlement(db, trade_date=DAY, as_of=NOW.replace(minute=3))["snapshot_id"] == final["snapshot_id"]
    assert preferred_settlement(db, trade_date=DAY, as_of=NOW.replace(hour=13)) is None
    assert later["preferred_snapshot_id"] == final["snapshot_id"]
    assert db.scalar(select(func.count()).select_from(TaskRun)) == 3
    assert db.scalar(select(func.count()).select_from(TaskStep)) == 3
    assert db.scalar(select(func.count()).select_from(CmeSettlementSnapshot)) == 3
    assert db.scalar(select(func.count()).select_from(CmeSettlementContract)) == 180
    assert (tmp_path / final["raw_artifact_ref"]).read_bytes() == RAW
    saved = db.get(CmeSettlementSnapshot, final["snapshot_id"]).payload
    changed = deepcopy(saved)
    changed["reason"] = "changed"
    with pytest.raises(ValueError, match="immutable"):
        save_settlement(db, changed)
    save_settlement(db, saved)
    stats = settlement_stability(db, as_of=NOW.replace(minute=3))
    assert stats["distinct_trade_days"] == 0  # three replay observations are not three live days
    assert len(stats["reconciliation"]) == 2
    assert stats["reconciliation"][0]["phase_change"]


def test_failed_attempt_does_not_replace_preferred(db, tmp_path):
    success = run_settlement_ingestion(db, storage_root=tmp_path, now=NOW, provider=provider())
    failed = run_settlement_ingestion(
        db, storage_root=tmp_path, now=NOW.replace(minute=1), provider=provider(status=403)
    )
    assert failed["source_health"]["status"] == "blocked"
    assert failed["preferred_snapshot_id"] == success["snapshot_id"]
    assert list(db.scalars(select(TaskRun.status)).all()) == [TaskStatus.success, TaskStatus.degraded]


def test_corrected_final_remains_a_new_observation(db, tmp_path):
    first = run_settlement_ingestion(db, storage_root=tmp_path, now=NOW, provider=provider())
    payload = json.loads(RAW)
    payload["settlements"][0]["settle"] = "96.2600"
    second = run_settlement_ingestion(
        db, storage_root=tmp_path, now=NOW.replace(minute=1), provider=provider(json.dumps(payload).encode())
    )
    assert second["preferred_snapshot_id"] == second["snapshot_id"]
    assert db.get(CmeSettlementSnapshot, first["snapshot_id"]).payload["rows"][0]["settle"] == 96.255
    assert second["stability"]["reconciliation"][0]["changed_contracts"] == ["SEP 26"]


def test_weekend_freshness_and_historical_age(tmp_path):
    row = provider().collect(trade_date=DAY, storage_root=tmp_path, now=NOW)
    assert expected_trade_date(NOW) == DAY
    assert settlement_health(row, as_of=NOW)["status"] == "fresh"
    assert settlement_health(row, as_of=NOW.replace(day=30))["status"] == "stale"


def test_schedule_registered_and_explicit_date():
    from dagster import build_schedule_context, DefaultScheduleStatus
    from dagster_finance.definitions import defs
    from dagster_finance.schedules.cme_settlement_schedule import cme_settlement_schedule

    assert defs.get_job_def("cme_settlement_job")
    assert cme_settlement_schedule.default_status == DefaultScheduleStatus.STOPPED
    result = cme_settlement_schedule(build_schedule_context(scheduled_execution_time=NOW))
    assert result.run_config["ops"]["cme_settlement_op"]["config"]["trade_date"] == DAY.isoformat()


def test_empty_weekend_is_expected_and_not_network_failure(tmp_path):
    payload = json.loads(RAW)
    payload.update(empty=True, settlements=[], tradeDate="09/26/2026")
    row = provider(json.dumps(payload).encode()).collect(trade_date=date(2026, 9, 26), storage_root=tmp_path, now=NOW)
    assert row["request_status"] == "success"
    assert settlement_health(row, as_of=NOW)["status"] == "no_trade_day"


def test_archival_failure_is_recorded_as_failed_task(db, tmp_path):
    class FailedArchive:
        def collect(self, **kwargs):
            raise OSError("private filesystem detail")

    with pytest.raises(OSError):
        run_settlement_ingestion(db, storage_root=tmp_path, now=NOW, provider=FailedArchive())
    assert db.scalar(select(TaskRun.status)) == TaskStatus.failed
    assert db.scalar(select(TaskStep.error)) == "settlement_worker_OSError"


def test_incremental_migration_preserves_existing_data(tmp_path):
    from alembic import command
    from sqlalchemy import inspect, text
    from database.migrations.runtime import build_alembic_config, run_database_migrations

    url = "sqlite:///" + str(tmp_path / "migration.sqlite")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE preserved_data (value INTEGER)"))
        connection.execute(text("INSERT INTO preserved_data VALUES (117)"))
    command.stamp(build_alembic_config(url), "20260704_0001")
    run_database_migrations(url)
    run_database_migrations(url)
    assert "cme_settlement_contract" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT value FROM preserved_data")) == 117
    engine.dispose()


def test_postgresql_schema_compiles():
    from sqlalchemy.dialects.postgresql import dialect
    from sqlalchemy.schema import CreateTable

    for model in (CmeSettlementSnapshot, CmeSettlementContract):
        assert "CREATE TABLE" in str(CreateTable(model.__table__).compile(dialect=dialect()))


@pytest.mark.parametrize("reason,retry", [("transport_RequestException", True), ("upstream_http_403", False)])
def test_dagster_retries_only_transient_transport(monkeypatch, reason, retry):
    from dagster import RetryRequested, build_op_context
    from dagster_finance.jobs.cme_settlement_job import cme_settlement_op, CmeSettlementConfig

    result = {"source_health": {"request_status": "failed", "reason": reason}}
    monkeypatch.setattr("dagster_finance.jobs.cme_settlement_job.run_settlement_ingestion", lambda *a, **kw: result)
    with build_op_context(resources={"db_session": object()}) as context:
        if retry:
            with pytest.raises(RetryRequested) as error:
                cme_settlement_op(context, CmeSettlementConfig())
            assert error.value.max_retries == 1
        else:
            assert cme_settlement_op(context, CmeSettlementConfig()) == result
