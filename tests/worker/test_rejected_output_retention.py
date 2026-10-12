from copy import deepcopy
from datetime import datetime, timezone
import json

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
from apps.worker.composite_analysis_pipeline import blocked_research_result


def test_rejected_composite_retains_diagnostic_without_body_or_domain_mutation(tmp_path):
    bad = "rejected synthetic research text must not survive"
    coordinator = AgentOutput(
        version="1.0", agent_name="coordinator_agent", module="coordinator",
        snapshot_id="snapshot", input_snapshot_ids={}, source_refs=[],
        created_at=datetime.now(timezone.utc), status=AgentStatus.PARTIAL,
        bias=AgentBias.BULLISH, confidence=.8, summary=bad, key_findings=[bad],
        risk_points=[bad], watchlist=[bad],
        input_payload={"narrative_md": bad, "research_synthesis": {"status": "rule_fallback", "analysis": bad}},
    )
    domain = coordinator.model_copy(update={"agent_name": "macro_agent", "module": "macro", "summary": "valid domain evidence"})
    before = deepcopy(coordinator.model_dump())
    _, result = blocked_research_result(
        storage_root=tmp_path, snapshot={"snapshot_id": "snapshot", "trade_date": "2026-10-12"},
        run_id="failed-run", summaries={}, reasons=["research_generation_failed"],
        agents={"coordinator_agent": coordinator, "macro_agent": domain},
    )
    output = result["agents"]["coordinator_agent"]
    assert bad not in output.model_dump_json()
    assert output.status == AgentStatus.UNAVAILABLE and output.bias == AgentBias.UNAVAILABLE
    assert output.confidence == 0 and not output.key_findings
    assert output.input_payload["output_cleanup"]["reason_codes"] == ["research_generation_failed"]
    assert len(output.input_payload["output_cleanup"]["original_payload_sha256"]) == 64
    assert result["agents"]["macro_agent"] is domain
    assert coordinator.model_dump() == before
    assert result["report_result"] is result["card_result"] is result["strategy_card"] is None
    assert all(bad not in path.read_text() for path in tmp_path.rglob("*.json"))
    diagnostic = json.loads(next(tmp_path.rglob("research_diagnostic.json")).read_text())
    assert diagnostic["report_generated"] is False
