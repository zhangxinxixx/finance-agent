"""Strict prompt contract for canary AnalysisState transition generation."""

from __future__ import annotations

import json
from typing import Any


_DOMINANT_DRIVER_SCHEMA = {
    "driver_id": "non-empty string, stable semantic identity",
    "label": "non-empty display label",
    "rank": "integer >= 1 or null",
    "score": "finite number or null",
    "direction": "tailwind|headwind|neutral|mixed|unknown",
    "coverage_status": "covered|partial|missing|unknown",
}
_KEY_LEVEL_SCHEMA = {
    "value": "finite number or non-empty string",
    "role": "non-empty string",
    "source": "non-empty string",
    "meaning": "non-empty string or null",
}
_SCENARIO_STATE_SCHEMA = {
    "scenario_id": "non-empty stable identity",
    "condition": "non-empty condition",
    "status": "active|pending|confirmed|invalidated",
}


def build_state_transition_prompt(
    *,
    canonical_state_id: str,
    state_scope: str,
    bundle_payload: dict[str, Any],
) -> str:
    """Build the JSON-only prompt for one immutable, scoped Bundle."""

    contract = {
        "schema_version": "analysis_transition_candidate.v2",
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
        "state_patch": _state_patch_schema(),
        "evidence_refs": ["exact source_ref objects present in this Bundle"],
    }
    return (
        "根据 immutable AnalysisContextBundle 生成 TransitionCandidate。\n"
        f"state_scope 必须是 {state_scope!r}，previous_state_id 必须完全匹配。"
        "每个 change 和 patch 必须一一对应；只引用 Bundle 内真实 source_ref；"
        "不得输出 as_of、evidence_cursors、input_snapshot_ids、source_refs、scope、version、session 或 trade_date；"
        "这些字段由系统从 Bundle 生成。没有充分证据就不得强化结论。\n"
        "输出契约：\n"
        f"{json.dumps(contract, ensure_ascii=False, indent=2)}\n"
        "AnalysisContextBundle：\n"
        f"{json.dumps(bundle_payload, ensure_ascii=False, indent=2)}"
    )


def build_state_transition_for_conclusion_prompt(
    *,
    canonical_state_id: str,
    state_scope: str,
    bundle_payload: dict[str, Any],
    accepted_state_conclusion: dict[str, Any],
) -> str:
    """Build a JSON-only prompt bound to one accepted typed conclusion."""

    target_patch = {
        "market_stage": accepted_state_conclusion["market_stage"],
        "core_thesis": accepted_state_conclusion["core_thesis"],
        "net_bias": accepted_state_conclusion["state_bias"],
        "dominant_drivers": accepted_state_conclusion["dominant_drivers"],
    }
    contract = {
        "schema_version": "analysis_transition_candidate.v2",
        "previous_state_id": canonical_state_id,
        "summary": "non-empty evidence-backed string",
        "changes": [
            {
                "target": "exactly one of market_stage|core_thesis|net_bias|dominant_drivers",
                "action": "strengthen|maintain|weaken|invalidate|pending",
                "reason": "non-empty reason based only on retained Bundle evidence",
                "evidence_refs": ["exact source_ref objects present in this Bundle"],
            }
        ],
        "state_patch": target_patch,
        "evidence_refs": ["exact source_ref objects present in this Bundle"],
    }
    return (
        "根据 immutable AnalysisContextBundle 为 accepted_state_conclusion 生成 TransitionCandidate。\n"
        f"Bundle state_scope 是 {state_scope!r}，仅用于校验；严禁在输出顶层或 state_patch 中输出 state_scope。"
        "输出顶层必须且只能包含 schema_version、previous_state_id、summary、changes、state_patch、evidence_refs。"
        "previous_state_id 必须完全匹配。"
        "state_patch 必须且只能包含 market_stage、core_thesis、net_bias、dominant_drivers，"
        "并逐值复制下方 accepted target，不得改写、重排或增删。"
        "changes 必须逐一覆盖这四个字段，且只能引用 Bundle retained evidence/facts 中真实存在的 "
        "source_ref。证据不能支持强化、削弱或失效时，action 必须使用 maintain 或 pending；"
        "不得补造证据、关键位、情景、因果关系或系统元数据。\n"
        "嵌套 AnalysisState schema（即使本次 target 不修改 key_levels/scenario_states，也必须遵守）：\n"
        f"{json.dumps(_nested_state_schema(), ensure_ascii=False, indent=2)}\n"
        "Accepted target：\n"
        f"{json.dumps(target_patch, ensure_ascii=False, indent=2)}\n"
        "输出契约：\n"
        f"{json.dumps(contract, ensure_ascii=False, indent=2)}\n"
        "AnalysisContextBundle：\n"
        f"{json.dumps(bundle_payload, ensure_ascii=False, indent=2)}"
    )


def _state_patch_schema() -> dict[str, Any]:
    return {
        "market_stage": "non-empty stable stage code",
        "core_thesis": "non-empty display thesis",
        "net_bias": "non-empty state bias code",
        "dominant_drivers": [_DOMINANT_DRIVER_SCHEMA],
        "key_levels": [_KEY_LEVEL_SCHEMA],
        "scenario_states": [_SCENARIO_STATE_SCHEMA],
        "unresolved_items": ["JSON object backed by Bundle evidence"],
        "invalidation_conditions": ["JSON object backed by Bundle evidence"],
    }


def _nested_state_schema() -> dict[str, Any]:
    return {
        "DominantDriver": _DOMINANT_DRIVER_SCHEMA,
        "KeyLevel": _KEY_LEVEL_SCHEMA,
        "ScenarioState": _SCENARIO_STATE_SCHEMA,
    }
