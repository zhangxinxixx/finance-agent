from __future__ import annotations

import json
from datetime import datetime, timezone

from apps.analysis.agents.system_evolution import evaluate_system_evolution
from apps.governance.system_evolution_workflow import persist_system_evolution_review


def test_persist_system_evolution_review_writes_findings_and_proposals_without_source_mutation(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    review = evaluate_system_evolution(
        gold_macro_overview={
            "net_bias": "mixed",
            "driver_conflict": {},
            "source_refs": [{"source": "event_flow", "source_ref": "event:1"}],
        },
        source_refs=[{"source": "test", "path": "outputs/gold/report.json"}],
    )

    result = persist_system_evolution_review(
        review=review,
        storage_root=storage_root,
        trade_date="2026-07-08",
        observed_at=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert result["artifacts"] == {
        "findings": "governance/system_evolution/2026-07-08/findings.json",
        "improvement_proposals": "governance/system_evolution/2026-07-08/improvement_proposals.json",
        "review": "governance/system_evolution/2026-07-08/system_evolution_review.json",
    }
    findings = json.loads((storage_root / result["artifacts"]["findings"]).read_text(encoding="utf-8"))
    proposals = json.loads((storage_root / result["artifacts"]["improvement_proposals"]).read_text(encoding="utf-8"))
    full_review = json.loads((storage_root / result["artifacts"]["review"]).read_text(encoding="utf-8"))

    assert findings["count"] == 1
    assert findings["findings"][0]["code"] == "mixed_without_driver_decomposition"
    assert proposals["count"] == 1
    proposal = proposals["proposals"][0]
    for field in (
        "rationale",
        "proposed_changes",
        "expected_impact",
        "risks",
        "rollback_plan",
        "test_plan",
    ):
        assert proposal[field]
    assert proposal["status"] == "pending_review"
    assert proposal["linked_issue"] is None
    assert proposal["linked_pr"] is None
    assert full_review["review_status"] == "blocked"
    assert full_review["blocked"] is True

    assert not (storage_root / "raw").exists()
    assert not (storage_root / "parsed").exists()
    assert not (storage_root / "features").exists()
