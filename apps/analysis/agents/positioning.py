from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory

_AGENT_NAME = "positioning_agent"
_MODULE = "positioning"
_VERSION = "1.1"

# Thresholds for the Producer/Merchant + Swap Dealer aggregate proxy.
HEAVY_COMMERCIAL_SHORT_THRESHOLD = -200000
COMMERCIAL_LONG_THRESHOLD = 0

_WATCHLIST = [
    "COT_GOLD",
    "commercial_net",
    "producer_net",
    "swap_net",
    "noncomm_net",
    "open_interest",
]


def analyze_positioning(snapshot: dict[str, Any], *, created_at: datetime | None = None) -> AgentOutput:
    """Analyze already-loaded positioning (CFTC COT) snapshot data without mutating inputs."""

    created_at = created_at or datetime.now(timezone.utc)
    if not isinstance(snapshot, dict):
        return AgentOutput(
            version=_VERSION,
            agent_name=_AGENT_NAME,
            module=_MODULE,
            snapshot_id="unknown",
            input_snapshot_ids={},
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            key_findings=[],
            risk_points=["持仓输入必须是已加载的快照字典。"],
            watchlist=list(_WATCHLIST),
            invalid_conditions=["非字典输入被拒绝；文件/路径读取不在范围内。"],
            summary="Positioning input is unavailable; no read-only conclusion was generated.",
            source_refs=[],
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            data_category=DataCategory.CONFIRMED_DATA,
        )

    snapshot_id = str(snapshot.get("snapshot_id") or "unknown")
    input_snapshot_ids = _input_snapshot_ids(snapshot)
    source_refs = _source_refs(snapshot)
    reports = snapshot.get("macro", {}).get("data", {}).get("cot_reports")
    if isinstance(reports, dict):
        return _analyze_official_reports(snapshot, reports, created_at=created_at)
    positioning = snapshot.get("positioning")

    if not isinstance(positioning, dict) or positioning.get("status") != "available":
        reason = (
            "positioning section is missing"
            if not isinstance(positioning, dict)
            else f"positioning status is {positioning.get('status')!r}"
        )
        return AgentOutput(
            version=_VERSION,
            agent_name=_AGENT_NAME,
            module=_MODULE,
            snapshot_id=snapshot_id,
            input_snapshot_ids=input_snapshot_ids,
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            key_findings=[],
            risk_points=["持仓（CFTC COT）输入不可用。"],
            watchlist=list(_WATCHLIST),
            invalid_conditions=[reason],
            summary="Positioning input is unavailable; no read-only conclusion was generated.",
            source_refs=source_refs,
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            data_category=DataCategory.CONFIRMED_DATA,
        )

    data_any = positioning.get("data")
    data: dict[str, Any] = data_any if isinstance(data_any, dict) else {}

    commercial_net = _to_float(data.get("commercial_net"))
    producer_net = _to_float(data.get("producer_net"))
    swap_net = _to_float(data.get("swap_net"))
    noncomm_net = _to_float(data.get("noncomm_net"))
    total_oi = _to_float(data.get("total_oi"))
    commercial_direction = str(data.get("commercial_direction", "flat"))
    noncomm_direction = str(data.get("noncomm_direction", "flat"))
    extreme_reading = bool(data.get("extreme_reading", False))

    key_findings: list[str] = []
    risk_points: list[str] = []
    invalid_conditions: list[str] = []
    watchlist = list(_WATCHLIST)
    status = AgentStatus.SUCCESS
    confidence = 0.45

    # Track data completeness
    data_points_available = 0
    data_points_missing = 0

    if commercial_net is None:
        status = AgentStatus.UNAVAILABLE
        confidence = 0.0
        invalid_conditions.append("COT commercial_net is missing; no positioning bias can be determined.")
        return AgentOutput(
            version=_VERSION,
            agent_name=_AGENT_NAME,
            module=_MODULE,
            snapshot_id=snapshot_id,
            input_snapshot_ids=input_snapshot_ids,
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            key_findings=[],
            risk_points=["COT commercial_net data is missing from positioning snapshot."],
            watchlist=watchlist,
            invalid_conditions=invalid_conditions,
            summary="持仓数据不可用；未生成只读结论。",
            source_refs=source_refs,
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            data_category=DataCategory.CONFIRMED_DATA,
        )

    data_points_available += 1

    if producer_net is not None and swap_net is not None:
        data_points_available += 2
        key_findings.append(
            f"Producer/Merchant net position: {producer_net:,.0f} contracts."
        )
        key_findings.append(f"Swap Dealer net position: {swap_net:,.0f} contracts.")
    else:
        data_points_missing += 1
        invalid_conditions.append(
            "Producer/Merchant and Swap Dealer breakdown is missing; "
            "commercial_net is only an aggregate compatibility proxy."
        )

    # Determine bias from the compatibility aggregate, without attributing it to producers alone.
    bias: AgentBias
    if commercial_net < HEAVY_COMMERCIAL_SHORT_THRESHOLD:
        bias = AgentBias.BEARISH
        key_findings.append(
            "Commercial aggregate proxy (Producer/Merchant + Swap Dealer) is heavily "
            f"net short ({commercial_net:,.0f} contracts) — bearish positioning signal for gold."
        )
        confidence += 0.18
    elif commercial_net > COMMERCIAL_LONG_THRESHOLD:
        bias = AgentBias.BULLISH
        key_findings.append(
            "Commercial aggregate proxy (Producer/Merchant + Swap Dealer) is net long "
            f"({commercial_net:,.0f} contracts) — bullish positioning signal for gold."
        )
        confidence += 0.12
    else:
        bias = AgentBias.NEUTRAL
        key_findings.append(
            "Commercial aggregate proxy (Producer/Merchant + Swap Dealer) is moderately "
            f"net short ({commercial_net:,.0f} contracts) but not extreme — neutral signal."
        )
        confidence += 0.06

    # Non-commercial (speculative) positioning adds context
    if noncomm_net is not None:
        data_points_available += 1
        if noncomm_net > 0:
            key_findings.append(
                f"Speculators (Managed Money) are net long {noncomm_net:,.0f} contracts — "
                f"crowded long positioning can be a contrarian warning."
            )
            if noncomm_net > 200000:
                risk_points.append(
                    f"Speculative net long is extreme ({noncomm_net:,.0f}); "
                    f"crowded longs increase reversal risk."
                )
                confidence -= 0.04
        else:
            key_findings.append(
                f"Speculators (Managed Money) are net short {abs(noncomm_net):,.0f} contracts."
            )
    else:
        data_points_missing += 1

    # Direction context
    if commercial_direction == "increasing_short":
        key_findings.append(
            "Commercial aggregate proxy is becoming more net short week-over-week — bearish momentum."
        )
        if bias is AgentBias.BEARISH:
            confidence += 0.05
        elif bias is not AgentBias.UNAVAILABLE:
            risk_points.append("Commercial shorts increasing despite non-bearish bias; monitor closely.")
    elif commercial_direction == "increasing_long":
        key_findings.append(
            "Commercial aggregate proxy is becoming more net long week-over-week — bullish momentum."
        )
        if bias is AgentBias.BULLISH:
            confidence += 0.05
        elif bias is not AgentBias.UNAVAILABLE:
            risk_points.append("Commercial longs increasing despite non-bullish bias; monitor closely.")
    else:
        key_findings.append("Commercial aggregate proxy is flat week-over-week.")

    if noncomm_direction == "increasing_long":
        key_findings.append("Speculative longs are increasing — momentum-driven, but watch for crowding.")
    elif noncomm_direction == "increasing_short":
        key_findings.append("Speculative shorts are increasing — bearish momentum from managed money.")

    # Extreme reading
    if extreme_reading:
        risk_points.append(
            "COT commercial aggregate proxy is at an extreme (top/bottom 20% of 52-week range) — "
            "elevated reversal risk."
        )
        confidence -= 0.06
        key_findings.append(
            "Commercial aggregate proxy is at a 52-week extreme — contrarian signal."
        )

    # Open interest
    if total_oi is not None and total_oi > 0:
        data_points_available += 1
        key_findings.append(f"Total open interest: {total_oi:,.0f} contracts.")
        if total_oi > 500000:
            key_findings.append("High open interest suggests strong market participation and liquidity.")
    else:
        data_points_missing += 1

    # Adjust confidence based on data completeness
    if data_points_missing > 0:
        status = AgentStatus.PARTIAL
        confidence -= 0.10 * data_points_missing
        invalid_conditions.append(
            f"Partial positioning data: {data_points_missing} fields missing "
            f"({data_points_available} available)."
        )

    if not key_findings:
        key_findings.append("Positioning data is present but directional signals are insufficient.")

    confidence = _clamp(confidence, 0.0, 0.80 if status is AgentStatus.PARTIAL else 0.85)

    return AgentOutput(
        version=_VERSION,
        agent_name=_AGENT_NAME,
        module=_MODULE,
        snapshot_id=snapshot_id,
        input_snapshot_ids=input_snapshot_ids,
        bias=bias,
        confidence=confidence,
        key_findings=key_findings,
        risk_points=risk_points,
        watchlist=watchlist,
        invalid_conditions=invalid_conditions,
        summary=_summary(bias, status, confidence),
        source_refs=source_refs,
        status=status,
        created_at=created_at,
        data_category=DataCategory.CONFIRMED_DATA,
    )


def _input_snapshot_ids(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("input_snapshot_ids")
    ids = dict(value) if isinstance(value, dict) else {}
    snapshot_id = snapshot.get("snapshot_id")
    if snapshot_id is not None:
        ids.setdefault("analysis_snapshot", snapshot_id)
    return ids


def _source_refs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    positioning = snapshot.get("positioning")
    if isinstance(positioning, dict):
        data = positioning.get("data")
        if isinstance(data, dict):
            data_refs = data.get("source_refs")
            if isinstance(data_refs, list):
                refs.extend(dict(item) for item in data_refs if isinstance(item, dict))
    snapshot_refs = snapshot.get("source_refs")
    if isinstance(snapshot_refs, list):
        refs.extend(dict(item) for item in snapshot_refs if isinstance(item, dict))
    return refs


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _analyze_official_reports(snapshot: dict[str, Any], reports: dict[str, Any], *, created_at: datetime) -> AgentOutput:
    from apps.features.positioning.formal_snapshot import COTPositioningSnapshot

    findings, risks, invalid = [], [], []
    usable = []
    for report_type in ("futures_only", "combined"):
        try:
            report = COTPositioningSnapshot.model_validate(reports.get(report_type, {}))
        except ValueError:
            invalid.append(f"{report_type} 持仓契约不完整。")
            continue
        if report.quality_status == "blocked" or report.freshness_status != "fresh" or report.alignment_status != "aligned":
            invalid.append(f"{report_type} 持仓不可用或过期。")
            continue
        usable.append(report)
        delta = report.managed_money.delta
        findings.append(f"CFTC {report_type} 截至 {report.report_date}，Managed Money 多仓 {report.managed_money.latest.long}、空仓 {report.managed_money.latest.short}、净仓 {report.managed_money.latest.net} 手；前期 {report.previous_report_date}。")
        if delta is not None:
            findings.append(f"{report_type} 多仓变化 {delta.long:+g}、空仓变化 {delta.short:+g}、净仓变化 {delta.net:+g} 手；总 OI {report.open_interest.value}、变化 {report.open_interest.delta} 手。")
    changes = [report.managed_money.delta.net for report in usable if report.managed_money.delta is not None]
    bias = AgentBias.UNAVAILABLE
    if changes:
        bias = AgentBias.BEARISH if all(value < 0 for value in changes) else AgentBias.BULLISH if all(value > 0 for value in changes) else AgentBias.MIXED
    etf = snapshot.get("macro", {}).get("data", {}).get("official_etf", {})
    if etf.get("status") == "available" and etf.get("shares_delta") is not None:
        findings.append(f"GLD 份额变化 {etf['shares_delta']:+g} 份，持金变化 {etf.get('gold_holdings_tonnes_delta')} 吨；基金规模变化不当作资金流。")
        if bias == AgentBias.BEARISH and etf["shares_delta"] > 0:
            bias = AgentBias.MIXED
            risks.append("期货 Managed Money 减仓与 GLD 份额增加形成分歧，不能把不同频率的持仓视为同一时点成交。")
    risks.append("CFTC 周二持仓不是周五发布后的成交；商业空仓可能来自套保，不能单凭商业净空推断黄金下跌。")
    status = AgentStatus.PARTIAL if usable else AgentStatus.UNAVAILABLE
    summary = "期货与 ETF 持仓证据存在分歧，方向仍需价格与宏观确认。" if bias == AgentBias.MIXED else "Managed Money 净仓减少，资金增量偏弱；不构成独立价格预测。" if bias == AgentBias.BEARISH else "Managed Money 净仓增加，资金增量改善；仍需其他模块确认。" if bias == AgentBias.BULLISH else "官方持仓增量不足，保持不可用。"
    flow_factors = []
    if snapshot.get("daily_research"):
        from apps.analysis.agents.research_adjudication import adjudicate_research

        flow_factors = [factor for factor in adjudicate_research(snapshot).get("factors", []) if factor["family"] in {"positioning", "etf"}]
        if flow_factors:
            findings.extend(factor["rationale"] for factor in flow_factors)
            directions = {factor["bias"] for factor in flow_factors}
            bias = AgentBias(next(iter(directions))) if len(directions) == 1 else AgentBias.MIXED
            summary = " ".join(factor["rationale"] for factor in flow_factors) + " 持仓窗口分别解释，不能替代黄金方向与买方身份确认。"
            status = AgentStatus.PARTIAL
    return AgentOutput(version="2.0", agent_name=_AGENT_NAME, module=_MODULE, snapshot_id=str(snapshot.get("snapshot_id") or "unknown"), input_snapshot_ids=_input_snapshot_ids(snapshot), bias=bias, confidence=.5 if changes or flow_factors else 0, key_findings=findings, risk_points=risks, watchlist=[*list(_WATCHLIST), "GLD daily/weekly shares"], invalid_conditions=invalid, summary=summary, source_refs=_source_refs(snapshot), status=status, created_at=created_at, data_category=DataCategory.SYSTEM_INFERENCE, input_payload={"flow_factors": flow_factors})


def _summary(bias: AgentBias, status: AgentStatus, confidence: float) -> str:
    if status is AgentStatus.UNAVAILABLE:
        return f"持仓只读视图不可用；确信度 {confidence:.2f}。"
    if status is AgentStatus.PARTIAL:
        return f"持仓只读视图 {bias.value}（输入不完整）；确信度 {confidence:.2f}。"
    return f"持仓只读视图 {bias.value}；确信度 {confidence:.2f}。"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, round(value, 2)))
