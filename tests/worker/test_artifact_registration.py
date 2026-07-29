from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def test_registers_gold_policy_shadow_artifacts_with_observe_lineage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = {}
    for filename in (
        "feature_snapshot.v1.json",
        "gold_analysis_decision.v1.json",
        "gold_price_attribution.v1.json",
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
            "gold_feature_snapshot": _FeatureSnapshot("feature_snapshot.v1:test"),
            "gold_analysis_decision": _GoldAnalysisDecision("feature_snapshot.v1:previous"),
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
        "gold_policy_feature_snapshot": "feature_snapshot.v1:test",
        "gold_policy_previous_feature_snapshot": "feature_snapshot.v1:previous",
    }
