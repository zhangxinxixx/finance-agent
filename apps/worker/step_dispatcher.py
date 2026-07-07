from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

from database.models.task import StepStatus

logger = logging.getLogger(__name__)

CME_STEP_NAMES = {"cme_download", "cme_parse", "cme_ingest", "option_wall"}
MACRO_STEP_NAMES = {"macro_collect", "macro_feature", "report_render"}
NEWS_STEP_NAMES = {"news_collect", "news_feature", "news_brief"}


@dataclass(slots=True)
class StepDispatchState:
    cme: Any
    macro: Any
    news: Any


def create_step_dispatch_state() -> StepDispatchState:
    from apps.worker.pipelines.cme import CmePipelineState
    from apps.worker.pipelines.macro import MacroPipelineState
    from apps.worker.pipelines.news import NewsPipelineState

    return StepDispatchState(
        cme=CmePipelineState(),
        macro=MacroPipelineState(),
        news=NewsPipelineState(),
    )


def step_pipeline_name(step_name: str) -> str | None:
    if step_name in CME_STEP_NAMES:
        return "cme"
    if step_name in MACRO_STEP_NAMES:
        return "macro"
    if step_name in NEWS_STEP_NAMES:
        return "news"
    return None


def has_blocked_upstream_in_same_pipeline(ordered_steps: list[Any], step_index: int) -> bool:
    step_pipeline = step_pipeline_name(ordered_steps[step_index].name)
    if step_pipeline is None:
        return False

    return any(
        upstream.status in {StepStatus.failed, StepStatus.blocked}
        and step_pipeline_name(upstream.name) == step_pipeline
        for upstream in ordered_steps[:step_index]
    )


def dispatch_premarket_step(
    *,
    db: DBSession,
    step_name: str,
    state: StepDispatchState,
    storage_root: Path,
    run_id: str,
    product: str,
) -> dict[str, object] | None:
    if step_name in CME_STEP_NAMES:
        from apps.worker.pipelines import cme as cme_pipeline

        return cme_pipeline.run_cme_step(
            step_name,
            state.cme,
            db=db,
            storage_root=storage_root,
            run_id=run_id,
            product=product,
        )
    if step_name in MACRO_STEP_NAMES:
        from apps.worker.pipelines import macro as macro_pipeline

        return macro_pipeline.run_macro_step(
            step_name,
            state.macro,
            storage_root=storage_root,
            run_id=run_id,
            db_session=db,
        )
    if step_name in NEWS_STEP_NAMES:
        from apps.worker.pipelines import news as news_pipeline

        return news_pipeline.run_news_step(
            step_name,
            state.news,
            storage_root=storage_root,
            run_id=run_id,
            db_session=db,
        )

    logger.info("Step %s: stub - marking success", step_name)
    return None
