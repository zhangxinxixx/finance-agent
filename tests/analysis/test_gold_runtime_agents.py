from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.analysis.agents.gold_runtime_agents import (
    materialize_report_render_agent_artifact,
    materialize_gold_runtime_agent_artifacts,
    stable_created_at,
    stable_gold_snapshot_id,
)


def test_runtime_agent_envelopes_reference_only_their_canonical_artifact(tmp_path: Path) -> None:
    paths = {
        "source_health": "analysis/gold/run/source_health.json",
        "gold_event_mainlines": "analysis/gold/run/gold_event_mainlines.json",
        "gold_macro_overview": "analysis/gold/run/gold_macro_overview.json",
        "quality_gate_result": "analysis/gold/run/quality_gate_result.json",
    }
    result = materialize_gold_runtime_agent_artifacts(
        storage_root=tmp_path,
        retrieved_date="2026-07-14",
        run_id="run-1",
        as_of="2026-07-14T08:30:00+00:00",
        input_snapshot_ids={"news": "features/news/input.json"},
        source_refs=[{"source": "fixture", "path": "raw/input.json"}],
        canonical_paths=paths,
        source_health={"overall_status": "degraded", "warnings": ["stale:etf"]},
        gold_event_mainlines={
            "status": "partial",
            "mainlines": [{"confidence": 0.72}],
            "warnings": ["single_source"],
        },
        gold_macro_overview={
            "status": "partial",
            "analysis_readiness": {"ready_count": 6, "total_count": 9},
        },
        review_gate={"review_status": "needs_review", "warnings": ["manual_review"]},
    )

    assert result["declared_agents"] == [
        "source_health_agent",
        "event_attribution_agent",
        "transmission_chain_agent",
        "driver_decomposition_agent",
        "mainline_ranking_agent",
        "gold_macro_overview_agent",
        "review_gate_agent",
    ]
    assert result["materialized_stage_envelopes"] == result["declared_agents"]
    assert result["executed_agents"] == []
    assert result["runtime_contract_only"] is True
    assert result["snapshot_id"] == stable_gold_snapshot_id(
        retrieved_date="2026-07-14", run_id="run-1"
    )
    for agent_name, relative_path in result["artifact_paths"].items():
        envelope = json.loads((tmp_path / relative_path).read_text(encoding="utf-8"))
        assert envelope["agent_name"] == agent_name
        assert envelope["status"] == "partial"
        assert 0.0 < envelope["confidence"] < 1.0
        assert len(envelope["artifact_refs"]) == 1
        expected_type = (
            "source_health"
            if agent_name == "source_health_agent"
            else "quality_gate_result"
            if agent_name == "review_gate_agent"
            else "gold_macro_overview"
            if agent_name == "gold_macro_overview_agent"
            else "gold_event_mainlines"
        )
        assert envelope["artifact_refs"] == [
            {"artifact_type": expected_type, "path": paths[expected_type]}
        ]

    rerun = materialize_gold_runtime_agent_artifacts(
        storage_root=tmp_path,
        retrieved_date="2026-07-14",
        run_id="run-1",
        as_of="2026-07-14T08:30:00+00:00",
        input_snapshot_ids={"news": "features/news/input.json"},
        source_refs=[{"source": "fixture", "path": "raw/input.json"}],
        canonical_paths=paths,
        source_health={"overall_status": "degraded", "warnings": ["stale:etf"]},
        gold_event_mainlines={
            "status": "partial",
            "mainlines": [{"confidence": 0.72}],
            "warnings": ["single_source"],
        },
        gold_macro_overview={
            "status": "partial",
            "analysis_readiness": {"ready_count": 6, "total_count": 9},
        },
        review_gate={"review_status": "needs_review", "warnings": ["manual_review"]},
    )
    assert all(not item.written for item in rerun["write_results"].values())
    assert rerun["executed_agents"] == []
    assert rerun["materialized_stage_envelopes"] == result["materialized_stage_envelopes"]


def test_stable_created_at_normalizes_date_only_without_wall_clock() -> None:
    assert stable_created_at("2026-07-14").isoformat() == "2026-07-14T00:00:00+00:00"


def test_ready_source_health_agent_has_full_confidence(tmp_path: Path) -> None:
    result = materialize_gold_runtime_agent_artifacts(
        storage_root=tmp_path,
        retrieved_date="2026-07-14",
        run_id="ready-run",
        as_of="2026-07-14T08:30:00+00:00",
        input_snapshot_ids={"news": "features/news/input.json"},
        source_refs=[{"source": "fixture", "path": "raw/input.json"}],
        canonical_paths={
            "source_health": "analysis/gold/run/source_health.json",
            "gold_event_mainlines": "analysis/gold/run/gold_event_mainlines.json",
            "gold_macro_overview": "analysis/gold/run/gold_macro_overview.json",
            "quality_gate_result": "analysis/gold/run/quality_gate_result.json",
        },
        source_health={"overall_status": "ready"},
        gold_event_mainlines={
            "status": "success",
            "mainlines": [{"confidence": 1.0}],
        },
        gold_macro_overview={
            "status": "success",
            "analysis_readiness": {"ready_count": 9, "total_count": 9},
        },
        review_gate={"review_status": "pass"},
    )

    envelope_path = result["artifact_paths"]["source_health_agent"]
    envelope = json.loads((tmp_path / envelope_path).read_text(encoding="utf-8"))
    assert envelope["status"] == "success"
    assert envelope["confidence"] == 1.0


def test_report_render_agent_references_canonical_outputs_without_copying_content(
    tmp_path: Path,
) -> None:
    report = tmp_path / "outputs" / "final_report" / "XAUUSD" / "2026-07-14" / "run-1" / "final_report.md"
    card = (
        tmp_path
        / "outputs"
        / "strategy_card"
        / "XAUUSD"
        / "2026-07-14"
        / "run-1"
        / "strategy_card.json"
    )
    report.parent.mkdir(parents=True)
    card.parent.mkdir(parents=True)
    report.write_text("# report\n", encoding="utf-8")
    card.write_text('{"bias":"neutral"}\n', encoding="utf-8")

    result = materialize_report_render_agent_artifact(
        storage_root=tmp_path,
        trade_date="2026-07-14",
        run_id="run-1",
        snapshot_id="snapshot-1",
        created_at=stable_created_at("2026-07-14T08:30:00Z"),
        input_snapshot_ids={"analysis_snapshot": "snapshot-1", "coordinator": "coordinator-1"},
        source_refs=[{"source": "fixture"}],
        report_paths=[str(report)],
        strategy_card_paths=[str(card)],
        report_artifact_type="final_report",
        strategy_artifact_type="strategy_card",
    )

    envelope = json.loads((tmp_path / result.storage_relative_path).read_text(encoding="utf-8"))
    assert envelope["agent_name"] == "report_render_agent"
    assert envelope["artifact_refs"] == [
        {
            "artifact_type": "final_report",
            "path": "outputs/final_report/XAUUSD/2026-07-14/run-1/final_report.md",
        },
        {
            "artifact_type": "strategy_card",
            "path": "outputs/strategy_card/XAUUSD/2026-07-14/run-1/strategy_card.json",
        },
    ]
    assert "# report" not in json.dumps(envelope)


def test_observation_report_render_envelope_preserves_observation_artifact_truth(
    tmp_path: Path,
) -> None:
    report = tmp_path / "outputs" / "observation_report" / "XAUUSD" / "2026-07-14" / "run-1" / "final_report.md"
    card = tmp_path / "outputs" / "observation_strategy_card" / "XAUUSD" / "2026-07-14" / "run-1" / "strategy_card.json"
    report.parent.mkdir(parents=True)
    card.parent.mkdir(parents=True)
    report.write_text("# observation\n", encoding="utf-8")
    card.write_text('{"bias":"neutral"}\n', encoding="utf-8")

    result = materialize_report_render_agent_artifact(
        storage_root=tmp_path,
        trade_date="2026-07-14",
        run_id="run-1",
        snapshot_id="snapshot-1",
        created_at=stable_created_at("2026-07-14T08:30:00Z"),
        input_snapshot_ids={"analysis_snapshot": "snapshot-1"},
        source_refs=[{"source": "fixture"}],
        report_paths=[str(report)],
        strategy_card_paths=[str(card)],
        report_artifact_type="observation_report",
        strategy_artifact_type="observation_strategy_card",
    )

    envelope = json.loads((tmp_path / result.storage_relative_path).read_text(encoding="utf-8"))
    assert envelope["status"] == "partial"
    assert envelope["confidence"] == 0.0
    assert envelope["data_quality"] == ["observation_only", "publish_not_allowed"]
    assert {item["artifact_type"] for item in envelope["artifact_refs"]} == {
        "observation_report",
        "observation_strategy_card",
    }
    assert "final_report" not in {item["artifact_type"] for item in envelope["artifact_refs"]}
    assert "strategy_card" not in {item["artifact_type"] for item in envelope["artifact_refs"]}


def test_report_render_agent_rejects_paths_outside_storage_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-final-report.md"
    outside.write_text("# outside\n", encoding="utf-8")
    card = tmp_path / "outputs" / "strategy_card" / "XAUUSD" / "2026-07-14" / "run-1" / "strategy_card.json"
    card.parent.mkdir(parents=True)
    card.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes storage root"):
        materialize_report_render_agent_artifact(
            storage_root=tmp_path,
            trade_date="2026-07-14",
            run_id="run-1",
            snapshot_id="snapshot-1",
            created_at=stable_created_at("2026-07-14T08:30:00Z"),
            input_snapshot_ids={"analysis_snapshot": "snapshot-1"},
            source_refs=[],
            report_paths=[str(outside)],
            strategy_card_paths=[str(card)],
            report_artifact_type="final_report",
            strategy_artifact_type="strategy_card",
        )
