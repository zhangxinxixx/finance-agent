"""Event Impact Agent — LLM-powered event chain and sentiment analysis.

Consumes Jin10 flash news + macro indicators + CME options data,
produces event classification, transmission chains, sentiment scoring, risk radar.

Output targets: EventFlow page (SentimentMetrics, RiskRadar, EventChainAnalysis, EventTable).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory

logger = logging.getLogger(__name__)


def build_event_impact_prompt(
    flash_news: list[dict[str, Any]],
    macro_snapshot: dict[str, Any] | None = None,
    options_intent: dict[str, Any] | None = None,
    current_price: float | None = None,
) -> str:
    """Build the event impact analysis prompt."""
    # Format flash news
    news_lines = []
    for i, item in enumerate(flash_news[:30], 1):
        content = item.get("content", "")[:200]
        time = item.get("time", "")
        news_lines.append(f"{i}. [{time}] {content}")
    news_block = "\n".join(news_lines) if news_lines else "无快讯数据"

    # Format macro
    macro_block = "无宏观数据"
    if macro_snapshot:
        indicators = macro_snapshot.get("indicators", {})
        macro_lines = []
        for name, ind in indicators.items():
            if isinstance(ind, dict):
                val = ind.get("value", "N/A")
                label = ind.get("label", name)
                macro_lines.append(f"- {label}: {val}")
        macro_block = "\n".join(macro_lines[:15]) if macro_lines else "无宏观数据"

    # Format options
    options_block = "无期权数据"
    if options_intent:
        options_block = f"""期权意图: {options_intent.get('type', 'N/A')}
Gamma Zero: {options_intent.get('gamma_zero', 'N/A')}
Forward Price: {options_intent.get('forward_price', 'N/A')}"""

    price_block = f"当前金价: {current_price}" if current_price else "当前金价: 未知"

    return f"""你是一位专业的贵金属市场事件分析师。默认使用简体中文。

任务：分析最近 24h 的 Jin10 快讯对黄金市场的影响，给出事件分类、传导链、情绪评分和风险雷达。

## 硬性规则
1. 只基于下方快讯和市场数据分析，不引入外部信息。
2. 每条重要事件必须给出传导链（事件 → 渠道 → 资产影响）。
3. 区分已定价、部分定价、未定价事件。
4. 情绪评分和风险雷达使用 0-100 数值。
5. 缺失信息标注"数据不足"。

## 输出格式
严格使用以下 JSON 格式：

```json
{{
  "events": [
    {{
      "headline": "事件标题",
      "category": "地缘|宏观|央行|供需|政治|技术",
      "impact_direction": "bullish|bearish|neutral",
      "impact_magnitude": "high|medium|low",
      "transmission_chain": "事件 → 渠道 → 资产影响",
      "pricing_status": "priced|partially_priced|unpriced",
      "duration": "intraday|multi_day|structural"
    }}
  ],
  "sentiment": {{
    "overall": "risk_on|risk_off|neutral",
    "gold_sentiment": "bullish|bearish|neutral",
    "fear_greed_index": 0-100,
    "summary": "一句话情绪总结"
  }},
  "risk_radar": {{
    "geopolitical": 0-100,
    "monetary": 0-100,
    "liquidity": 0-100,
    "technical": 0-100
  }},
  "top_drivers": [
    "最重要的驱动因素1",
    "最重要的驱动因素2",
    "最重要的驱动因素3"
  ],
  "summary": "一句话事件影响总结"
}}
```

## 最近 24h 快讯
{news_block}

## 市场数据
{macro_block}

## 期权数据
{options_block}

## 价格
{price_block}

请输出 JSON 分析结果。"""


def parse_event_impact_response(response_text: str) -> dict[str, Any]:
    """Parse LLM JSON response."""
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
        else:
            text = "\n".join(lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {}


def run_event_impact_agent(
    flash_news: list[dict[str, Any]] | None = None,
    macro_snapshot: dict[str, Any] | None = None,
    options_intent: dict[str, Any] | None = None,
    current_price: float | None = None,
    *,
    daily_market_brief: dict[str, Any] | None = None,
    impact_assessments: list[dict[str, Any]] | None = None,
    market_reactions: list[dict[str, Any]] | None = None,
    snapshot_id: str = "",
    run_id: str = "",
) -> AgentOutput:
    """Run the Event Impact Agent with LLM, fallback to deterministic."""
    flash_news = flash_news or []
    if isinstance(daily_market_brief, dict):
        return run_structured_event_impact_agent(
            daily_market_brief=daily_market_brief,
            impact_assessments=impact_assessments,
            market_reactions=market_reactions,
            snapshot_id=snapshot_id,
            run_id=run_id,
        )

    from apps.llm.gateway import chat_sync

    prompt = build_event_impact_prompt(flash_news, macro_snapshot, options_intent, current_price)
    prompt_messages = [
        {"role": "system", "content": "你是贵金属事件分析师。只输出 JSON。"},
        {"role": "user", "content": prompt},
    ]
    input_payload = {
        "flash_news": flash_news,
        "macro_snapshot": macro_snapshot,
        "options_intent": options_intent,
        "current_price": current_price,
    }

    try:
        response = chat_sync(
            messages=prompt_messages,
            temperature=0.2,
            max_tokens=4096,
        )
        parsed = parse_event_impact_response(response.content)
        if not parsed:
            raise ValueError("Failed to parse LLM JSON response")

        events = parsed.get("events", [])
        sentiment = parsed.get("sentiment", {})
        risk_radar = parsed.get("risk_radar", {})
        top_drivers = parsed.get("top_drivers", [])
        summary = parsed.get("summary", "")

        # Derive bias from sentiment
        gold_sent = sentiment.get("gold_sentiment", "neutral")
        fear_greed = sentiment.get("fear_greed_index", 50)
        if gold_sent == "bullish":
            bias = AgentBias.BULLISH
        elif gold_sent == "bearish":
            bias = AgentBias.BEARISH
        else:
            bias = AgentBias.NEUTRAL

        # Build findings
        findings = []
        for event in events[:5]:
            cat = event.get("category", "?")
            head = event.get("headline", "")[:60]
            direction = event.get("impact_direction", "?")
            findings.append(f"[{cat}] {head} → {direction}")

        # Build risk points
        risk_points = []
        for event in events:
            if event.get("impact_magnitude") == "high" and event.get("pricing_status") != "priced":
                risk_points.append(f"未定价高影响事件: {event.get('headline', '')[:60]}")

        # Build watchlist
        watchlist = []
        for event in events:
            if event.get("pricing_status") == "unpriced":
                watchlist.append(f"关注: {event.get('headline', '')[:60]}")

        return AgentOutput(
            version="1.0",
            agent_name="event_impact",
            module="event_flow",
            snapshot_id=snapshot_id,
            input_snapshot_ids={"jin10_news": snapshot_id},
            bias=bias,
            confidence=min(float(fear_greed) / 100, 0.9),
            key_findings=findings,
            risk_points=risk_points,
            watchlist=watchlist[:5],
            invalid_conditions=[
                "地缘事件急转",
                "央行意外政策",
                "流动性突发收紧",
            ],
            summary=summary,
            source_refs=[],
            status=AgentStatus.SUCCESS,
            created_at=datetime.now(timezone.utc),
            data_category=DataCategory.EXTERNAL_OPINION,
            evidence_refs=[{
                "type": "event_analysis",
                "events_count": len(events),
                "sentiment": sentiment,
                "risk_radar": risk_radar,
                "top_drivers": top_drivers,
                "generated_by": "llm",
                "model": response.model,
                "provider": response.provider,
                "latency_ms": response.latency_ms,
            }],
            llm_model=response.model,
            llm_provider=response.provider,
            llm_usage=response.usage,
            llm_latency_ms=response.latency_ms,
            prompt_messages=prompt_messages,
            input_payload=input_payload,
            llm_raw_output=response.content,
        )
    except Exception as exc:
        logger.warning("Event Impact Agent LLM failed, using fallback: %s", exc)
        return _fallback_event_impact(flash_news, snapshot_id, run_id)


def run_structured_event_impact_agent(
    *,
    daily_market_brief: dict[str, Any],
    impact_assessments: list[dict[str, Any]] | None = None,
    market_reactions: list[dict[str, Any]] | None = None,
    snapshot_id: str = "",
    run_id: str = "",
) -> AgentOutput:
    """Build event-impact output from P0 structured news/event artifacts.

    This path is intentionally deterministic. It preserves verification status
    from the upstream event pipeline and does not promote candidate events into
    confirmed facts.
    """

    brief = dict(daily_market_brief)
    assessment_by_event_id = {
        str(item.get("event_id") or ""): dict(item)
        for item in (impact_assessments or [])
        if isinstance(item, dict) and item.get("event_id")
    }
    reaction_by_event_id = {
        str(item.get("event_id") or ""): dict(item)
        for item in (market_reactions or [])
        if isinstance(item, dict) and item.get("event_id")
    }

    confirmed_events = [
        _enrich_structured_event(event, assessment_by_event_id, reaction_by_event_id)
        for event in _dict_list(brief.get("confirmed_events"))
    ]
    candidate_events = [
        _enrich_structured_event(event, assessment_by_event_id, reaction_by_event_id)
        for event in _dict_list(brief.get("candidate_events"))
    ]
    unconfirmed_risks = [
        _enrich_structured_event(event, assessment_by_event_id, reaction_by_event_id)
        for event in _dict_list(brief.get("unconfirmed_risks"))
    ]

    valid_confirmed, missing_confirmed = _partition_events_with_id(confirmed_events)
    valid_candidates, missing_candidates = _partition_events_with_id(candidate_events)
    valid_unconfirmed, missing_unconfirmed = _partition_events_with_id(unconfirmed_risks)
    missing_event_id_count = missing_confirmed + missing_candidates + missing_unconfirmed

    key_findings = [_structured_event_line("确认影响", event) for event in valid_confirmed[:5]]
    risk_events = _dedupe_events_by_id([*valid_unconfirmed, *[event for event in valid_candidates if _risk_level(event) in {"high", "medium"}]])
    risk_points = [_structured_event_line("待确认冲击", event) for event in risk_events[:8]]
    watchlist_events = [
        event
        for event in valid_candidates
        if str(event.get("verification_status") or "") != "official_confirmed"
    ]
    watchlist = [_structured_event_line("观察事件", event) for event in watchlist_events[:8]]

    invalid_conditions: list[str] = []
    if missing_event_id_count:
        invalid_conditions.append(f"{missing_event_id_count} structured event(s) missing event_id were excluded from directional output.")
    if valid_candidates or valid_unconfirmed:
        invalid_conditions.append("Candidate or single-source events require verification before becoming confirmed facts.")
    if not valid_confirmed:
        invalid_conditions.append("No official-confirmed structured events available for directional findings.")

    if not key_findings:
        key_findings.append("结构化事件输入可用，但没有可作为确认事实的 official-confirmed 事件。")

    bias = _structured_bias(valid_confirmed)
    confidence = _structured_confidence(
        confirmed_count=len(valid_confirmed),
        candidate_count=len(valid_candidates),
        unconfirmed_count=len(valid_unconfirmed),
        missing_event_id_count=missing_event_id_count,
    )
    source_refs = _dedupe_refs([
        *_dict_list(brief.get("source_refs")),
        *[ref for event in [*valid_confirmed, *valid_candidates, *valid_unconfirmed] for ref in _dict_list(event.get("source_refs"))],
    ])
    status = AgentStatus.SUCCESS if valid_confirmed or valid_candidates or valid_unconfirmed else AgentStatus.PARTIAL
    event_ids = [event["event_id"] for event in _dedupe_events_by_id([*valid_confirmed, *valid_candidates, *valid_unconfirmed])]

    return AgentOutput(
        version="1.0",
        agent_name="event_impact",
        module="event_flow",
        snapshot_id=snapshot_id,
        input_snapshot_ids={
            "daily_market_brief": snapshot_id,
            "impact_assessments": snapshot_id if impact_assessments is not None else "",
            "market_reactions": snapshot_id if market_reactions is not None else "",
        },
        bias=bias,
        confidence=confidence,
        key_findings=_dedupe_strings(key_findings),
        risk_points=_dedupe_strings(risk_points),
        watchlist=_dedupe_strings(watchlist),
        invalid_conditions=_dedupe_strings(invalid_conditions),
        summary=(
            f"事件冲击层：确认事件 {len(valid_confirmed)} 条，候选事件 {len(valid_candidates)} 条，"
            f"待确认风险 {len(valid_unconfirmed)} 条；方向={bias.value}。"
        ),
        source_refs=source_refs,
        status=status,
        created_at=datetime.now(timezone.utc),
        data_category=DataCategory.SYSTEM_INFERENCE,
        evidence_refs=[{
            "type": "structured_event_impact",
            "generated_by": "structured_rules",
            "run_id": run_id,
            "event_ids": event_ids,
            "confirmed_event_count": len(valid_confirmed),
            "candidate_event_count": len(valid_candidates),
            "unconfirmed_risk_count": len(valid_unconfirmed),
            "excluded_missing_event_id_count": missing_event_id_count,
        }],
        input_payload={
            "daily_market_brief": brief,
            "impact_assessments": impact_assessments or [],
            "market_reactions": market_reactions or [],
        },
    )


def _fallback_event_impact(
    flash_news: list[dict[str, Any]],
    snapshot_id: str,
    run_id: str,
) -> AgentOutput:
    """Deterministic fallback when LLM is unavailable."""
    # Simple keyword-based classification
    bullish_kw = ["战争", "冲突", "制裁", "降息", "宽松", "避险", "黄金上涨"]
    bearish_kw = ["加息", "紧缩", "美元走强", "风险偏好", "抛售"]

    bullish_count = 0
    bearish_count = 0
    for item in flash_news:
        content = item.get("content", "")
        for kw in bullish_kw:
            if kw in content:
                bullish_count += 1
                break
        for kw in bearish_kw:
            if kw in content:
                bearish_count += 1
                break

    if bullish_count > bearish_count + 2:
        bias = AgentBias.BULLISH
    elif bearish_count > bullish_count + 2:
        bias = AgentBias.BEARISH
    else:
        bias = AgentBias.NEUTRAL

    return AgentOutput(
        version="1.0",
        agent_name="event_impact",
        module="event_flow",
        snapshot_id=snapshot_id,
        input_snapshot_ids={"jin10_news": snapshot_id},
        bias=bias,
        confidence=0.2,
        key_findings=[f"快讯分析: {len(flash_news)} 条, 多头信号 {bullish_count}, 空头信号 {bearish_count}"],
        risk_points=["LLM 不可用，使用关键词 fallback"],
        watchlist=["等待 LLM 恢复"],
        invalid_conditions=[],
        summary=f"事件分析 (关键词 fallback): {bias.value}",
        source_refs=[],
        status=AgentStatus.PARTIAL,
        created_at=datetime.now(timezone.utc),
        data_category=DataCategory.SYSTEM_INFERENCE,
    )


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _enrich_structured_event(
    event: dict[str, Any],
    assessment_by_event_id: dict[str, dict[str, Any]],
    reaction_by_event_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    result = dict(event)
    event_id = str(result.get("event_id") or "")
    assessment = assessment_by_event_id.get(event_id) or {}
    reaction = reaction_by_event_id.get(event_id) or {}
    for key in (
        "impact_path",
        "gold_impact",
        "silver_impact",
        "dollar_impact",
        "yield_impact",
        "oil_impact",
        "risk_level",
        "pricing_status",
        "invalidation_condition",
    ):
        if not result.get(key) and assessment.get(key):
            result[key] = assessment.get(key)
    if reaction and not result.get("market_validation"):
        result["market_validation"] = {
            "status": reaction.get("status"),
            "pricing_status": reaction.get("pricing_status"),
            "confirmation_summary": reaction.get("confirmation_summary"),
        }
    return result


def _partition_events_with_id(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    valid: list[dict[str, Any]] = []
    missing_count = 0
    for event in events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            missing_count += 1
            continue
        event["event_id"] = event_id
        valid.append(event)
    return valid, missing_count


def _structured_event_line(prefix: str, event: dict[str, Any]) -> str:
    title = event.get("what_happened") or event.get("event_name") or event.get("event_type") or "unknown"
    event_id = event.get("event_id") or "no_event_id"
    verification = event.get("verification_status") or "unknown"
    impact_path = event.get("impact_path") or "unknown"
    gold_impact = event.get("gold_impact") or "unknown"
    pricing = event.get("pricing_status") or _pricing_status_from_validation(event.get("market_validation")) or "unknown"
    return (
        f"{prefix}: {title} | {verification} | {impact_path} | "
        f"gold={gold_impact} | pricing={pricing} | event_id={event_id}"
    )


def _pricing_status_from_validation(value: Any) -> str | None:
    return value.get("pricing_status") if isinstance(value, dict) else None


def _risk_level(event: dict[str, Any]) -> str:
    return str(event.get("risk_level") or "low").lower()


def _dedupe_events_by_id(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)
        result.append(event)
    return result


def _structured_bias(events: list[dict[str, Any]]) -> AgentBias:
    scores = {"bullish": 0, "bearish": 0}
    for event in events:
        impact = str(event.get("gold_impact") or "").lower()
        if impact in scores:
            scores[impact] += 1
    if scores["bullish"] and scores["bearish"]:
        return AgentBias.MIXED
    if scores["bullish"]:
        return AgentBias.BULLISH
    if scores["bearish"]:
        return AgentBias.BEARISH
    return AgentBias.NEUTRAL


def _structured_confidence(
    *,
    confirmed_count: int,
    candidate_count: int,
    unconfirmed_count: int,
    missing_event_id_count: int,
) -> float:
    confidence = 0.45
    confidence += min(confirmed_count, 3) * 0.10
    confidence += min(unconfirmed_count, 3) * 0.03
    confidence += min(candidate_count, 3) * 0.02
    confidence -= min(missing_event_id_count, 3) * 0.05
    return max(0.10, min(round(confidence, 2), 0.85))


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = json.dumps(ref, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
