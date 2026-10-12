"""已退役的线程调度器兼容模块。

正式任务只能由 API 触发 Dagster job，再由 Dagster worker 执行。这个
模块保留函数名以避免仓库外旧调用在导入阶段直接失败，但不再创建线程、
打开数据库会话或执行 worker。
"""

from __future__ import annotations

import uuid
from pathlib import Path


class LegacySchedulerDispatchDisabled(RuntimeError):
    """Raised when a retired thread-based scheduler entry is called."""


_PREMARKET_DISABLED_MESSAGE = (
    "旧线程调度入口已退役；请通过 API /api/tasks/premarket 进入 Dagster premarket_job。"
)
_FOLLOWUP_DISABLED_MESSAGE = "旧线程调度入口已退役；daily_analysis_followup 必须由正式 Dagster job 接管。"


def dispatch_premarket_task(task_id: uuid.UUID, *, storage_root: Path = Path("./storage")) -> None:
    """Retired compatibility symbol; never execute a second premarket runner."""
    del task_id, storage_root
    raise LegacySchedulerDispatchDisabled(_PREMARKET_DISABLED_MESSAGE)


def dispatch_daily_analysis_followup_task(task_id: uuid.UUID, *, storage_root: Path = Path("./storage")) -> None:
    """Retired compatibility symbol; follow-up tasks must get a formal job."""
    del task_id, storage_root
    raise LegacySchedulerDispatchDisabled(_FOLLOWUP_DISABLED_MESSAGE)
