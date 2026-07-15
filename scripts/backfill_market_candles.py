from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from math import ceil
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.parsers.macro.storage import archive_raw_payload  # noqa: E402
from apps.collectors.jin10.mcp_client import Jin10MCPClient  # noqa: E402
from database.models.analysis import MarketCandle, ensure_analysis_tables  # noqa: E402
from database.models.engine import DATABASE_URL, SessionLocal  # noqa: E402
from database.queries.market import upsert_market_candle  # noqa: E402


YAHOO_GC_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
YAHOO_DXY_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB"


@dataclass
class ImportResult:
    scanned: int = 0
    imported: int = 0
    skipped: int = 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill market candles into market_candles.")
    parser.add_argument("--asset", default="GC", help="Supported: GC (GC=F), XAUUSD (1m staging), DXY")
    parser.add_argument("--timeframe", default="1d", help="Supported now: 1d, 1h, 1m")
    parser.add_argument("--range", dest="range_", default="1y", help="Historical range for 1d fallback fetches, for example 3mo/1y/2y/5y.")
    parser.add_argument("--start-date", default="", help="Optional start date YYYY-MM-DD for OpenBB-backed 1d/1h fetches.")
    parser.add_argument("--end-date", default="", help="Optional end date YYYY-MM-DD for OpenBB-backed 1d/1h fetches.")
    parser.add_argument("--input-json", default="", help="Optional local Yahoo chart payload JSON path for offline import")
    parser.add_argument("--jin10-batches", type=int, default=1, help="For Jin10 intraday import, how many 100-minute batches to fetch sequentially.")
    parser.add_argument("--target-minutes", type=int, default=0, help="For 1m Jin10 import, derive batches from target minutes.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and summarize candles without writing to the database.")
    parser.add_argument("--repair-gaps", action="store_true", help="Inspect existing DB gaps; non-dry-run then upserts the configured fetch window.")
    parser.add_argument(
        "--storage-root",
        default=str(PROJECT_ROOT / "storage"),
        help="Project storage root. Default: ./storage",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="Optional SQLAlchemy database URL. Defaults to DATABASE_URL.",
    )
    args = parser.parse_args()

    asset = args.asset.upper()
    timeframe = args.timeframe.lower()
    if asset not in {"GC", "XAUUSD", "DXY"}:
        raise SystemExit(f"unsupported --asset {asset!r}; currently only GC, XAUUSD and DXY are implemented")
    if timeframe not in {"1d", "1h", "1m"}:
        raise SystemExit(f"unsupported --timeframe {timeframe!r}; currently only 1d, 1h and 1m are implemented")
    if asset == "DXY" and timeframe != "1d":
        raise SystemExit("DXY is only supported as daily candles; do not backfill fabricated intraday DXY data")
    if asset == "GC" and timeframe not in {"1d", "1h"}:
        raise SystemExit("GC is supported as 1d or 1h GC=F candles")
    if asset == "XAUUSD" and timeframe != "1m":
        raise SystemExit("XAUUSD backfill only supports Jin10 1m staging; use --asset GC for GC=F")

    storage_root = Path(args.storage_root).resolve()
    database_url = args.database_url or DATABASE_URL
    start_date = _parse_optional_date(args.start_date, name="--start-date")
    end_date = _parse_optional_date(args.end_date, name="--end-date")
    if start_date and end_date and start_date > end_date:
        raise SystemExit("--start-date must be earlier than or equal to --end-date")
    session_factory = None
    if not args.dry_run:
        session_factory = _session_factory(database_url)
        _ensure_sqlite_parent(database_url)

    existing_gap_summary = inspect_existing_candle_gaps(
        database_url=database_url,
        asset=asset,
        timeframe=timeframe,
    ) if args.repair_gaps else {"gap_count": 0, "gap_ranges": [], "max_gap_seconds": None}

    if args.repair_gaps and args.dry_run and not args.input_json:
        print(
            json.dumps(
                {
                    "asset": asset,
                    "timeframe": timeframe,
                    "dry_run": True,
                    "repair_gaps": True,
                    "scanned": 0,
                    "imported": 0,
                    "skipped": 0,
                    "first_time": existing_gap_summary.get("first_time"),
                    "last_time": existing_gap_summary.get("last_time"),
                    "gap_count": existing_gap_summary["gap_count"],
                    "max_gap_seconds": existing_gap_summary["max_gap_seconds"],
                    "gap_ranges": existing_gap_summary["gap_ranges"],
                    "database_url": _display_database_url(database_url),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return

    if timeframe == "1d":
        candles, raw_path, source, source_ref = collect_daily_candles(
            storage_root=storage_root,
            asset=asset,
            input_json=args.input_json or None,
            range_=args.range_,
            start_date=start_date,
            end_date=end_date,
        )
    elif timeframe == "1h":
        candles, raw_path = collect_intraday_hourly_candles(
            storage_root=storage_root,
            asset=asset,
            input_json=args.input_json or None,
            batches=max(args.jin10_batches, 1),
            start_date=start_date,
            end_date=end_date,
        )
        source = "openbb_yfinance_gc_f_60m"
        source_ref = {
            "provider_symbol": "GC=F",
            "source": "openbb_yfinance",
            "instrument_type": "futures_continuous_proxy",
        }
    else:
        jin10_batches = _target_minutes_to_batches(args.target_minutes) if args.target_minutes else max(args.jin10_batches, 1)
        candles, raw_path = collect_intraday_minute_candles(
            storage_root=storage_root,
            asset=asset,
            input_json=args.input_json or None,
            batches=jin10_batches,
        )
        source = "jin10_mcp_kline_1m"
        source_ref = {"symbol": asset, "source": "jin10_mcp", "provider_timeframe": "1m"}

    result = ImportResult()
    if args.dry_run:
        result.scanned = len(candles)
    else:
        assert session_factory is not None
        with session_factory() as session:
            try:
                ensure_analysis_tables(session)
                for candle in candles:
                    result.scanned += 1
                    before = _candle_count(session)
                    upsert_market_candle(
                        session,
                        asset=asset,
                        timeframe=timeframe,
                        open_time=candle["open_time"],
                        open=candle["open"],
                        high=candle["high"],
                        low=candle["low"],
                        close=candle["close"],
                        volume=candle["volume"],
                        source=source,
                        source_ref=source_ref,
                        raw_path=raw_path,
                    )
                    after = _candle_count(session)
                    if after > before:
                        result.imported += 1
                session.commit()
            except Exception:
                session.rollback()
                raise

    result.skipped = max(result.scanned - result.imported, 0)
    coverage = summarize_candles(candles, timeframe=timeframe)
    print(
        json.dumps(
            {
                "asset": asset,
                "timeframe": timeframe,
                "raw_path": raw_path,
                "scanned": result.scanned,
                "imported": result.imported,
                "skipped": result.skipped,
                "dry_run": bool(args.dry_run),
                "repair_gaps": bool(args.repair_gaps),
                "first_time": coverage["first_time"],
                "last_time": coverage["last_time"],
                "gap_count": coverage["gap_count"],
                "max_gap_seconds": coverage["max_gap_seconds"],
                "existing_gap_count": existing_gap_summary["gap_count"],
                "existing_gap_ranges": existing_gap_summary["gap_ranges"],
                "range": args.range_,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "database_url": _display_database_url(database_url),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def collect_daily_candles(
    *,
    storage_root: Path,
    asset: str,
    input_json: str | None = None,
    range_: str = "1y",
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[dict[str, Any]], str, str, dict[str, Any]]:
    if asset == "GC":
        candles, raw_path = collect_gc_daily_candles(
            storage_root=storage_root,
            input_json=input_json,
            range_=range_,
            start_date=start_date,
            end_date=end_date,
        )
        return candles, raw_path, "yahoo_finance_gc_f", {
            "provider_symbol": "GC=F",
            "instrument_type": "futures_continuous_proxy",
            "url": YAHOO_GC_CHART_URL,
        }
    if asset != "DXY":
        raise ValueError(f"daily candles are not available for {asset}; use GC for GC=F")
    candles, raw_path = collect_dxy_daily_candles(
        storage_root=storage_root,
        input_json=input_json,
        range_=range_,
        start_date=start_date,
        end_date=end_date,
    )
    return candles, raw_path, "yahoo_finance_dx_y_nyb", {"ticker": "DX-Y.NYB", "url": YAHOO_DXY_CHART_URL}


def collect_gc_daily_candles(
    *,
    storage_root: Path,
    input_json: str | None = None,
    range_: str = "1y",
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if input_json:
        payload_path = Path(input_json).resolve()
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        raw_path = payload_path.relative_to(storage_root).as_posix() if payload_path.is_relative_to(storage_root) else str(payload_path)
        return _parse_yahoo_daily_candles(payload), raw_path

    try:
        payload = _fetch_openbb_daily_payload(
            symbol="GC=F",
            asset_type="equity",
            start_date=start_date,
            end_date=end_date,
            range_=range_,
        )
    except Exception:
        try:
            with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
                response = client.get(YAHOO_GC_CHART_URL, params={"range": _normalize_yahoo_range(range_), "interval": "1d"})
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            local_candidates = sorted((storage_root / "raw" / "technical" / "yahoo").glob("*/GC=F-*.json"))
            if local_candidates:
                payload_path = local_candidates[-1]
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
                raw_path = payload_path.relative_to(storage_root).as_posix()
                return _parse_yahoo_daily_candles(payload), raw_path
            raise ValueError(f"unable to fetch GC daily candles and no local raw fallback found: {exc}") from exc

    today = datetime.now(UTC).date().isoformat()
    raw_path = archive_raw_payload(
        storage_root=storage_root,
        source="yahoo_finance_gc_f",
        retrieved_date=today,
        symbol="GC=F",
        payload=payload,
    )
    return _parse_dxy_daily_payload(payload), raw_path


def collect_dxy_daily_candles(
    *,
    storage_root: Path,
    input_json: str | None = None,
    range_: str = "1y",
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if input_json:
        payload_path = Path(input_json).resolve()
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        raw_path = payload_path.relative_to(storage_root).as_posix() if payload_path.is_relative_to(storage_root) else str(payload_path)
        return _parse_dxy_daily_payload(payload), raw_path

    try:
        payload = _fetch_openbb_daily_payload(
            symbol="DX-Y.NYB",
            asset_type="index",
            start_date=start_date,
            end_date=end_date,
            range_=range_,
        )
    except Exception:
        try:
            with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
                response = client.get(YAHOO_DXY_CHART_URL, params={"range": _normalize_yahoo_range(range_), "interval": "1d"})
                response.raise_for_status()
                payload = response.json()
        except Exception:
            local_candidates = sorted((storage_root / "raw" / "macro" / "openbb_yfinance").glob("*/DX-Y.NYB-*.json"))
            if local_candidates:
                payload_path = local_candidates[-1]
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
                raw_path = payload_path.relative_to(storage_root).as_posix()
                return _parse_dxy_daily_payload(payload), raw_path
            raise

    today = datetime.now(UTC).date().isoformat()
    raw_path = archive_raw_payload(
        storage_root=storage_root,
        source="yahoo_finance_dx_y_nyb",
        retrieved_date=today,
        symbol="DX-Y.NYB",
        payload=payload,
    )
    return _parse_dxy_daily_payload(payload), raw_path


def _parse_dxy_daily_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("chart"), dict):
        return _parse_yahoo_daily_candles(payload)
    return _parse_openbb_ohlcv_payload(payload)


def _fetch_openbb_daily_payload(
    *,
    symbol: str,
    asset_type: str,
    start_date: date | None = None,
    end_date: date | None = None,
    range_: str = "1y",
) -> dict[str, Any]:
    from openbb import obb

    end_day = end_date or datetime.now(UTC).date()
    start_day = start_date or _start_day_for_range(end_day, range_)
    result = obb.equity.price.historical(
        symbol=symbol,
        provider="yfinance",
        start_date=start_day.isoformat(),
        end_date=end_day.isoformat(),
        interval="1d",
    )
    df = result.to_df()
    if df is None or df.empty:
        raise ValueError(f"openbb yfinance returned empty {symbol} 1d data")
    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "source": "openbb_yfinance",
        "retrieved_date": end_day.isoformat(),
        "interval": "1d",
        "columns": list(df.columns),
        "row_count": len(df),
        "latest": _jsonify_openbb_records(df.reset_index().to_dict("records")),
    }


def _parse_yahoo_daily_candles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = (((payload.get("chart") or {}).get("result")) or [None])[0]
    if not isinstance(result, dict):
        raise ValueError("yahoo chart payload missing result")

    timestamps = result.get("timestamp") or []
    quote = ((((result.get("indicators") or {}).get("quote")) or [None])[0]) or {}
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    candles: list[dict[str, Any]] = []
    for idx, ts in enumerate(timestamps):
        try:
            open_ = opens[idx]
            high = highs[idx]
            low = lows[idx]
            close = closes[idx]
        except IndexError:
            continue
        if None in (open_, high, low, close):
            continue
        open_time = datetime.fromtimestamp(int(ts), tz=UTC)
        volume = volumes[idx] if idx < len(volumes) else None
        candles.append(
            {
                "open_time": open_time,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume) if volume is not None else None,
            }
        )
    if not candles:
        raise ValueError("yahoo chart payload produced no valid candles")
    return candles


def _parse_openbb_ohlcv_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    latest = payload.get("latest") if isinstance(payload, dict) else None
    if not isinstance(latest, list) or not latest:
        raise ValueError("openbb yfinance payload missing latest rows")
    retrieved_date = str(payload.get("retrieved_date") or "")

    candles: list[dict[str, Any]] = []
    rows = list(latest)
    fallback_day = datetime.fromisoformat(retrieved_date).date() if retrieved_date else None
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        open_ = row.get("open")
        high = row.get("high")
        low = row.get("low")
        close = row.get("close")
        ts = row.get("date") or row.get("datetime") or row.get("time")
        if None in (open_, high, low, close):
            continue
        if ts is not None:
            open_time = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if open_time.tzinfo is None:
                open_time = open_time.replace(tzinfo=UTC)
        else:
            if fallback_day is None:
                continue
            from datetime import timedelta
            open_time = datetime.combine(fallback_day - timedelta(days=(len(rows) - index - 1)), datetime.min.time(), tzinfo=UTC)
        candles.append(
            {
                "open_time": open_time,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(row["volume"]) if row.get("volume") is not None else None,
            }
        )
    if not candles:
        raise ValueError("openbb yfinance payload produced no valid candles")
    return candles




def collect_intraday_hourly_candles(
    *,
    storage_root: Path,
    asset: str,
    input_json: str | None = None,
    batches: int = 1,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if input_json:
        payload_path = Path(input_json).resolve()
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        raw_path = payload_path.relative_to(storage_root).as_posix() if payload_path.is_relative_to(storage_root) else str(payload_path)
        return _parse_intraday_payload(payload, asset=asset), raw_path

    if asset == "GC":
        try:
            return collect_gc_hourly_candles_via_openbb(
                storage_root=storage_root,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
            pass

    if batches > 1:
        payloads, raw_paths = _fetch_jin10_kline_batches(storage_root=storage_root, asset=asset, batches=batches)
        return _parse_jin10_hourly_candles_from_payloads(payloads), raw_paths[-1]

    candidates = sorted(
        (storage_root / "raw" / "macro" / "jin10_mcp").glob(f"*/kline_{asset}-*.json"),
        reverse=True,
    )
    if not candidates:
        raise ValueError(f"no local jin10_mcp kline payloads found for {asset}")

    best_path = candidates[0]
    payload = json.loads(best_path.read_text(encoding="utf-8"))
    return _parse_jin10_hourly_candles(payload), best_path.relative_to(storage_root).as_posix()


def collect_intraday_minute_candles(
    *, storage_root: Path, asset: str, input_json: str | None = None, batches: int = 1
) -> tuple[list[dict[str, Any]], str]:
    if input_json:
        payload_path = Path(input_json).resolve()
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        raw_path = payload_path.relative_to(storage_root).as_posix() if payload_path.is_relative_to(storage_root) else str(payload_path)
        return _parse_jin10_minute_candles(payload), raw_path

    payloads, raw_paths = _fetch_jin10_kline_batches(storage_root=storage_root, asset=asset, batches=max(batches, 1))
    return _parse_jin10_minute_candles_from_payloads(payloads), raw_paths[-1]


def collect_gc_hourly_candles_via_openbb(
    *,
    storage_root: Path,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[dict[str, Any]], str]:
    from openbb import obb

    end_day = end_date or datetime.now(UTC).date()
    start_day = start_date or (end_day - timedelta(days=92))
    end_date = end_day.isoformat()
    start_date = start_day.isoformat()
    result = obb.equity.price.historical(
        symbol="GC=F",
        provider="yfinance",
        start_date=start_date,
        end_date=end_date,
        interval="60m",
    )
    df = result.to_df()
    if df is None or df.empty:
        raise ValueError("openbb yfinance returned empty GC=F 60m data")
    payload = {
        "symbol": "GC=F",
        "asset_type": "equity",
        "source": "openbb_yfinance",
        "retrieved_date": end_date,
        "interval": "60m",
        "columns": list(df.columns),
        "row_count": len(df),
        "latest": _jsonify_openbb_records(df.reset_index().to_dict("records")),
    }
    raw_path = archive_raw_payload(
        storage_root=storage_root,
        source="openbb_yfinance",
        retrieved_date=end_date,
        symbol="GC-F-60m",
        payload=payload,
    )
    return _parse_openbb_intraday_payload(payload), raw_path


def _jsonify_openbb_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in records:
        clean: dict[str, Any] = {}
        for key, value in row.items():
            if hasattr(value, "isoformat"):
                clean[key] = value.isoformat()
            else:
                clean[key] = value
        normalized.append(clean)
    return normalized


def _parse_intraday_payload(payload: dict[str, Any], *, asset: str) -> list[dict[str, Any]]:
    if payload.get("source") == "openbb_yfinance":
        return _parse_openbb_intraday_payload(payload)
    return _parse_jin10_hourly_candles(payload)


def _parse_openbb_intraday_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    latest = payload.get("latest") if isinstance(payload, dict) else None
    if not isinstance(latest, list) or not latest:
        raise ValueError("openbb intraday payload missing latest rows")
    candles: list[dict[str, Any]] = []
    for row in latest:
        if not isinstance(row, dict):
            continue
        ts = row.get("date")
        if not ts:
            continue
        open_ = row.get("open")
        high = row.get("high")
        low = row.get("low")
        close = row.get("close")
        if None in (open_, high, low, close):
            continue
        candles.append(
            {
                "open_time": datetime.fromisoformat(str(ts).replace("Z", "+00:00")),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(row["volume"]) if row.get("volume") is not None else None,
            }
        )
    if not candles:
        raise ValueError("openbb intraday payload produced no valid candles")
    return candles


def _fetch_jin10_kline_batches(*, storage_root: Path, asset: str, batches: int) -> tuple[list[dict[str, Any]], list[str]]:
    payloads: list[dict[str, Any]] = []
    raw_paths: list[str] = []
    next_ts: int | None = None
    retrieved_date = datetime.now(UTC).date().isoformat()
    with Jin10MCPClient() as client:
        for _ in range(batches):
            payload = client.get_kline(asset, time_stamp=next_ts, count=100)
            payloads.append(payload)
            raw_path = archive_raw_payload(
                storage_root=storage_root,
                source="jin10_mcp",
                retrieved_date=retrieved_date,
                symbol=f"kline_{asset}",
                payload=payload,
            )
            raw_paths.append(str(raw_path))
            rows = _extract_jin10_kline_rows(payload)
            if not rows:
                break
            oldest_ts = min(int(row.get("time", 0)) for row in rows if row.get("time") is not None)
            if oldest_ts <= 0:
                break
            next_ts = oldest_ts - 60
    return payloads, raw_paths


def _extract_jin10_kline_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    klines = data.get("klines") or data.get("list") or data.get("data") or []
    return [row for row in klines if isinstance(row, dict)] if isinstance(klines, list) else []


def _parse_jin10_hourly_candles_from_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_payload = {"data": {"klines": _merge_jin10_kline_rows(payloads)}}
    return _parse_jin10_hourly_candles(merged_payload)


def _parse_jin10_minute_candles_from_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_payload = {"data": {"klines": _merge_jin10_kline_rows(payloads)}}
    return _parse_jin10_minute_candles(merged_payload)


def _merge_jin10_kline_rows(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_rows: list[dict[str, Any]] = []
    seen_times: set[int] = set()
    for payload in payloads:
        for row in _extract_jin10_kline_rows(payload):
            ts = row.get("time")
            if ts is None:
                continue
            ts_int = int(ts)
            if ts_int in seen_times:
                continue
            seen_times.add(ts_int)
            merged_rows.append(row)
    return sorted(merged_rows, key=lambda row: int(row.get("time", 0)))


def _parse_jin10_minute_candles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("jin10 kline payload missing data")
    klines = data.get("klines") or data.get("list") or data.get("data") or []
    if not isinstance(klines, list) or not klines:
        raise ValueError("jin10 kline payload missing klines")

    minute_rows: list[dict[str, Any]] = []
    seen_times: set[int] = set()
    for candle in klines:
        if not isinstance(candle, dict):
            continue
        ts = candle.get("time")
        open_ = candle.get("open")
        high = candle.get("high")
        low = candle.get("low")
        close = candle.get("close")
        if None in (ts, open_, high, low, close):
            continue
        ts_int = int(ts)
        if ts_int in seen_times:
            continue
        seen_times.add(ts_int)
        minute_rows.append(
            {
                "open_time": datetime.fromtimestamp(ts_int, tz=UTC).replace(second=0, microsecond=0),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(candle["volume"]) if candle.get("volume") is not None else None,
            }
        )
    minute_rows.sort(key=lambda row: row["open_time"])
    if not minute_rows:
        raise ValueError("jin10 kline payload produced no valid minute candles")
    return minute_rows


def _parse_jin10_hourly_candles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    buckets: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for candle in _parse_jin10_minute_candles(payload):
        dt = candle["open_time"]
        hour_open = dt.replace(minute=0)
        buckets[hour_open].append(candle)

    hourly: list[dict[str, Any]] = []
    for hour_open in sorted(buckets):
        rows = sorted(buckets[hour_open], key=lambda row: int(row.get("time", 0)))
        first = rows[0]
        last = rows[-1]
        highs = [float(row["high"]) for row in rows if row.get("high") is not None]
        lows = [float(row["low"]) for row in rows if row.get("low") is not None]
        volumes = [float(row["volume"]) for row in rows if row.get("volume") is not None]
        hourly.append(
            {
                "open_time": hour_open,
                "open": float(first["open"]),
                "high": max(highs),
                "low": min(lows),
                "close": float(last["close"]),
                "volume": sum(volumes) if volumes else None,
            }
        )
    if not hourly:
        raise ValueError("jin10 kline payload produced no valid hourly candles")
    return hourly


def summarize_candles(candles: list[dict[str, Any]], *, timeframe: str) -> dict[str, Any]:
    sorted_candles = sorted(
        (
            {**candle, "open_time": _utc_datetime(candle["open_time"])}
            for candle in candles
            if isinstance(candle.get("open_time"), datetime)
        ),
        key=lambda candle: candle["open_time"],
    )
    if not sorted_candles:
        return {"first_time": None, "last_time": None, "gap_count": 0, "max_gap_seconds": None}

    expected_seconds = {"1m": 60, "1h": 3600, "1d": 86400}.get(timeframe.lower(), 60)
    threshold = expected_seconds * (3.5 if timeframe.lower() == "1d" else 1.5)
    gap_count = 0
    max_gap_seconds: int | None = None
    gap_ranges: list[dict[str, Any]] = []
    for current, nxt in zip(sorted_candles, sorted_candles[1:]):
        gap_seconds = int((nxt["open_time"] - current["open_time"]).total_seconds())
        if gap_seconds > threshold:
            gap_count += 1
            max_gap_seconds = max(max_gap_seconds or gap_seconds, gap_seconds)
            gap_ranges.append(
                {
                    "from": current["open_time"].isoformat(),
                    "to": nxt["open_time"].isoformat(),
                    "gap_seconds": gap_seconds,
                }
            )

    return {
        "first_time": sorted_candles[0]["open_time"].isoformat(),
        "last_time": sorted_candles[-1]["open_time"].isoformat(),
        "gap_count": gap_count,
        "max_gap_seconds": max_gap_seconds,
        "gap_ranges": gap_ranges[:10],
    }


def _utc_datetime(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _target_minutes_to_batches(target_minutes: int) -> int:
    return max(1, ceil(max(int(target_minutes), 1) / 100))


def _parse_optional_date(value: str, *, name: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise SystemExit(f"{name} must use YYYY-MM-DD format") from exc


def _normalize_yahoo_range(value: str) -> str:
    normalized = str(value or "1y").strip().lower()
    allowed = {"5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
    if normalized not in allowed:
        raise SystemExit(f"unsupported --range {value!r}; expected one of {sorted(allowed)}")
    return normalized


def _start_day_for_range(end_day: date, range_: str) -> date:
    normalized = _normalize_yahoo_range(range_)
    if normalized.endswith("d") and normalized[:-1].isdigit():
        return end_day - timedelta(days=int(normalized[:-1]))
    if normalized.endswith("mo") and normalized[:-2].isdigit():
        return end_day - timedelta(days=int(normalized[:-2]) * 31)
    if normalized.endswith("y") and normalized[:-1].isdigit():
        return end_day - timedelta(days=int(normalized[:-1]) * 365)
    if normalized == "ytd":
        return date(end_day.year, 1, 1)
    if normalized == "max":
        return end_day - timedelta(days=3650)
    return end_day - timedelta(days=365)


def inspect_existing_candle_gaps(*, database_url: str, asset: str, timeframe: str) -> dict[str, Any]:
    if _sqlite_database_missing(database_url):
        return {"first_time": None, "last_time": None, "gap_count": 0, "max_gap_seconds": None, "gap_ranges": []}
    session_factory = _session_factory(database_url)
    try:
        with session_factory() as session:
            rows = list(
                session.scalars(
                    select(MarketCandle)
                    .where(MarketCandle.asset == asset, MarketCandle.timeframe == timeframe)
                    .order_by(MarketCandle.open_time.asc(), MarketCandle.id.asc())
                ).all()
            )
    except Exception:
        return {"first_time": None, "last_time": None, "gap_count": 0, "max_gap_seconds": None, "gap_ranges": []}
    candles = [{"open_time": row.open_time} for row in rows]
    return summarize_candles(candles, timeframe=timeframe)


def _sqlite_database_missing(database_url: str) -> bool:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return False
    return not Path(url.database).exists()


def _session_factory(database_url: str):
    if database_url == DATABASE_URL:
        return SessionLocal
    engine = create_engine(database_url, echo=False)
    return sessionmaker(bind=engine)


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return
    db_path = Path(url.database)
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)


def _display_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.password:
        return str(url.set(password="***"))
    return str(url)


def _candle_count(session) -> int:
    return session.query(MarketCandle).count()


if __name__ == "__main__":
    main()
