"""SQLite contract tests for normalized FedWatch persistence."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateIndex, CreateTable

from database.models.fedwatch import (
    FedWatchFactor,
    FedWatchFutures,
    FedWatchMeetingSnapshot,
    FedWatchProbability,
    FedWatchRawSnapshot,
    ensure_fedwatch_tables,
)
from database.queries.fedwatch import (
    get_fedwatch_history,
    get_latest_fedwatch_factor,
    get_latest_fedwatch_snapshot,
    save_fedwatch_snapshot,
)


def _make_session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'fedwatch.db'}")
    ensure_fedwatch_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _snapshot(
    *,
    snapshot_id: str | None = None,
    source_time: datetime | None = None,
    collected_at: datetime | None = None,
    meeting_date: str = "2026-10-28",
    parse_status: str = "ok",
    reason: str | None = None,
    content_hash: str = "a" * 64,
) -> dict:
    """Build clearly labelled synthetic normalized rows, not source evidence."""

    source_time = source_time or datetime(2026, 9, 18, 18, tzinfo=UTC)
    collected_at = collected_at or source_time + timedelta(minutes=5)
    rows = []
    if parse_status == "ok":
        rows = [
            {
                "meeting_date": meeting_date,
                "contract_ref": "ZQX26",
                "comparison_window": "current",
                "as_of": source_time.isoformat(),
                "target_low": 4.0,
                "target_high": 4.25,
                "probability": 0.4,
            },
            {
                "meeting_date": meeting_date,
                "contract_ref": "ZQX26",
                "comparison_window": "current",
                "as_of": source_time.isoformat(),
                "target_low": 4.25,
                "target_high": 4.5,
                "probability": 0.6,
            },
            {
                "meeting_date": meeting_date,
                "contract_ref": "ZQX26",
                "comparison_window": "1d",
                "as_of": (source_time - timedelta(days=1)).isoformat(),
                "target_low": 4.0,
                "target_high": 4.25,
                "probability": 0.3,
            },
            {
                "meeting_date": meeting_date,
                "contract_ref": "ZQX26",
                "comparison_window": "1d",
                "as_of": (source_time - timedelta(days=1)).isoformat(),
                "target_low": 4.25,
                "target_high": 4.5,
                "probability": 0.7,
            },
        ]
    return {
        "source": "cme_fedwatch_free",
        "snapshot_id": snapshot_id or str(uuid.uuid4()),
        "collected_at": collected_at.isoformat(),
        "as_of": source_time.isoformat() if parse_status == "ok" else None,
        "source_url": "https://www.cmegroup.com/test-only/fedwatch",
        "collector_version": "test-synthetic-v1",
        "http_status": 200 if parse_status == "ok" else None,
        "content_hash": content_hash if parse_status == "ok" else None,
        "raw_artifact_ref": (
            f"raw/fedwatch/test/{snapshot_id or 'synthetic'}.json"
            if parse_status == "ok"
            else None
        ),
        "parse_status": parse_status,
        "reason": reason,
        "source_refs": [{"kind": "synthetic_test", "is_source_evidence": False}],
        "rows": rows,
        "futures": [
            {
                "contract_ref": "ZQX26",
                "as_of": source_time.isoformat(),
                "settlement": 95.75,
                "test_data": True,
            }
        ] if parse_status == "ok" else [],
        "warnings": ["synthetic_test_fixture"],
        "coverage": {"current": True, "1d": parse_status == "ok"},
    }


def test_ensure_helper_creates_only_fedwatch_tables_with_constraints_and_indexes() -> None:
    engine = create_engine("sqlite:///:memory:")
    ensure_fedwatch_tables(engine)
    inspector = inspect(engine)

    assert set(inspector.get_table_names()) == {
        "fedwatch_raw_snapshot",
        "fedwatch_meeting_snapshot",
        "fedwatch_probability",
        "fedwatch_futures",
        "fedwatch_factor",
    }
    probability_indexes = {
        index["name"] for index in inspector.get_indexes("fedwatch_probability")
    }
    meeting_indexes = {
        index["name"] for index in inspector.get_indexes("fedwatch_meeting_snapshot")
    }
    probability_checks = {
        item["name"] for item in inspector.get_check_constraints("fedwatch_probability")
    }
    assert "ix_fedwatch_probability_target_range" in probability_indexes
    assert "ix_fedwatch_meeting_snapshot_meeting_window_as_of" in meeting_indexes
    assert "ck_fedwatch_probability_value" in probability_checks


def test_models_compile_for_postgresql_with_jsonb() -> None:
    dialect = postgresql.dialect()
    tables = (
        FedWatchRawSnapshot.__table__,
        FedWatchMeetingSnapshot.__table__,
        FedWatchProbability.__table__,
        FedWatchFutures.__table__,
        FedWatchFactor.__table__,
    )

    table_ddl = "\n".join(str(CreateTable(table).compile(dialect=dialect)) for table in tables)
    index_ddl = "\n".join(
        str(CreateIndex(index).compile(dialect=dialect))
        for table in tables
        for index in table.indexes
    )
    assert table_ddl.count("CREATE TABLE fedwatch_") == 5
    assert "JSONB" in table_ddl
    assert "ix_fedwatch_probability_target_range" in index_ddl


def test_save_persists_normalized_rows_and_reconstructs_lineage(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    payload = _snapshot()
    try:
        returned = save_fedwatch_snapshot(session, payload)
        assert session.in_transaction()
        session.commit()

        assert session.scalar(select(func.count()).select_from(FedWatchRawSnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(FedWatchMeetingSnapshot)) == 2
        assert session.scalar(select(func.count()).select_from(FedWatchProbability)) == 4
        assert session.scalar(select(func.count()).select_from(FedWatchFutures)) == 1
        latest = get_latest_fedwatch_snapshot(session)
    finally:
        session.close()

    assert returned == payload
    assert latest == payload
    assert latest["source_refs"] == payload["source_refs"]
    assert latest["warnings"] == ["synthetic_test_fixture"]


def test_query_api_does_not_commit(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        save_fedwatch_snapshot(session, _snapshot())
        session.rollback()
        assert session.scalar(select(func.count()).select_from(FedWatchRawSnapshot)) == 0
    finally:
        session.close()


def test_same_id_is_idempotent_but_conflict_leaves_no_partial_children(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    snapshot_id = str(uuid.uuid4())
    original = _snapshot(snapshot_id=snapshot_id)
    try:
        save_fedwatch_snapshot(session, original)
        save_fedwatch_snapshot(session, copy.deepcopy(original))
        session.commit()

        conflict = copy.deepcopy(original)
        conflict["rows"][0]["probability"] = 0.5
        conflict["rows"][1]["probability"] = 0.5
        with pytest.raises(ValueError, match="conflicting payload"):
            save_fedwatch_snapshot(session, conflict)
        # A runner may catch the error and commit its own failure bookkeeping.
        session.commit()

        assert session.scalar(select(func.count()).select_from(FedWatchRawSnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(FedWatchMeetingSnapshot)) == 2
        assert session.scalar(select(func.count()).select_from(FedWatchProbability)) == 4
    finally:
        session.close()


def test_same_raw_content_under_new_collection_ids_is_retained(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    source_time = datetime(2026, 9, 18, 18, tzinfo=UTC)
    try:
        first = _snapshot(source_time=source_time, collected_at=source_time + timedelta(minutes=1))
        second = _snapshot(source_time=source_time, collected_at=source_time + timedelta(minutes=2))
        save_fedwatch_snapshot(session, first)
        save_fedwatch_snapshot(session, second)
        session.commit()
        assert session.scalar(select(func.count()).select_from(FedWatchRawSnapshot)) == 2
        assert len(get_fedwatch_history(session)) == 2
    finally:
        session.close()


def test_latest_valid_uses_source_time_and_latest_event_exposes_failure(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    base = datetime(2026, 9, 18, 10, tzinfo=UTC)
    newer_source = _snapshot(source_time=base + timedelta(hours=2), collected_at=base + timedelta(hours=3))
    late_old_source = _snapshot(source_time=base, collected_at=base + timedelta(hours=4))
    failed = _snapshot(
        source_time=base + timedelta(hours=4),
        collected_at=base + timedelta(hours=5),
        parse_status="parse_failed",
        reason="synthetic_parser_failure",
    )
    try:
        for item in (newer_source, late_old_source, failed):
            save_fedwatch_snapshot(session, item)
        session.commit()

        latest_valid = get_latest_fedwatch_snapshot(session)
        latest_event = get_latest_fedwatch_snapshot(session, valid_only=False)
        history = get_fedwatch_history(session, limit=1)
    finally:
        session.close()

    assert latest_valid["snapshot_id"] == newer_source["snapshot_id"]
    assert latest_event["snapshot_id"] == failed["snapshot_id"]
    assert latest_event["reason"] == "synthetic_parser_failure"
    assert history[0]["snapshot_id"] == failed["snapshot_id"]


def test_as_of_cutoff_constrains_source_and_collection_times(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    base = datetime(2026, 9, 18, 10, tzinfo=UTC)
    available = _snapshot(source_time=base, collected_at=base + timedelta(minutes=5))
    observed_but_not_collected = _snapshot(
        source_time=base + timedelta(minutes=10),
        collected_at=base + timedelta(hours=2),
    )
    try:
        save_fedwatch_snapshot(session, available)
        save_fedwatch_snapshot(session, observed_but_not_collected)
        session.commit()

        cutoff = base + timedelta(hours=1)
        latest = get_latest_fedwatch_snapshot(session, as_of=cutoff)
        history = get_fedwatch_history(session, as_of=cutoff)
    finally:
        session.close()

    assert latest["snapshot_id"] == available["snapshot_id"]
    assert [item["snapshot_id"] for item in history] == [available["snapshot_id"]]


def test_history_filters_meeting_and_validates_bounded_limit(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    try:
        october = _snapshot(meeting_date="2026-10-28")
        december = _snapshot(
            meeting_date="2026-12-09",
            source_time=datetime(2026, 9, 18, 19, tzinfo=UTC),
        )
        save_fedwatch_snapshot(session, october)
        save_fedwatch_snapshot(session, december)
        session.commit()

        filtered = get_fedwatch_history(session, meeting_date="2026-10-28", limit=1)
        with pytest.raises(ValueError, match="limit must be between"):
            get_fedwatch_history(session, limit=0)
        with pytest.raises(ValueError, match="limit must be between"):
            get_fedwatch_history(session, limit=1001)
    finally:
        session.close()

    assert [item["snapshot_id"] for item in filtered] == [october["snapshot_id"]]


def test_missing_is_persisted_but_never_returned_as_valid(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    missing = _snapshot(parse_status="missing", reason="synthetic_source_unavailable")
    try:
        save_fedwatch_snapshot(session, missing)
        session.commit()
        assert get_latest_fedwatch_snapshot(session) is None
        assert get_latest_fedwatch_snapshot(session, valid_only=False) == missing
    finally:
        session.close()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(source_url="http://www.cmegroup.com/fedwatch"), "https URL"),
        (lambda value: value.update(source_url="https://example.com/fedwatch"), "official CME"),
        (lambda value: value.update(raw_artifact_ref="../outside.json"), "safe relative path"),
        (lambda value: value.update(raw_artifact_ref=r"..\outside.json"), "safe relative path"),
        (lambda value: value["rows"][0].update(probability=float("nan")), "finite number"),
        (lambda value: value["rows"][1].update(target_low=4.1), "must not overlap"),
        (lambda value: value["rows"].__setitem__(slice(0, 2), []), "current comparison"),
    ],
)
def test_malformed_snapshot_is_rejected_before_write(tmp_path: Path, mutate, message: str) -> None:
    session = _make_session(tmp_path)
    payload = _snapshot()
    mutate(payload)
    try:
        with pytest.raises(ValueError, match=message):
            save_fedwatch_snapshot(session, payload)
        session.commit()
        assert session.scalar(select(func.count()).select_from(FedWatchRawSnapshot)) == 0
    finally:
        session.close()


def test_factor_is_versioned_queryable_idempotent_and_fail_closed(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    payload = _snapshot()
    factor_time = datetime.fromisoformat(payload["collected_at"]) + timedelta(minutes=1)
    factor = {
        "snapshot_id": payload["snapshot_id"],
        "version": "repricing.v1",
        "as_of": factor_time.isoformat(),
        "status": "available",
        "source_refs": payload["source_refs"],
        "repricing": {"direction": "easing"},
    }
    try:
        save_fedwatch_snapshot(session, payload, factor=factor)
        save_fedwatch_snapshot(session, payload, factor=copy.deepcopy(factor))
        session.commit()
        assert session.scalar(select(func.count()).select_from(FedWatchFactor)) == 1
        assert get_latest_fedwatch_factor(session) == factor
        assert get_latest_fedwatch_factor(session, as_of=factor_time - timedelta(seconds=1)) is None

        conflict = copy.deepcopy(factor)
        conflict["repricing"]["direction"] = "tightening"
        with pytest.raises(ValueError, match="conflicting factor"):
            save_fedwatch_snapshot(session, payload, factor=conflict)

        missing = _snapshot(parse_status="missing", reason="synthetic_missing")
        invalid_factor = copy.deepcopy(factor)
        invalid_factor["snapshot_id"] = missing["snapshot_id"]
        with pytest.raises(ValueError, match="requires an ok snapshot"):
            save_fedwatch_snapshot(session, missing, factor=invalid_factor)
    finally:
        session.close()
