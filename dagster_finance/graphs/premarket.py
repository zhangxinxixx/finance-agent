"""Dagster graphs composing the premarket pipeline sub-graphs.

Three independent sub-pipelines (macro, cme, news) run in parallel,
then their outputs merge into the analysis snapshot, which feeds the
canonical analysis pipeline.
"""

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from dagster import Config, graph, op

from dagster_finance.ops.macro import (
    macro_collect_op,
    macro_feature_op,
    macro_init_op,
    report_render_op,
)
from dagster_finance.ops.cme import (
    cme_download_op,
    cme_ingest_op,
    cme_init_op,
    cme_parse_op,
    option_wall_op,
)
from dagster_finance.ops.news import (
    news_collect_op,
    news_feature_op,
    news_init_op,
    news_brief_op,
)
from dagster_finance.ops.agents import (
    canonical_composite_analysis_op,
)
from dagster_finance.ops.premarket_gate import premarket_readiness_gate_op
from dagster_finance.ops.task_run_lifecycle import (
    premarket_task_run_complete_op,
    premarket_task_run_init_op,
)


# ── Macro sub-pipeline ──────────────────────────────────────────

@graph(
    name="macro_pipeline",
    description="Macro data collection → feature engineering → report rendering",
)
def macro_pipeline(task_run_ready):
    state = macro_init_op(task_run_ready=task_run_ready)
    state = macro_collect_op(state)
    state = macro_feature_op(state)
    state = report_render_op(state)
    return state


# ── CME sub-pipeline ────────────────────────────────────────────

@graph(
    name="cme_pipeline",
    description="CME PDF download → parse → ingest → options analysis",
)
def cme_pipeline(task_run_ready):
    state = cme_init_op(task_run_ready=task_run_ready)
    state = cme_download_op(state)
    state = cme_parse_op(state)
    state = cme_ingest_op(state)
    state = option_wall_op(state)
    return state


# ── News sub-pipeline ───────────────────────────────────────────

@graph(
    name="news_pipeline",
    description="News collection → feature extraction → daily brief",
)
def news_pipeline(task_run_ready):
    state = news_init_op(task_run_ready=task_run_ready)
    state = news_collect_op(state)
    state = news_feature_op(state)
    state = news_brief_op(state)
    return state


# ── Merge snapshot op ───────────────────────────────────────────

class MergeSnapshotConfig(Config):
    storage_root: str = "./storage"


def _resolve_analysis_trade_date(
    *,
    macro_snapshot: dict[str, Any] | None,
    options_snapshot: dict[str, Any] | None,
    news_snapshot: dict[str, Any] | None,
    fallback_date: date,
) -> str:
    """Use the freshest source anchor as the analysis context date."""

    candidates: list[Any] = [
        macro_snapshot.get("as_of") if macro_snapshot else None,
        options_snapshot.get("trade_date") if options_snapshot else None,
    ]
    if news_snapshot:
        daily_market_brief = news_snapshot.get("daily_market_brief")
        if isinstance(daily_market_brief, dict):
            candidates.append(daily_market_brief.get("as_of"))
        daily_brief_input = news_snapshot.get("daily_brief_input_snapshot")
        if isinstance(daily_brief_input, dict):
            candidates.append(daily_brief_input.get("retrieved_date"))

    resolved: list[date] = []
    for value in candidates:
        if not isinstance(value, str):
            continue
        try:
            resolved.append(date.fromisoformat(value[:10]))
        except ValueError:
            continue
    return max(resolved, default=fallback_date).isoformat()

@op(
    tags={"pipeline": "premarket", "step": "merge_snapshot"},
)
def merge_analysis_snapshot_op(
    context,
    config: MergeSnapshotConfig,
    macro_state: Any,
    cme_state: Any,
    news_state: Any,
) -> dict[str, Any]:
    """Merge the three pipeline states into a unified analysis snapshot."""
    from apps.analysis.snapshots.builder import build_analysis_snapshot, write_analysis_snapshot
    from apps.analysis.jin10.daily_context import build_daily_analysis_context

    context.log.info("Merging analysis snapshot from macro + cme + news")

    macro_snapshot = getattr(macro_state, "snapshot_dict", None)
    options_snapshot = getattr(cme_state, "snapshot_dict", None)

    news_snapshot = getattr(news_state, "snapshot_dict", None) if news_state is not None else None
    trade_date = _resolve_analysis_trade_date(
        macro_snapshot=macro_snapshot,
        options_snapshot=options_snapshot,
        news_snapshot=news_snapshot,
        fallback_date=datetime.now(timezone.utc).date(),
    )

    source_refs = list(getattr(macro_state, "all_source_refs", []) or [])
    # CME source refs
    raw_file = getattr(cme_state, "raw_file", None)
    if raw_file is not None:
        ref = {"source": "cme_daily_bulletin"}
        for attr in ("source_url", "raw_path", "sha256", "report_date"):
            val = getattr(raw_file, attr, None)
            if val is not None:
                ref[attr] = val
        source_refs.append(ref)
    if news_state is not None:
        source_refs.extend(getattr(news_state, "source_refs", []) or [])

    collected_points = [p.to_dict() for p in getattr(macro_state, "all_points", [])]
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date=trade_date,
        run_id=context.run_id,
        macro_snapshot=macro_snapshot,
        options_snapshot=options_snapshot,
        source_refs=source_refs,
        collected_points=collected_points,
        news_snapshot=news_snapshot,
        gold_analysis_context=build_daily_analysis_context(
            trade_date=trade_date,
            storage_root=Path(config.storage_root),
            asset="XAUUSD",
            preferred_run_id=context.run_id,
        ),
    )
    snapshot_path = write_analysis_snapshot(snapshot, storage_root=Path(config.storage_root))
    context.log.info(f"Snapshot merged: trade_date={snapshot.get('trade_date')}, "
                     f"snapshot_id={snapshot.get('snapshot_id', 'unknown')[:12]}, "
                     f"path={snapshot_path}")
    return snapshot


# ── Canonical analysis sub-pipeline ─────────────────────────────

@graph(
    name="canonical_analysis_pipeline",
    description="Canonical domain agents → FactReview → QualityGate/fallback → accepted report/card",
)
def canonical_analysis_pipeline(snapshot: dict[str, Any], readiness_gate: dict[str, Any]):
    return canonical_composite_analysis_op(snapshot, readiness_gate)


# ── Full premarket graph ────────────────────────────────────────

@graph(
    name="premarket",
    description="Full premarket pipeline: macro ∥ cme ∥ news → snapshot → canonical analysis → strategy card",
)
def premarket_graph():
    task_run_ready = premarket_task_run_init_op()
    # Three independent sub-pipelines run in parallel (Dagster resolves deps)
    macro_state = macro_pipeline(task_run_ready)
    cme_state = cme_pipeline(task_run_ready)
    news_state = news_pipeline(task_run_ready)

    # Merge into unified snapshot
    snapshot = merge_analysis_snapshot_op(macro_state, cme_state, news_state)

    # Domain agents may only start after the current readiness artifact passes.
    readiness_gate = premarket_readiness_gate_op(snapshot)

    # Canonical analysis pipeline
    analysis_result = canonical_analysis_pipeline(snapshot, readiness_gate)
    premarket_task_run_complete_op(analysis_result)
