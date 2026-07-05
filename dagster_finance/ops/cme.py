"""Dagster ops for the CME pipeline.

Wraps existing step functions from apps.worker.pipelines.cme.
"""

from pathlib import Path

from dagster import Config, Out, Output, op

from apps.worker.pipelines.cme import CmePipelineState, run_cme_step


class CmeConfig(Config):
    storage_root: str = "./storage"


@op(
    out={"state": Out(CmePipelineState, description="Initialized CME state")},
    tags={"pipeline": "cme", "step": "init"},
)
def cme_init_op(context) -> Output[CmePipelineState]:
    state = CmePipelineState()
    context.log.info("CME pipeline state initialized")
    return Output(state, output_name="state")


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "cme", "step": "cme_download"},
)
def cme_download_op(context, state: CmePipelineState, config: CmeConfig) -> CmePipelineState:
    storage = Path(config.storage_root)
    run_id = context.run_id
    context.log.info("Starting cme_download")
    summary = run_cme_step(
        "cme_download", state,
        db=context.resources.db_session, storage_root=storage, run_id=run_id,
    )
    context.log.info(f"cme_download done: {summary.get('status', 'ok')}")
    return state


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "cme", "step": "cme_parse"},
)
def cme_parse_op(context, state: CmePipelineState, config: CmeConfig) -> CmePipelineState:
    storage = Path(config.storage_root)
    run_id = context.run_id
    context.log.info("Starting cme_parse")
    summary = run_cme_step(
        "cme_parse", state,
        db=context.resources.db_session, storage_root=storage, run_id=run_id,
    )
    context.log.info(f"cme_parse done: {summary.get('status', 'ok')}")
    return state


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "cme", "step": "cme_ingest"},
)
def cme_ingest_op(context, state: CmePipelineState, config: CmeConfig) -> CmePipelineState:
    storage = Path(config.storage_root)
    run_id = context.run_id
    context.log.info("Starting cme_ingest")
    summary = run_cme_step(
        "cme_ingest", state,
        storage_root=storage, run_id=run_id, db=context.resources.db_session,
    )
    context.log.info(f"cme_ingest done: {summary.get('status', 'ok')}")
    return state


@op(
    required_resource_keys={"db_session"},
    tags={"pipeline": "cme", "step": "option_wall"},
)
def option_wall_op(context, state: CmePipelineState, config: CmeConfig) -> CmePipelineState:
    storage = Path(config.storage_root)
    run_id = context.run_id
    context.log.info("Starting option_wall")
    summary = run_cme_step(
        "option_wall", state,
        storage_root=storage, run_id=run_id, db=context.resources.db_session,
    )
    context.log.info(f"option_wall done: {summary.get('status', 'ok')}")
    return state
