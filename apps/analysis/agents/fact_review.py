from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError

from apps.analysis.agents.schemas import (
    AgentBias,
    AgentOutput as RuntimeAgentOutput,
    AgentStatus,
)
from database.models.analysis import AgentOutput as PersistedAgentOutput
from database.models.report import ReportItem
from database.queries.analysis import list_agent_outputs, upsert_agent_output
from database.queries.review import upsert_review_item


_PROMPT_VERSION = "fact_review_rules_v1"
_SKIP_AGENT_NAMES = {"fact_review_agent", "synthesis_agent", "coordinator", "coordinator_agent"}
_UNAVAILABLE_SOURCE_STATUSES = {"unavailable", "failed", "error"}
_REVIEW_QUEUE_VERDICTS = {"unsupported", "contradicted"}
_STRUCTURED_CONTRADICTION_FIELDS = ("subject", "metric", "predicate", "horizon", "scope", "observation_time")


def build_fact_review_prompt_template() -> str:
    return """你是 finance-agent 的事实审查 Agent，默认使用简体中文。

任务边界：
1. 不改写 raw / parsed / features。
2. 只审查 claims、source_refs、evidence_refs；不根据上游 Agent 的总体 bias 推断事实矛盾。
3. 输出 verdict 仅允许：supported / partially_supported / unsupported / contradicted / insufficient_evidence。

规则：
- claim 同时具备 source_refs 与 evidence_refs，且来源状态可用 => supported
- 仅具备 source_refs 或 evidence_refs 之一 => partially_supported
- 同时缺少 source_refs 与 evidence_refs => unsupported
- 上游 Agent 状态不可用，或 claim 的所有来源均为 unavailable / failed / error => insufficient_evidence
- 仅当 claim 具有完整的 subject、metric、predicate、horizon、scope、observation_time 结构化字段，且存在显式结构化冲突时，才可标为 contradicted；当前非结构化 claim 不推断矛盾

输入模板：
{{reviewed_agent_outputs}}

输出要求：
- 逐条输出 claim_id、verdict、reason、conflicting_refs、suggested_action
- 汇总 verdict_counts、fact_review_status、unsupported_claim_ids、conflicted_claim_ids
"""


def build_fact_review_agent_output_payload(
    agent_outputs: Iterable[PersistedAgentOutput],
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

    claim_reviews: list[dict[str, Any]] = []

    for row in review_targets:
        for claim in _claims_from_row(row):
            verdict, reason, conflicting_refs = _review_claim(claim, row, review_targets)
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
            "review_scope": ["claims", "source_refs", "evidence_refs", "structured_claim_contradiction"],
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


def build_runtime_fact_review_agent_output(
    agent_outputs: Iterable[RuntimeAgentOutput],
    *,
    snapshot_id: str,
    created_at: datetime,
) -> RuntimeAgentOutput:
    """Review in-memory domain outputs without fabricating persistence identifiers."""

    review_targets = [row for row in agent_outputs if row.agent_name not in _SKIP_AGENT_NAMES]
    if not review_targets:
        raise ValueError("fact_review_agent requires at least one upstream agent output")

    claim_reviews: list[dict[str, Any]] = []
    reviewed_agent_outputs: list[dict[str, Any]] = []
    for row in review_targets:
        claims = _claims_from_row(row)
        reviewed_agent_outputs.append(
            {
                "agent_name": row.agent_name,
                "module": row.module,
                "snapshot_id": row.snapshot_id,
                "bias": row.bias.value,
                "status": row.status.value,
                "source_refs": list(row.source_refs),
                "claims": claims,
            }
        )
        for claim in claims:
            verdict, reason, conflicting_refs = _review_claim(claim, row, review_targets)
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
        verdict: verdict_counts.get(verdict, 0)
        for verdict in (
            "supported",
            "partially_supported",
            "unsupported",
            "contradicted",
            "insufficient_evidence",
        )
    }
    fact_review_status = _fact_review_status(counts, len(claim_reviews))
    source_refs = _dedupe_dicts(ref for row in review_targets for ref in row.source_refs)
    evidence_refs = _dedupe_dicts(ref for row in review_targets for ref in row.evidence_refs)
    input_snapshot_ids = {row.agent_name: row.snapshot_id for row in review_targets}
    return RuntimeAgentOutput(
        version="1.0",
        agent_name="fact_review_agent",
        module="fact_review",
        snapshot_id=f"{snapshot_id}:fact_review",
        input_snapshot_ids=input_snapshot_ids,
        bias=AgentBias.MIXED if fact_review_status == "conflicted" else AgentBias.NEUTRAL,
        confidence=_review_confidence(counts, len(claim_reviews)),
        key_findings=_build_key_findings(counts, review_targets),
        risk_points=_build_risk_points(claim_reviews),
        watchlist=[row.agent_name for row in review_targets],
        invalid_conditions=_build_invalid_conditions(counts),
        summary=_build_summary_text(counts),
        source_refs=source_refs,
        evidence_refs=evidence_refs,
        status=AgentStatus(_agent_status(fact_review_status)),
        created_at=created_at,
        data_quality=[f"fact_review:{fact_review_status}"],
        input_payload={
            "generated_by": "rule",
            "prompt_version": _PROMPT_VERSION,
            "fact_review_status": fact_review_status,
            "claim_review_status": (
                "contradicted" if counts["contradicted"] else "unsupported" if counts["unsupported"] else "supported"
            ),
            "reviewed_agent_outputs": reviewed_agent_outputs,
            "verdict_counts": counts,
            "claim_reviews": claim_reviews,
            "unsupported_claim_ids": [item["claim_id"] for item in claim_reviews if item["verdict"] == "unsupported"],
            "conflicted_claim_ids": [item["claim_id"] for item in claim_reviews if item["verdict"] == "contradicted"],
        },
    )


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


def _sync_review_items(session: Any, row: PersistedAgentOutput) -> int:
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
    row: PersistedAgentOutput | RuntimeAgentOutput,
    review_targets: list[PersistedAgentOutput] | list[RuntimeAgentOutput],
) -> tuple[str, str, list[dict[str, Any]]]:
    claim_id = str(claim.get("claim_id") or f"{row.agent_name}:claim")
    source_refs = claim.get("source_refs") if isinstance(claim.get("source_refs"), list) else list(row.source_refs or [])
    evidence_refs = claim.get("evidence_refs") if isinstance(claim.get("evidence_refs"), list) else []

    if row.status in _UNAVAILABLE_SOURCE_STATUSES or _all_sources_unavailable(source_refs):
        return (
            "insufficient_evidence",
            "来源状态不可用，当前 claim 无法验证。",
            [],
        )

    conflicting_refs = _find_structured_conflicts(claim, row, review_targets)
    if conflicting_refs:
        return (
            "contradicted",
            "存在显式结构化事实矛盾，需人工复核。",
            conflicting_refs,
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


def _find_structured_conflicts(
    claim: dict[str, Any],
    row: PersistedAgentOutput | RuntimeAgentOutput,
    review_targets: list[PersistedAgentOutput] | list[RuntimeAgentOutput],
) -> list[dict[str, Any]]:
    """Extension point for explicit structured contradiction matching.

    Existing claim payloads do not have the required identity/time fields, and
    bias or free text is not a fact-conflict signal.  When the schema gains an
    explicit comparable value/polarity contract, implement matching here.
    """

    if not all(claim.get(field) is not None for field in _STRUCTURED_CONTRADICTION_FIELDS):
        return []
    # The current schema has no explicit comparable value/polarity field, so
    # even structurally identified claims cannot be declared contradictory yet.
    _ = row, review_targets
    return []


def _claims_from_row(row: PersistedAgentOutput | RuntimeAgentOutput) -> list[dict[str, Any]]:
    if isinstance(row, RuntimeAgentOutput):
        payload = row.input_payload
        evidence_refs = list(row.evidence_refs)
    else:
        payload = row.payload
        evidence_refs = (
            list(payload.get("evidence_refs") or payload.get("artifact_refs") or [])
            if isinstance(payload, dict)
            else []
        )
    claims = payload.get("claims") if isinstance(payload, dict) else None
    explicit_claims = [item for item in claims if isinstance(item, dict)] if isinstance(claims, list) else []
    if explicit_claims:
        return explicit_claims
    if row.status in _UNAVAILABLE_SOURCE_STATUSES:
        # An unavailable agent's generated summary describes data availability;
        # it is not a market claim.  Explicit claims remain reviewable above.
        return []
    return [
        {
            "claim_id": f"{row.agent_name}:summary",
            "claim_type": "market_view",
            "claim_text": row.summary,
            "source_refs": list(row.source_refs or []),
            "evidence_refs": evidence_refs,
        }
    ]


def _all_sources_unavailable(source_refs: list[dict[str, Any]]) -> bool:
    """Return true only when every declared claim source is explicitly unusable.

    Agent summaries may carry the complete analysis snapshot lineage, including
    optional degraded sources.  One unavailable optional source must not poison
    otherwise usable evidence from the same claim.
    """

    statuses = [
        str(ref.get("status") or "").strip().lower()
        for ref in source_refs
        if isinstance(ref, dict)
    ]
    return bool(statuses) and all(status in _UNAVAILABLE_SOURCE_STATUSES for status in statuses)


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
        parts.append(f"{counts['contradicted']} 条结论存在结构化事实矛盾")
    if counts["insufficient_evidence"]:
        parts.append(f"{counts['insufficient_evidence']} 条来源不可验证")
    if not parts:
        return "事实审查通过，所有 claims 均具备基础证据链。"
    return f"事实审查发现 {'、'.join(parts)}。"


def _build_key_findings(
    counts: dict[str, int],
    agent_outputs: list[PersistedAgentOutput] | list[RuntimeAgentOutput],
) -> list[str]:
    findings = [f"已审查 {len(agent_outputs)} 个 Agent 输出，累计 {sum(counts.values())} 条 claims。"]
    if counts["contradicted"]:
        findings.append(f"发现 {counts['contradicted']} 条结构化事实矛盾 claim。")
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
        invalid_conditions.append("存在结构化事实矛盾时，不得直接生成强方向综合结论。")
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
