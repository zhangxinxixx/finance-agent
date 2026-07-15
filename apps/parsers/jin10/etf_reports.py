"""Normalize Jin10 Mini Program ETF report responses."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from apps.collectors.news.base import archive_news_payload


@dataclass(frozen=True)
class Jin10EtfReport:
    asset: str
    attr_id: int
    fund_name: str
    as_of: str | None
    rows: list[dict[str, Any]]
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    status: str = "ok"
    freshness_status: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_jin10_etf_report(
    envelope: dict[str, Any],
    *,
    raw_path: str,
    reference_date: str,
) -> Jin10EtfReport:
    asset = str(envelope.get("asset") or "unknown")
    attr_id = int(envelope.get("attr_id") or 0)
    fund_name = str(envelope.get("fund_name") or "")
    payload = envelope.get("payload")
    raw_rows = payload.get("data") if isinstance(payload, dict) else None
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    if isinstance(raw_rows, list):
        for item in raw_rows:
            normalized = _normalize_row(item)
            if normalized is not None:
                rows.append(normalized)
    rows.sort(key=lambda item: item["reported_on"], reverse=True)
    if not rows:
        warnings.append("no_valid_etf_report_rows")
    as_of = rows[0]["reported_on"] if rows else None
    freshness_status = _freshness(as_of=as_of, reference_date=reference_date)
    source_refs = [
        {
            "source": "jin10_minipro",
            "source_key": "jin10_minipro_etf_reports",
            "source_url": "https://mp-api.jin10.com/api/etf-reports",
            "asset": asset,
            "attr_id": attr_id,
            "fund_name": fund_name,
            "raw_path": raw_path,
            "provider_role": "supplemental_source",
            "source_tier": "supplemental",
            "verification_status": "single_source",
            "status": "ok" if rows else "unavailable",
        }
    ]
    return Jin10EtfReport(
        asset=asset,
        attr_id=attr_id,
        fund_name=fund_name,
        as_of=as_of,
        rows=rows,
        source_refs=source_refs,
        status="ok" if rows else "unavailable",
        freshness_status=freshness_status,
        warnings=warnings,
    )


def archive_parsed_etf_report(
    *,
    storage_root: Path,
    retrieved_date: str,
    report: Jin10EtfReport,
) -> str:
    return archive_news_payload(
        storage_root=storage_root,
        layer="parsed",
        source_key="jin10_minipro_etf_reports",
        retrieved_date=retrieved_date,
        name=report.asset,
        payload=report.to_dict(),
    )


def _normalize_row(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    reported_on = str(value.get("reported_on") or "").strip()
    trust = _number(value.get("trust"))
    change = _number(value.get("change"))
    total_value = _number(value.get("value"))
    if not reported_on or trust is None or change is None:
        return None
    return {
        "reported_on": reported_on,
        "updated_at": str(value.get("updated_at") or "") or None,
        "holdings_tonnes": trust,
        "change_tonnes": change,
        "value_usd": total_value,
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _freshness(*, as_of: str | None, reference_date: str) -> str:
    if not as_of:
        return "missing"
    try:
        age_days = (date.fromisoformat(reference_date) - date.fromisoformat(as_of)).days
    except ValueError:
        return "invalid"
    return "fresh" if age_days <= 7 else "stale"
