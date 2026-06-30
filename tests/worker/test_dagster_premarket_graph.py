from __future__ import annotations

from types import SimpleNamespace

from dagster_finance.graphs.premarket import build_market_state_op
from dagster_finance.jobs.premarket_job import premarket_job


def _snapshot() -> dict:
    return {
        "version": "1.0",
        "snapshot_id": "XAUUSD:2026-05-14:run-001",
        "asset": "XAUUSD",
        "trade_date": "2026-05-14",
        "run_id": "run-001",
        "input_snapshot_ids": {"macro": "macro:2026-05-14:run-001"},
        "macro": {"status": "available", "data": {"indicators": {"DGS10": {"value": 4.3}}}},
        "options": {"status": "unavailable", "reason": "input_not_available"},
        "technical": {"status": "unavailable", "reason": "no_xauusd_collected_points"},
        "positioning": {"status": "unavailable", "reason": "no_cot_gold_collected_points"},
        "news": {"status": "unavailable", "reason": "no_news_collected_points"},
        "market_odds": {"status": "unavailable", "reason": "input_not_available"},
        "source_refs": [{"source": "fred", "symbol": "DGS10"}],
    }


def test_build_market_state_op_rebuilds_market_state_from_snapshot() -> None:
    context = SimpleNamespace(log=SimpleNamespace(info=lambda *_args, **_kwargs: None))

    result = build_market_state_op.compute_fn.decorated_fn(context, _snapshot())

    assert result["version"] == "1.0"
    assert result["snapshot_id"] == "XAUUSD:2026-05-14:run-001"
    assert result["macro"]["status"] == "available"
    assert result["options"]["status"] == "unavailable"
    assert result["data_completeness"]["available_modules"] == ["macro"]
    assert result["data_completeness"]["coverage_ratio"] == 0.167
    assert result["source_quality"]["sources"] == ["fred"]


def test_premarket_graph_includes_market_state_between_snapshot_and_c4() -> None:
    premarket = premarket_job.graph.node_defs[0]
    node_names = [node.name for node in premarket.node_defs]
    dependencies = premarket.dependencies

    assert "build_market_state_op" in node_names
    assert node_names.index("merge_analysis_snapshot_op") < node_names.index("build_market_state_op")
    assert node_names.index("build_market_state_op") < node_names.index("c4_agent_pipeline")
    market_state_invocation = next(key for key in dependencies if key.name == "build_market_state_op")
    c4_invocation = next(key for key in dependencies if key.name == "c4_agent_pipeline")
    assert dependencies[market_state_invocation]["snapshot"].node == "merge_analysis_snapshot_op"
    assert dependencies[c4_invocation]["snapshot"].node == "merge_analysis_snapshot_op"
