from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from dagster import build_op_context
import pytest

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
from dagster_finance.graphs.premarket import (
    MergeSnapshotConfig,
    canonical_analysis_pipeline,
    merge_analysis_snapshot_op,
    premarket_graph,
)
from dagster_finance.ops.agents import (
    AgentConfig,
    canonical_composite_analysis_op,
    final_report_op,
    strategy_card_op,
)

_CREATED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)


def _allow_readiness_gate() -> dict[str, object]:
    return {
        "decision": "allow",
        "trade_date": "2026-05-14",
        "source_ref": "monitoring/2026-05-14/downstream_readiness.json",
        "reason_code": None,
    }


def _snapshot() -> dict[str, object]:
    return {
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "run_id": "run-card-test",
        "input_snapshot_ids": {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "macro": "macro:2026-05-14",
            "options": "cme-options:2026-05-14",
        },
        "metadata": {
            "symbol": "XAUUSD",
            "as_of": "2026-05-14",
            "unavailable_modules": [],
        },
        "source_refs": [{"source": "analysis_snapshot", "snapshot_id": "XAUUSD:2026-05-14:analysis"}],
    }


def _agent_output(*, module: str, agent_name: str) -> AgentOutput:
    return AgentOutput(
        version="1.0",
        agent_name=agent_name,
        module=module,
        snapshot_id=f"{module}:2026-05-14",
        input_snapshot_ids={module: f"{module}:2026-05-14"},
        bias=AgentBias.BULLISH,
        confidence=0.70,
        key_findings=["Options prior finding: Call wall near 2450"],
        risk_points=[f"{module} risk point"],
        watchlist=["DXY"],
        invalid_conditions=[f"{module} invalid condition"],
        summary=f"{module} summary",
        source_refs=[{"source": module, "snapshot_id": f"{module}:2026-05-14"}],
        status=AgentStatus.SUCCESS,
        created_at=_CREATED_AT,
    )


def test_strategy_card_op_coerces_dagster_dict_payloads() -> None:
    coordinator_output = _agent_output(module="coordinator", agent_name="coordinator_agent")
    risk_output = _agent_output(module="risk", agent_name="risk_agent")

    with patch("apps.output.final_report.write_strategy_card", return_value={"ok": True}) as write_mock:
        result = strategy_card_op(
            build_op_context(resources={"db_session": object()}),
            snapshot=_snapshot(),
            coordinator_output=coordinator_output.model_dump(mode="json"),
            risk_output=risk_output.model_dump(mode="json"),
        )

    assert result == {"ok": True}
    card = write_mock.call_args.kwargs["card"]
    assert card.bias == AgentBias.BULLISH
    assert card.confidence == 0.70
    assert any("Call wall near 2450" in level for level in card.key_levels_from_options)


def test_dagster_canonical_analysis_graph_delegates_only_to_composite_pipeline() -> None:
    assert {node.name for node in canonical_analysis_pipeline.node_defs} == {"canonical_composite_analysis_op"}


def test_premarket_graph_contains_readiness_gate_before_canonical_analysis_subgraph() -> None:
    node_names = {node.name for node in premarket_graph.node_defs}
    assert {
        "premarket_task_run_init_op",
        "premarket_readiness_gate_op",
        "canonical_analysis_pipeline",
        "premarket_task_run_complete_op",
    } <= node_names
    for pipeline_name in ("macro_pipeline", "cme_pipeline", "news_pipeline"):
        pipeline_dependencies = next(
            dependencies
            for invocation, dependencies in premarket_graph.dependencies.items()
            if invocation.name == pipeline_name
        )
        assert pipeline_dependencies["task_run_ready"].node == "premarket_task_run_init_op"
    analysis_dependencies = next(
        dependencies
        for invocation, dependencies in premarket_graph.dependencies.items()
        if invocation.name == "canonical_analysis_pipeline"
    )
    assert analysis_dependencies["readiness_gate"].node == "premarket_readiness_gate_op"
    completion_dependencies = next(
        dependencies
        for invocation, dependencies in premarket_graph.dependencies.items()
        if invocation.name == "premarket_task_run_complete_op"
    )
    assert completion_dependencies["analysis_result"].node == "canonical_analysis_pipeline"


def test_dagster_merge_prefers_current_run_analysis_context(tmp_path) -> None:
    context = build_op_context()
    macro_state = SimpleNamespace(
        snapshot_dict={"as_of": "2026-07-21"},
        all_source_refs=[],
        all_points=[],
    )
    cme_state = SimpleNamespace(
        snapshot_dict={"trade_date": "2026-07-20"},
        raw_file=None,
    )
    news_state = SimpleNamespace(
        snapshot_dict={"daily_market_brief": {"as_of": "2026-07-21T10:00:00+00:00"}},
        source_refs=[],
    )
    with (
        patch(
            "apps.analysis.jin10.daily_context.build_daily_analysis_context",
            return_value={"status": "ready"},
        ) as context_mock,
        patch(
            "apps.analysis.snapshots.builder.build_analysis_snapshot",
            return_value={"trade_date": "2026-07-21", "snapshot_id": "XAUUSD:test"},
        ),
        patch(
            "apps.analysis.snapshots.builder.write_analysis_snapshot",
            return_value=tmp_path / "premarket_snapshot.json",
        ),
    ):
        merge_analysis_snapshot_op(
            context,
            MergeSnapshotConfig(storage_root=str(tmp_path)),
            macro_state,
            cme_state,
            news_state,
        )

    assert context_mock.call_args.kwargs["preferred_run_id"] == context.run_id


def test_canonical_composite_analysis_op_delegates_to_gated_pipeline() -> None:
    fake_outputs = {
        "quality_gate_decision": {"action": "pass"},
        "agent_loop_decision": {"decision": "passed"},
        "report_result": {"paths": ["final_report.md"]},
        "card_result": {"paths": ["strategy_card.json"]},
    }
    fake_summaries = {"final_report": {"output_mode": "accepted"}}
    with patch(
        "apps.worker.composite_analysis_pipeline.run_composite_analysis_pipeline",
        return_value=(fake_summaries, fake_outputs),
    ) as canonical_mock:
        result = canonical_composite_analysis_op(
            build_op_context(),
            AgentConfig(storage_root="/tmp/dagster-canonical-test"),
            {**_snapshot(), "trade_date": "2026-05-14"},
            _allow_readiness_gate(),
        )

    assert result["output_mode"] == "accepted"
    assert canonical_mock.call_count == 1
    assert canonical_mock.call_args.kwargs["storage_root"].as_posix() == "/tmp/dagster-canonical-test"
    assert canonical_mock.call_args.kwargs["created_at"] == datetime(2026, 5, 14, tzinfo=timezone.utc)


def test_canonical_composite_analysis_op_does_not_start_agents_when_readiness_blocks() -> None:
    blocked_gate = {
        "decision": "block",
        "reason_code": "downstream_readiness_missing",
        "trade_date": "2026-05-14",
    }
    with patch("apps.worker.composite_analysis_pipeline.run_composite_analysis_pipeline") as canonical_mock:
        result = canonical_composite_analysis_op(
            build_op_context(),
            AgentConfig(),
            {**_snapshot(), "trade_date": "2026-05-14"},
            blocked_gate,
        )

    assert result["output_mode"] == "blocked"
    assert result["premarket_readiness_gate"] == blocked_gate
    canonical_mock.assert_not_called()


def test_canonical_composite_analysis_op_retries_with_stable_snapshot_created_at() -> None:
    fake_outputs = {
        "quality_gate_decision": {"action": "pass"},
        "agent_loop_decision": {"decision": "passed"},
        "report_result": {"paths": ["final_report.md"]},
        "card_result": {"paths": ["strategy_card.json"]},
    }
    fake_summaries = {"final_report": {"output_mode": "accepted"}}
    snapshot = {**_snapshot(), "snapshot_time": "2026-05-14T12:00:00+08:00"}
    with patch(
        "apps.worker.composite_analysis_pipeline.run_composite_analysis_pipeline",
        return_value=(fake_summaries, fake_outputs),
    ) as canonical_mock:
        context = build_op_context()
        canonical_composite_analysis_op(context, AgentConfig(), snapshot, _allow_readiness_gate())
        canonical_composite_analysis_op(context, AgentConfig(), snapshot, _allow_readiness_gate())

    created_at_values = [call.kwargs["created_at"] for call in canonical_mock.call_args_list]
    assert created_at_values == [datetime.fromisoformat("2026-05-14T12:00:00+08:00")] * 2
    assert created_at_values[0] == created_at_values[1]
    assert [call.kwargs["run_id"] for call in canonical_mock.call_args_list] == [context.run_id] * 2


def test_canonical_composite_analysis_op_rejects_missing_or_invalid_snapshot_time() -> None:
    with pytest.raises(ValueError, match="requires snapshot_time or as_of"):
        canonical_composite_analysis_op(
            build_op_context(), AgentConfig(), {"snapshot_id": "missing-time"}, _allow_readiness_gate()
        )

    with pytest.raises(ValueError, match="invalid snapshot_time"):
        canonical_composite_analysis_op(
            build_op_context(),
            AgentConfig(),
            {**_snapshot(), "snapshot_time": "not-a-timestamp"},
            _allow_readiness_gate(),
        )


def test_final_report_op_renders_and_writes_dagster_agent_payloads() -> None:
    outputs = {
        "macro_output": _agent_output(module="macro", agent_name="macro_liquidity_agent"),
        "options_output": _agent_output(module="options", agent_name="cme_options_agent"),
        "risk_output": _agent_output(module="risk", agent_name="risk_agent"),
        "technical_output": _agent_output(module="technical", agent_name="technical_agent"),
        "positioning_output": _agent_output(module="positioning", agent_name="positioning_agent"),
        "news_output": _agent_output(module="news", agent_name="news_agent"),
        "coordinator_output": _agent_output(module="coordinator", agent_name="coordinator_agent"),
    }

    with (
        patch("dagster_finance.ops.agents.render_final_report_markdown", return_value="# report\n") as render_mock,
        patch("dagster_finance.ops.agents.build_structured_report") as structured_mock,
        patch("dagster_finance.ops.agents.write_final_report", return_value={"paths": ["final_report.md"]}) as write_mock,
    ):
        structured_mock.return_value.model_dump.return_value = {"report_id": "final-report-test"}
        context = build_op_context()
        result = final_report_op(
            context,
            snapshot={**_snapshot(), "trade_date": "2026-05-14", "asset": "XAUUSD"},
            **{name: output.model_dump(mode="json") for name, output in outputs.items()},
        )

    assert result == {"paths": ["final_report.md"]}
    assert render_mock.call_args.kwargs["coordinator_output"].agent_name == "coordinator_agent"
    assert write_mock.call_args.kwargs["trade_date"] == "2026-05-14"
    assert write_mock.call_args.kwargs["run_id"] == context.run_id
