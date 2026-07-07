from __future__ import annotations

from datetime import datetime


def coordinator_output_payload(*, created_at: datetime) -> dict:
    return {
        "version": "1.0",
        "agent_name": "coordinator_agent",
        "module": "coordinator",
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "input_snapshot_ids": {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "macro": "macro:2026-05-14",
            "options": "cme-options:2026-05-14",
            "risk": "risk:2026-05-14",
        },
        "bias": "bullish",
        "confidence": 0.61,
        "key_findings": ["Macro and options are aligned."],
        "risk_points": ["Technical, news, and positioning inputs are unavailable."],
        "watchlist": ["DGS10", "CME option walls"],
        "invalid_conditions": ["No precise trade execution plan is produced."],
        "summary": "Bullish research view with constrained confidence.",
        "source_refs": [],
        "status": "partial",
        "created_at": created_at,
    }
