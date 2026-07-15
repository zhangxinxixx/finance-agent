from __future__ import annotations

import json
from types import SimpleNamespace

from apps.analysis.agents.weekly_context_revision import (
    apply_weekly_context_revision_llm,
    invoke_weekly_context_revision_llm,
    mark_weekly_context_revision_llm_failure,
)
from apps.renderer.markdown.weekly_context_revision import build_weekly_context_revision_payload
from apps.renderer.contracts import WeeklyContextRevisionPayload


def _deterministic_payload():
    return build_weekly_context_revision_payload(
        {
            "status": "ready",
            "asset": "XAUUSD",
            "trade_date": "2026-07-19",
            "context_as_of": "2026-07-19T11:14:10+00:00",
            "anchor": {
                "article_id": "224965",
                "report_date": "2026-07-18",
                "run_id": "224965",
                "title": "黄金投资者周报",
                "baseline_quality_status": "accepted",
                "baseline_artifact_refs": [{"path": "baseline.json"}],
            },
            "input_snapshot_ids": {"weekly_baseline": "baseline.json"},
            "freshness": {"baseline": {"status": "available", "as_of": "2026-07-18"}},
            "baseline_claims": [
                {
                    "claim_id": "overall_thesis",
                    "category": "overall_thesis",
                    "claim": "底部逐步夯实",
                    "source_path": "one_line_conclusion",
                }
            ],
            "new_evidence": [],
            "confirmation_matrix": {
                "price": {"status": "observed", "current_price": 4016.55},
                "rates": {"status": "confirmed", "real_10y": 2.35, "us10y": 4.57},
                "options": {"status": "confirmed", "gamma_zero": 4126.43},
            },
            "positioning_check": {"status": "confirmed"},
            "dominant_transmission_chain": {"status": "observed"},
            "scenario_updates": [],
            "watch_items": [],
            "revision_risk": {"level": "monitor", "reason": "monitor", "quality_flags": []},
            "source_refs": [],
            "quality_flags": [],
        },
        run_id="revision-run",
    )


def test_weekly_revision_agent_explicitly_uses_sol_high(monkeypatch) -> None:
    payload = _deterministic_payload()
    raw_payload = payload.model_dump(mode="json")
    raw_payload["dominant_transmission_chain"]["source_refs"] = [{"title": "x" * 100_000}]
    payload = WeeklyContextRevisionPayload.model_validate(raw_payload)
    captured = {}
    monkeypatch.setenv("FINANCE_AGENT_FORCE_LIVE_LLM", "1")

    def fake_chat_sync(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=json.dumps(
                {
                    "executive_summary": "底部信号保留，但价格和利率尚未共振。",
                    "claim_revisions": [
                        {
                            "claim_id": "overall_thesis",
                            "action": "weaken",
                            "reason": "价格仍低于 Gamma Zero，实际利率维持高位。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            model="gpt-5.6-sol",
            provider="jojocode",
            reasoning_effort="high",
            latency_ms=120,
            usage={"total_tokens": 100},
        )

    monkeypatch.setattr("apps.llm.gateway.chat_sync", fake_chat_sync)

    result = invoke_weekly_context_revision_llm(payload)
    refined = apply_weekly_context_revision_llm(payload, result)

    assert captured["model"] == "gpt-5.6-sol"
    assert captured["reasoning_effort"] == "high"
    assert captured["json_mode"] is True
    assert len(captured["messages"][1]["content"]) < 20_000
    assert refined.claim_revisions[0].action == "weaken"
    assert refined.analysis_provenance["llm_status"] == "accepted"


def test_weekly_revision_agent_failure_forces_observe_only() -> None:
    payload = _deterministic_payload()

    degraded = mark_weekly_context_revision_llm_failure(payload, RuntimeError("524 timeout"))

    assert degraded.quality_status == "needs_review"
    assert degraded.publication_status == "observe"
    assert degraded.publish_allowed is False
    assert degraded.analysis_provenance["model"] == "gpt-5.6-sol"
    assert degraded.analysis_provenance["reasoning_effort"] == "high"
    assert "llm_error" in degraded.revision_risk["quality_flags"]
