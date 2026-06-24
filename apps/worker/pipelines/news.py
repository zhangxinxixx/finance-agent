"""News worker pipeline — collect -> classify -> brief.

Chains P0 news/event collectors into the existing worker flow. The pipeline
archives collector raw/parsed payloads through the collectors themselves, then
writes feature artifacts under ``storage/features/news/<date>/<run_id>/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from apps.collectors.news.base import NewsCollectionResult, RawNewsItem
from apps.features.news.daily_brief_snapshot import archive_daily_brief_input_snapshot, build_daily_brief_input_snapshot
from apps.features.news.daily_market_brief import DailyMarketBrief, archive_daily_market_brief, build_daily_market_brief
from apps.features.news.daily_analysis_triggers import (
    DailyAnalysisTriggerBundle,
    archive_daily_analysis_triggers,
    build_daily_analysis_triggers,
)
from apps.features.news.event_candidates import EventCandidateBundle, archive_event_candidates, build_event_candidates
from apps.features.news.impact_classifier import EventImpactAssessment, archive_impact_assessments, build_impact_assessments
from apps.features.news.market_binding import (
    MarketReaction,
    archive_market_reactions,
    build_market_reaction,
    market_snapshot_assets_for_event,
)
from apps.features.news.report_event_extractor import (
    Jin10ReportEventExtraction,
    archive_jin10_report_events,
    extract_jin10_report_events,
)
from apps.renderer.markdown.daily_brief import archive_daily_brief, render_daily_brief_payload

NEWS_STEPS = {"news_collect", "news_feature", "news_brief"}
_MARKET_REACTION_TIMEFRAME = "1m"
_MARKET_REACTION_LIMIT = 4320
_MARKET_REACTION_LOOKBACK_HOURS = 72


@dataclass
class NewsPipelineState:
    """Holds intermediate results for the news/event pipeline."""

    retrieved_date: str = ""
    raw_items: list[RawNewsItem] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    collector_statuses: list[dict[str, Any]] = field(default_factory=list)
    event_bundle: EventCandidateBundle | None = None
    impact_assessments: list[EventImpactAssessment] = field(default_factory=list)
    daily_analysis_triggers: DailyAnalysisTriggerBundle | None = None
    report_event_extraction: Jin10ReportEventExtraction | None = None
    market_reactions: list[MarketReaction] = field(default_factory=list)
    daily_market_brief: DailyMarketBrief | None = None
    snapshot_dict: dict[str, Any] | None = None
    step_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)


def run_news_step(
    step_name: str,
    state: NewsPipelineState,
    *,
    storage_root: Path = Path("./storage"),
    run_id: str | None = None,
    db_session: Any | None = None,
) -> dict[str, Any]:
    """Execute a single news pipeline step and update *state*."""

    dispatch = {
        "news_collect": _step_collect,
        "news_feature": _step_feature,
        "news_brief": _step_brief,
    }
    fn = dispatch.get(step_name)
    if fn is None:
        raise ValueError(f"Unknown news step: {step_name!r}")

    summary = fn(state, storage_root=storage_root, run_id=run_id, db_session=db_session)
    state.step_summaries[step_name] = summary
    return summary


def _step_collect(
    state: NewsPipelineState,
    *,
    storage_root: Path,
    run_id: str | None,
    db_session: Any | None,
) -> dict[str, Any]:
    retrieved_date = datetime.now(timezone.utc).date().isoformat()
    state.retrieved_date = retrieved_date
    checkpoint_state = _load_collection_checkpoints(storage_root)
    checkpoint_path = _collection_checkpoint_path(storage_root).relative_to(storage_root).as_posix()
    skipped_duplicate_item_count = 0
    collected_raw_news_item_count = 0

    for collector_name, collector in _collectors():
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            result = collector(retrieved_date=retrieved_date, storage_root=storage_root)
            collected_raw_news_item_count += len(result.items)
            accepted_items, skipped_count = _filter_checkpointed_items(
                result.items,
                _checkpoint_for_source(checkpoint_state, result.source_key),
            )
            skipped_duplicate_item_count += skipped_count
            checkpointed_result = NewsCollectionResult(
                source_key=result.source_key,
                status=result.status,
                items=accepted_items,
                source_refs=result.source_refs,
                unavailable_feeds=result.unavailable_feeds,
                warnings=result.warnings,
            )
            _merge_collection_result(state, checkpointed_result)
            ended_at = datetime.now(timezone.utc).isoformat()
            _update_collection_checkpoint(
                checkpoint_state,
                collector_name=collector_name,
                result=result,
                started_at=started_at,
                ended_at=ended_at,
                accepted_item_count=len(accepted_items),
                skipped_duplicate_item_count=skipped_count,
            )
            _save_collection_checkpoints(storage_root, checkpoint_state)
            state.collector_statuses.append({
                "collector": collector_name,
                "status": result.status,
                "items": len(accepted_items),
                "collected_items": len(result.items),
                "skipped_duplicate_items": skipped_count,
                "unavailable_feeds": len(result.unavailable_feeds),
                "warnings": list(result.warnings),
                "started_at": started_at,
                "ended_at": ended_at,
                "checkpoint_path": checkpoint_path,
                "high_watermark_published_at": _checkpoint_for_source(checkpoint_state, result.source_key).get("high_watermark_published_at"),
            })
        except Exception as exc:
            ended_at = datetime.now(timezone.utc).isoformat()
            _update_failed_collection_checkpoint(
                checkpoint_state,
                collector_name=collector_name,
                started_at=started_at,
                ended_at=ended_at,
                error=f"{type(exc).__name__}: {exc}",
            )
            _save_collection_checkpoints(storage_root, checkpoint_state)
            state.collector_statuses.append({
                "collector": collector_name,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "started_at": started_at,
                "ended_at": ended_at,
                "checkpoint_path": checkpoint_path,
            })

    failed_or_unavailable = [
        row for row in state.collector_statuses
        if row.get("status") in {"failed", "unavailable"}
    ]
    if state.raw_items and failed_or_unavailable:
        status = "partial_success"
    elif state.raw_items:
        status = "success"
    else:
        status = "partial_success"

    run_key = run_id or "manual"
    diagnostics_path = _archive_collection_diagnostics(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        run_id=run_key,
        collector_statuses=state.collector_statuses,
        source_refs=state.source_refs,
    )

    return {
        "step": "news_collect",
        "status": status,
        "retrieved_date": retrieved_date,
        "raw_news_item_count": len(state.raw_items),
        "collected_raw_news_item_count": collected_raw_news_item_count,
        "skipped_duplicate_item_count": skipped_duplicate_item_count,
        "collector_statuses": state.collector_statuses,
        "source_ref_count": len(state.source_refs),
        "artifact_path": diagnostics_path,
        "collection_checkpoint_path": checkpoint_path,
    }


def _step_feature(
    state: NewsPipelineState,
    *,
    storage_root: Path,
    run_id: str | None,
    db_session: Any | None,
) -> dict[str, Any]:
    if not state.retrieved_date:
        state.retrieved_date = datetime.now(timezone.utc).date().isoformat()
    run_key = run_id or "manual"
    as_of = datetime.now(timezone.utc).isoformat()
    warnings: list[str] = []

    report_extraction: Jin10ReportEventExtraction | None = None
    report_events_path: str | None = None
    feature_items = list(state.raw_items)
    feature_source_refs = list(state.source_refs)

    try:
        report_extraction = _extract_latest_jin10_report_events(storage_root=storage_root, fetched_at=as_of)
    except Exception as exc:
        warnings.append(f"report_event_extractor unavailable: {type(exc).__name__}: {exc}")
    else:
        if report_extraction is not None:
            feature_items.extend(report_extraction.items)
            feature_source_refs.extend(report_extraction.source_refs)
            report_events_path = archive_jin10_report_events(
                storage_root=storage_root,
                retrieved_date=state.retrieved_date,
                run_id=run_key,
                extraction=report_extraction,
            )
            warnings.extend(report_extraction.warnings)

    bundle = build_event_candidates(
        feature_items,
        as_of=as_of,
        source_refs=feature_source_refs,
    )
    assessments = build_impact_assessments(bundle.event_candidates, as_of=as_of)
    daily_analysis_triggers = build_daily_analysis_triggers(
        event_bundle=bundle,
        impact_assessments=assessments,
        as_of=as_of,
    )
    reactions = _build_market_reactions(
        bundle.event_candidates,
        assessments,
        db_session=db_session,
        as_of=as_of,
    )
    event_candidates_path = archive_event_candidates(
        storage_root=storage_root,
        retrieved_date=state.retrieved_date,
        run_id=run_key,
        bundle=bundle,
    )
    impact_assessments_path = archive_impact_assessments(
        storage_root=storage_root,
        retrieved_date=state.retrieved_date,
        run_id=run_key,
        assessments=assessments,
    )
    daily_analysis_triggers_path = archive_daily_analysis_triggers(
        storage_root=storage_root,
        retrieved_date=state.retrieved_date,
        run_id=run_key,
        bundle=daily_analysis_triggers,
    )
    market_reactions_path = archive_market_reactions(
        storage_root=storage_root,
        retrieved_date=state.retrieved_date,
        run_id=run_key,
        reactions=reactions,
    )

    state.event_bundle = bundle
    state.impact_assessments = assessments
    state.daily_analysis_triggers = daily_analysis_triggers
    state.report_event_extraction = report_extraction
    state.market_reactions = reactions
    return {
        "step": "news_feature",
        "status": "success",
        "retrieved_date": state.retrieved_date,
        "event_candidate_count": len(bundle.event_candidates),
        "top_market_event_count": len(bundle.top_market_events),
        "impact_assessment_count": len(assessments),
        "daily_analysis_trigger_count": len(daily_analysis_triggers.triggers),
        "report_event_count": len(report_extraction.items) if report_extraction is not None else 0,
        "market_reaction_count": len(reactions),
        "event_candidates_path": event_candidates_path,
        "impact_assessments_path": impact_assessments_path,
        "daily_analysis_triggers_path": daily_analysis_triggers_path,
        "report_events_path": report_events_path,
        "market_reactions_path": market_reactions_path,
        "artifact_path": event_candidates_path,
        "warnings": warnings,
    }


def _step_brief(
    state: NewsPipelineState,
    *,
    storage_root: Path,
    run_id: str | None,
    db_session: Any | None,
) -> dict[str, Any]:
    if state.event_bundle is None:
        raise RuntimeError("news_brief requires news_feature to have completed first")
    if not state.retrieved_date:
        state.retrieved_date = datetime.now(timezone.utc).date().isoformat()
    run_key = run_id or "manual"

    brief = build_daily_market_brief(
        event_bundle=state.event_bundle,
        impact_assessments=state.impact_assessments,
        market_reactions=state.market_reactions,
        as_of=datetime.now(timezone.utc).isoformat(),
        source_refs=state.source_refs,
    )
    brief_path = archive_daily_market_brief(
        storage_root=storage_root,
        retrieved_date=state.retrieved_date,
        run_id=run_key,
        brief=brief,
    )

    state.daily_market_brief = brief
    trigger_bundle = state.daily_analysis_triggers.to_dict() if state.daily_analysis_triggers is not None else None
    report_events = state.report_event_extraction.to_dict() if state.report_event_extraction is not None else None
    daily_brief_input_snapshot = build_daily_brief_input_snapshot(
        retrieved_date=state.retrieved_date,
        run_id=run_key,
        daily_market_brief=brief.to_dict(),
        daily_analysis_triggers=trigger_bundle,
        report_events=report_events,
        market_reactions=[reaction.to_dict() for reaction in state.market_reactions],
    )
    daily_brief_input_snapshot_path = archive_daily_brief_input_snapshot(
        storage_root=storage_root,
        retrieved_date=state.retrieved_date,
        run_id=run_key,
        snapshot=daily_brief_input_snapshot,
    )
    daily_brief_paths = archive_daily_brief(
        storage_root=storage_root,
        retrieved_date=state.retrieved_date,
        run_id=run_key,
        snapshot=daily_brief_input_snapshot,
    )
    daily_brief_output = render_daily_brief_payload(
        daily_brief_input_snapshot,
        artifact_path=daily_brief_paths["markdown"],
        input_snapshot_path=daily_brief_input_snapshot_path,
    )
    data_quality = dict(brief.data_quality)
    data_quality["daily_analysis_trigger_count"] = len(state.daily_analysis_triggers.triggers) if state.daily_analysis_triggers is not None else 0
    data_quality["daily_brief_report_mode"] = daily_brief_input_snapshot.report_mode
    state.snapshot_dict = {
        "daily_market_brief": brief.to_dict(),
        "daily_analysis_triggers": trigger_bundle,
        "daily_brief_input_snapshot": daily_brief_input_snapshot.to_dict(),
        "daily_brief_output": daily_brief_output,
        "source_refs": brief.source_refs,
        "data_quality": data_quality,
    }
    return {
        "step": "news_brief",
        "status": "success",
        "retrieved_date": state.retrieved_date,
        "daily_market_brief_path": brief_path,
        "daily_brief_input_snapshot_path": daily_brief_input_snapshot_path,
        "daily_brief_markdown_path": daily_brief_paths["markdown"],
        "daily_brief_json_path": daily_brief_paths["json"],
        "artifact_path": brief_path,
        "confirmed_event_count": len(brief.confirmed_events),
        "candidate_event_count": len(brief.candidate_events),
        "unconfirmed_risk_count": len(brief.unconfirmed_risks),
        "daily_brief_report_mode": daily_brief_input_snapshot.report_mode,
    }


def _collectors() -> list[tuple[str, Callable[..., NewsCollectionResult]]]:
    from apps.collectors.news.bea import collect_bea_schedule
    from apps.collectors.news.bls import collect_bls_calendar
    from apps.collectors.news.eia import collect_eia_energy_events
    from apps.collectors.news.fed_rss import collect_fed_rss
    from apps.collectors.news.feishu_jin10 import collect_feishu_jin10_messages, is_feishu_jin10_enabled
    from apps.collectors.news.gdelt import collect_gdelt_docs
    from apps.collectors.news.google_news_rss import collect_google_news_rss
    from apps.collectors.news.reuters_public import collect_reuters_public_news

    collectors: list[tuple[str, Callable[..., NewsCollectionResult]]] = [
        ("fed_rss", collect_fed_rss),
        ("bls_calendar", collect_bls_calendar),
        ("bea_calendar", collect_bea_schedule),
        ("eia_energy", collect_eia_energy_events),
        ("gdelt_news", collect_gdelt_docs),
        ("google_news_rss", collect_google_news_rss),
        ("reuters_public_news", collect_reuters_public_news),
    ]
    if is_feishu_jin10_enabled():
        collectors.append(("jin10_feishu", collect_feishu_jin10_messages))
    return collectors


def _merge_collection_result(state: NewsPipelineState, result: NewsCollectionResult) -> None:
    state.raw_items.extend(result.items)
    state.source_refs.extend(dict(ref) for ref in result.source_refs if isinstance(ref, dict))


def _collection_checkpoint_path(storage_root: Path) -> Path:
    return storage_root / "state" / "news_collection_checkpoints.json"


def _load_collection_checkpoints(storage_root: Path) -> dict[str, Any]:
    path = _collection_checkpoint_path(storage_root)
    if not path.exists():
        return {"version": 1, "updated_at": None, "sources": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "updated_at": None, "sources": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "updated_at": None, "sources": {}}
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        payload["sources"] = {}
    payload.setdefault("version", 1)
    payload.setdefault("updated_at", None)
    return payload


def _save_collection_checkpoints(storage_root: Path, checkpoint_state: dict[str, Any]) -> None:
    path = _collection_checkpoint_path(storage_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(checkpoint_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _checkpoint_for_source(checkpoint_state: dict[str, Any], source_key: str) -> dict[str, Any]:
    sources = checkpoint_state.setdefault("sources", {})
    if not isinstance(sources, dict):
        checkpoint_state["sources"] = {}
        sources = checkpoint_state["sources"]
    checkpoint = sources.setdefault(source_key, {})
    if not isinstance(checkpoint, dict):
        checkpoint = {}
        sources[source_key] = checkpoint
    checkpoint.setdefault("seen_duplicate_keys", [])
    return checkpoint


def _filter_checkpointed_items(items: list[RawNewsItem], checkpoint: dict[str, Any]) -> tuple[list[RawNewsItem], int]:
    seen = {
        str(key)
        for key in checkpoint.get("seen_duplicate_keys", [])
        if key
    }
    accepted: list[RawNewsItem] = []
    skipped = 0
    for item in items:
        key = _news_item_checkpoint_key(item)
        if key in seen:
            skipped += 1
            continue
        accepted.append(item)
    return accepted, skipped


def _update_collection_checkpoint(
    checkpoint_state: dict[str, Any],
    *,
    collector_name: str,
    result: NewsCollectionResult,
    started_at: str,
    ended_at: str,
    accepted_item_count: int,
    skipped_duplicate_item_count: int,
) -> None:
    checkpoint = _checkpoint_for_source(checkpoint_state, result.source_key)
    existing_seen = [
        str(key)
        for key in checkpoint.get("seen_duplicate_keys", [])
        if key
    ]
    seen_keys = [*existing_seen, *[_news_item_checkpoint_key(item) for item in result.items]]
    checkpoint.update({
        "collector": collector_name,
        "source_key": result.source_key,
        "last_attempt_at": started_at,
        "last_success_at": ended_at if result.status in {"success", "partial"} else checkpoint.get("last_success_at"),
        "last_status": result.status,
        "last_collected_item_count": len(result.items),
        "last_accepted_item_count": accepted_item_count,
        "last_skipped_duplicate_item_count": skipped_duplicate_item_count,
        "last_source_ref_count": len(result.source_refs),
        "high_watermark_published_at": _max_iso_datetime([
            str(item.published_at)
            for item in result.items
            if item.published_at
        ], fallback=checkpoint.get("high_watermark_published_at")),
        "seen_duplicate_keys": _dedupe_keep_tail(seen_keys, limit=2000),
        "error": None,
    })


def _update_failed_collection_checkpoint(
    checkpoint_state: dict[str, Any],
    *,
    collector_name: str,
    started_at: str,
    ended_at: str,
    error: str,
) -> None:
    checkpoint = _checkpoint_for_source(checkpoint_state, collector_name)
    checkpoint.update({
        "collector": collector_name,
        "source_key": collector_name,
        "last_attempt_at": started_at,
        "last_status": "failed",
        "last_failed_at": ended_at,
        "error": error,
    })


def _news_item_checkpoint_key(item: RawNewsItem) -> str:
    return str(item.duplicate_key or f"{item.source_key}|{item.url}|{item.title}|{item.published_at}")


def _max_iso_datetime(values: list[str], *, fallback: Any = None) -> str | None:
    candidates = [value for value in values if value]
    if fallback:
        candidates.append(str(fallback))
    if not candidates:
        return None
    return max(candidates)


def _dedupe_keep_tail(values: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in reversed(values):
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return list(reversed(result))


def _archive_collection_diagnostics(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    collector_statuses: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "collection_diagnostics.json"
    target.parent.mkdir(parents=True, exist_ok=True)

    warnings = [
        str(warning)
        for row in collector_statuses
        for warning in (row.get("warnings") or [])
        if warning
    ]
    latest_collector_status_by_collector = {
        str(row.get("collector")): dict(row)
        for row in collector_statuses
        if row.get("collector")
    }
    latest_source_status_by_source_key = _source_status_by_source_key(source_refs)
    payload = {
        "retrieved_date": retrieved_date,
        "run_id": run_id,
        "collector_statuses": collector_statuses,
        "source_ref_count": len(source_refs),
        "latest_collector_status_by_collector": latest_collector_status_by_collector,
        "latest_source_status_by_source_key": latest_source_status_by_source_key,
        "summary": {
            "collector_count": len(collector_statuses),
            "warning_count": len(warnings),
            "warnings": warnings,
            "source_key_count": len(latest_source_status_by_source_key),
        },
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def _source_status_by_source_key(source_refs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_source: dict[str, dict[str, Any]] = {}
    for ref in source_refs:
        if not isinstance(ref, dict):
            continue
        source_key = str(ref.get("source") or ref.get("source_key") or "").strip()
        if not source_key:
            continue
        bucket = by_source.setdefault(
            source_key,
            {
                "source_ref_count": 0,
                "status": "unknown",
                "source_ref_statuses": [],
                "reason_codes": [],
                "warnings": [],
                "source_refs": [],
            },
        )
        bucket["source_ref_count"] += 1
        diagnostic_ref = _source_ref_diagnostic(ref)
        if diagnostic_ref and len(bucket["source_refs"]) < 20:
            bucket["source_refs"].append(diagnostic_ref)
        status = str(ref.get("status") or "").strip()
        if status:
            if bucket["status"] == "unknown":
                bucket["status"] = status
            if status not in bucket["source_ref_statuses"]:
                bucket["source_ref_statuses"].append(status)
        reason_code = str(ref.get("reason_code") or "").strip()
        if reason_code and reason_code not in bucket["reason_codes"]:
            bucket["reason_codes"].append(reason_code)
        warning = str(ref.get("warning") or "").strip()
        if warning and warning not in bucket["warnings"]:
            bucket["warnings"].append(warning)
    return by_source


def _source_ref_diagnostic(ref: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source_ref",
        "source",
        "source_key",
        "query_group",
        "status",
        "reason_code",
        "reason",
        "warning",
        "raw_path",
        "parsed_path",
    )
    return {
        key: ref[key]
        for key in keys
        if ref.get(key) not in (None, "", [])
    }


def _extract_latest_jin10_report_events(
    *,
    storage_root: Path,
    fetched_at: str,
) -> Jin10ReportEventExtraction | None:
    bundle = _find_latest_jin10_report_bundle(storage_root=storage_root)
    if bundle is None:
        return None

    raw_report = _read_json_dict(bundle["raw_article_report_json"])
    daily_analysis = _read_json_dict(bundle["daily_analysis_json"])
    agent_analysis = _read_json_dict(bundle["agent_analysis_report_json"]) if bundle.get("agent_analysis_report_json") else {}
    artifact_paths = {
        "raw_article_report": bundle["raw_article_report_json"].relative_to(storage_root).as_posix(),
        "daily_analysis": bundle["daily_analysis_json"].relative_to(storage_root).as_posix(),
    }
    if bundle.get("agent_analysis_report_json"):
        artifact_paths["agent_analysis_report"] = bundle["agent_analysis_report_json"].relative_to(storage_root).as_posix()
    return extract_jin10_report_events(
        raw_article_report=raw_report,
        daily_analysis=daily_analysis,
        agent_analysis_report=agent_analysis,
        artifact_paths=artifact_paths,
        fetched_at=fetched_at,
    )


def _find_latest_jin10_report_bundle(*, storage_root: Path) -> dict[str, Path] | None:
    base = storage_root / "outputs" / "jin10"
    if not base.exists():
        return None
    for date_dir in sorted((item for item in base.iterdir() if item.is_dir()), reverse=True):
        for run_dir in sorted((item for item in date_dir.iterdir() if item.is_dir()), reverse=True):
            raw_path = run_dir / "raw_article_report.json"
            daily_path = run_dir / "daily_analysis.json"
            if not raw_path.exists() or not daily_path.exists():
                continue
            agent_path = run_dir / "agent_analysis_report.json"
            return {
                "trade_date_dir": date_dir,
                "run_dir": run_dir,
                "raw_article_report_json": raw_path,
                "daily_analysis_json": daily_path,
                "agent_analysis_report_json": agent_path if agent_path.exists() else None,
            }
    return None


def _read_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _build_market_reactions(
    events: list[Any],
    assessments: list[EventImpactAssessment],
    *,
    db_session: Any | None,
    as_of: str,
) -> list[MarketReaction]:
    if db_session is None:
        return []

    bindable_events = _recent_bindable_events(events, as_of=as_of)
    if not bindable_events:
        return []

    assessment_by_event_id = {assessment.event_id: assessment.to_dict() for assessment in assessments}
    assets = sorted(
        {
            asset
            for event in bindable_events
            for asset in market_snapshot_assets_for_event(
                event,
                assessment_by_event_id.get(str(event.get("event_id") or ""), {}),
            )
        }
    )
    if not assets:
        return []

    from database.queries.market import list_market_candles_by_assets

    rows = list_market_candles_by_assets(
        db_session,
        assets=assets,
        timeframe=_MARKET_REACTION_TIMEFRAME,
        limit=_MARKET_REACTION_LIMIT,
    )
    candles_by_asset: dict[str, list[Any]] = {}
    for row in rows:
        candles_by_asset.setdefault(str(getattr(row, "asset", "")), []).append(row)

    reactions: list[MarketReaction] = []
    for event in bindable_events:
        event_id = str(event.get("event_id") or "")
        reaction = build_market_reaction(
            event,
            assessment_by_event_id.get(event_id, {}),
            candles_by_asset,
            windows=("5m", "30m", "2h"),
        )
        if reaction.status == "unavailable" or not reaction.windows:
            continue
        reactions.append(reaction)
    return reactions


def _recent_bindable_events(events: list[Any], *, as_of: str) -> list[dict[str, Any]]:
    as_of_dt = _parse_iso_datetime(as_of)
    if as_of_dt is None:
        return []

    bindable: list[dict[str, Any]] = []
    for event in events:
        event_dict = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        if str(event_dict.get("event_status") or "") == "scheduled":
            continue
        event_time = _parse_iso_datetime(event_dict.get("event_time"))
        if event_time is None or event_time > as_of_dt:
            continue
        age_hours = (as_of_dt - event_time).total_seconds() / 3600
        if age_hours > _MARKET_REACTION_LOOKBACK_HOURS:
            continue
        bindable.append(event_dict)
    return bindable


def _parse_iso_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
