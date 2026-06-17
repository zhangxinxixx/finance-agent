from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory

_AGENT_NAME = "technical_agent"
_MODULE = "technical"
_VERSION = "1.0"


def analyze_technical(
    snapshot: dict[str, Any], *, created_at: datetime | None = None
) -> AgentOutput:
    """Analyze the technical snapshot section of an already-loaded analysis snapshot.

    Works on ``snapshot["technical"]`` — a dict with ``status`` and
    ``data`` keys following the same structure as ``snapshot["macro"]``.
    """

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
            risk_points=["技术面输入必须是已加载的快照字典。"],
            watchlist=["XAUUSD"],
            invalid_conditions=["非字典输入被拒绝；文件/路径读取不在范围内。"],
            summary="Technical input is unavailable; no read-only conclusion was generated.",
            source_refs=[],
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            data_category=DataCategory.SYSTEM_INFERENCE,
        )

    snapshot_id = str(snapshot.get("snapshot_id") or "unknown")
    input_snapshot_ids = _input_snapshot_ids(snapshot)
    source_refs = _source_refs(snapshot)
    technical = snapshot.get("technical")

    if not isinstance(technical, dict) or technical.get("status") != "available":
        reason = (
            "technical section is missing"
            if not isinstance(technical, dict)
            else f"technical status is {technical.get('status')!r}"
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
            risk_points=["技术面输入不可用。"],
            watchlist=["XAUUSD"],
            invalid_conditions=[reason],
            summary="Technical input is unavailable; no read-only conclusion was generated.",
            source_refs=source_refs,
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            data_category=DataCategory.SYSTEM_INFERENCE,
        )

    data_any = technical.get("data")
    data: dict[str, Any] = data_any if isinstance(data_any, dict) else {}

    key_findings: list[str] = []
    risk_points: list[str] = []
    invalid_conditions: list[str] = []
    watchlist = ["XAUUSD"]
    score = 0
    confidence = 0.50
    status = AgentStatus.SUCCESS

    # ── Price ──────────────────────────────────────────────────────────────
    price_raw = data.get("price")
    price = _to_float(price_raw)
    if price is None:
        status = AgentStatus.PARTIAL
        confidence -= 0.15
        invalid_conditions.append("XAUUSD price is missing from technical snapshot.")
        risk_points.append("Cannot assess technical direction without price data.")
    else:
        key_findings.append(f"XAUUSD close: {price:.2f}.")

    # ── Trend (from snapshot) ─────────────────────────────────────────────
    trend = str(data.get("trend", "")).lower()
    if trend == "bullish":
        score += 1
        key_findings.append("Price above MA20 approximation → bullish trend.")
    elif trend == "bearish":
        score -= 1
        key_findings.append("Price below MA20 approximation → bearish trend.")
    elif trend == "neutral":
        key_findings.append("Price near MA20 approximation; no clear trend direction.")
    else:
        key_findings.append("Trend direction not determined; insufficient data.")

    # ── MA levels ──────────────────────────────────────────────────────────
    ma20 = _to_float(data.get("ma20_approx"))
    ma50 = _to_float(data.get("ma50_approx"))
    ma_notes: list[str] = []
    if ma20 is not None and price is not None:
        ma_notes.append(f"MA20≈{ma20:.2f}")
        if price > ma20:
            ma_notes.append("price > MA20")
        else:
            ma_notes.append("price < MA20")
    if ma50 is not None and price is not None:
        ma_notes.append(f"MA50≈{ma50:.2f}")
        if price > ma50:
            ma_notes.append("price > MA50")
        else:
            ma_notes.append("price < MA50")
    if ma_notes:
        key_findings.append("MA approximation: " + ", ".join(ma_notes) + ".")
    if ma20 is None and ma50 is None:
        invalid_conditions.append("MA20/MA50 approximations unavailable; trend signal weakened.")
        confidence -= 0.08

    # Gold cross: price above both MAs is extra bullish
    if (
        ma20 is not None
        and ma50 is not None
        and price is not None
        and price > ma20
        and price > ma50
    ):
        score += 1
        key_findings.append("Gold cross pattern: price above both MA20 and MA50 — bullish reinforcement.")

    # ── RSI ────────────────────────────────────────────────────────────────
    rsi = _to_float(data.get("rsi_14"))
    if rsi is not None:
        if rsi > 70:
            score -= 1
            key_findings.append(f"RSI(14) = {rsi:.1f}: overbought (>70) → bearish signal.")
            risk_points.append(f"RSI overbought at {rsi:.1f}; reversal risks elevated.")
        elif rsi < 30:
            score += 1
            key_findings.append(f"RSI(14) = {rsi:.1f}: oversold (<30) → bullish signal.")
        elif 40 <= rsi <= 60:
            key_findings.append(f"RSI(14) = {rsi:.1f}: neutral zone.")
        else:
            key_findings.append(f"RSI(14) = {rsi:.1f}.")
    else:
        rsi_note = str(data.get("rsi_14_note", ""))
        if rsi_note:
            invalid_conditions.append(f"RSI(14) unavailable: {rsi_note}")
        else:
            invalid_conditions.append("RSI(14) unavailable; requires 14 daily closes.")
        confidence -= 0.05

    # ── ATR / Volatility ──────────────────────────────────────────────────
    atr = _to_float(data.get("atr_14"))
    volatility = str(data.get("volatility", "")).lower()
    if atr is not None and price is not None:
        atr_pct = round((atr / price) * 100, 2)
        key_findings.append(f"ATR(14)≈{atr:.2f} ({atr_pct}% of price).")
        if volatility == "high":
            risk_points.append(f"Volatility elevated (ATR≈{atr_pct}% of price); wider stop-loss recommended.")
            score -= 1 if trend == "bullish" else 0
        elif volatility == "low":
            key_findings.append("Low volatility environment; range-bound expectations.")
    else:
        atr_note = str(data.get("atr_14_note", ""))
        if atr_note:
            invalid_conditions.append(f"ATR(14) unavailable: {atr_note}")
        else:
            invalid_conditions.append("ATR(14) unavailable; requires high/low data.")
        confidence -= 0.05

    # ── Data quality: approximations reduce confidence ────────────────────
    if ma20 is not None or ma50 is not None:
        key_findings.append(
            "Note: MAs are approximated from Perf.1M/Perf.3M; precise levels require historical data."
        )
        confidence -= 0.03

    # ── Final bias and confidence ──────────────────────────────────────────
    bias = _bias_from_score(score)
    if not key_findings:
        key_findings.append("Technical data is present but directional signals are insufficient.")
    confidence = _clamp(
        confidence + min(abs(score) * 0.06, 0.12),
        0.0,
        0.82 if status is AgentStatus.PARTIAL else 0.88,
    )

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
        data_category=DataCategory.SYSTEM_INFERENCE,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _input_snapshot_ids(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("input_snapshot_ids")
    ids = dict(value) if isinstance(value, dict) else {}
    snapshot_id = snapshot.get("snapshot_id")
    if snapshot_id is not None:
        ids.setdefault("analysis_snapshot", snapshot_id)
    return ids


def _source_refs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for candidate in (
        snapshot.get("source_refs"),
        snapshot.get("technical", {}).get("data", {}).get("source_refs"),
    ):
        if isinstance(candidate, list):
            refs.extend(dict(item) for item in candidate if isinstance(item, dict))
    return refs


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bias_from_score(score: int) -> AgentBias:
    if score > 0:
        return AgentBias.BULLISH
    if score < 0:
        return AgentBias.BEARISH
    return AgentBias.NEUTRAL


def _summary(bias: AgentBias, status: AgentStatus, confidence: float) -> str:
    if status is AgentStatus.PARTIAL:
        return (
            f"技术面只读视图 {bias.value}（输入不完整）；"
            f"confidence {confidence:.2f}."
        )
    return f"技术面只读视图 {bias.value}；确信度 {confidence:.2f}。"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, round(value, 2)))
