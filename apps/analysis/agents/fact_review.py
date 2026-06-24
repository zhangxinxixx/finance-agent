from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError

from database.models.analysis import AgentOutput
from database.models.report import ReportItem
from database.queries.analysis import list_agent_outputs, upsert_agent_output
from database.queries.review import upsert_review_item


_PROMPT_VERSION = "fact_review_rules_v1"
_SKIP_AGENT_NAMES = {"fact_review_agent", "synthesis_agent", "coordinator", "coordinator_agent"}
_UNAVAILABLE_SOURCE_STATUSES = {"unavailable", "failed", "error"}
_CONFLICT_CLAIM_TYPES = {"market_view", "strategy_condition", "causal_inference"}
_REVIEW_QUEUE_VERDICTS = {"unsupported", "contradicted"}


def build_fact_review_prompt_template() -> str:
    return """你是 finance-agent 的事实审查 Agent，默认使用简体中文。

任务边界：
1. 不改写 raw / parsed / features。
2. 只审查 claims、source_refs、evidence_refs、上游 Agent bias。
3. 输出 verdict 仅允许：supported / partially_supported / unsupported / contradicted / insufficient_evidence。

规则：
- claim 同时具备 source_refs 与 evidence_refs，且来源状态可用 => supported
- 仅具备 source_refs 或 evidence_refs 之一 => partially_supported
- 同时缺少 source_refs 与 evidence_refs => unsupported
- 来源状态为 unavailable / failed / error，或上游 Agent 状态不可用 => insufficient_evidence
- bullish 与 bearish Agent 同时存在时，market_view / strategy_condition / causal_inference claims 标为 contradicted

输入模板：
{{reviewed_agent_outputs}}

输出要求：
- 逐条输出 claim_id、verdict、reason、conflicting_refs、suggested_action
- 汇总 verdict_counts、fact_review_status、unsupported_claim_ids、conflicted_claim_ids
"""


def build_fact_review_agent_output_payload(
    agent_outputs: Iterable[AgentOutput],
    *,
    snapshot_id: str | None = None,
    asset: str | None = None,
    trade_date: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    review_targets = [row for row in agent_outputs if row.agent_name not in _SKIP_AGENT_NAMES]
    if not review_targets:
        raise ValueError("fact_review_agent requires at least one upstream agent output")

    reference = review_targets[0]
    resolved_snapshot_id = snapshot_id or reference.snapshot_id
    resolved_asset = asset or reference.asset
    resolved_trade_date = trade_date or _iso_date(reference.trade_date)
    resolved_run_id = run_id or reference.run_id

    conflict_map = _build_conflict_map(review_targets)
    claim_reviews: list[dict[str, Any]] = []

    for row in review_targets:
        for claim in _claims_from_row(row):
            verdict, reason, conflicting_refs = _review_claim(claim, row, conflict_map)
            claim_reviews.append(
                {
                    "claim_id": str(claim.get("claim_id") or f"{row.agent_name}:claim"),
                    "verdict": verdict,
                    "reason": reason,
                    "conflicting_refs": conflicting_refs,
                    "suggested_action": _suggested_action(verdict),
                    "reviewer_agent_id": "fact_review_agent",
                }
            )

    verdict_counts = Counter(review["verdict"] for review in claim_reviews)
    counts = {
        "supported": verdict_counts.get("supported", 0),
        "partially_supported": verdict_counts.get("partially_supported", 0),
        "unsupported": verdict_counts.get("unsupported", 0),
        "contradicted": verdict_counts.get("contradicted", 0),
        "insufficient_evidence": verdict_counts.get("insufficient_evidence", 0),
    }
    fact_review_status = _fact_review_status(counts, len(claim_reviews))
    summary = _build_summary_text(counts)
    reviewed_agent_outputs = [
        {
            "agent_output_id": row.id,
            "agent_name": row.agent_name,
            "module": row.module,
            "snapshot_id": row.snapshot_id,
            "run_id": row.run_id,
            "bias": row.bias,
            "status": row.status,
            "source_refs": row.source_refs or [],
            "claims": _claims_from_row(row),
        }
        for row in review_targets
    ]
    source_refs = _dedupe_dicts(ref for row in review_targets for ref in (row.source_refs or []))
    key_findings = _build_key_findings(counts, review_targets)
    risk_points = _build_risk_points(claim_reviews)
    invalid_conditions = _build_invalid_conditions(counts)
    confidence = _review_confidence(counts, len(claim_reviews))

    return {
        "snapshot_id": resolved_snapshot_id,
        "analysis_snapshot_db_id": reference.analysis_snapshot_db_id,
        "asset": resolved_asset,
        "trade_date": resolved_trade_date,
        "run_id": resolved_run_id,
        "agent_name": "fact_review_agent",
        "module": "fact_review",
        "version": "1.0",
        "status": _agent_status(fact_review_status),
        "bias": "mixed" if fact_review_status == "conflicted" else "neutral",
        "confidence": confidence,
        "input_snapshot_ids": {row.agent_name: row.snapshot_id for row in review_targets},
        "source_refs": source_refs,
        "key_findings": key_findings,
        "risk_points": risk_points,
        "watchlist": [row.agent_name for row in review_targets],
        "invalid_conditions": invalid_conditions,
        "summary": summary,
        "payload": {
            "generated_by": "rule",
            "prompt_version": _PROMPT_VERSION,
            "prompt_messages": [
                {"role": "system", "content": "你是 finance-agent 的事实审查 Agent，默认使用简体中文。"},
                {"role": "user", "content": build_fact_review_prompt_template()},
            ],
            "input_payload": {
                "reviewed_agent_outputs": reviewed_agent_outputs,
            },
            "fact_review_status": fact_review_status,
            "review_scope": ["claims", "source_refs", "evidence_refs", "agent_bias_conflict"],
            "reviewed_agent_outputs": reviewed_agent_outputs,
            "verdict_counts": counts,
            "claim_reviews": claim_reviews,
            "supported_claim_ids": [item["claim_id"] for item in claim_reviews if item["verdict"] == "supported"],
            "partially_supported_claim_ids": [
                item["claim_id"] for item in claim_reviews if item["verdict"] == "partially_supported"
            ],
            "unsupported_claim_ids": [item["claim_id"] for item in claim_reviews if item["verdict"] == "unsupported"],
            "conflicted_claim_ids": [item["claim_id"] for item in claim_reviews if item["verdict"] == "contradicted"],
            "insufficient_evidence_claim_ids": [
                item["claim_id"] for item in claim_reviews if item["verdict"] == "insufficient_evidence"
            ],
            "claims": [],
            "artifact_refs": [],
        },
    }


def persist_fact_review_agent_output(
    session: Any,
    *,
    snapshot_id: str,
) -> dict[str, Any]:
    payload = build_fact_review_agent_output_payload(list_agent_outputs(session, snapshot_id), snapshot_id=snapshot_id)
    row = upsert_agent_output(session, payload)
    review_items = _sync_review_items(session, row)
    return {
        "agent_output_id": row.id,
        "snapshot_id": row.snapshot_id,
        "run_id": row.run_id,
        "fact_review_status": row.payload.get("fact_review_status"),
        "claim_review_count": len(row.payload.get("claim_reviews") or []),
        "review_item_count": review_items,
    }


def _sync_review_items(session: Any, row: AgentOutput) -> int:
    payload = row.payload if isinstance(row.payload, dict) else {}
    reviewed_agent_outputs = payload.get("reviewed_agent_outputs")
    claim_reviews = payload.get("claim_reviews")
    if not isinstance(reviewed_agent_outputs, list) or not isinstance(claim_reviews, list):
        return 0

    claim_context = _build_claim_context(reviewed_agent_outputs)
    impact_report_ids = _find_related_report_ids(session, run_id=row.run_id, snapshot_id=row.snapshot_id)
    queued = 0

    for review in claim_reviews:
        if not isinstance(review, dict):
            continue
        verdict = str(review.get("verdict") or "")
        if verdict not in _REVIEW_QUEUE_VERDICTS:
            continue
        claim_id = str(review.get("claim_id") or "")
        if not claim_id:
            continue
        context = claim_context.get(claim_id)
        if context is None:
            continue

        review_id = f"fact-review:{context['agent_output_id']}:{claim_id}"
        upsert_review_item(
            session,
            {
                "review_id": review_id,
                "run_id": context["run_id"] or row.run_id,
                "source_module": context["source_module"],
                "source_step_id": row.id,
                "agent_output_id": context["agent_output_id"],
                "claim_id": claim_id,
                "severity": "error" if verdict == "contradicted" else "warning",
                "reason": str(review.get("reason") or "fact review requires manual confirmation"),
                "impact_modules": _impact_modules(context["agent_name"]),
                "impact_report_ids": impact_report_ids,
                "source_refs": context["source_refs"],
                "evidence_refs": _normalize_evidence_refs(context["evidence_refs"]),
                "suggested_action": review.get("suggested_action") or "manual_review",
                "status": "pending",
            },
        )
        queued += 1

    return queued


def _build_claim_context(reviewed_agent_outputs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    context: dict[str, dict[str, Any]] = {}
    for item in reviewed_agent_outputs:
        if not isinstance(item, dict):
            continue
        claims = item.get("claims")
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            claim_id = str(claim.get("claim_id") or "")
            if not claim_id:
                continue
            context[claim_id] = {
                "agent_output_id": str(item.get("agent_output_id") or ""),
                "agent_name": str(item.get("agent_name") or ""),
                "source_module": str(item.get("module") or item.get("agent_name") or "fact_review"),
                "run_id": item.get("run_id"),
                "source_refs": _claim_source_refs(claim, item),
                "evidence_refs": claim.get("evidence_refs") if isinstance(claim.get("evidence_refs"), list) else [],
            }
    return context


def _claim_source_refs(claim: dict[str, Any], reviewed_output: dict[str, Any]) -> list[dict[str, Any]]:
    raw = claim.get("source_refs")
    if isinstance(raw, list) and raw:
        return [item for item in raw if isinstance(item, dict)]
    fallback = reviewed_output.get("source_refs")
    if isinstance(fallback, list):
        return [item for item in fallback if isinstance(item, dict)]
    return []


def _normalize_evidence_refs(raw: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            refs.append(
                {
                    "artifact_id": f"evidence-{index}",
                    "artifact_type": _infer_artifact_type(item),
                    "file_path": item,
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        file_path = item.get("file_path") or item.get("artifact_path") or item.get("path")
        if not file_path:
            continue
        refs.append(
            {
                "artifact_id": str(item.get("artifact_id") or f"evidence-{index}"),
                "artifact_type": str(item.get("artifact_type") or _infer_artifact_type(str(file_path))),
                "file_path": str(file_path),
                "version": item.get("version"),
                "generated_at": item.get("generated_at"),
                "sha256": item.get("sha256"),
            }
        )
    return refs


def _infer_artifact_type(path: str) -> str:
    normalized = path.lower()
    if normalized.endswith(".json"):
        return "structured_json"
    if normalized.endswith(".html"):
        return "visual_html"
    return "analysis_md"


def _impact_modules(agent_name: str) -> list[str]:
    if agent_name == "cme_options_agent":
        return ["cme_options", "reports", "report_detail", "agent_tasks", "review_center", "strategy"]
    if agent_name == "jin10_report_analysis_agent":
        return ["dashboard", "reports", "report_detail", "agent_tasks", "review_center"]
    return ["dashboard", "reports", "report_detail", "agent_tasks", "review_center"]


def _find_related_report_ids(session: Any, *, run_id: str | None, snapshot_id: str | None) -> list[str]:
    if run_id is None and snapshot_id is None:
        return []

    stmt = select(ReportItem.report_id)
    if run_id is not None and snapshot_id is not None:
        stmt = stmt.where((ReportItem.run_id == run_id) | (ReportItem.snapshot_id == snapshot_id))
    elif run_id is not None:
        stmt = stmt.where(ReportItem.run_id == run_id)
    else:
        stmt = stmt.where(ReportItem.snapshot_id == snapshot_id)

    try:
        return sorted({str(report_id) for report_id in session.scalars(stmt)})
    except (OperationalError, ProgrammingError):
        return []


def _review_claim(
    claim: dict[str, Any],
    row: AgentOutput,
    conflict_map: dict[str, list[str]],
) -> tuple[str, str, list[dict[str, Any]]]:
    claim_id = str(claim.get("claim_id") or f"{row.agent_name}:claim")
    claim_type = str(claim.get("claim_type") or "market_view")
    source_refs = claim.get("source_refs") if isinstance(claim.get("source_refs"), list) else list(row.source_refs or [])
    evidence_refs = claim.get("evidence_refs") if isinstance(claim.get("evidence_refs"), list) else []
    conflicting_agents = conflict_map.get(row.agent_name, [])

    if row.status in _UNAVAILABLE_SOURCE_STATUSES or _has_unavailable_source(source_refs):
        return (
            "insufficient_evidence",
            "来源状态不可用，当前 claim 无法验证。",
            [],
        )

    if conflicting_agents and claim_type in _CONFLICT_CLAIM_TYPES:
        return (
            "contradicted",
            f"与 {', '.join(conflicting_agents)} 的 bias 冲突，需人工复核。",
            [{"agent_name": agent_name, "reason": "bias_conflict"} for agent_name in conflicting_agents],
        )

    if not source_refs and not evidence_refs:
        return (
            "unsupported",
            "缺少 source_refs 和 evidence_refs，无法形成最小证据链。",
            [],
        )

    if not source_refs or not evidence_refs:
        return (
            "partially_supported",
            "仅具备部分证据链，需补齐 source_refs 或 artifact 证据。",
            [],
        )

    return ("supported", f"Claim {claim_id} 具备基础证据链。", [])


def _build_conflict_map(agent_outputs: list[AgentOutput]) -> dict[str, list[str]]:
    bullish = [row for row in agent_outputs if str(row.bias).lower() == "bullish"]
    bearish = [row for row in agent_outputs if str(row.bias).lower() == "bearish"]
    if not bullish or not bearish:
        return {}

    conflict_map: dict[str, list[str]] = {}
    for row in bullish:
        conflict_map[row.agent_name] = [item.agent_name for item in bearish]
    for row in bearish:
        conflict_map[row.agent_name] = [item.agent_name for item in bullish]
    return conflict_map


def _claims_from_row(row: AgentOutput) -> list[dict[str, Any]]:
    claims = row.payload.get("claims") if isinstance(row.payload, dict) else None
    if not isinstance(claims, list):
        return []
    return [item for item in claims if isinstance(item, dict)]


def _has_unavailable_source(source_refs: list[dict[str, Any]]) -> bool:
    for ref in source_refs:
        status = str(ref.get("status") or "").lower()
        if status in _UNAVAILABLE_SOURCE_STATUSES:
            return True
    return False


def _fact_review_status(counts: dict[str, int], total_claims: int) -> str:
    if total_claims == 0:
        return "unavailable"
    if counts["contradicted"] > 0:
        return "conflicted"
    if counts["unsupported"] > 0 or counts["insufficient_evidence"] > 0:
        return "needs_review"
    if counts["partially_supported"] > 0:
        return "partial"
    return "passed"


def _build_summary_text(counts: dict[str, int]) -> str:
    parts: list[str] = []
    if counts["partially_supported"]:
        parts.append(f"{counts['partially_supported']} 条证据不完整")
    if counts["unsupported"]:
        parts.append(f"{counts['unsupported']} 条缺少证据链")
    if counts["contradicted"]:
        parts.append(f"{counts['contradicted']} 条结论存在 bias 冲突")
    if counts["insufficient_evidence"]:
        parts.append(f"{counts['insufficient_evidence']} 条来源不可验证")
    if not parts:
        return "事实审查通过，所有 claims 均具备基础证据链。"
    return f"事实审查发现 {'、'.join(parts)}。"


def _build_key_findings(counts: dict[str, int], agent_outputs: list[AgentOutput]) -> list[str]:
    findings = [f"已审查 {len(agent_outputs)} 个 Agent 输出，累计 {sum(counts.values())} 条 claims。"]
    if counts["contradicted"]:
        findings.append(f"发现 {counts['contradicted']} 条 bias 冲突 claim。")
    if counts["unsupported"] or counts["insufficient_evidence"]:
        findings.append(
            f"发现 {counts['unsupported'] + counts['insufficient_evidence']} 条需人工补证的 claim。"
        )
    return findings


def _build_risk_points(claim_reviews: list[dict[str, Any]]) -> list[str]:
    risks: list[str] = []
    for review in claim_reviews:
        verdict = review["verdict"]
        if verdict in {"unsupported", "contradicted", "insufficient_evidence"}:
            risks.append(str(review["reason"]))
    return risks[:5]


def _build_invalid_conditions(counts: dict[str, int]) -> list[str]:
    invalid_conditions: list[str] = []
    if counts["contradicted"]:
        invalid_conditions.append("存在跨 Agent bias 冲突时，不得直接生成强方向综合结论。")
    if counts["unsupported"] or counts["insufficient_evidence"]:
        invalid_conditions.append("存在缺证或不可验证 claim 时，不得将其作为页面主结论依据。")
    return invalid_conditions


def _review_confidence(counts: dict[str, int], total_claims: int) -> float:
    if total_claims <= 0:
        return 0.0
    score = counts["supported"] + 0.5 * counts["partially_supported"]
    return round(max(0.0, min(score / total_claims, 1.0)), 2)


def _agent_status(fact_review_status: str) -> str:
    if fact_review_status == "passed":
        return "success"
    if fact_review_status == "unavailable":
        return "unavailable"
    return "partial"


def _suggested_action(verdict: str) -> str | None:
    if verdict == "supported":
        return None
    if verdict == "partially_supported":
        return "补齐缺失的 source_refs 或 artifact 引用。"
    if verdict == "unsupported":
        return "补充原始来源与产出证据后再进入综合分析。"
    if verdict == "contradicted":
        return "降级该 claim，并等待综合分析或人工复核。"
    return "等待来源恢复或补录后重跑事实审查。"


def _dedupe_dicts(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = tuple(sorted((str(k), str(v)) for k, v in item.items()))
        if key in seen:
            continue
        seen.add(key)
        output.append(dict(item))
    return output


def _iso_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
