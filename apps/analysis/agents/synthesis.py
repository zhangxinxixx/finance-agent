from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from database.models.analysis import AgentOutput
from database.queries.analysis import list_agent_outputs, upsert_agent_output
from database.queries.review import list_review_items


_PROMPT_VERSION = "synthesis_rules_v1"
_SKIP_AGENT_NAMES = {"fact_review_agent", "synthesis_agent", "coordinator", "coordinator_agent"}
_DIRECTIONAL_BIASES = {"bullish", "bearish"}
_REJECTED_VERDICTS = {"unsupported", "contradicted"}
_SOFT_VERDICTS = {"partially_supported", "insufficient_evidence"}


def build_synthesis_prompt_template() -> str:
    return """你是 finance-agent 的综合分析 Agent，默认使用简体中文。

任务边界：
1. 不改写 raw / parsed / features，不生成最终 HTML。
2. 只汇总确定性输入、专项 Agent 输出、fact review 结果和 ReviewItem 状态。
3. unsupported / contradicted claim 必须排除出综合结论，并保留为 warnings。
4. 综合输出必须给出共识、分歧、待复核项和建议阅读顺序。
"""


def build_synthesis_agent_output_payload(
    agent_outputs: Iterable[AgentOutput],
    *,
    review_items: Iterable[Any] | None = None,
    snapshot_id: str | None = None,
    asset: str | None = None,
    trade_date: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    rows = list(agent_outputs)
    domain_outputs = [row for row in rows if row.agent_name not in _SKIP_AGENT_NAMES]
    if not domain_outputs:
        raise ValueError("synthesis_agent requires at least one upstream domain agent output")

    reference = domain_outputs[0]
    fact_review_row = next((row for row in rows if row.agent_name == "fact_review_agent"), None)
    review_lookup = _claim_review_lookup(fact_review_row.payload if fact_review_row is not None else {})
    normalized_review_items = _normalize_review_items(review_items or [])

    included_agent_output_ids: list[str] = []
    excluded_agent_output_ids: list[str] = []
    excluded_claim_ids: list[str] = []
    warnings: list[dict[str, str]] = []
    consensus_points: list[str] = []
    divergent_points: list[str] = []
    reading_order: list[str] = []
    key_findings: list[str] = []
    risk_points: list[str] = []
    included_outputs: list[AgentOutput] = []

    for row in domain_outputs:
        reading_order.append(row.agent_name)
        claims = _claims_from_row(row)
        included_claims: list[dict[str, Any]] = []

        for claim in claims:
            claim_id = str(claim.get("claim_id") or "")
            review = review_lookup.get(claim_id)
            verdict = str(review.get("verdict") or "") if review else ""

            if verdict in _REJECTED_VERDICTS:
                excluded_claim_ids.append(claim_id)
                warnings.append(
                    {
                        "code": f"claim-{verdict}",
                        "message": f"{row.agent_name} 的 claim {claim_id} 已被排除：{review.get('reason') or '需人工复核'}",
                    }
                )
                divergent_points.append(str(claim.get("text") or row.summary))
                continue

            if verdict in _SOFT_VERDICTS:
                warnings.append(
                    {
                        "code": f"claim-{verdict}",
                        "message": f"{row.agent_name} 的 claim {claim_id} 证据不完整：{review.get('reason') or '需补充来源'}",
                    }
                )

            included_claims.append(claim)

        if claims and not included_claims:
            excluded_agent_output_ids.append(row.id)
            continue

        included_outputs.append(row)
        included_agent_output_ids.append(row.id)
        claim_text = str(included_claims[0].get("text") or "").strip() if included_claims else ""
        if claim_text:
            consensus_points.append(claim_text)
            key_findings.append(claim_text)
        else:
            consensus_points.append(row.summary)
            key_findings.append(row.summary)

    review_item_ids = [item["review_id"] for item in normalized_review_items]
    if review_item_ids:
        risk_points.append(f"当前有 {len(review_item_ids)} 条待人工复核项。")
        warnings.append(
            {
                "code": "review-items-pending",
                "message": f"Review Center 中仍有 {len(review_item_ids)} 条待处理问题项。",
            }
        )

    included_biases = [str(row.bias).lower() for row in included_outputs if str(row.bias).lower()]
    bias = _combined_bias(included_biases, divergent_points)
    synthesis_status = _synthesis_status(
        included_count=len(included_outputs),
        warnings=warnings,
        fact_review_status=_fact_review_status(fact_review_row.payload if fact_review_row is not None else {}),
    )
    confidence = _confidence(included_outputs, bias=bias, synthesis_status=synthesis_status, warnings=warnings)

    if divergent_points:
        risk_points.append("存在被事实审查排除或冲突的结论，综合结论已降权处理。")
    if bias == "mixed":
        risk_points.append("多来源方向未形成单边共识。")

    summary = _build_summary_text(
        bias=bias,
        synthesis_status=synthesis_status,
        consensus_count=len(consensus_points),
        divergent_count=len(divergent_points),
        review_item_count=len(review_item_ids),
    )

    source_refs = _dedupe_dicts(ref for row in rows for ref in (row.source_refs or []))
    artifact_refs = _dedupe_dicts(_artifact_refs_from_row(row) for row in rows)
    input_payload = {
        "domain_agent_outputs": [
            {
                "agent_output_id": row.id,
                "agent_name": row.agent_name,
                "bias": row.bias,
                "status": row.status,
                "summary": row.summary,
                "claims": [str(item.get("claim_id")) for item in _claims_from_row(row)],
            }
            for row in domain_outputs
        ],
        "fact_review_output": {
            "agent_output_id": fact_review_row.id if fact_review_row is not None else None,
            "fact_review_status": _fact_review_status(fact_review_row.payload if fact_review_row is not None else {}),
            "claim_reviews": list(review_lookup.values()),
        },
        "review_items": normalized_review_items,
    }

    return {
        "snapshot_id": snapshot_id or reference.snapshot_id,
        "analysis_snapshot_db_id": reference.analysis_snapshot_db_id,
        "asset": asset or reference.asset,
        "trade_date": trade_date or _iso_date(reference.trade_date),
        "run_id": run_id or reference.run_id,
        "agent_name": "synthesis_agent",
        "module": "synthesis",
        "version": "1.0",
        "status": "success" if synthesis_status == "success" else ("unavailable" if synthesis_status == "unavailable" else "partial"),
        "bias": bias,
        "confidence": confidence,
        "input_snapshot_ids": {row.agent_name: row.snapshot_id for row in rows},
        "source_refs": source_refs,
        "key_findings": key_findings[:6],
        "risk_points": risk_points,
        "watchlist": reading_order[:8],
        "invalid_conditions": divergent_points[:8],
        "summary": summary,
        "payload": {
            "generated_by": "rule",
            "prompt_version": _PROMPT_VERSION,
            "prompt_messages": [
                {"role": "system", "content": "你是 finance-agent 的综合分析 Agent，默认使用简体中文。"},
                {"role": "user", "content": build_synthesis_prompt_template()},
            ],
            "input_payload": input_payload,
            "synthesis_status": synthesis_status,
            "fact_review_status": synthesis_status,
            "included_agent_output_ids": included_agent_output_ids,
            "excluded_agent_output_ids": excluded_agent_output_ids,
            "excluded_claim_ids": excluded_claim_ids,
            "review_item_ids": review_item_ids,
            "consensus_points": consensus_points[:8],
            "divergent_points": divergent_points[:8],
            "reading_order": reading_order,
            "warnings": warnings,
            "artifact_refs": artifact_refs,
            "claims": [],
            "claim_reviews": [],
        },
    }


def persist_synthesis_agent_output(session: Any, *, snapshot_id: str) -> dict[str, Any]:
    rows = list_agent_outputs(session, snapshot_id)
    reference = next((row for row in rows if row.agent_name not in _SKIP_AGENT_NAMES), None)
    if reference is None:
        raise ValueError("synthesis_agent requires upstream agent outputs")
    review_items = list_review_items(session, run_id=reference.run_id, limit=500)
    payload = build_synthesis_agent_output_payload(rows, review_items=review_items, snapshot_id=snapshot_id)
    row = upsert_agent_output(session, payload)
    warnings = row.payload.get("warnings") if isinstance(row.payload, dict) else []
    return {
        "agent_output_id": row.id,
        "snapshot_id": row.snapshot_id,
        "run_id": row.run_id,
        "synthesis_status": row.payload.get("synthesis_status"),
        "warning_count": len(warnings or []),
    }


def _claims_from_row(row: AgentOutput) -> list[dict[str, Any]]:
    claims = row.payload.get("claims") if isinstance(row.payload, dict) else None
    if not isinstance(claims, list):
        return []
    return [item for item in claims if isinstance(item, dict)]


def _claim_review_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get("claim_reviews") if isinstance(payload, dict) else None
    lookup: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, list):
        return lookup
    for item in raw:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id") or "")
        if claim_id:
            lookup[claim_id] = item
    return lookup


def _fact_review_status(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return "not_reviewed"
    return str(payload.get("fact_review_status") or "not_reviewed")


def _normalize_review_items(items: Iterable[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            review_id = str(item.get("review_id") or "")
            if not review_id:
                continue
            normalized.append(
                {
                    "review_id": review_id,
                    "claim_id": item.get("claim_id"),
                    "status": item.get("status"),
                    "reason": item.get("reason"),
                }
            )
            continue
        review_id = getattr(item, "review_id", None)
        if not review_id:
            continue
        normalized.append(
            {
                "review_id": str(review_id),
                "claim_id": getattr(item, "claim_id", None),
                "status": getattr(item, "status", None),
                "reason": getattr(item, "reason", None),
            }
        )
    return normalized


def _combined_bias(included_biases: list[str], divergent_points: list[str]) -> str:
    directional = {bias for bias in included_biases if bias in _DIRECTIONAL_BIASES}
    if len(directional) > 1:
        return "mixed"
    if "mixed" in included_biases:
        return "mixed"
    if directional:
        return next(iter(directional))
    if divergent_points:
        return "mixed"
    if "neutral" in included_biases:
        return "neutral"
    return "unavailable"


def _synthesis_status(*, included_count: int, warnings: list[dict[str, str]], fact_review_status: str) -> str:
    if included_count == 0:
        return "unavailable"
    warning_codes = {item["code"] for item in warnings}
    if "claim-contradicted" in warning_codes or "review-items-pending" in warning_codes:
        return "needs_review"
    if fact_review_status in {"conflicted", "needs_review", "partial"} or warning_codes:
        return "partial"
    return "success"


def _confidence(
    included_outputs: list[AgentOutput],
    *,
    bias: str,
    synthesis_status: str,
    warnings: list[dict[str, str]],
) -> float:
    if not included_outputs:
        return 0.0
    baseline = sum(float(row.confidence or 0.0) for row in included_outputs) / len(included_outputs)
    if bias == "mixed":
        baseline -= 0.12
    if synthesis_status == "needs_review":
        baseline -= 0.15
    elif synthesis_status == "partial":
        baseline -= 0.08
    baseline -= min(len(warnings), 3) * 0.03
    return max(0.0, min(round(baseline, 4), 1.0))


def _build_summary_text(
    *,
    bias: str,
    synthesis_status: str,
    consensus_count: int,
    divergent_count: int,
    review_item_count: int,
) -> str:
    bias_text = {
        "bullish": "偏多",
        "bearish": "偏空",
        "neutral": "中性",
        "mixed": "分歧较大",
        "unavailable": "不可用",
    }.get(bias, bias)
    if synthesis_status == "needs_review":
        return f"综合分析当前为{bias_text}，共有 {consensus_count} 条可纳入共识结论，另有 {divergent_count} 条冲突/排除结论与 {review_item_count} 条待复核项。"
    if synthesis_status == "partial":
        return f"综合分析当前为{bias_text}，已有 {consensus_count} 条共识结论，但仍存在 {divergent_count} 条需关注的分歧。"
    if synthesis_status == "unavailable":
        return "综合分析输入不足，当前无法形成稳定结论。"
    return f"综合分析当前为{bias_text}，已形成 {consensus_count} 条可追溯共识结论。"


def _artifact_refs_from_row(row: AgentOutput) -> list[dict[str, Any]]:
    payload = row.payload if isinstance(row.payload, dict) else {}
    artifact_refs = payload.get("artifact_refs")
    if not isinstance(artifact_refs, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in artifact_refs:
        if isinstance(item, str):
            normalized.append({"file_path": item})
        elif isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def _dedupe_dicts(items: Iterable[Any]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, list):
            for nested in item:
                if isinstance(nested, dict):
                    key = repr(sorted(nested.items()))
                    if key not in seen:
                        seen.add(key)
                        deduped.append(nested)
            continue
        if not isinstance(item, dict):
            continue
        key = repr(sorted(item.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
