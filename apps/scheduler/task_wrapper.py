"""为 Jin10 定时刷新函数添加 TaskRecorder 包装。

使 APScheduler 的 background job 在执行时自动写入 task_runs 表，
供调度中心页面消费。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apps.runtime.task_recorder import TaskRecorder

logger = logging.getLogger(__name__)

# 最多每 N 秒记录一次同类刷新任务
# 高频采集任务做限频采样，避免 task_runs 被 1 分钟级刷新刷满。
_RECORD_INTERVAL_SECONDS: dict[str, int] = {
    "jin10_quotes": 900,
    "jin10_kline": 900,
    "market_candles_daily": 3600,
    "jin10_calendar": 3600,
    "jin10_flash": 900,
}

_last_record_time: dict[str, float] = {}


def _should_record(task_key: str) -> bool:
    """按任务类型限频记录 task_runs。"""
    now = datetime.now(timezone.utc).timestamp()
    interval = _RECORD_INTERVAL_SECONDS.get(task_key, 300)
    if task_key in _last_record_time:
        if now - _last_record_time[task_key] < interval:
            return False
    _last_record_time[task_key] = now
    return True


def record_jin10_refresh(task_key: str, task_name: str, fn, *args, **kwargs):
    """包装 Jin10 刷新函数，将执行结果记录到 task_runs。

    task_key: 用于去重（如 'jin10_quotes'）
    task_name: 显示在调度中心的任务名
    fn: 原始刷新函数
    """
    # 先执行 fn，不改变原有逻辑
    fn(*args, **kwargs)

    # 仅在需要时记录
    if not _should_record(task_key):
        return

    try:
        with TaskRecorder(
            task_type=f"jin10_refresh_{task_key}",
            task_name=task_name,
            trade_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        ) as rec:
            rec.step(f"refresh_{task_key}", status="success")
    except Exception as exc:
        logger.debug("Failed to record Jin10 refresh task: %s", exc)
