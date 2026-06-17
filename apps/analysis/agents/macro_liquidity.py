from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory
from apps.analysis.macro.regime import classify_macro_regime

_AGENT_NAME = "macro_liquidity_agent"
_MODULE = "macro"
_VERSION = "1.0"

_DXY_KEYS = ("DXY", "dxy")
_REAL_YIELD_KEYS = ("REAL_YIELD_10Y", "real_yield_10y", "US10Y_REAL", "10Y_REAL_YIELD")
_NOMINAL_YIELD_KEYS = ("US10Y", "DGS10", "10Y", "10Y_NOMINAL_YIELD")
_BREAKEVEN_KEYS = ("T10YIE", "10Y_BREAKEVEN")
_LIQUIDITY_GROUPS = {
    "ON RRP": ("RRPONTSYD", "ON_RRP", "ON_RRP_USAGE"),
    "TGA": ("TGA",),
    "SOFR": ("SOFR",),
    "EFFR": ("EFFR",),
    "IORB": ("IORB",),
}


def analyze_macro_liquidity(snapshot: dict[str, Any], *, created_at: datetime | None = None) -> AgentOutput:
    """Analyze already-loaded macro liquidity snapshot data without mutating inputs."""

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
            risk_points=["宏观流动性输入必须是已加载的快照字典。"],
            watchlist=["DGS10", "T10YIE", "DXY", "RRPONTSYD", "TGA", "SOFR", "EFFR", "IORB"],
            invalid_conditions=["非字典输入被拒绝；文件/路径读取不在范围内。"],
            summary="Macro liquidity input is unavailable; no read-only conclusion was generated.",
            source_refs=[],
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            market_phase="unavailable",
            regime_drivers=None,
            data_category=DataCategory.CONFIRMED_DATA,
        )
    snapshot_id = str(snapshot.get("snapshot_id") or "unknown")
    input_snapshot_ids = _input_snapshot_ids(snapshot)
    source_refs = _source_refs(snapshot)
    macro = snapshot.get("macro")

    if not isinstance(macro, dict) or macro.get("status") != "available":
        reason = "macro section is missing" if not isinstance(macro, dict) else f"macro status is {macro.get('status')!r}"
        return AgentOutput(
            version=_VERSION,
            agent_name=_AGENT_NAME,
            module=_MODULE,
            snapshot_id=snapshot_id,
            input_snapshot_ids=input_snapshot_ids,
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            key_findings=[],
            risk_points=["宏观流动性输入不可用。"],
            watchlist=["DGS10", "T10YIE", "DXY", "RRPONTSYD", "TGA", "SOFR", "EFFR", "IORB"],
            invalid_conditions=[reason],
            summary="Macro liquidity input is unavailable; no read-only conclusion was generated.",
            source_refs=source_refs,
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            market_phase="unavailable",
            regime_drivers=None,
            data_category=DataCategory.CONFIRMED_DATA,
        )

    data_any = macro.get("data")
    data: dict[str, Any] = data_any if isinstance(data_any, dict) else {}
    indicators_any = data.get("indicators")
    indicators: dict[str, Any] = indicators_any if isinstance(indicators_any, dict) else {}

    key_findings: list[str] = []
    risk_points: list[str] = []
    invalid_conditions: list[str] = []
    watchlist = ["DGS10", "T10YIE", "DXY", "RRPONTSYD", "TGA", "SOFR", "EFFR", "IORB"]
    score = 0
    confidence = 0.45
    status = AgentStatus.SUCCESS

    real_change = _first_change(indicators, _REAL_YIELD_KEYS)
    real_value = _first_value(indicators, _REAL_YIELD_KEYS)
    if real_change is None:
        nominal_change = _first_change(indicators, _NOMINAL_YIELD_KEYS)
        breakeven_change = _first_change(indicators, _BREAKEVEN_KEYS)
        if nominal_change is not None and breakeven_change is not None:
            real_change = nominal_change - breakeven_change
            key_findings.append(f"Estimated 10Y real-yield change from nominal yield and T10YIE: {real_change:.2f}.")
        else:
            status = AgentStatus.PARTIAL
            confidence -= 0.12
            invalid_conditions.append("10Y real-yield signal is missing; checked real-yield fields, nominal yield and T10YIE.")
    if real_change is not None:
        if real_change < 0:
            score += 1
            key_findings.append("Falling 10Y real yields are bullish for gold.")
        elif real_change > 0:
            score -= 1
            key_findings.append("Rising 10Y real yields are bearish for gold.")
        else:
            key_findings.append("10Y real yields are flat and do not add directional conviction.")
    elif real_value is not None:
        key_findings.append(f"10Y real yield level is available ({real_value:.2f}) but change direction is missing.")

    dxy_change = _first_change(indicators, _DXY_KEYS)
    dxy_value = _first_value(indicators, _DXY_KEYS)
    if dxy_value is None and dxy_change is None:
        status = AgentStatus.PARTIAL
        confidence -= 0.18
        risk_points.append("DXY is missing, so dollar-pressure confirmation is unavailable.")
        invalid_conditions.append("DXY input missing; confidence capped below full conviction.")
    else:
        if dxy_change is not None and dxy_change < 0:
            score += 1
            key_findings.append("DXY is falling, which is a macro tailwind for gold.")
        elif dxy_change is not None and dxy_change > 0:
            score -= 1
            key_findings.append("DXY is rising, which is a macro headwind for gold.")
        elif dxy_value is not None:
            key_findings.append(f"DXY level is available ({dxy_value:.2f}) but directional change is missing.")

    present_liquidity = [name for name, keys in _LIQUIDITY_GROUPS.items() if _first_indicator(indicators, keys) is not None]
    if len(present_liquidity) < len(_LIQUIDITY_GROUPS):
        missing = [name for name in _LIQUIDITY_GROUPS if name not in present_liquidity]
        status = AgentStatus.PARTIAL
        confidence -= 0.08
        risk_points.append("Liquidity indicators are incomplete: " + ", ".join(missing) + ".")
    else:
        confidence += 0.08
        key_findings.append("Core liquidity indicators are available for cross-checking.")

    unavailable = data.get("unavailable_symbols")
    if isinstance(unavailable, list) and unavailable:
        status = AgentStatus.PARTIAL
        confidence -= 0.08
        invalid_conditions.append("Unavailable macro symbols: " + ", ".join(str(item) for item in unavailable) + ".")

    bias = _bias_from_score(score)
    if not key_findings:
        key_findings.append("Macro data is present but directional signals are insufficient.")
    confidence = _clamp(confidence + min(abs(score) * 0.08, 0.16), 0.0, 0.85 if status is AgentStatus.PARTIAL else 0.92)

    # ── P4-05: classify macro regime ─────────────────────────────────
    regime = classify_macro_regime(indicators) if indicators else None
    if regime and regime["market_phase"] != "unavailable":
        mp = regime["market_phase"]
        rc = regime["confidence"]
        gi = regime["gold_interpretation"]
        key_findings.append(f"Macro regime: {mp} (confidence {rc:.2f}). {gi}")

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
        # ── P4-05: regime fields ──
        market_phase=regime.get("market_phase", "unavailable") if regime else "unavailable",
        regime_drivers=regime if regime else None,
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
    for candidate in (snapshot.get("source_refs"), _macro_data(snapshot).get("source_refs")):
        if isinstance(candidate, list):
            refs.extend(dict(item) for item in candidate if isinstance(item, dict))
    return refs


def _macro_data(snapshot: dict[str, Any]) -> dict[str, Any]:
    macro = snapshot.get("macro")
    if not isinstance(macro, dict):
        return {}
    data = macro.get("data")
    return data if isinstance(data, dict) else {}


def _first_indicator(indicators: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any] | None:
    for key in keys:
        item = indicators.get(key)
        if isinstance(item, dict):
            return item
    return None


def _first_value(indicators: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    item = _first_indicator(indicators, keys)
    if item is None:
        return None
    return _to_float(item.get("value") or item.get("latest") or item.get("level"))


def _first_change(indicators: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    item = _first_indicator(indicators, keys)
    if item is None:
        return None
    for field in ("change_1w", "weekly_change", "delta_1w", "change", "change_1m", "monthly_change"):
        value = _to_float(item.get(field))
        if value is not None:
            return value
    return None


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
        return f"宏观流动性只读视图 {bias.value}（输入不完整）；确信度 {confidence:.2f}。"
    return f"宏观流动性只读视图 {bias.value}；确信度 {confidence:.2f}。"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, round(value, 2)))
