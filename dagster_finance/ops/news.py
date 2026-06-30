"""Dagster ops for the news pipeline.

Wraps existing step functions from apps.worker.pipelines.news.
"""

from pathlib import Path
from typing import Any

from dagster import Config, Out, Output, op

from dagster_finance.ops.artifact_registration import register_dagster_output_artifacts
from apps.worker.pipelines.news import NewsPipelineState, run_news_step


class NewsConfig(Config):
    storage_root: str = "./storage"


@op(
    out={"state": Out(NewsPipelineState, description="Initialized news state")},
    tags={"pipeline": "news", "step": "init"},
)
def news_init_op(context) -> Output[NewsPipelineState]:
    state = NewsPipelineState()
    context.log.info("News pipeline state initialized")
    return Output(state, output_name="state")


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "news", "step": "news_collect"},
)
def news_collect_op(context, state: NewsPipelineState, config: NewsConfig) -> NewsPipelineState:
    storage = Path(config.storage_root)
    run_id = context.run_id
    context.log.info("Starting news_collect")
    summary = run_news_step(
        "news_collect", state,
        storage_root=storage, run_id=run_id, db_session=context.resources.db_session,
    )
    _register_news_artifacts(
        context,
        summary=summary,
        paths=[summary.get("artifact_path")],
        step_name="news_collect",
        task_kind="collect",
        state=state,
    )
    context.log.info(f"news_collect done: {summary.get('status', 'ok')}")
    return state


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "news", "step": "news_feature"},
)
def news_feature_op(context, state: NewsPipelineState, config: NewsConfig) -> NewsPipelineState:
    storage = Path(config.storage_root)
    run_id = context.run_id
    context.log.info("Starting news_feature")
    summary = run_news_step(
        "news_feature", state,
        storage_root=storage, run_id=run_id, db_session=context.resources.db_session,
    )
    _register_news_artifacts(
        context,
        summary=summary,
        paths=[
            summary.get("event_candidates_path"),
            summary.get("impact_assessments_path"),
            summary.get("daily_analysis_triggers_path"),
            summary.get("report_events_path"),
            summary.get("market_reactions_path"),
        ],
        step_name="news_feature",
        task_kind="feature",
        state=state,
    )
    context.log.info(f"news_feature done: {summary.get('status', 'ok')}")
    return state


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "news", "step": "news_brief"},
)
def news_brief_op(context, state: NewsPipelineState, config: NewsConfig) -> NewsPipelineState:
    storage = Path(config.storage_root)
    run_id = context.run_id
    context.log.info("Starting news_brief")
    summary = run_news_step(
        "news_brief", state,
        storage_root=storage, run_id=run_id, db_session=context.resources.db_session,
    )
    _register_news_artifacts(
        context,
        summary=summary,
        paths=[
            summary.get("daily_market_brief_path"),
            summary.get("daily_brief_input_snapshot_path"),
            summary.get("daily_brief_markdown_path"),
            summary.get("daily_brief_json_path"),
        ],
        step_name="news_brief",
        task_kind="render",
        state=state,
    )
    context.log.info(f"news_brief done: {summary.get('status', 'ok')}")
    return state


def _register_news_artifacts(
    context: Any,
    *,
    summary: dict[str, Any],
    paths: list[Any],
    step_name: str,
    task_kind: str,
    state: NewsPipelineState,
) -> None:
    if summary.get("status") not in {"success", "partial_success"}:
        return
    retrieved_date = str(summary.get("retrieved_date") or state.retrieved_date or "").strip()
    register_dagster_output_artifacts(
        context,
        db=context.resources.db_session,
        paths=[str(path) for path in paths if isinstance(path, str) and path],
        step_name=step_name,
        stage="news",
        task_kind=task_kind,
        source_refs=[ref for ref in state.source_refs if isinstance(ref, dict)],
        input_snapshot_ids={"news": f"news:{retrieved_date}:{context.run_id}"} if retrieved_date else None,
        snapshot_id=f"news:{retrieved_date}" if retrieved_date else None,
        trade_date=retrieved_date or None,
        json_artifact_type="feature_json",
    )
