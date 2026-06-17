"""Jin10 快讯持久化模型和仓库操作。

提供：
- Jin10FlashMessage: 消息存储，增量光标拉取
- FlashCursorState: 光标追踪，断点续拉
- upsert / query / analysis dispatch
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models.analysis import (
    Jin10FlashMessage,
    FlashCursorState,
    ensure_analysis_tables,
)

logger = logging.getLogger(__name__)

UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


# ── Cursor ────────────────────────────────────────────────────────────────

def get_latest_cursor(session: Session, source_key: str = "jin10_mcp_flash") -> dict[str, Any] | None:
    """获取最新拉取光标，返回 None 表示首次拉取。"""
    cursor = session.scalar(
        select(FlashCursorState).where(FlashCursorState.source_key == source_key)
    )
    if cursor is None:
        return None
    return {
        "latest_message_id": cursor.latest_message_id,
        "latest_message_time": cursor.latest_message_time,
        "total_fetched": cursor.total_fetched,
        "last_fetch_at": cursor.last_fetch_at,
    }


def update_cursor(
    session: Session,
    source_key: str,
    latest_message_id: str | None,
    latest_message_time: datetime | None,
    fetch_count: int,
    status: str = "ok",
) -> None:
    """更新光标状态（幂等 upsert）。"""
    cursor = session.scalar(
        select(FlashCursorState).where(FlashCursorState.source_key == source_key)
    )
    now = utc_now()
    if cursor is None:
        cursor = FlashCursorState(
            source_key=source_key,
            latest_message_id=latest_message_id,
            latest_message_time=latest_message_time,
            total_fetched=fetch_count,
            last_fetch_at=now,
            last_fetch_status=status,
        )
        session.add(cursor)
    else:
        cursor.latest_message_id = latest_message_id or cursor.latest_message_id
        cursor.latest_message_time = latest_message_time or cursor.latest_message_time
        cursor.total_fetched = cursor.total_fetched + fetch_count
        cursor.last_fetch_at = now
        cursor.last_fetch_status = status
    session.flush()


# ── Message Persistence ────────────────────────────────────────────────────


def _generate_message_id(item: dict[str, Any]) -> str:
    """为没有 ID 的快讯生成确定性唯一标识。"""
    msg_id = str(item.get("id") or item.get("message_id") or "")
    if msg_id:
        return msg_id
    # 用 content + time 的 MD5 作为 ID
    content = str(item.get("content") or "")
    time_val = str(item.get("time") or "")
    return hashlib.md5(f"{content}|{time_val}".encode()).hexdigest()[:32]

def _normalize_message_time(value: Any) -> datetime | None:
    """解析 Jin10 MCP 返回的时间字段为 UTC datetime。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        text_val = value.strip().replace("Z", "+00:00")
        for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(text_val.replace(" ", "T"), fmt.split("%z")[0])
                return dt.replace(tzinfo=UTC)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text_val)
        except ValueError:
            pass
    return None


def _message_already_exists(session: Session, message_id: str) -> bool:
    """检查消息是否已存在。"""
    from sqlalchemy import exists as sql_exists
    return session.scalar(
        sql_exists().where(Jin10FlashMessage.message_id == message_id).select()
    ) is True


def _signal_tags_str(tags: Any) -> str | None:
    """信号标签列表 → 逗号分隔字符串。"""
    if isinstance(tags, list):
        return ",".join(str(t) for t in tags if t)
    if isinstance(tags, str):
        return tags
    return None


def upsert_flash_message(
    session: Session,
    message_id: str,
    content: str,
    message_time: datetime | None,
    *,
    is_key_event: bool = False,
    importance: str = "normal",
    signal_tags: list[str] | None = None,
    content_type: str = "flash",
    classification_provider: str | None = None,
    classification_model: str | None = None,
    classification_confidence: float | None = None,
    filter_reason: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> bool:
    """幂等写入快讯消息。返回 True 表示是新消息。"""
    if _message_already_exists(session, message_id):
        return False

    record = Jin10FlashMessage(
        message_id=message_id,
        content=content,
        message_time=message_time,
        is_key_event=is_key_event,
        importance=importance,
        signal_tags=_signal_tags_str(signal_tags),
        content_type=content_type,
        classification_provider=classification_provider,
        classification_model=classification_model,
        classification_confidence=classification_confidence,
        filter_reason=filter_reason,
        raw_payload=json.dumps(raw_payload, ensure_ascii=False) if raw_payload else None,
        analysis_processed=False,
    )
    session.add(record)
    return True


def persist_flash_items(
    session: Session,
    annotated_items: list[dict[str, Any]],
    source_key: str = "jin10_mcp_flash",
) -> dict[str, int]:
    """批量持久化分类标注后的快讯消息，并更新光标。

    Returns:
        {"new": N, "skipped": M, "key_events": K}
    """
    ensure_analysis_tables(session)

    new_count = 0
    skipped_count = 0
    key_events = 0
    latest_id = None
    latest_time = None

    for item in annotated_items:
        msg_id = _generate_message_id(item)
        if not msg_id:
            continue

        content = str(item.get("content") or item.get("title") or "")
        if not content.strip():
            continue

        # 过滤无关快讯：normal 重要性 + flash 类型直接跳过
        imp = str(item.get("importance") or "normal")
        ct = str(item.get("content_type") or "flash")
        if imp == "normal" and ct == "flash":
            continue

        msg_time = _normalize_message_time(item.get("time"))

        # 追踪最新光标
        if msg_time and (latest_time is None or msg_time > latest_time):
            latest_time = msg_time
            latest_id = msg_id

        is_new = upsert_flash_message(
            session,
            message_id=msg_id,
            content=content,
            message_time=msg_time,
            is_key_event=bool(item.get("is_key_event")),
            importance=str(item.get("importance") or "normal"),
            signal_tags=item.get("signal_tags"),
            content_type=str(item.get("content_type") or "flash"),
            classification_provider=item.get("classification_provider"),
            classification_model=item.get("classification_model"),
            classification_confidence=(
                float(item["classification_confidence"])
                if item.get("classification_confidence") is not None
                else None
            ),
            filter_reason=str(item.get("filter_reason") or "")[:256] if item.get("filter_reason") else None,
            raw_payload=item,
        )
        if is_new:
            new_count += 1
            if bool(item.get("is_key_event")):
                key_events += 1
        else:
            skipped_count += 1

    # 更新光标
    update_cursor(
        session,
        source_key=source_key,
        latest_message_id=latest_id,
        latest_message_time=latest_time,
        fetch_count=new_count,
        status="ok",
    )
    session.commit()

    return {
        "new": new_count,
        "skipped": skipped_count,
        "key_events": key_events,
    }


# ── Analysis Task Dispatch ─────────────────────────────────────────────────

# 黄金/宏观相关的信号标签 → 需要触发深度分析
ANALYSIS_TRIGGER_TAGS = {
    "gold", "oil", "macro_policy", "rates", "inflation",
    "employment", "usd", "geopolitical_risk",
    "market_sensitive", "strategic_channel", "geopolitical_escalation",
}

# 分析触发的最低重要性
ANALYSIS_MIN_IMPORTANCE = {"high", "medium"}


def _should_trigger_analysis(msg: Jin10FlashMessage) -> bool:
    """判断一条快讯是否需要触发分析任务。"""
    if not msg.is_key_event:
        return False
    if msg.importance not in ANALYSIS_MIN_IMPORTANCE:
        return False

    tags = set()
    if msg.signal_tags:
        tags = set(msg.signal_tags.split(","))

    return bool(tags & ANALYSIS_TRIGGER_TAGS)


def dispatch_pending_flash_analysis(session: Session, limit: int = 5) -> int:
    """扫描未分析的 key_event 快讯，按 content_type 创建不同分析任务到 task_runs。

    分流规则：
    - report: 创建 report_analysis 深度分析任务（多 Agent 协作）
    - article: 创建 flash_article_analysis 中深度分析任务
    - calendar: 仅标记已处理，不创建分析任务（事件汇总不需 AI 分析）
    - flash: 仅标记已处理，不创建分析任务（短快讯不需深度分析）
    """
    from database.models.task import TaskRun, TaskStatus

    messages = session.execute(
        select(Jin10FlashMessage)
        .where(
            Jin10FlashMessage.is_key_event.is_(True),
            Jin10FlashMessage.analysis_processed.is_(False),
        )
        .order_by(Jin10FlashMessage.message_time.desc())
        .limit(limit)
    ).scalars().all()

    dispatched = 0
    skipped_non_analyzable = 0
    for msg in messages:
        if not _should_trigger_analysis(msg):
            msg.analysis_processed = True
            skipped_non_analyzable += 1
            continue

        ct = msg.content_type or "flash"

        if ct == "calendar":
            # 日历汇总只需标记处理，不需 AI 分析
            msg.analysis_processed = True
            skipped_non_analyzable += 1
            continue

        if ct == "flash":
            # 短快讯不需深度分析
            msg.analysis_processed = True
            skipped_non_analyzable += 1
            continue

        # article / report 创建分析任务
        task_type = "report_analysis" if ct == "report" else "flash_article_analysis"
        task_name = f"{'深度分析' if ct == 'report' else '快讯分析'}: {msg.content[:40]}"
        task = TaskRun(
            name=task_name,
            task_type=task_type,
            status=TaskStatus.pending,
            trade_date=msg.message_time.strftime("%Y-%m-%d") if msg.message_time else None,
        )
        session.add(task)
        session.flush()

        msg.analysis_processed = True
        msg.analysis_task_id = str(task.id)
        dispatched += 1

    if dispatched or skipped_non_analyzable:
        session.commit()
        logger.info(
            "Flash analysis dispatched: %d tasks, %d skipped (non-analyzable)",
            dispatched, skipped_non_analyzable,
        )

    return dispatched


def get_key_flash_messages(
    session: Session,
    since: datetime | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """查询重点快讯消息列表（供仪表盘 / 飞书消费）。"""
    stmt = select(Jin10FlashMessage).where(Jin10FlashMessage.is_key_event.is_(True))
    if since:
        stmt = stmt.where(Jin10FlashMessage.message_time >= since)
    stmt = stmt.order_by(Jin10FlashMessage.message_time.desc()).limit(limit)

    results = []
    for msg in session.scalars(stmt):
        results.append({
            "id": msg.id,
            "message_id": msg.message_id,
            "content": msg.content,
            "message_time": msg.message_time.isoformat() if msg.message_time else None,
            "importance": msg.importance,
            "signal_tags": msg.signal_tags.split(",") if msg.signal_tags else [],
            "filter_reason": msg.filter_reason,
            "analysis_task_id": msg.analysis_task_id,
            "analysis_processed": msg.analysis_processed,
        })
    return results


def get_flash_stats(session: Session) -> dict[str, Any]:
    """快讯统计：总数、key_event 数、最新消息时间。"""
    total = session.scalar(select(func.count()).select_from(Jin10FlashMessage)) or 0
    key_count = session.scalar(
        select(func.count()).where(Jin10FlashMessage.is_key_event.is_(True))
    ) or 0
    unanalyzed = session.scalar(
        select(func.count()).where(
            Jin10FlashMessage.is_key_event.is_(True),
            Jin10FlashMessage.analysis_processed.is_(False),
        )
    ) or 0
    latest = session.scalar(
        select(Jin10FlashMessage.message_time).order_by(
            Jin10FlashMessage.message_time.desc()
        ).limit(1)
    )

    return {
        "total": total,
        "key_events": key_count,
        "unanalyzed_key_events": unanalyzed,
        "latest_message_time": latest.isoformat() if latest else None,
    }
