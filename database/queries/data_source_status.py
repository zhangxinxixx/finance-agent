"""数据源状态仓库：DataSourceStatus 的幂等 upsert 与查询。

所有函数使用便携 AnalysisBase 模型，在 SQLite 和 PostgreSQL 上均可运行。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.analysis import DataSourceStatus


def upsert_data_source_status(
    session: Session,
    data: dict[str, Any],
) -> DataSourceStatus:
    """幂等 upsert：按 source_key 查找，存在则更新，不存在则创建。

    data 键（与 DataSourceStatus 字段一一对应）：
      source_key, source_name, source_group, source_type, access_method,
      configured, raw_ingested, parsed, analysis_ready,
      latest_raw_time, latest_parsed_time, latest_snapshot_id, row_count,
      status, error_message, last_run_id, next_run_time, source_metadata
    """
    source_key = data["source_key"]
    existing = session.scalar(
        select(DataSourceStatus).where(DataSourceStatus.source_key == source_key)
    )

    if existing is not None:
        # Update all mutable fields
        existing.source_name = data.get("source_name", existing.source_name)
        existing.source_group = data.get("source_group")
        existing.source_type = data.get("source_type")
        existing.access_method = data.get("access_method")
        existing.configured = data.get("configured", False)
        existing.raw_ingested = data.get("raw_ingested", False)
        existing.parsed = data.get("parsed", False)
        existing.analysis_ready = data.get("analysis_ready", False)
        existing.latest_raw_time = data.get("latest_raw_time")
        existing.latest_parsed_time = data.get("latest_parsed_time")
        existing.latest_snapshot_id = data.get("latest_snapshot_id")
        existing.row_count = data.get("row_count")
        existing.status = data.get("status", "not_connected")
        existing.error_message = data.get("error_message")
        existing.last_run_id = data.get("last_run_id")
        existing.next_run_time = data.get("next_run_time")
        existing.source_metadata = data.get("source_metadata", {})
        session.flush()
        return existing

    record = DataSourceStatus(
        source_key=data["source_key"],
        source_name=data.get("source_name", source_key),
        source_group=data.get("source_group"),
        source_type=data.get("source_type"),
        access_method=data.get("access_method"),
        configured=data.get("configured", False),
        raw_ingested=data.get("raw_ingested", False),
        parsed=data.get("parsed", False),
        analysis_ready=data.get("analysis_ready", False),
        latest_raw_time=data.get("latest_raw_time"),
        latest_parsed_time=data.get("latest_parsed_time"),
        latest_snapshot_id=data.get("latest_snapshot_id"),
        row_count=data.get("row_count"),
        status=data.get("status", "not_connected"),
        error_message=data.get("error_message"),
        last_run_id=data.get("last_run_id"),
        next_run_time=data.get("next_run_time"),
        source_metadata=data.get("source_metadata", {}),
    )
    session.add(record)
    session.flush()
    return record


def list_data_source_statuses(
    session: Session,
    source_group: str | None = None,
) -> list[DataSourceStatus]:
    """列出所有数据源状态，可按 source_group 过滤，按 source_key 排序。"""
    stmt = select(DataSourceStatus)
    if source_group is not None:
        stmt = stmt.where(DataSourceStatus.source_group == source_group)
    stmt = stmt.order_by(DataSourceStatus.source_key)
    return list(session.scalars(stmt))


def get_data_source_status(
    session: Session,
    source_key: str,
) -> DataSourceStatus | None:
    """按 source_key 精确查询单个数据源状态。"""
    return session.scalar(
        select(DataSourceStatus).where(DataSourceStatus.source_key == source_key)
    )
