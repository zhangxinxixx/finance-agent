from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.worker.artifact_registration import register_composite_output_artifacts


@dataclass
class _Step:
    name: str
    output_ref: str | None = None


@dataclass
class _FeatureSnapshot:
    snapshot_id: str


@dataclass
class _GoldAnalysisDecision:
    previous_snapshot_id: str


@pytest.mark.parametrize("version", ("v1", "v2"))
def test_registers_gold_policy_shadow_artifacts_with_observe_lineage(
    tmp_path: Path,
    monkeypatch,
    version: str,
) -> None:
    paths = {}
    for filename in (
        f"feature_snapshot.{version}.json",
        f"gold_analysis_decision.{version}.json",
        f"gold_price_attribution.{version}.json",
    ):
        path = tmp_path / filename
        path.write_text("{}\n", encoding="utf-8")
        paths[filename] = str(path)

    captured: dict = {}

    def capture(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)

    monkeypatch.setattr("apps.worker.artifact_registration.register_step_artifacts", capture)
    register_composite_output_artifacts(
        object(),
        run_id="run-shadow",
        steps=[_Step("report_render")],
        composite_outputs={
            "gold_policy_execution_mode": "shadow",
            "gold_policy_artifact_paths": paths,
            "gold_feature_snapshot": _FeatureSnapshot(
                f"feature_snapshot.{version}:test"
            ),
            "gold_analysis_decision": _GoldAnalysisDecision(
                f"feature_snapshot.{version}:previous"
            ),
        },
        analysis_snapshot={
            "source_refs": [{"source": "analysis_snapshot", "snapshot_id": "snap-1"}],
            "input_snapshot_ids": {"analysis_snapshot": "snap-1"},
        },
    )

    artifacts = captured["output_refs"]
    shadow_artifacts = [item for item in artifacts if item.get("execution_mode") == "shadow"]
    assert len(shadow_artifacts) == 3
    assert {item["artifact_type"] for item in shadow_artifacts} == {"feature_json", "structured_json"}
    assert all(item["publish_allowed"] is False for item in shadow_artifacts)
    assert all(item["output_mode"] == "observe" for item in shadow_artifacts)
    assert captured["input_snapshot_ids"] == {
        "analysis_snapshot": "snap-1",
        "gold_policy_feature_snapshot": f"feature_snapshot.{version}:test",
        "gold_policy_previous_feature_snapshot": f"feature_snapshot.{version}:previous",
    }


def test_registers_composite_artifacts_under_strategy_step_when_report_step_is_absent(monkeypatch) -> None:
    captured: dict = {}

    def capture(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)

    monkeypatch.setattr("apps.worker.artifact_registration.register_step_artifacts", capture)
    register_composite_output_artifacts(
        object(),
        run_id="run-canonical",
        steps=[_Step("strategy_card")],
        composite_outputs={
            "agent_loop_decision": SimpleNamespace(publish_allowed=True),
            "report_result": {"paths": ["storage/outputs/final_report/run-canonical/final_report.md"]},
            "card_result": {"paths": ["storage/outputs/strategy_card/run-canonical/strategy_card.json"]},
            "strategy_card": SimpleNamespace(source_refs=[], input_snapshot_ids={}),
        },
        analysis_snapshot={"source_refs": [], "input_snapshot_ids": {}},
    )

    assert captured["step"].name == "strategy_card"
    assert captured["output_refs"]
