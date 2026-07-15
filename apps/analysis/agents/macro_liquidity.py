from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory
from apps.analysis.agents.macro_liquidity_prompt import build_macro_liquidity_prompt_template
from apps.analysis.macro.regime import classify_macro_regime

_AGENT_NAME = "macro_liquidity_agent"
_MODULE = "macro"
_VERSION = "1.0"
_SYSTEM_PROMPT = "你是一位专业的宏观流动性研究员。只输出 Markdown 正文。"
_PROMPT_VERSION = "macro_liquidity_agent_v1"
_DEFAULT_LLM_PROVIDER = "cockpit"
_DEFAULT_LLM_MODEL = "gpt-5.6-sol"
_DEFAULT_LLM_REASONING_EFFORT = "high"

_DXY_KEYS = ("DXY", "dxy")
_REAL_YIELD_KEYS = ("REAL_10Y", "REAL_YIELD_10Y", "real_yield_10y", "US10Y_REAL", "10Y_REAL_YIELD")
_NOMINAL_YIELD_KEYS = ("US10Y", "DGS10", "10Y", "10Y_NOMINAL_YIELD")
_BREAKEVEN_KEYS = ("T10YIE", "BREAKEVEN_10Y", "10Y_BREAKEVEN")
_US02Y_KEYS = ("US02Y", "DGS2")
_WATCHLIST = ["DGS10", "T10YIE", "DXY", "RRPONTSYD", "TGA", "WRESBAL", "DGS2", "SOFR", "EFFR", "IORB"]
_LIQUIDITY_GROUPS = {
    "ON RRP": ("RRPONTSYD", "ON_RRP", "ON_RRP_USAGE"),
    "TGA": ("TGA",),
    "Reserve Balances": ("RESERVES", "WRESBAL"),
    "SOFR": ("SOFR",),
    "EFFR": ("EFFR",),
    "IORB": ("IORB",),
}


def analyze_macro_liquidity(snapshot: dict[str, Any], *, created_at: datetime | None = None) -> AgentOutput:
    """Analyze already-loaded macro liquidity snapshot data without mutating inputs."""

    created_at = created_at or datetime.now(timezone.utc)
    if not isinstance(snapshot, dict):
        return _build_unavailable_output(
            snapshot_id="unknown",
            input_snapshot_ids={},
            source_refs=[],
            created_at=created_at,
            invalid_reason="非字典输入被拒绝；文件/路径读取不在范围内。",
            risk_point="宏观流动性输入必须是已加载的快照字典。",
        )

    snapshot_id = str(snapshot.get("snapshot_id") or "unknown")
    input_snapshot_ids = _input_snapshot_ids(snapshot)
    source_refs = _source_refs(snapshot)
    macro = snapshot.get("macro")

    if not isinstance(macro, dict) or macro.get("status") != "available":
        reason = "macro section is missing" if not isinstance(macro, dict) else f"macro status is {macro.get('status')!r}"
        return _build_unavailable_output(
            snapshot_id=snapshot_id,
            input_snapshot_ids=input_snapshot_ids,
            source_refs=source_refs,
            created_at=created_at,
            invalid_reason=reason,
            risk_point="宏观流动性输入不可用。",
        )

    data = _macro_data(snapshot)
    indicators = _indicators(snapshot)

    deterministic = _build_deterministic_output(
        snapshot_id=snapshot_id,
        input_snapshot_ids=input_snapshot_ids,
        source_refs=source_refs,
        created_at=created_at,
        snapshot=snapshot,
        indicators=indicators,
        data=data,
    )
    llm_result = invoke_macro_liquidity_llm(snapshot, deterministic_output=deterministic)
    return _merge_macro_liquidity_output(snapshot, deterministic, llm_result)


def invoke_macro_liquidity_llm(
    snapshot: dict[str, Any],
    *,
    deterministic_output: AgentOutput | None = None,
) -> dict[str, Any]:
    from apps.llm.gateway import chat_sync

    if _should_skip_live_llm():
        return {
            "markdown": "",
            "model": None,
            "provider": None,
            "latency_ms": None,
            "tokens": None,
            "prompt_version": _PROMPT_VERSION,
            "skipped": True,
        }

    prompt = build_macro_liquidity_prompt(snapshot, deterministic_output=deterministic_output)
    provider = os.getenv("MACRO_LIQUIDITY_LLM_PROVIDER", _DEFAULT_LLM_PROVIDER)
    model = os.getenv("MACRO_LIQUIDITY_LLM_MODEL", os.getenv("LLM_COCKPIT_MODEL", _DEFAULT_LLM_MODEL))
    reasoning_effort = os.getenv(
        "MACRO_LIQUIDITY_LLM_REASONING_EFFORT",
        os.getenv("LLM_COCKPIT_REASONING_EFFORT", _DEFAULT_LLM_REASONING_EFFORT),
    )
    response = chat_sync(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        temperature=0.3,
        max_tokens=4096,
        max_retries=0,
        audit_context={
            "caller": "macro_liquidity.invoke_macro_liquidity_llm",
            "run_id": snapshot.get("run_id"),
            "snapshot_id": snapshot.get("snapshot_id"),
            "trade_date": snapshot.get("trade_date"),
            "input_payload": build_macro_liquidity_structured_payload(snapshot, deterministic_output=deterministic_output),
        },
    )
    return {
        "markdown": _parse_markdown(response.content),
        "model": response.model,
        "provider": response.provider,
        "latency_ms": response.latency_ms,
        "tokens": response.usage,
        "reasoning_effort": response.reasoning_effort,
        "prompt_version": _PROMPT_VERSION,
        "skipped": False,
        "audit_id": getattr(response, "audit_id", None),
    }


def build_macro_liquidity_prompt(
    snapshot: dict[str, Any],
    *,
    deterministic_output: AgentOutput | None = None,
) -> str:
    payload = build_macro_liquidity_structured_payload(snapshot, deterministic_output=deterministic_output)
    return (
        f"{build_macro_liquidity_prompt_template()}\n\n"
        "=== 结构化输入 ===\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
    )


def build_macro_liquidity_structured_payload(
    snapshot: dict[str, Any],
    *,
    deterministic_output: AgentOutput | None = None,
) -> dict[str, Any]:
    deterministic_output = deterministic_output or _build_deterministic_output(
        snapshot_id=str(snapshot.get("snapshot_id") or "unknown"),
        input_snapshot_ids=_input_snapshot_ids(snapshot),
        source_refs=_source_refs(snapshot),
        created_at=datetime.now(timezone.utc),
        snapshot=snapshot,
        indicators=_indicators(snapshot),
        data=_macro_data(snapshot),
    )
    macro = snapshot.get("macro") if isinstance(snapshot.get("macro"), dict) else {}
    data = macro.get("data") if isinstance(macro.get("data"), dict) else {}
    indicators = data.get("indicators") if isinstance(data.get("indicators"), dict) else {}
    return {
        "report_type": "macro_liquidity",
        "snapshot_id": str(snapshot.get("snapshot_id") or "unknown"),
        "trade_date": _trade_date(snapshot),
        "input_snapshot_ids": _input_snapshot_ids(snapshot),
        "source_refs": _source_refs(snapshot),
        "status": str(deterministic_output.status.value),
        "bias": str(deterministic_output.bias.value),
        "confidence": float(deterministic_output.confidence),
        "market_phase": deterministic_output.market_phase,
        "regime_drivers": deterministic_output.regime_drivers,
        "v21_execution_order": [
            "liquidity_table",
            "liquidity_quantity",
            "liquidity_price",
            "real_yield",
            "dxy",
            "phase",
            "dominant_variable",
            "five_factor_score",
            "trading_configuration_meaning",
        ],
        "real_yield_policy": {
            "main": "US10Y - T10YIE",
            "supplementary": "DFII10 / TIPS only as observation, not the main score口径",
        },
        "external_web_policy": {
            "use_full_available_capability": True,
            "rule": "联网获取到但 source_refs 未覆盖的数据，必须标注为外部联网补充 / 待系统化接入，不得混作系统已确认数据。",
        },
        "system_data_gaps": _system_data_gaps(indicators, _source_refs(snapshot)),
        "macro_status": str(macro.get("status") or "unavailable"),
        "indicators": _compact_indicators(indicators),
        "key_findings": list(deterministic_output.key_findings),
        "risk_points": list(deterministic_output.risk_points),
        "watchlist": list(deterministic_output.watchlist),
        "invalid_conditions": list(deterministic_output.invalid_conditions),
        "summary": deterministic_output.summary,
        "data_category": str(deterministic_output.data_category.value) if deterministic_output.data_category else None,
        "existing_frame": {
            "real_yield": _indicator_snapshot(indicators, _REAL_YIELD_KEYS),
            "dxy": _indicator_snapshot(indicators, _DXY_KEYS),
            "liquidity": {
                name: _indicator_snapshot(indicators, keys) for name, keys in _LIQUIDITY_GROUPS.items()
            },
        },
    }


def _system_data_gaps(indicators: dict[str, Any], source_refs: list[dict[str, Any]]) -> list[dict[str, str]]:
    refs_text = " ".join(
        f"{ref.get('symbol', '')} {ref.get('source', '')} {ref.get('source_url', '')}"
        for ref in source_refs
        if isinstance(ref, dict)
    ).lower()
    gaps: list[dict[str, str]] = []

    dxy = _indicator_snapshot(indicators, _DXY_KEYS)
    if dxy is None:
        gaps.append({
            "item": "DXY",
            "current_status": "missing_from_system_snapshot",
            "optimization": "接入 TradingView DXY 最新值、1周变化、1月变化，CNBC 仅作兜底。",
        })
    elif "tradingview" not in refs_text:
        gaps.append({
            "item": "DXY TradingView weekly/monthly",
            "current_status": "system_snapshot_has_dxy_but_not_confirmed_tradingview_source",
            "optimization": "修复 TradingView source_ref 与周/月变化映射。",
        })

    required = [
        ("ETF / GLD flows", ("etf", "gld"), "接入 WGC / GLD 持仓或可信 ETF flow 数据源。"),
        ("COT managed money", ("cot", "cftc"), "接入 CFTC / COTData 持仓结构。"),
        ("CME delivery / physical", ("cme_delivery", "delivery"), "复用 CME Daily Bulletin 解析链路输出交割观察。"),
        ("HY OAS", ("hy_oas", "bamlh0a0hym2"), "接入 FRED BAMLH0A0HYM2 作为系统风险雷达输入。"),
        ("VIX", ("vix",), "接入 FRED / CBOE VIX 作为风险溢价输入。"),
    ]
    for item, needles, optimization in required:
        if not any(needle in refs_text for needle in needles):
            gaps.append({
                "item": item,
                "current_status": "not_in_system_source_refs",
                "optimization": optimization,
            })
    return gaps


def _merge_macro_liquidity_output(
    snapshot: dict[str, Any],
    deterministic: AgentOutput,
    llm_result: dict[str, Any],
) -> AgentOutput:
    markdown = str(llm_result.get("markdown") or "").strip()
    prompt_version = llm_result.get("prompt_version")
    generated_by = "llm" if markdown else "rule"
    payload = {
        "generated_by": generated_by,
        "prompt_version": prompt_version,
        "prompt_messages": deterministic_prompt_messages(snapshot, deterministic) if markdown else [],
        "input_payload": deterministic_input_payload(snapshot) if markdown else {},
        "llm_raw_output": markdown or None,
        "narrative_md": markdown or deterministic.summary,
        "data_category": "external_opinion" if markdown else str(deterministic.data_category.value),
        "deterministic_output": deterministic.model_dump(mode="json"),
    }
    return deterministic.model_copy(
        update={
            "summary": _extract_summary(markdown) or deterministic.summary,
            "key_findings": _extract_bullets(markdown) or deterministic.key_findings,
            "risk_points": _extract_risk_points(markdown) or deterministic.risk_points,
            "watchlist": _extract_watchlist(markdown) or deterministic.watchlist,
            "invalid_conditions": _extract_invalid_conditions(markdown) or deterministic.invalid_conditions,
            "data_category": DataCategory.EXTERNAL_OPINION if markdown else deterministic.data_category,
            "llm_model": llm_result.get("model"),
            "llm_provider": llm_result.get("provider"),
            "llm_usage": llm_result.get("tokens"),
            "llm_latency_ms": llm_result.get("latency_ms"),
            "prompt_messages": payload["prompt_messages"] or None,
            "input_payload": payload["input_payload"] or None,
            "llm_raw_output": payload["llm_raw_output"],
            "llm_audit_id": llm_result.get("audit_id"),
        }
    )


def _build_unavailable_output(
    *,
    snapshot_id: str,
    input_snapshot_ids: dict[str, Any],
    source_refs: list[dict[str, Any]],
    created_at: datetime,
    invalid_reason: str,
    risk_point: str,
) -> AgentOutput:
    return AgentOutput(
        version=_VERSION,
        agent_name=_AGENT_NAME,
        module=_MODULE,
        snapshot_id=snapshot_id,
        input_snapshot_ids=input_snapshot_ids,
        bias=AgentBias.UNAVAILABLE,
        confidence=0.0,
        key_findings=[],
        risk_points=[risk_point],
        watchlist=list(_WATCHLIST),
        invalid_conditions=[invalid_reason],
        summary="Macro liquidity input is unavailable; no read-only conclusion was generated.",
        source_refs=source_refs,
        status=AgentStatus.UNAVAILABLE,
        created_at=created_at,
        market_phase="unavailable",
        regime_drivers=None,
        data_category=DataCategory.CONFIRMED_DATA,
    )


def _input_snapshot_ids(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("input_snapshot_ids")
    ids = dict(value) if isinstance(value, dict) else {}
    snapshot_id = snapshot.get("snapshot_id")
    if snapshot_id is not None:
        ids.setdefault("analysis_snapshot", snapshot_id)
    return ids


def _trade_date(snapshot: dict[str, Any]) -> str:
    return str(snapshot.get("trade_date") or _macro_data(snapshot).get("as_of") or "")


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


def _indicators(snapshot: dict[str, Any]) -> dict[str, Any]:
    indicators = _macro_data(snapshot).get("indicators")
    return indicators if isinstance(indicators, dict) else {}


def _compact_indicators(indicators: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in (
        "DGS10",
        "US10Y",
        "DGS2",
        "US02Y",
        "T10YIE",
        "BREAKEVEN_10Y",
        "REAL_10Y",
        "REAL_YIELD_10Y",
        "DXY",
        "TGA",
        "RRPONTSYD",
        "ON_RRP_USAGE",
        "WRESBAL",
        "RESERVES",
        "SOFR",
        "EFFR",
        "IORB",
    ):
        item = _indicator_snapshot(indicators, (key,))
        if item is not None:
            result[key] = item
    return result


def _indicator_snapshot(indicators: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any] | None:
    item = _first_indicator(indicators, keys)
    if item is None:
        return None
    return {
        "value": item.get("value") or item.get("latest") or item.get("level"),
        "change": item.get("change_1w") or item.get("weekly_change") or item.get("delta_1w") or item.get("change"),
        "unit": item.get("unit"),
        "updated_at": item.get("updated_at") or item.get("as_of"),
    }


def _parse_markdown(text: str) -> str:
    markdown = text.strip()
    if markdown.startswith("```"):
        lines = markdown.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        markdown = "\n".join(lines).strip()
    return markdown


def _extract_summary(markdown: str) -> str:
    for line in markdown.splitlines():
        if line.strip() and not line.startswith("#") and not line.startswith("-"):
            return line.strip()
    return ""


def _extract_bullets(markdown: str) -> list[str]:
    return [line[2:].strip() for line in markdown.splitlines() if line.startswith("- ")]


def _extract_risk_points(markdown: str) -> list[str]:
    return _section_bullets(markdown, ("当前风险与失效条件", "风险与失效条件"))


def _extract_watchlist(markdown: str) -> list[str]:
    return _section_bullets(markdown, ("下一步观察", "下一步"))


def _extract_invalid_conditions(markdown: str) -> list[str]:
    section = _section_lines(markdown, ("当前风险与失效条件", "风险与失效条件"))
    if section:
        return section
    return []


def _section_lines(markdown: str, titles: tuple[str, ...]) -> list[str]:
    lines = markdown.splitlines()
    collecting = False
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and any(title in stripped for title in titles):
            collecting = True
            continue
        if collecting and stripped.startswith("## "):
            break
        if collecting and stripped:
            result.append(stripped)
    return result


def _section_bullets(markdown: str, titles: tuple[str, ...]) -> list[str]:
    return [line[2:].strip() for line in _section_lines(markdown, titles) if line.startswith("- ")]


def _build_deterministic_output(
    *,
    snapshot_id: str,
    input_snapshot_ids: dict[str, Any],
    source_refs: list[dict[str, Any]],
    created_at: datetime,
    snapshot: dict[str, Any],
    indicators: dict[str, Any],
    data: dict[str, Any],
) -> AgentOutput:
    key_findings: list[str] = []
    risk_points: list[str] = []
    invalid_conditions: list[str] = []
    watchlist = ["DGS10", "T10YIE", "DXY", "RRPONTSYD", "TGA", "WRESBAL", "DGS2", "SOFR", "EFFR", "IORB"]
    score = 0
    confidence = 0.45
    status = AgentStatus.SUCCESS

    real_change = _computed_real_yield_change(indicators)
    real_value = _computed_real_yield_value(indicators)
    if real_change is None:
        real_change = _first_change(indicators, _REAL_YIELD_KEYS)
        real_value = real_value if real_value is not None else _first_value(indicators, _REAL_YIELD_KEYS)
        if real_change is not None:
            key_findings.append("10Y real-yield change is using supplementary TIPS/direct field because US10Y-T10YIE change is incomplete.")
        else:
            status = AgentStatus.PARTIAL
            confidence -= 0.12
            invalid_conditions.append("10Y real-yield signal is missing; checked real-yield fields, nominal yield and T10YIE.")
    else:
        key_findings.append(f"10Y real-yield main口径 uses US10Y - T10YIE; weekly/directional change is {real_change:.2f}.")
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
        market_phase=regime.get("market_phase", "unavailable") if regime else "unavailable",
        regime_drivers=regime if regime else None,
        data_category=DataCategory.CONFIRMED_DATA,
    )


def deterministic_input_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return build_macro_liquidity_structured_payload(snapshot, deterministic_output=None)


def deterministic_prompt_messages(snapshot: dict[str, Any], deterministic: AgentOutput) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{build_macro_liquidity_prompt_template()}\n\n"
                "=== 结构化输入 ===\n"
                f"{json.dumps(deterministic_input_payload(snapshot), ensure_ascii=False, indent=2)}\n"
            ),
        },
    ]


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


def _computed_real_yield_value(indicators: dict[str, Any]) -> float | None:
    nominal = _first_value(indicators, _NOMINAL_YIELD_KEYS)
    breakeven = _first_value(indicators, _BREAKEVEN_KEYS)
    if nominal is None or breakeven is None:
        return None
    return nominal - breakeven


def _computed_real_yield_change(indicators: dict[str, Any]) -> float | None:
    nominal_change = _first_change(indicators, _NOMINAL_YIELD_KEYS)
    breakeven_change = _first_change(indicators, _BREAKEVEN_KEYS)
    if nominal_change is None or breakeven_change is None:
        return None
    return nominal_change - breakeven_change


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
        return f"宏观流动性结论偏{_bias_cn(bias)}，但关键输入仍不完整；当前确信度 {confidence:.2f}。"
    return f"宏观流动性结论偏{_bias_cn(bias)}，当前数据更支持这一方向；确信度 {confidence:.2f}。"


def _bias_cn(bias: AgentBias) -> str:
    if bias is AgentBias.BULLISH:
        return "多"
    if bias is AgentBias.BEARISH:
        return "空"
    if bias is AgentBias.MIXED:
        return "中性偏分化"
    if bias is AgentBias.UNAVAILABLE:
        return "不可用"
    return "中性"


def _should_skip_live_llm() -> bool:
    if os.getenv("FINANCE_AGENT_FORCE_LIVE_LLM", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return "PYTEST_CURRENT_TEST" in os.environ


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, round(value, 2)))
