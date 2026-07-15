from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.collectors.twelvedata import TwelveDataCandle, TwelveDataFetchResult
from apps.scheduler import twelvedata_refresh as scheduler
from database.models.analysis import DataSourceStatus, MarketCandle, ensure_analysis_tables
from database.queries.data_source_status import upsert_data_source_status
from database.queries.market import upsert_market_candle


def _factory():
    engine = create_engine("sqlite:///:memory:", echo=False)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        ensure_analysis_tables(session)
    return factory


def test_refresh_twelvedata_persists_closed_bars_and_records_fallback(monkeypatch, tmp_path):
    factory = _factory()
    with factory() as session:
        upsert_market_candle(
            session,
            asset="XAUUSD",
            timeframe="5m",
            open_time=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
            open=4200.0,
            high=4202.0,
            low=4199.0,
            close=4201.0,
            source="jin10_mcp_derived_5m",
        )
        session.commit()

    result = TwelveDataFetchResult(
        symbol="XAU/USD",
        provider_interval="5min",
        timeframe="5m",
        candles=(
            TwelveDataCandle(datetime(2026, 7, 16, 11, 55, tzinfo=UTC), 4198.0, 4200.0, 4197.0, 4199.0),
            TwelveDataCandle(datetime(2026, 7, 16, 12, 0, tzinfo=UTC), 4200.1, 4202.1, 4199.1, 4201.1),
            TwelveDataCandle(datetime(2026, 7, 16, 12, 5, tzinfo=UTC), 4201.1, 4203.0, 4200.0, 4202.0),
        ),
        retrieved_at=datetime(2026, 7, 16, 12, 6, 30, tzinfo=UTC),
        raw_path="raw/market/twelvedata/2026-07-16/XAU-USD-5min.json",
        http_status=200,
        credits_used=1,
        credits_left=799,
    )

    class FakeClient:
        def __init__(self, *, storage_root):
            assert storage_root == tmp_path

        def fetch_time_series(self, *, interval: str, outputsize: int):
            assert interval == "5min"
            assert outputsize == 10
            return result

    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    monkeypatch.setattr(scheduler, "TwelveDataClient", FakeClient)

    summary = scheduler.refresh_twelvedata_xauusd(
        "5min",
        now=datetime(2026, 7, 16, 12, 6, 30, tzinfo=UTC),
        storage_root=tmp_path,
    )

    assert summary["status"] == "ok"
    assert summary["persisted"] == 2
    assert summary["fallback_count"] == 1
    assert summary["comparison"]["sample_count"] == 1
    assert (tmp_path / summary["diagnostics_path"]).exists()

    with factory() as session:
        rows = (
            session.query(MarketCandle)
            .filter_by(source="twelvedata_xauusd_5m")
            .order_by(MarketCandle.open_time.asc())
            .all()
        )
        status = session.query(DataSourceStatus).filter_by(source_key="twelvedata_xauusd").one()

    assert len(rows) == 2
    assert rows[0].source_ref["source_role"] == "fallback"
    assert rows[0].source_ref["quality_status"] == "accepted_fallback"
    assert rows[1].source_ref["source_role"] == "validation"
    assert rows[1].source_ref["quality_status"] == "accepted_validation"
    assert rows[1].volume is None
    assert status.status == "ok"
    assert status.source_metadata["normal_scheduled_requests_per_day"] == 414
    assert status.source_metadata["credit_headers_scope"] == "minute"
    assert status.source_metadata["intervals"]["5m"]["credits_left"] == 799


def test_refresh_twelvedata_skips_request_after_minute_quota_exhaustion(monkeypatch, tmp_path):
    factory = _factory()
    with factory() as session:
        upsert_data_source_status(
            session,
            {
                "source_key": "twelvedata_xauusd",
                "source_name": "Twelve Data XAU/USD",
                "source_metadata": {
                    "intervals": {
                        "5m": {
                            "credits_left": 0,
                            "retrieved_at": "2026-07-16T12:16:05+00:00",
                        }
                    }
                },
            },
        )
        session.commit()
        assert scheduler._minute_quota_exhausted(
            session,
            datetime(2026, 7, 16, 12, 17, tzinfo=UTC),
        ) is False

    class UnexpectedClient:
        def __init__(self, **kwargs):
            raise AssertionError("provider request must be skipped")

    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    monkeypatch.setattr(scheduler, "TwelveDataClient", UnexpectedClient)

    summary = scheduler.refresh_twelvedata_xauusd(
        "15min",
        now=datetime(2026, 7, 16, 12, 16, 30, tzinfo=UTC),
        storage_root=tmp_path,
    )

    assert summary["status"] == "minute_quota_exhausted"
    assert summary["persisted"] == 0


def test_dispatcher_runs_due_intervals_sequentially(monkeypatch, tmp_path):
    factory = _factory()
    calls: list[str] = []

    def fake_refresh(interval, **kwargs):
        calls.append(interval)
        return {"status": "ok", "interval": interval, "credits_left": 10 - len(calls)}

    monkeypatch.setattr(scheduler, "refresh_twelvedata_xauusd", fake_refresh)
    monkeypatch.setattr(scheduler, "SessionLocal", factory)

    summary = scheduler.refresh_due_twelvedata_xauusd(
        now=datetime(2026, 7, 16, 5, 1, 30, tzinfo=UTC),
        storage_root=tmp_path,
    )

    assert summary["status"] == "ok"
    assert calls == ["5min", "15min", "1h", "4h"]
    assert summary["executed_intervals"] == calls


def test_dispatcher_stops_remaining_due_intervals_when_minute_quota_is_exhausted(monkeypatch):
    factory = _factory()
    calls: list[str] = []

    def fake_refresh(interval, **kwargs):
        calls.append(interval)
        return {
            "status": "ok",
            "interval": interval,
            "credits_left": 0 if interval == "15min" else 5,
        }

    monkeypatch.setattr(scheduler, "refresh_twelvedata_xauusd", fake_refresh)
    monkeypatch.setattr(scheduler, "SessionLocal", factory)

    summary = scheduler.refresh_due_twelvedata_xauusd(
        now=datetime(2026, 7, 16, 5, 1, 30, tzinfo=UTC),
    )

    assert calls == ["5min", "15min"]
    assert summary["status"] == "partial"
    assert summary["stopped_reason"] == "minute_quota_exhausted"


def test_dispatcher_skips_requests_when_process_lock_is_busy(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "refresh_twelvedata_xauusd",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("request must not run")),
    )
    assert scheduler._TWELVE_DATA_DISPATCH_PROCESS_LOCK.acquire(blocking=False) is True
    try:
        summary = scheduler.refresh_due_twelvedata_xauusd(
            now=datetime(2026, 7, 16, 5, 1, 30, tzinfo=UTC),
        )
    finally:
        scheduler._TWELVE_DATA_DISPATCH_PROCESS_LOCK.release()

    assert summary["status"] == "dispatch_busy"
    assert summary["executed_intervals"] == []
