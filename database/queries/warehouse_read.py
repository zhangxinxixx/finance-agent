"""Read-only compatibility DTOs backed exclusively by typed DWD facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import aliased

from database.models.warehouse import (
    AssetDimension,
    CandleFact,
    DateDimension,
    MacroFact,
    MetricDimension,
    ProducerRunDimension,
    SourceDimension,
)


@dataclass(frozen=True)
class WarehouseMacroObservation:
    id: str
    source_key: str
    symbol: str
    observation_date: date
    value: float | None
    unit: str | None
    frequency: str | None
    source_url: str | None
    raw_path: str | None
    raw_artifact_id: str | None
    parsed_artifact_id: str | None
    retrieved_at: datetime | None
    run_id: str | None
    source_refs: list[dict[str, Any]]
    observation_metadata: dict[str, Any]
    warehouse_fact_id: int
    version_sha256: str
    batch_id: int


@dataclass(frozen=True)
class WarehouseCandle:
    id: str
    asset: str
    timeframe: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    source: str
    source_ref: dict[str, Any] | None
    raw_path: str | None
    created_at: datetime | None
    updated_at: datetime | None
    warehouse_fact_id: int
    version_sha256: str
    batch_id: int


def list_warehouse_macro_observations(
    session,
    *,
    source_key: str | None = None,
    symbol: str | None = None,
    run_id: str | None = None,
    record_ids: Iterable[str] | None = None,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    as_of: datetime | None = None,
    limit: int = 1000,
) -> list[WarehouseMacroObservation]:
    """Return one source-time revision per macro business grain.

    Missing DWD schema errors are deliberately propagated.  No ODS, JSON,
    filesystem, DDL, or warehouse-load timestamp fallback is available here.
    """

    bounded_limit = _limit(limit)
    selected_ids = _record_ids(record_ids, limit=bounded_limit)
    if selected_ids == ():
        return []
    cutoff = _as_of(as_of)
    start = _date(start_date, field="start_date")
    end = _date(end_date, field="end_date")
    if start is not None and end is not None and start > end:
        raise ValueError("start_date must not be after end_date")

    unknown = aliased(MacroFact)
    unknown_metric = aliased(MetricDimension)
    later_unknown = exists(
        select(unknown.id).join(unknown_metric, unknown.metric_id == unknown_metric.id).where(
            unknown_metric.source_id == MetricDimension.source_id,
            unknown_metric.symbol == MetricDimension.symbol,
            unknown.date_key == MacroFact.date_key,
            unknown.retrieved_at.is_(None),
            unknown.id > MacroFact.id,
        )
    )
    revision_rank = func.row_number().over(
        partition_by=(MetricDimension.source_id, MetricDimension.symbol, MacroFact.date_key),
        order_by=(
            case((MacroFact.retrieved_at.is_not(None), 1), else_=0).desc(),
            MacroFact.retrieved_at.desc(),
            MacroFact.id.desc(),
        ),
    )
    stmt = (
        select(
            MacroFact.source_record_id.label("id"),
            SourceDimension.source_key,
            MetricDimension.symbol,
            DateDimension.date.label("observation_date"),
            MacroFact.value,
            MacroFact.unit,
            MetricDimension.frequency,
            MacroFact.source_url,
            MacroFact.previous_value,
            MacroFact.reference_period,
            MacroFact.previous_reference_period,
            MacroFact.raw_path,
            MacroFact.raw_artifact_id,
            MacroFact.parsed_artifact_id,
            MacroFact.retrieved_at,
            MacroFact.quality_status,
            ProducerRunDimension.run_id,
            MacroFact.id.label("warehouse_fact_id"),
            MacroFact.version_sha256,
            MacroFact.batch_id,
            revision_rank.label("revision_rank"),
        )
        .join(MetricDimension, MacroFact.metric_id == MetricDimension.id)
        .join(SourceDimension, MetricDimension.source_id == SourceDimension.id)
        .join(DateDimension, MacroFact.date_key == DateDimension.date_key)
        .outerjoin(ProducerRunDimension, MacroFact.producer_run_id == ProducerRunDimension.id)
    )
    if source_key is not None:
        stmt = stmt.where(SourceDimension.source_key == source_key)
    if symbol is not None:
        stmt = stmt.where(MetricDimension.symbol == symbol)
    if run_id is not None:
        stmt = stmt.where(ProducerRunDimension.run_id == run_id)
    if selected_ids is not None:
        stmt = stmt.where(MacroFact.source_record_id.in_(selected_ids))
    if start is not None:
        stmt = stmt.where(DateDimension.date >= start)
    if end is not None:
        stmt = stmt.where(DateDimension.date <= end)
    if cutoff is not None:
        # Unknown availability cannot be proven PIT-safe.  A later unknown
        # fact also blocks fallback to an older evidence-bearing revision.
        stmt = stmt.where(
            MacroFact.retrieved_at.is_not(None),
            MacroFact.retrieved_at <= cutoff,
            DateDimension.date <= cutoff.date(),
            ~later_unknown,
        )
    else:
        stmt = stmt.where(or_(MacroFact.retrieved_at.is_(None), ~later_unknown))

    ranked = stmt.subquery("ranked_warehouse_macro")
    query = (
        select(ranked)
        .where(ranked.c.revision_rank == 1)
        .order_by(
            ranked.c.observation_date.desc(),
            ranked.c.source_key.asc(),
            ranked.c.symbol.asc(),
            ranked.c.warehouse_fact_id.desc(),
        )
        .limit(bounded_limit)
    )
    with session.no_autoflush:
        rows = session.execute(query).mappings().all()
    return [_macro_dto(row) for row in rows]


def list_warehouse_candles(
    session,
    *,
    asset: str,
    timeframe: str,
    limit: int = 100,
    source: str | None = None,
    as_of: datetime | None = None,
) -> list[WarehouseCandle]:
    """Return the most recent ``limit`` grains in chronological order."""

    return _list_candles(
        session,
        asset=asset,
        timeframe=timeframe,
        limit=_limit(limit, maximum=300000),
        source=source,
        as_of=_as_of(as_of),
        completed_before=None,
    )


def list_completed_warehouse_candles(
    session,
    *,
    asset: str,
    timeframe: str,
    as_of: datetime,
    bar_duration: timedelta,
    limit: int = 100,
    source: str | None = None,
) -> list[WarehouseCandle]:
    """Return PIT-available bars whose inclusive close is at/before ``as_of``."""

    cutoff = _as_of(as_of, required=True)
    if not isinstance(bar_duration, timedelta) or bar_duration <= timedelta(0):
        raise ValueError("bar_duration must be positive")
    return _list_candles(
        session,
        asset=asset,
        timeframe=timeframe,
        limit=_limit(limit, maximum=300000),
        source=source,
        as_of=cutoff,
        completed_before=cutoff - bar_duration,
    )


def list_warehouse_candles_by_assets(
    session,
    *,
    assets: Iterable[str],
    timeframe: str,
    limit: int = 100,
    as_of: datetime | None = None,
) -> list[WarehouseCandle]:
    """Return at most ``limit`` recent rows per distinct asset."""

    if isinstance(assets, (str, bytes)):
        raise ValueError("assets must be a bounded iterable")
    values = tuple(assets)
    if any(not isinstance(item, str) for item in values):
        raise ValueError("assets must contain strings")
    normalized = tuple(dict.fromkeys(values))
    if not normalized:
        return []
    if len(normalized) > 1000 or any(not item for item in normalized):
        raise ValueError("assets must contain 1..1000 non-empty values")
    bounded_limit = _limit(limit, maximum=300000)
    cutoff = _as_of(as_of)
    rows = [
        row
        for asset in normalized
        for row in _list_candles(
            session,
            asset=asset,
            timeframe=timeframe,
            limit=bounded_limit,
            source=None,
            as_of=cutoff,
            completed_before=None,
        )
    ]
    return sorted(rows, key=lambda row: (row.open_time, row.asset, row.source, row.warehouse_fact_id))


def _list_candles(
    session,
    *,
    asset: str,
    timeframe: str,
    limit: int,
    source: str | None,
    as_of: datetime | None,
    completed_before: datetime | None,
) -> list[WarehouseCandle]:
    if not isinstance(asset, str) or not asset or not isinstance(timeframe, str) or not timeframe:
        raise ValueError("asset and timeframe must be non-empty strings")

    available_at = _candle_available_at(CandleFact)
    unknown = aliased(CandleFact)
    unknown_available_at = _candle_available_at(unknown)
    later_unknown = exists(
        select(unknown.id).where(
            unknown.asset_id == CandleFact.asset_id,
            unknown.source_id == CandleFact.source_id,
            unknown.timeframe == CandleFact.timeframe,
            unknown.open_time == CandleFact.open_time,
            unknown_available_at.is_(None),
            unknown.id > CandleFact.id,
        )
    )
    revision_rank = func.row_number().over(
        partition_by=(CandleFact.asset_id, CandleFact.source_id, CandleFact.timeframe, CandleFact.open_time),
        order_by=(
            case((available_at.is_not(None), 1), else_=0).desc(),
            available_at.desc(),
            CandleFact.id.desc(),
        ),
    )
    stmt = (
        select(
            CandleFact.source_record_id.label("id"),
            AssetDimension.code.label("asset"),
            CandleFact.timeframe,
            CandleFact.open_time,
            CandleFact.open,
            CandleFact.high,
            CandleFact.low,
            CandleFact.close,
            CandleFact.volume,
            SourceDimension.source_key.label("source"),
            CandleFact.raw_path,
            CandleFact.retrieved_at,
            CandleFact.created_at,
            CandleFact.updated_at,
            CandleFact.provider,
            CandleFact.provider_symbol,
            CandleFact.provider_timeframe,
            CandleFact.instrument_type,
            CandleFact.source_role,
            CandleFact.source_url,
            CandleFact.source_reference,
            CandleFact.reference_status,
            CandleFact.evidence_scope,
            CandleFact.source_tier,
            CandleFact.identity_guard,
            CandleFact.quality_status,
            CandleFact.id.label("warehouse_fact_id"),
            CandleFact.version_sha256,
            CandleFact.batch_id,
            revision_rank.label("revision_rank"),
        )
        .join(AssetDimension, CandleFact.asset_id == AssetDimension.id)
        .join(SourceDimension, CandleFact.source_id == SourceDimension.id)
        .where(AssetDimension.code == asset, CandleFact.timeframe == timeframe)
    )
    if source is not None:
        stmt = stmt.where(SourceDimension.source_key == source)
    if completed_before is not None:
        stmt = stmt.where(CandleFact.open_time <= completed_before)
    elif as_of is not None:
        stmt = stmt.where(CandleFact.open_time <= as_of)
    if as_of is not None:
        stmt = stmt.where(available_at.is_not(None), available_at <= as_of, ~later_unknown)
    else:
        stmt = stmt.where(or_(available_at.is_(None), ~later_unknown))

    ranked = stmt.subquery("ranked_warehouse_candle")
    query = (
        select(ranked)
        .where(ranked.c.revision_rank == 1)
        .order_by(ranked.c.open_time.desc(), ranked.c.warehouse_fact_id.desc())
        .limit(limit)
    )
    with session.no_autoflush:
        rows = session.execute(query).mappings().all()
    return list(reversed([_candle_dto(row) for row in rows]))


def _macro_dto(row) -> WarehouseMacroObservation:
    retrieved_at = _utc(row["retrieved_at"])
    source_ref = _compact(
        source=row["source_key"],
        symbol=row["symbol"],
        source_url=row["source_url"],
        raw_path=row["raw_path"],
        raw_artifact_id=row["raw_artifact_id"],
        parsed_artifact_id=row["parsed_artifact_id"],
        retrieved_at=retrieved_at,
        quality_status=row["quality_status"],
    )
    metadata = _compact(
        quality_status=row["quality_status"],
        previous_value=float(row["previous_value"]) if row["previous_value"] is not None else None,
        reference_period=row["reference_period"],
        previous_reference_period=row["previous_reference_period"],
    )
    return WarehouseMacroObservation(
        id=row["id"],
        source_key=row["source_key"],
        symbol=row["symbol"],
        observation_date=row["observation_date"],
        value=float(row["value"]) if row["value"] is not None else None,
        unit=row["unit"],
        frequency=row["frequency"] or None,
        source_url=row["source_url"],
        raw_path=row["raw_path"],
        raw_artifact_id=row["raw_artifact_id"],
        parsed_artifact_id=row["parsed_artifact_id"],
        retrieved_at=retrieved_at,
        run_id=row["run_id"],
        source_refs=[source_ref],
        observation_metadata=metadata,
        warehouse_fact_id=row["warehouse_fact_id"],
        version_sha256=row["version_sha256"],
        batch_id=row["batch_id"],
    )


def _candle_dto(row) -> WarehouseCandle:
    retrieved_at = _utc(row["retrieved_at"])
    created_at = _utc(row["created_at"])
    updated_at = _utc(row["updated_at"])
    source_ref = _compact(
        provider=row["provider"],
        provider_symbol=row["provider_symbol"],
        provider_timeframe=row["provider_timeframe"],
        instrument_type=row["instrument_type"],
        source_role=row["source_role"],
        source_url=row["source_url"],
        reference=row["source_reference"],
        status=row["reference_status"],
        evidence_scope=row["evidence_scope"],
        source_tier=row["source_tier"],
        identity_guard=row["identity_guard"],
        retrieved_at=retrieved_at,
        created_at=created_at,
        updated_at=updated_at,
        raw_path=row["raw_path"],
        quality_status=row["quality_status"],
    )
    return WarehouseCandle(
        id=row["id"],
        asset=row["asset"],
        timeframe=row["timeframe"],
        open_time=_utc(row["open_time"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]) if row["volume"] is not None else None,
        source=row["source"],
        source_ref=source_ref or None,
        raw_path=row["raw_path"],
        created_at=created_at,
        updated_at=updated_at,
        warehouse_fact_id=row["warehouse_fact_id"],
        version_sha256=row["version_sha256"],
        batch_id=row["batch_id"],
    )


def _compact(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None and value != ""}


def _candle_available_at(model):
    """Latest source-side collection/revision time, portable across SQL dialects."""

    return case(
        (
            and_(
                model.retrieved_at.is_not(None),
                or_(model.updated_at.is_(None), model.retrieved_at >= model.updated_at),
                or_(model.created_at.is_(None), model.retrieved_at >= model.created_at),
            ),
            model.retrieved_at,
        ),
        (
            and_(
                model.updated_at.is_not(None),
                or_(model.created_at.is_(None), model.updated_at >= model.created_at),
            ),
            model.updated_at,
        ),
        else_=model.created_at,
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _as_of(value: datetime | None, *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            raise ValueError("as_of must be timezone-aware")
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC)


def _date(value: str | date | None, *, field: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip().split("T", 1)[0].split(" ", 1)[0])
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _limit(value: int, *, maximum: int = 1000) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return value


def _record_ids(values: Iterable[str] | None, *, limit: int) -> tuple[str, ...] | None:
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise ValueError("record_ids must be a bounded iterable")
    items = tuple(values)
    if any(not isinstance(value, str) for value in items):
        raise ValueError("record_ids must contain strings")
    normalized = tuple(dict.fromkeys(items))
    if len(normalized) > 1000 or len(normalized) > limit or any(not value for value in normalized):
        raise ValueError("record_ids must be non-empty strings and fit within limit")
    return normalized
