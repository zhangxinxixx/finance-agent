from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, func, inspect, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import JSON, LargeBinary

from apps.data_layer.warehouse_etl import load_warehouse, WarehouseError
from database.models.analysis import MacroObservation, MarketCandle
from database.models.execution import RunArtifact
from database.models.task import TaskRun, TaskStep, TaskStatus
from database.models.warehouse import (
    WarehouseBase,
    ensure_warehouse_tables,
    MacroFact,
    CandleFact,
    NewsEventFact,
    LoadBatch,
    ProducerRunDimension,
    EventSourceReference,
    TriggerSourceReference,
    TriggerAction,
    TriggerReason,
    TriggerTopic,
)
from database.queries.warehouse import macro_observations, macro_daily_counts, candles, news_facts


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    for model in (MacroObservation, MarketCandle, RunArtifact, TaskRun, TaskStep):
        model.__table__.create(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def macro(db, **kw):
    values = dict(
        id="a",
        source_key="fred",
        symbol="DGS10",
        observation_date=date(2020, 1, 1),
        value=4.25,
        unit="percent",
        frequency="daily",
        run_id="not-a-task",
        retrieved_at=datetime(2020, 1, 2, tzinfo=UTC),
        source_refs=[{"irrelevant": "private"}],
        observation_metadata={"ignored": True},
    )
    values.update(kw)
    db.add(MacroObservation(**values))
    db.commit()


def artifact(db, tmp_path, dataset="news-events", items=None, **changes):
    run = changes.pop("run", uuid4())
    producer = changes.pop("producer", True)
    if producer and db.get(TaskRun, run) is None:
        db.add(
            TaskRun(
                id=run,
                name="producer",
                status=TaskStatus.degraded,
                trade_date="2026-10-05",
                started_at=datetime(2026, 10, 5, tzinfo=UTC),
            )
        )
    event_domain = dataset == "news-events"
    filename = "event_candidates.json" if event_domain else "daily_analysis_triggers.json"
    refs = [
        {
            "source_key": "official",
            "source_ref": "news-1",
            "url": "https://example.org/a",
            "retrieved_at": "2020-01-02T00:00:00Z",
            "status": "unverified",
            "content_scope": "excerpt",
        }
    ]
    item = (
        dict(
            event_id="e1",
            event_type="macro_watchlist",
            event_status="candidate",
            event_time="2020-01-01T00:00:00Z",
            asset_tags=["GC", "XAUUSD", "gold"],
            direction="unknown",
            confidence=0.4,
            verification_status="single_source",
            need_verification=True,
            source_count=1,
            evidence_text="source sentence",
            duplicate_group="g",
            source_refs=refs,
        )
        if event_domain
        else dict(
            trigger_id="t1",
            trigger_type="jin10_daily_analysis",
            priority="high",
            status="pending",
            created_at="2020-01-01T00:00:00Z",
            source_news_item_id="n1",
            source_event_id="e1",
            source_key="official",
            source_title="source title",
            source_url="https://example.org/a",
            event_type="macro_watchlist",
            impact_path="rates",
            gold_impact="unknown",
            evidence_text="source sentence",
            asset_tags=["gold"],
            suggested_actions=["observe"],
            reason_codes=["new_information"],
            topic_tags=["macro"],
            source_refs=refs,
            data_quality={"verification_status": "single_source"},
        )
    )
    payload = dict(
        as_of="2020-01-02T00:00:00Z",
        run_id=str(run),
        retrieved_date="2026-10-05",
        data_quality={"status": "degraded", "event_candidate_count": 1, "rejected_event_count": 0},
    )
    payload["event_candidates" if event_domain else "triggers"] = [item] if items is None else items
    if not event_domain:
        payload.update(rule_version="rule-v1", trigger_count=len(payload["triggers"]))
    payload.update(changes.pop("payload_changes", {}))
    path = tmp_path / "features" / "news" / "2026-10-05" / str(run) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)
    attrs = dict(
        artifact_id=uuid4(),
        run_id=run,
        artifact_type="news",
        file_path=path.relative_to(tmp_path).as_posix(),
        sha256=sha256(raw).hexdigest(),
        content_type="application/json",
        storage_backend="local_fs",
        created_at=datetime.now(UTC),
        structured_payload={"do_not_load": True},
    )
    attrs.update(changes)
    db.add(RunArtifact(**attrs))
    db.commit()
    return run, path, attrs["artifact_id"]


def test_schema_portable_typed_and_owned(db):
    ensure_warehouse_tables(db)
    assert "analysis_snapshots" not in inspect(db.connection()).get_table_names()
    for table in WarehouseBase.metadata.tables.values():
        assert str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert not any(
            isinstance(c.type, (JSON, LargeBinary)) or c.name in ("body", "payload", "metadata", "key", "value_json")
            for c in table.c
        )
        for fk in table.foreign_keys:
            assert fk.column.table.metadata is WarehouseBase.metadata
    assert MacroFact.__table__.indexes and CandleFact.__table__.constraints


def test_dry_run_no_ddl_write_audit_even_pending(db):
    macro(db)
    statements = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda c, cu, s, p, ctx, many: statements.append(s))
    db.add(TaskRun(name="pending unrelated"))
    result = load_warehouse(db, "macro")
    assert result["planned"] == 1 and result["task_run_id"] is None
    assert all(s.lstrip().upper().startswith(("SELECT", "PRAGMA")) for s in statements)
    assert not inspect(db.connection()).has_table("dwh_load_batch")
    assert not any("metadata" in s for s in statements if "macro_observations" in s)
    # Legacy references are inspected transiently for numeric quarantine.
    assert any("source_refs" in s for s in statements if "macro_observations" in s)
    db.rollback()
    assert count(db, TaskRun) == 0


def test_macro_values_joins_history_and_idempotence(db):
    macro(db)
    ensure_warehouse_tables(db)
    first = load_warehouse(db, "macro", dry_run=False)
    db.commit()
    assert first["inserted"] == 1
    assert macro_observations(db, symbol="DGS10", source="fred")[0]["value"] == Decimal("4.25")
    assert macro_daily_counts(db)[0]["version_count"] == 1
    assert db.scalar(select(ProducerRunDimension)).verified is False
    assert count(db, TaskRun) == 1 and count(db, TaskStep) == 1
    dim_counts = {
        t: db.scalar(select(func.count()).select_from(t))
        for t in WarehouseBase.metadata.tables.values()
        if "_dim_" in t.name
    }
    repeated = load_warehouse(db, "macro", dry_run=False)
    db.commit()
    assert repeated["inserted"] == 0 and repeated["skipped"] == 1
    assert dim_counts == {t: db.scalar(select(func.count()).select_from(t)) for t in dim_counts}
    db.execute(update(MacroObservation).where(MacroObservation.id == "a").values(value=4.5))
    db.commit()
    assert load_warehouse(db, "macro", dry_run=False)["inserted"] == 1
    db.commit()
    assert [r["value"] for r in macro_observations(db)] == [Decimal("4.25"), Decimal("4.5")]
    assert db.get(MacroObservation, "a").observation_metadata == {"ignored": True}
    assert count(db, LoadBatch) == 3


def test_candles_exact_asset_values_and_source_select(db):
    ensure_warehouse_tables(db)
    for i, asset in enumerate(("GC", "XAUUSD")):
        db.add(
            MarketCandle(
                id=str(i),
                asset=asset,
                source="test",
                timeframe="1h",
                open_time=datetime(2020, 1, 1, tzinfo=UTC),
                open=10,
                high=12,
                low=9,
                close=11,
                volume=2,
                source_ref={"ignored": True},
            )
        )
    db.commit()
    stmts = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda c, cu, s, p, ctx, many: stmts.append(s))
    result = load_warehouse(db, "candles", dry_run=False)
    db.commit()
    assert result["inserted"] == 2
    assert candles(db, asset="GC")[0]["close"] == Decimal(11)
    assert {r["asset"] for r in candles(db)} == {"GC", "XAUUSD"}
    assert any("source_ref" in s for s in stmts if s.startswith("SELECT") and "market_candles" in s)
    assert "source_ref" not in CandleFact.__table__.columns


@pytest.mark.parametrize("dataset", ["news-events", "news-triggers"])
def test_news_real_field_mapping_history_quality_no_blob_select(db, tmp_path, dataset):
    ensure_warehouse_tables(db)
    run, _, _ = artifact(db, tmp_path, dataset)
    statements = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda c, cu, s, p, ctx, many: statements.append(s))
    result = load_warehouse(db, dataset, storage_root=tmp_path, dry_run=False)
    db.commit()
    assert result["inserted"] == 1
    facts = news_facts(db, dataset=dataset, asset="gold", source="official", run_id=str(run))
    assert len(facts) == 1 and facts[0].verification_status == "single_source"
    fact = facts[0]
    assert fact.as_of.year == 2020 and fact.date_key == 20200101
    assert db.scalar(select(LoadBatch)).producer_date == date(2026, 10, 5)
    assert db.scalar(select(LoadBatch)).schema_version is None
    assert db.get(TaskRun, run).status == TaskStatus.degraded
    assert not any("structured_payload" in s for s in statements if s.startswith("SELECT"))
    assert load_warehouse(db, dataset, storage_root=tmp_path, dry_run=False)["skipped"] == 1
    refmodel = EventSourceReference if dataset == "news-events" else TriggerSourceReference
    assert db.scalar(select(refmodel)).content_scope == "excerpt"
    if dataset == "news-triggers":
        assert db.scalar(select(TriggerAction)).action == "observe"
        assert db.scalar(select(TriggerReason)).reason_code == "new_information"
        assert db.scalar(select(TriggerTopic)).topic == "macro"
    db.commit()


def test_empty_triggers_loaded_not_missing(db, tmp_path):
    ensure_warehouse_tables(db)
    run, _, _ = artifact(db, tmp_path, "news-triggers", items=[], producer=False)
    result = load_warehouse(db, "news-triggers", storage_root=tmp_path, dry_run=False)
    assert result["processed"] == 1 and result["rejected"] == 0
    batch = db.scalar(select(LoadBatch))
    assert batch.status == "loaded" and batch.source_trigger_count == 0 and batch.as_of.year == 2020
    assert db.scalar(select(ProducerRunDimension)).verified is False
    assert count(db, TaskRun) == 1  # loader only; no forged producer


@pytest.mark.parametrize("bad", ["sha", "identity", "date", "symlink", "nan", "missing_items"])
def test_artifact_bad_inputs_explicit_rejection(db, tmp_path, bad):
    ensure_warehouse_tables(db)
    run, path, aid = artifact(db, tmp_path)
    if bad == "sha":
        db.execute(update(RunArtifact).where(RunArtifact.artifact_id == aid).values(sha256="0" * 64))
    elif bad == "symlink":
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    else:
        payload = json.loads(path.read_text())
        if bad == "identity":
            payload["run_id"] = str(uuid4())
        elif bad == "date":
            payload["retrieved_date"] = "2026-10-04"
        elif bad == "nan":
            payload["event_candidates"][0]["confidence"] = "nan"
        else:
            del payload["event_candidates"]
        raw = json.dumps(payload).encode()
        path.write_bytes(raw)
        db.execute(update(RunArtifact).where(RunArtifact.artifact_id == aid).values(sha256=sha256(raw).hexdigest()))
    db.commit()
    result = load_warehouse(db, "news-events", storage_root=tmp_path, dry_run=False)
    assert result["rejected"] == 1 and result["inserted"] == 0
    assert db.scalar(select(LoadBatch)).status == "rejected"
    assert count(db, NewsEventFact) == 0


def test_latest_bad_alias_does_not_fallback(db, tmp_path):
    ensure_warehouse_tables(db)
    run, path, _ = artifact(db, tmp_path)
    db.add(
        RunArtifact(
            run_id=run,
            artifact_type="news",
            file_path=str(path),
            sha256="0" * 64,
            created_at=datetime(2030, 1, 1, tzinfo=UTC),
        )
    )
    db.commit()
    result = load_warehouse(db, "news-events", storage_root=tmp_path, dry_run=False)
    assert result["processed"] == 1 and result["rejected"] == 1 and result["inserted"] == 0


def test_partial_artifact_counts_and_new_version_preserves_old(db, tmp_path):
    ensure_warehouse_tables(db)
    run, path, aid = artifact(db, tmp_path)
    result = load_warehouse(db, "news-events", storage_root=tmp_path, dry_run=False)
    db.commit()
    assert result["inserted"] == 1
    payload = json.loads(path.read_text())
    payload["event_candidates"][0]["evidence_text"] = "corrected source sentence"
    payload["event_candidates"].append({"event_id": "bad", "confidence": "nan"})
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)
    db.add(
        RunArtifact(
            run_id=run,
            artifact_type="news",
            file_path=path.relative_to(tmp_path).as_posix(),
            sha256=sha256(raw).hexdigest(),
            created_at=datetime(2030, 1, 1, tzinfo=UTC),
        )
    )
    db.commit()
    result = load_warehouse(db, "news-events", storage_root=tmp_path, dry_run=False)
    db.commit()
    assert result["inserted"] == 1 and result["rejected"] == 1
    assert count(db, NewsEventFact) == 2
    assert db.get(TaskRun, __import__("uuid").UUID(result["task_run_id"])).status == TaskStatus.partial_success
    assert db.scalar(select(LoadBatch).order_by(LoadBatch.id.desc())).status == "partial"


def test_bounded_cursor_and_missing_schema(db):
    macro(db)
    macro(db, id="b", symbol="DGS2")
    with pytest.raises(WarehouseError, match="DWH_SCHEMA_MISSING"):
        load_warehouse(db, "macro", dry_run=False)
    ensure_warehouse_tables(db)
    first = load_warehouse(db, "macro", limit=1, dry_run=False)
    second = load_warehouse(db, "macro", limit=1, after=first["next_after"], dry_run=False)
    assert first["next_after"] == "a" and second["next_after"] == "b"
    empty = load_warehouse(db, "macro", after="b", dry_run=False)
    assert empty["processed"] == 0 and empty["next_after"] == "b"
    db.commit()


def test_explicit_record_ids_are_bounded_and_return_batch_receipts(db):
    macro(db, id="a", symbol="DGS10")
    macro(db, id="b", symbol="DGS2")
    ensure_warehouse_tables(db)
    result = load_warehouse(db, "macro", record_ids=["b"], dry_run=False)
    db.commit()
    assert result["processed"] == result["inserted"] == 1
    assert result["next_after"] == "b" and len(result["load_batch_ids"]) == 1
    assert db.scalar(select(MacroFact)).source_record_id == "b"
    with pytest.raises(WarehouseError, match="DWH_ARGUMENT_INVALID"):
        load_warehouse(db, "macro", after="a", record_ids=["b"])


def test_transaction_failure_no_partial_and_caller_rollback(db):
    ensure_warehouse_tables(db)
    macro(db)

    def break_fact(conn, cursor, stmt, params, context, many):
        if stmt.startswith("INSERT INTO dwh_fact_macro"):
            raise RuntimeError("private backend detail")

    event.listen(db.get_bind(), "before_cursor_execute", break_fact)
    with pytest.raises(WarehouseError, match="DWH_TRANSACTION_FAILED"):
        load_warehouse(db, "macro", dry_run=False)
    event.remove(db.get_bind(), "before_cursor_execute", break_fact)
    assert count(db, LoadBatch) == 0 and count(db, MacroFact) == 0 and count(db, TaskRun) == 0
    assert count(db, ProducerRunDimension) == 0
    load_warehouse(db, "macro", dry_run=False)
    db.rollback()
    assert count(db, MacroFact) == 0


def test_queries_read_only_even_with_pending_work(db):
    ensure_warehouse_tables(db)
    macro(db)
    load_warehouse(db, "macro", dry_run=False)
    db.commit()
    db.add(TaskRun(name="pending"))
    statements = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda c, cu, s, p, ctx, many: statements.append(s))
    assert macro_observations(db, start=date(2020, 1, 1), end=date(2020, 1, 1), run_id="not-a-task")
    assert macro_daily_counts(db, source="fred")
    assert not candles(db, asset="GC")
    assert not news_facts(db, dataset="news-events", asset="GC", source="official")
    assert all(s.startswith("SELECT") for s in statements)


def test_first_apply_is_caller_owned_not_savepoint_autocommit(db):
    macro(db)
    ensure_warehouse_tables(db)
    db.commit()
    load_warehouse(db, "macro", dry_run=False)
    db.rollback()
    assert count(db, MacroFact) == 0
    assert count(db, LoadBatch) == 0
    assert count(db, TaskRun) == 0


def test_real_producer_source_alias_and_utc(db, tmp_path):
    ensure_warehouse_tables(db)
    run, path, aid = artifact(db, tmp_path)
    payload = json.loads(path.read_text())
    ref = payload["event_candidates"][0]["source_refs"][0]
    ref["source"] = ref.pop("source_key")
    ref.update(source_type="wire_public_candidate", source_name="Original publisher")
    payload["event_candidates"][0]["event_time"] = "2020-01-01T08:00:00+08:00"
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)
    db.execute(update(RunArtifact).where(RunArtifact.artifact_id == aid).values(sha256=sha256(raw).hexdigest()))
    db.commit()
    load_warehouse(db, "news-events", storage_root=tmp_path, dry_run=False)
    db.commit()
    assert news_facts(db, dataset="news-events", source="official")[0].event_time == datetime(2020, 1, 1, tzinfo=UTC)
    from database.models.warehouse import SourceDimension

    source = db.scalar(select(SourceDimension))
    assert source.source_type == "wire_public_candidate" and source.name == "Original publisher"


def test_invalid_macro_number_is_not_silent_success(db):
    macro(db, value=float("inf"))
    ensure_warehouse_tables(db)
    result = load_warehouse(db, "macro", dry_run=False)
    assert result["rejected"] == 1 and result["inserted"] == 0
    assert result["error_codes"] == ["DWH_NUMBER_INVALID"]
    assert db.scalar(select(LoadBatch)).rejected == 1
    assert db.get(MacroObservation, "a").value == float("inf")


def test_news_uuid_cursor_and_invalid_cursor(db, tmp_path):
    artifact(db, tmp_path)
    artifact(db, tmp_path)
    one = load_warehouse(db, "news-events", limit=1, storage_root=tmp_path)
    two = load_warehouse(db, "news-events", limit=1, after=one["next_after"], storage_root=tmp_path)
    assert one["processed"] == two["processed"] == 1
    assert one["next_after"] != two["next_after"]
    assert load_warehouse(db, "news-events", after=two["next_after"], storage_root=tmp_path)["processed"] == 0
    with pytest.raises(WarehouseError, match="DWH_CURSOR_INVALID"):
        load_warehouse(db, "news-events", after="invalid", storage_root=tmp_path)


def test_null_macro_value_and_missing_source_time_are_preserved(db):
    macro(db, value=None, retrieved_at=None, run_id=None)
    ensure_warehouse_tables(db)
    assert load_warehouse(db, "macro", dry_run=False)["inserted"] == 1
    row = db.scalar(select(MacroFact))
    assert row.value is None and row.as_of is None and row.producer_run_id is None
