from __future__ import annotations

from typing import Any, Mapping

from apps.renderer.contracts import WeeklyContextRevisionPayload


def build_weekly_context_revision_payload(
    snapshot: Mapping[str, Any],
    *,
    run_id: str,
) -> WeeklyContextRevisionPayload:
    anchor = _dict(snapshot.get("anchor"))
    baseline_quality = str(anchor.get("baseline_quality_status") or "needs_review")
    confirmation_matrix = _dict_of_dicts(snapshot.get("confirmation_matrix"))
    quality_flags = _strings(snapshot.get("quality_flags"))
    if baseline_quality != "accepted" and "baseline_needs_review" not in quality_flags:
        quality_flags.append("baseline_needs_review")

    required_confirmations = {
        "price": {"observed", "confirmed"},
        "rates": {"confirmed"},
        "options": {"confirmed"},
    }
    confirmations_ready = all(
        str(confirmation_matrix.get(key, {}).get("status") or "pending") in accepted_statuses
        for key, accepted_statuses in required_confirmations.items()
    )
    publish_allowed = (
        str(snapshot.get("status") or "blocked") == "ready"
        and baseline_quality == "accepted"
        and confirmations_ready
        and not quality_flags
    )
    quality_status = "accepted" if publish_allowed else (
        "blocked" if str(snapshot.get("status") or "") == "blocked" else "needs_review"
    )

    claims = [dict(item) for item in snapshot.get("baseline_claims") or [] if isinstance(item, Mapping)]
    revisions = [
        _revise_claim(
            claim,
            baseline_quality=baseline_quality,
            confirmation_matrix=confirmation_matrix,
        )
        for claim in claims
    ]
    action_counts = {action: 0 for action in ("maintain", "strengthen", "weaken", "invalidate", "pending")}
    for item in revisions:
        action_counts[str(item["action"])] += 1
    executive_summary = (
        "周报基线结论已按最新价格、利率、期权和持仓证据逐项复核："
        f"维持 {action_counts['maintain']} 项，强化 {action_counts['strengthen']} 项，"
        f"削弱 {action_counts['weaken']} 项，推翻 {action_counts['invalidate']} 项，"
        f"待确认 {action_counts['pending']} 项。"
    )
    risk = _dict(snapshot.get("revision_risk"))
    risk["quality_flags"] = _dedupe([*_strings(risk.get("quality_flags")), *quality_flags])
    if not publish_allowed:
        risk["level"] = "needs_review"
        if baseline_quality != "accepted":
            risk["reason"] = "周报基线尚未通过质量审核，修正结果仅供观察。"

    return WeeklyContextRevisionPayload.model_validate(
        {
            "report_type": "weekly_context_revision",
            "schema_version": "1.0.0",
            "asset": str(snapshot.get("asset") or "XAUUSD"),
            "trade_date": str(snapshot.get("trade_date") or ""),
            "run_id": run_id,
            "context_as_of": str(snapshot.get("context_as_of") or ""),
            "anchor": anchor,
            "input_snapshot_ids": _dict(snapshot.get("input_snapshot_ids")),
            "freshness": _dict_of_dicts(snapshot.get("freshness")),
            "baseline_claims": claims,
            "new_evidence": [
                dict(item) for item in snapshot.get("new_evidence") or [] if isinstance(item, Mapping)
            ],
            "claim_revisions": revisions,
            "executive_summary": executive_summary,
            "confirmation_matrix": confirmation_matrix,
            "positioning_check": _dict(snapshot.get("positioning_check")),
            "dominant_transmission_chain": _dict(snapshot.get("dominant_transmission_chain")),
            "scenario_updates": [
                dict(item) for item in snapshot.get("scenario_updates") or [] if isinstance(item, Mapping)
            ],
            "watch_items": [
                dict(item) for item in snapshot.get("watch_items") or [] if isinstance(item, Mapping)
            ],
            "revision_risk": risk,
            "quality_status": quality_status,
            "publication_status": "accepted" if publish_allowed else "observe",
            "publish_allowed": publish_allowed,
            "analysis_provenance": {
                "source": "deterministic_fallback",
                "model": None,
                "provider": None,
                "reasoning_effort": None,
                "prompt_version": None,
                "llm_status": "not_invoked",
            },
            "source_refs": [
                dict(item) for item in snapshot.get("source_refs") or [] if isinstance(item, Mapping)
            ],
        }
    )


def render_weekly_context_revision_source_markdown(snapshot: Mapping[str, Any]) -> str:
    anchor = _dict(snapshot.get("anchor"))
    freshness = _dict_of_dicts(snapshot.get("freshness"))
    input_snapshot_ids = _dict(snapshot.get("input_snapshot_ids"))
    lines = [
        "# Weekly Context Revision Sources",
        "",
        f"- article_id: {anchor.get('article_id') or 'unknown'}",
        f"- baseline_report_date: {anchor.get('report_date') or 'unknown'}",
        f"- baseline_quality_status: {anchor.get('baseline_quality_status') or 'unknown'}",
        f"- context_as_of: {snapshot.get('context_as_of') or 'unknown'}",
        "",
        "## Input Snapshots",
        "",
    ]
    for key, value in input_snapshot_ids.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Freshness", ""])
    for key, value in freshness.items():
        lines.append(
            f"- {key}: status={value.get('status') or 'unknown'}, as_of={value.get('as_of') or 'unknown'}"
        )
    lines.append("")
    return "\n".join(lines)


def render_weekly_context_revision_analysis_markdown(payload: Mapping[str, Any]) -> str:
    structured = WeeklyContextRevisionPayload.model_validate(dict(payload))
    observe_suffix = "（仅供观察）" if not structured.publish_allowed else ""
    action_labels = {
        "maintain": "维持",
        "strengthen": "强化",
        "weaken": "削弱",
        "invalidate": "推翻",
        "pending": "待确认",
    }
    matrix_labels = {
        "price": "价格确认",
        "rates": "利率确认",
        "options": "期权确认",
        "macro": "宏观确认",
        "geopolitical": "地缘确认",
    }
    lines = [
        f"# XAUUSD 周报最新上下文修正{observe_suffix}",
        "",
        f"- 周报锚点：{structured.anchor.report_date} / {structured.anchor.article_id}",
        f"- 上下文截止：{structured.context_as_of}",
        f"- 质量状态：{structured.quality_status}",
        "",
        "## 基线结论修正",
        "",
        structured.executive_summary,
        "",
    ]
    for item in structured.claim_revisions:
        lines.append(
            f"- **{action_labels[item.action]}**：{item.original_claim}  "
            f"原因：{item.reason}"
        )
    lines.extend(["", "## 确认矩阵", ""])
    for key, label in matrix_labels.items():
        item = structured.confirmation_matrix.get(key) or {}
        lines.append(f"- {label}：{item.get('status') or 'pending'}（as_of={item.get('as_of') or item.get('trade_date') or 'unknown'}）")
    lines.extend(["", "## 主导传导链", ""])
    chain = structured.dominant_transmission_chain
    lines.append(f"- {chain.get('label') or '尚未形成可验证的主导传导链。'}")
    if chain.get("dominant_driver"):
        lines.append(f"- 主导驱动：{chain['dominant_driver']}")
    lines.extend(["", "## 情景更新", ""])
    if structured.scenario_updates:
        for item in structured.scenario_updates:
            lines.append(f"- {item.get('path') or item.get('label') or '情景'}：{item.get('summary') or item.get('status') or '待确认'}")
    else:
        lines.append("- 暂无可确定升级的情景，继续等待确认条件。")
    lines.extend(["", "## 下一步观察", ""])
    if structured.watch_items:
        for item in structured.watch_items:
            lines.append(f"- {item.get('label') or item.get('title') or '观察项'}")
    else:
        lines.append("- 无新增观察项。")
    lines.extend(["", "## 修正风险", ""])
    lines.append(f"- {structured.revision_risk.get('reason') or '暂无额外风险说明。'}")
    lines.append("")
    return "\n".join(lines)


def _revise_claim(
    claim: Mapping[str, Any],
    *,
    baseline_quality: str,
    confirmation_matrix: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    claim_id = str(claim.get("claim_id") or "claim")
    original = str(claim.get("claim") or "未提取到基线主张")
    category = str(claim.get("category") or "unknown")
    rates = confirmation_matrix.get("rates") or {}
    price = confirmation_matrix.get("price") or {}
    options = confirmation_matrix.get("options") or {}
    real_10y = _number(rates.get("real_10y"))
    us10y = _number(rates.get("us10y"))
    current_price = _number(price.get("current_price"))
    gamma_zero = _number(options.get("gamma_zero"))
    rate_pressure = (real_10y is not None and real_10y >= 2.0) or (us10y is not None and us10y >= 4.5)
    bullish_claim = any(marker in original for marker in ("底", "反转", "突破", "向上", "修复"))

    action = "pending"
    reason = "现有证据尚不足以改变该基线主张。"
    evidence_refs: list[str] = []
    if category == "market_stage" and rate_pressure and any(marker in original for marker in ("利率", "承压")):
        action = "maintain"
        reason = "10年期名义利率或实际利率仍处高位，利率压制尚未解除。"
        evidence_refs = ["rates"]
    elif bullish_claim and rate_pressure and current_price is not None and gamma_zero is not None and current_price < gamma_zero:
        action = "weaken"
        reason = "价格仍低于期权 Gamma Zero，且实际利率压力未解除，底部或反转主张尚未获得价格与利率共振。"
        evidence_refs = ["price", "rates", "options"]
    elif category == "scenario":
        reason = "情景触发条件需要收盘级价格确认，当前点报价不能代替 4H 或日线确认。"
        evidence_refs = ["price"] if current_price is not None else []

    confidence_before = "medium" if baseline_quality == "accepted" else "low"
    confidence_after = "medium" if action in {"maintain", "weaken"} and baseline_quality == "accepted" else "low"
    return {
        "claim_id": claim_id,
        "original_claim": original,
        "action": action,
        "reason": reason,
        "evidence_refs": evidence_refs,
        "confidence_before": confidence_before,
        "confidence_after": confidence_after,
    }


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _dict_of_dicts(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): dict(item) for key, item in value.items() if isinstance(item, Mapping)}


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value or [] if item]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
