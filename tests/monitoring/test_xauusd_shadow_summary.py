from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.monitoring.xauusd_shadow_summary import (
    ShadowArtifactConflictError,
    build_xauusd_shadow_summary,
    default_shadow_output_path,
    write_xauusd_shadow_summary,
)
from database.models.analysis import ensure_analysis_tables
from database.queries.market import upsert_market_candle


def _factory():
    engine = create_engine("sqlite:///:memory:")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        ensure_analysis_tables(session)
    return factory


def _seed_5m(session, *, day: date, jin10: bool, twelve: bool, count: int = 288) -> None:
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    for index in range(count):
        open_time = start + timedelta(minutes=5 * index)
        if jin10:
            upsert_market_candle(
                session,
                asset="XAUUSD",
                timeframe="5m",
                open_time=open_time,
                open=4200 + index,
                high=4201 + index,
                low=4199 + index,
                close=4200.5 + index,
                source="jin10_mcp_derived_5m",
                raw_path="raw/market/jin10.json",
            )
        if twelve:
            upsert_market_candle(
                session,
                asset="XAUUSD",
                timeframe="5m",
                open_time=open_time,
                open=4200.1 + index,
                high=4201.1 + index,
                low=4199.1 + index,
                close=4200.6 + index,
                source="twelvedata_xauusd_5m",
                raw_path="raw/market/twelvedata.json",
            )


def _diagnostic(root, *, day: date, timeframe: str = "5m", **overrides) -> None:
    directory = root / "monitoring" / "market_data" / "twelvedata" / day.isoformat()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "ok",
        "timeframe": timeframe,
        "request_count": 1,
        "fallback_count": 2,
        "fallback_open_times": ["2026-07-16T00:00:00+00:00", "2026-07-16T00:05:00+00:00"],
        "persisted": 10,
        "credits_used": 1,
        "credits_left": 799,
    }
    payload.update(overrides)
    (directory / f"{timeframe}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_complete_summary_has_real_percentiles_and_boundary_diagnostics(tmp_path):
    factory = _factory()
    day = date(2026, 7, 16)
    with factory() as session:
        _seed_5m(session, day=day, jin10=True, twelve=True)
        session.commit()
        for timeframe in ("5m", "15m", "1h", "4h"):
            _diagnostic(tmp_path, day=day, timeframe=timeframe)
        payload = build_xauusd_shadow_summary(
            session,
            trade_date=day,
            storage_root=tmp_path,
            as_of=datetime(2026, 7, 17, 0, 11, tzinfo=UTC),
        )

    assert payload["status"] == "pass"
    assert payload["jin10"]["success"] is True
    assert payload["canonical_5m"]["completeness"]["status"] == "complete"
    assert payload["twelvedata"]["request_count"] == 4
    assert payload["twelvedata"]["fallback_count"] == 8
    assert payload["comparison"]["sample_count"] == 288
    assert payload["comparison"]["p50_bps"] is not None
    assert set(payload["boundary_diagnostics"]) == {"5m", "15m", "1h", "4h"}
    assert payload["finalization"]["finalized"] is True
    assert payload["rollup"]["completed_trade_days"] == 1
    assert payload["rollup"]["status"] == "collecting"


def test_partial_and_empty_samples_do_not_create_fake_percentiles(tmp_path):
    factory = _factory()
    partial_day = date(2026, 7, 15)
    empty_day = date(2026, 7, 14)
    with factory() as session:
        _seed_5m(session, day=partial_day, jin10=True, twelve=True, count=1)
        session.commit()
        partial = build_xauusd_shadow_summary(
            session,
            trade_date=partial_day,
            storage_root=tmp_path,
            as_of=datetime(2026, 7, 16, 0, 11, tzinfo=UTC),
        )
        empty = build_xauusd_shadow_summary(
            session,
            trade_date=empty_day,
            storage_root=tmp_path,
            as_of=datetime(2026, 7, 15, 0, 11, tzinfo=UTC),
        )

    assert partial["status"] == "partial"
    assert partial["comparison"]["availability"] == "partial"
    assert partial["comparison"]["p50_bps"] is None
    assert partial["comparison"]["p95_bps"] is None
    assert partial["comparison"]["p99_bps"] is None
    assert empty["status"] == "unavailable"
    assert empty["comparison"]["availability"] == "unavailable"
    assert empty["comparison"]["p50_bps"] is None


def test_fallback_and_quota_exhaustion_are_explicit(tmp_path):
    factory = _factory()
    day = date(2026, 7, 13)
    with factory() as session:
        _seed_5m(session, day=day, jin10=False, twelve=True, count=1)
        session.commit()
        _diagnostic(tmp_path, day=day, status="minute_quota_exhausted", request_count=0, credits_left=0)
        payload = build_xauusd_shadow_summary(
            session,
            trade_date=day,
            storage_root=tmp_path,
            as_of=datetime(2026, 7, 14, 0, 11, tzinfo=UTC),
        )

    assert payload["status"] == "fail"
    assert payload["jin10"]["success"] is False
    assert payload["canonical_5m"]["source_breakdown"] == {"twelvedata_xauusd_5m": 1}
    assert payload["twelvedata"]["quota"]["exhausted"] is True
    assert "twelvedata_quota_exhausted" in payload["reasons"]


def test_ten_day_rollup_uses_only_explicit_daily_artifacts(tmp_path):
    factory = _factory()
    first_day = date(2026, 7, 1)
    trade_days: list[date] = []
    candidate = first_day
    while len(trade_days) < 10:
        if candidate.weekday() < 5:
            trade_days.append(candidate)
        candidate += timedelta(days=1)
    for trade_day in trade_days[:9]:
        artifact = default_shadow_output_path(storage_root=tmp_path, trade_date=trade_day)
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            json.dumps(
                {
                    "artifact_type": "xauusd_shadow_summary",
                    "trade_date": trade_day.isoformat(),
                    "status": "pass",
                    "finalization": {"finalized": True, "is_trade_day": True},
                }
            ),
            encoding="utf-8",
        )
    day = trade_days[9]
    with factory() as session:
        _seed_5m(session, day=day, jin10=True, twelve=True)
        session.commit()
        for timeframe in ("5m", "15m", "1h", "4h"):
            _diagnostic(tmp_path, day=day, timeframe=timeframe)
        payload = build_xauusd_shadow_summary(
            session,
            trade_date=day,
            storage_root=tmp_path,
            as_of=datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            + timedelta(minutes=11),
        )

    assert payload["rollup"]["completed_trade_days"] == 10
    assert payload["rollup"]["status"] == "pass"


def test_write_is_idempotent_and_refuses_different_inputs(tmp_path):
    path = default_shadow_output_path(storage_root=tmp_path, trade_date="2026-07-16")
    payload = {
        "artifact_type": "xauusd_shadow_summary",
        "trade_date": "2026-07-16",
        "status": "partial",
        "finalization": {"finalized": True, "is_trade_day": True},
    }
    _, created = write_xauusd_shadow_summary(payload, output_path=path)
    _, created_again = write_xauusd_shadow_summary(payload, output_path=path)

    assert created is True
    assert created_again is False
    with pytest.raises(ShadowArtifactConflictError):
        write_xauusd_shadow_summary({**payload, "status": "pass"}, output_path=path)


def test_intraday_preview_is_not_counted_or_writable(tmp_path):
    factory = _factory()
    day = date(2026, 7, 17)
    with factory() as session:
        _seed_5m(session, day=day, jin10=True, twelve=True, count=2)
        session.commit()
        payload = build_xauusd_shadow_summary(
            session,
            trade_date=day,
            storage_root=tmp_path,
            as_of=datetime(2026, 7, 17, 12, 0, tzinfo=UTC),
        )

    assert payload["finalization"]["finalized"] is False
    assert payload["rollup"]["completed_trade_days"] == 0
    with pytest.raises(ValueError, match="finalized"):
        write_xauusd_shadow_summary(
            payload,
            output_path=default_shadow_output_path(storage_root=tmp_path, trade_date=day),
        )


def test_boundary_diagnostics_compare_canonical_and_native_starts(tmp_path):
    factory = _factory()
    day = date(2026, 7, 16)
    with factory() as session:
        _seed_5m(session, day=day, jin10=True, twelve=True, count=3)
        upsert_market_candle(
            session,
            asset="XAUUSD",
            timeframe="15m",
            open_time=datetime(2026, 7, 16, 0, 5, tzinfo=UTC),
            open=4200,
            high=4201,
            low=4199,
            close=4200.5,
            source="twelvedata_xauusd_15m",
        )
        session.commit()
        payload = build_xauusd_shadow_summary(
            session,
            trade_date=day,
            storage_root=tmp_path,
            as_of=datetime(2026, 7, 17, 0, 11, tzinfo=UTC),
        )

    boundary = payload["boundary_diagnostics"]["15m"]
    assert boundary["canonical_only_bucket_starts"] == ["2026-07-16T00:00:00+00:00"]
    assert boundary["native_only_bucket_starts"] == ["2026-07-16T00:05:00+00:00"]
    assert boundary["overlap_alignment_ratio"] == 0.0
    assert boundary["native_coverage_ratio"] == 0.0
    assert boundary["boundary_mismatch_count"] == 1
