"""轻量 scheduler：在后台线程触发 premarket pipeline。MVP 单实例模式。"""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

_logger = logging.getLogger(__name__)


def dispatch_premarket_task(task_id: uuid.UUID, *, storage_root: Path = Path("./storage")) -> None:
    """在后台线程执行 premarket pipeline，不阻塞 API 响应。

    后续升级 Celery/APScheduler 时只需替换此函数内部，接口不变。
    """

    def _run() -> None:
        from apps.worker.runner import run_premarket
        from database.models.engine import SessionLocal

        _logger.info("premarket pipeline started task_id=%s", task_id)
        try:
            with SessionLocal() as db:
                status = run_premarket(db, task_id, storage_root=storage_root)
            _logger.info("premarket pipeline finished task_id=%s status=%s", task_id, status)
        except Exception as exc:
            _logger.error("premarket pipeline crashed task_id=%s error=%s", task_id, exc, exc_info=True)

    thread = threading.Thread(target=_run, daemon=True, name=f"premarket-{task_id}")
    thread.start()


def dispatch_daily_analysis_followup_task(task_id: uuid.UUID, *, storage_root: Path = Path("./storage")) -> None:
    """在后台线程执行单个 daily_analysis_followup task 的 worker consumer。"""

    def _run() -> None:
        from apps.worker.pipelines.daily_analysis_followup import run_daily_analysis_followup_task
        from database.models.engine import SessionLocal

        _logger.info("daily analysis follow-up worker started task_id=%s", task_id)
        try:
            with SessionLocal() as db:
                status = run_daily_analysis_followup_task(db, task_id, storage_root=storage_root)
            _logger.info("daily analysis follow-up worker finished task_id=%s status=%s", task_id, status)
        except Exception as exc:
            _logger.error("daily analysis follow-up worker crashed task_id=%s error=%s", task_id, exc, exc_info=True)

    thread = threading.Thread(target=_run, daemon=True, name=f"daily-analysis-followup-{task_id}")
    thread.start()
