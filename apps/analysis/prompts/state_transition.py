"""Strict prompt contract for canary AnalysisState transition generation."""

from __future__ import annotations

import json
from typing import Any


def build_state_transition_prompt(
    *,
    canonical_state_id: str,
    state_scope: str,
    bundle_payload: dict[str, Any],
) -> str:
    """Build the JSON-only prompt for one immutable, scoped Bundle."""

    contract = {
        "previous_state_id": canonical_state_id,
        "summary": "non-empty string",
        "changes": [
            {
                "target": "one changed AnalysisState field",
                "action": "strengthen|maintain|weaken|invalidate|pending",
                "reason": "non-empty evidence-backed reason",
                "evidence_refs": ["exact source_ref objects present in this Bundle"],
            }
        ],
        "state_patch": {"changed_field": "new value; represented once in changes"},
        "evidence_refs": ["exact source_ref objects present in this Bundle"],
    }
    return (
        "根据 immutable AnalysisContextBundle 生成 TransitionCandidate。\n"
        f"state_scope 必须是 {state_scope!r}，previous_state_id 必须完全匹配。"
        "每个 change 和 patch 必须一一对应；只引用 Bundle 内真实 source_ref；"
        "as_of 只能前进；没有充分证据就不得强化结论。\n"
        "输出契约：\n"
        f"{json.dumps(contract, ensure_ascii=False, indent=2)}\n"
        "AnalysisContextBundle：\n"
        f"{json.dumps(bundle_payload, ensure_ascii=False, indent=2)}"
    )
