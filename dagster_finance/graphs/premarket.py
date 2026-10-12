"""Dagster graphs composing the premarket pipeline sub-graphs.

Three independent sub-pipelines (macro, cme, news) run in parallel,
then their outputs merge into the analysis snapshot, which feeds the
canonical analysis pipeline.
"""

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dagster import Config, graph, op

from apps.runtime.source_controls import jin10_disabled
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
from dagster_finance.ops.premarket_gate import (
    premarket_readiness_gate_op,
    refresh_premarket_readiness_op,
)
from dagster_finance.ops.task_run_lifecycle import (
    premarket_task_run_complete_op,
    premarket_task_run_init_op,
)


_SHANGHAI = ZoneInfo("Asia/Shanghai")


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


def _open_formal_market_read_session() -> Any:
    """Open the dedicated read session used only by formal market materialization."""

    from database.models.engine import SessionLocal

    return SessionLocal()


def _load_formal_market_snapshot_bundle(*, trade_date: str, run_time: datetime) -> tuple[Any, str | None]:
    """Load formal market inputs, degrading to explicit empty snapshots on failure."""

    from apps.features.market_data.formal_snapshot_loader import (
        FormalSnapshotBundle,
        load_formal_market_snapshots,
        resolve_formal_snapshot_as_of,
    )
    from apps.features.market_data.formal_snapshots import (
        build_market_context_snapshot,
        build_market_price_snapshot,
        build_oil_snapshot,
    )

    session = None
    try:
        as_of = resolve_formal_snapshot_as_of(trade_date=trade_date, run_time=run_time, mode="latest_available")
        session = _open_formal_market_read_session()
        return load_formal_market_snapshots(session, as_of=as_of), None
    except Exception as exc:
        # A read/resolve failure must not silently substitute legacy market
        # data.  Empty formal contracts preserve the blocked/missing lineage.
        fallback_as_of = run_time.astimezone(timezone.utc)
        return (
            FormalSnapshotBundle(
                market_prices=build_market_price_snapshot(candidates=(), as_of=fallback_as_of),
                oil=build_oil_snapshot(candidates=(), as_of=fallback_as_of),
                as_of=fallback_as_of,
                market_context=build_market_context_snapshot(candidates=(), as_of=fallback_as_of),
            ),
            f"{type(exc).__name__}: formal market snapshot load failed",
        )
    finally:
        if session is not None:
            session.close()


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
    required_resource_keys={"db_session"},
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
    from apps.runtime.premarket_snapshot_authority import (
        canonicalize_premarket_snapshot_payload,
        stage_premarket_snapshot_authority,
    )

    context.log.info("Merging analysis snapshot from macro + cme + news")
    run_time = datetime.now(timezone.utc)

    macro_snapshot = getattr(macro_state, "snapshot_dict", None)
    options_snapshot = getattr(cme_state, "snapshot_dict", None)

    news_snapshot = getattr(news_state, "snapshot_dict", None) if news_state is not None else None
    trade_date = _resolve_analysis_trade_date(
        macro_snapshot=macro_snapshot,
        options_snapshot=options_snapshot,
        news_snapshot=news_snapshot,
        fallback_date=run_time.astimezone(_SHANGHAI).date(),
    )
    formal_bundle, formal_degraded_reason = _load_formal_market_snapshot_bundle(
        trade_date=trade_date,
        run_time=run_time,
    )
    if formal_degraded_reason:
        context.log.warning("Formal market snapshot load degraded: %s", formal_degraded_reason)

    source_refs = list(getattr(macro_state, "all_source_refs", []) or [])
    # CME source refs
    selected_cme_refs = (options_snapshot or {}).get("selected_source_refs", [])
    source_refs.extend(selected_cme_refs)
    raw_file = getattr(cme_state, "raw_file", None)
    if raw_file is not None and not selected_cme_refs:
        ref = {"source": "cme_daily_bulletin"}
        for attr in ("source_url", "raw_path", "sha256", "report_date"):
            val = getattr(raw_file, attr, None)
            if val is not None:
                ref[attr] = val
        source_refs.append(ref)
    if news_state is not None:
        source_refs.extend(getattr(news_state, "source_refs", []) or [])

    collected_points = list(getattr(macro_state, "warehouse_points", []))
    if jin10_disabled():
        gold_analysis_context = None
    else:
        from apps.analysis.jin10.daily_context import build_daily_analysis_context

        gold_analysis_context = build_daily_analysis_context(
            trade_date=trade_date,
            storage_root=Path(config.storage_root),
            asset="XAUUSD",
            preferred_run_id=context.run_id,
        )
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date=trade_date,
        run_id=context.run_id,
        macro_snapshot=macro_snapshot,
        options_snapshot=options_snapshot,
        source_refs=source_refs,
        collected_points=collected_points,
        news_snapshot=news_snapshot,
        gold_analysis_context=gold_analysis_context,
        market_price_snapshot=formal_bundle.market_prices,
        market_context_snapshot=formal_bundle.market_context,
        oil_snapshot=formal_bundle.oil,
        snapshot_time=run_time.isoformat(),
        disabled_sources=("jin10",) if jin10_disabled() else (),
        include_daily_research=True,
    )
    from apps.analysis.snapshots.report_continuity import load_and_attach_prior_report_contexts

    snapshot = load_and_attach_prior_report_contexts(
        context.resources.db_session, storage_root=Path(config.storage_root), snapshot=snapshot,
    )
    from apps.worker.adaptive_research import enrich_research_snapshot
    from apps.worker.cross_asset_research import enrich_cross_asset_snapshot
    from apps.worker.mainstream_news import enrich_mainstream_news_snapshot
    from apps.worker.fedwatch import enrich_fedwatch_snapshot

    snapshot = enrich_fedwatch_snapshot(snapshot, storage_root=Path(config.storage_root),
                                       db_session=context.resources.db_session)
    snapshot = enrich_cross_asset_snapshot(snapshot, storage_root=Path(config.storage_root), db_session=context.resources.db_session)
    snapshot = enrich_mainstream_news_snapshot(snapshot, storage_root=Path(config.storage_root))
    from apps.worker.execution_research import refresh_execution_snapshot
    from apps.analysis.snapshots.input_validation import prepare_analysis_inputs

    # Refresh the native spot evidence before deciding whether model research
    # has a trustworthy price observation to explain.
    snapshot = refresh_execution_snapshot(snapshot, storage_root=Path(config.storage_root), db_session=context.resources.db_session)
    snapshot = prepare_analysis_inputs(snapshot, storage_root=Path(config.storage_root))
    if snapshot.get("input_validation", {}).get("can_analyze") is True:
        snapshot = enrich_research_snapshot(snapshot, storage_root=Path(config.storage_root), evidence_review_enabled=True,
                                            db_session=context.resources.db_session)
        snapshot = refresh_execution_snapshot(snapshot, storage_root=Path(config.storage_root), db_session=context.resources.db_session)
    # Supplementary research may introduce stale, failed or future inputs.
    snapshot = prepare_analysis_inputs(snapshot, storage_root=Path(config.storage_root))
    from apps.analysis.snapshots.research_previous import load_previous_research
    from apps.features.research.workflow import build_gold_workflow

    previous_research = load_previous_research(context.resources.db_session, storage_root=Path(config.storage_root), snapshot=snapshot)
    from database.queries.market_state import load_accepted_state, stage_state_proposal

    accepted = load_accepted_state(context.resources.db_session, asset=snapshot["asset"], as_of=snapshot["snapshot_time"])
    if accepted.get("state_id"):
        snapshot["input_snapshot_ids"]["accepted_research_state"] = accepted["state_id"]
        snapshot["source_refs"].extend(accepted.get("source_refs", []))
    if previous_research.get("status") == "verified":
        snapshot["input_snapshot_ids"]["previous_research"] = previous_research["snapshot_id"]
        snapshot["source_refs"].extend(previous_research.get("source_refs", []))
    from apps.analysis.research_shadow import archive_research_versions

    snapshot["research_versions"] = archive_research_versions(Path(config.storage_root))
    snapshot["gold_workflow"] = build_gold_workflow(snapshot, previous=previous_research)
    from apps.features.research.production_shadow import apply_production_shadow_features

    snapshot["gold_workflow"] = apply_production_shadow_features(snapshot, snapshot["gold_workflow"])
    # Version new canonical runs explicitly; frozen historical readers remain
    # on their recorded v1/v2/v3 contract.
    snapshot["gold_workflow"]["reader_report_version"] = "gold_reader.v4"
    from apps.analysis.agents.research_input import RESEARCH_PRESENTATION_VERSION
    snapshot["gold_workflow"]["reader_presentation"] = RESEARCH_PRESENTATION_VERSION
    from apps.features.research.state import build_state_proposal
    proposal = build_state_proposal(snapshot, snapshot["gold_workflow"], accepted)
    snapshot["gold_workflow"]["state_record"] = proposal
    snapshot["gold_workflow"]["production_shadow"] = {"schema_version": "production_shadow.v1", "product": "Gold Research Agent v0.9 — Production Shadow", "automatic_acceptance": False, "automatic_trading_allowed": False}
    snapshot["gold_workflow"]["state"].update({k: proposal[k] for k in ("state_id", "accepted_state", "current_state", "previous_state", "transition_status", "transition_confirmed", "accepted_at", "predecessor_id", "missing_conditions", "confirmed_conditions", "trigger_conditions", "rule_validation")})
    snapshot["gold_workflow"]["state"]["reason"] = "S1–SX 候选已保存至研究状态账本；只有独立审阅接受操作可推进 Accepted。既有 Gold daily-close 状态契约保持独立，研究接受不授权交易。"
    snapshot = canonicalize_premarket_snapshot_payload(snapshot)
    snapshot = prepare_analysis_inputs(snapshot, storage_root=Path(config.storage_root))
    snapshot_path = write_analysis_snapshot(snapshot, storage_root=Path(config.storage_root))
    db = context.resources.db_session
    try:
        stage_premarket_snapshot_authority(
            db,
            run_id=context.run_id,
            snapshot=snapshot,
            snapshot_path=snapshot_path,
            storage_root=Path(config.storage_root),
        )
        stage_state_proposal(db, snapshot)
        from database.queries.data_source_status import upsert_data_source_status
        for health_item in snapshot["gold_workflow"]["core_source_health"]["items"]:
            upsert_data_source_status(db, {"source_key": health_item["source_key"], "source_name": health_item["source_key"], "source_group": "gold_core", "source_type": health_item.get("source_type", "official"), "access_method": health_item.get("access_method", "official_collector"),
                "configured": health_item["collector_status"] not in {"not_configured", "not_connected"}, "raw_ingested": bool(health_item.get("raw_path")), "parsed": bool(health_item.get("actual_latest_date")),
                "analysis_ready": health_item["source_health"] == "HEALTHY", "latest_snapshot_id": snapshot["snapshot_id"], "last_run_id": context.run_id,
                "status": "ready" if health_item["source_health"] == "HEALTHY" else "error", "error_message": health_item["reason"] if health_item["alert_required"] else None, "source_metadata": health_item})
            if health_item["alert_required"]:
                context.log.error("Core source health %s: %s", health_item["source_key"], health_item["reason"])
        db.commit()
    except Exception:
        db.rollback()
        raise
    context.log.info(
        f"Snapshot merged: trade_date={snapshot.get('trade_date')}, "
        f"snapshot_id={snapshot.get('snapshot_id', 'unknown')[:12]}, "
        f"path={snapshot_path}"
    )
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

    # Refresh readiness from this run's complete snapshot before gating agents.
    readiness_refresh = refresh_premarket_readiness_op(snapshot)
    readiness_gate = premarket_readiness_gate_op(snapshot, readiness_refresh)

    # Canonical analysis pipeline
    analysis_result = canonical_analysis_pipeline(snapshot, readiness_gate)
    premarket_task_run_complete_op(analysis_result)
