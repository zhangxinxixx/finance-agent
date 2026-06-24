"""Dagster ops for the macro pipeline.

Wraps existing step functions from apps.worker.pipelines.macro.
"""

from pathlib import Path

from dagster import Config, Out, Output, op

from apps.worker.pipelines.macro import MacroPipelineState, run_macro_step


class MacroConfig(Config):
    storage_root: str = "./storage"


@op(
    out={"state": Out(MacroPipelineState, description="Initialized macro state")},
    tags={"pipeline": "macro", "step": "init"},
)
def macro_init_op(context) -> Output[MacroPipelineState]:
    state = MacroPipelineState()
    context.log.info("Macro pipeline state initialized")
    return Output(state, output_name="state")


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "macro", "step": "macro_collect"},
)
def macro_collect_op(context, state: MacroPipelineState, config: MacroConfig) -> MacroPipelineState:
    storage = Path(config.storage_root)
    db = context.resources.db_session
    run_id = context.run_id
    context.log.info("Starting macro_collect")
    summary = run_macro_step(
        "macro_collect", state,
        storage_root=storage, run_id=run_id, db_session=db,
    )
    context.log.info(f"macro_collect done: {summary.get('status', 'ok')}")
    return state


@op(
    tags={"pipeline": "macro", "step": "macro_feature"},
)
def macro_feature_op(context, state: MacroPipelineState, config: MacroConfig) -> MacroPipelineState:
    storage = Path(config.storage_root)
    run_id = context.run_id
    context.log.info("Starting macro_feature")
    summary = run_macro_step(
        "macro_feature", state,
        storage_root=storage, run_id=run_id,
    )
    context.log.info(f"macro_feature done: {summary.get('status', 'ok')}")
    return state


@op(
    tags={"pipeline": "macro", "step": "report_render"},
)
def report_render_op(context, state: MacroPipelineState, config: MacroConfig) -> MacroPipelineState:
    storage = Path(config.storage_root)
    run_id = context.run_id
    context.log.info("Starting report_render")
    summary = run_macro_step(
        "report_render", state,
        storage_root=storage, run_id=run_id,
    )
    context.log.info(f"report_render done: {summary.get('status', 'ok')}")
    return state
