from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from apps.analysis.services.market_odds_comparison import compare_market_odds
from apps.api.schemas.market_odds_evidence import (
    MarketOddsAnalysisContext,
    MarketOddsEvidenceGroup,
    MarketOddsEvidenceViewModel,
)
from apps.features.jin10.schemas.market_odds import Jin10MarketOddsEvidence

_GROUPS = (
    ("precious_metals", "黄金 / 白银", {"XAUUSD", "XAGUSD"}),
    ("oil", "WTI", {"WTI"}),
    ("policy_events", "政策与事件", {"FED_POLICY_RATE", "STRAIT_OF_HORMUZ"}),
    ("other_assets", "其他资产", set()),
)
_FRESH_MAX_HOURS = 72
_STALE_MAX_HOURS = 168


def load_report_market_odds_view(*, storage_root: Path, trade_date: str | None, article_id: str) -> MarketOddsEvidenceViewModel | None:
    candidates = []
    if trade_date:
        candidates.extend([
            storage_root / "features" / "jin10" / trade_date / article_id / "market_odds_evidence.json",
            storage_root / "outputs" / "jin10" / trade_date / article_id / "market_odds_evidence.json",
        ])
    for path in candidates:
        if not path.is_file():
            continue
        try:
            feature = Jin10MarketOddsEvidence.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError, json.JSONDecodeError):
            continue
        return build_market_odds_view(
            feature,
            asset_base_url=f"/api/jin10/report-bundle/{trade_date}/{article_id}/asset/figures/",
            internal_market_odds=_load_internal_market_odds(storage_root=storage_root, trade_date=trade_date),
            agent_analysis=_load_accepted_agent_analysis(
                storage_root=storage_root,
                trade_date=trade_date,
                article_id=article_id,
            ),
        )
    return None


def load_latest_report_market_odds_view(*, storage_root: Path) -> MarketOddsEvidenceViewModel | None:
    base = storage_root / "features" / "jin10"
    if not base.is_dir():
        return None
    for date_dir in sorted((item for item in base.iterdir() if item.is_dir()), reverse=True):
        article_dirs = sorted((item for item in date_dir.iterdir() if item.is_dir()), reverse=True)
        for article_dir in article_dirs:
            view = load_report_market_odds_view(
                storage_root=storage_root,
                trade_date=date_dir.name,
                article_id=article_dir.name,
            )
            if view is not None:
                return view
    return None


def build_market_odds_view(
    feature: Jin10MarketOddsEvidence,
    *,
    asset_base_url: str | None = None,
    internal_market_odds: list[dict[str, Any]] | None = None,
    agent_analysis: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> MarketOddsEvidenceViewModel:
    raw_items = [item.model_dump(mode="json") for item in feature.items]
    evaluated_at = _as_utc(now or datetime.now(timezone.utc))
    for item in raw_items:
        item["observed_at"] = feature.published_at
        item.update(_analysis_eligibility(item, observed_at=feature.published_at, evaluated_at=evaluated_at))
    if asset_base_url:
        for item in raw_items:
            figure_id = str(item.get("figure_id") or "").strip()
            if figure_id:
                item["image_url"] = f"{asset_base_url}{figure_id}.png"
                item["image_kind"] = "figure_crop"
    assigned: set[str] = set()
    groups: list[MarketOddsEvidenceGroup] = []
    for key, label, assets in _GROUPS:
        if assets:
            items = [item for item in raw_items if item.get("asset") in assets]
        else:
            items = [item for item in raw_items if str(item.get("item_id")) not in assigned]
        if not items:
            continue
        assigned.update(str(item.get("item_id")) for item in items)
        groups.append(MarketOddsEvidenceGroup(group_key=key, label=label, items=items))
    eligible_items = [item for item in raw_items if item.get("analysis_eligible") is True]
    comparisons = _comparable_internal_odds(eligible_items, internal_market_odds or [])
    return MarketOddsEvidenceViewModel(
        article_id=feature.article_id,
        report_id=feature.report_id,
        trade_date=feature.published_at[:10],
        as_of=feature.published_at,
        source_verification_status=feature.source_verification_status,
        extraction_status=feature.extraction_status,
        panel_count=feature.panel_count,
        groups=groups,
        interpretation={
            "structure_label": "raw_probability_distribution",
            "directional_interpretation": "unavailable_without_spot_reference",
            "notice": "外部单源赔率仅作辅助证据，不独立决定策略方向或 readiness。",
        },
        analysis_context=_build_analysis_context(raw_items=eligible_items, agent_analysis=agent_analysis),
        internal_comparisons=comparisons,
        evidence_items=raw_items,
        parser_version=feature.parser_version,
        feature_schema_version=feature.schema_version,
    )


def _analysis_eligibility(
    item: dict[str, Any],
    *,
    observed_at: str,
    evaluated_at: datetime,
) -> dict[str, Any]:
    reasons: list[str] = []
    observed = _parse_timestamp(observed_at)
    horizon_end = _horizon_end(item)
    if horizon_end is None:
        freshness_status = "historical"
        reasons.append("horizon_missing_or_invalid")
    elif evaluated_at > horizon_end:
        freshness_status = "expired"
        reasons.append("horizon_expired")
    elif observed is None:
        freshness_status = "historical"
        reasons.append("observation_time_missing_or_invalid")
    else:
        age_hours = max((evaluated_at - observed).total_seconds() / 3600, 0.0)
        freshness_status = (
            "fresh"
            if age_hours <= _FRESH_MAX_HOURS
            else "stale"
            if age_hours <= _STALE_MAX_HOURS
            else "historical"
        )
        if freshness_status != "fresh":
            reasons.append(f"freshness_{freshness_status}")
    if item.get("extraction_status") != "accepted":
        reasons.append("extraction_not_accepted")
    if not _event_semantics_complete(item):
        reasons.append("event_semantics_incomplete")
    if not _evidence_anchor_complete(item):
        reasons.append("evidence_anchor_incomplete")
    return {
        "freshness_status": freshness_status,
        "analysis_eligible": not reasons,
        "analysis_block_reasons": list(dict.fromkeys(reasons)),
    }


def _event_semantics_complete(item: dict[str, Any]) -> bool:
    required = (
        item.get("asset"),
        item.get("event_type"),
        item.get("predicate"),
        item.get("target_value"),
        item.get("target_unit"),
        item.get("probability_semantics"),
        item.get("horizon_start"),
        item.get("horizon_end"),
    )
    return all(value not in {None, "", "unknown"} for value in required)


def _evidence_anchor_complete(item: dict[str, Any]) -> bool:
    return bool(item.get("page_no") and item.get("figure_id") and item.get("ocr_text"))


def _horizon_end(item: dict[str, Any]) -> datetime | None:
    text = str(item.get("horizon_end") or "").strip()
    if not text:
        return None
    try:
        local_zone = ZoneInfo(str(item.get("timezone") or "Asia/Shanghai"))
        parsed = datetime.fromisoformat(text)
    except (ValueError, KeyError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=local_zone)
    return _as_utc(parsed)


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _load_accepted_agent_analysis(
    *,
    storage_root: Path,
    trade_date: str,
    article_id: str,
) -> dict[str, Any] | None:
    path = storage_root / "outputs" / "jin10" / trade_date / article_id / "agent_analysis_report.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload if _is_accepted_agent_analysis(payload) else None


def _build_analysis_context(
    *,
    raw_items: list[dict[str, Any]],
    agent_analysis: dict[str, Any] | None,
) -> MarketOddsAnalysisContext:
    if _is_accepted_agent_analysis(agent_analysis):
        structure_summary = _first_text(
            agent_analysis.get("one_line_conclusion"),
            agent_analysis.get("final_summary"),
        )
        cross_asset = agent_analysis.get("cross_asset_analysis")
        cross_asset_gold = cross_asset.get("黄金与白银联动") if isinstance(cross_asset, dict) else None
        gold_implication = _first_text(agent_analysis.get("gold_analysis"), cross_asset_gold)
        confirmation_variables = _string_list(agent_analysis.get("unresolved_items"))
        if structure_summary and gold_implication:
            return MarketOddsAnalysisContext(
                source="accepted_agent_analysis",
                quality_status="accepted",
                structure_summary=structure_summary,
                gold_implication=gold_implication,
                confirmation_variables=confirmation_variables,
            )

    has_gold = any(item.get("asset") == "XAUUSD" for item in raw_items)
    return MarketOddsAnalysisContext(
        source="deterministic_fallback",
        quality_status="unavailable",
        structure_summary="当前仅展示外部报告的原始概率分布；没有通过质量审计的单篇赔率分析可供展示。",
        gold_implication=(
            "黄金赔率已作为战术价格分布证据保留，但在缺少现价距离和同语义内部赔率时不生成方向解释。"
            if has_gold
            else "当前外部赔率没有返回可用于黄金辅助分析的价格事件。"
        ),
        confirmation_variables=[
            "当前现货价格与赔率目标的距离",
            "同期限、同目标、同概率语义的内部市场赔率",
            "美元、实际利率与黄金价格的同步验证",
        ],
    )


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _is_accepted_agent_analysis(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    quality = value.get("quality_audit")
    if not isinstance(quality, dict) or quality.get("status") != "accepted":
        return False
    return all(
        isinstance(quality.get(field), dict) and quality[field].get("status") == "accepted"
        for field in ("input_quality_audit", "output_quality_audit")
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item or "").strip())]


def _load_internal_market_odds(*, storage_root: Path, trade_date: str) -> list[dict[str, Any]]:
    date_dir = storage_root / "features" / "snapshots" / "XAUUSD" / trade_date
    if not date_dir.is_dir():
        return []
    for run_dir in sorted((item for item in date_dir.iterdir() if item.is_dir()), reverse=True):
        path = run_dir / "premarket_snapshot.json"
        if not path.is_file():
            continue
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        market_odds = snapshot.get("market_odds") if isinstance(snapshot, dict) else None
        events = market_odds.get("events") if isinstance(market_odds, dict) else None
        if isinstance(events, list):
            observed_at = (
                snapshot.get("as_of")
                or snapshot.get("generated_at")
                or market_odds.get("as_of")
                or market_odds.get("generated_at")
            )
            return [
                _normalize_internal_event(item, observed_at=observed_at)
                for item in events
                if isinstance(item, dict)
            ]
    return []


def _normalize_internal_event(event: dict[str, Any], *, observed_at: Any = None) -> dict[str, Any]:
    return {
        "event_id": event.get("event_id"),
        "underlying": event.get("underlying") or event.get("symbol"),
        "event_type": "price_level" if event.get("event_type") == "price_target" else event.get("event_type"),
        "predicate": event.get("predicate"),
        "target_value": event.get("target_value"),
        "target_unit": event.get("target_unit"),
        "probability_semantics": event.get("probability_semantics"),
        "horizon_start": event.get("horizon_start"),
        "horizon_end": event.get("horizon_end"),
        "probability": event.get("final_probability"),
        "observed_at": event.get("observed_at") or event.get("as_of") or observed_at,
        "source_refs": event.get("source_refs") or [],
    }


def _comparable_internal_odds(
    external_items: list[dict[str, Any]],
    internal_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for external in external_items:
        if external.get("extraction_status") != "accepted":
            continue
        for internal in internal_events:
            comparison = compare_market_odds(external=external, internal=internal)
            if comparison["comparison_status"] == "not_comparable":
                continue
            comparisons.append({
                **comparison,
                "external_item_id": external.get("item_id"),
                "internal_event_id": internal.get("event_id"),
            })
    return comparisons
