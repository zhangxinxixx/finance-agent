"""Dagster graphs composing the premarket pipeline sub-graphs.

Three independent sub-pipelines (macro, cme, news) run in parallel,
then their outputs merge into the analysis snapshot, which feeds the
C4 agent pipeline.
"""

from typing import Any

from dagster import graph, op

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
    cme_options_agent_op,
    coordinator_op,
    final_report_op,
    macro_liquidity_agent_op,
    market_odds_agent_op,
    news_agent_op,
    positioning_agent_op,
    risk_agent_op,
    strategy_card_op,
    technical_agent_op,
)


# ── Macro sub-pipeline ──────────────────────────────────────────

@graph(
    name="macro_pipeline",
    description="Macro data collection → feature engineering → report rendering",
)
def macro_pipeline():
    state = macro_init_op()
    state = macro_collect_op(state)
    state = macro_feature_op(state)
    state = report_render_op(state)
    return state


# ── CME sub-pipeline ────────────────────────────────────────────

@graph(
    name="cme_pipeline",
    description="CME PDF download → parse → ingest → options analysis",
)
def cme_pipeline():
    state = cme_init_op()
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
def news_pipeline():
    state = news_init_op()
    state = news_collect_op(state)
    state = news_feature_op(state)
    state = news_brief_op(state)
    return state


# ── Merge snapshot op ───────────────────────────────────────────

@op(
    tags={"pipeline": "premarket", "step": "merge_snapshot"},
)
def merge_analysis_snapshot_op(
    context,
    macro_state: Any,
    cme_state: Any,
    news_state: Any,
) -> dict[str, Any]:
    """Merge the three pipeline states into a unified analysis snapshot."""
    from apps.analysis.snapshots.builder import build_analysis_snapshot
    from datetime import datetime, timezone
    context.log.info("Merging analysis snapshot from macro + cme + news")

    macro_snapshot = getattr(macro_state, "snapshot_dict", None)
    options_snapshot = getattr(cme_state, "snapshot_dict", None)

    # Resolve trade_date: prefer options, then macro, then today
    trade_date = None
    if options_snapshot and options_snapshot.get("trade_date"):
        trade_date = str(options_snapshot["trade_date"])
    elif macro_snapshot and macro_snapshot.get("as_of"):
        trade_date = str(macro_snapshot["as_of"])
    else:
        trade_date = datetime.now(timezone.utc).date().isoformat()

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
    news_snapshot = getattr(news_state, "snapshot_dict", None) if news_state is not None else None

    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date=trade_date,
        run_id=context.run_id,
        macro_snapshot=macro_snapshot,
        options_snapshot=options_snapshot,
        source_refs=source_refs,
        collected_points=collected_points,
        news_snapshot=news_snapshot,
    )
    context.log.info(f"Snapshot merged: trade_date={snapshot.get('trade_date')}, "
                     f"snapshot_id={snapshot.get('snapshot_id', 'unknown')[:12]}")
    return snapshot


# ── C4 agent sub-pipeline ───────────────────────────────────────

@graph(
    name="c4_agent_pipeline",
    description="C3 agents (parallel) → coordinator → strategy card",
)
def c4_agent_pipeline(snapshot: dict[str, Any]):
    # C3 agents run in parallel where possible
    macro_out = macro_liquidity_agent_op(snapshot)
    options_out = cme_options_agent_op(snapshot)
    risk_out = risk_agent_op(snapshot, macro_out, options_out)
    tech_out = technical_agent_op(snapshot)
    pos_out = positioning_agent_op(snapshot)
    news_out = news_agent_op(snapshot)
    odds_out = market_odds_agent_op(snapshot)

    # Coordinator aggregates all agent outputs
    coord_out = coordinator_op(
        snapshot, macro_out, options_out, risk_out,
        tech_out, pos_out, news_out, odds_out,
    )

    final_report_op(
        snapshot,
        macro_out,
        options_out,
        risk_out,
        tech_out,
        pos_out,
        news_out,
        coord_out,
    )

    # Strategy card
    card = strategy_card_op(snapshot, coord_out, risk_out)
    return card


# ── Full premarket graph ────────────────────────────────────────

@graph(
    name="premarket",
    description="Full premarket pipeline: macro ∥ cme ∥ news → snapshot → C4 agents → strategy card",
)
def premarket_graph():
    # Three independent sub-pipelines run in parallel (Dagster resolves deps)
    macro_state = macro_pipeline()
    cme_state = cme_pipeline()
    news_state = news_pipeline()

    # Merge into unified snapshot
    snapshot = merge_analysis_snapshot_op(macro_state, cme_state, news_state)

    # C4 agent pipeline
    c4_agent_pipeline(snapshot)
