"""Market candle persistence helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from database.models.analysis import MarketCandle
from database.market_identity import normalize_market_candle_identity


def upsert_market_candle(
    session: Session,
    *,
    asset: str,
    timeframe: str,
    open_time: datetime,
    open: float,
    high: float,
    low: float,
    close: float,
    source: str,
    volume: float | None = None,
    source_ref: dict | None = None,
    raw_path: str | None = None,
) -> MarketCandle:
    identity = normalize_market_candle_identity(asset=asset, source=source, source_ref=source_ref)
    existing = session.scalar(
        select(MarketCandle).where(
            MarketCandle.asset == identity.asset,
            MarketCandle.timeframe == timeframe,
            MarketCandle.open_time == open_time,
            MarketCandle.source == source,
        )
    )

    if existing is not None:
        existing.open = float(open)
        existing.high = float(high)
        existing.low = float(low)
        existing.close = float(close)
        existing.volume = float(volume) if volume is not None else None
        existing.source_ref = identity.source_ref or None
        existing.raw_path = raw_path
        session.flush()
        return existing

    row = MarketCandle(
        asset=identity.asset,
        timeframe=timeframe,
        open_time=open_time,
        open=float(open),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=float(volume) if volume is not None else None,
        source=source,
        source_ref=identity.source_ref or None,
        raw_path=raw_path,
    )
    session.add(row)
    session.flush()
    return row


def list_market_candles(
    session: Session,
    *,
    asset: str,
    timeframe: str,
    limit: int = 100,
    source: str | None = None,
) -> list[MarketCandle]:
    stmt = (
        select(MarketCandle)
        .where(
            MarketCandle.asset == asset,
            MarketCandle.timeframe == timeframe,
        )
    )
    if source:
        stmt = stmt.where(MarketCandle.source == source)
    stmt = stmt.order_by(MarketCandle.open_time.desc(), MarketCandle.id.desc()).limit(limit)
    return list(reversed(list(session.scalars(stmt).all())))


def list_completed_market_candles(
    session: Session,
    *,
    asset: str,
    timeframe: str,
    as_of: datetime,
    bar_duration: timedelta,
    limit: int = 100,
    source: str | None = None,
) -> list[MarketCandle]:
    """Return completed bars available at ``as_of`` in chronological order.

    ``open_time`` is the bar start.  A bar is eligible only when its end is at
    or before the point-in-time boundary, expressed as
    ``open_time <= as_of - bar_duration``.  Naive datetimes are rejected so
    callers cannot silently mix local clock time with canonical UTC storage.
    """

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if not isinstance(bar_duration, timedelta) or bar_duration <= timedelta(0):
        raise ValueError("bar_duration must be positive")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be positive")

    cutoff = as_of.astimezone(UTC) - bar_duration
    stmt = select(MarketCandle).where(
        MarketCandle.asset == asset,
        MarketCandle.timeframe == timeframe,
        MarketCandle.open_time <= cutoff,
    )
    if source is not None:
        stmt = stmt.where(MarketCandle.source == source)
    stmt = stmt.order_by(MarketCandle.open_time.desc(), MarketCandle.id.desc()).limit(limit)
    return list(reversed(list(session.scalars(stmt).all())))


def list_market_candles_by_assets(
    session: Session,
    *,
    assets: list[str],
    timeframe: str,
    limit: int = 100,
) -> list[MarketCandle]:
    if not assets:
        return []
    stmt = (
        select(MarketCandle)
        .where(
            MarketCandle.asset.in_(assets),
            MarketCandle.timeframe == timeframe,
        )
        .order_by(MarketCandle.open_time.desc(), MarketCandle.id.desc())
        .limit(limit * max(len(assets), 1))
    )
    return list(reversed(list(session.scalars(stmt).all())))


def delete_market_candles_before(
    session: Session,
    *,
    asset: str,
    timeframe: str,
    source: str,
    before: datetime,
) -> int:
    stmt = (
        delete(MarketCandle)
        .where(
            MarketCandle.asset == asset,
            MarketCandle.timeframe == timeframe,
            MarketCandle.source == source,
            MarketCandle.open_time < before,
        )
        .execution_options(synchronize_session=False)
    )
    result = session.execute(stmt)
    return int(result.rowcount or 0)
