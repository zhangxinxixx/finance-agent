from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from apps.analysis.agents.source_health import build_gold_v3_source_health
from apps.analysis.gold_mainline_engine import build_gold_macro_overview
from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.source_service import get_data_source_statuses

logger = logging.getLogger(__name__)

_OVERVIEW_FILENAME = "gold_macro_overview.json"
_MAINLINES_FILENAME = "gold_event_mainlines.json"


def get_gold_mainlines_latest(*, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    base = root / "storage" / "analysis" / "gold_mainlines"
    if base.exists():
        for date_dir in sorted((path for path in base.iterdir() if path.is_dir()), reverse=True):
            for run_dir in sorted((path for path in date_dir.iterdir() if path.is_dir()), reverse=True):
                overview_path = run_dir / _OVERVIEW_FILENAME
                if overview_path.exists():
                    return _load_gold_mainlines(
                        date=date_dir.name,
                        run_id=run_dir.name,
                        overview_path=overview_path,
                        project_root=root,
                    )
    inferred = _load_latest_inferred_gold_mainlines(project_root=root)
    if inferred is not None:
        return inferred
    return _unavailable_payload(date=None, run_id=None, warnings=["gold_macro_overview artifact unavailable"])


def get_gold_mainlines(*, date: str, run_id: str, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _PROJECT_ROOT
    overview_path = root / "storage" / "analysis" / "gold_mainlines" / date / run_id / _OVERVIEW_FILENAME
    if not overview_path.exists():
        inferred = _load_inferred_gold_mainlines(date=date, run_id=run_id, project_root=root)
        if inferred is not None:
            return inferred
        return _unavailable_payload(date=date, run_id=run_id, warnings=["gold_macro_overview artifact unavailable"])
    return _load_gold_mainlines(date=date, run_id=run_id, overview_path=overview_path, project_root=root)


def _load_gold_mainlines(*, date: str, run_id: str, overview_path: Path, project_root: Path) -> dict[str, Any]:
    overview = _load_json_dict(overview_path)
    if overview is None:
        return _unavailable_payload(date=date, run_id=run_id, warnings=["gold_macro_overview artifact unreadable"])
    mainlines = _load_linked_event_mainlines(overview=overview, project_root=project_root)
    _normalize_gold_mainline_contract(overview=overview, mainlines=mainlines)
    _normalize_gold_requirement_contract(overview=overview, mainlines=mainlines, project_root=project_root)
    warnings = [str(item) for item in overview.get("warnings") or []]
    warnings.extend(_apply_source_health_gate(overview=overview))
    if mainlines["status"] == "unavailable":
        warnings.append("gold_event_mainlines artifact unavailable")
    return {
        "status": str(overview.get("status") or "partial"),
        "date": str(overview.get("retrieved_date") or date),
        "run_id": str(overview.get("run_id") or run_id),
        "artifact_path": overview_path.relative_to(project_root).as_posix(),
        "schema_version": overview.get("schema_version"),
        "input_snapshot_ids": dict(overview.get("input_snapshot_ids") or {}),
        "gold_macro_overview": overview,
        "gold_mainlines": mainlines,
        "source_refs": _source_refs(overview, mainlines),
        "warnings": warnings,
    }


def _load_linked_event_mainlines(*, overview: dict[str, Any], project_root: Path) -> dict[str, Any]:
    input_snapshot_ids = overview.get("input_snapshot_ids")
    linked_path = None
    if isinstance(input_snapshot_ids, dict):
        linked_path = input_snapshot_ids.get("gold_event_mainlines")
    if isinstance(linked_path, str) and linked_path.strip():
        path = _resolve_storage_relative_path(project_root=project_root, value=linked_path)
        if path is not None and path.exists():
            return _load_event_mainlines(path=path, project_root=project_root)
    return _unavailable_mainlines()


def _load_latest_inferred_gold_mainlines(*, project_root: Path) -> dict[str, Any] | None:
    base = project_root / "storage" / "features" / "news"
    if not base.exists():
        return None
    for date_dir in sorted((path for path in base.iterdir() if path.is_dir()), reverse=True):
        for run_dir in sorted((path for path in date_dir.iterdir() if path.is_dir()), reverse=True):
            event_path = run_dir / _MAINLINES_FILENAME
            if event_path.exists():
                return _load_inferred_gold_mainlines(
                    date=date_dir.name,
                    run_id=run_dir.name,
                    project_root=project_root,
                )
    return None


def _load_inferred_gold_mainlines(*, date: str, run_id: str, project_root: Path) -> dict[str, Any] | None:
    event_path = project_root / "storage" / "features" / "news" / date / run_id / _MAINLINES_FILENAME
    if not event_path.exists():
        return None
    mainlines = _load_event_mainlines(path=event_path, project_root=project_root)
    if mainlines["status"] == "unavailable":
        return None
    event_ref = event_path.relative_to(project_root / "storage").as_posix()
    seed_overview = {
        "retrieved_date": date,
        "run_id": run_id,
        "as_of": mainlines.get("as_of"),
        "input_snapshot_ids": {"gold_event_mainlines": event_ref},
    }
    overview = build_gold_macro_overview(
        mainlines,
        macro_context=_latest_macro_context_for_overview(overview=seed_overview, project_root=project_root),
        market_context=_latest_market_context_for_overview(overview=seed_overview, project_root=project_root),
        oil_context=_latest_oil_context_for_overview(overview=seed_overview, project_root=project_root),
        flow_context=_latest_flow_context_for_overview(overview=seed_overview, project_root=project_root),
        reserve_context=_latest_reserve_context_for_overview(overview=seed_overview, project_root=project_root),
        asia_context=_latest_asia_context_for_overview(overview=seed_overview, project_root=project_root),
        positioning_context=_latest_positioning_context_for_overview(overview=seed_overview, project_root=project_root),
        policy_context=_latest_policy_context_for_overview(overview=seed_overview, project_root=project_root),
        geopolitical_context=_latest_geopolitical_context_for_overview(overview=seed_overview, project_root=project_root),
    ).to_dict()
    overview["retrieved_date"] = str(overview.get("retrieved_date") or date)
    overview["run_id"] = str(overview.get("run_id") or run_id)
    overview["input_snapshot_ids"] = {"gold_event_mainlines": event_ref}
    _normalize_gold_mainline_contract(overview=overview, mainlines=mainlines)
    _normalize_gold_requirement_contract(overview=overview, mainlines=mainlines, project_root=project_root)
    warnings = [str(item) for item in overview.get("warnings") or []]
    warnings.extend(_apply_source_health_gate(overview=overview))
    warnings.append("gold_macro_overview inferred from gold_event_mainlines artifact")
    return {
        "status": str(overview.get("status") or "partial"),
        "date": str(overview.get("retrieved_date") or date),
        "run_id": str(overview.get("run_id") or run_id),
        "artifact_path": None,
        "schema_version": overview.get("schema_version"),
        "input_snapshot_ids": dict(overview.get("input_snapshot_ids") or {}),
        "gold_macro_overview": overview,
        "gold_mainlines": mainlines,
        "source_refs": _source_refs(overview, mainlines),
        "warnings": warnings,
    }


def _load_event_mainlines(*, path: Path, project_root: Path) -> dict[str, Any]:
    payload = _load_json_dict(path)
    if payload is None:
        return _unavailable_mainlines()
    payload = dict(payload)
    payload["artifact_path"] = path.relative_to(project_root).as_posix()
    payload["status"] = str(payload.get("status") or "partial")
    return payload


_VERIFICATION_SOURCE_MAP: dict[str, str] = {
    "multi_source_confirmation_needed": "news_sources",
    "oil_price_reaction_needed": "oil_price",
    "real_rate_response_needed": "real_rates",
    "flow_data_confirmation_needed": "etf_comex_flows",
    "price_level_confirmation_needed": "xauusd_price",
    "official_release_needed": "official_data",
    "official_reserve_data_needed": "central_bank_reserves",
    "positioning_confirmation_needed": "positioning_data",
    "macro_data_confirmation_needed": "macro_data",
    "fx_market_confirmation_needed": "fx_market",
}


def _normalize_gold_mainline_contract(*, overview: dict[str, Any], mainlines: dict[str, Any]) -> None:
    event_links = [dict(item) for item in mainlines.get("event_links") or [] if isinstance(item, dict)]
    mainline_rows = [item for item in mainlines.get("mainlines") or [] if isinstance(item, dict)]
    overview_rows = [item for item in overview.get("theme_rankings") or [] if isinstance(item, dict)]
    overview_refs = [dict(ref) for ref in overview.get("source_refs") or [] if isinstance(ref, dict)]

    for row in mainline_rows:
        _fill_ranking_contract(row, event_links=event_links, fallback_refs=overview_refs)

    for row in overview_rows:
        mainline_id = _ranking_mainline_id(row)
        matching_mainline = next((item for item in mainline_rows if _ranking_mainline_id(item) == mainline_id), None)
        fallback_refs = _merge_source_refs(
            [
                overview_refs,
                matching_mainline.get("source_refs") if matching_mainline else [],
            ]
        )
        fallback_event_ids = []
        if matching_mainline:
            fallback_event_ids.extend(_string_list(matching_mainline.get("related_event_ids") or matching_mainline.get("event_ids")))
        fallback_event_ids.extend(_string_list(overview.get("key_events")))
        _fill_ranking_contract(
            row,
            event_links=event_links,
            fallback_refs=fallback_refs,
            fallback_event_ids=fallback_event_ids,
        )


def _normalize_gold_requirement_contract(*, overview: dict[str, Any], mainlines: dict[str, Any], project_root: Path) -> None:
    if (
        overview.get("mainline_requirements")
        and overview.get("analysis_readiness")
        and overview.get("architecture_gaps") is not None
        and _has_context_feature_fields_for(overview, "real_rates_usd")
        and _has_context_feature_fields_for(overview, "oil_prices")
        and _has_context_feature_fields_for(overview, "etf_flows")
        and _has_context_feature_fields_for(overview, "central_bank_gold")
        and _has_context_feature_fields_for(overview, "china_asia_demand")
        and _has_context_feature_fields_for(overview, "institutional_sentiment")
        and _has_context_feature_fields_for(overview, "fed_policy_path")
        and _has_context_feature_fields_for(overview, "geopolitical_war_risk")
        and _has_context_feature_fields_for(overview, "gold_technical_levels")
    ):
        return
    source_payload: dict[str, Any] = mainlines if mainlines.get("status") != "unavailable" else overview
    macro_context = _latest_macro_context_for_overview(overview=overview, project_root=project_root)
    market_context = _latest_market_context_for_overview(overview=overview, project_root=project_root)
    oil_context = _latest_oil_context_for_overview(overview=overview, project_root=project_root)
    flow_context = _latest_flow_context_for_overview(overview=overview, project_root=project_root)
    reserve_context = _latest_reserve_context_for_overview(overview=overview, project_root=project_root)
    asia_context = _latest_asia_context_for_overview(overview=overview, project_root=project_root)
    positioning_context = _latest_positioning_context_for_overview(overview=overview, project_root=project_root)
    policy_context = _latest_policy_context_for_overview(overview=overview, project_root=project_root)
    geopolitical_context = _latest_geopolitical_context_for_overview(overview=overview, project_root=project_root)
    inferred = build_gold_macro_overview(
        source_payload,
        macro_context=macro_context,
        market_context=market_context,
        oil_context=oil_context,
        flow_context=flow_context,
        reserve_context=reserve_context,
        asia_context=asia_context,
        positioning_context=positioning_context,
        policy_context=policy_context,
        geopolitical_context=geopolitical_context,
    ).to_dict()
    inferred_has_context = _has_context_feature_fields(inferred)
    needs_context_update = not (
        _has_context_feature_fields_for(overview, "real_rates_usd")
        and _has_context_feature_fields_for(overview, "oil_prices")
        and _has_context_feature_fields_for(overview, "etf_flows")
        and _has_context_feature_fields_for(overview, "central_bank_gold")
        and _has_context_feature_fields_for(overview, "china_asia_demand")
        and _has_context_feature_fields_for(overview, "institutional_sentiment")
        and _has_context_feature_fields_for(overview, "fed_policy_path")
        and _has_context_feature_fields_for(overview, "geopolitical_war_risk")
        and _has_context_feature_fields_for(overview, "gold_technical_levels")
    )
    if needs_context_update and inferred_has_context:
        _merge_inferred_context_contract(overview=overview, inferred=inferred)
    else:
        overview.setdefault("mainline_requirements", inferred.get("mainline_requirements") or [])
        overview.setdefault("analysis_readiness", inferred.get("analysis_readiness") or {})
        overview.setdefault("architecture_gaps", inferred.get("architecture_gaps") or [])


def _merge_inferred_context_contract(*, overview: dict[str, Any], inferred: dict[str, Any]) -> None:
    inferred_rows = {
        _ranking_mainline_id(row): row
        for row in inferred.get("theme_rankings") or []
        if isinstance(row, dict) and isinstance(row.get("feature_fields"), dict) and row.get("feature_fields")
    }
    overview_rows = [dict(row) for row in overview.get("theme_rankings") or [] if isinstance(row, dict)]
    seen: set[str] = set()
    for row in overview_rows:
        mainline_id = _ranking_mainline_id(row)
        inferred_row = inferred_rows.get(mainline_id)
        if inferred_row:
            _merge_context_row(row=row, inferred_row=inferred_row)
            seen.add(mainline_id)
    for mainline_id, inferred_row in inferred_rows.items():
        if mainline_id not in seen:
            overview_rows.append(dict(inferred_row))
    overview["theme_rankings"] = overview_rows
    if inferred.get("war_oil_rate_chain") is not None:
        overview["war_oil_rate_chain"] = inferred.get("war_oil_rate_chain")
    overview["verification_matrix"] = inferred.get("verification_matrix") or overview.get("verification_matrix") or []
    overview["mainline_requirements"] = inferred.get("mainline_requirements") or []
    overview["analysis_readiness"] = inferred.get("analysis_readiness") or {}
    overview["architecture_gaps"] = inferred.get("architecture_gaps") or []


def _merge_context_row(*, row: dict[str, Any], inferred_row: dict[str, Any]) -> None:
    for key in (
        "coverage_status",
        "direction",
        "direction_score",
        "freshness",
        "verification_status",
        "summary",
        "missing_data",
        "feature_fields",
        "source_refs",
        "evidence_count",
    ):
        if key in inferred_row:
            row[key] = inferred_row[key]
    row.setdefault("mainline_id", _ranking_mainline_id(row))
    row.setdefault("mainline", _ranking_mainline_id(row))


def _apply_source_health_gate(*, overview: dict[str, Any]) -> list[str]:
    try:
        snapshot = build_gold_v3_source_health(
            get_data_source_statuses(),
            as_of=str(overview.get("as_of") or "") or None,
            gold_macro_overview=overview,
        )
    except Exception as exc:
        overview["source_health"] = {
            "overall_status": "degraded",
            "as_of": str(overview.get("as_of") or "") or None,
            "p0_missing": [],
            "p1_missing": [],
            "p2_missing": [],
            "stale_sources": [],
            "fresh_sources": [],
            "source_freshness": {},
            "mainline_impact": {},
            "can_build_gold_macro_overview": True,
            "blocking_reasons": [],
            "warnings": [f"source_health_unavailable: {exc.__class__.__name__}"],
        }
        return ["source_health unavailable for GoldMacroOverview gate"]

    source_health = snapshot.to_dict()
    overview["source_health"] = source_health
    blocking_reasons = [str(item) for item in source_health.get("blocking_reasons") or []]
    strong_conflict = any("strong GoldMacroOverview conclusion" in reason for reason in blocking_reasons)
    if not strong_conflict:
        return []

    overview["status"] = "blocked"
    overview["review_status"] = "blocked"
    overview["review_blocking_reasons"] = blocking_reasons
    return ["source_health blocked strong GoldMacroOverview conclusion"]


def _has_context_feature_fields(overview: dict[str, Any]) -> bool:
    for row in overview.get("theme_rankings") or []:
        if not isinstance(row, dict):
            continue
        mainline_id = _ranking_mainline_id(row)
        fields = row.get("feature_fields")
        if mainline_id in {"fed_policy_path", "real_rates_usd", "oil_prices", "geopolitical_war_risk", "etf_flows", "central_bank_gold", "china_asia_demand", "institutional_sentiment", "gold_technical_levels"} and isinstance(fields, dict) and fields:
            return True
    return False


def _has_context_feature_fields_for(overview: dict[str, Any], mainline_id: str) -> bool:
    for row in overview.get("theme_rankings") or []:
        if not isinstance(row, dict):
            continue
        fields = row.get("feature_fields")
        if _ranking_mainline_id(row) == mainline_id and isinstance(fields, dict) and fields:
            return True
    return False


def _latest_macro_context_for_overview(*, overview: dict[str, Any], project_root: Path) -> dict[str, Any]:
    payload = _load_context_artifact_for_overview(
        overview=overview,
        project_root=project_root,
        snapshot_key="macro_snapshot",
        artifact_types={"macro_snapshot"},
    )
    if payload is not None:
        return payload
    date = str(overview.get("retrieved_date") or overview.get("as_of") or "")[:10]
    base = project_root / "storage" / "features" / "macro"
    date_dirs = [base / date] if date else []
    if base.exists():
        date_dirs.extend(path for path in sorted((item for item in base.iterdir() if item.is_dir()), reverse=True) if path not in date_dirs)
    for date_dir in date_dirs:
        if not date_dir.exists():
            continue
        for run_dir in sorted((item for item in date_dir.iterdir() if item.is_dir()), reverse=True):
            payload = _load_json_dict(run_dir / "macro_snapshot.json")
            if payload is not None:
                return payload
    return {}


def _latest_market_context_for_overview(*, overview: dict[str, Any], project_root: Path) -> dict[str, Any]:
    payload = _load_context_artifact_for_overview(
        overview=overview,
        project_root=project_root,
        snapshot_key="market_context",
        artifact_types={"market_context"},
    )
    if payload is not None:
        return payload
    try:
        return _get_market_monitor_overview()
    except Exception as exc:
        logger.debug(
            "Market monitor context unavailable for gold mainline technical levels",
            exc_info=exc,
            extra={"service": "gold_mainline_service", "stage": "market_context"},
        )
    return {}


def _latest_oil_context_for_overview(*, overview: dict[str, Any], project_root: Path) -> dict[str, Any]:
    return _load_context_artifact_for_overview(
        overview=overview,
        project_root=project_root,
        snapshot_key="oil_context",
        artifact_types={"oil_context"},
    ) or {}


def _latest_flow_context_for_overview(*, overview: dict[str, Any], project_root: Path) -> dict[str, Any]:
    return _load_context_artifact_for_overview(
        overview=overview,
        project_root=project_root,
        snapshot_key="flow_context",
        artifact_types={"flow_context"},
    ) or {}


def _latest_reserve_context_for_overview(*, overview: dict[str, Any], project_root: Path) -> dict[str, Any]:
    return _load_context_artifact_for_overview(
        overview=overview,
        project_root=project_root,
        snapshot_key="reserve_context",
        artifact_types={"reserve_context"},
    ) or {}


def _latest_asia_context_for_overview(*, overview: dict[str, Any], project_root: Path) -> dict[str, Any]:
    return _load_context_artifact_for_overview(
        overview=overview,
        project_root=project_root,
        snapshot_key="asia_context",
        artifact_types={"asia_context"},
    ) or {}


def _latest_positioning_context_for_overview(*, overview: dict[str, Any], project_root: Path) -> dict[str, Any]:
    return _load_context_artifact_for_overview(
        overview=overview,
        project_root=project_root,
        snapshot_key="positioning_context",
        artifact_types={"positioning_context"},
    ) or {}


def _latest_policy_context_for_overview(*, overview: dict[str, Any], project_root: Path) -> dict[str, Any]:
    return _load_context_artifact_for_overview(
        overview=overview,
        project_root=project_root,
        snapshot_key="policy_context",
        artifact_types={"policy_context"},
    ) or {}


def _latest_geopolitical_context_for_overview(*, overview: dict[str, Any], project_root: Path) -> dict[str, Any]:
    return _load_context_artifact_for_overview(
        overview=overview,
        project_root=project_root,
        snapshot_key="geopolitical_context",
        artifact_types={"geopolitical_context"},
    ) or {}


def _load_context_artifact_for_overview(
    *,
    overview: dict[str, Any],
    project_root: Path,
    snapshot_key: str,
    artifact_types: set[str],
) -> dict[str, Any] | None:
    input_snapshot_ids = overview.get("input_snapshot_ids")
    if isinstance(input_snapshot_ids, dict):
        payload = _load_context_path(project_root=project_root, value=input_snapshot_ids.get(snapshot_key))
        if payload is not None:
            return payload

    accepted_types = {snapshot_key, *artifact_types}
    for ref in overview.get("artifact_refs") or []:
        if not isinstance(ref, dict):
            continue
        artifact_type = str(ref.get("artifact_type") or ref.get("type") or "").strip()
        if artifact_type not in accepted_types:
            continue
        payload = _load_context_path(
            project_root=project_root,
            value=ref.get("path") or ref.get("artifact_path"),
        )
        if payload is not None:
            return payload
    return None


def _load_context_path(*, project_root: Path, value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    resolved = _resolve_storage_relative_path(project_root=project_root, value=value)
    return _load_json_dict(resolved) if resolved and resolved.exists() else None


def _get_market_monitor_overview() -> dict[str, Any]:
    from apps.api.services.market_service import get_market_monitor_overview

    payload = get_market_monitor_overview()
    return payload if isinstance(payload, dict) else {}


def _fill_ranking_contract(
    row: dict[str, Any],
    *,
    event_links: list[dict[str, Any]],
    fallback_refs: list[dict[str, Any]],
    fallback_event_ids: list[str] | None = None,
) -> None:
    mainline_id = _ranking_mainline_id(row)
    if not mainline_id:
        return

    matching_links = [
        link
        for link in event_links
        if mainline_id in _string_list(link.get("mainline_ids")) or link.get("primary_mainline") == mainline_id
    ]
    event_ids = _unique_strings(
        [
            *_string_list(row.get("related_event_ids")),
            *_string_list(row.get("event_ids")),
            *(str(link.get("event_id") or "") for link in matching_links),
            *(fallback_event_ids or []),
        ]
    )
    source_refs = _merge_source_refs(
        [
            row.get("source_refs") or [],
            *(link.get("source_refs") or [] for link in matching_links),
            fallback_refs,
        ]
    )
    verification_needed = _unique_strings(
        [
            *(_string_list(row.get("verification_needed"))),
            *(item for link in matching_links for item in _string_list(link.get("verification_needed"))),
        ]
    )
    missing_data = _missing_data(verification_needed=verification_needed, source_refs=source_refs, existing=row.get("missing_data"))

    row.setdefault("mainline_id", mainline_id)
    row.setdefault("mainline", mainline_id)
    row.setdefault("source_refs", source_refs)
    row.setdefault("related_event_ids", event_ids)
    row.setdefault("evidence_count", len(source_refs))
    row.setdefault("missing_data", missing_data)
    row.setdefault("freshness", _freshness(missing_data=missing_data, source_refs=source_refs))
    row.setdefault(
        "impact_strength",
        _impact_strength(score=row.get("score"), rank=row.get("rank"), direction=str(row.get("direction") or "unknown")),
    )


def _ranking_mainline_id(row: dict[str, Any]) -> str:
    return str(row.get("mainline_id") or row.get("mainline") or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _merge_source_refs(ref_groups: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for group in ref_groups:
        if isinstance(group, dict):
            candidates = [group]
        elif isinstance(group, list):
            candidates = group
        else:
            continue
        refs.extend(dict(ref) for ref in candidates if isinstance(ref, dict))

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for ref in refs:
        key = json.dumps(ref, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique


def _missing_data(*, verification_needed: list[str], source_refs: list[dict[str, Any]], existing: Any = None) -> list[str]:
    if isinstance(existing, list):
        return _unique_strings([str(item) for item in existing if str(item or "").strip()])
    missing = _unique_strings([_VERIFICATION_SOURCE_MAP.get(item, item) for item in verification_needed])
    if not source_refs:
        missing.append("source_refs")
    return _unique_strings(missing)


def _freshness(*, missing_data: list[str], source_refs: list[dict[str, Any]]) -> str:
    if not source_refs:
        return "stale"
    if missing_data:
        return "partial"
    return "fresh"


def _impact_strength(*, score: Any, rank: Any, direction: str) -> str:
    try:
        numeric_score = float(score or 0.0)
    except (TypeError, ValueError):
        numeric_score = 0.0
    try:
        numeric_rank = int(rank or 0)
    except (TypeError, ValueError):
        numeric_rank = 0
    if numeric_score >= 18 or numeric_rank == 1:
        return "high" if direction != "mixed" else "medium"
    if numeric_score >= 8 or 0 < numeric_rank <= 3:
        return "medium"
    return "low"


def _resolve_storage_relative_path(*, project_root: Path, value: str) -> Path | None:
    normalized = value.strip().lstrip("/")
    if not normalized:
        return None
    if normalized.startswith("storage/"):
        return project_root / normalized
    return project_root / "storage" / normalized


def _source_refs(overview: dict[str, Any], mainlines: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    refs.extend(ref for ref in overview.get("source_refs") or [] if isinstance(ref, dict))
    refs.extend(ref for ref in mainlines.get("source_refs") or [] if isinstance(ref, dict))
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for ref in refs:
        key = json.dumps(ref, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        unique.append(dict(ref))
    return unique


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to load gold mainline artifact", exc_info=True, extra={"path": str(path)})
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _unavailable_mainlines() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "schema_version": "gold-event-mainlines-v1",
        "asset": "XAUUSD",
        "as_of": None,
        "mainlines": [],
        "event_links": [],
        "dominant_forces": [],
        "source_refs": [],
        "artifact_refs": [],
        "warnings": ["gold_event_mainlines artifact unavailable"],
    }


def _unavailable_payload(*, date: str | None, run_id: str | None, warnings: list[str]) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "date": date,
        "run_id": run_id,
        "artifact_path": None,
        "schema_version": "gold-macro-overview-v1",
        "input_snapshot_ids": {},
        "gold_macro_overview": None,
        "gold_mainlines": _unavailable_mainlines(),
        "source_refs": [],
        "warnings": warnings,
    }
