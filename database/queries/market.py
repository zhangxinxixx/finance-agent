"""Market candle persistence helpers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.analysis import MarketCandle


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
    existing = session.scalar(
        select(MarketCandle).where(
            MarketCandle.asset == asset,
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
        existing.source_ref = dict(source_ref) if isinstance(source_ref, dict) else None
        existing.raw_path = raw_path
        session.flush()
        return existing

    row = MarketCandle(
        asset=asset,
        timeframe=timeframe,
        open_time=open_time,
        open=float(open),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=float(volume) if volume is not None else None,
        source=source,
        source_ref=dict(source_ref) if isinstance(source_ref, dict) else None,
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
