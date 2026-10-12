from datetime import UTC, datetime
from hashlib import sha256
import os

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import apps.data_layer.warehouse_etl as etl
from apps.data_layer.collection_ingestion import ingest_collection_records
from apps.data_layer.warehouse_etl import WarehouseError, prepare_record
from apps.data_layer.raw_retention import preview_raw_retention
from database.migrations.runtime import run_database_migrations
from database.models.analysis import MarketCandle
from database.models.raw_source import RawSourceFile, RawSourceLoad, RawSourceLoadBatch
from database.models.warehouse import CandleFact, LoadBatch
from database.models.warehouse_sync import BatchSourceFile


SOURCE = "twelvedata_xauusd_15m"
RAW_PATH = "raw/market/twelvedata/2026-09-02/XAU-USD-15min.json"
COLLECTED_AT = datetime(2026, 9, 2, 11, 13, 22, tzinfo=UTC)
RETENTION_NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _ref(**changes):
    value = {
        "provider": "twelve_data",
        "source_key": "twelvedata_xauusd",
        "source_role": "fallback",
        "quality_status": "accepted_fallback",
        "fallback_reason": "jin10_incomplete_or_stale",
        "instrument_type": "composite_otc_spot_proxy",
        "provider_symbol": "XAU/USD",
        "provider_timeframe": "15min",
        "volume_semantics": "unavailable",
        "raw_path": RAW_PATH,
        "retrieved_at": COLLECTED_AT.isoformat(),
    }
    value.update(changes)
    return value


def _record(ref):
    return {
        "id": "legacy-twelvedata-candle",
        "asset": "XAUUSD",
        "source": SOURCE,
        "timeframe": "15m",
        "open_time": datetime(2026, 9, 2, 8, 15, tzinfo=UTC),
        "open": 3500.0,
        "high": 3501.0,
        "low": 3499.0,
        "close": 3500.5,
        "volume": None,
        "raw_path": RAW_PATH,
        "created_at": datetime(2026, 9, 2, 11, 13, tzinfo=UTC),
        "updated_at": datetime(2026, 9, 2, 11, 13, tzinfo=UTC),
        "_numeric_lineage": ref,
    }


@pytest.fixture
def migrated_warehouse(tmp_path):
    url = f"sqlite:///{tmp_path / 'warehouse.sqlite'}"
    run_database_migrations(url)
    engine = create_engine(url)
    factory = sessionmaker(engine)
    root = tmp_path / "storage"
    raw_file = root / "raw" / "market" / "twelvedata" / "2026-09-02" / "XAU-USD-15min.json"
    raw_file.parent.mkdir(parents=True)
    payload = b'{"provider":"twelve_data","status":"ok","values":[{"close":"3500.5"}]}\n'
    raw_file.write_bytes(payload)
    os.utime(raw_file, (COLLECTED_AT.timestamp(), COLLECTED_AT.timestamp()))
    yield factory, root, raw_file, payload
    engine.dispose()


def _persisted_candle(*, source=SOURCE, source_ref=None, raw_path=RAW_PATH):
    return MarketCandle(
        id="legacy-twelvedata-candle",
        asset="XAUUSD",
        source=source,
        timeframe="15m",
        open_time=datetime(2026, 9, 2, 8, 15, tzinfo=UTC),
        open=3500.0,
        high=3501.0,
        low=3499.0,
        close=3500.5,
        volume=None,
        raw_path=raw_path,
        source_ref=source_ref if source_ref is not None else _ref(),
        created_at=COLLECTED_AT,
        updated_at=COLLECTED_AT,
    )


def test_legacy_twelvedata_rejection_recovers_with_exact_receipt_and_retention(
    migrated_warehouse, monkeypatch
):
    factory, root, raw_file, payload = migrated_warehouse
    with factory.begin() as session:
        row = _persisted_candle()
        session.add(row)
        row_id = row.id

    with monkeypatch.context() as old_policy:
        old_policy.setattr(etl, "is_formal_numeric_source", lambda *args, **kwargs: False)
        with factory.begin() as session:
            first = ingest_collection_records(
                session,
                "candles",
                record_ids=[row_id],
                storage_root=root,
            )
        assert first["rejected"] == 1
        assert first["raw_ready"] == 0
        assert first["raw_blocked"][0]["reason"] == "RAW_WAREHOUSE_COVERAGE_INCOMPLETE"

    with factory() as session:
        old_batch = session.scalar(select(LoadBatch).order_by(LoadBatch.id))
        assert old_batch.status == "rejected"
        assert old_batch.error_code == "DWH_NUMERIC_SOURCE_FORBIDDEN"
        assert session.scalar(select(func.count()).select_from(BatchSourceFile)) == 0
        assert session.scalar(select(func.count()).select_from(RawSourceLoad)) == 0
        assert session.scalar(select(func.count()).select_from(CandleFact)) == 0
        ods_before = session.get(MarketCandle, row_id)
        ods_snapshot = (
            ods_before.asset,
            ods_before.timeframe,
            ods_before.open,
            ods_before.high,
            ods_before.low,
            ods_before.close,
            ods_before.volume,
            ods_before.source,
            ods_before.source_ref,
            ods_before.raw_path,
        )

    with factory.begin() as session:
        recovered = ingest_collection_records(
            session,
            "candles",
            record_ids=[row_id],
            storage_root=root,
        )
        assert (recovered["inserted"], recovered["raw_ready"], recovered["raw_blocked"]) == (
            1,
            1,
            [],
        )

    expected_hash = sha256(payload).hexdigest()
    with factory() as session:
        batches = list(session.scalars(select(LoadBatch).order_by(LoadBatch.id)))
        assert [batch.id for batch in batches] == [old_batch.id, batches[-1].id]
        assert batches[-1].id > old_batch.id
        assert (batches[-1].status, batches[-1].inserted, batches[-1].rejected) == (
            "loaded",
            1,
            0,
        )
        assert session.scalar(select(func.count()).select_from(LoadBatch)) == 2

        catalog = session.scalar(select(RawSourceFile))
        assert (catalog.sha256, catalog.byte_size, catalog.state) == (
            expected_hash,
            len(payload),
            "loaded",
        )
        link = session.scalar(select(BatchSourceFile))
        assert link is not None
        assert (link.batch_id, link.raw_path, link.sha256, link.byte_size) == (
            batches[-1].id,
            RAW_PATH,
            expected_hash,
            len(payload),
        )
        assert (link.batch_source_path, link.batch_source_cursor) == (
            RAW_PATH,
            row_id,
        )
        load = session.scalar(select(RawSourceLoad))
        assert load is not None
        assert (load.status, load.expected_records, load.loaded_records, load.rejected_records) == (
            "completed",
            1,
            1,
            0,
        )
        assert session.scalar(select(RawSourceLoadBatch.batch_id)) == batches[-1].id

        ods_after = session.get(MarketCandle, row_id)
        assert (
            ods_after.asset,
            ods_after.timeframe,
            ods_after.open,
            ods_after.high,
            ods_after.low,
            ods_after.close,
            ods_after.volume,
            ods_after.source,
            ods_after.source_ref,
            ods_after.raw_path,
        ) == ods_snapshot
        assert ods_after.source_ref["source_role"] == "fallback"
        fact = session.scalar(select(CandleFact).where(CandleFact.source_record_id == row_id))
        assert fact is not None
        preview = preview_raw_retention(
            session,
            storage_root=root,
            now=RETENTION_NOW,
            retention_days=30,
            limit=10,
        )
        assert preview["candidate_count"] == 1
        assert preview["blocked_count"] == 0
        assert preview["candidates"][0]["raw_path"] == RAW_PATH
        assert preview["candidates"][0]["sha256"] == expected_hash


def test_real_jin10_candle_still_has_no_receipt_or_retention_candidate(migrated_warehouse):
    factory, root, _raw_file, _payload = migrated_warehouse
    jin10_path = "raw/market/jin10/2026-09-02/derived.json"
    physical = root / jin10_path
    physical.parent.mkdir(parents=True)
    physical.write_bytes(b'{"source":"jin10_mcp","close":3500.5}\n')
    os.utime(physical, (COLLECTED_AT.timestamp(), COLLECTED_AT.timestamp()))
    source_ref = {
        "provider": "jin10_mcp",
        "source_key": "jin10_mcp_derived_5m",
        "source_role": "market_primary",
        "raw_path": jin10_path,
        "retrieved_at": COLLECTED_AT.isoformat(),
    }
    with factory.begin() as session:
        row = _persisted_candle(
            source="jin10_mcp_derived_5m",
            source_ref=source_ref,
            raw_path=jin10_path,
        )
        session.add(row)
        row_id = row.id
        result = ingest_collection_records(
            session,
            "candles",
            record_ids=[row_id],
            storage_root=root,
        )
        assert result["rejected"] == 1
        assert result["raw_ready"] == 0
        assert result["raw_blocked"][0]["reason"] == "RAW_WAREHOUSE_COVERAGE_INCOMPLETE"

    with factory() as session:
        batch = session.scalar(select(LoadBatch))
        assert (batch.status, batch.error_code, batch.rejected) == (
            "rejected",
            "DWH_NUMERIC_SOURCE_FORBIDDEN",
            1,
        )
        assert session.scalar(select(func.count()).select_from(CandleFact)) == 0
        assert session.scalar(select(func.count()).select_from(BatchSourceFile)) == 0
        assert session.scalar(select(func.count()).select_from(RawSourceLoad)) == 0
        preview = preview_raw_retention(
            session,
            storage_root=root,
            now=RETENTION_NOW,
            retention_days=30,
            limit=10,
        )
        assert preview["candidate_count"] == 0
        assert preview["blocked_count"] == 1
        assert preview["blocked"][0]["reason"] == "LOAD_COVERAGE_INCOMPLETE"


def test_prepare_record_accepts_legacy_diagnostic_without_mutating_lineage():
    record = _record(_ref())
    original = dict(record)

    batch, producer, facts = prepare_record(None, "candles", record, None, {})

    assert producer is None
    assert batch["source_cursor"] == record["id"]
    assert facts[0][0]["source_role"] == "fallback"
    assert facts[0][0]["quality_status"] == "accepted_fallback"
    assert facts[0][0]["close"] == 3500.5
    assert record == original


@pytest.mark.parametrize(
    "ref",
    [
        _ref(provider="jin10_mcp"),
        _ref(source_key="twelvedata_xauusd_jin10"),
        _ref(raw_path="raw/jin10/legacy.json"),
        _ref(component_source_refs=[{"provider": "jin10_mcp"}]),
        _ref(fallback_reason="derived_from_jin10"),
    ],
)
def test_prepare_record_rejects_non_exact_legacy_lineage(ref):
    with pytest.raises(WarehouseError, match="DWH_NUMERIC_SOURCE_FORBIDDEN"):
        prepare_record(None, "candles", _record(ref), None, {})
