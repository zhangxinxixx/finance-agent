"""Deterministic validation of Jin10 positioning rows against CME OI changes."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


_ASSET_BY_HEADING = {
    "黄金持仓报告": "XAUUSD",
    "白银持仓报告": "XAGUSD",
}
_ROW_RE = re.compile(
    r"(?P<strike>\d+(?:\.\d+)?)\s*看涨期权\s*(?P<call>[+\-−]?\d[\d,]*)\s*手\s*[,，、]?\s*"
    r"看跌期权\s*(?P<put>[+\-−]?\d[\d,]*)\s*手"
)
_EXPIRY_RE = re.compile(r"对应\s*(?P<expiry>[A-Z]{3}\d{2})\s*期货价格")


def extract_positioning_oi_changes(markdown_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current_asset = ""
    for page in sorted(markdown_pages, key=lambda item: int(item.get("page_no") or 0)):
        markdown = str(page.get("markdown") or "")
        for heading, asset in _ASSET_BY_HEADING.items():
            if heading in markdown:
                current_asset = asset
                break
        expiry_match = _EXPIRY_RE.search(markdown)
        if not current_asset or expiry_match is None:
            continue
        expiry = expiry_match.group("expiry")
        for match in _ROW_RE.finditer(markdown):
            rows.append(
                {
                    "asset": current_asset,
                    "expiry": expiry,
                    "strike": float(match.group("strike")),
                    "call_oi_change": _signed_int(match.group("call")),
                    "put_oi_change": _signed_int(match.group("put")),
                    "page_no": int(page.get("page_no") or 0),
                    "evidence_text": match.group(0),
                }
            )
    return rows


def validate_positioning_against_cme(
    *,
    article_id: str,
    report_date: str,
    report_rows: list[dict[str, Any]],
    cme_payload: dict[str, Any],
    report_source_ref: dict[str, Any],
    cme_source_ref: dict[str, Any],
) -> dict[str, Any]:
    detail_rows = [row for row in cme_payload.get("detail_rows") or [] if isinstance(row, dict)]
    cme_index = {
        (
            str(row.get("expiry") or ""),
            float(row.get("strike") or 0),
            str(row.get("option_type") or "").upper(),
        ): int(row.get("oi_change") or 0)
        for row in detail_rows
        if str(row.get("product") or "") == "OG"
    }
    comparisons: list[dict[str, Any]] = []
    for report_row in report_rows:
        if report_row.get("asset") != "XAUUSD":
            continue
        expiry = str(report_row.get("expiry") or "")
        strike = float(report_row.get("strike") or 0)
        for option_type, report_key in (("CALL", "call_oi_change"), ("PUT", "put_oi_change")):
            reported = int(report_row.get(report_key) or 0)
            cme_value = cme_index.get((expiry, strike, option_type))
            comparisons.append(
                {
                    "asset": "XAUUSD",
                    "product": "OG",
                    "expiry": expiry,
                    "strike": strike,
                    "option_type": option_type,
                    "jin10_oi_change": reported,
                    "cme_oi_change": cme_value,
                    "match": cme_value == reported if cme_value is not None else False,
                    "difference": None if cme_value is None else reported - cme_value,
                    "page_no": report_row.get("page_no"),
                    "evidence_text": report_row.get("evidence_text"),
                }
            )
    matched = sum(1 for item in comparisons if item["match"])
    missing = sum(1 for item in comparisons if item["cme_oi_change"] is None)
    mismatched = len(comparisons) - matched - missing
    status = (
        "confirmed"
        if comparisons and matched == len(comparisons)
        else "mismatch"
        if mismatched
        else "partial"
    )
    return {
        "schema_version": "1.0",
        "artifact_type": "jin10_positioning_cme_validation",
        "article_id": article_id,
        "report_date": report_date,
        "cme_trade_date": cme_payload.get("trade_date"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validation_status": status,
        "summary": {
            "comparison_count": len(comparisons),
            "matched_count": matched,
            "mismatched_count": mismatched,
            "missing_count": missing,
            "match_rate": matched / len(comparisons) if comparisons else 0.0,
        },
        "comparisons": comparisons,
        "source_refs": [report_source_ref, cme_source_ref],
        "interpretation_policy": {
            "jin10_role": "secondary_interpretation",
            "cme_role": "official_market_source",
            "confirmed_rows_may_support": True,
            "mismatched_rows_require_review": True,
            "validation_does_not_confirm_directional_opinion": True,
        },
    }


def _signed_int(value: str) -> int:
    return int(value.replace(",", "").replace("−", "-"))
