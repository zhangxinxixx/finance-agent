from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

RULE_VERSION = "jin10-positioning-report-inputs-v1"
PROVIDER_ROLE = "supplemental_source"
VERIFICATION_STATUS = "single_source"
DEFAULT_CONFIDENCE = 0.72

_ASSET_ALIASES = {
    "XAUUSD": "XAUUSD",
    "黄金": "XAUUSD",
    "COMEX黄金": "XAUUSD",
    "伦敦金": "XAUUSD",
    "白银": "XAGUSD",
    "XAGUSD": "XAGUSD",
    "原油": "WTI",
    "WTI": "WTI",
    "美元": "DXY",
    "DXY": "DXY",
}

_LEVEL_RE = re.compile(r"(?<!\d)(\d{2,6}(?:\.\d+)?)(?!\d)")
def extract_jin10_positioning_report_inputs(
    *,
    report_text: str = "",
    vlm_markdown: str = "",
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract supplemental positioning facts from Jin10 category/274 report text.

    The output is intentionally evidence-only. It marks Jin10 as a supplemental
    single-source provider and does not produce trading recommendations.
    """

    refs = _source_refs(source_refs)
    combined_text = "\n".join(part for part in [report_text, vlm_markdown] if part)
    inputs = _dedupe_inputs(
        [
            *_extract_from_report_text(report_text, refs=refs, default_asset=_infer_asset(combined_text)),
            *_extract_from_markdown_table(vlm_markdown, refs=refs),
        ]
    )
    return {
        "schema_version": RULE_VERSION,
        "report_type": "positioning",
        "provider_role": PROVIDER_ROLE,
        "verification_status": VERIFICATION_STATUS,
        "input_count": len(inputs),
        "inputs": inputs,
        "source_refs": refs,
        "warnings": [
            "Jin10 category/274 positioning report is supplemental single-source evidence; official facts must be confirmed."
        ],
    }


def archive_jin10_positioning_report_inputs(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    extraction: dict[str, Any],
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "positioning.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(extraction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def _extract_from_report_text(
    text: str,
    *,
    refs: list[dict[str, Any]],
    default_asset: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment in _text_segments(text):
        direction = _direction(segment)
        position_change = _position_change(segment)
        level = _level(segment)
        if not direction or not position_change or not level:
            continue
        rows.append(
            _input_row(
                asset=_asset_or_default(_infer_asset(segment), default_asset),
                direction=direction,
                strike_or_level=level,
                position_change=position_change,
                source_refs=refs,
                evidence_text=_evidence_text(segment),
            )
        )
    return rows


def _extract_from_markdown_table(text: str, *, refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4 or _is_markdown_header_or_rule(cells):
            continue
        asset, level, direction_text, change_text = cells[:4]
        direction = _direction(direction_text)
        position_change = _position_change(change_text)
        if not direction or not position_change or not _level(level):
            continue
        rows.append(
            _input_row(
                asset=_asset_from_text(asset),
                direction=direction,
                strike_or_level=_level(level),
                position_change=position_change,
                source_refs=refs,
                evidence_text=" | ".join(cells[:4]),
            )
        )
    return rows


def _input_row(
    *,
    asset: str,
    direction: str,
    strike_or_level: str,
    position_change: str,
    source_refs: list[dict[str, Any]],
    evidence_text: str,
) -> dict[str, Any]:
    return {
        "asset": asset,
        "direction": direction,
        "strike_or_level": strike_or_level,
        "position_change": position_change,
        "confidence": DEFAULT_CONFIDENCE,
        "source_refs": copy.deepcopy(source_refs),
        "verification_status": VERIFICATION_STATUS,
        "provider_role": PROVIDER_ROLE,
        "evidence_text": evidence_text,
    }


def _text_segments(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    raw_segments = re.split(r"[。；;，]|,(?!\d)", normalized)
    segments: list[str] = []
    for raw in raw_segments:
        cleaned = raw.strip(" ，,")
        if cleaned:
            segments.append(cleaned)
    return segments


def _evidence_text(segment: str) -> str:
    cleaned = segment.strip(" ，,。；;")
    for token in _ASSET_ALIASES:
        index = cleaned.find(token)
        if index > 0:
            return cleaned[index:]
    return cleaned


def _direction(text: str) -> str | None:
    lower = text.lower()
    if any(token in text for token in ("看涨", "多头", "认购")) or "call" in lower:
        return "bullish"
    if any(token in text for token in ("看跌", "空头", "认沽")) or "put" in lower:
        return "bearish"
    return None


def _position_change(text: str) -> str | None:
    if any(token in text for token in ("新增", "增加", "增持", "增仓", "净增")):
        return "increase"
    if any(token in text for token in ("减少", "减持", "减仓", "下降", "净减")):
        return "decrease"
    return None


def _level(text: str) -> str | None:
    match = _LEVEL_RE.search(text)
    return match.group(1) if match else None


def _infer_asset(text: str) -> str:
    return _asset_from_text(text) if text else "unknown"


def _asset_from_text(text: str) -> str:
    for token, asset in _ASSET_ALIASES.items():
        if token in text:
            return asset
    return "unknown"


def _asset_or_default(asset: str, default_asset: str) -> str:
    return asset if asset != "unknown" else default_asset


def _source_refs(source_refs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    refs = copy.deepcopy(source_refs or [])
    return refs or [{"source_key": "jin10_category_274", "provider_role": PROVIDER_ROLE}]


def _is_markdown_header_or_rule(cells: list[str]) -> bool:
    joined = "".join(cells)
    return "标的" in joined or set(joined.replace(" ", "")) <= {"-"}


def _dedupe_inputs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = (
            str(row.get("asset")),
            str(row.get("direction")),
            str(row.get("strike_or_level")),
            str(row.get("position_change")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped
