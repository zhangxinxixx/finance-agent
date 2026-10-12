"""Typed DWD context attached to immutable news-item fact versions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.models.warehouse import UTCDateTime, WarehouseBase

# Register the referenced fact table when this module is imported on its own.
from database.models.warehouse_sources import NewsItemFact as NewsItemFact


class NewsItemContext(WarehouseBase):
    """One typed compatibility context for one immutable ``NewsItemFact``."""

    __tablename__ = "dwh_news_item_context"
    __table_args__ = (
        CheckConstraint(
            "relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 1)",
            name="ck_dwh_news_context_relevance_score",
        ),
        CheckConstraint(
            "calendar_start_date IS NULL OR calendar_end_date IS NULL OR calendar_start_date <= calendar_end_date",
            name="ck_dwh_news_context_calendar_range",
        ),
        Index("ix_dwh_news_context_hash", "context_sha256"),
    )

    news_fact_id: Mapped[int] = mapped_column(ForeignKey("dwh_fact_news_item.id", ondelete="CASCADE"), primary_key=True)
    context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    publisher: Mapped[str | None] = mapped_column(String(255))
    publisher_url: Mapped[str | None] = mapped_column(Text)
    discovery_method: Mapped[str | None] = mapped_column(String(128))
    candidate_scope: Mapped[str | None] = mapped_column(String(128))
    authorized_wire: Mapped[bool | None] = mapped_column(Boolean)
    content_scope: Mapped[str | None] = mapped_column(String(128))
    full_text_available: Mapped[bool | None] = mapped_column(Boolean)

    calendar_start_date: Mapped[date | None] = mapped_column(Date)
    calendar_end_date: Mapped[date | None] = mapped_column(Date)
    calendar_release_date: Mapped[date | None] = mapped_column(Date)
    calendar_date_text: Mapped[str | None] = mapped_column(Text)
    calendar_is_sep: Mapped[bool | None] = mapped_column(Boolean)
    calendar_source_url: Mapped[str | None] = mapped_column(Text)

    relevance_decision: Mapped[str | None] = mapped_column(String(64))
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(18, 12))


class NewsArticleParagraph(WarehouseBase):
    __tablename__ = "dwh_news_article_paragraph"

    news_fact_id: Mapped[int] = mapped_column(
        ForeignKey("dwh_news_item_context.news_fact_id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    paragraph: Mapped[str] = mapped_column(Text, nullable=False)


class NewsRelevanceAssetTag(WarehouseBase):
    __tablename__ = "dwh_news_relevance_asset_tag"
    __table_args__ = (UniqueConstraint("news_fact_id", "asset_tag", name="uq_dwh_news_relevance_asset_tag"),)

    news_fact_id: Mapped[int] = mapped_column(
        ForeignKey("dwh_news_item_context.news_fact_id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_tag: Mapped[str] = mapped_column(String(128), nullable=False)


class NewsRelevanceTopicTag(WarehouseBase):
    __tablename__ = "dwh_news_relevance_topic_tag"
    __table_args__ = (UniqueConstraint("news_fact_id", "topic_tag", name="uq_dwh_news_relevance_topic_tag"),)

    news_fact_id: Mapped[int] = mapped_column(
        ForeignKey("dwh_news_item_context.news_fact_id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_tag: Mapped[str] = mapped_column(String(128), nullable=False)


class NewsItemSourceReference(WarehouseBase):
    """Named source-lineage fields used by current news feature consumers."""

    __tablename__ = "dwh_news_item_source_ref"
    __table_args__ = (Index("ix_dwh_news_source_ref_identity", "source", "source_ref"),)

    news_fact_id: Mapped[int] = mapped_column(
        ForeignKey("dwh_news_item_context.news_fact_id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_ref: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(128))
    source_key: Mapped[str | None] = mapped_column(String(128))
    source_type: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(128))
    provider_role: Mapped[str | None] = mapped_column(String(64))
    reference: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(255))
    feed_key: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str | None] = mapped_column(String(64))
    content_scope: Mapped[str | None] = mapped_column(String(128))
    publisher: Mapped[str | None] = mapped_column(String(255))
    publisher_url: Mapped[str | None] = mapped_column(Text)
    discovery_method: Mapped[str | None] = mapped_column(String(128))
    candidate_scope: Mapped[str | None] = mapped_column(String(128))
    authorized_wire: Mapped[bool | None] = mapped_column(Boolean)
    full_text_available: Mapped[bool | None] = mapped_column(Boolean)
    raw_path: Mapped[str | None] = mapped_column(Text)
    parsed_path: Mapped[str | None] = mapped_column(Text)
    asset_type: Mapped[str | None] = mapped_column(String(64))
    path: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    access_mode: Mapped[str | None] = mapped_column(String(128))
    reason_code: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String(255))
    chat_id: Mapped[str | None] = mapped_column(String(255))


NEWS_CONTEXT_TABLES = (
    NewsItemContext.__table__,
    NewsArticleParagraph.__table__,
    NewsRelevanceAssetTag.__table__,
    NewsRelevanceTopicTag.__table__,
    NewsItemSourceReference.__table__,
)
