"""Cross-metal ETF holdings feature built from parsed Jin10 reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle


def build_etf_holdings_context(reports: list[dict[str, Any]]) -> dict[str, Any]:
    by_asset = {
        str(report.get("asset")): report
        for report in reports
        if isinstance(report, dict) and report.get("status") == "ok"
    }
    gold = _latest(by_asset.get("gold"))
    silver = _latest(by_asset.get("silver"))
    if not gold and not silver:
        return {}

    source_refs: list[dict[str, Any]] = []
    for report in by_asset.values():
        source_refs.extend(dict(ref) for ref in report.get("source_refs") or [] if isinstance(ref, dict))
    gold_change = gold.get("change_tonnes") if gold else None
    silver_change = silver.get("change_tonnes") if silver else None
    missing_data: list[str] = []
    if not gold:
        missing_data.append("gold_etf_holdings")
    if not silver:
        missing_data.append("silver_etf_holdings")
    return {
        "source_key": "jin10_minipro_etf_reports",
        "source_kind": "etf_holdings",
        "as_of": max(
            (str(row.get("reported_on")) for row in (gold, silver) if row and row.get("reported_on")),
            default=None,
        ),
        "global_etf_flow": gold_change,
        "north_america_etf_flow": None,
        "asia_etf_flow": None,
        "gold_etf_fund_name": by_asset.get("gold", {}).get("fund_name"),
        "gold_etf_holdings_tonnes": gold.get("holdings_tonnes") if gold else None,
        "gold_etf_change_tonnes": gold_change,
        "gold_etf_value_usd": gold.get("value_usd") if gold else None,
        "gold_etf_reported_on": gold.get("reported_on") if gold else None,
        "silver_etf_fund_name": by_asset.get("silver", {}).get("fund_name"),
        "silver_etf_holdings_tonnes": silver.get("holdings_tonnes") if silver else None,
        "silver_etf_change_tonnes": silver_change,
        "silver_etf_value_usd": silver.get("value_usd") if silver else None,
        "silver_etf_reported_on": silver.get("reported_on") if silver else None,
        "cross_metal_confirmation": _cross_metal_confirmation(gold_change, silver_change),
        "provider_role": "supplemental_source",
        "verification_status": "single_source",
        "source_tier": "supplemental",
        "missing_data": missing_data,
        "source_refs": _dedupe_refs(source_refs),
    }


def archive_etf_holdings_context(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    context: dict[str, Any],
) -> str:
    rel_path = Path("features") / "market" / retrieved_date / run_id / "etf_holdings.json"
    payload = dict(context)
    payload["artifact_path"] = rel_path.as_posix()
    write_immutable_artifact_bundle(
        [immutable_json_item(storage_root / rel_path, payload)],
        storage_root=storage_root,
    )
    context.clear()
    context.update(payload)
    return rel_path.as_posix()


def _latest(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    rows = [row for row in report.get("rows") or [] if isinstance(row, dict)]
    return max(rows, key=lambda row: str(row.get("reported_on") or ""), default={})


def _cross_metal_confirmation(gold: Any, silver: Any) -> str:
    if gold is None or silver is None:
        return "unavailable"
    if gold > 0 and silver > 0:
        return "confirmed_inflow"
    if gold < 0 and silver < 0:
        return "confirmed_outflow"
    if gold == 0 and silver == 0:
        return "flat"
    return "divergent"


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for ref in refs:
        key = tuple(sorted((str(k), str(v)) for k, v in ref.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result
