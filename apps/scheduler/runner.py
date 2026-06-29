"""轻量 scheduler：在后台线程触发 premarket pipeline。MVP 单实例模式。"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from pathlib import Path

_logger = logging.getLogger(__name__)
ENABLE_LEGACY_PREMARKET_WORKER_ENV = "FINANCE_AGENT_ENABLE_LEGACY_PREMARKET_WORKER"


class LegacyPremarketDispatchDisabled(RuntimeError):
    """Raised when production code tries to dispatch the legacy premarket worker."""


def dispatch_premarket_task(task_id: uuid.UUID, *, storage_root: Path = Path("./storage")) -> None:
    """Compatibility-only legacy premarket dispatch.

    Production premarket execution is Dagster `premarket_job`. This local
    worker path remains available only when explicitly enabled for debug runs.
    """
    if os.getenv(ENABLE_LEGACY_PREMARKET_WORKER_ENV) != "1":
        raise LegacyPremarketDispatchDisabled(
            "Legacy premarket worker dispatch is disabled; use Dagster premarket_job via API launch."
        )

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
