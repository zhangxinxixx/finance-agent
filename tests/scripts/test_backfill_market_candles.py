from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts.backfill_market_candles import (
    _extract_jin10_kline_rows,
    _parse_openbb_intraday_payload,
    _parse_jin10_hourly_candles,
    _parse_jin10_hourly_candles_from_payloads,
    _parse_jin10_minute_candles,
    _parse_jin10_minute_candles_from_payloads,
    _parse_yahoo_daily_candles,
    _start_day_for_range,
    _target_minutes_to_batches,
    summarize_candles,
)


def test_parse_yahoo_daily_candles_extracts_valid_rows() -> None:
    payload = {
        "chart": {
            "result": [{
                "timestamp": [1746403200, 1746489600],
                "indicators": {
                    "quote": [{
                        "open": [3300.0, 3310.0],
                        "high": [3320.0, 3330.0],
                        "low": [3290.0, 3305.0],
                        "close": [3315.0, 3324.0],
                        "volume": [100, 120],
                    }],
                },
            }],
        },
    }

    candles = _parse_yahoo_daily_candles(payload)

    assert len(candles) == 2
    assert candles[0]["open_time"] == datetime.fromtimestamp(1746403200, tz=UTC)
    assert candles[0]["close"] == 3315.0
    assert candles[1]["volume"] == 120.0


def test_parse_yahoo_daily_candles_skips_incomplete_rows() -> None:
    payload = {
        "chart": {
            "result": [{
                "timestamp": [1746403200, 1746489600],
                "indicators": {
                    "quote": [{
                        "open": [3300.0, None],
                        "high": [3320.0, 3330.0],
                        "low": [3290.0, 3305.0],
                        "close": [3315.0, 3324.0],
                        "volume": [100, 120],
                    }],
                },
            }],
        },
    }

    candles = _parse_yahoo_daily_candles(payload)

    assert len(candles) == 1
    assert candles[0]["close"] == 3315.0


def test_backfill_market_candles_supports_dxy_yahoo_payload(tmp_path: Path) -> None:
    payload = {
        "chart": {
            "result": [{
                "timestamp": [1746403200, 1746489600],
                "indicators": {
                    "quote": [{
                        "open": [100.1, 100.4],
                        "high": [100.3, 100.8],
                        "low": [99.9, 100.2],
                        "close": [100.2, 100.7],
                        "volume": [None, None],
                    }],
                },
            }],
        },
    }
    storage_root = tmp_path / "storage"
    input_json = storage_root / "raw" / "fixtures" / "dx-y-nyb-3mo-1d.json"
    input_json.parent.mkdir(parents=True, exist_ok=True)
    input_json.write_text(json.dumps(payload), encoding="utf-8")
    db_path = tmp_path / "market-candles.db"

    from scripts.backfill_market_candles import main
    import sys

    argv = sys.argv[:]
    try:
        sys.argv = [
            "backfill_market_candles.py",
            "--asset",
            "DXY",
            "--database-url",
            f"sqlite:///{db_path}",
            "--storage-root",
            str(storage_root),
            "--input-json",
            str(input_json),
        ]
        main()
    finally:
        sys.argv = argv

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models.analysis import MarketCandle, ensure_analysis_tables

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    ensure_analysis_tables(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    rows = session.query(MarketCandle).order_by(MarketCandle.open_time.asc()).all()
    assert len(rows) == 2
    assert rows[0].asset == "DXY"
    assert rows[0].timeframe == "1d"
    assert rows[1].close == 100.7


def test_backfill_market_candles_supports_dxy_openbb_payload(tmp_path: Path) -> None:
    payload = {
        "symbol": "DX-Y.NYB",
        "source": "openbb_yfinance",
        "retrieved_date": "2026-05-30",
        "latest": [
            {"open": 99.08, "high": 99.26, "low": 98.97, "close": 99.21, "volume": 0},
            {"open": 99.27, "high": 99.54, "low": 98.95, "close": 99.02, "volume": 0},
            {"open": 99.00, "high": 99.19, "low": 98.75, "close": 98.91, "volume": 0},
        ],
    }
    storage_root = tmp_path / "storage"
    input_json = storage_root / "raw" / "macro" / "openbb_yfinance" / "2026-05-30" / "DX-Y.NYB-test.json"
    input_json.parent.mkdir(parents=True, exist_ok=True)
    input_json.write_text(json.dumps(payload), encoding="utf-8")
    db_path = tmp_path / "market-candles.db"

    from scripts.backfill_market_candles import main
    import sys

    argv = sys.argv[:]
    try:
        sys.argv = [
            "backfill_market_candles.py",
            "--asset",
            "DXY",
            "--database-url",
            f"sqlite:///{db_path}",
            "--storage-root",
            str(storage_root),
            "--input-json",
            str(input_json),
        ]
        main()
    finally:
        sys.argv = argv

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models.analysis import MarketCandle, ensure_analysis_tables

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    ensure_analysis_tables(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    rows = session.query(MarketCandle).order_by(MarketCandle.open_time.asc()).all()
    assert len(rows) == 3
    assert rows[0].asset == "DXY"
    assert rows[0].close == 99.21
    assert rows[2].close == 98.91


def test_backfill_market_candles_offline_import(tmp_path: Path) -> None:
    payload = {
        "chart": {
            "result": [{
                "timestamp": [1746403200, 1746489600],
                "indicators": {
                    "quote": [{
                        "open": [3300.0, 3310.0],
                        "high": [3320.0, 3330.0],
                        "low": [3290.0, 3305.0],
                        "close": [3315.0, 3324.0],
                        "volume": [100, 120],
                    }],
                },
            }],
        },
    }
    storage_root = tmp_path / "storage"
    input_json = storage_root / "raw" / "fixtures" / "gc-f-3mo-1d.json"
    input_json.parent.mkdir(parents=True, exist_ok=True)
    input_json.write_text(json.dumps(payload), encoding="utf-8")
    db_path = tmp_path / "market-candles.db"

    from scripts.backfill_market_candles import main
    import sys

    argv = sys.argv[:]
    try:
        sys.argv = [
            "backfill_market_candles.py",
            "--database-url",
            f"sqlite:///{db_path}",
            "--storage-root",
            str(storage_root),
            "--input-json",
            str(input_json),
        ]
        main()
    finally:
        sys.argv = argv

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models.analysis import MarketCandle, ensure_analysis_tables

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    ensure_analysis_tables(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    rows = session.query(MarketCandle).order_by(MarketCandle.open_time.asc()).all()
    assert len(rows) == 2
    assert rows[0].asset == "GC"
    assert rows[0].timeframe == "1d"
    assert rows[0].source_ref["provider_symbol"] == "GC=F"
    assert rows[0].source_ref["instrument_type"] == "futures_continuous_proxy"
    assert rows[1].close == 3324.0


def test_backfill_market_candles_dry_run_outputs_coverage_without_db_write(tmp_path: Path, capsys) -> None:
    payload = {
        "chart": {
            "result": [{
                "timestamp": [1746403200, 1746489600, 1747008000],
                "indicators": {
                    "quote": [{
                        "open": [3300.0, 3310.0, 3320.0],
                        "high": [3320.0, 3330.0, 3340.0],
                        "low": [3290.0, 3305.0, 3315.0],
                        "close": [3315.0, 3324.0, 3333.0],
                        "volume": [100, 120, 130],
                    }],
                },
            }],
        },
    }
    storage_root = tmp_path / "storage"
    input_json = storage_root / "raw" / "fixtures" / "gc-f-1y-1d.json"
    input_json.parent.mkdir(parents=True, exist_ok=True)
    input_json.write_text(json.dumps(payload), encoding="utf-8")
    db_path = tmp_path / "market-candles.db"

    from scripts.backfill_market_candles import main
    import sys

    argv = sys.argv[:]
    try:
        sys.argv = [
            "backfill_market_candles.py",
            "--database-url",
            f"sqlite:///{db_path}",
            "--storage-root",
            str(storage_root),
            "--input-json",
            str(input_json),
            "--dry-run",
            "--range",
            "1y",
        ]
        main()
    finally:
        sys.argv = argv

    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["scanned"] == 3
    assert output["imported"] == 0
    assert output["first_time"] == datetime.fromtimestamp(1746403200, tz=UTC).isoformat()
    assert output["last_time"] == datetime.fromtimestamp(1747008000, tz=UTC).isoformat()
    assert output["gap_count"] == 1
    assert db_path.exists() is False


def test_backfill_market_candles_repair_gaps_dry_run_reads_existing_db_only(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "market-candles.db"
    database_url = f"sqlite:///{db_path}"

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models.analysis import MarketCandle, ensure_analysis_tables
    from database.queries.market import upsert_market_candle

    engine = create_engine(database_url, echo=False)
    ensure_analysis_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    base_time = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    with factory() as session:
        for minute in (0, 1, 10):
            upsert_market_candle(
                session,
                asset="XAUUSD",
                timeframe="1m",
                open_time=base_time.replace(minute=minute),
                open=3300.0 + minute,
                high=3301.0 + minute,
                low=3299.0 + minute,
                close=3300.5 + minute,
                source="jin10_mcp_kline_1m",
            )
        session.commit()

    from scripts.backfill_market_candles import main
    import sys

    argv = sys.argv[:]
    try:
        sys.argv = [
            "backfill_market_candles.py",
            "--asset",
            "XAUUSD",
            "--timeframe",
            "1m",
            "--database-url",
            database_url,
            "--dry-run",
            "--repair-gaps",
        ]
        main()
    finally:
        sys.argv = argv

    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["repair_gaps"] is True
    assert output["scanned"] == 0
    assert output["gap_count"] == 1
    assert output["max_gap_seconds"] == 540
    assert output["gap_ranges"] == [{
        "from": "2026-07-01T00:01:00+00:00",
        "to": "2026-07-01T00:10:00+00:00",
        "gap_seconds": 540,
    }]

    with factory() as session:
        assert session.query(MarketCandle).count() == 3


def test_target_minutes_derives_jin10_batches() -> None:
    assert _target_minutes_to_batches(1) == 1
    assert _target_minutes_to_batches(100) == 1
    assert _target_minutes_to_batches(101) == 2
    assert _target_minutes_to_batches(3000) == 30


def test_start_day_for_range_supports_daily_history_windows() -> None:
    end_day = datetime(2026, 7, 6, tzinfo=UTC).date()

    assert _start_day_for_range(end_day, "1y").isoformat() == "2025-07-06"
    assert _start_day_for_range(end_day, "2y").isoformat() == "2024-07-06"
    assert _start_day_for_range(end_day, "5d").isoformat() == "2026-07-01"
    assert _start_day_for_range(end_day, "ytd").isoformat() == "2026-01-01"


def test_summarize_candles_reports_gap_bounds() -> None:
    candles = [
        {"open_time": datetime(2026, 7, 1, 0, 0, tzinfo=UTC)},
        {"open_time": datetime(2026, 7, 1, 0, 1, tzinfo=UTC)},
        {"open_time": datetime(2026, 7, 1, 0, 10, tzinfo=UTC)},
    ]

    summary = summarize_candles(candles, timeframe="1m")

    assert summary["first_time"] == "2026-07-01T00:00:00+00:00"
    assert summary["last_time"] == "2026-07-01T00:10:00+00:00"
    assert summary["gap_count"] == 1
    assert summary["max_gap_seconds"] == 540


def test_parse_jin10_hourly_candles_aggregates_minute_rows() -> None:
    payload = {
        "data": {
            "code": "XAUUSD",
            "klines": [
                {"time": 1749002400, "open": "3360.0", "high": "3362.0", "low": "3359.0", "close": "3361.0", "volume": 10},
                {"time": 1749002460, "open": "3361.0", "high": "3364.0", "low": "3360.5", "close": "3363.0", "volume": 12},
                {"time": 1749006000, "open": "3363.0", "high": "3365.0", "low": "3362.0", "close": "3364.5", "volume": 8},
            ],
        },
    }

    candles = _parse_jin10_hourly_candles(payload)

    assert len(candles) == 2
    assert candles[0]["open"] == 3360.0
    assert candles[0]["high"] == 3364.0
    assert candles[0]["low"] == 3359.0
    assert candles[0]["close"] == 3363.0
    assert candles[0]["volume"] == 22.0


def test_parse_jin10_minute_candles_preserves_mcp_minute_rows() -> None:
    payload = {
        "data": {
            "code": "XAUUSD",
            "klines": [
                {"time": 1749002400, "open": "3360.0", "high": "3362.0", "low": "3359.0", "close": "3361.0", "volume": 10},
                {"time": 1749002460, "open": "3361.0", "high": "3364.0", "low": "3360.5", "close": "3363.0", "volume": 12},
            ],
        },
    }

    candles = _parse_jin10_minute_candles(payload)

    assert len(candles) == 2
    assert candles[0]["open_time"] == datetime.fromtimestamp(1749002400, tz=UTC)
    assert candles[0]["open"] == 3360.0
    assert candles[1]["open_time"] == datetime.fromtimestamp(1749002460, tz=UTC)
    assert candles[1]["close"] == 3363.0


def test_parse_jin10_hourly_candles_from_payloads_merges_batches_without_duplicates() -> None:
    payload_a = {
        "data": {
            "klines": [
                {"time": 1749002400, "open": "3360.0", "high": "3362.0", "low": "3359.0", "close": "3361.0", "volume": 10},
                {"time": 1749002460, "open": "3361.0", "high": "3364.0", "low": "3360.5", "close": "3363.0", "volume": 12},
            ]
        }
    }
    payload_b = {
        "data": {
            "klines": [
                {"time": 1749002460, "open": "3361.0", "high": "3364.0", "low": "3360.5", "close": "3363.0", "volume": 12},
                {"time": 1749006000, "open": "3363.0", "high": "3365.0", "low": "3362.0", "close": "3364.5", "volume": 8},
            ]
        }
    }

    candles = _parse_jin10_hourly_candles_from_payloads([payload_a, payload_b])

    assert len(candles) == 2
    assert candles[0]["open"] == 3360.0
    assert candles[0]["close"] == 3363.0
    assert candles[1]["close"] == 3364.5


def test_parse_jin10_minute_candles_from_payloads_merges_without_hourly_aggregation() -> None:
    payload_a = {
        "data": {
            "klines": [
                {"time": 1749002400, "open": "3360.0", "high": "3362.0", "low": "3359.0", "close": "3361.0", "volume": 10},
                {"time": 1749002460, "open": "3361.0", "high": "3364.0", "low": "3360.5", "close": "3363.0", "volume": 12},
            ]
        }
    }
    payload_b = {
        "data": {
            "klines": [
                {"time": 1749002460, "open": "3361.0", "high": "3364.0", "low": "3360.5", "close": "3363.0", "volume": 12},
                {"time": 1749002520, "open": "3363.0", "high": "3365.0", "low": "3362.0", "close": "3364.5", "volume": 8},
            ]
        }
    }

    candles = _parse_jin10_minute_candles_from_payloads([payload_a, payload_b])

    assert len(candles) == 3
    assert candles[0]["open_time"] == datetime.fromtimestamp(1749002400, tz=UTC)
    assert candles[1]["open_time"] == datetime.fromtimestamp(1749002460, tz=UTC)
    assert candles[2]["open_time"] == datetime.fromtimestamp(1749002520, tz=UTC)


def test_extract_jin10_kline_rows_supports_klines_list_data_shapes() -> None:
    payloads = [
        {"data": {"klines": [{"time": 1}, {"time": 2}]}},
        {"data": {"list": [{"time": 3}]}},
        {"data": {"data": [{"time": 4}]}},
    ]

    assert [row["time"] for row in _extract_jin10_kline_rows(payloads[0])] == [1, 2]
    assert [row["time"] for row in _extract_jin10_kline_rows(payloads[1])] == [3]
    assert [row["time"] for row in _extract_jin10_kline_rows(payloads[2])] == [4]


def test_parse_openbb_intraday_payload_preserves_full_hourly_history() -> None:
    payload = {
        "source": "openbb_yfinance",
        "interval": "60m",
        "latest": [
            {"date": "2026-03-01T00:00:00+00:00", "open": 2860.0, "high": 2865.0, "low": 2858.0, "close": 2862.0, "volume": 10},
            {"date": "2026-06-01T00:00:00+00:00", "open": 3340.0, "high": 3350.0, "low": 3335.0, "close": 3348.0, "volume": 18},
        ],
    }

    candles = _parse_openbb_intraday_payload(payload)

    assert len(candles) == 2
    assert candles[0]["open_time"] == datetime.fromisoformat("2026-03-01T00:00:00+00:00")
    assert candles[1]["close"] == 3348.0


def test_backfill_market_candles_supports_jin10_1m_payload(tmp_path: Path) -> None:
    payload = {
        "data": {
            "code": "XAUUSD",
            "klines": [
                {"time": 1749002400, "open": "3360.0", "high": "3362.0", "low": "3359.0", "close": "3361.0", "volume": 10},
                {"time": 1749002460, "open": "3361.0", "high": "3364.0", "low": "3360.5", "close": "3363.0", "volume": 12},
            ],
        },
    }
    storage_root = tmp_path / "storage"
    input_json = storage_root / "raw" / "macro" / "jin10_mcp" / "2026-06-05" / "kline_XAUUSD-test.json"
    input_json.parent.mkdir(parents=True, exist_ok=True)
    input_json.write_text(json.dumps(payload), encoding="utf-8")
    db_path = tmp_path / "market-candles.db"

    from scripts.backfill_market_candles import main
    import sys

    argv = sys.argv[:]
    try:
        sys.argv = [
            "backfill_market_candles.py",
            "--asset",
            "XAUUSD",
            "--timeframe",
            "1m",
            "--database-url",
            f"sqlite:///{db_path}",
            "--storage-root",
            str(storage_root),
            "--input-json",
            str(input_json),
        ]
        main()
    finally:
        sys.argv = argv

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models.analysis import MarketCandle, ensure_analysis_tables

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    ensure_analysis_tables(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    rows = session.query(MarketCandle).order_by(MarketCandle.open_time.asc()).all()
    assert len(rows) == 2
    assert rows[0].asset == "XAUUSD"
    assert rows[0].timeframe == "1m"
    assert rows[1].close == 3363.0
