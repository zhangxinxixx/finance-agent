"""Dagster ops for the news pipeline.

Wraps existing step functions from apps.worker.pipelines.news.
"""

from pathlib import Path

from dagster import Config, Out, Output, op

from apps.worker.pipelines.news import NewsPipelineState, run_news_step
from dagster_finance.ops.summary_status import raise_for_failed_summary


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
    context.log.info(f"news_collect done: {summary.get('status', 'ok')}")
    raise_for_failed_summary("news_collect", summary)
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
    context.log.info(f"news_feature done: {summary.get('status', 'ok')}")
    raise_for_failed_summary("news_feature", summary)
    return state


@op(
    tags={"pipeline": "news", "step": "news_brief"},
)
def news_brief_op(context, state: NewsPipelineState, config: NewsConfig) -> NewsPipelineState:
    storage = Path(config.storage_root)
    run_id = context.run_id
    context.log.info("Starting news_brief")
    summary = run_news_step(
        "news_brief", state,
        storage_root=storage, run_id=run_id,
    )
    context.log.info(f"news_brief done: {summary.get('status', 'ok')}")
    raise_for_failed_summary("news_brief", summary)
    return state
