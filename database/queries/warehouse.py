"""Bounded read-only examples for DWD joins and on-demand DWS aggregation."""

from sqlalchemy import select, func
from database.models.warehouse import (
    MacroFact,
    CandleFact,
    NewsEventFact,
    NewsTriggerFact,
    DateDimension,
    MetricDimension,
    SourceDimension,
    AssetDimension,
    ProducerRunDimension,
    EventAsset,
    TriggerAsset,
)


def _limit(limit):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("DWH_ARGUMENT_INVALID")
    return limit


def macro_observations(session, *, symbol=None, source=None, start=None, end=None, run_id=None, limit=100):
    stmt = (
        select(
            MacroFact.id,
            DateDimension.date,
            SourceDimension.source_key,
            MetricDimension.symbol,
            MacroFact.value,
            MacroFact.unit,
            MacroFact.retrieved_at,
            MacroFact.quality_status,
            MacroFact.version_sha256,
            ProducerRunDimension.run_id,
            ProducerRunDimension.verified,
        )
        .join(MetricDimension, MacroFact.metric_id == MetricDimension.id)
        .join(SourceDimension, MetricDimension.source_id == SourceDimension.id)
        .join(DateDimension, MacroFact.date_key == DateDimension.date_key)
        .outerjoin(ProducerRunDimension, MacroFact.producer_run_id == ProducerRunDimension.id)
    )
    for value, clause in (
        (symbol, MetricDimension.symbol == symbol),
        (source, SourceDimension.source_key == source),
        (start, DateDimension.date >= start if start is not None else None),
        (end, DateDimension.date <= end if end is not None else None),
        (run_id, ProducerRunDimension.run_id == run_id),
    ):
        if value is not None:
            stmt = stmt.where(clause)
    with session.no_autoflush:
        return list(session.execute(stmt.order_by(MacroFact.date_key, MacroFact.id).limit(_limit(limit))).mappings())


def macro_daily_counts(session, *, source=None, start=None, end=None, limit=100):
    stmt = (
        select(DateDimension.date, SourceDimension.source_key, func.count(MacroFact.id).label("version_count"))
        .select_from(MacroFact)
        .join(DateDimension)
        .join(MetricDimension)
        .join(SourceDimension)
    )
    if source is not None:
        stmt = stmt.where(SourceDimension.source_key == source)
    if start is not None:
        stmt = stmt.where(DateDimension.date >= start)
    if end is not None:
        stmt = stmt.where(DateDimension.date <= end)
    with session.no_autoflush:
        return list(
            session.execute(
                stmt.group_by(DateDimension.date, SourceDimension.source_key)
                .order_by(DateDimension.date, SourceDimension.source_key)
                .limit(_limit(limit))
            ).mappings()
        )


def candles(session, *, asset=None, source=None, timeframe=None, start=None, end=None, limit=100):
    stmt = (
        select(
            CandleFact.id,
            AssetDimension.code.label("asset"),
            SourceDimension.source_key,
            CandleFact.timeframe,
            CandleFact.open_time,
            CandleFact.open,
            CandleFact.high,
            CandleFact.low,
            CandleFact.close,
            CandleFact.volume,
            CandleFact.version_sha256,
        )
        .join(AssetDimension)
        .join(SourceDimension)
    )
    for value, clause in (
        (asset, AssetDimension.code == asset),
        (source, SourceDimension.source_key == source),
        (timeframe, CandleFact.timeframe == timeframe),
        (start, CandleFact.open_time >= start if start is not None else None),
        (end, CandleFact.open_time <= end if end is not None else None),
    ):
        if value is not None:
            stmt = stmt.where(clause)
    with session.no_autoflush:
        return list(session.execute(stmt.order_by(CandleFact.open_time, CandleFact.id).limit(_limit(limit))).mappings())


def news_facts(session, *, dataset, asset=None, source=None, run_id=None, start=None, end=None, status=None, limit=100):
    if dataset not in ("news-events", "news-triggers"):
        raise ValueError("DWH_ARGUMENT_INVALID")
    event = dataset == "news-events"
    model, bridge = (NewsEventFact, EventAsset) if event else (NewsTriggerFact, TriggerAsset)
    instant = model.event_time if event else model.created_at
    stmt = select(model).join(ProducerRunDimension, model.producer_run_id == ProducerRunDimension.id)
    if asset is not None:
        parent = bridge.event_id if event else bridge.trigger_id
        stmt = stmt.where(
            select(parent).join(AssetDimension).where(parent == model.id, AssetDimension.code == asset).exists()
        )
    if source is not None:
        if event:
            from database.models.warehouse import EventSourceReference

            stmt = stmt.where(
                select(EventSourceReference.id)
                .join(SourceDimension)
                .where(EventSourceReference.event_id == model.id, SourceDimension.source_key == source)
                .exists()
            )
        else:
            stmt = stmt.join(SourceDimension, model.source_id == SourceDimension.id).where(
                SourceDimension.source_key == source
            )
    for value, clause in (
        (run_id, ProducerRunDimension.run_id == run_id),
        (start, instant >= start if start is not None else None),
        (end, instant <= end if end is not None else None),
        (status, model.status == status),
    ):
        if value is not None:
            stmt = stmt.where(clause)
    with session.no_autoflush:
        return list(session.scalars(stmt.order_by(instant, model.id).limit(_limit(limit))))
