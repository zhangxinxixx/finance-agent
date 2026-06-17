from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine
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
    parser.add_argument("--asset", default="XAUUSD", help="Supported: XAUUSD, DXY")
    parser.add_argument("--timeframe", default="1d", help="Supported now: 1d, 1h, 1m")
    parser.add_argument("--input-json", default="", help="Optional local Yahoo chart payload JSON path for offline import")
    parser.add_argument("--jin10-batches", type=int, default=1, help="For Jin10 intraday import, how many 100-minute batches to fetch sequentially.")
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
    if asset not in {"XAUUSD", "DXY"}:
        raise SystemExit(f"unsupported --asset {asset!r}; currently only XAUUSD and DXY are implemented")
    if timeframe not in {"1d", "1h", "1m"}:
        raise SystemExit(f"unsupported --timeframe {timeframe!r}; currently only 1d, 1h and 1m are implemented")
    if asset == "DXY" and timeframe != "1d":
        raise SystemExit("DXY is only supported as daily candles; do not backfill fabricated intraday DXY data")

    storage_root = Path(args.storage_root).resolve()
    database_url = args.database_url or DATABASE_URL
    session_factory = _session_factory(database_url)
    _ensure_sqlite_parent(database_url)

    if timeframe == "1d":
        candles, raw_path, source, source_ref = collect_daily_candles(
            storage_root=storage_root,
            asset=asset,
            input_json=args.input_json or None,
        )
    elif timeframe == "1h":
        candles, raw_path = collect_intraday_hourly_candles(
            storage_root=storage_root,
            asset=asset,
            input_json=args.input_json or None,
            batches=max(args.jin10_batches, 1),
        )
        source = "openbb_yfinance_60m" if asset == "XAUUSD" else "jin10_mcp_kline"
        source_ref = {"symbol": asset, "source": "openbb_yfinance" if asset == "XAUUSD" else "jin10_mcp"}
    else:
        candles, raw_path = collect_intraday_minute_candles(
            storage_root=storage_root,
            asset=asset,
            input_json=args.input_json or None,
            batches=max(args.jin10_batches, 1),
        )
        source = "jin10_mcp_kline_1m"
        source_ref = {"symbol": asset, "source": "jin10_mcp", "provider_timeframe": "1m"}

    result = ImportResult()
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
    print(
        json.dumps(
            {
                "asset": asset,
                "timeframe": timeframe,
                "raw_path": raw_path,
                "scanned": result.scanned,
                "imported": result.imported,
                "skipped": result.skipped,
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
) -> tuple[list[dict[str, Any]], str, str, dict[str, Any]]:
    if asset == "XAUUSD":
        candles, raw_path = collect_xauusd_daily_candles(storage_root=storage_root, input_json=input_json)
        return candles, raw_path, "yahoo_finance_gc_f", {"ticker": "GC=F", "url": YAHOO_GC_CHART_URL}
    candles, raw_path = collect_dxy_daily_candles(storage_root=storage_root, input_json=input_json)
    return candles, raw_path, "yahoo_finance_dx_y_nyb", {"ticker": "DX-Y.NYB", "url": YAHOO_DXY_CHART_URL}


def collect_xauusd_daily_candles(*, storage_root: Path, input_json: str | None = None) -> tuple[list[dict[str, Any]], str]:
    if input_json:
        payload_path = Path(input_json).resolve()
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        raw_path = payload_path.relative_to(storage_root).as_posix() if payload_path.is_relative_to(storage_root) else str(payload_path)
        return _parse_yahoo_daily_candles(payload), raw_path

    try:
        payload = _fetch_openbb_daily_payload(symbol="GC=F", asset_type="equity")
    except Exception:
        local_candidates = sorted((storage_root / "raw" / "technical" / "yahoo").glob("*/GC=F-*.json"))
        if local_candidates:
            payload_path = local_candidates[-1]
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            raw_path = payload_path.relative_to(storage_root).as_posix()
            return _parse_yahoo_daily_candles(payload), raw_path
        try:
            with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
                response = client.get(YAHOO_GC_CHART_URL, params={"range": "3mo", "interval": "1d"})
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise ValueError(f"unable to fetch XAUUSD daily candles and no local raw fallback found: {exc}") from exc

    today = datetime.now(UTC).date().isoformat()
    raw_path = archive_raw_payload(
        storage_root=storage_root,
        source="yahoo_finance_gc_f",
        retrieved_date=today,
        symbol="GC=F",
        payload=payload,
    )
    return _parse_dxy_daily_payload(payload), raw_path


def collect_dxy_daily_candles(*, storage_root: Path, input_json: str | None = None) -> tuple[list[dict[str, Any]], str]:
    if input_json:
        payload_path = Path(input_json).resolve()
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        raw_path = payload_path.relative_to(storage_root).as_posix() if payload_path.is_relative_to(storage_root) else str(payload_path)
        return _parse_dxy_daily_payload(payload), raw_path

    try:
        payload = _fetch_openbb_daily_payload(symbol="DX-Y.NYB", asset_type="index")
    except Exception:
        local_candidates = sorted((storage_root / "raw" / "macro" / "openbb_yfinance").glob("*/DX-Y.NYB-*.json"))
        if local_candidates:
            payload_path = local_candidates[-1]
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            raw_path = payload_path.relative_to(storage_root).as_posix()
            return _parse_dxy_daily_payload(payload), raw_path
        with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
            response = client.get(YAHOO_DXY_CHART_URL, params={"range": "3mo", "interval": "1d"})
            response.raise_for_status()
            payload = response.json()

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


def _fetch_openbb_daily_payload(*, symbol: str, asset_type: str) -> dict[str, Any]:
    from openbb import obb

    end_day = datetime.now(UTC).date()
    start_day = end_day.replace(month=max(end_day.month - 3, 1)) if end_day.month > 3 else end_day
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
        "latest": _jsonify_openbb_records(df.tail(90).reset_index().to_dict("records")),
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
    *, storage_root: Path, asset: str, input_json: str | None = None, batches: int = 1
) -> tuple[list[dict[str, Any]], str]:
    if input_json:
        payload_path = Path(input_json).resolve()
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        raw_path = payload_path.relative_to(storage_root).as_posix() if payload_path.is_relative_to(storage_root) else str(payload_path)
        return _parse_intraday_payload(payload, asset=asset), raw_path

    if asset == "XAUUSD":
        try:
            return collect_xauusd_hourly_candles_via_openbb(storage_root=storage_root)
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


def collect_xauusd_hourly_candles_via_openbb(*, storage_root: Path) -> tuple[list[dict[str, Any]], str]:
    from openbb import obb

    from datetime import timedelta

    end_day = datetime.now(UTC).date()
    start_day = end_day - timedelta(days=92)
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
