from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.features.jin10.schemas.market_odds import Jin10MarketOddsEvidence, MarketOddsEvidenceItem

ARTIFACT_NAME = "market_odds_evidence.json"
SOURCE_KIND = "jin10_external_market_odds"
SUPPLEMENTAL_INFLUENCE_POLICY = {
    "can_change_macro_regime": False,
    "can_set_strategy_direction": False,
    "can_block_readiness": False,
    "can_raise_confidence_alone": False,
    "can_support_existing_view": True,
    "can_weaken_existing_view": True,
    "can_add_watch_variables": True,
    "can_add_risk_points": True,
}

_PERCENT_LINE_RE = re.compile(r"(?P<label>[^\n。；;]{2,100}?)\s*(?:概率(?:为|达到|升至|降至)?\s*)?(?P<pct>\d{1,3}(?:\.\d+)?)\s*%")
_LEVEL_RE = re.compile(r"(?P<value>\d{2,6}(?:\.\d+)?)")
_DATE_RE = re.compile(r"(?:(?P<year>20\d{2})年)?(?P<month>\d{1,2})月(?P<day>\d{1,2})日")
_YEAR_RE = re.compile(r"(?P<year>20\d{2})年(?:内|底|年底)")

_ASSETS = (
    ("美元兑日元", "USDJPY", "JPY_per_USD"),
    ("美元日元", "USDJPY", "JPY_per_USD"),
    ("USDJPY", "USDJPY", "JPY_per_USD"),
    ("黄金", "XAUUSD", "USD_per_oz"),
    ("白银", "XAGUSD", "USD_per_oz"),
    ("WTI", "WTI", "USD_per_bbl"),
    ("原油", "WTI", "USD_per_bbl"),
    ("美联储", "FED_POLICY_RATE", "event"),
    ("霍尔木兹", "STRAIT_OF_HORMUZ", "event"),
)


def build_jin10_market_odds_evidence(
    *,
    article_id: str,
    published_at: str,
    parser_version: str,
    figures: list[dict[str, Any]],
    vision_layout: dict[str, Any] | None = None,
    markdown_context: str = "",
    source_refs: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> Jin10MarketOddsEvidence:
    """Build external odds evidence from anchored VLM figures/blocks.

    Markdown may supply surrounding horizon context, but probability rows are
    only emitted from text attached to a concrete page/figure anchor.
    """
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    anchors = _anchored_inputs(figures=figures, vision_layout=vision_layout or {})
    items: list[MarketOddsEvidenceItem] = []
    for anchor in anchors:
        for panel_index, panel_text in enumerate(_split_panels(anchor["text"]), start=1):
            panel_id = f'{anchor["figure_id"]}:panel_{panel_index:02d}'
            items.extend(
                _extract_panel_items(
                    article_id=article_id,
                    published_at=published_at,
                    panel_id=panel_id,
                    panel_text=panel_text,
                    markdown_context=markdown_context,
                    anchor=anchor,
                    source_refs=source_refs or [],
                )
            )
    items = _dedupe_items(items)
    statuses = {item.extraction_status for item in items}
    has_unanchored_probability_context = not anchors and "%" in markdown_context
    extraction_status = (
        "accepted"
        if items and statuses == {"accepted"}
        else "needs_review"
        if items or has_unanchored_probability_context
        else "rejected"
    )
    return Jin10MarketOddsEvidence(
        feature_id=f"jin10-market-odds:{article_id}:{published_at}",
        article_id=article_id,
        report_id=f"jin10:{article_id}",
        published_at=published_at,
        generated_at=generated,
        extraction_status=extraction_status,
        parser_version=parser_version,
        panel_count=len({item.panel_id for item in items if item.extraction_status != "rejected"}),
        items=items,
        source_refs=source_refs or [],
    )


def write_market_odds_evidence(feature: Jin10MarketOddsEvidence, *, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / ARTIFACT_NAME
    target.write_text(feature.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target


def to_daily_market_observation(feature: Jin10MarketOddsEvidence | dict[str, Any]) -> dict[str, Any]:
    payload = feature.model_dump(mode="json") if isinstance(feature, Jin10MarketOddsEvidence) else dict(feature)
    return {
        "observation_type": "external_market_odds",
        "source_kind": SOURCE_KIND,
        "provider_role": "supplemental_source",
        "article_id": payload.get("article_id"),
        "as_of": payload.get("published_at"),
        "source_verification_status": payload.get("source_verification_status", "single_source"),
        "extraction_status": payload.get("extraction_status", "needs_review"),
        "influence_policy": dict(SUPPLEMENTAL_INFLUENCE_POLICY),
        "items": [dict(item) for item in payload.get("items") or [] if isinstance(item, dict)],
        "source_refs": [dict(ref) for ref in payload.get("source_refs") or [] if isinstance(ref, dict)],
    }


def _anchored_inputs(*, figures: list[dict[str, Any]], vision_layout: dict[str, Any]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    pages = {int(page.get("page_no") or 0): page for page in vision_layout.get("pages") or [] if isinstance(page, dict)}
    for figure in figures:
        if not isinstance(figure, dict):
            continue
        page_no = int(figure.get("page_no") or 0)
        text = str(figure.get("recognized_text") or figure.get("text") or figure.get("markdown") or figure.get("title") or "").strip()
        if not text and page_no in pages:
            text = "\n".join(
                str(block.get("text") or "").strip()
                for block in pages[page_no].get("blocks") or []
                if isinstance(block, dict) and block.get("text")
            )
        figure_id = str(figure.get("figure_id") or "").strip()
        if page_no > 0 and figure_id and text:
            anchors.append({"page_no": page_no, "figure_id": figure_id, "bbox": figure.get("bbox"), "text": text})
    return anchors


def _split_panels(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n")
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*(?=(?:0?[1-9]|[一二三四五六])[.、\s]|(?:美元日元|霍尔木兹|美联储|WTI|黄金|白银)\s*[:：])", normalized) if chunk.strip()]
    probability_chunks = [chunk for chunk in chunks if "%" in chunk]
    return probability_chunks or ([normalized.strip()] if "%" in normalized else [])


def _extract_panel_items(**kwargs: Any) -> list[MarketOddsEvidenceItem]:
    panel_text = str(kwargs["panel_text"])
    published_at = str(kwargs["published_at"])
    asset, unit = _infer_asset(panel_text)
    if not asset:
        asset, unit = _infer_asset_from_context(panel_text, str(kwargs["markdown_context"]))
    horizon_start = published_at[:10]
    context_window = _context_window_for_panel(panel_text, str(kwargs["markdown_context"]))
    horizon_end = _infer_horizon(panel_text, published_at) or _infer_horizon(context_window, published_at)
    anchor = kwargs["anchor"]
    rows: list[MarketOddsEvidenceItem] = []
    for item_index, match in enumerate(_PERCENT_LINE_RE.finditer(panel_text), start=1):
        label = match.group("label").strip(" -|：:")
        probability = float(match.group("pct")) / 100.0
        if probability > 1:
            continue
        event_type, predicate, direction, target, target_unit, semantics = _semantics(label, asset, unit)
        complete = bool(asset and horizon_end and target is not None and predicate and semantics)
        status = "accepted" if complete else "needs_review"
        raw = match.group(0).strip()
        item_key = (
            f'{kwargs["article_id"]}:{anchor["figure_id"]}:{kwargs["panel_id"]}:'
            f'{item_index}:{asset or "unknown"}:{predicate or "unknown"}:{target}:{horizon_end or "unknown"}'
        )
        rows.append(MarketOddsEvidenceItem(
            item_id=item_key,
            panel_id=kwargs["panel_id"],
            asset=asset or "unknown",
            event_type=event_type,
            predicate=predicate or "unknown",
            direction=direction,
            target_value=target if target is not None else "unknown",
            target_unit=target_unit,
            horizon_start=horizon_start,
            horizon_end=horizon_end or "",
            probability=probability,
            probability_raw=f'{match.group("pct")}%',
            probability_semantics=semantics or "unknown",
            outcome_label=label,
            extraction_confidence=0.96 if status == "accepted" else 0.55,
            extraction_status=status,
            page_no=anchor["page_no"],
            figure_id=anchor["figure_id"],
            bbox=anchor.get("bbox"),
            ocr_text=raw,
            source_refs=kwargs["source_refs"],
            evidence_refs=[{"page_no": anchor["page_no"], "figure_id": anchor["figure_id"], "bbox": anchor.get("bbox")}],
        ))
    return rows


def _infer_asset(text: str) -> tuple[str, str]:
    for marker, asset, unit in _ASSETS:
        if marker.lower() in text.lower():
            return asset, unit
    if "加息" in text:
        return "FED_POLICY_RATE", "event"
    if "恢复正常" in text or "交通恢复" in text:
        return "STRAIT_OF_HORMUZ", "event"
    return "", "unknown"


def _infer_asset_from_context(panel_text: str, context: str) -> tuple[str, str]:
    """Use report Markdown only to label an already figure-anchored panel."""
    window = _context_window_for_panel(panel_text, context)
    if not window:
        return "", "unknown"
    best: tuple[int, str, str] | None = None
    for marker, asset, unit in _ASSETS:
        marker_at = window.lower().rfind(marker.lower())
        if marker_at < 0:
            continue
        distance = len(window) - marker_at
        if best is None or distance < best[0]:
            best = (distance, asset, unit)
    return (best[1], best[2]) if best else ("", "unknown")


def _context_window_for_panel(panel_text: str, context: str) -> str:
    first = _PERCENT_LINE_RE.search(panel_text)
    if first is None or not context:
        return ""
    pct_marker = f'{first.group("pct")}%'
    target_match = _LEVEL_RE.search(first.group("label"))
    target_marker = target_match.group("value") if target_match else ""
    candidates: list[str] = []
    for percent_match in re.finditer(re.escape(pct_marker), context):
        paragraph_start = context.rfind("\n\n", 0, percent_match.start())
        start = paragraph_start + 2 if paragraph_start >= 0 else 0
        paragraph_end = context.find("\n\n", percent_match.end())
        end = paragraph_end if paragraph_end >= 0 else len(context)
        window = context[start:end]
        if not target_marker or target_marker in window:
            probability_at = window.find(pct_marker)
            if probability_at >= 0:
                marker_positions = [
                    window.lower().rfind(marker.lower(), 0, probability_at)
                    for marker, _, _ in _ASSETS
                ]
                nearest_marker = max(marker_positions, default=-1)
                if nearest_marker >= 0:
                    window = window[nearest_marker:probability_at + len(pct_marker)]
            candidates.append(window)
    return min(candidates, key=len) if candidates else ""


def _infer_horizon(text: str, published_at: str) -> str | None:
    date_match = _DATE_RE.search(text)
    if date_match:
        year = int(date_match.group("year") or published_at[:4])
        return f'{year:04d}-{int(date_match.group("month")):02d}-{int(date_match.group("day")):02d}'
    year_match = _YEAR_RE.search(text)
    if year_match:
        return f'{int(year_match.group("year")):04d}-12-31'
    month_match = re.search(r"(?P<month>\d{1,2})月(?:内|底|月底|(?=触及))", text)
    if month_match:
        month = int(month_match.group("month"))
        next_month = datetime(int(published_at[:4]) + (month == 12), month % 12 + 1, 1)
        from datetime import timedelta
        return (next_month - timedelta(days=1)).date().isoformat()
    return None


def _semantics(label: str, asset: str, unit: str) -> tuple[str, str, str, float | str | None, str, str]:
    if asset == "FED_POLICY_RATE":
        return "policy_outcome", "rate_hike_occurs", "event", "rate_hike", "event", "event_occurs_before_horizon"
    if asset == "STRAIT_OF_HORMUZ":
        return "event_outcome", "normal_operations_resume", "event", "normal_operations", "event", "event_occurs_before_horizon"
    level = _LEVEL_RE.search(label)
    target = float(level.group("value")) if level else None
    if any(token in label for token in ("向下", "下方", "跌破", "低于")):
        return "price_level", "touch_below", "down", target, unit, "ever_touch_before_horizon"
    if any(token in label for token in ("向上", "上方", "触及", "升破", "高于")):
        return "price_level", "touch_above", "up", target, unit, "ever_touch_before_horizon"
    return "price_level", "", "neutral", target, unit, ""


def _dedupe_items(items: list[MarketOddsEvidenceItem]) -> list[MarketOddsEvidenceItem]:
    seen: set[str] = set()
    result: list[MarketOddsEvidenceItem] = []
    for item in items:
        key = hashlib.sha256(json.dumps([item.item_id, item.probability], ensure_ascii=False).encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            result.append(item)
    probabilities_by_event: dict[tuple[Any, ...], set[float]] = {}
    for item in result:
        probabilities_by_event.setdefault(_standard_event_key(item), set()).add(item.probability)
    conflict_flag = "duplicate_event_conflicting_probability"
    return [
        item.model_copy(
            update={
                "extraction_status": "needs_review",
                "validation_flags": [*item.validation_flags, conflict_flag],
            }
        )
        if len(probabilities_by_event[_standard_event_key(item)]) > 1
        else item
        for item in result
    ]


def _standard_event_key(item: MarketOddsEvidenceItem) -> tuple[Any, ...]:
    return (
        item.figure_id,
        item.asset,
        item.event_type,
        item.predicate,
        item.target_value,
        item.target_unit,
        item.probability_semantics,
        item.horizon_start,
        item.horizon_end,
    )
