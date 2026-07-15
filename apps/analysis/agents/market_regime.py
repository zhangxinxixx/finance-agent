"""Market Regime Agent — LLM-powered market state classification.

Consumes macro snapshot + Jin10 quotes + CME options intent,
produces regime classification, environment filters, and indicator interpretations.

Output targets: MarketMonitor page (MarketRegimePanel, EnvironmentFilterPanel).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory

logger = logging.getLogger(__name__)

REGIME_LABELS = {
    "rate_pressure": "利率压制态",
    "transition_release": "过渡释放态",
    "trend_tailwind": "趋势顺风态",
    "consolidation": "高位整固态",
    "liquidity_crunch": "流动性踩踏态",
    "direction_choice": "方向抉择态",
    "breakout_accumulation": "突破前蓄势态",
}


def build_regime_prompt(
    macro_snapshot: dict[str, Any],
    options_intent: dict[str, Any] | None = None,
    quotes: dict[str, Any] | None = None,
) -> str:
    """Build the market regime analysis prompt."""
    indicators = macro_snapshot.get("indicators", {})

    # Format indicators
    indicator_lines = []
    for name, ind in indicators.items():
        if isinstance(ind, dict):
            val = ind.get("value", "N/A")
            unit = ind.get("unit", "")
            label = ind.get("label", name)
            date = ind.get("date", "")
            direction = ind.get("direction_note", "")
            indicator_lines.append(
                f"- {label} ({name}): {val} {unit} | 日期: {date} | {direction}"
            )
    indicator_block = "\n".join(indicator_lines) if indicator_lines else "无宏观指标数据"

    # Format options intent
    intent_block = "无期权数据"
    if options_intent:
        intent_type = options_intent.get("type", options_intent.get("intent_type", "N/A"))
        intent_score = options_intent.get("score", options_intent.get("confidence", "N/A"))
        gamma_zero = options_intent.get("gamma_zero", "N/A")
        forward_price = options_intent.get("forward_price", "N/A")
        intent_block = f"""期权意图: {intent_type}
意图评分: {intent_score}
Gamma Zero: {gamma_zero}
Forward Price: {forward_price}"""

    # Format quotes
    quotes_block = "无实时报价"
    if quotes:
        quote_lines = []
        for sym, q in quotes.items():
            if isinstance(q, dict):
                price = q.get("price", "N/A")
                change_pct = q.get("change_pct", "")
                quote_lines.append(f"- {sym}: {price} ({change_pct}%)")
        quotes_block = "\n".join(quote_lines) if quote_lines else "无实时报价"

    return f"""你是一位专业的宏观市场状态分析师，专注于黄金和贵金属市场。默认使用简体中文。

任务：基于以下宏观指标、期权意图和实时报价，判断当前市场 regime 并给出环境过滤器。

## 可选 Regime 标签
- rate_pressure（利率压制态）：利率上升、实际利率走高，压制黄金
- transition_release（过渡释放态）：利率见顶回落，流动性边际改善
- trend_tailwind（趋势顺风态）：利率下行+美元弱+避险需求，黄金趋势性上涨
- consolidation（高位整固态）：价格高位震荡，无明确方向
- liquidity_crunch（流动性踩踏态）：流动性紧张，所有资产同跌
- direction_choice（方向抉择态）：多空因素交织，等待催化剂
- breakout_accumulation（突破前蓄势态）：价格收敛，波动率降低，等待突破

## 硬性规则
1. 只基于下方输入数据判断，不引入外部数据。
2. 给出明确 regime 判断和置信度。
3. 每个宏观指标给出简短解读（1-2 句）。
4. 环境过滤器必须给出明确方向判断。
5. 缺失数据标注"数据缺失"，不补造。

## 输出格式
严格使用以下 JSON 格式输出，不要输出其他内容：

```json
{{
  "regime": "rate_pressure|transition_release|trend_tailwind|consolidation|liquidity_crunch|direction_choice|breakout_accumulation",
  "regime_label_cn": "中文标签",
  "confidence": 0.0-1.0,
  "summary": "一句话 regime 判断",
  "environment_filters": {{
    "us10y": {{ "direction": "上升|下降|持平", "interpretation": "解读" }},
    "dxy": {{ "direction": "强|弱|中性", "interpretation": "解读" }},
    "us02y": {{ "direction": "上升|下降|持平", "interpretation": "解读" }},
    "xauusd_reaction": {{ "direction": "正相关|负相关|脱钩", "interpretation": "解读" }}
  }},
  "indicator_interpretations": {{
    "DXY": "解读",
    "US10Y": "解读",
    "REAL_10Y": "解读",
    "SOFR": "解读",
    "TGA": "解读",
    "RESERVES": "解读",
    "IORB": "解读"
  }},
  "key_drivers": ["驱动因素1", "驱动因素2", "驱动因素3"],
  "risk_factors": ["风险因素1", "风险因素2"]
}}
```

## 宏观指标
{indicator_block}

## 期权意图
{intent_block}

## 实时报价
{quotes_block}

请输出 JSON 分析结果。"""


def parse_regime_response(response_text: str) -> dict[str, Any]:
    """Parse LLM JSON response into structured fields."""
    text = response_text.strip()
    # Strip code fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
        else:
            text = "\n".join(lines[1:])
    # Try to extract JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON in text
        import re
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {}


def run_market_regime_agent(
    macro_snapshot: dict[str, Any],
    options_intent: dict[str, Any] | None = None,
    quotes: dict[str, Any] | None = None,
    *,
    snapshot_id: str = "",
    run_id: str = "",
) -> AgentOutput:
    """Run the Market Regime Agent with LLM, fallback to deterministic."""
    from apps.llm.gateway import chat_sync

    prompt = build_regime_prompt(macro_snapshot, options_intent, quotes)
    prompt_messages = [
        {"role": "system", "content": "你是市场状态分析师。只输出 JSON。"},
        {"role": "user", "content": prompt},
    ]
    input_payload = {
        "macro_snapshot": macro_snapshot,
        "options_intent": options_intent,
        "quotes": quotes,
    }

    try:
        response = chat_sync(
            messages=prompt_messages,
            temperature=0.2,
            max_tokens=2048,
            audit_context={
                "caller": "market_regime.run_market_regime_agent",
                "run_id": run_id,
                "snapshot_id": snapshot_id,
                "input_payload": input_payload,
            },
        )
        parsed = parse_regime_response(response.content)
        if not parsed:
            raise ValueError("Failed to parse LLM JSON response")

        regime = parsed.get("regime", "direction_choice")
        confidence = float(parsed.get("confidence", 0.5))
        summary = parsed.get("summary", "")
        env_filters = parsed.get("environment_filters", {})
        interpretations = parsed.get("indicator_interpretations", {})
        key_drivers = parsed.get("key_drivers", [])
        risk_factors = parsed.get("risk_factors", [])

        # Build findings
        findings = [
            f"Regime: {REGIME_LABELS.get(regime, regime)}",
            f"Confidence: {confidence:.0%}",
        ]
        for driver in key_drivers[:3]:
            findings.append(f"驱动: {driver}")

        # Build watchlist
        watchlist = [
            "利率方向: US10Y 是否继续上行",
            "美元强弱: DXY 走势",
            "期权意图: CME options intent 变化",
        ]

        return AgentOutput(
            version="1.0",
            agent_name="market_regime",
            module="market_monitor",
            snapshot_id=snapshot_id,
            input_snapshot_ids={"macro": snapshot_id},
            bias=_regime_to_bias(regime, confidence),
            confidence=confidence,
            key_findings=findings,
            risk_points=risk_factors,
            watchlist=watchlist,
            invalid_conditions=[
                "利率方向反转",
                "流动性指标异常波动",
                "地缘事件导致 regime 跳变",
            ],
            summary=summary,
            source_refs=[],
            status=AgentStatus.SUCCESS,
            created_at=datetime.now(timezone.utc),
            market_phase=regime,
            regime_drivers={
                "key_drivers": key_drivers,
                "environment_filters": env_filters,
                "indicator_interpretations": interpretations,
                "generated_by": "llm",
                "model": response.model,
                "provider": response.provider,
                "latency_ms": response.latency_ms,
            },
            data_category=DataCategory.EXTERNAL_OPINION,
            llm_model=response.model,
            llm_provider=response.provider,
            llm_usage=response.usage,
            llm_latency_ms=response.latency_ms,
            llm_audit_id=getattr(response, "audit_id", None),
            prompt_messages=prompt_messages,
            input_payload=input_payload,
            llm_raw_output=response.content,
        )
    except Exception as exc:
        logger.warning("Market Regime Agent LLM failed, using fallback: %s", exc)
        return _fallback_regime(macro_snapshot, snapshot_id, run_id)


def _regime_to_bias(regime: str, confidence: float) -> AgentBias:
    """Map regime to bias."""
    bullish_regimes = {"trend_tailwind", "transition_release"}
    bearish_regimes = {"rate_pressure", "liquidity_crunch"}
    if regime in bullish_regimes:
        return AgentBias.BULLISH if confidence > 0.6 else AgentBias.MIXED
    if regime in bearish_regimes:
        return AgentBias.BEARISH if confidence > 0.6 else AgentBias.MIXED
    return AgentBias.NEUTRAL


def _fallback_regime(
    macro_snapshot: dict[str, Any],
    snapshot_id: str,
    run_id: str,
) -> AgentOutput:
    """Deterministic fallback when LLM is unavailable."""
    indicators = macro_snapshot.get("indicators", {})

    # Simple rule-based regime classification
    us10y = indicators.get("US10Y", {})
    us10y_val = us10y.get("value") if isinstance(us10y, dict) else None

    regime = "direction_choice"
    confidence = 0.3

    if us10y_val and isinstance(us10y_val, (int, float)):
        if us10y_val > 4.5:
            regime = "rate_pressure"
            confidence = 0.5
        elif us10y_val < 3.5:
            regime = "transition_release"
            confidence = 0.4

    return AgentOutput(
        version="1.0",
        agent_name="market_regime",
        module="market_monitor",
        snapshot_id=snapshot_id,
        input_snapshot_ids={"macro": snapshot_id},
        bias=_regime_to_bias(regime, confidence),
        confidence=confidence,
        key_findings=[f"Regime: {REGIME_LABELS.get(regime, regime)} (fallback)"],
        risk_points=["LLM 不可用，使用规则引擎 fallback"],
        watchlist=["等待 LLM 恢复"],
        invalid_conditions=[],
        summary=f"市场状态: {REGIME_LABELS.get(regime, regime)} (规则引擎，低置信度)",
        source_refs=[],
        status=AgentStatus.PARTIAL,
        created_at=datetime.now(timezone.utc),
        market_phase=regime,
        regime_drivers={"generated_by": "fallback"},
        data_category=DataCategory.SYSTEM_INFERENCE,
    )
