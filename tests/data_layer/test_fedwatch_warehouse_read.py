from copy import deepcopy

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from apps.data_layer.warehouse_sources import load_source_warehouse
from apps.features.macro.fedwatch import build_fedwatch_factors
from database.models.fedwatch import ensure_fedwatch_tables
from database.models.task import TaskRun, TaskStep
from database.models.warehouse import ensure_warehouse_tables
from database.models.warehouse_fedwatch import FedWatchContextFact, FedWatchSourceEvidence
from database.models.warehouse_sources import FedWatchProbabilityFact
from database.queries.fedwatch import save_fedwatch_snapshot
from database.queries.warehouse_fedwatch import get_fedwatch_warehouse_snapshot
from tests.features.test_fedwatch import NOW, TARGET, snapshot


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    ensure_fedwatch_tables(engine)
    TaskRun.__table__.create(engine, checkfirst=True)
    TaskStep.__table__.create(engine, checkfirst=True)
    ensure_warehouse_tables(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _seed(db):
    value = snapshot()
    value["target_reference"] = deepcopy(TARGET)
    value["coverage"] = {"all_future_meetings": False, "available_tab_count": 8, "captured_tab_count": 4}
    save_fedwatch_snapshot(db, value)
    db.commit()
    return value


def test_factors_read_typed_facts_and_keep_numeric_and_quality_results(db):
    value = _seed(db)
    before = build_fedwatch_factors(value, as_of=NOW, target_reference=TARGET)
    result = load_source_warehouse(db, "fedwatch", record_ids=[value["snapshot_id"]], dry_run=False)
    assert result["rejected"] == 0
    db.commit()

    def forbid_ods(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select"):
            assert " fedwatch_raw_snapshot" not in statement
            assert " fedwatch_probability" not in statement
            assert " fedwatch_meeting_snapshot" not in statement
            assert " fedwatch_futures" not in statement
    event.listen(db.get_bind(), "before_cursor_execute", forbid_ods)
    try:
        read = get_fedwatch_warehouse_snapshot(db, as_of=NOW)
        after = build_fedwatch_factors(read, as_of=NOW, target_reference=read["target_reference"])
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", forbid_ods)
    assert after["market_implied_path"] == before["market_implied_path"]
    assert after["repricing"] == before["repricing"]
    assert after["official_policy"] == before["official_policy"]
    assert after["health"]["quality_summary"] == before["health"]["quality_summary"]
    assert after["health"]["quality_summary"]["all_meeting_tabs_captured"] is False
    assert after["health"]["quality_summary"]["raw_hash_verified"] is None
    assert read["warehouse_context_version"]
    assert get_fedwatch_warehouse_snapshot(db, as_of="2026-09-27T00:00:00+00:00") is None


def test_context_idempotence_and_rollback_share_fact_transaction(db):
    value = _seed(db)
    for _ in range(2):
        load_source_warehouse(db, "fedwatch", record_ids=[value["snapshot_id"]], dry_run=False)
    assert db.scalar(select(func.count()).select_from(FedWatchContextFact)) == 1
    assert db.scalar(select(func.count()).select_from(FedWatchProbabilityFact)) == 32
    assert db.scalar(select(func.count()).select_from(FedWatchSourceEvidence)) > 0
    db.rollback()
    assert db.scalar(select(func.count()).select_from(FedWatchContextFact)) == 0
    assert db.scalar(select(func.count()).select_from(FedWatchProbabilityFact)) == 0


def test_dry_run_does_not_write_context_or_fact(db):
    value = _seed(db)
    result = load_source_warehouse(db, "fedwatch", record_ids=[value["snapshot_id"]], dry_run=True)
    assert result["planned"] == 32
    assert db.scalar(select(func.count()).select_from(FedWatchContextFact)) == 0
    assert db.scalar(select(func.count()).select_from(FedWatchProbabilityFact)) == 0


def test_truthy_hash_verification_does_not_become_verified(db):
    value = snapshot()
    value["source_refs"][0]["hash_verified_at_ingestion"] = "yes"
    save_fedwatch_snapshot(db, value)
    db.commit()
    result = load_source_warehouse(db, "fedwatch", record_ids=[value["snapshot_id"]], dry_run=False)
    assert result["rejected"] == 1
    assert "DWH_MAPPING_INVALID" in result["error_codes"]
    assert db.scalar(select(func.count()).select_from(FedWatchContextFact)) == 0
