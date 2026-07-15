"""News agent — generate a NEUTRAL risk opinion from the news snapshot.

Returns a read-only ``AgentOutput`` describing recent macro events,
flash volume, and derived risk concerns.

BIAS IS ALWAYS NEUTRAL — news provides risk signals, not price direction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory

_AGENT_NAME = "news_agent"
_MODULE = "news"
_VERSION = "1.0"


def analyze_news(
    snapshot: dict[str, Any], *, created_at: datetime | None = None
) -> AgentOutput:
    """Analyze the news section of an already-loaded analysis snapshot."""

    created_at = created_at or datetime.now(timezone.utc)
    if not isinstance(snapshot, dict):
        return _unavailable("News input must be an already-loaded snapshot dictionary.")

    snapshot_id = str(snapshot.get("snapshot_id") or "unknown")
    input_snapshot_ids = _input_snapshot_ids(snapshot)
    source_refs = _news_source_refs(snapshot)
    news = snapshot.get("news")

    if not isinstance(news, dict) or news.get("status") != "available":
        reason = (
            "news section is missing"
            if not isinstance(news, dict)
            else f"news status is {news.get('status')!r}"
        )
        return AgentOutput(
            version=_VERSION,
            agent_name=_AGENT_NAME,
            module=_MODULE,
            snapshot_id=snapshot_id,
            input_snapshot_ids=input_snapshot_ids,
            bias=AgentBias.NEUTRAL,
            confidence=0.0,
            key_findings=[],
            risk_points=["新闻输入不可用。"],
            watchlist=["FOMC", "CPI", "NFP", "PCE"],
            invalid_conditions=[reason],
            summary="新闻输入不可用；未生成只读结论。",
            source_refs=source_refs,
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            data_category=DataCategory.SYSTEM_INFERENCE,
        )

    data_any = news.get("data")
    data: dict[str, Any] = data_any if isinstance(data_any, dict) else {}
    daily_market_brief = _daily_market_brief(data)
    if daily_market_brief:
        return _analyze_daily_market_brief(
            daily_market_brief,
            snapshot_id=snapshot_id,
            input_snapshot_ids=input_snapshot_ids,
            source_refs=source_refs,
            created_at=created_at,
        )

    key_findings: list[str] = []
    risk_points: list[str] = []
    invalid_conditions: list[str] = []
    watchlist = ["FOMC", "CPI", "NFP", "PCE"]
    confidence = 0.50
    status = AgentStatus.SUCCESS

    # ── Risk level ─────────────────────────────────────────────────────
    risk_level = str(data.get("risk_level", "LOW")).upper()
    high_star = int(data.get("high_star_count_7d", 0))

    if risk_level == "HIGH":
        key_findings.append(
            f"News risk level: HIGH ({high_star} high-impact events in recent 7d)."
        )
        risk_points.append(
            "Recent macro events are high-impact; elevated headline-driven volatility risk."
        )
        confidence = 0.72
    elif risk_level == "MEDIUM":
        key_findings.append(
            f"News risk level: MEDIUM ({high_star} high-impact events in recent 7d)."
        )
        risk_points.append(
            "Moderate macro event risk; some headline-driven volatility possible."
        )
        confidence = 0.62
    else:
        key_findings.append(
            "News risk level: LOW (no high-impact events in recent 7 days)."
        )
        confidence = 0.55

    # ── Recent events ──────────────────────────────────────────────────
    events = data.get("recent_events")
    if isinstance(events, list) and events:
        top = events[:3]
        key_findings.append("Top recent events:")
        for event in top:
            if isinstance(event, dict):
                title = event.get("title", "Unknown")
                time_str = str(event.get("pub_time", ""))[:16]
                star = int(event.get("star", 0))
                key_findings.append(f"  - {title} ({'★' * star} {time_str})")
                if star >= 4:
                    risk_points.append(f"High-impact event completed: {title} on {time_str}.")
        if len(events) > 3:
            key_findings.append(f"  ... and {len(events) - 3} more events.")
        confidence = min(confidence + 0.03 * min(len(events), 5), 0.80)
    else:
        invalid_conditions.append("No recent calendar events available.")
        confidence -= 0.05

    # ── Flashes ────────────────────────────────────────────────────────
    flashes = data.get("recent_flashes")
    if isinstance(flashes, list) and flashes:
        flash_count = len(flashes)
        key_findings.append(
            f"{flash_count} flash headlines collected (deduplicated)."
        )

        # Detect keyword hits via URL (flash content is in raw payload)
        keywords = {"美联储", "FOMC", "利率", "CPI", "非农", "PCE"}
        hit_count = sum(
            1 for f in flashes
            if isinstance(f, dict)
            and any(kw in str(f.get("url", "")) for kw in keywords)
        )
        if hit_count >= 3:
            risk_points.append(
                f"{hit_count} flash headlines mention key macro topics — elevated news flow."
            )
        confidence = min(confidence + 0.02 * min(hit_count, 3), 0.80)
    else:
        invalid_conditions.append("No flash headlines available; news signal may be stale.")
        confidence -= 0.08

    # ── Data quality ───────────────────────────────────────────────────
    if (not isinstance(events, list) or not events) and (
        not isinstance(flashes, list) or not flashes
    ):
        status = AgentStatus.PARTIAL
        confidence -= 0.12
        invalid_conditions.append("Both calendar events and flash headlines are empty.")

    # ── Final output ───────────────────────────────────────────────────
    if not key_findings:
        key_findings.append("News module is available but no significant findings.")

    return AgentOutput(
        version=_VERSION,
        agent_name=_AGENT_NAME,
        module=_MODULE,
        snapshot_id=snapshot_id,
        input_snapshot_ids=input_snapshot_ids,
        bias=AgentBias.NEUTRAL,
        confidence=_clamp(confidence, 0.0, 0.80),
        key_findings=key_findings,
        risk_points=risk_points,
        watchlist=watchlist,
        invalid_conditions=invalid_conditions,
        summary=_summary(risk_level, status, _clamp(confidence, 0.0, 0.80)),
        source_refs=source_refs,
        status=status,
        created_at=created_at,
        data_category=DataCategory.SYSTEM_INFERENCE,
    )


def _unavailable(reason: str) -> AgentOutput:
    return AgentOutput(
        version=_VERSION,
        agent_name=_AGENT_NAME,
        module=_MODULE,
        snapshot_id="unknown",
        input_snapshot_ids={},
        bias=AgentBias.NEUTRAL,
        confidence=0.0,
        key_findings=[],
        risk_points=[reason],
        watchlist=[],
        invalid_conditions=[reason],
        summary=f"News unavailable: {reason}",
        source_refs=[],
        status=AgentStatus.UNAVAILABLE,
        created_at=datetime.now(timezone.utc),
        data_category=DataCategory.SYSTEM_INFERENCE,
    )


def _input_snapshot_ids(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("input_snapshot_ids")
    ids = dict(value) if isinstance(value, dict) else {}
    snapshot_id = snapshot.get("snapshot_id")
    if snapshot_id is not None:
        ids.setdefault("analysis_snapshot", snapshot_id)
    return ids


def _news_source_refs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for candidate in (
        snapshot.get("source_refs"),
        snapshot.get("news", {}).get("data", {}).get("source_refs"),
        snapshot.get("news", {}).get("data", {}).get("daily_market_brief", {}).get("source_refs"),
    ):
        if isinstance(candidate, list):
            refs.extend(dict(item) for item in candidate if isinstance(item, dict))
    return refs


def _daily_market_brief(data: dict[str, Any]) -> dict[str, Any] | None:
    candidate = data.get("daily_market_brief")
    if isinstance(candidate, dict):
        return candidate
    if any(key in data for key in ("market_mainline", "confirmed_events", "candidate_events", "report_inputs")):
        return data
    return None


def _analyze_daily_market_brief(
    brief: dict[str, Any],
    *,
    snapshot_id: str,
    input_snapshot_ids: dict[str, Any],
    source_refs: list[dict[str, Any]],
    created_at: datetime,
) -> AgentOutput:
    confirmed_events = _dict_list(brief.get("confirmed_events"))
    candidate_events = _dict_list(brief.get("candidate_events"))
    unconfirmed_risks = _dict_list(brief.get("unconfirmed_risks"))
    next_calendar = _dict_list(brief.get("next_7d_calendar"))
    report_inputs = brief.get("report_inputs") if isinstance(brief.get("report_inputs"), dict) else {}
    external_market_odds = [
        item
        for item in _dict_list(report_inputs.get("market_observations"))
        if item.get("source_kind") == "jin10_external_market_odds"
        or item.get("observation_type") == "external_market_odds"
    ]
    etf_holdings = next(iter(_dict_list(report_inputs.get("etf_holdings"))), {})
    etf_claims = _etf_holdings_claims(etf_holdings)
    market_mainline = brief.get("market_mainline") if isinstance(brief.get("market_mainline"), dict) else {}

    key_findings: list[str] = []
    risk_points: list[str] = []
    watchlist: list[str] = []
    invalid_conditions: list[str] = []

    mainline_summary = str(market_mainline.get("summary") or "").strip()
    if mainline_summary:
        key_findings.append(f"事件主线: {mainline_summary}")
    for claim in etf_claims:
        key_findings.append(str(claim.get("claim_text") or ""))

    for event in confirmed_events[:5]:
        key_findings.append(_event_line(prefix="确认事件", event=event))

    for event in unconfirmed_risks[:5]:
        risk_points.append(_event_line(prefix="待确认风险", event=event))

    # Candidate events remain watchlist-only unless already official-confirmed.
    for event in candidate_events[:8]:
        if event.get("verification_status") == "official_confirmed":
            continue
        watchlist.append(_event_line(prefix="观察事件", event=event))

    for item in _dict_list(report_inputs.get("watchlist"))[:5]:
        watchlist.append(_event_line(prefix="报告观察", event=item))
    for item in _dict_list(report_inputs.get("risk_points"))[:5]:
        risk_points.append(str(item))
    for observation in external_market_odds[:5]:
        items = _dict_list(observation.get("items"))
        article_id = str(observation.get("article_id") or "unknown")
        watchlist.append(f"外部赔率观察: Jin10 {article_id} | {len(items)} 条 | 仅作辅助证据")
        if observation.get("extraction_status") != "accepted":
            risk_points.append(f"外部赔率 {article_id} 含待复核识别项，不得升级为方向结论。")
    for item in next_calendar[:5]:
        watchlist.append(
            f"官方日历: {item.get('event_name') or item.get('what_happened') or 'unknown'}"
            f" | {item.get('event_time') or ''}"
            f" | {item.get('expected_impact_path') or item.get('impact_path') or 'unknown'}"
        )

    if not key_findings:
        key_findings.append("Daily market brief is available, but no official-confirmed event is present.")
    if not confirmed_events:
        invalid_conditions.append("No official-confirmed news event in daily_market_brief.")
    if candidate_events or unconfirmed_risks:
        invalid_conditions.append("Single-source or unofficial events must remain watchlist until verified.")
    if external_market_odds:
        invalid_conditions.append("External market odds cannot independently set direction, macro regime, confidence, or readiness.")
    if etf_claims:
        invalid_conditions.append("Jin10 ETF holdings are single-source supplemental observations and require source-tier labeling.")

    confidence = 0.58
    if confirmed_events:
        confidence += 0.08
    if unconfirmed_risks:
        confidence += 0.04
    if market_mainline.get("risk_level") == "high":
        confidence += 0.04

    return AgentOutput(
        version=_VERSION,
        agent_name=_AGENT_NAME,
        module=_MODULE,
        snapshot_id=snapshot_id,
        input_snapshot_ids=input_snapshot_ids,
        bias=AgentBias.NEUTRAL,
        confidence=_clamp(confidence, 0.0, 0.80),
        key_findings=_dedupe_strings(key_findings),
        risk_points=_dedupe_strings(risk_points),
        watchlist=_dedupe_strings(watchlist),
        invalid_conditions=_dedupe_strings(invalid_conditions),
        summary=(
            f"新闻事件雷达：确认事件 {len(confirmed_events)} 条，"
            f"候选事件 {len(candidate_events)} 条，未确认风险 {len(unconfirmed_risks)} 条；"
            "方向判断保持中性，影响路径交由事件影响层处理。"
        ),
        source_refs=source_refs,
        status=AgentStatus.SUCCESS,
        created_at=created_at,
        data_category=DataCategory.SYSTEM_INFERENCE,
        input_payload={
            "daily_market_brief": brief,
            "external_market_odds": external_market_odds,
            "external_market_odds_count": len(external_market_odds),
            "etf_holdings": etf_holdings,
            "claims": etf_claims,
        },
        evidence_refs=[
            {
                "type": "daily_market_brief",
                "confirmed_event_count": len(confirmed_events),
                "candidate_event_count": len(candidate_events),
                "unconfirmed_risk_count": len(unconfirmed_risks),
            },
            *(
                [{"type": "etf_holdings_feature", "artifact_path": etf_holdings.get("artifact_path")}]
                if etf_holdings.get("artifact_path")
                else []
            ),
        ],
        evidence_items=[
            {
                "factor": "external_market_odds",
                "source_kind": "jin10_external_market_odds",
                "provider_role": "supplemental_source",
                "source_tier": "external_single_source",
                "article_id": observation.get("article_id"),
                "extraction_status": observation.get("extraction_status"),
                "influence_policy": observation.get("influence_policy") or {},
            }
            for observation in external_market_odds
        ],
    )


def _etf_holdings_claims(context: dict[str, Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    source_refs = [dict(ref) for ref in context.get("source_refs") or [] if isinstance(ref, dict)]
    artifact_path = context.get("artifact_path")
    for asset, label in (("gold", "黄金 SPDR ETF"), ("silver", "白银 iShares ETF")):
        holdings = context.get(f"{asset}_etf_holdings_tonnes")
        change = context.get(f"{asset}_etf_change_tonnes")
        reported_on = context.get(f"{asset}_etf_reported_on")
        if not isinstance(holdings, (int, float)) or isinstance(holdings, bool):
            continue
        change_text = "未知"
        predicate = "unchanged"
        if isinstance(change, (int, float)) and not isinstance(change, bool):
            change_text = f"{change:+,.2f} 吨"
            predicate = "increased" if change > 0 else "decreased" if change < 0 else "unchanged"
        claims.append(
            {
                "claim_id": f"news_agent:{asset}_etf_holdings:{reported_on or 'unknown'}",
                "claim_type": "observed_fact",
                "claim_text": f"{label}持仓 {float(holdings):,.2f} 吨，日变动 {change_text}（{reported_on or '日期未知'}）。",
                "subject": f"{asset}_etf",
                "metric": "holdings_tonnes",
                "predicate": predicate,
                "horizon": "daily",
                "scope": asset,
                "observation_time": reported_on,
                "value": float(holdings),
                "change": change,
                "source_refs": [
                    ref for ref in source_refs
                    if ref.get("asset") in {None, asset}
                ],
                "evidence_refs": [
                    {"type": "etf_holdings_feature", "artifact_path": artifact_path}
                ] if artifact_path else [],
            }
        )
    return claims


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _event_line(*, prefix: str, event: dict[str, Any]) -> str:
    title = event.get("what_happened") or event.get("event_name") or event.get("event_type") or "unknown"
    verification = event.get("verification_status") or "unknown"
    impact_path = event.get("impact_path") or event.get("expected_impact_path") or "unknown"
    pricing = event.get("pricing_status") or "unknown"
    event_id = event.get("event_id") or "no_event_id"
    return f"{prefix}: {title} | {verification} | {impact_path} | pricing={pricing} | event_id={event_id}"


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


def _summary(risk_level: str, status: AgentStatus, confidence: float) -> str:
    if status is AgentStatus.UNAVAILABLE:
        return f"新闻只读视图不可用；确信度 {confidence:.2f}。"
    if status is AgentStatus.PARTIAL:
        return f"新闻只读视图：风险={risk_level}（不完整）；确信度 {confidence:.2f}。"
    return f"新闻只读视图：风险={risk_level}；确信度 {confidence:.2f}。"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, round(value, 2)))
