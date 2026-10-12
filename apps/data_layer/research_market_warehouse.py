"""Materialize TradingView research inputs into typed DWD and read them back.

The caller owns the outer transaction.  This module performs no DDL, commit,
collector call, or artifact read; the returned value is rebuilt only from DWD.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from uuid import uuid4

from sqlalchemy import inspect, select
from apps.parsers.market.tradingview import ALL_INSTRUMENTS
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep
from database.models.warehouse_research_market import (
    RESEARCH_MARKET_TABLES,
    ResearchMarketBar,
    ResearchMarketBatch,
    ResearchMarketBatchSourceRef,
    ResearchMarketChartSeries,
    ResearchMarketLimitation,
    ResearchMarketScannerQuote,
    ResearchMarketScannerSourceRef,
    ResearchMarketSeriesSourceRef,
)

KINDS = frozenset({"cross_asset", "adaptive", "execution"})
COLLECTION_KEYS = ("chart_series", "execution_chart_series", "series")
MAX_QUOTES = 64
MAX_SERIES = 64
MAX_BARS = 256
MAX_REFS = 256


class ResearchMarketWarehouseError(ValueError):
    """Fixed safe error code for validation and transactional failures."""


def _fail(code: str = "RESEARCH_MARKET_MAPPING_INVALID") -> None:
    raise ResearchMarketWarehouseError(code)


def _string(value, *, required=False, length=None):
    if value is None:
        if required:
            _fail()
        return None
    if not isinstance(value, str) or "\x00" in value or (required and not value.strip()):
        _fail()
    if length is not None and len(value) > length:
        _fail()
    return value


def _timestamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            _fail("RESEARCH_MARKET_TIME_INVALID")
    if not isinstance(value, datetime) or value.tzinfo is None:
        _fail("RESEARCH_MARKET_TIME_INVALID")
    return value.astimezone(UTC)


def _number(value, *, required=False):
    if value is None:
        if required:
            _fail("RESEARCH_MARKET_NUMBER_INVALID")
        return None
    if isinstance(value, bool):
        _fail("RESEARCH_MARKET_NUMBER_INVALID")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _fail("RESEARCH_MARKET_NUMBER_INVALID")
    if not result.is_finite() or abs(result) >= Decimal("1e26"):
        _fail("RESEARCH_MARKET_NUMBER_INVALID")
    return result


def _integer(value, *, required=False, maximum=2_147_483_647):
    if value is None:
        if required:
            _fail()
        return None
    if type(value) is not int or value < 0 or value > maximum:
        _fail()
    return value


def _boolean(value):
    if value is None or type(value) is bool:
        return value
    _fail("RESEARCH_MARKET_BOOLEAN_INVALID")


def _items(value, *, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        _fail()
    return value


def _artifact_path(value, storage_root):
    value = _string(value)
    if value is None:
        return None
    root = Path(storage_root).resolve()
    path = Path(value)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(root)
        except ValueError:
            _fail("RESEARCH_MARKET_PATH_INVALID")
    pure = PurePosixPath(path.as_posix())
    if not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        _fail("RESEARCH_MARKET_PATH_INVALID")
    return pure.as_posix()


def _source_ref(ref, storage_root):
    if not isinstance(ref, dict):
        _fail()
    source = _string(ref.get("source", ref.get("source_key")), length=128)
    source_url = _string(ref.get("source_url", ref.get("url")))
    source_name = _string(ref.get("source_name"), length=255)
    identities = (source, source_url, source_name)
    if any(value and ("jin10" in value.casefold() or "金十" in value) for value in identities):
        _fail("RESEARCH_MARKET_SOURCE_REJECTED")
    return {
        "source": source,
        "source_url": source_url,
        "ticker": _string(ref.get("ticker"), length=128),
        "symbol": _string(ref.get("symbol"), length=128),
        "raw_path": _artifact_path(ref.get("raw_path"), storage_root),
        "parsed_path": _artifact_path(ref.get("parsed_path"), storage_root),
        "retrieved_at": _timestamp(ref.get("retrieved_at", ref.get("fetched_at"))),
        "published_at": _timestamp(ref.get("published_at")),
        "source_tier": _string(ref.get("source_tier"), length=64),
        "evidence_scope": _string(ref.get("evidence_scope"), length=128),
        "reference": _string(ref.get("reference"), length=255),
        "status": _string(ref.get("status"), length=64),
        "source_type": _string(ref.get("source_type"), length=64),
        "source_name": source_name,
        "content_scope": _string(ref.get("content_scope"), length=128),
    }


def _refs(value, storage_root):
    return [_source_ref(item, storage_root) for item in _items(value, maximum=MAX_REFS)]


def _quote(row, ordinal, storage_root):
    if not isinstance(row, dict):
        _fail()
    status = _string(row.get("status"), required=True, length=32)
    if status not in {"available", "missing", "invalid"}:
        _fail()
    ticker = _string(row.get("ticker"), required=True, length=128)
    identity = ALL_INSTRUMENTS.get(ticker)
    symbol = _string(row.get("symbol"), required=True, length=128)
    instrument_type = _string(row.get("instrument_type"), required=True, length=64)
    unit = _string(row.get("unit"), required=True, length=64)
    if identity is None or (symbol, instrument_type, unit) != identity[:3]:
        _fail("RESEARCH_MARKET_IDENTITY_INVALID")
    retrieved_at = _timestamp(row.get("retrieved_at"))
    refs = _refs(row.get("source_refs", []), storage_root)
    value = _number(row.get("value"))
    continuous_contract = _boolean(row.get("continuous_contract"))
    expected_continuous = instrument_type == "futures" and ticker.endswith("1!")
    if continuous_contract is not None and continuous_contract != expected_continuous:
        _fail("RESEARCH_MARKET_IDENTITY_INVALID")
    if status == "available":
        if (
            value is None
            or value <= 0
            or retrieved_at is None
            or not any(
                ref["source"] == "tradingview_cross_asset" and ref["retrieved_at"] == retrieved_at and ref["raw_path"]
                for ref in refs
            )
        ):
            _fail("RESEARCH_MARKET_SOURCE_INVALID")
    elif value is not None:
        _fail("RESEARCH_MARKET_QUALITY_INVALID")
    result = {
        "ordinal": ordinal,
        "ticker": ticker,
        "symbol": symbol,
        "instrument_type": instrument_type,
        "unit": unit,
        "retrieved_at": retrieved_at,
        "status": status,
        "reason": _string(row.get("reason"), length=128),
        "value": value,
        "quote_time": _timestamp(row.get("quote_time")),
        "quote_time_verified": _boolean(row.get("quote_time_verified")),
        "value_kind": _string(row.get("value_kind"), required=True, length=64),
        "delay_seconds": _integer(row.get("delay_seconds"), maximum=86_400),
        "provider_bar_time": _timestamp(row.get("provider_bar_time")),
        "minute_bar_time": _timestamp(row.get("minute_bar_time")),
        "continuous_contract": continuous_contract,
        "scanner_close": _number(row.get("scanner_close")),
        "update_mode": _string(row.get("update_mode"), length=64),
        "current_session": _string(row.get("current_session"), length=64),
        "description": _string(row.get("description")),
        "provider_change_pct": _number(row.get("provider_change_pct")),
        "provider_change_abs": _number(row.get("provider_change_abs")),
        "change_basis": _string(row.get("change_basis"), length=128),
    }
    return result, refs


def _bar(row, ordinal):
    if not isinstance(row, dict):
        _fail()
    open_ = _number(row.get("open"), required=True)
    high = _number(row.get("high"), required=True)
    low = _number(row.get("low"), required=True)
    close = _number(row.get("close"), required=True)
    volume = _number(row.get("volume"))
    if high < max(open_, close) or low > min(open_, close) or high < low or (volume is not None and volume < 0):
        _fail("RESEARCH_MARKET_BAR_INVALID")
    return {
        "ordinal": ordinal,
        "bar_time": _timestamp(row.get("time")),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "front_contract": _string(row.get("front_contract"), length=64),
    }


def _series(row, collection_key, ordinal, storage_root):
    if not isinstance(row, dict):
        _fail()
    status = _string(row.get("status"), required=True, length=32)
    if status not in {"available", "unavailable"}:
        _fail()
    ticker = _string(row.get("ticker"), required=True, length=128)
    identity = ALL_INSTRUMENTS.get(ticker)
    if identity is None:
        _fail("RESEARCH_MARKET_IDENTITY_INVALID")
    resolution = _integer(row.get("resolution_seconds"), required=True, maximum=86_400)
    if resolution not in {60, 900, 3_600, 14_400}:
        _fail()
    retrieved_at = _timestamp(row.get("retrieved_at"))
    refs = _refs(row.get("source_refs", []), storage_root)
    raw_bars = _items(row.get("bars", []), maximum=MAX_BARS)
    metadata = row.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        _fail()
    metadata = metadata or {}
    continuous_contract = _boolean(row.get("continuous_contract"))
    expected_continuous = identity[1] == "futures" and ticker.endswith("1!")
    if continuous_contract is not None and continuous_contract != expected_continuous:
        _fail("RESEARCH_MARKET_IDENTITY_INVALID")
    if status == "available":
        if (
            retrieved_at is None
            or not raw_bars
            or not any(
                ref["source"] == "tradingview_chart"
                and ref["ticker"] == ticker
                and ref["raw_path"]
                and ref["retrieved_at"] == retrieved_at
                for ref in refs
            )
        ):
            _fail("RESEARCH_MARKET_SOURCE_INVALID")
        if _boolean(metadata.get("series_completed")) is not True:
            _fail("RESEARCH_MARKET_QUALITY_INVALID")
        if expected_continuous and not _string(row.get("front_contract"), required=True, length=64):
            _fail("RESEARCH_MARKET_IDENTITY_INVALID")
        _expected_symbol, expected_type, expected_unit, _description = identity
        expected_currency = expected_unit.split("/", 1)[0] if "/" in expected_unit else None
        if (
            metadata.get("exchange") != ticker.split(":", 1)[0]
            or metadata.get("instrument_type") != expected_type
            or (expected_currency and metadata.get("currency") != expected_currency)
        ):
            _fail("RESEARCH_MARKET_IDENTITY_INVALID")
    elif raw_bars:
        _fail("RESEARCH_MARKET_QUALITY_INVALID")
    result = {
        "collection_key": collection_key,
        "ordinal": ordinal,
        "ticker": ticker,
        "status": status,
        "resolution_seconds": resolution,
        "delay_seconds": _integer(row.get("delay_seconds"), maximum=86_400),
        "retrieved_at": retrieved_at,
        "front_contract": _string(row.get("front_contract"), length=64),
        "continuous_contract": continuous_contract,
        "error": _string(row.get("error"), length=128),
        "exchange": _string(metadata.get("exchange"), length=64),
        "instrument_type": _string(metadata.get("instrument_type"), length=64),
        "currency": _string(metadata.get("currency"), length=32),
        "update_mode": _string(metadata.get("update_mode"), length=64),
        "provider_delay_seconds": _integer(metadata.get("provider_delay_seconds"), maximum=86_400),
        "series_completed": _boolean(metadata.get("series_completed")),
        "provider_timezone": _string(metadata.get("timezone"), length=128),
        "provider_session": _string(metadata.get("session"), length=128),
        "description": _string(metadata.get("description")),
        "has_metadata": "metadata" in row,
    }
    bars = [_bar(bar, i) for i, bar in enumerate(raw_bars)]
    if len({bar["bar_time"] for bar in bars}) != len(bars):
        _fail("RESEARCH_MARKET_BAR_CONFLICT")
    return result, bars, refs


def _prepare(observed, *, run_id, storage_root, kind):
    if not isinstance(observed, dict):
        _fail()
    run_id = _string(run_id, required=True, length=255)
    if kind not in KINDS:
        _fail("RESEARCH_MARKET_KIND_INVALID")
    if storage_root is None:
        _fail("RESEARCH_MARKET_STORAGE_ROOT_REQUIRED")
    header = {
        "run_id": run_id,
        "kind": kind,
        "schema_version": _string(observed.get("schema_version"), length=128),
        "retrieved_at": _timestamp(observed.get("retrieved_at")),
        "parsed_path": _artifact_path(observed.get("parsed_path"), storage_root),
        "chart_parsed_path": _artifact_path(observed.get("chart_parsed_path"), storage_root),
        "scanner_error": _string(observed.get("error"), length=128),
        "has_schema_version": "schema_version" in observed,
        "has_retrieved_at": "retrieved_at" in observed,
        "has_parsed_path": "parsed_path" in observed,
        "has_chart_parsed_path": "chart_parsed_path" in observed,
        "has_scanner_error": "error" in observed,
        "has_observations": "observations" in observed,
        "has_chart_series": "chart_series" in observed,
        "has_execution_chart_series": "execution_chart_series" in observed,
        "has_series": "series" in observed,
        "has_source_refs": "source_refs" in observed,
        "has_limitations": "limitations" in observed,
    }
    quotes = [
        _quote(row, i, storage_root)
        for i, row in enumerate(_items(observed.get("observations", []), maximum=MAX_QUOTES))
    ]
    series = []
    for key in COLLECTION_KEYS:
        rows = _items(observed.get(key, []), maximum=MAX_SERIES)
        series.extend(_series(row, key, i, storage_root) for i, row in enumerate(rows))
    refs = _refs(observed.get("source_refs", []), storage_root)
    limitations = [_string(item, required=True) for item in _items(observed.get("limitations", []), maximum=MAX_REFS)]
    # The immutable content version is independent of its producer run and
    # consumer lane; those remain separate components of the natural key.
    content_header = {key: value for key, value in header.items() if key not in {"run_id", "kind"}}
    canonical = {
        "header": content_header,
        "quotes": quotes,
        "series": series,
        "source_refs": refs,
        "limitations": limitations,
    }
    content_sha256 = sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=_canonical, allow_nan=False).encode()
    ).hexdigest()
    return header, quotes, series, refs, limitations, content_sha256


def _canonical(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def _ensure_schema(session):
    names = {table.name for table in RESEARCH_MARKET_TABLES} | {"task_runs", "task_steps"}
    inspector = inspect(session.connection())
    if any(not inspector.has_table(name) for name in names):
        _fail("RESEARCH_MARKET_SCHEMA_MISSING")


def _insert_batch(session, values):
    dialect = session.connection().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        insert = None
    if insert is not None:
        statement = (
            insert(ResearchMarketBatch)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["run_id", "kind", "content_sha256"])
            .returning(ResearchMarketBatch.id)
        )
        batch_id = session.execute(statement).scalar_one_or_none()
        if batch_id is not None:
            return batch_id, True
    existing = session.execute(
        select(ResearchMarketBatch.id).where(
            ResearchMarketBatch.run_id == values["run_id"],
            ResearchMarketBatch.kind == values["kind"],
            ResearchMarketBatch.content_sha256 == values["content_sha256"],
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    batch = ResearchMarketBatch(**values)
    session.add(batch)
    session.flush([batch])
    return batch.id, True


def materialize_research_market(session, observed, *, run_id, storage_root, kind):
    """Write one immutable typed version and return a DWD-only reconstruction."""

    if session is None:
        _fail("RESEARCH_MARKET_SESSION_REQUIRED")
    prepared = _prepare(observed, run_id=run_id, storage_root=storage_root, kind=kind)
    header, quotes, series, refs, limitations, content_sha256 = prepared
    _ensure_schema(session)
    try:
        connection = session.connection()
        if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
        with session.begin_nested():
            now, audit_id, step_id = datetime.now(UTC), uuid4(), uuid4()
            audit = TaskRun(
                id=audit_id,
                name="warehouse:research-market",
                task_type="warehouse_load",
                status=TaskStatus.running,
                current_stage="research_market_materialize",
                started_at=now,
            )
            step = TaskStep(
                id=step_id,
                task_run_id=audit_id,
                name="typed_research_market",
                stage="warehouse_load",
                task_kind="warehouse_load",
                status=StepStatus.running,
                started_at=now,
                input_hash=content_sha256,
            )
            session.add(audit)
            session.flush([audit])
            session.add(step)
            session.flush([step])
            batch_id, inserted = _insert_batch(
                session,
                {
                    **header,
                    "content_sha256": content_sha256,
                    "audit_task_run_id": str(audit_id),
                    "audit_task_step_id": str(step_id),
                },
            )
            if inserted:
                for quote_values, quote_refs in quotes:
                    quote = ResearchMarketScannerQuote(batch_id=batch_id, **quote_values)
                    session.add(quote)
                    session.flush([quote])
                    for ordinal, ref in enumerate(quote_refs):
                        session.add(ResearchMarketScannerSourceRef(quote_id=quote.id, ordinal=ordinal, **ref))
                for series_values, bars, series_refs in series:
                    item = ResearchMarketChartSeries(batch_id=batch_id, **series_values)
                    session.add(item)
                    session.flush([item])
                    for bar in bars:
                        session.add(ResearchMarketBar(series_id=item.id, **bar))
                    for ordinal, ref in enumerate(series_refs):
                        session.add(ResearchMarketSeriesSourceRef(series_id=item.id, ordinal=ordinal, **ref))
                for ordinal, ref in enumerate(refs):
                    session.add(ResearchMarketBatchSourceRef(batch_id=batch_id, ordinal=ordinal, **ref))
                for ordinal, limitation in enumerate(limitations):
                    session.add(ResearchMarketLimitation(batch_id=batch_id, ordinal=ordinal, limitation=limitation))
            ended = datetime.now(UTC)
            audit.status = TaskStatus.success
            audit.progress = 1.0
            audit.ended_at = ended
            audit.final_result_id = f"dwh_research_market_batch:{batch_id}"
            step.status = StepStatus.success
            step.finished_at = ended
            step.output_ref = audit.final_result_id
            session.flush()
        result = read_research_market(session, batch_id=batch_id)
        session.info["research_market_batch_id"] = batch_id
        return result
    except ResearchMarketWarehouseError:
        raise
    except Exception:
        _fail("RESEARCH_MARKET_TRANSACTION_FAILED")


def _iso(value):
    return value.astimezone(UTC).isoformat() if value is not None else None


def _float(value):
    return float(value) if value is not None else None


def _ref_dict(row):
    result = {}
    for key in (
        "source",
        "source_url",
        "ticker",
        "symbol",
        "raw_path",
        "parsed_path",
        "retrieved_at",
        "published_at",
        "source_tier",
        "evidence_scope",
        "reference",
        "status",
        "source_type",
        "source_name",
        "content_scope",
    ):
        value = getattr(row, key)
        if value is not None:
            result[key] = _iso(value) if key in {"retrieved_at", "published_at"} else value
    return result


def read_research_market(session, *, batch_id=None, run_id=None, kind=None, content_sha256=None):
    """Read one immutable version, choosing the latest inserted id when needed."""

    if session is None:
        _fail("RESEARCH_MARKET_SESSION_REQUIRED")
    _ensure_schema(session)
    if batch_id is None:
        run_id = _string(run_id, required=True, length=255)
        if kind not in KINDS:
            _fail("RESEARCH_MARKET_KIND_INVALID")
        query = select(ResearchMarketBatch.id).where(
            ResearchMarketBatch.run_id == run_id, ResearchMarketBatch.kind == kind
        )
        if content_sha256 is not None:
            query = query.where(ResearchMarketBatch.content_sha256 == _string(content_sha256, required=True, length=64))
        batch_id = session.execute(query.order_by(ResearchMarketBatch.id.desc()).limit(1)).scalar_one_or_none()
    batch = session.get(ResearchMarketBatch, batch_id) if batch_id is not None else None
    if batch is None:
        _fail("RESEARCH_MARKET_NOT_FOUND")
    result = {}
    if batch.has_schema_version:
        result["schema_version"] = batch.schema_version
    if batch.has_retrieved_at:
        result["retrieved_at"] = _iso(batch.retrieved_at)
    if batch.has_parsed_path:
        result["parsed_path"] = batch.parsed_path
    if batch.has_chart_parsed_path:
        result["chart_parsed_path"] = batch.chart_parsed_path
    if batch.has_scanner_error:
        result["error"] = batch.scanner_error
    if batch.has_observations:
        result["observations"] = []
        quotes = session.scalars(
            select(ResearchMarketScannerQuote)
            .where(ResearchMarketScannerQuote.batch_id == batch.id)
            .order_by(ResearchMarketScannerQuote.ordinal)
        ).all()
        for quote in quotes:
            row = {
                "ticker": quote.ticker,
                "symbol": quote.symbol,
                "instrument_type": quote.instrument_type,
                "unit": quote.unit,
                "retrieved_at": _iso(quote.retrieved_at),
                "status": quote.status,
                "reason": quote.reason,
                "value": _float(quote.value),
                "quote_time": _iso(quote.quote_time),
                "quote_time_verified": quote.quote_time_verified,
                "value_kind": quote.value_kind,
                "delay_seconds": quote.delay_seconds,
                "provider_bar_time": _iso(quote.provider_bar_time),
                "minute_bar_time": _iso(quote.minute_bar_time),
                "continuous_contract": quote.continuous_contract,
            }
            for key in (
                "update_mode",
                "current_session",
                "description",
                "change_basis",
            ):
                value = getattr(quote, key)
                if value is not None:
                    row[key] = value
            for key in ("scanner_close", "provider_change_pct", "provider_change_abs"):
                value = getattr(quote, key)
                if value is not None:
                    row[key] = _float(value)
            quote_refs = session.scalars(
                select(ResearchMarketScannerSourceRef)
                .where(ResearchMarketScannerSourceRef.quote_id == quote.id)
                .order_by(ResearchMarketScannerSourceRef.ordinal)
            ).all()
            row["source_refs"] = [_ref_dict(ref) for ref in quote_refs]
            result["observations"].append(row)
    for key, present in (
        ("chart_series", batch.has_chart_series),
        ("execution_chart_series", batch.has_execution_chart_series),
        ("series", batch.has_series),
    ):
        if not present:
            continue
        result[key] = []
        rows = session.scalars(
            select(ResearchMarketChartSeries)
            .where(ResearchMarketChartSeries.batch_id == batch.id, ResearchMarketChartSeries.collection_key == key)
            .order_by(ResearchMarketChartSeries.ordinal)
        ).all()
        for item in rows:
            row = {
                "ticker": item.ticker,
                "status": item.status,
                "resolution_seconds": item.resolution_seconds,
                "delay_seconds": item.delay_seconds,
                "retrieved_at": _iso(item.retrieved_at),
                "front_contract": item.front_contract,
                "continuous_contract": item.continuous_contract,
            }
            if item.error is not None:
                row["error"] = item.error
            if item.has_metadata:
                row["metadata"] = {
                    "exchange": item.exchange,
                    "instrument_type": item.instrument_type,
                    "currency": item.currency,
                    "update_mode": item.update_mode,
                    "provider_delay_seconds": item.provider_delay_seconds,
                    "series_completed": item.series_completed,
                }
                for target, source in (
                    ("timezone", "provider_timezone"),
                    ("session", "provider_session"),
                    ("description", "description"),
                ):
                    value = getattr(item, source)
                    if value is not None:
                        row["metadata"][target] = value
            bars = session.scalars(
                select(ResearchMarketBar)
                .where(ResearchMarketBar.series_id == item.id)
                .order_by(ResearchMarketBar.ordinal)
            ).all()
            row["bars"] = [
                {
                    "time": _iso(bar.bar_time),
                    "open": _float(bar.open),
                    "high": _float(bar.high),
                    "low": _float(bar.low),
                    "close": _float(bar.close),
                    "volume": _float(bar.volume),
                    **({"front_contract": bar.front_contract} if bar.front_contract is not None else {}),
                }
                for bar in bars
            ]
            series_refs = session.scalars(
                select(ResearchMarketSeriesSourceRef)
                .where(ResearchMarketSeriesSourceRef.series_id == item.id)
                .order_by(ResearchMarketSeriesSourceRef.ordinal)
            ).all()
            row["source_refs"] = [_ref_dict(ref) for ref in series_refs]
            result[key].append(row)
    if batch.has_source_refs:
        refs = session.scalars(
            select(ResearchMarketBatchSourceRef)
            .where(ResearchMarketBatchSourceRef.batch_id == batch.id)
            .order_by(ResearchMarketBatchSourceRef.ordinal)
        ).all()
        result["source_refs"] = [_ref_dict(ref) for ref in refs]
    if batch.has_limitations:
        result["limitations"] = list(
            session.scalars(
                select(ResearchMarketLimitation.limitation)
                .where(ResearchMarketLimitation.batch_id == batch.id)
                .order_by(ResearchMarketLimitation.ordinal)
            )
        )
    return result
