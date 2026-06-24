from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory

_AGENT_NAME = "positioning_agent"
_MODULE = "positioning"
_VERSION = "1.0"

# Thresholds for COT commercial net positioning bias
# Heavy commercial short (commercials are hedging producers → typically bearish for gold)
HEAVY_COMMERCIAL_SHORT_THRESHOLD = -200000
# Commercials net long → bullish signal (producers reducing hedges)
COMMERCIAL_LONG_THRESHOLD = 0

_WATCHLIST = [
    "COT_GOLD",
    "commercial_net",
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

    # Determine bias from commercial net position
    bias: AgentBias
    if commercial_net < HEAVY_COMMERCIAL_SHORT_THRESHOLD:
        bias = AgentBias.BEARISH
        key_findings.append(
            f"Commercial net position is heavily short ({commercial_net:,.0f} contracts), "
            f"indicating strong producer hedging — bearish for gold."
        )
        confidence += 0.18
    elif commercial_net > COMMERCIAL_LONG_THRESHOLD:
        bias = AgentBias.BULLISH
        key_findings.append(
            f"Commercial net position is long ({commercial_net:,.0f} contracts), "
            f"suggesting reduced producer hedging — bullish for gold."
        )
        confidence += 0.12
    else:
        bias = AgentBias.NEUTRAL
        key_findings.append(
            f"Commercial net position is moderately short ({commercial_net:,.0f} contracts) "
            f"but not extreme — neutral signal."
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
        key_findings.append("Commercial shorts are increasing week-over-week — bearish momentum.")
        if bias is AgentBias.BEARISH:
            confidence += 0.05
        elif bias is not AgentBias.UNAVAILABLE:
            risk_points.append("Commercial shorts increasing despite non-bearish bias; monitor closely.")
    elif commercial_direction == "increasing_long":
        key_findings.append("Commercial longs are increasing week-over-week — bullish momentum.")
        if bias is AgentBias.BULLISH:
            confidence += 0.05
        elif bias is not AgentBias.UNAVAILABLE:
            risk_points.append("Commercial longs increasing despite non-bullish bias; monitor closely.")
    else:
        key_findings.append("Commercial direction is flat week-over-week.")

    if noncomm_direction == "increasing_long":
        key_findings.append("Speculative longs are increasing — momentum-driven, but watch for crowding.")
    elif noncomm_direction == "increasing_short":
        key_findings.append("Speculative shorts are increasing — bearish momentum from managed money.")

    # Extreme reading
    if extreme_reading:
        risk_points.append(
            "COT commercial net position is at an extreme (top/bottom 20% of 52-week range) — "
            "elevated reversal risk."
        )
        confidence -= 0.06
        key_findings.append("Commercial net position is at a 52-week extreme — contrarian signal.")

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


def _summary(bias: AgentBias, status: AgentStatus, confidence: float) -> str:
    if status is AgentStatus.UNAVAILABLE:
        return f"持仓只读视图不可用；确信度 {confidence:.2f}。"
    if status is AgentStatus.PARTIAL:
        return f"持仓只读视图 {bias.value}（输入不完整）；确信度 {confidence:.2f}。"
    return f"持仓只读视图 {bias.value}；确信度 {confidence:.2f}。"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, round(value, 2)))
