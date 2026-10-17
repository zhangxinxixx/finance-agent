"""Independent model synthesis grounded in the versioned Gold research workflow.

The research workflow computes the facts, bias, confidence, state candidate and
source lineage before this module is called.  The model can challenge module conclusions and develop alternative hypotheses.
Its views remain model inference: they cannot mutate the deterministic facts,
canonical state, rule weights or source lineage.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from apps.analysis.agents.schemas import AgentOutput
from apps.analysis.agents.research_quality import GATE_VERSION, ResearchQualityError
from apps.analysis.agents.research_input import final_input, encode, input_metrics, ResearchInputTooLarge
from apps.analysis.agents.research_input import (
    DETAILED_PROFILE_VERSION,
    DETAILED_REASONING_FIELDS,
    DETAILED_TOPICS,
    RESEARCH_PRESENTATION_VERSION,
)

GOLD_WORKFLOW_SCHEMA_VERSION = "gold_workflow.v2"
RESEARCH_SYNTHESIS_SCHEMA_VERSION = "research_synthesis.v2"

_REQUIRED_FIELDS = (
    "dominant_factor",
    "counter_evidence",
    "state_limitations",
    "convergence_transition",
    "evidence_ids",
)
_OPTIONAL_FIELDS = ("independent_assessment", "module_challenges", "alternative_hypotheses", "what_would_change_my_mind", "market_move_explanation", "energy_transmission", "funds_interpretation", "news_catalysts", "reader_narrative", "macro_answers", "macro_narrative", "dominant_shocks")
_ALLOWED_FIELDS = (*_REQUIRED_FIELDS, *_OPTIONAL_FIELDS)
_DETAILED_ALLOWED_FIELDS = (*_ALLOWED_FIELDS, 'report_sections')
_LIST_FIELDS = {
    "counter_evidence",
    "state_limitations",
    "convergence_transition",
    "evidence_ids", "module_challenges", "alternative_hypotheses", "what_would_change_my_mind",
}
_TEXT_FIELDS = {"dominant_factor", "independent_assessment", "market_move_explanation", "energy_transmission", "funds_interpretation", "news_catalysts", "reader_narrative"}
_MAX_ITEMS = 12
_MAX_EVIDENCE_IDS = 32
_MAX_TEXT_LENGTH = 1600
_NUMBER_RE = re.compile(r"(?<![A-Za-z_])[-+]?(?:\d+(?:\.\d+)?|\.\d+)%?")
_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "gold_research_coordinator.md"
_DAILY_PROMPT_PATH = _PROMPT_PATH.with_name("gold_macro_daily.md")
_WEEKLY_PROMPT_PATH = _PROMPT_PATH.with_name("gold_macro_weekly.md")


def enrich_research_coordinator(
    snapshot: Mapping[str, Any],
    output: AgentOutput,
    gateway: Any = None,
    allow_repairs: bool = True,
) -> AgentOutput:
    """Add a bounded final-agent explanation to a deterministic coordinator.

    The function is deliberately opt-in.  Existing snapshots and tests without
    ``gold_workflow.v2`` are returned byte-for-byte at the Pydantic model level
    and do not instantiate or call an LLM gateway.
    """

    if not _workflow_enabled(snapshot):
        return output
    quality_required = snapshot.get('gold_workflow', {}).get('reader_report_version') == DETAILED_PROFILE_VERSION

    from apps.analysis.snapshots.input_validation import prepare_analysis_inputs
    snapshot = prepare_analysis_inputs(dict(snapshot))
    validation = snapshot["input_validation"]
    original_payload = dict(output.input_payload or {})
    if validation["can_analyze"] and (original_payload.get("input_validation") or {}).get("input_sha256") != validation.get("input_sha256"):
        from apps.analysis.agents.research_context import build_research_assessment
        original_payload["daily_research_assessment"] = build_research_assessment(snapshot)
        original_payload["domain_analyses"] = []
    output = output.model_copy(update={"input_payload": {**original_payload, "input_validation": validation}})
    if not validation["can_analyze"]:
        result = _apply_rule_fallback(output, messages=[], prompt_payload={},
            reason_code="input_validation_blocked", raw_response=None, quality_required=quality_required)
        from apps.analysis.agents.schemas import AgentStatus, AgentBias
        return result.model_copy(update={"status": AgentStatus.UNAVAILABLE, "bias": AgentBias.UNAVAILABLE,
            "confidence": 0.0, "summary": "研究输入校验阻断，详见 input_validation。",
            "key_findings": [], "watchlist": [], "evidence_items": []})
    existing_payload = output.input_payload if isinstance(output.input_payload, dict) else {}
    existing = existing_payload.get("research_synthesis")
    if isinstance(existing, dict) and existing.get("status") in {"success", "rule_fallback", "quality_blocked"} and (existing.get("input_validation") or {}).get("input_sha256") == validation.get("input_sha256"):
        return output

    prompt_payload = {}
    try:
        prompt_payload = _build_prompt_payload(snapshot, output)
        if quality_required and 'research_quality_standard' not in prompt_payload:
            raise ResearchQualityError('quality_contract_missing')
        messages = _build_messages(prompt_payload)
    except ResearchInputTooLarge:
        return _apply_rule_fallback(output, messages=[], prompt_payload={},
                                   reason_code='ResearchInputTooLarge', raw_response=None,
                                   quality_required=quality_required)
    except ResearchQualityError as exc:
        return _apply_rule_fallback(output, messages=[], prompt_payload=prompt_payload,
            reason_code=exc.reason_code, raw_response=None, quality_failure=exc.details)
    audit_context = {
        "caller": "research_synthesis.enrich_research_coordinator",
        "run_id": snapshot.get("run_id"),
        "snapshot_id": output.snapshot_id,
        "trade_date": snapshot.get("trade_date"),
        "workflow_schema_version": GOLD_WORKFLOW_SCHEMA_VERSION,
        "prompt_schema_version": RESEARCH_SYNTHESIS_SCHEMA_VERSION,
        "input_payload": deepcopy(prompt_payload),
    }

    raw_response: str | None = None
    response: Any = None
    try:
        response = _call_gateway(gateway, messages=messages, audit_context=audit_context)
        raw_response = _response_content(response)
        try:
            parsed = _parse_and_validate(raw_response, prompt_payload)
        except ValueError:
            if not allow_repairs:
                raise
            # One bounded format/constraint repair through the same gateway.
            # Every attempt is audited; the repaired answer faces identical
            # validation, with no changes to facts, sources or hard decisions.
            messages = [*messages, {"role": "assistant", "content": raw_response}, {
                "role": "user",
                "content": "上一条输出未通过 JSON 格式或证据 ID 校验。请按约定必需字段和可选字段重新输出 JSON，每个叙述列表最多十二条，每条最多一千六百字，仅使用合法证据 ID。保留你的独立判断、模块质疑与替代假设；区分输入事实和待验证推断，不能改写系统记录。"
                + (" v4仍须全部report_sections、局部pending、三路径paths与三张cards；六段文本各24至4000字符。" if prompt_payload.get('report_profile') else '')
                + (" 新日报展示还必须保留完整reader_narrative；正文与内部report_sections合计最多50000字符。" if _new_daily_presentation(prompt_payload) else ''),
            }]
            response = _call_gateway(gateway, messages=messages, audit_context={**audit_context, "validation_attempt": 2})
            raw_response = _response_content(response)
            parsed = _parse_and_validate(raw_response, prompt_payload)
        review = None
        if prompt_payload.get("macro_causal") or 'research_quality_standard' in prompt_payload:
            from apps.analysis.agents.macro_causal_review import review_macro_thesis
            review = review_macro_thesis(gateway=gateway, analysis=parsed,
                evidence=prompt_payload, audit_context=audit_context)
            if (allow_repairs and review.get('status') == 'needs_revision'
                    and prompt_payload.get('gold_workflow', {}).get('reader_report_version') in {'gold_reader.v3', DETAILED_PROFILE_VERSION}):
                parsed, raw_response, response, messages, review = _revise_after_review(
                    gateway=gateway, parsed=parsed, raw_response=raw_response, response=response,
                    messages=messages, review=review, prompt_payload=prompt_payload,
                    audit_context=audit_context)
            prompt_payload["macro_review"] = review
        result = _apply_success(
            output,
            parsed=parsed,
            raw_response=raw_response,
            response=response,
            messages=messages,
            prompt_payload=prompt_payload,
        )
        if review:
            result = result.model_copy(update={"confidence": result.confidence * review["confidence_multiplier"]})
        return result
    except Exception as exc:  # noqa: BLE001 - fallback is part of the contract
        return _apply_rule_fallback(
            output,
            messages=messages,
            prompt_payload=prompt_payload,
            reason_code=f"{type(exc).__name__}",
            raw_response=raw_response,
            quality_required=quality_required,
        )


def _revise_after_review(*, gateway, parsed, raw_response, response, messages, review,
                         prompt_payload, audit_context):
    """One evidence-grounded revision; a second rejection stays visible."""
    from apps.analysis.agents.macro_causal_review import review_macro_thesis
    feedback = [c for c in review.get('checks', []) if not c.get('passed')]
    revised_messages = [*messages, {'role': 'assistant', 'content': raw_response},
        {'role': 'user', 'content':
         '请针对以下审阅意见修订整份JSON，保留合理且明确为候选的主观判断。'
         '不能把持仓集中或相关性升级为已识别的交易因果。若不同意审阅意见，'
         '用输入事实说明依据，不强行迎合；正文不出现审阅流程。不得增加新事实或改Accepted。'
         + encode(feedback)}]
    try:
        if sum(len(m['content']) for m in revised_messages) > 260000:
            raise ResearchInputTooLarge('quality revision message budget exceeded')
        revised_response = _call_gateway(gateway, messages=revised_messages,
            audit_context={**audit_context, 'quality_revision_attempt': 1})
        revised_raw = _response_content(revised_response)
        revised = _parse_and_validate(revised_raw, prompt_payload)
        checked = review_macro_thesis(gateway=gateway, analysis=revised, evidence=prompt_payload,
            audit_context={**audit_context, 'quality_revision_attempt': 1})
        checked['prior_review'] = review
        checked['revision_attempts'] = 1
        return revised, revised_raw, revised_response, revised_messages, checked
    except Exception as exc:
        # Keep the valid but challenged draft, and disclose unsuccessful repair.
        return parsed, raw_response, response, messages, {
            **review, 'revision_attempts': 1, 'revision_error': type(exc).__name__}


def _workflow_enabled(snapshot: Mapping[str, Any]) -> bool:
    workflow = snapshot.get("gold_workflow")
    return isinstance(workflow, Mapping) and workflow.get("schema_version") == GOLD_WORKFLOW_SCHEMA_VERSION


def _call_gateway(gateway: Any, *, messages: list[dict[str, str]], audit_context: dict[str, Any]) -> Any:
    if gateway is None:
        from apps.llm.gateway import chat_sync

        caller = chat_sync
    else:
        caller = getattr(gateway, "chat_sync", gateway)
    if not callable(caller):
        raise TypeError("gateway must expose chat_sync")
    # Model/provider are intentionally omitted.  The installed gateway config
    # remains the authority selected by the project runtime.
    return caller(
        messages=messages,
        json_mode=True,
        temperature=0.2,
        max_tokens=32000 if audit_context.get('input_payload', {}).get('report_profile', {}).get('version') == DETAILED_PROFILE_VERSION else 7800,
        max_retries=0,
        request_timeout=360,
        audit_context=audit_context,
    )


def _response_content(response: Any) -> str:
    if isinstance(response, Mapping):
        content = response.get("content") or response.get("text")
    else:
        content = getattr(response, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("gateway response content is empty")
    return content.strip()


def _build_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    from apps.analysis.agents.research_quality import quality_instructions
    method = quality_instructions(payload)
    if method:
        template += "\n\n" + method
    messages = [{"role": "system", "content": template}]
    if payload.get("report_profile", {}).get("version") == DETAILED_PROFILE_VERSION:
        if _new_daily_presentation(payload):
            messages.append({
                "role": "user",
                "content": (
                    "以下是新日报展示的写作方法。它只约束如何组织本次已校验证据，"
                    "不提供事实、价位、方向、Accepted语义或额外采集权限。日报方法优先于随后通用周报方法；"
                    "reader_narrative是读者完整正文，report_sections仍是简洁的内部审阅结构。\n\n"
                    + _DAILY_PROMPT_PATH.read_text(encoding="utf-8")
                ),
            })
        messages.append({
            "role": "user",
            "content": "以下模板仅为研究方法参考。本次实际报告窗口与已校验输入、"
            "既有 system JSON 输出协议优先；20节是周报正文表达框架，"
            "不是新增 report_sections 主题键，不新增 cards 键。"
            + ("新日报仍须按前一条方法输出完整reader_narrative；" if _new_daily_presentation(payload)
               else "旧v4展示不要求reader_narrative；")
            + "保持 v4 的20主题、六文本及 evidence_ids/pending、paths/cards 原契约。"
            "不把每日观察改称本周，不自动新建周报任务、启动采集或云端写入；"
            "加载模板不表示 renderer 已改成20个标题。\n\n"
            + _WEEKLY_PROMPT_PATH.read_text(encoding="utf-8"),
        })
    messages.append(
        {
            "role": "user",
            "content": "只根据以下已校验输入输出 JSON；不要输出 Markdown 或代码围栏。\n"
            + encode(payload),
        }
    )
    return messages


def _new_daily_presentation(payload: Mapping[str, Any]) -> bool:
    workflow = payload.get("gold_workflow")
    return isinstance(workflow, Mapping) and workflow.get("reader_presentation") == RESEARCH_PRESENTATION_VERSION


def _build_prompt_payload(snapshot: Mapping[str, Any], output: AgentOutput) -> dict[str, Any]:
    original_payload = output.input_payload if isinstance(output.input_payload, dict) else {}
    workflow = snapshot.get("gold_workflow")
    if not isinstance(workflow, Mapping):
        workflow = original_payload.get("gold_workflow", {})
    assessment = original_payload.get("daily_research_assessment", {})
    if (snapshot.get("input_validation") or {}).get("input_sha256") and (original_payload.get("input_validation") or {}).get("input_sha256") != snapshot["input_validation"]["input_sha256"]:
        from apps.analysis.agents.research_context import build_research_assessment
        assessment = build_research_assessment(snapshot)
    if not isinstance(assessment, Mapping):
        assessment = {}
    catalog = _evidence_catalog(output, assessment, workflow)
    for row in snapshot.get("daily_research", {}).get("passport", []):
        if row.get("status") == "fresh" and row.get("value") is not None and row.get("source_refs"):
            identifier = row.get("symbol")
            if identifier and not any(c["evidence_id"] == identifier for c in catalog):
                catalog.insert(0, {"evidence_id": identifier, "rationale": f"{row['observation_date']}: {row['value']} {row['unit']}"})
    catalog = catalog[:32]
    if workflow.get("macro_causal"):
        catalog.append({"evidence_id": "macro_causal_v4", "summary": "同版本通胀动能、政策分布可用性、同期国债分解、因果链缺口；推断不等于事实。"})
    if snapshot.get('adaptive_research', {}).get('plan'):
        catalog.append({'evidence_id': 'adaptive_research', 'summary': '本轮按研究问题补采的证据；逐项区分发布方正文与搜索摘要，核对日期及证据范围，缺失项不能参与事实确认。'})
    if workflow.get('reader_report_version') in {'gold_reader.v3', DETAILED_PROFILE_VERSION}:
        return final_input(snapshot, output, catalog=catalog, assessment=assessment)
    return {
        "schema_version": RESEARCH_SYNTHESIS_SCHEMA_VERSION,
        "workflow_schema_version": GOLD_WORKFLOW_SCHEMA_VERSION,
        "snapshot_id": output.snapshot_id,
        "trade_date": snapshot.get("trade_date"),
        "hard_fields": {
            "bias": output.bias.value,
            "confidence": output.confidence,
            "status": output.status.value,
            "research_accepted_state": workflow.get("state", {}).get("accepted_state"),
            "accepted_state_conclusion": (
                output.accepted_state_conclusion.model_dump(mode="json")
                if output.accepted_state_conclusion is not None
                else None
            ),
        },
        "gold_workflow": _compact_json({key: value for key, value in workflow.items() if key not in {"source_refs", "input_snapshot_ids"}}),
        "research_versions": _compact_json(snapshot.get("research_versions", {})),
        "adaptive_research": _compact_json(snapshot.get('adaptive_research', {})),
        "tradingview_cross_asset": _compact_json(workflow.get('cross_asset_freshness', {})),
        "price_action": _compact_json(workflow.get('price_action', {})),
        "macro_causal": _compact_json(workflow.get("macro_causal", {})),
        "daily_research_assessment": _compact_assessment(assessment),
        "domain_analyses": _compact_json(original_payload.get("domain_analyses", [])),
        "news_focus": _compact_json(snapshot.get("news", {}).get("data", {}).get("daily_market_brief", {}).get("report_inputs", {}).get("research_focus", [])[:8]),
        "evidence_catalog": catalog,
        "allowed_output_fields": list(_ALLOWED_FIELDS),
        "analysis_policy": {"independent_judgment_allowed": True, "module_disagreement_allowed": True, "new_hypotheses_allowed": True, "hard_fields_scope": "immutable_system_records_not_a_limit_on_model_opinion", "new_numbers": "model_inference_pending_verification_not_promoted_to_facts"},
    }


def _compact_assessment(value: Mapping[str, Any]) -> dict[str, Any]:
    adjudication = value.get("adjudication")
    factors: list[dict[str, Any]] = []
    if isinstance(adjudication, Mapping):
        raw_factors = adjudication.get("factors")
        if isinstance(raw_factors, Sequence) and not isinstance(raw_factors, (str, bytes)):
            for factor in raw_factors[:12]:
                if not isinstance(factor, Mapping):
                    continue
                factors.append(
                    {
                        "factor_id": factor.get("factor_id"),
                        "family": factor.get("family"),
                        "role": factor.get("role"),
                        "bias": factor.get("bias"),
                        "rationale": factor.get("rationale"),
                        "invalidated_by": factor.get("invalidated_by"),
                        "window": factor.get("window"),
                    }
                )
    return {
        "summary": value.get("summary"),
        "facts": value.get("facts", []),
        "domain_notes": value.get("domain_notes", {}),
        "research_stage": value.get("research_stage"),
        "scenarios": value.get("scenarios"),
        "limitations": value.get("limitations"),
        "adjudication": {
            "bias": adjudication.get("bias") if isinstance(adjudication, Mapping) else None,
            "factor_tilt": adjudication.get("factor_tilt") if isinstance(adjudication, Mapping) else None,
            "preferred_scenario": adjudication.get("preferred_scenario") if isinstance(adjudication, Mapping) else None,
            "factors": factors,
        },
    }


def _evidence_catalog(
    output: AgentOutput,
    assessment: Mapping[str, Any],
    workflow: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    def add(identifier: Any, rationale: Any, *, family: Any = None) -> None:
        key = str(identifier or "").strip()
        if not key or key in result:
            return
        result[key] = {
            "evidence_id": key,
            "family": str(family or "") or None,
            "rationale": str(rationale or "")[:_MAX_TEXT_LENGTH],
        }

    adjudication = assessment.get("adjudication")
    if isinstance(adjudication, Mapping):
        factors = adjudication.get("factors")
        if isinstance(factors, Sequence) and not isinstance(factors, (str, bytes)):
            for factor in factors:
                if isinstance(factor, Mapping):
                    add(factor.get("factor_id") or factor.get("factor"), factor.get("rationale"), family=factor.get("family"))

    for item in output.evidence_items:
        if not isinstance(item, Mapping):
            continue
        add(item.get("factor_id") or item.get("evidence_id") or item.get("factor"), item.get("rationale") or item.get("text"), family=item.get("family"))

    workflow_catalog = workflow.get("evidence_catalog")
    if isinstance(workflow_catalog, Sequence) and not isinstance(workflow_catalog, (str, bytes)):
        for item in workflow_catalog:
            if isinstance(item, Mapping):
                add(item.get("evidence_id") or item.get("id"), item.get("rationale") or item.get("text"), family=item.get("family"))

    # ``gold_workflow.v2`` calls the same deterministic records
    # ``factor_families``.  Accepting that explicit field keeps the final
    # language layer useful even when the legacy research assessment is absent.
    factor_families = workflow.get("factor_families")
    if isinstance(factor_families, Sequence) and not isinstance(factor_families, (str, bytes)):
        for item in factor_families:
            if isinstance(item, Mapping):
                add(
                    item.get("factor_id") or item.get("family"),
                    item.get("rationale") or item.get("explanation"),
                    family=item.get("family"),
                )

    return list(result.values())[:32]


def _compact_json(value: Any, *, depth: int = 0) -> Any:
    if depth >= 7 and isinstance(value, (Mapping, list, tuple)):
        return "[truncated]"
    if isinstance(value, Mapping):
        result = {}
        for key, item in list(value.items())[:80]:
            # Raw files and full hashes remain in the immutable snapshot, not
            # repeated inside every level, zone, scenario and state condition.
            if key in {'raw_path', 'parsed_path', 'input_snapshot_ids', 'raw_levels', 'raw_scenarios'}:
                continue
            if key == 'source_refs':
                refs = item.values() if isinstance(item, Mapping) else item if isinstance(item, list) else []
                result['source_urls'] = list(dict.fromkeys(
                    str(ref.get('source_url') or ref.get('url')) for ref in refs
                    if isinstance(ref, Mapping) and (ref.get('source_url') or ref.get('url'))
                ))[:12]
            else:
                result[str(key)] = _compact_json(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_compact_json(item, depth=depth + 1) for item in list(value)[:40]]
    if isinstance(value, str):
        return value[:_MAX_TEXT_LENGTH]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_TEXT_LENGTH]


def _parse_and_validate(raw: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    parsed = json.loads(text)
    detailed = payload.get('gold_workflow', {}).get('reader_report_version') == DETAILED_PROFILE_VERSION
    allowed_fields = _DETAILED_ALLOWED_FIELDS if detailed else _ALLOWED_FIELDS
    if not isinstance(parsed, Mapping) or not set(_REQUIRED_FIELDS).issubset(parsed) or not set(parsed).issubset(allowed_fields):
        raise ValueError("research synthesis output fields do not match the allowlist")

    if (payload.get('gold_workflow', {}).get('reader_report_version') == 'gold_reader.v3'
            or _new_daily_presentation(payload)):
        if not isinstance(parsed.get('reader_narrative'), str) or not parsed['reader_narrative'].strip():
            raise ValueError('reader presentation requires a complete narrative')
        if (_new_daily_presentation(payload)
                and not re.match(r'^\s*#{1,3}\s*一句话结论\s*(?:\n|$)', parsed['reader_narrative'])):
            raise ValueError('new daily narrative must open with 一句话结论')

    if payload.get("macro_causal"):
        for key, required in {
            "macro_answers": {"growth","inflation","reaction","policy","treasury","oil","response","residual"},
            "macro_narrative": {"growth","inflation","labor","fed","treasury","term_premium","fiscal","dollar","liquidity","credit","oil"},
            "dominant_shocks": {"primary","secondary","counter"},
        }.items():
            values = parsed.get(key)
            if not isinstance(values, dict) or set(values) != required or any(not isinstance(v,str) or not v.strip() or len(v)>1600 for v in values.values()):
                raise ValueError("v4 missing or invalid " + key)
    evidence_ids = _validate_fields(
        parsed,
        reader_narrative_max=50000 if _new_daily_presentation(payload) else 14000,
    )
    allowed_ids = {
        str(item.get("evidence_id"))
        for item in payload.get("evidence_catalog", [])
        if isinstance(item, Mapping) and item.get("evidence_id")
    }
    if not set(evidence_ids).issubset(allowed_ids):
        raise ValueError("research synthesis cited an unknown evidence id")
    if allowed_ids and not evidence_ids:
        raise ValueError("research synthesis must cite at least one evidence id")
    if detailed:
        validate_report_sections(parsed.get('report_sections'), allowed_ids=allowed_ids)
        for key, module in payload.get('report_profile', {}).get('modules', {}).items():
            if module['availability'] != 'available' and not parsed['report_sections'][key]['pending']:
                raise ValueError('partial evidence requires scoped pending conclusions: ' + key)
        if (_new_daily_presentation(payload)
                and len(parsed['reader_narrative']) + _report_sections_prose_length(parsed['report_sections']) > 50000):
            raise ValueError('new daily reader and internal sections exceed total prose budget')

    return {key: parsed[key] for key in allowed_fields if key in parsed}


def validate_report_sections(sections, *, allowed_ids):
    """Bounded structural coverage; semantic quality remains the reviewer's job."""
    if not isinstance(sections, dict) or set(sections) != set(DETAILED_TOPICS):
        raise ValueError('reader v4 requires exactly all report topics')
    total = 0
    for key, section in sections.items():
        fields = {*DETAILED_REASONING_FIELDS, 'evidence_ids', 'pending'}
        if key == 'scenarios':
            fields.add('paths')
        if key == 'observation':
            fields.add('cards')
        if not isinstance(section, dict) or set(section) != fields:
            raise ValueError('invalid detailed section fields: ' + key)
        for field in DETAILED_REASONING_FIELDS:
            value = section[field]
            if not isinstance(value, str) or not 24 <= len(value.strip()) <= 4000:
                raise ValueError('substantive bounded reasoning required: ' + key + '.' + field)
            total += len(value)
        ids = section['evidence_ids']
        if (not isinstance(ids, list) or len(ids) > 32
                or any(not isinstance(i, str) or i not in allowed_ids for i in ids)):
            raise ValueError('unknown detailed evidence id: ' + key)
        # Every topic anchors to its own supplied scope, including explicit
        # absence evidence; a global source list is not a module citation.
        if 'detailed:' + key not in ids:
            raise ValueError('missing scoped detailed evidence id: ' + key)
        pending = section['pending']
        if (not isinstance(pending, list) or len(pending) > 12
                or any(not isinstance(p, str) or not p.strip() or len(p) > 1600 for p in pending)):
            raise ValueError('invalid pending conclusions: ' + key)
        total += sum(len(p) for p in pending)
        if key in {'scenarios', 'observation'}:
            group = section['paths' if key == 'scenarios' else 'cards']
            names = {'main', 'up', 'down'} if key == 'scenarios' else {'flat', 'long', 'short'}
            keys = {'macro', 'funds', 'price', 'region', 'trigger', 'invalidation', 'window'} if key == 'scenarios' else {'4H', '1H', '15m', 'invalidation'}
            if not isinstance(group, dict) or set(group) != names:
                raise ValueError('incomplete conditional paths/cards')
            for row in group.values():
                if (not isinstance(row, dict) or set(row) != keys
                        or any(not isinstance(v, str) or not 12 <= len(v.strip()) <= 1600 for v in row.values())):
                    raise ValueError('missing path/card conditions')
                total += sum(len(v) for v in row.values())
    if total > 50000:
        raise ValueError('detailed report exceeds total prose budget')
    return sections


def _report_sections_prose_length(sections: Mapping[str, Any]) -> int:
    total = 0
    for section in sections.values():
        total += sum(len(section[field]) for field in DETAILED_REASONING_FIELDS)
        total += sum(len(value) for value in section.get('pending', []))
        for group_name in ('paths', 'cards'):
            total += sum(len(value) for row in section.get(group_name, {}).values() for value in row.values())
    return total


def _validate_fields(parsed: Mapping[str, Any], *, reader_narrative_max: int = 14000) -> list[str]:
    for key in _TEXT_FIELDS:
        if key not in parsed and key in _OPTIONAL_FIELDS:
            continue
        if not isinstance(parsed.get(key), str) or not parsed[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
        if len(parsed[key]) > (reader_narrative_max if key == 'reader_narrative' else _MAX_TEXT_LENGTH):
            raise ValueError(f"{key} is too long")
    for key in _LIST_FIELDS:
        if key not in parsed and key in _OPTIONAL_FIELDS:
            continue
        value = parsed.get(key)
        max_items = _MAX_EVIDENCE_IDS if key == "evidence_ids" else _MAX_ITEMS
        if not isinstance(value, list) or len(value) > max_items:
            raise ValueError(f"{key} must be a bounded list")
        if any(not isinstance(item, str) or not item.strip() or len(item) > _MAX_TEXT_LENGTH for item in value):
            raise ValueError(f"{key} contains an invalid item")
        if key == "evidence_ids" and len(set(value)) != len(value):
            raise ValueError("evidence_ids must be unique")
    return list(parsed["evidence_ids"])


def _numeric_tokens(value: Any) -> set[str]:
    tokens: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for child in item.values():
                visit(child)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for child in item:
                visit(child)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            tokens.add(_number_key(str(item)))
        elif isinstance(item, str):
            tokens.update(_number_key(token) for token in _NUMBER_RE.findall(item))

    visit(value)
    return tokens


def _number_key(value: str) -> str:
    normalized = value.strip().rstrip("%").replace(",", "")
    try:
        return format(Decimal(normalized).normalize(), "f")
    except (InvalidOperation, ValueError):
        return normalized


def _numeric_review(parsed: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    narrative = {key: value for key, value in parsed.items() if key != "evidence_ids"}
    unknown = sorted(_numeric_tokens(narrative) - _numeric_tokens(payload))
    return {"status": "requires_verification" if unknown else "input_tokens_only",
            "unverified_mentions": unknown, "promoted_to_facts": False,
            "method": "numeric_token_screen_not_claim_level_fact_verification"}


def _apply_success(
    output: AgentOutput,
    *,
    parsed: dict[str, Any],
    raw_response: str,
    response: Any,
    messages: list[dict[str, str]],
    prompt_payload: dict[str, Any],
) -> AgentOutput:
    payload = deepcopy(output.input_payload) if isinstance(output.input_payload, dict) else {}
    invalidations = _append_many(output.invalidation_conditions, "[MODEL] 状态限制：", parsed["state_limitations"])
    invalid_conditions = _append_many(output.invalid_conditions, "[MODEL] 状态限制：", parsed["state_limitations"])
    metadata = {
        "schema_version": RESEARCH_SYNTHESIS_SCHEMA_VERSION,
        "input_validation": payload.get("input_validation"),
        "status": "success",
        "generated_by": "llm",
        "data_category": "external_opinion",
        "allowed_fields": list(_ALLOWED_FIELDS),
        "analysis": parsed,
        "proposal_scope": "model_inference_not_canonical_decision",
        "analysis_policy": "open_reasoning_with_fact_and_write_boundaries",
        "numeric_review": _numeric_review(parsed, prompt_payload),
        "input_metrics": input_metrics({k: v for k, v in prompt_payload.items() if k != "macro_review"}),
        "macro_review": prompt_payload.get("macro_review"),
        "evidence_ids": list(parsed["evidence_ids"]),
        "prompt_input_snapshot_id": output.snapshot_id,
    }
    if 'research_quality_standard' in prompt_payload:
        review_status = (prompt_payload.get('macro_review') or {}).get('status', 'unavailable')
        eligible = review_status == 'pass'
        metadata.update({
            'quality_gate_version': GATE_VERSION,
            'generation_status': 'success',
            'review_status': review_status,
            'quality_eligible': eligible,
            'status': 'success' if eligible else 'quality_blocked',
        })
        if (prompt_payload.get('macro_review') or {}).get('quality_failure'):
            metadata['quality_failure'] = deepcopy(prompt_payload['macro_review']['quality_failure'])
    if prompt_payload.get('report_profile', {}).get('version') == DETAILED_PROFILE_VERSION:
        metadata['research_quality_standard'] = deepcopy(prompt_payload.get('research_quality_standard'))
        metadata['report_profile_version'] = DETAILED_PROFILE_VERSION
        metadata['evidence_catalog_ids'] = [r['evidence_id'] for r in prompt_payload.get('evidence_catalog', [])]
        metadata['allowed_fields'] = list(_DETAILED_ALLOWED_FIELDS)
        metadata['report_coverage'] = {
            'prose_contract': 'complete', 'analytic_quality': 'requires_content_review',
            'financial_evidence': {key: value['availability'] for key, value in prompt_payload['report_profile']['modules'].items()},
            'macro_review_status': (prompt_payload.get('macro_review') or {}).get('status', 'unavailable'),
            'publish_allowed': 'unchanged_external_gate',
        }
    payload["research_synthesis"] = metadata
    if metadata.get('quality_eligible') is False:
        # Retain the challenged draft and call identity for audit. Do not copy
        # unapproved claims into the coordinator's summary or decision fields.
        return output.model_copy(update={
            'input_payload': payload,
            'llm_model': _response_value(response, 'model'),
            'llm_provider': _response_value(response, 'provider'),
            'llm_usage': _response_value(response, 'usage'),
            'llm_latency_ms': _response_value(response, 'latency_ms'),
            'llm_audit_id': _response_value(response, 'audit_id'),
            'prompt_messages': messages, 'llm_raw_output': raw_response,
            'data_quality': _append_unique(output.data_quality, 'research_quality_blocked'),
        })
    evidence_refs = [*output.evidence_refs, {"source": "gold_workflow", "snapshot_id": output.snapshot_id, "evidence_ids": list(parsed["evidence_ids"]), "generated_by": "llm"}]
    return output.model_copy(
        update={
            "key_findings": _append_many(_append_unique(output.key_findings, f"[MODEL] 主导因素解释：{parsed['dominant_factor']}"), "[MODEL] 模块复核：", parsed.get("module_challenges", [])),
            "risk_points": _append_many(output.risk_points, "[MODEL] 反证：", parsed["counter_evidence"]),
            "invalid_conditions": invalid_conditions,
            "invalidation_conditions": invalidations,
            "watchlist": _append_many(_append_many(output.watchlist, "[MODEL] 共振/迁移观察：", parsed["convergence_transition"]), "[MODEL] 改变判断的证据：", parsed.get("what_would_change_my_mind", [])),
            "summary": _append_summary(output.summary, parsed.get("independent_assessment") or parsed["dominant_factor"]),
            "evidence_refs": evidence_refs,
            "input_payload": payload,
            "llm_model": _response_value(response, "model"),
            "llm_provider": _response_value(response, "provider"),
            "llm_usage": _response_value(response, "usage"),
            "llm_latency_ms": _response_value(response, "latency_ms"),
            "llm_audit_id": _response_value(response, "audit_id"),
            "prompt_messages": messages,
            "llm_raw_output": raw_response,
            "data_quality": _append_unique(output.data_quality, "llm_enrichment"),
        }
    )


def _apply_rule_fallback(
    output: AgentOutput,
    *,
    messages: list[dict[str, str]],
    prompt_payload: dict[str, Any],
    reason_code: str,
    raw_response: str | None,
    quality_failure: dict | None = None,
    quality_required: bool = False,
) -> AgentOutput:
    payload = deepcopy(output.input_payload) if isinstance(output.input_payload, dict) else {}
    payload["research_synthesis"] = {
        "schema_version": RESEARCH_SYNTHESIS_SCHEMA_VERSION,
        "status": "rule_fallback",
        "generated_by": "deterministic_coordinator",
        "failure_reason": reason_code,
        "allowed_fields": list(_ALLOWED_FIELDS),
        "evidence_ids": [],
        "prompt_input_snapshot_id": output.snapshot_id,
    }
    if quality_required or quality_failure is not None or 'research_quality_standard' in prompt_payload:
        payload['research_synthesis'].update({
            'input_validation': deepcopy(payload.get('input_validation')),
            'research_quality_standard': deepcopy(prompt_payload.get('research_quality_standard')),
            'quality_gate_version': GATE_VERSION,
            'generation_status': 'unavailable' if quality_failure is not None else 'failed',
            'review_status': 'not_run', 'quality_eligible': False,
        })
        if quality_failure is not None:
            payload['research_synthesis']['quality_failure'] = deepcopy(quality_failure)
    # Keep the actual response out of a failed artifact.  The shared gateway
    # audit retains the call record; this output only records a safe reason code.
    _ = messages, prompt_payload, raw_response
    return output.model_copy(
        update={
            "input_payload": payload,
            "data_quality": _append_unique(output.data_quality, "rule_fallback"),
        }
    )


def _response_value(response: Any, key: str) -> Any:
    if isinstance(response, Mapping):
        return response.get(key)
    return getattr(response, key, None)


def _append_summary(summary: str, dominant_factor: str) -> str:
    suffix = f" 综合 Agent 解释：{dominant_factor}"
    return summary if suffix in summary else f"{summary}{suffix}"


def _append_many(existing: list[str], prefix: str, values: Sequence[str]) -> list[str]:
    result = list(existing)
    for value in values:
        result = _append_unique(result, f"{prefix}{value}")
    return result


def _append_unique(existing: list[str], value: str) -> list[str]:
    result = list(existing)
    if value and value not in result:
        result.append(value)
    return result


__all__ = [
    "GOLD_WORKFLOW_SCHEMA_VERSION",
    "RESEARCH_SYNTHESIS_SCHEMA_VERSION",
    "enrich_research_coordinator",
]
