"""Dagster op for explicitly selected daily-analysis follow-up tasks."""

from pathlib import Path
from typing import Any

from dagster import Config, op

from apps.worker.pipelines.daily_analysis_followup import (
    FOLLOWUP_MAX_STAGE_STEPS,
    run_selected_daily_analysis_followup_tasks,
)


class DailyAnalysisFollowupConfig(Config):
    """Run configuration supplied by the API for one explicit task batch."""

    task_ids: list[str]
    storage_root: str = "./storage"
    max_stage_steps: int = FOLLOWUP_MAX_STAGE_STEPS


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "daily_analysis_followup", "task_scope": "explicit_ids"},
)
def daily_analysis_followup_op(context, config: DailyAnalysisFollowupConfig) -> dict[str, Any]:
    if not config.task_ids:
        return {
            "status": "empty",
            "requested_count": 0,
            "unique_task_count": 0,
            "processed_count": 0,
            "results": [],
        }
    result = run_selected_daily_analysis_followup_tasks(
        context.resources.db_session,
        config.task_ids,
        storage_root=Path(config.storage_root),
        max_stage_steps=config.max_stage_steps,
    )
    context.log.info(
        "Daily analysis follow-up batch finished: requested=%s processed=%s",
        result.get("requested_count", 0),
        result.get("processed_count", 0),
    )
    return result
