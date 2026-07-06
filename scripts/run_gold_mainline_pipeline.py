from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.analysis.agents.source_health import build_gold_v3_source_health
from apps.analysis.gold_mainline_engine import archive_gold_macro_overview, build_gold_macro_overview
from apps.api.services.source_service import get_data_source_statuses
from apps.collectors.positioning.collector import CFTC_COT_URL
from apps.features.news.gold_event_mainlines import archive_gold_event_mainlines, build_gold_event_mainlines
from apps.gold_runtime_orchestration import build_gold_runtime_summary_preview


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild gold_event_mainlines and gold_macro_overview from existing news feature artifacts."
    )
    parser.add_argument("--storage-root", default="storage", help="finance-agent storage root.")
    parser.add_argument("--date", default=None, help="Source artifact date under features/news/YYYY-MM-DD.")
    parser.add_argument("--run-id", default=None, help="Source artifact run id under features/news/<date>/<run-id>.")
    parser.add_argument(
        "--output-run-id",
        default=None,
        help="Output run id. Defaults to gold-mainlines-refresh-<UTC timestamp>.",
    )
    parser.add_argument(
        "--macro-date",
        default=None,
        help="Macro snapshot date under features/macro/YYYY-MM-DD. Defaults to source date when available.",
    )
    parser.add_argument(
        "--macro-run-id",
        default=None,
        help="Macro snapshot run id under features/macro/<date>/<run-id>. Defaults to latest run for macro date.",
    )
    parser.add_argument(
        "--market-context",
        default=None,
        help="Optional JSON file containing deterministic market context, e.g. XAUUSD price/candles.",
    )
    parser.add_argument(
        "--oil-context",
        default=None,
        help="Optional JSON file containing deterministic oil context, e.g. Brent/WTI/inventory inputs.",
    )
    parser.add_argument(
        "--flow-context",
        default=None,
        help="Optional JSON file containing deterministic ETF flow context, e.g. global / regional gold ETF flows.",
    )
    parser.add_argument(
        "--reserve-context",
        default=None,
        help="Optional JSON file containing deterministic central-bank reserve context.",
    )
    parser.add_argument(
        "--asia-context",
        default=None,
        help="Optional JSON file containing deterministic China / Asia gold demand context.",
    )
    parser.add_argument(
        "--positioning-context",
        default=None,
        help="Optional JSON file containing deterministic COT / COMEX / options / forecast context.",
    )
    parser.add_argument(
        "--policy-context",
        default=None,
        help="Optional JSON file containing deterministic Fed policy path verification context.",
    )
    parser.add_argument(
        "--geopolitical-context",
        default=None,
        help="Optional JSON file containing deterministic geopolitical verification context.",
    )
    parser.add_argument(
        "--run-mode",
        default="premarket_full_run",
        help="Gold v3 runtime mode for the emitted run summary. Defaults to premarket_full_run.",
    )
    parser.add_argument(
        "--trigger-reason",
        default=None,
        help="Optional trigger reason for the emitted Gold v3 runtime summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    storage_root = Path(args.storage_root)
    try:
        runtime_summary = build_gold_runtime_summary_preview(
            run_mode=args.run_mode,
            trigger_reason=args.trigger_reason,
        )
        source_date, source_run_id = _resolve_source_run(
            storage_root=storage_root,
            date=args.date,
            run_id=args.run_id,
        )
        output_run_id = args.output_run_id or _default_output_run_id()
        event_candidates_payload = _read_json(
            storage_root / "features" / "news" / source_date / source_run_id / "event_candidates.json"
        )
        impact_assessments_payload = _read_json(
            storage_root / "features" / "news" / source_date / source_run_id / "impact_assessments.json"
        )
        events = list(event_candidates_payload.get("event_candidates") or [])
        impacts = list(impact_assessments_payload.get("impact_assessments") or [])
        as_of = str(event_candidates_payload.get("as_of") or datetime.now(timezone.utc).isoformat())

        gold_event_mainlines = build_gold_event_mainlines(
            events,
            impact_assessments=impacts,
            as_of=as_of,
        )
        gold_event_mainlines_path = archive_gold_event_mainlines(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            bundle=gold_event_mainlines,
        )
        gold_event_mainlines_payload = gold_event_mainlines.to_dict()
        gold_event_mainlines_payload["artifact_refs"] = [
            {"artifact_type": "event_candidates", "path": f"features/news/{source_date}/{source_run_id}/event_candidates.json"},
            {"artifact_type": "impact_assessments", "path": f"features/news/{source_date}/{source_run_id}/impact_assessments.json"},
            {"artifact_type": "gold_event_mainlines", "path": gold_event_mainlines_path},
        ]
        macro_context, macro_snapshot_path = _resolve_macro_context(
            storage_root=storage_root,
            source_date=source_date,
            macro_date=args.macro_date,
            macro_run_id=args.macro_run_id,
        )
        market_context, market_context_path = _resolve_market_context(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            value=args.market_context,
        )
        oil_context, oil_context_path = _resolve_oil_context(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            value=args.oil_context,
        )
        flow_context, flow_context_path = _resolve_flow_context(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            value=args.flow_context,
        )
        reserve_context, reserve_context_path = _resolve_reserve_context(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            value=args.reserve_context,
            events=events,
            impacts=impacts,
        )
        asia_context, asia_context_path = _resolve_asia_context(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            value=args.asia_context,
            events=events,
            impacts=impacts,
        )
        positioning_context, positioning_context_path = _resolve_positioning_context(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            value=args.positioning_context,
        )
        policy_context, policy_context_path = _resolve_policy_context(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            value=args.policy_context,
            macro_context=macro_context,
            macro_snapshot_path=macro_snapshot_path,
        )
        geopolitical_context, geopolitical_context_path = _resolve_geopolitical_context(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            value=args.geopolitical_context,
            events=events,
            impacts=impacts,
        )
        if macro_snapshot_path:
            gold_event_mainlines_payload["artifact_refs"].append({"artifact_type": "macro_snapshot", "path": macro_snapshot_path})
        if market_context_path:
            gold_event_mainlines_payload["artifact_refs"].append({"artifact_type": "market_context", "path": market_context_path})
        if oil_context_path:
            gold_event_mainlines_payload["artifact_refs"].append({"artifact_type": "oil_context", "path": oil_context_path})
        if flow_context_path:
            gold_event_mainlines_payload["artifact_refs"].append({"artifact_type": "flow_context", "path": flow_context_path})
        if reserve_context_path:
            gold_event_mainlines_payload["artifact_refs"].append({"artifact_type": "reserve_context", "path": reserve_context_path})
        if asia_context_path:
            gold_event_mainlines_payload["artifact_refs"].append({"artifact_type": "asia_context", "path": asia_context_path})
        if positioning_context_path:
            gold_event_mainlines_payload["artifact_refs"].append({"artifact_type": "positioning_context", "path": positioning_context_path})
        if policy_context_path:
            gold_event_mainlines_payload["artifact_refs"].append({"artifact_type": "policy_context", "path": policy_context_path})
        if geopolitical_context_path:
            gold_event_mainlines_payload["artifact_refs"].append({"artifact_type": "geopolitical_context", "path": geopolitical_context_path})
        gold_macro_overview = build_gold_macro_overview(
            gold_event_mainlines_payload,
            macro_context=macro_context,
            market_context=market_context,
            oil_context=oil_context,
            flow_context=flow_context,
            reserve_context=reserve_context,
            asia_context=asia_context,
            positioning_context=positioning_context,
            policy_context=policy_context,
            geopolitical_context=geopolitical_context,
        )
        input_snapshot_ids = {"gold_event_mainlines": gold_event_mainlines_path}
        if macro_snapshot_path:
            input_snapshot_ids["macro_snapshot"] = macro_snapshot_path
        if market_context_path:
            input_snapshot_ids["market_context"] = market_context_path
        if oil_context_path:
            input_snapshot_ids["oil_context"] = oil_context_path
        if flow_context_path:
            input_snapshot_ids["flow_context"] = flow_context_path
        if reserve_context_path:
            input_snapshot_ids["reserve_context"] = reserve_context_path
        if asia_context_path:
            input_snapshot_ids["asia_context"] = asia_context_path
        if positioning_context_path:
            input_snapshot_ids["positioning_context"] = positioning_context_path
        if policy_context_path:
            input_snapshot_ids["policy_context"] = policy_context_path
        if geopolitical_context_path:
            input_snapshot_ids["geopolitical_context"] = geopolitical_context_path
        gold_macro_overview_path = archive_gold_macro_overview(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            overview=gold_macro_overview,
            input_snapshot_ids=input_snapshot_ids,
        )
        runtime_gate = _attach_source_health_runtime_gate(
            storage_root=storage_root,
            gold_macro_overview_path=gold_macro_overview_path,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1

    runtime_summary["review_status"] = runtime_gate["review_gate"]["review_status"]
    runtime_summary["warnings"] = sorted(
        {
            *[str(item) for item in runtime_summary.get("warnings") or []],
            *[str(item) for item in runtime_gate["review_gate"].get("warnings") or []],
        }
    )
    summary = {
        "status": "success",
        "run_mode": runtime_summary["run_mode"],
        "trigger_reason": runtime_summary["trigger_reason"],
        "affected_mainlines": runtime_summary["affected_mainlines"],
        "affected_chains": runtime_summary["affected_chains"],
        "planned_agents_executed": runtime_summary["planned_agents_executed"],
        "planned_agents_skipped": runtime_summary["planned_agents_skipped"],
        "runtime_contract_only": runtime_summary["runtime_contract_only"],
        "gold_macro_overview_updated": runtime_summary["gold_macro_overview_updated"],
        "retrieved_date": source_date,
        "source_run_id": source_run_id,
        "output_run_id": output_run_id,
        "gold_event_mainlines_path": gold_event_mainlines_path,
        "gold_macro_overview_path": gold_macro_overview_path,
        "gold_mainline_count": len(gold_event_mainlines.mainlines),
        "gold_event_link_count": len(gold_event_mainlines.event_links),
        "gold_macro_theme_count": len(gold_macro_overview.theme_rankings),
        "gold_verification_item_count": len(gold_macro_overview.verification_matrix),
        "gold_dominant_mainline": gold_macro_overview.dominant_mainline,
        "gold_readiness": gold_macro_overview.analysis_readiness.to_dict(),
        "runtime_steps": {
            "source_health_check": runtime_gate["source_health_check"],
            "review_gate": runtime_gate["review_gate"],
        },
        "source_health_status": runtime_gate["source_health_check"]["status"],
        "review_status": runtime_gate["review_gate"]["review_status"],
        "warnings": runtime_summary["warnings"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _attach_source_health_runtime_gate(*, storage_root: Path, gold_macro_overview_path: str) -> dict[str, Any]:
    overview_path = storage_root / gold_macro_overview_path
    overview = _read_json(overview_path)
    try:
        source_health = build_gold_v3_source_health(
            get_data_source_statuses(),
            as_of=str(overview.get("as_of") or "") or None,
            gold_macro_overview=overview,
        ).to_dict()
    except Exception as exc:
        source_health = {
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
            "can_emit_strong_conclusion": True,
            "blocked_mainlines": [],
            "degraded_mainlines": [],
            "blocking_reasons": [],
            "warnings": [f"source_health_unavailable: {exc.__class__.__name__}"],
        }
    review_gate = _review_gate_from_source_health(source_health=source_health)
    overview["source_health"] = source_health
    overview["review_gate"] = review_gate
    overview["review_status"] = review_gate["review_status"]
    overview["review_blocking_reasons"] = review_gate["blocking_reasons"]
    if review_gate["review_status"] == "blocked":
        overview["status"] = "blocked"
    overview_path.write_text(json.dumps(overview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "source_health_check": {
            "node_id": "source_health_check",
            "status": source_health["overall_status"],
            "p0_missing": source_health["p0_missing"],
            "p1_missing": source_health["p1_missing"],
            "p2_missing": source_health["p2_missing"],
            "blocking_reasons": source_health["blocking_reasons"],
            "can_build_gold_macro_overview": source_health["can_build_gold_macro_overview"],
        },
        "review_gate": review_gate,
    }


def _review_gate_from_source_health(*, source_health: dict[str, Any]) -> dict[str, Any]:
    blocking_reasons = [str(item) for item in source_health.get("blocking_reasons") or []]
    warnings = [str(item) for item in source_health.get("warnings") or []]
    strong_conflict = any("strong GoldMacroOverview conclusion" in reason for reason in blocking_reasons)
    if strong_conflict:
        review_status = "blocked"
        reason = "SourceHealth blocked a strong GoldMacroOverview conclusion."
    elif blocking_reasons or warnings:
        review_status = "needs_review"
        reason = "SourceHealth found missing or stale sources; downstream conclusion must be reviewed."
    else:
        review_status = "pass"
        reason = "SourceHealth passed with no blocking reasons or warnings."
    return {
        "agent_id": "review_gate_agent",
        "dag_node_id": "review_gate",
        "review_status": review_status,
        "source_health_status": source_health.get("overall_status"),
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "reason": reason,
    }


def _resolve_source_run(*, storage_root: Path, date: str | None, run_id: str | None) -> tuple[str, str]:
    if bool(date) != bool(run_id):
        raise ValueError("--date and --run-id must be provided together.")
    if date and run_id:
        source_dir = storage_root / "features" / "news" / date / run_id
        _require_source_files(source_dir)
        return date, run_id

    base = storage_root / "features" / "news"
    if not base.exists():
        raise FileNotFoundError(f"No news feature artifacts found under {base}")
    for date_dir in sorted((item for item in base.iterdir() if item.is_dir()), reverse=True):
        for run_dir in sorted((item for item in date_dir.iterdir() if item.is_dir()), reverse=True):
            if _has_source_files(run_dir):
                return date_dir.name, run_dir.name
    raise FileNotFoundError(f"No event_candidates.json + impact_assessments.json pair found under {base}")


def _require_source_files(source_dir: Path) -> None:
    missing = [
        path.name
        for path in [source_dir / "event_candidates.json", source_dir / "impact_assessments.json"]
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(f"Missing source artifact(s) in {source_dir}: {', '.join(missing)}")


def _has_source_files(source_dir: Path) -> bool:
    return (source_dir / "event_candidates.json").exists() and (source_dir / "impact_assessments.json").exists()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _persist_context_payload(*, storage_root: Path, rel_path: Path, kind: str, payload: dict[str, Any]) -> str:
    payload["artifact_path"] = rel_path.as_posix()
    _validate_context_payload(kind=kind, payload=payload)
    target = storage_root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rel_path.as_posix()


def _validate_context_payload(*, kind: str, payload: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    source_refs = payload.get("source_refs")
    if not isinstance(source_refs, list) or not any(isinstance(item, dict) for item in source_refs):
        missing.append("source_refs")
    for field in ["provider_role", "verification_status", "as_of", "artifact_path"]:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            missing.append(field)
    warnings = [str(item) for item in payload.get("warnings") or [] if str(item).strip()]
    warnings.extend(f"{kind}_context_missing_{field}" for field in missing)
    if warnings:
        payload["warnings"] = sorted(set(warnings))
    return missing


def _resolve_macro_context(*, storage_root: Path, source_date: str, macro_date: str | None, macro_run_id: str | None) -> tuple[dict[str, Any], str | None]:
    if bool(macro_date) != bool(macro_run_id) and macro_run_id:
        raise ValueError("--macro-date must be provided when --macro-run-id is provided.")
    date = macro_date or source_date
    base = storage_root / "features" / "macro"
    candidates: list[tuple[Path, str]] = []
    if macro_run_id:
        path = base / date / macro_run_id / "macro_snapshot.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing macro snapshot: {path}")
        candidates.append((path, f"features/macro/{date}/{macro_run_id}/macro_snapshot.json"))
    else:
        date_dir = base / date
        if date_dir.exists():
            for run_dir in sorted((item for item in date_dir.iterdir() if item.is_dir()), reverse=True):
                path = run_dir / "macro_snapshot.json"
                if path.exists():
                    candidates.append((path, f"features/macro/{date}/{run_dir.name}/macro_snapshot.json"))
                    break
    if not candidates:
        return {}, None
    path, rel_path = candidates[0]
    return _read_json(path), rel_path


def _resolve_market_context(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    value: str | None,
) -> tuple[dict[str, Any], str | None]:
    if value:
        payload = _read_json(Path(value))
    else:
        payload = _get_market_monitor_overview()
    if not payload:
        return {}, None
    rel_path = _persist_market_context(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        run_id=run_id,
        payload=payload,
    )
    return payload, rel_path


def _persist_market_context(*, storage_root: Path, retrieved_date: str, run_id: str, payload: dict[str, Any]) -> str:
    rel_path = Path("analysis") / "gold_mainlines" / retrieved_date / run_id / "market_context.json"
    return _persist_context_payload(storage_root=storage_root, rel_path=rel_path, kind="market", payload=payload)


def _resolve_oil_context(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    value: str | None,
) -> tuple[dict[str, Any], str | None]:
    if not value:
        return {}, None
    payload = _read_json(Path(value))
    rel_path = Path("analysis") / "gold_mainlines" / retrieved_date / run_id / "oil_context.json"
    return payload, _persist_context_payload(storage_root=storage_root, rel_path=rel_path, kind="oil", payload=payload)


def _resolve_flow_context(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    value: str | None,
) -> tuple[dict[str, Any], str | None]:
    payload = _read_json(Path(value)) if value else _latest_jin10_gold_etf_flow_context(
        storage_root=storage_root,
        source_date=retrieved_date,
    )
    if not payload:
        return {}, None
    rel_path = Path("analysis") / "gold_mainlines" / retrieved_date / run_id / "flow_context.json"
    return payload, _persist_context_payload(storage_root=storage_root, rel_path=rel_path, kind="flow", payload=payload)


def _latest_jin10_gold_etf_flow_context(*, storage_root: Path, source_date: str) -> dict[str, Any]:
    base = storage_root / "parsed" / "jin10" / "datacenter"
    candidates: list[Path] = []
    dated_path = base / source_date / "dc_etf_gold" / "parsed.json"
    if dated_path.exists():
        candidates.append(dated_path)
    if base.exists():
        candidates.extend(
            path / "dc_etf_gold" / "parsed.json"
            for path in sorted((item for item in base.iterdir() if item.is_dir()), reverse=True)
            if path.name != source_date
        )
    for path in candidates:
        if not path.exists():
            continue
        payload = _read_json(path)
        context = _jin10_gold_etf_flow_context_from_parsed(
            payload=payload,
            parsed_path=path.relative_to(storage_root).as_posix(),
        )
        if context:
            return context
    return {}


def _jin10_gold_etf_flow_context_from_parsed(*, payload: dict[str, Any], parsed_path: str) -> dict[str, Any]:
    if payload.get("status") != "ok" or payload.get("slug") != "dc_etf_gold":
        return {}
    rows = [item for item in payload.get("rows") or [] if isinstance(item, dict)]
    if not rows:
        return {}
    latest = max(rows, key=lambda item: str(item.get("data_time") or item.get("date") or ""))
    global_flow = _row_numeric_value(latest, "增持/减持")
    if global_flow is None:
        return {}
    source_refs = _jin10_gold_etf_source_refs(payload=payload, parsed_path=parsed_path)
    return {
        "global_etf_flow": global_flow,
        "north_america_etf_flow": None,
        "asia_etf_flow": None,
        "as_of": payload.get("as_of") or latest.get("data_time") or latest.get("date"),
        "provider_role": "supplemental_source",
        "verification_status": "single_source",
        "source_refs": source_refs,
    }


def _row_numeric_value(row: dict[str, Any], kind_token: str) -> float | None:
    for item in row.get("values") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind_token not in kind:
            continue
        value = str(item.get("value") or "").replace(",", "").strip()
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _jin10_gold_etf_source_refs(*, payload: dict[str, Any], parsed_path: str) -> list[dict[str, Any]]:
    refs = [dict(ref) for ref in payload.get("source_refs") or [] if isinstance(ref, dict)]
    if not refs:
        refs = [{"source": "jin10_datacenter", "source_key": "jin10_datacenter_reports", "slug": "dc_etf_gold"}]
    for ref in refs:
        ref.setdefault("source", "jin10_datacenter")
        ref.setdefault("source_key", "jin10_datacenter_reports")
        ref.setdefault("slug", "dc_etf_gold")
        ref["parsed_path"] = parsed_path
        ref.setdefault("provider_role", "supplemental_source")
        ref.setdefault("source_tier", "supplemental")
        ref.setdefault("evidence_role", "flow_context")
        ref.setdefault("lineage_type", "parsed_artifact")
        ref.setdefault("verification_status", "single_source")
    return refs


def _resolve_reserve_context(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    value: str | None,
    events: list[dict[str, Any]] | None = None,
    impacts: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str | None]:
    payload = _read_json(Path(value)) if value else _news_reserve_context(events=events or [], impacts=impacts or [])
    if not payload:
        return {}, None
    rel_path = Path("analysis") / "gold_mainlines" / retrieved_date / run_id / "reserve_context.json"
    return payload, _persist_context_payload(storage_root=storage_root, rel_path=rel_path, kind="reserve", payload=payload)


def _resolve_asia_context(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    value: str | None,
    events: list[dict[str, Any]] | None = None,
    impacts: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str | None]:
    payload = _read_json(Path(value)) if value else _news_asia_context(events=events or [], impacts=impacts or [])
    if not payload:
        return {}, None
    rel_path = Path("analysis") / "gold_mainlines" / retrieved_date / run_id / "asia_context.json"
    return payload, _persist_context_payload(storage_root=storage_root, rel_path=rel_path, kind="asia", payload=payload)


def _news_reserve_context(*, events: list[dict[str, Any]], impacts: list[dict[str, Any]]) -> dict[str, Any]:
    impact_by_event_id = _impact_by_event_id(impacts)
    reserve_events = [
        event
        for event in events
        if isinstance(event, dict) and _is_reserve_event(event=event, impact=impact_by_event_id.get(str(event.get("event_id") or ""), {}))
    ]
    if not reserve_events:
        return {}
    primary = max(reserve_events, key=lambda event: _number(event.get("confidence")) or 0.0)
    confidence = _number(primary.get("confidence")) or 0.0
    return {
        "central_bank_net_buying": _number(primary.get("central_bank_net_buying")),
        "pboc_gold_holdings_change": _number(primary.get("pboc_gold_holdings_change")),
        "reserve_diversification_signal": str(primary.get("reserve_diversification_signal") or f"{primary.get('event_type')}_watch"),
        "monetary_credit_repricing": primary.get("monetary_credit_repricing"),
        "long_term_support_score": round(min(max(confidence * 10.0, 0.0), 10.0), 2),
        "as_of": primary.get("event_time") or primary.get("as_of"),
        "provider_role": "supplemental_source",
        "verification_status": _aggregate_event_verification_status(reserve_events),
        "source_refs": _news_context_source_refs(events=reserve_events, evidence_role="reserve_context"),
    }


def _news_asia_context(*, events: list[dict[str, Any]], impacts: list[dict[str, Any]]) -> dict[str, Any]:
    impact_by_event_id = _impact_by_event_id(impacts)
    asia_events = [
        event
        for event in events
        if isinstance(event, dict) and _is_asia_event(event=event, impact=impact_by_event_id.get(str(event.get("event_id") or ""), {}))
    ]
    if not asia_events:
        return {}
    primary = max(asia_events, key=lambda event: _number(event.get("confidence")) or 0.0)
    confidence = _number(primary.get("confidence")) or 0.0
    return {
        "usdcnh_weekly_change": _number(primary.get("usdcnh_weekly_change")),
        "usdcnh_monthly_change": _number(primary.get("usdcnh_monthly_change")),
        "shanghai_gold_premium": _number(primary.get("shanghai_gold_premium")),
        "china_gold_etf_flow": _number(primary.get("china_gold_etf_flow")),
        "asia_demand_score": _number(primary.get("asia_demand_score")) or round(min(max(confidence * 10.0, 0.0), 10.0), 2),
        "india_physical_demand": _number(primary.get("india_physical_demand")),
        "cny_gold_relative_strength": primary.get("cny_gold_relative_strength"),
        "as_of": primary.get("event_time") or primary.get("as_of"),
        "provider_role": "supplemental_source",
        "verification_status": _aggregate_event_verification_status(asia_events),
        "source_refs": _news_context_source_refs(events=asia_events, evidence_role="asia_context"),
    }


def _impact_by_event_id(impacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(impact.get("event_id") or ""): impact
        for impact in impacts
        if isinstance(impact, dict) and impact.get("event_id")
    }


def _is_reserve_event(*, event: dict[str, Any], impact: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "")
    impact_path = str(impact.get("impact_path") or event.get("impact_path") or "")
    return event_type in {"central_bank_gold_buying", "reserve_reallocation", "dedollarization_reserve_shift"} or impact_path == "reserve_reallocation"


def _is_asia_event(*, event: dict[str, Any], impact: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "")
    impact_path = str(impact.get("impact_path") or event.get("impact_path") or "")
    return event_type in {"china_gold_demand", "asia_gold_demand", "india_gold_demand", "shanghai_gold_premium"} or impact_path == "asia_demand"


def _resolve_positioning_context(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    value: str | None,
) -> tuple[dict[str, Any], str | None]:
    if value:
        payload = _read_json(Path(value))
    else:
        payload = _merge_positioning_contexts(
            _latest_cftc_cot_positioning_context(storage_root=storage_root, source_date=retrieved_date),
            _latest_cme_options_positioning_context(storage_root=storage_root, source_date=retrieved_date),
        )
    if not payload:
        return {}, None
    rel_path = Path("analysis") / "gold_mainlines" / retrieved_date / run_id / "positioning_context.json"
    return payload, _persist_context_payload(storage_root=storage_root, rel_path=rel_path, kind="positioning", payload=payload)


def _merge_positioning_contexts(*contexts: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    source_refs: list[dict[str, Any]] = []
    provider_roles: set[str] = set()
    verification_statuses: set[str] = set()
    for context in contexts:
        if not context:
            continue
        for ref in context.get("source_refs") or []:
            if isinstance(ref, dict):
                source_refs.append(dict(ref))
        provider_role = str(context.get("provider_role") or "").strip()
        if provider_role:
            provider_roles.add(provider_role)
        verification_status = str(context.get("verification_status") or "").strip()
        if verification_status:
            verification_statuses.add(verification_status)
        for key, value in context.items():
            if key in {"source_refs", "provider_role", "verification_status"}:
                continue
            if key not in merged or merged.get(key) is None:
                merged[key] = value
    if not merged:
        return {}
    if source_refs:
        merged["source_refs"] = source_refs
    if provider_roles:
        merged["provider_role"] = "mixed" if len(provider_roles) > 1 else next(iter(provider_roles))
    if verification_statuses:
        merged["verification_status"] = "multi_source" if len(source_refs) > 1 else next(iter(verification_statuses))
    return merged


def _latest_cftc_cot_positioning_context(*, storage_root: Path, source_date: str) -> dict[str, Any]:
    for path in _cftc_cot_raw_candidates(storage_root=storage_root, source_date=source_date):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue
        context = _cftc_cot_positioning_context_from_raw_rows(
            rows=payload,
            raw_path=path.relative_to(storage_root).as_posix(),
        )
        if context:
            return context
    return {}


def _cftc_cot_raw_candidates(*, storage_root: Path, source_date: str) -> list[Path]:
    base = storage_root / "raw" / "positioning"
    candidates: list[Path] = []
    exact_path = base / source_date / "cot_gold.json"
    if exact_path.exists():
        candidates.append(exact_path)
    if base.exists():
        date_dirs = sorted((item for item in base.iterdir() if item.is_dir()), reverse=True)
        candidates.extend(
            date_dir / "cot_gold.json"
            for date_dir in date_dirs
            if date_dir.name != source_date and date_dir.name <= source_date
        )
        candidates.extend(
            date_dir / "cot_gold.json"
            for date_dir in date_dirs
            if date_dir.name != source_date and date_dir.name > source_date
        )
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def _cftc_cot_positioning_context_from_raw_rows(*, rows: list[Any], raw_path: str) -> dict[str, Any]:
    cot_rows = [row for row in rows if isinstance(row, dict)]
    if not cot_rows:
        return {}
    cot_rows.sort(key=lambda row: str(row.get("Report_Date_as_YYYY-MM-DD") or ""))
    latest = cot_rows[-1]
    previous = cot_rows[-2] if len(cot_rows) > 1 else None
    noncomm_net = _cot_noncomm_net(latest)
    open_interest = _number(latest.get("Open_Interest_All"))
    if noncomm_net is None:
        return {}
    previous_noncomm_net = _cot_noncomm_net(previous) if previous else None
    ratio = noncomm_net / open_interest if open_interest and open_interest > 0 else None
    return {
        "comex_net_long": round(noncomm_net, 6),
        "cot_positioning": _cot_positioning_regime(noncomm_net=noncomm_net, previous_noncomm_net=previous_noncomm_net, ratio=ratio),
        "positioning_crowding": _cot_positioning_crowding(noncomm_net=noncomm_net, ratio=ratio),
        "as_of": latest.get("Report_Date_as_YYYY-MM-DD"),
        "provider_role": "official_source",
        "verification_status": "official_confirmed",
        "source_refs": [
            {
                "source": "cftc_cot",
                "source_ref": f"cot_gold:{latest.get('Report_Date_as_YYYY-MM-DD') or 'latest'}",
                "source_url": CFTC_COT_URL,
                "raw_path": raw_path,
                "provider_role": "official_source",
                "source_tier": "official",
                "evidence_role": "positioning_context",
                "lineage_type": "raw_artifact",
            }
        ],
    }


def _cot_noncomm_net(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    long_value = _number(row.get("M_Money_Positions_Long_All"))
    short_value = _number(row.get("M_Money_Positions_Short_All"))
    if long_value is None or short_value is None:
        return None
    return long_value - short_value


def _cot_positioning_regime(*, noncomm_net: float, previous_noncomm_net: float | None, ratio: float | None) -> str:
    if noncomm_net >= 200000 or (ratio is not None and ratio >= 0.45):
        return "stretched_long"
    if noncomm_net <= -100000 or (ratio is not None and ratio <= -0.25):
        return "net_short"
    if noncomm_net > 0:
        if previous_noncomm_net is not None and noncomm_net > previous_noncomm_net:
            return "net_long_building"
        if previous_noncomm_net is not None and noncomm_net < previous_noncomm_net:
            return "net_long_reducing"
        return "net_long"
    return "neutral"


def _cot_positioning_crowding(*, noncomm_net: float, ratio: float | None) -> str:
    if noncomm_net >= 200000 or (ratio is not None and ratio >= 0.45):
        return "crowded_long"
    if noncomm_net <= -100000 or (ratio is not None and ratio <= -0.25):
        return "crowded_short"
    return "balanced"


def _latest_cme_options_positioning_context(*, storage_root: Path, source_date: str) -> dict[str, Any]:
    candidates = _cme_options_analysis_candidates(storage_root=storage_root, source_date=source_date)
    for path in candidates:
        if not path.exists():
            continue
        payload = _read_json(path)
        context = _cme_options_positioning_context_from_snapshot(
            payload=payload,
            snapshot_path=path.relative_to(storage_root).as_posix(),
        )
        if context:
            return context
    return {}


def _cme_options_analysis_candidates(*, storage_root: Path, source_date: str) -> list[Path]:
    candidates: list[Path] = []
    legacy_path = storage_root / "outputs" / "cme_options" / source_date / "options_analysis.json"
    if legacy_path.exists():
        candidates.append(legacy_path)
    for base in [storage_root / "features" / "cme", storage_root / "outputs" / "cme"]:
        date_dir = base / source_date
        if date_dir.exists():
            candidates.extend(
                run_dir / "options_analysis.json"
                for run_dir in sorted((item for item in date_dir.iterdir() if item.is_dir()), reverse=True)
            )
        if base.exists():
            for other_date_dir in sorted((item for item in base.iterdir() if item.is_dir()), reverse=True):
                if other_date_dir.name == source_date:
                    continue
                candidates.extend(
                    run_dir / "options_analysis.json"
                    for run_dir in sorted((item for item in other_date_dir.iterdir() if item.is_dir()), reverse=True)
                )
    legacy_base = storage_root / "outputs" / "cme_options"
    if legacy_base.exists():
        candidates.extend(
            date_dir / "options_analysis.json"
            for date_dir in sorted((item for item in legacy_base.iterdir() if item.is_dir()), reverse=True)
            if date_dir.name != source_date
        )
    return candidates


def _cme_options_positioning_context_from_snapshot(*, payload: dict[str, Any], snapshot_path: str) -> dict[str, Any]:
    option_skew = _option_skew_from_snapshot(payload)
    call_put_oi_ratio = _call_put_oi_ratio_from_snapshot(payload)
    intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
    institutional_sentiment = str(intent.get("type") or "").strip() or None
    if option_skew is None and call_put_oi_ratio is None and institutional_sentiment is None:
        return {}
    return {
        "comex_net_long": None,
        "cot_positioning": None,
        "option_skew": option_skew,
        "call_put_oi_ratio": call_put_oi_ratio,
        "institutional_sentiment": institutional_sentiment,
        "positioning_crowding": _option_positioning_crowding(call_put_oi_ratio),
        "as_of": payload.get("trade_date"),
        "provider_role": "derived",
        "verification_status": str((payload.get("data_source") or {}).get("status") or "single_source"),
        "source_refs": _cme_options_source_refs(payload=payload, snapshot_path=snapshot_path),
    }


def _option_skew_from_snapshot(payload: dict[str, Any]) -> float | None:
    iv_by_expiry = payload.get("iv_skew_by_expiry")
    if not isinstance(iv_by_expiry, dict):
        gex = payload.get("gex") if isinstance(payload.get("gex"), dict) else {}
        by_expiry = gex.get("by_expiry") if isinstance(gex.get("by_expiry"), dict) else {}
        iv_by_expiry = {
            expiry: data.get("iv_skew")
            for expiry, data in by_expiry.items()
            if isinstance(data, dict) and isinstance(data.get("iv_skew"), dict)
        }
    for expiry in sorted(iv_by_expiry):
        skew = iv_by_expiry.get(expiry)
        if not isinstance(skew, dict):
            continue
        value = _number(skew.get("skew_25d") or skew.get("tail_skew_10d"))
        if value is not None:
            return value
    return None


def _call_put_oi_ratio_from_snapshot(payload: dict[str, Any]) -> float | None:
    call_oi = 0.0
    put_oi = 0.0
    for wall in payload.get("wall_scores") or []:
        if not isinstance(wall, dict):
            continue
        wall_type = str(wall.get("wall_type") or "").lower()
        oi = _number(wall.get("oi"))
        if oi is None:
            continue
        if "call" in wall_type:
            call_oi += oi
        elif "put" in wall_type:
            put_oi += oi
    if call_oi <= 0 or put_oi <= 0:
        return None
    return round(call_oi / put_oi, 6)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _option_positioning_crowding(call_put_oi_ratio: float | None) -> str | None:
    if call_put_oi_ratio is None:
        return None
    if call_put_oi_ratio >= 1.25:
        return "call_wall_dominant"
    if call_put_oi_ratio <= 0.8:
        return "put_wall_dominant"
    return "balanced"


def _cme_options_source_refs(*, payload: dict[str, Any], snapshot_path: str) -> list[dict[str, Any]]:
    refs = [dict(ref) for ref in payload.get("source_trace") or [] if isinstance(ref, dict)]
    if not refs:
        refs = [{"source": "cme_options", "source_ref": f"options_analysis:{payload.get('trade_date') or 'latest'}"}]
    for ref in refs:
        ref.setdefault("source", "cme_options")
        ref["path"] = snapshot_path
        ref.setdefault("provider_role", "derived")
        ref.setdefault("source_tier", "market_derived")
        ref.setdefault("evidence_role", "positioning_context")
        ref.setdefault("lineage_type", "analysis_artifact")
    return refs


def _resolve_policy_context(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    value: str | None,
    macro_context: dict[str, Any] | None = None,
    macro_snapshot_path: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    payload = _read_json(Path(value)) if value else _macro_policy_context(
        macro_context=macro_context or {},
        macro_snapshot_path=macro_snapshot_path,
    )
    if not payload:
        return {}, None
    rel_path = Path("analysis") / "gold_mainlines" / retrieved_date / run_id / "policy_context.json"
    return payload, _persist_context_payload(storage_root=storage_root, rel_path=rel_path, kind="policy", payload=payload)


def _macro_policy_context(*, macro_context: dict[str, Any], macro_snapshot_path: str | None) -> dict[str, Any]:
    indicators = macro_context.get("indicators") if isinstance(macro_context.get("indicators"), dict) else {}
    us02y = _indicator_payload(indicators, "US02Y", "DGS2")
    us10y = _indicator_payload(indicators, "US10Y", "DGS10")
    treasury_2y_change = _number(us02y.get("weekly_change")) if us02y else None
    treasury_10y_change = _number(us10y.get("weekly_change")) if us10y else None
    if treasury_2y_change is None and treasury_10y_change is None:
        return {}
    return {
        "fed_policy_bias": _policy_bias_from_treasury(treasury_2y_change=treasury_2y_change),
        "rate_expectation_delta": None,
        "cut_hike_probability": None,
        "fomc_tone": None,
        "policy_surprise": _policy_surprise_from_treasury(
            treasury_2y_change=treasury_2y_change,
            treasury_10y_change=treasury_10y_change,
        ),
        "treasury_2y_change": treasury_2y_change,
        "treasury_10y_change": treasury_10y_change,
        "as_of": macro_context.get("as_of"),
        "provider_role": "market_derived",
        "verification_status": "market_derived",
        "source_refs": _macro_policy_source_refs(macro_context=macro_context, macro_snapshot_path=macro_snapshot_path),
    }


def _indicator_payload(indicators: dict[str, Any], *symbols: str) -> dict[str, Any]:
    for symbol in symbols:
        value = indicators.get(symbol)
        if isinstance(value, dict):
            return value
    return {}


def _policy_bias_from_treasury(*, treasury_2y_change: float | None) -> str:
    if treasury_2y_change is None:
        return "watch"
    if treasury_2y_change >= 0.05:
        return "higher_for_longer"
    if treasury_2y_change <= -0.05:
        return "easing_repricing"
    return "watch"


def _policy_surprise_from_treasury(*, treasury_2y_change: float | None, treasury_10y_change: float | None) -> str:
    two_year = treasury_2y_change or 0.0
    ten_year = treasury_10y_change or 0.0
    if two_year >= 0.05 and ten_year >= 0.03:
        return "hawkish_rates_repricing"
    if two_year <= -0.05 and ten_year <= -0.03:
        return "dovish_rates_repricing"
    if abs(two_year) >= 0.05 or abs(ten_year) >= 0.05:
        return "rates_curve_repricing"
    return "no_major_surprise"


def _macro_policy_source_refs(*, macro_context: dict[str, Any], macro_snapshot_path: str | None) -> list[dict[str, Any]]:
    source_refs = macro_context.get("source_refs") if isinstance(macro_context.get("source_refs"), dict) else {}
    refs: list[dict[str, Any]] = []
    for symbol in ["US02Y", "DGS2", "US10Y", "DGS10"]:
        ref = source_refs.get(symbol)
        if not isinstance(ref, dict):
            continue
        item = dict(ref)
        item.setdefault("source", "treasury_yields")
        item.setdefault("source_ref", symbol)
        item["macro_snapshot_path"] = macro_snapshot_path
        item.setdefault("provider_role", "market_derived")
        item.setdefault("source_tier", "market_derived")
        item.setdefault("evidence_role", "policy_context")
        item.setdefault("lineage_type", "feature_artifact")
        refs.append(item)
    if not refs:
        refs.append(
            {
                "source": "macro_snapshot",
                "source_ref": "treasury_yields",
                "macro_snapshot_path": macro_snapshot_path,
                "provider_role": "market_derived",
                "source_tier": "market_derived",
                "evidence_role": "policy_context",
                "lineage_type": "feature_artifact",
            }
        )
    return refs


def _resolve_geopolitical_context(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    value: str | None,
    events: list[dict[str, Any]] | None = None,
    impacts: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str | None]:
    payload = _read_json(Path(value)) if value else _news_geopolitical_context(events=events or [], impacts=impacts or [])
    if not payload:
        return {}, None
    rel_path = Path("analysis") / "gold_mainlines" / retrieved_date / run_id / "geopolitical_context.json"
    return payload, _persist_context_payload(storage_root=storage_root, rel_path=rel_path, kind="geopolitical", payload=payload)


def _news_geopolitical_context(*, events: list[dict[str, Any]], impacts: list[dict[str, Any]]) -> dict[str, Any]:
    impact_by_event_id = {
        str(impact.get("event_id") or ""): impact
        for impact in impacts
        if isinstance(impact, dict) and impact.get("event_id")
    }
    geo_events: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        impact = impact_by_event_id.get(str(event.get("event_id") or ""), {})
        if _is_geopolitical_event(event=event, impact=impact):
            geo_events.append((event, impact))
    if not geo_events:
        return {}

    primary, primary_impact = max(
        geo_events,
        key=lambda item: _number(item[0].get("confidence")) or 0.0,
    )
    confidence = _number(primary.get("confidence")) or 0.0
    verification_status = _aggregate_event_verification_status([event for event, _ in geo_events])
    source_refs = _news_geopolitical_source_refs(events=[event for event, _ in geo_events])
    return {
        "geopolitical_status": _geopolitical_status(geo_events),
        "war_escalation_level": _war_escalation_level(primary),
        "safe_haven_score": round(min(max(confidence * 10.0, 0.0), 10.0), 2),
        "energy_channel_risk": _energy_channel_risk(primary=primary, impact=primary_impact),
        "war_oil_rate_chain_status": _war_oil_rate_chain_status(primary=primary, impact=primary_impact),
        "as_of": primary.get("event_time") or primary.get("as_of"),
        "provider_role": "supplemental_source",
        "verification_status": verification_status,
        "source_refs": source_refs,
    }


def _is_geopolitical_event(*, event: dict[str, Any], impact: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "")
    impact_path = str(impact.get("impact_path") or event.get("impact_path") or "")
    return event_type in {"hormuz_risk", "middle_east_escalation", "oil_supply_shock"} or impact_path == "geo_risk_to_oil_to_inflation"


def _aggregate_event_verification_status(events: list[dict[str, Any]]) -> str:
    statuses = {str(event.get("verification_status") or "") for event in events}
    if "official_confirmed" in statuses:
        return "official_confirmed"
    if "multi_source" in statuses or len(_independent_news_sources(events)) >= 2:
        return "multi_source"
    return "single_source"


def _independent_news_sources(events: list[dict[str, Any]]) -> set[str]:
    sources: set[str] = set()
    for event in events:
        for ref in event.get("source_refs") or []:
            if not isinstance(ref, dict):
                continue
            source = str(ref.get("source") or ref.get("source_key") or ref.get("domain") or "").strip()
            if source:
                sources.add(source)
    return sources


def _news_geopolitical_source_refs(*, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _news_context_source_refs(events=events, evidence_role="geopolitical_context")


def _news_context_source_refs(*, events: list[dict[str, Any]], evidence_role: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("event_id") or "")
        event_status = str(event.get("verification_status") or "single_source")
        raw_refs = event.get("source_refs") if isinstance(event.get("source_refs"), list) else []
        if not raw_refs:
            raw_refs = [{"source": "news_event_candidates", "source_ref": event_id}]
        for ref in raw_refs:
            if not isinstance(ref, dict):
                continue
            item = dict(ref)
            item.setdefault("source", "news_event_candidates")
            item.setdefault("source_ref", event_id)
            item.setdefault("event_id", event_id)
            item.setdefault("event_type", event.get("event_type"))
            item.setdefault("provider_role", "supplemental_source")
            item.setdefault("source_tier", "supplemental")
            item.setdefault("evidence_role", evidence_role)
            item.setdefault("lineage_type", "feature_artifact")
            item.setdefault("verification_status", event_status)
            refs.append(item)
    return refs


def _geopolitical_status(geo_events: list[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    event_types = {str(event.get("event_type") or "") for event, _ in geo_events}
    if event_types & {"hormuz_risk", "middle_east_escalation"}:
        return "escalating"
    if "oil_supply_shock" in event_types:
        return "energy_supply_risk"
    return "monitoring"


def _war_escalation_level(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    if event_type in {"hormuz_risk", "middle_east_escalation"}:
        return "regional_risk"
    if event_type == "oil_supply_shock":
        return "energy_channel_stress"
    return "watchlist"


def _energy_channel_risk(*, primary: dict[str, Any], impact: dict[str, Any]) -> str:
    event_type = str(primary.get("event_type") or "")
    impact_path = str(impact.get("impact_path") or primary.get("impact_path") or "")
    oil_impact = str(impact.get("oil_impact") or primary.get("oil_impact") or "")
    if event_type in {"hormuz_risk", "oil_supply_shock"} or impact_path == "geo_risk_to_oil_to_inflation" or oil_impact == "oil_up":
        return "elevated"
    return "watch"


def _war_oil_rate_chain_status(*, primary: dict[str, Any], impact: dict[str, Any]) -> str:
    if _energy_channel_risk(primary=primary, impact=impact) == "elevated":
        return "active"
    return "watch"


def _get_market_monitor_overview() -> dict[str, Any]:
    try:
        from apps.api.services.market_service import get_market_monitor_overview

        payload = get_market_monitor_overview()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _default_output_run_id() -> str:
    return "gold-mainlines-refresh-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
