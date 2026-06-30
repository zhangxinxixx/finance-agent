"""Dagster ops for the CME pipeline.

Wraps existing step functions from apps.worker.pipelines.cme.
"""

from pathlib import Path
from typing import Any

from dagster import Config, Out, Output, op

from dagster_finance.ops.artifact_registration import register_dagster_output_artifacts
from apps.runtime.execution_event_bridge import emit_task_event
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
    if summary.get("status") == "success":
        task_id = register_dagster_output_artifacts(
            context,
            db=context.resources.db_session,
            paths=[summary.get("raw_path")],
            step_name="cme_download",
            stage="cme",
            task_kind="collect",
            source_refs=_cme_source_refs(state),
            input_snapshot_ids={"raw_file_sha256": summary.get("sha256")},
            trade_date=summary.get("report_date"),
            json_artifact_type="raw_file",
        )
        _emit_cme_timeline_event(
            context,
            task_id=task_id,
            event_type="SOURCE_COLLECTED",
            payload={
                "source": "cme_daily_bulletin",
                "raw_path": summary.get("raw_path"),
                "report_date": summary.get("report_date"),
                "sha256": summary.get("sha256"),
            },
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
    if summary.get("status") == "success":
        task_id = register_dagster_output_artifacts(
            context,
            db=context.resources.db_session,
            paths=[summary.get("parsed_path")],
            step_name="cme_parse",
            stage="cme",
            task_kind="parse",
            source_refs=_cme_source_refs(state),
            input_snapshot_ids=_cme_parse_input_snapshot_ids(state),
            trade_date=summary.get("trade_date"),
            json_artifact_type="parsed_file",
        )
        _emit_cme_timeline_event(
            context,
            task_id=task_id,
            event_type="DATA_PARSED",
            payload={
                "source": "cme_daily_bulletin",
                "parsed_path": summary.get("parsed_path"),
                "trade_date": summary.get("trade_date"),
                "detail_rows": summary.get("detail_rows"),
                "summary_rows": summary.get("summary_rows"),
            },
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
    if summary.get("status") == "success":
        task_id = register_dagster_output_artifacts(
            context,
            db=context.resources.db_session,
            paths=[summary.get("summary_path")],
            step_name="cme_ingest",
            stage="cme",
            task_kind="ingest",
            source_refs=_cme_source_refs(state),
            input_snapshot_ids=_cme_ingest_input_snapshot_ids(state),
            trade_date=summary.get("report_date"),
            json_artifact_type="feature_json",
        )
        ingest_result = state.ingest_result
        _emit_cme_timeline_event(
            context,
            task_id=task_id,
            event_type="FEATURE_COMPUTED",
            payload={
                "source": "cme_daily_bulletin",
                "summary_path": summary.get("summary_path"),
                "report_date": summary.get("report_date"),
                "detail_rows": ingest_result.detail_rows_count if ingest_result else None,
                "summary_rows": ingest_result.summary_rows_count if ingest_result else None,
                "total_rows": summary.get("total_rows"),
            },
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
    if summary.get("status") == "success":
        register_dagster_output_artifacts(
            context,
            db=context.resources.db_session,
            paths=[
                summary["json_path"],
                summary["md_path"],
                summary["visual_json_path"],
                summary["html_path"],
            ],
            step_name="option_wall",
            stage="cme",
            task_kind="analysis",
            source_refs=_option_wall_source_refs(state),
            input_snapshot_ids=summary.get("input_snapshot_ids"),
            snapshot_id=f"cme-options:{summary.get('trade_date')}",
            trade_date=summary.get("trade_date"),
            json_artifact_type="feature_json",
        )
    context.log.info(f"option_wall done: {summary.get('status', 'ok')}")
    return state


def _option_wall_source_refs(state: CmePipelineState) -> list[dict[str, str]]:
    return _cme_source_refs(state)


def _emit_cme_timeline_event(
    context: Any,
    *,
    task_id: str | None,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    if not task_id:
        return
    db = context.resources.db_session
    emit_task_event(
        db,
        run_id=str(context.run_id),
        task_id=task_id,
        event_type=event_type,
        payload=payload,
    )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        context.log.warning("Skipping CME timeline event commit for %s: %s", event_type, exc)


def _cme_source_refs(state: CmePipelineState) -> list[dict[str, str]]:
    if state.raw_file is None:
        return []
    return [
        {
            "source": "cme_daily_bulletin",
            "source_url": state.raw_file.source_url,
            "raw_path": state.raw_file.raw_path,
            "sha256": state.raw_file.sha256,
            "report_date": state.raw_file.report_date,
        }
    ]


def _cme_parse_input_snapshot_ids(state: CmePipelineState) -> dict[str, Any]:
    if state.raw_file is None:
        return {}
    return {"raw_file_sha256": state.raw_file.sha256}


def _cme_ingest_input_snapshot_ids(state: CmePipelineState) -> dict[str, Any]:
    input_ids = _cme_parse_input_snapshot_ids(state)
    if state.ingest_result is not None and state.ingest_result.parse_run_id:
        input_ids["parse_run_id"] = state.ingest_result.parse_run_id
    if state.ingest_result is not None and state.ingest_result.raw_file_id:
        input_ids["raw_file_id"] = state.ingest_result.raw_file_id
    return input_ids
