from __future__ import annotations

from typing import Any

from apps.api.schemas.claim import Claim, ClaimReview, ClaimReviewVerdict, ClaimType
from apps.api.services._trace_refs import (
    artifact_ref_from_path,
    coerce_artifact_type,
    dedupe_artifact_refs,
    parse_artifact_refs,
    parse_source_refs,
)


_BIAS_LABELS = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
    "mixed": "混合",
    "unavailable": "不可用",
}


def prompt_contract_id(agent_id: str | None) -> str | None:
    if not agent_id:
        return None
    return f"{agent_id}_prompt"


def prompt_metadata_from_row(row) -> dict[str, Any]:
    prompt_version = getattr(row, "prompt_version", None)
    payload = row.payload or {}
    if prompt_version is None:
        return {
            "prompt_id": prompt_contract_id(getattr(row, "agent_name", None)) if row.prompt_version_id else None,
            "prompt_version": payload.get("prompt_version"),
            "prompt_checksum": None,
            "prompt_source_file": None,
        }
    return {
        "prompt_id": prompt_contract_id(prompt_version.agent_id),
        "prompt_version": prompt_version.version,
        "prompt_checksum": prompt_version.prompt_sha256,
        "prompt_source_file": prompt_version.prompt_source,
    }


def _contains_cjk(text: str | None) -> bool:
    if not text:
        return False
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _format_confidence(confidence: Any) -> str:
    try:
        return f"{float(confidence):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def build_summary_zh(
    *,
    agent_name: str,
    display_name: str,
    status: str | None,
    bias: str | None,
    confidence: Any,
    raw_summary: str | None,
) -> str:
    if raw_summary and _contains_cjk(raw_summary):
        return raw_summary

    confidence_text = _format_confidence(confidence)
    bias_label = _BIAS_LABELS.get((bias or "").lower(), bias or "中性")
    status_norm = (status or "").lower()

    if agent_name == "news_agent":
        if status_norm == "unavailable":
            return f"{display_name}只读视图不可用；确信度 {confidence_text}。"
        suffix = "（输入不完整）" if status_norm in {"partial", "failed"} else ""
        return f"{display_name}只读视图：风险={bias_label}{suffix}；确信度 {confidence_text}。"

    if status_norm == "unavailable":
        return f"{display_name}只读视图不可用；确信度 {confidence_text}。"

    if status_norm in {"partial", "failed"}:
        return f"{display_name}只读视图为{bias_label}（输入不完整）；确信度 {confidence_text}。"

    return f"{display_name}只读视图为{bias_label}；确信度 {confidence_text}。"


def build_agent_output_summary(row) -> dict[str, Any]:
    from apps.analysis.agents.registry import resolve_agent_runtime_meta

    payload = row.payload or {}
    runtime_meta = resolve_agent_runtime_meta(row.agent_name)
    summary_zh = build_summary_zh(
        agent_name=row.agent_name,
        display_name=runtime_meta["display_name"],
        status=row.status,
        bias=row.bias,
        confidence=row.confidence,
        raw_summary=row.summary,
    )
    generated_by = payload.get("generated_by")
    if generated_by is None:
        generated_by = "llm" if row.llm_model else "rule"

    artifact_refs = _normalize_artifact_refs(
        payload.get("artifact_refs") if payload.get("artifact_refs") is not None else payload.get("source_artifact_refs"),
    )
    source_refs = [source_ref.model_dump(mode="json") for source_ref in parse_source_refs(row.source_refs)]

    claims = normalize_claims(payload.get("claims"))
    claim_reviews = normalize_claim_reviews(payload.get("claim_reviews"))
    fact_review_status = payload.get("fact_review_status")
    if fact_review_status is None and runtime_meta.get("registry_id") == "synthesis_agent":
        fact_review_status = payload.get("synthesis_status")
    prompt_metadata = prompt_metadata_from_row(row)

    return {
        "agent_output_id": row.id,
        "registry_id": runtime_meta.get("registry_id"),
        "agent_name": row.agent_name,
        "display_name": runtime_meta["display_name"],
        "role": runtime_meta["role"],
        "module": row.module,
        "version": row.version,
        "run_id": row.run_id,
        "snapshot_id": row.snapshot_id,
        "status": row.status,
        "bias": row.bias,
        "confidence": row.confidence,
        "summary": row.summary,
        "summary_zh": summary_zh,
        "key_findings": row.key_findings or [],
        "risk_points": row.risk_points or [],
        "watchlist": row.watchlist or [],
        "invalid_conditions": row.invalid_conditions or [],
        "input_snapshot_ids": row.input_snapshot_ids or {},
        "source_refs": source_refs,
        "artifact_refs": artifact_refs,
        "market_phase": payload.get("market_phase"),
        "regime_drivers": payload.get("regime_drivers"),
        "narrative_md": payload.get("narrative_md", ""),
        "data_category": payload.get("data_category"),
        "evidence_refs": payload.get("evidence_refs") or [],
        "data_quality": payload.get("data_quality") or [],
        "claims": claims,
        "claim_reviews": claim_reviews,
        "claim_count": len(claims),
        "fact_review_status": fact_review_status,
        "synthesis_group_id": payload.get("synthesis_group_id"),
        "generated_by": generated_by,
        "prompt_id": prompt_metadata["prompt_id"],
        "prompt_version": prompt_metadata["prompt_version"],
        "prompt_checksum": prompt_metadata["prompt_checksum"],
        "prompt_source_file": prompt_metadata["prompt_source_file"],
        "llm_model": row.llm_model,
        "llm_usage": row.token_usage,
        "llm_elapsed_seconds": row.llm_elapsed_seconds,
        "prompt_version_id": row.prompt_version_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def normalize_claims(raw_claims: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_claims, list):
        return []
    claims: list[dict[str, Any]] = []
    for index, item in enumerate(raw_claims, start=1):
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id") or f"claim-{index}")
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        claim_type = _coerce_claim_type(item.get("claim_type"))
        source_refs = parse_source_refs(item.get("source_refs"))
        evidence_refs = _parse_evidence_refs(item.get("evidence_refs"))
        confidence = _coerce_confidence(item.get("confidence"))
        claims.append(
            Claim(
                claim_id=claim_id,
                text=text,
                claim_type=claim_type,
                source_refs=source_refs,
                evidence_refs=evidence_refs,
                confidence=confidence,
            ).model_dump(mode="json")
        )
    return claims


def normalize_claim_reviews(raw_reviews: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_reviews, list):
        return []
    reviews: list[dict[str, Any]] = []
    for index, item in enumerate(raw_reviews, start=1):
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id") or f"claim-{index}")
        reason = str(item.get("reason") or "").strip()
        verdict = _coerce_claim_review_verdict(item.get("verdict"))
        conflicting_refs = _parse_evidence_refs(item.get("conflicting_refs"))
        reviews.append(
            ClaimReview(
                claim_id=claim_id,
                verdict=verdict,
                reason=reason or "No review reason provided.",
                conflicting_refs=conflicting_refs,
                suggested_action=_optional_string(item.get("suggested_action")),
                reviewer_agent_id=_optional_string(item.get("reviewer_agent_id")),
            ).model_dump(mode="json")
        )
    return reviews


def _coerce_claim_type(raw: Any) -> ClaimType:
    try:
        return ClaimType(str(raw))
    except ValueError:
        return ClaimType.market_view


def _coerce_claim_review_verdict(raw: Any) -> ClaimReviewVerdict:
    try:
        return ClaimReviewVerdict(str(raw))
    except ValueError:
        return ClaimReviewVerdict.insufficient_evidence


def _coerce_confidence(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(round(value, 4), 1.0))


def _optional_string(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _parse_evidence_refs(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    refs: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if isinstance(item, str):
            refs.append(
                artifact_ref_from_path(
                    item,
                    artifact_id=f"evidence-{index + 1}",
                ).model_dump(mode="json")
            )
            continue
        if not isinstance(item, dict):
            continue
        file_path = item.get("file_path") or item.get("artifact_path") or item.get("path")
        if file_path:
            artifact_id = str(item.get("artifact_id") or f"evidence-{index + 1}")
            refs.append(
                artifact_ref_from_path(
                    str(file_path),
                    artifact_id=artifact_id,
                )
                .model_copy(
                    update={
                        "artifact_type": coerce_artifact_type(item.get("artifact_type"), str(file_path)),
                        "version": item.get("version"),
                        "generated_at": item.get("generated_at"),
                        "sha256": item.get("sha256"),
                    }
                )
                .model_dump(mode="json")
            )
            continue
        refs.extend(source_ref.model_dump(mode="json") for source_ref in parse_source_refs([item]))
    return refs


def _normalize_artifact_refs(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    return [artifact.model_dump(mode="json") for artifact in dedupe_artifact_refs(parse_artifact_refs(raw))]
