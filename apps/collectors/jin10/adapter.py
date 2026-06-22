"""Adapter for already-fetched Jin10 VIP reports.

This module intentionally reads the external ~/jin10-reports output only. It
does not import or call the Playwright fetcher.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from apps.collectors.jin10.fetcher import parse_svip_report_html
from apps.analysis.jin10.agent_analysis import (
    build_agent_analysis_prompt,
    build_jin10_agent_analysis_report_with_llm,
)
from apps.analysis.agents.schemas import AgentBias, AgentStatus
from apps.analysis.jin10.daily_report import build_daily_report_analysis_snapshot
from apps.analysis.jin10.visual_report import build_jin10_daily_analysis_report
from apps.analysis.jin10.raw_article import build_jin10_raw_article_report, render_jin10_raw_article_markdown
from apps.analysis.jin10.placeholder import build_analysis_index
from apps.documents.parsing import build_parsed_document
from apps.documents.schemas import SourceAssetRef, SourceDocument
from apps.extractors.report_fact_extractor import extract_report_facts
from apps.parsers.jin10.report import build_parsed_index
from apps.parsers.jin10.report_image_parser import write_parse_artifacts
from apps.renderer.html.jin10_daily import render_jin10_daily_html
from apps.renderer.markdown.jin10_agent_analysis import render_jin10_agent_analysis_markdown
from apps.runtime.state_machine import transition_task_run, transition_task_step
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep

JIN10_CATEGORY_ALIASES: dict[str, list[str]] = {
    "270": ["金银报告", "报告", "daily"],
    "271": ["外汇报告"],
    "272": ["原油报告"],
    "274": ["持仓报告"],
    "380": ["挂单报告"],
    "536": ["周报", "报告", "weekly"],
}

JIN10_CATEGORY_NAMES: dict[str, str] = {
    "270": "金银报告",
    "271": "外汇报告",
    "272": "原油报告",
    "274": "持仓报告",
    "380": "挂单报告",
    "536": "周报",
}

JIN10_REPORT_TYPE_BY_CATEGORY: dict[str, str] = {
    "270": "daily",
    "536": "weekly",
}

def build_jin10_outputs(
    *,
    external_root: Path | str = Path("~/jin10-reports"),
    date: str,
    category: str | None = None,
    article_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build raw, parsed and analysis indexes from external Jin10 files."""

    root = Path(external_root).expanduser()
    raw = collect_raw_index(root, date, category)
    if article_ids:
        expected_ids = {str(item) for item in article_ids}
        raw = dict(raw)
        raw["reports"] = [report for report in raw.get("reports", []) if str(report.get("article_id")) in expected_ids]
        raw["source_refs"] = [ref for ref in raw.get("source_refs", []) if str(ref.get("article_id")) in expected_ids]
    parsed = build_parsed_index(raw)
    analysis = build_analysis_index(parsed)
    parsed_report_map = {item["article_id"]: item for item in parsed["reports"]}
    daily_reports = [
        _build_daily_report_bundle(report, parsed_report_map.get(report["article_id"]), raw["source_refs"])
        for report in raw["reports"]
    ]
    return {"raw": raw, "parsed": parsed, "analysis": analysis, "daily_reports": daily_reports}


def write_jin10_outputs(outputs: dict[str, dict[str, Any]], *, storage_root: Path | str = "storage") -> dict[str, Path]:
    """Write Jin10 indexes into finance-agent storage layers."""

    root = Path(storage_root)
    date = outputs["raw"]["as_of"]
    targets = {
        "raw": root / "raw" / "jin10" / date / "index.json",
        "parsed": root / "parsed" / "jin10" / date / "index.json",
        "analysis": root / "outputs" / "jin10" / date / "analysis.json",
    }

    for layer, target in targets.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = outputs[layer]
        if layer == "parsed":
            payload = {key: value for key, value in payload.items() if key != "artifacts"}
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    parsed_artifacts = outputs.get("parsed", {}).get("artifacts", {})
    for article_id, artifacts in parsed_artifacts.items():
        base = root / "parsed" / "jin10" / date / article_id
        write_parse_artifacts(artifacts, base)

    for report in outputs.get("daily_reports", []):
        base = root / "outputs" / "jin10" / report["trade_date"] / report["run_id"]
        base.mkdir(parents=True, exist_ok=True)
        allowed_figure_paths = {
            str(chart.get("image_path") or "")
            for chart in (report.get("raw_article_json") or {}).get("charts", [])
            if str(chart.get("image_path") or "").strip()
        }
        _copy_output_figures(
            parsed_artifacts.get(report["run_id"]),
            parsed_base=root / "parsed" / "jin10" / report["trade_date"] / report["run_id"],
            output_base=base,
            allowed_paths=allowed_figure_paths,
        )
        (base / "raw_article_report.json").write_text(
            json.dumps(report["raw_article_json"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (base / "raw_article_report.md").write_text(report["raw_article_markdown"], encoding="utf-8")
        (base / "daily_analysis.json").write_text(
            json.dumps(report["json"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (base / "daily_analysis.html").write_text(report["html"], encoding="utf-8")
        (base / "agent_analysis_report.json").write_text(
            json.dumps(report["agent_analysis_json"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (base / "agent_analysis_report.md").write_text(report["agent_analysis_markdown"], encoding="utf-8")

    return targets


def build_jin10_agent_output_payload(
    report: dict[str, Any],
    *,
    storage_root: Path | str = "storage",
) -> dict[str, Any]:
    """Build a traceable AgentOutput payload for Jin10 report analysis."""

    storage_root_path = Path(storage_root)
    trade_date = str(report["trade_date"])
    run_id = str(report["run_id"])
    raw_report = dict(report["raw_article_json"])
    daily_report = dict(report["json"])
    agent_report = dict(report["agent_analysis_json"])
    agent_markdown = str(report["agent_analysis_markdown"])
    prompt = build_agent_analysis_prompt(raw_report, daily_report)

    generated_from = dict(agent_report.get("generated_from") or {})
    generated_source = str(generated_from.get("source") or "")
    generated_by = "llm" if "llm" in generated_source else "rule"
    status = _jin10_agent_status(agent_report, generated_source)
    bias = _jin10_agent_bias(agent_report)
    confidence = _jin10_agent_confidence(agent_report, generated_by, status)
    source_refs = [dict(item) for item in agent_report.get("source_refs") or [] if isinstance(item, dict)]
    claims = _jin10_agent_claims(agent_report)

    artifact_refs = [
        str(storage_root_path / "outputs" / "jin10" / trade_date / run_id / "raw_article_report.json"),
        str(storage_root_path / "outputs" / "jin10" / trade_date / run_id / "raw_article_report.md"),
        str(storage_root_path / "outputs" / "jin10" / trade_date / run_id / "daily_analysis.json"),
        str(storage_root_path / "outputs" / "jin10" / trade_date / run_id / "daily_analysis.html"),
        str(storage_root_path / "outputs" / "jin10" / trade_date / run_id / "agent_analysis_report.json"),
        str(storage_root_path / "outputs" / "jin10" / trade_date / run_id / "agent_analysis_report.md"),
    ]
    visual_family = str(daily_report.get("family") or "jin10_daily_visual")
    input_snapshot_ids = {
        "jin10_raw_article_report": f"jin10:{trade_date}:{run_id}:raw_article_report",
        visual_family: f"jin10:{trade_date}:{run_id}:daily_analysis",
    }

    key_findings = [
        f"市场阶段：{agent_report.get('market_stage', {}).get('label') or 'unavailable'}",
        *[
            str(item).strip()
            for item in agent_report.get("logic_chain") or []
            if str(item).strip()
        ][:3],
    ]
    watchlist = [
        str(item.get("name")).strip()
        for item in agent_report.get("key_variables") or []
        if str(item.get("name") or "").strip()
    ][:8]
    invalid_conditions = _dedupe(
        [
            *[
                str(item.get("invalid") or "").strip()
                for item in agent_report.get("scenario_paths") or []
                if isinstance(item, dict)
            ],
            *[
                str(item.get("invalid") or "").strip()
                for item in agent_report.get("trading_implications") or []
                if isinstance(item, dict)
            ],
            *[str(item).strip() for item in agent_report.get("unresolved_items") or []],
        ]
    )

    return {
        "snapshot_id": f"jin10:{trade_date}:{run_id}:agent_analysis",
        "analysis_snapshot_db_id": None,
        "asset": str(agent_report.get("asset") or "XAUUSD"),
        "trade_date": trade_date,
        "run_id": run_id,
        "agent_name": "jin10_report_analysis_agent",
        "module": "jin10_reports",
        "version": "1.0",
        "status": status.value,
        "bias": bias.value,
        "confidence": confidence,
        "input_snapshot_ids": input_snapshot_ids,
        "source_refs": source_refs,
        "key_findings": _dedupe([item for item in key_findings if item]),
        "risk_points": [str(item).strip() for item in agent_report.get("risk_points") or [] if str(item).strip()],
        "watchlist": watchlist,
        "invalid_conditions": invalid_conditions,
        "summary": str(agent_report.get("one_line_conclusion") or agent_report.get("final_summary") or ""),
        "payload": {
            "title": agent_report.get("title"),
            "article_id": agent_report.get("article_id"),
            "family": agent_report.get("family"),
            "generated_by": generated_by,
            "generated_from": generated_from,
            "prompt_version": "jin10_agent_analysis_v2",
            "prompt_messages": [
                {"role": "system", "content": "你是一名专业的宏观市场与贵金属分析 Agent，默认使用简体中文。"},
                {"role": "user", "content": prompt},
            ],
            "input_payload": {
                "raw_report": raw_report,
                "daily_report": daily_report,
            },
            "llm_raw_output": agent_markdown if generated_by == "llm" else None,
            "narrative_md": agent_markdown,
            "report_json": agent_report,
            "artifact_refs": artifact_refs,
            "source_artifact_refs": list(agent_report.get("source_artifact_refs") or []),
            "claims": claims,
            "data_category": str(agent_report.get("data_category") or "external_opinion"),
        },
        "token_usage": generated_from.get("tokens"),
        "llm_model": generated_from.get("model"),
        "llm_elapsed_seconds": _latency_seconds(generated_from.get("latency_ms")),
    }


def persist_jin10_agent_outputs(
    outputs: dict[str, dict[str, Any]],
    *,
    storage_root: Path | str = "storage",
    session: Any | None = None,
) -> list[dict[str, Any]]:
    """Persist Jin10 report-analysis AgentOutput rows and return a compact summary."""

    from apps.analysis.agents.fact_review import persist_fact_review_agent_output
    from apps.analysis.agents.synthesis import persist_synthesis_agent_output
    from database.queries.analysis import upsert_agent_output

    own_session = session is None
    if own_session:
        from database.models.engine import SessionLocal

        session = SessionLocal()

    assert session is not None
    persisted: list[dict[str, Any]] = []
    try:
        for report in outputs.get("daily_reports", []):
            payload = build_jin10_agent_output_payload(report, storage_root=storage_root)
            row = upsert_agent_output(session, payload)
            fact_review = persist_fact_review_agent_output(session, snapshot_id=row.snapshot_id)
            synthesis = persist_synthesis_agent_output(session, snapshot_id=row.snapshot_id)
            persisted.append(
                {
                    "agent_output_id": row.id,
                    "run_id": row.run_id,
                    "snapshot_id": row.snapshot_id,
                    "agent_name": row.agent_name,
                    "trade_date": payload["trade_date"],
                    "fact_review_agent_output_id": fact_review["agent_output_id"],
                    "fact_review_status": fact_review["fact_review_status"],
                    "synthesis_agent_output_id": synthesis["agent_output_id"],
                    "synthesis_status": synthesis["synthesis_status"],
                }
            )
        if own_session:
            session.commit()
        return persisted
    finally:
        if own_session:
            session.close()


def persist_jin10_task_runs(
    outputs: dict[str, dict[str, Any]],
    *,
    storage_root: Path | str = "storage",
    session: Any | None = None,
) -> list[dict[str, Any]]:
    from database.models.engine import SessionLocal
    from database.models.task import ensure_task_tables

    own_session = session is None
    if own_session:
        session = SessionLocal()

    assert session is not None
    ensure_task_tables(session)
    persisted: list[dict[str, Any]] = []
    try:
        for report in outputs.get("daily_reports", []):
            trade_date = str(report.get("trade_date") or "")
            run_id = str(report.get("run_id") or "")
            quality_audit = report.get("quality_audit") or {}
            quality_status = str(quality_audit.get("status") or "accepted")
            task_status = TaskStatus.success if quality_status == "accepted" else TaskStatus.degraded
            error_summary = None if quality_status == "accepted" else f"jin10 report quality audit: {quality_status}"
            now = datetime.now(timezone.utc)
            existing = (
                session.query(TaskRun)
                .filter(
                    TaskRun.task_type == "jin10_report",
                    TaskRun.trade_date == trade_date,
                    TaskRun.final_result_id == run_id,
                )
                .first()
            )
            if existing is not None:
                existing.current_stage = "agent" if quality_status == "accepted" else "quality_audit"
                existing.error_summary = error_summary
                existing_steps = (
                    session.query(TaskStep)
                    .filter(TaskStep.task_run_id == existing.id)
                    .order_by(TaskStep.step_order.asc())
                    .all()
                )
                for step in existing_steps:
                    if step.name == "agent_analysis":
                        transition_task_step(
                            session,
                            step,
                            StepStatus.blocked if quality_status == "rejected" else StepStatus.success,
                            source="jin10_adapter",
                            blocked_reason="quality_audit rejected" if quality_status == "rejected" else None,
                        )
                    if step.name == "quality_audit":
                        step.output_json = json.dumps(quality_audit, ensure_ascii=False)
                        step.error_json = json.dumps(quality_audit, ensure_ascii=False) if quality_status != "accepted" else None
                        transition_task_step(
                            session,
                            step,
                            StepStatus.blocked if quality_status == "rejected" else StepStatus.success,
                            source="jin10_adapter",
                            blocked_reason="report rejected by quality audit" if quality_status == "rejected" else None,
                        )
                        break
                else:
                    quality_step = TaskStep(
                        task_run_id=existing.id,
                        name="quality_audit",
                        stage="quality",
                        task_kind="validation",
                        status=StepStatus.pending,
                        started_at=now,
                        finished_at=now,
                        duration_ms=0,
                        step_order=5,
                        output_json=json.dumps(quality_audit, ensure_ascii=False),
                        error_json=json.dumps(quality_audit, ensure_ascii=False) if quality_status != "accepted" else None,
                        blocked_reason="report rejected by quality audit" if quality_status == "rejected" else None,
                    )
                    session.add(quality_step)
                    session.flush()
                    transition_task_step(
                        session,
                        quality_step,
                        StepStatus.blocked if quality_status == "rejected" else StepStatus.success,
                        source="jin10_adapter",
                        blocked_reason="report rejected by quality audit" if quality_status == "rejected" else None,
                    )
                transition_task_run(session, existing, task_status, source="jin10_adapter")
                persisted.append({"task_run_id": str(existing.id), "run_id": run_id, "status": existing.status.value})
                continue

            task_run = TaskRun(
                name=f"jin10_report:{run_id}",
                task_type="jin10_report",
                workspace_id="jin10",
                status=TaskStatus.pending,
                current_stage="agent" if quality_status == "accepted" else "quality_audit",
                progress=1.0,
                started_at=now,
                ended_at=now,
                snapshot_id=f"jin10:{trade_date}:{run_id}:agent_analysis",
                final_result_id=run_id,
                trade_date=trade_date,
                error_summary=error_summary,
            )
            session.add(task_run)
            session.flush()

            source_refs = _dump_task_refs(_jin10_task_source_refs(report.get("raw_article_json") or {}))
            raw_outputs = _dump_task_refs(
                [
                    _task_ref(f"{run_id}:raw_article_md", "source_md", f"storage/outputs/jin10/{trade_date}/{run_id}/raw_article_report.md"),
                    _task_ref(f"{run_id}:raw_article_json", "structured_json", f"storage/outputs/jin10/{trade_date}/{run_id}/raw_article_report.json"),
                ]
            )
            parsed_outputs = _dump_task_refs(
                [
                    _task_ref(f"{run_id}:parsed_index", "parsed_file", f"storage/parsed/jin10/{trade_date}/{run_id}/index.json"),
                ]
            )
            visual_outputs = _dump_task_refs(
                [
                    _task_ref(f"{run_id}:daily_html", "visual_html", f"storage/outputs/jin10/{trade_date}/{run_id}/daily_analysis.html"),
                    _task_ref(f"{run_id}:daily_json", "structured_json", f"storage/outputs/jin10/{trade_date}/{run_id}/daily_analysis.json"),
                ]
            )
            agent_outputs = _dump_task_refs(
                [
                    _task_ref(f"{run_id}:agent_md", "analysis_md", f"storage/outputs/jin10/{trade_date}/{run_id}/agent_analysis_report.md"),
                    _task_ref(f"{run_id}:agent_json", "structured_json", f"storage/outputs/jin10/{trade_date}/{run_id}/agent_analysis_report.json"),
                ]
            )
            quality_output = _dump_task_refs(
                [
                    _task_ref(f"{run_id}:quality_audit", "quality_audit", f"storage/outputs/jin10/{trade_date}/{run_id}/daily_analysis.json"),
                ]
            )
            latency_ms = int((((report.get("agent_analysis_json") or {}).get("generated_from") or {}).get("latency_ms") or 0))
            agent_step_status = StepStatus.blocked if quality_status == "rejected" else StepStatus.success

            steps = [
                TaskStep(
                    task_run_id=task_run.id,
                    name="external_ingest",
                    stage="collector",
                    task_kind="collector",
                    status=StepStatus.pending,
                    started_at=now,
                    finished_at=now,
                    source_refs=source_refs,
                    output_refs=raw_outputs,
                    artifact_refs=raw_outputs,
                    duration_ms=0,
                    step_order=1,
                ),
                TaskStep(
                    task_run_id=task_run.id,
                    name="vlm_parse",
                    stage="parser",
                    task_kind="parser",
                    status=StepStatus.pending,
                    started_at=now,
                    finished_at=now,
                    source_refs=source_refs,
                    input_refs=raw_outputs,
                    output_refs=parsed_outputs,
                    artifact_refs=parsed_outputs,
                    duration_ms=0,
                    step_order=2,
                ),
                TaskStep(
                    task_run_id=task_run.id,
                    name="daily_analysis",
                    stage="analysis",
                    task_kind="analysis",
                    status=StepStatus.pending,
                    started_at=now,
                    finished_at=now,
                    source_refs=source_refs,
                    input_refs=parsed_outputs,
                    output_refs=visual_outputs,
                    artifact_refs=visual_outputs,
                    duration_ms=0,
                    step_order=3,
                ),
                TaskStep(
                    task_run_id=task_run.id,
                    name="agent_analysis",
                    stage="agent",
                    task_kind="agent",
                    status=StepStatus.pending,
                    started_at=now,
                    finished_at=now,
                    source_refs=source_refs,
                    input_refs=visual_outputs,
                    output_refs=agent_outputs,
                    artifact_refs=agent_outputs,
                    duration_ms=latency_ms,
                    step_order=4,
                ),
                TaskStep(
                    task_run_id=task_run.id,
                    name="quality_audit",
                    stage="quality",
                    task_kind="validation",
                    status=StepStatus.pending,
                    started_at=now,
                    finished_at=now,
                    source_refs=source_refs,
                    input_refs=agent_outputs,
                    output_refs=quality_output,
                    artifact_refs=quality_output,
                    duration_ms=0,
                    step_order=5,
                    output_json=json.dumps(quality_audit, ensure_ascii=False),
                    error_json=json.dumps(quality_audit, ensure_ascii=False) if quality_status != "accepted" else None,
                    blocked_reason="report rejected by quality audit" if quality_status == "rejected" else None,
                ),
            ]
            session.add_all(steps)
            session.flush()
            for step in steps:
                if step.name == "agent_analysis":
                    transition_task_step(
                        session,
                        step,
                        agent_step_status,
                        source="jin10_adapter",
                        blocked_reason="quality_audit rejected" if quality_status == "rejected" else None,
                    )
                    continue
                if step.name == "quality_audit":
                    transition_task_step(
                        session,
                        step,
                        StepStatus.blocked if quality_status == "rejected" else StepStatus.success,
                        source="jin10_adapter",
                        blocked_reason="report rejected by quality audit" if quality_status == "rejected" else None,
                    )
                    continue
                transition_task_step(session, step, StepStatus.success, source="jin10_adapter")
            transition_task_run(session, task_run, task_status, source="jin10_adapter")
            persisted.append({"task_run_id": str(task_run.id), "run_id": run_id, "status": task_run.status.value})
        if own_session:
            session.commit()
        return persisted
    finally:
        if own_session:
            session.close()


def _task_ref(artifact_id: str, artifact_type: str, file_path: str) -> dict[str, Any]:
    return {"artifact_id": artifact_id, "artifact_type": artifact_type, "file_path": file_path}


def _dump_task_refs(refs: list[dict[str, Any]]) -> str:
    return json.dumps(refs, ensure_ascii=True)


def _jin10_task_source_refs(raw_json: dict[str, Any]) -> list[dict[str, Any]]:
    refs = []
    for item in raw_json.get("source_refs") or []:
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                "source_id": str(item.get("article_id") or item.get("path") or "jin10"),
                "source_name": str(item.get("source") or item.get("article_id") or "jin10_external"),
                "source_type": str(item.get("asset_type") or "article"),
                "data_date": raw_json.get("trade_date"),
                "file_path": item.get("path"),
                "sha256": item.get("sha256"),
                "url": item.get("source_url"),
                "status": "available",
            }
        )
    return refs


def collect_raw_index(root: Path, date: str, category: str | None = None) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    date_dir = root / date
    unavailable: list[dict[str, str]] = []

    if not date_dir.is_dir():
        return _empty_raw_index(
            date=date,
            root=root,
            retrieved_at=retrieved_at,
            unavailable=[
                {
                    "symbol": _symbol(date, category),
                    "reason": "date_not_found",
                    "source_root": str(root),
                }
            ],
        )

    category_dirs = _category_dirs(date_dir, category)
    if category and not category_dirs:
        return _empty_raw_index(
            date=date,
            root=root,
            retrieved_at=retrieved_at,
            unavailable=[
                {
                    "symbol": _symbol(date, category),
                    "reason": "category_not_found",
                    "source_root": str(root),
                }
            ],
        )

    reports = [_read_report_dir(report_dir, root, date, category, retrieved_at) for report_dir in _report_dirs(category_dirs)]
    reports = [report for report in reports if report is not None]
    reports = _dedupe_reports_by_article_id(reports, requested_category=category)

    if category and not reports:
        unavailable.append(
            {
                "symbol": _symbol(date, category),
                "reason": "report_not_found",
                "source_root": str(root),
            }
        )

    return {
        "schema_version": 1,
        "source": "jin10_external",
        "as_of": date,
        "external_root": str(root),
        "retrieved_at": retrieved_at,
        "reports": reports,
        "source_refs": _source_refs(reports),
        "unavailable_symbols": unavailable,
    }


def _empty_raw_index(
    *, date: str, root: Path, retrieved_at: str, unavailable: list[dict[str, str]]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "jin10_external",
        "as_of": date,
        "external_root": str(root),
        "retrieved_at": retrieved_at,
        "reports": [],
        "source_refs": [],
        "unavailable_symbols": unavailable,
    }


def _category_dirs(date_dir: Path, category: str | None) -> list[Path]:
    if category is None:
        return sorted(path for path in date_dir.iterdir() if path.is_dir())

    names = JIN10_CATEGORY_ALIASES.get(category, [category])
    return [date_dir / name for name in names if (date_dir / name).is_dir()]


def _report_dirs(category_dirs: list[Path]) -> list[Path]:
    dirs: list[Path] = []
    for category_dir in category_dirs:
        dirs.extend(sorted(path for path in category_dir.iterdir() if path.is_dir()))
    return dirs


def _dedupe_reports_by_article_id(
    reports: list[dict[str, Any]],
    *,
    requested_category: str | None,
) -> list[dict[str, Any]]:
    if not reports:
        return []
    selected: dict[str, dict[str, Any]] = {}
    for report in reports:
        article_id = str(report.get("article_id") or "")
        if not article_id:
            continue
        current = selected.get(article_id)
        if current is None or _report_preference_key(report, requested_category) < _report_preference_key(current, requested_category):
            selected[article_id] = report
    return sorted(selected.values(), key=lambda item: (str(item.get("date") or ""), str(item.get("article_id") or "")))


def _report_preference_key(report: dict[str, Any], requested_category: str | None) -> tuple[int, int, str]:
    # Prefer complete archives first, then canonical directory names. This avoids
    # stale preview directories shadowing real 20-page image archives.
    image_penalty = -len(report.get("images") or [])
    parent_name = Path(str(report.get("external_report_dir") or "")).parent.name
    canonical_priority = _category_parent_priority(parent_name, requested_category)
    return (image_penalty, canonical_priority, str(report.get("external_report_dir") or ""))


def _category_parent_priority(parent_name: str, requested_category: str | None) -> int:
    if requested_category == "536":
        order = {"weekly": 0, "周报": 1, "报告": 2}
    elif requested_category == "270":
        order = {"daily": 0, "金银报告": 1, "报告": 2}
    else:
        order = {"daily": 0, "weekly": 0, "金银报告": 1, "周报": 1, "报告": 2}
    return order.get(parent_name, 9)


def _read_report_dir(
    report_dir: Path,
    root: Path,
    date: str,
    requested_category: str | None,
    retrieved_at: str,
) -> dict[str, Any] | None:
    meta_path = report_dir / "meta.json"
    report_path = report_dir / "report.md"
    if not meta_path.is_file() or not report_path.is_file():
        return None

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    article_id = str(meta.get("id") or report_dir.name)
    category_name = str(meta.get("category") or report_dir.parent.name)
    category_code = requested_category or _infer_category_code(category_name, report_dir.parent.name)
    report_type = str(meta.get("report_type") or "").strip().lower()
    expected_report_type = JIN10_REPORT_TYPE_BY_CATEGORY.get(category_code or "")
    if expected_report_type and report_type and report_type != expected_report_type:
        return None
    images = _image_refs(report_dir / "images", meta.get("images", []))
    detail_html_path = report_dir / "detail.html"
    if _is_incomplete_vip_summary_report(report_path=report_path, detail_html_path=detail_html_path, images=images):
        return None
    if _should_reparse_external_report(meta=meta, report_path=report_path, images=images, detail_html_path=detail_html_path):
        meta, images = _rebuild_external_report_from_detail_html(
            report_dir=report_dir,
            meta=meta,
            report_path=report_path,
            detail_html_path=detail_html_path,
        )
    if _is_incomplete_vip_summary_report(report_path=report_path, detail_html_path=detail_html_path, images=images):
        return None
    payload = {
        "article_id": article_id,
        "date": str(meta.get("date") or date),
        "title": str(meta.get("title") or ""),
        "category": category_name,
        "category_code": category_code,
        "report_type": report_type or expected_report_type or "",
        "source_url": str(meta.get("source_url") or f"https://xnews.jin10.com/details/{article_id}"),
        "external_report_dir": str(report_dir),
        "retrieved_at": retrieved_at,
        "meta_json": _file_ref(meta_path, "meta_json"),
        "report_md": _file_ref(report_path, "report_md"),
        "images": images,
    }
    return payload


def _should_reparse_external_report(
    *,
    meta: dict[str, Any],
    report_path: Path,
    images: list[dict[str, Any]],
    detail_html_path: Path,
) -> bool:
    if not detail_html_path.is_file():
        return False
    report_text = report_path.read_text(encoding="utf-8")
    normalized = "".join(report_text.split())
    if "证据不足：仅抓取到详情页HTML，未稳定解析出正文。" in normalized:
        return True
    if len(images) == 0 and not meta.get("images"):
        return True
    if any(
        token in normalized
        for token in (
            "金十VIP专享",
            "欢迎点击查看",
            "更多金银信号和消息汇总",
            "来看今天最新的金银报告",
            "图表解析:unavailable",
        )
    ):
        return True
    body_lines = [line.strip() for line in report_text.splitlines() if line.strip()]
    if len(body_lines) <= 8:
        return True
    return False


def _is_incomplete_vip_summary_report(
    *,
    report_path: Path,
    detail_html_path: Path,
    images: list[dict[str, Any]],
) -> bool:
    report_text = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    detail_text = detail_html_path.read_text(encoding="utf-8") if detail_html_path.is_file() else ""
    compact = "".join(f"{report_text}\n{detail_text}".split())
    report_compact = "".join(report_text.split())

    has_report_download_placeholder = any(
        token in report_compact
        for token in (
            "页数：",
            "页数:",
            "仅VIP查看",
            "下载地址：",
            "下载地址:",
        )
    )
    has_ellipsis_body = any(
        token in compact
        for token in (
            "1、行情回顾：...",
            "1、行情回顾:...",
            "2、关键指标：...",
            "2、关键指标:...",
            "3、观点分享：...",
            "3、观点分享:...",
        )
    )
    # Some newly fetched daily Jin10 VIP reports only expose a short guided body
    # plus page images at this stage. If we already have a valid daily skeleton
    # and local images, keep the report in the pipeline and let downstream VLM
    # / agent analysis consume it instead of dropping it as an incomplete shell.
    has_guided_daily_body = "文章导读：" in report_text and "1、行情回顾" in report_text
    # This is the public/VIP preview shell, not the full report evidence.
    if has_report_download_placeholder and has_ellipsis_body and len(images) <= 2:
        return True
    if has_guided_daily_body and len(images) > 0 and not has_report_download_placeholder:
        return False
    return False


def _rebuild_external_report_from_detail_html(
    *,
    report_dir: Path,
    meta: dict[str, Any],
    report_path: Path,
    detail_html_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reparsed = parse_svip_report_html(
        detail_html_path.read_text(encoding="utf-8"),
        article_id=str(meta.get("id") or report_dir.name),
        source_url=str(meta.get("source_url") or f"https://svip.jin10.com/news/{report_dir.name}"),
    )
    report_path.write_text(reparsed.report_markdown, encoding="utf-8")
    rebuilt_meta = dict(meta)
    existing_images = list(meta.get("images") or [])
    rebuilt_images = _rebuild_meta_images(reparsed.image_urls)
    local_image_map = _match_local_images_to_rebuilt_meta(report_dir / "images", rebuilt_images, existing_images)
    rebuilt_meta.update(
        {
            "date": reparsed.date,
            "title": reparsed.title,
            "category": reparsed.category,
            "report_type": reparsed.report_type,
            "source_url": reparsed.source_url,
            "fetched_at": reparsed.fetched_at,
            "images": local_image_map,
            "image_insights": [],
        }
    )
    meta_path = report_dir / "meta.json"
    meta_path.write_text(json.dumps(rebuilt_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    local_refs = _image_refs(report_dir / "images", rebuilt_meta.get("images", []))
    return rebuilt_meta, local_refs or _meta_image_url_refs(rebuilt_meta.get("images", []))


def _rebuild_meta_images(image_urls: list[str]) -> list[dict[str, Any]]:
    return [{"file": Path(path).name, "seq": index, "source_url": path} for index, path in enumerate(image_urls, start=1)]


def _match_local_images_to_rebuilt_meta(
    images_dir: Path,
    rebuilt_images: list[dict[str, Any]],
    existing_images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not images_dir.is_dir():
        return rebuilt_images

    local_paths = sorted(path for path in images_dir.iterdir() if path.is_file())
    if not local_paths:
        return rebuilt_images

    existing_by_seq = {
        int(item.get("seq")): item
        for item in existing_images
        if str(item.get("seq") or "").isdigit()
    }

    mapped: list[dict[str, Any]] = []
    for index, image in enumerate(rebuilt_images, start=1):
        local_path = local_paths[index - 1] if index - 1 < len(local_paths) else None
        existing = existing_by_seq.get(index, {})
        mapped.append(
            {
                "file": local_path.name if local_path is not None else image.get("file"),
                "seq": index,
                "path": str(local_path) if local_path is not None else existing.get("path"),
                "source_url": image.get("source_url"),
            }
        )
    return mapped


def _meta_image_url_refs(image_meta: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in image_meta:
        source_url = str(item.get("source_url") or "")
        if not source_url:
            continue
        refs.append(
            {
                "asset_type": "image",
                "path": source_url,
                "size_bytes": 0,
                "sha256": hashlib.sha256(source_url.encode("utf-8")).hexdigest(),
                "file": str(item.get("file") or Path(source_url).name),
                "seq": item.get("seq"),
                "width": item.get("w"),
                "height": item.get("h"),
                "source_url": source_url,
            }
        )
    return refs


def _image_refs(images_dir: Path, image_meta: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if not images_dir.is_dir():
        return refs

    local_paths = sorted(path for path in images_dir.iterdir() if path.is_file())
    local_by_name = {path.name: path for path in local_paths}

    def resolve_local_path(meta: dict[str, Any]) -> Path | None:
        file_name = str(meta.get("file") or "").strip()
        if file_name and file_name in local_by_name:
            return local_by_name[file_name]

        source_url = str(meta.get("source_url") or meta.get("url") or "").strip()
        source_name = Path(urlparse(source_url).path).name if source_url else ""
        if source_name:
            if source_name in local_by_name:
                return local_by_name[source_name]
            prefixed = next((path for path in local_paths if path.name.endswith(f"-{source_name}") or path.name == source_name), None)
            if prefixed is not None:
                return prefixed
        return None

    seen_paths: set[Path] = set()
    ordered: list[tuple[Path, dict[str, Any]]] = []
    for meta in image_meta:
        path = resolve_local_path(meta)
        if path is None or path in seen_paths:
            continue
        seen_paths.add(path)
        ordered.append((path, meta))

    if not ordered:
        ordered = [(path, {}) for path in local_paths]

    for path, meta in ordered:
        ref = _file_ref(path, "image")
        ref.update(
            {
                "file": path.name,
                "seq": meta.get("seq"),
                "width": meta.get("w"),
                "height": meta.get("h"),
                "source_url": meta.get("source_url") or meta.get("url"),
            }
        )
        refs.append(ref)
    return refs


def _file_ref(path: Path, asset_type: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "asset_type": asset_type,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _source_refs(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for report in reports:
        base = {
            "source": "jin10_external",
            "article_id": report["article_id"],
            "category_code": report["category_code"],
            "source_url": report["source_url"],
        }
        assets = [report["meta_json"], report["report_md"], *report["images"]]
        for asset in assets:
            refs.append({**base, **asset})
    return refs


def _build_daily_report_bundle(
    report: dict[str, Any],
    parsed_report: dict[str, Any] | None,
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_report_markdown = Path(report["report_md"]["path"]).read_text(encoding="utf-8")
    report_text = parsed_report["body_text"] if parsed_report and parsed_report.get("body_text") else raw_report_markdown
    document = SourceDocument(
        document_id=f"jin10-{report['date']}-{report['article_id']}",
        source="jin10_external",
        trade_date=report["date"],
        title=report["title"],
        category=report["category"],
        category_code=report["category_code"],
        source_url=report["source_url"],
        article_id=report["article_id"],
        external_report_dir=report["external_report_dir"],
        retrieved_at=report["retrieved_at"],
        markdown_asset=_asset_from_raw(report["report_md"]),
        meta_asset=_asset_from_raw(report["meta_json"]),
        image_assets=[_asset_from_raw(image) for image in report["images"]],
        report_text=report_text,
        source_refs=[ref for ref in source_refs if ref.get("article_id") == report["article_id"]],
    )
    parsed = build_parsed_document(document)
    facts = extract_report_facts(parsed)
    snapshot = build_daily_report_analysis_snapshot(parsed, facts)
    raw_article_text = report_text if str(report_text or "").strip() else raw_report_markdown
    raw_article = build_jin10_raw_article_report(
        document,
        article_markdown_override=raw_article_text,
        charts=_charts_for_raw_article(report=report, parsed_report=parsed_report),
    )
    visual = build_jin10_daily_analysis_report(snapshot)
    report_type = _report_type_for_raw_report(report)
    if report_type == "weekly":
        visual.family = "jin10_weekly_visual"
    visual.generated_from = {**visual.generated_from, "report_type": report_type}
    quality_audit = _build_report_quality_audit(
        report=report,
        parsed_report=parsed_report,
        raw_article=raw_article.to_dict(),
        visual=visual.to_dict(),
    )
    agent_analysis = build_jin10_agent_analysis_report_with_llm(raw_article, visual)
    visual_json = visual.to_dict()
    visual_json["report_type"] = report_type
    visual_json["quality_audit"] = quality_audit
    raw_article_json = raw_article.to_dict()
    raw_article_json["quality_audit"] = quality_audit
    agent_analysis_json = agent_analysis.to_dict()
    agent_analysis_json["quality_audit"] = quality_audit
    return {
        "trade_date": report["date"],
        "run_id": report["article_id"],
        "quality_audit": quality_audit,
        "raw_article_json": raw_article_json,
        "raw_article_markdown": render_jin10_raw_article_markdown(raw_article),
        "json": visual_json,
        "html": render_jin10_daily_html(visual),
        "agent_analysis_json": agent_analysis_json,
        "agent_analysis_markdown": render_jin10_agent_analysis_markdown(agent_analysis),
    }


def _build_report_quality_audit(
    *,
    report: dict[str, Any],
    parsed_report: dict[str, Any] | None,
    raw_article: dict[str, Any],
    visual: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[dict[str, str]] = []
    title = str(report.get("title") or "")
    external_dir = Path(str(report.get("external_report_dir") or ""))
    folder_date = external_dir.parents[1].name if len(external_dir.parents) >= 2 else ""
    report_date = str(report.get("date") or "")

    if folder_date and report_date and folder_date != report_date:
        reasons.append({"code": "date_mismatch", "message": f"folder_date={folder_date}, report_date={report_date}"})

    non_report_tokens = ("财料", "黄金头条", "投行金评")
    if any(token in title for token in non_report_tokens):
        reasons.append({"code": "non_daily_report_title", "message": f"title={title}"})

    market_prices = visual.get("market_prices") or []
    logic_chains = visual.get("logic_chains") or []
    core_conclusion = str(visual.get("core_conclusion") or "")
    article_context = (raw_article.get("generated_from") or {}).get("article_context") or {}
    key_sentences = article_context.get("key_sentences") or []
    level_snippets = article_context.get("level_snippets") or []
    chart_summaries = article_context.get("chart_summaries") or []
    parse_status = str((parsed_report or {}).get("vlm_status") or "")

    has_insufficient_conclusion = "证据仍不足" in core_conclusion or "证据不足" in core_conclusion
    has_only_placeholder_logic = all(str(item.get("label") or "") == "证据不足" for item in logic_chains if isinstance(item, dict))
    if has_insufficient_conclusion or (not market_prices and not key_sentences and not level_snippets and has_only_placeholder_logic):
        reasons.append({"code": "evidence_insufficient", "message": "no stable prices, key sentences, levels, or logic chain extracted"})

    if parse_status and parse_status not in {"success", "partial"}:
        reasons.append({"code": "parse_degraded", "message": f"vlm_status={parse_status}"})

    if chart_summaries and all("第" in str(item) and "报告图" in str(item) for item in chart_summaries):
        reasons.append({"code": "fallback_chart_only", "message": "only fallback page-image captions were available"})

    blocking_codes = {"date_mismatch", "non_daily_report_title"}
    status = "accepted"
    if any(reason["code"] in blocking_codes for reason in reasons):
        status = "rejected"
    elif reasons:
        status = "needs_review"

    return {
        "status": status,
        "reasons": reasons,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _report_type_for_raw_report(report: dict[str, Any]) -> str:
    category_code = str(report.get("category_code") or "")
    if category_code in JIN10_REPORT_TYPE_BY_CATEGORY:
        return JIN10_REPORT_TYPE_BY_CATEGORY[category_code]
    category = str(report.get("category") or "")
    title = str(report.get("title") or "")
    if "黄金周报" in category or "黄金周报" in title:
        return "weekly"
    explicit = str(report.get("report_type") or "").strip().lower()
    return explicit if explicit == "daily" else "daily"


def _jin10_agent_status(agent_report: dict[str, Any], generated_source: str) -> AgentStatus:
    unresolved = [str(item).strip() for item in agent_report.get("unresolved_items") or [] if str(item).strip()]
    if generated_source.endswith("fallback_after_llm_error"):
        return AgentStatus.PARTIAL
    if unresolved and not (len(unresolved) == 1 and "暂无新增未确认项" in unresolved[0]):
        return AgentStatus.PARTIAL
    return AgentStatus.SUCCESS


def _jin10_agent_bias(agent_report: dict[str, Any]) -> AgentBias:
    text = " ".join(
        [
            str(agent_report.get("one_line_conclusion") or ""),
            str(agent_report.get("final_summary") or ""),
            str((agent_report.get("market_stage") or {}).get("label") or ""),
        ]
    )
    positive = sum(word in text for word in ("反弹", "修复", "上行", "顺风", "强化", "突破", "看涨", "多头"))
    negative = sum(word in text for word in ("承压", "压制", "下行", "失守", "踩踏", "看跌", "空头"))
    if positive and negative:
        return AgentBias.MIXED
    if positive:
        return AgentBias.BULLISH
    if negative:
        return AgentBias.BEARISH
    return AgentBias.NEUTRAL


def _jin10_agent_confidence(
    agent_report: dict[str, Any],
    generated_by: str,
    status: AgentStatus,
) -> float:
    confidence = 0.72 if generated_by == "llm" else 0.64
    unresolved = [str(item).strip() for item in agent_report.get("unresolved_items") or [] if str(item).strip()]
    if status is AgentStatus.PARTIAL:
        confidence -= 0.10
    confidence -= min(len(unresolved) * 0.03, 0.12)
    return max(0.18, min(round(confidence, 2), 0.86))


def _jin10_agent_claims(agent_report: dict[str, Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    article_id = str(agent_report.get("article_id") or "unknown")
    source_refs = [dict(item) for item in agent_report.get("source_refs") or [] if isinstance(item, dict)]
    source_artifact_refs = list(agent_report.get("source_artifact_refs") or [])
    evidence_refs = [*source_refs, *[{"artifact_path": path} for path in source_artifact_refs]]

    def _append_claim(claim_id: str, text: str, claim_type: str) -> None:
        if not text.strip():
            return
        claims.append(
            {
                "claim_id": f"{article_id}:{claim_id}",
                "text": text.strip(),
                "claim_type": claim_type,
                "source_refs": source_refs,
                "evidence_refs": evidence_refs,
                "confidence": 0.7,
            }
        )

    _append_claim("one_line_conclusion", str(agent_report.get("one_line_conclusion") or ""), "market_view")
    stage = agent_report.get("market_stage") or {}
    _append_claim(
        "market_stage",
        f"{stage.get('label') or 'unavailable'}：{stage.get('reason') or ''}",
        "market_view",
    )
    for index, row in enumerate(agent_report.get("logic_chain") or [], start=1):
        _append_claim(f"logic_chain_{index}", str(row), "causal_inference")
    for index, row in enumerate(agent_report.get("risk_points") or [], start=1):
        _append_claim(f"risk_{index}", str(row), "risk_warning")
    for index, row in enumerate(agent_report.get("key_levels") or [], start=1):
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        value = str(row.get("value") or "").strip()
        _append_claim(f"key_level_{index}", f"{label}: {value}", "strategy_condition")
    return claims


def _latency_seconds(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value) / 1000.0, 3)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _asset_from_raw(raw: dict[str, Any]) -> SourceAssetRef:
    metadata = {key: raw[key] for key in ("file", "seq", "width", "height") if key in raw and raw[key] is not None}
    return SourceAssetRef(
        asset_type=raw["asset_type"],
        path=raw["path"],
        sha256=raw["sha256"],
        size_bytes=raw["size_bytes"],
        metadata=metadata,
    )


def _charts_from_parsed_figures(parsed_report: dict[str, Any]) -> list[dict[str, object]] | None:
    figures = parsed_report.get("figures") or []
    artifacts = parsed_report.get("artifacts") or {}
    vision_layout_pages = (artifacts.get("vision_layout") or {}).get("pages") or []
    vision_markdown_pages = (artifacts.get("vision_markdown") or {}).get("pages") or []
    vision_page_map = {
        int(page.get("page_no") or 0): page
        for page in (vision_layout_pages or vision_markdown_pages)
        if isinstance(page, dict)
    }
    if not figures:
        return None
    charts: list[dict[str, object]] = []
    for index, figure in enumerate(figures, start=1):
        title = str(figure.get("title") or f"图表 {index}")
        page_payload = vision_page_map.get(int(figure.get("page_no") or 0)) or {}
        page_markdown = str(page_payload.get("markdown") or "").strip()
        nearby_text = str(figure.get("nearby_text") or "").strip()
        layout_block_text = _layout_block_text_for_bbox(page_payload, figure.get("bbox") or [])
        charts.append(
            {
                "seq": index,
                "figure_id": figure.get("figure_id"),
                "page_no": figure.get("page_no"),
                "title": title,
                "image_path": figure.get("chart_image_path"),
                "caption": title,
                "bbox": figure.get("bbox"),
                "recognized_text": nearby_text or layout_block_text or (page_markdown[:500] if page_markdown else ""),
                "summary": _chart_summary_from_markdown(
                    title,
                    page_markdown or layout_block_text,
                    nearby_text=nearby_text or layout_block_text,
                ),
            }
        )
    return charts


def _layout_block_text_for_bbox(page_payload: dict[str, Any], bbox: list[Any]) -> str:
    if not isinstance(page_payload, dict) or not isinstance(bbox, list) or len(bbox) != 4:
        return ""
    blocks = page_payload.get("blocks") or []
    if not isinstance(blocks, list):
        return ""
    try:
        target = [int(float(value)) for value in bbox]
    except (TypeError, ValueError):
        return ""

    candidates: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_bbox = block.get("bbox")
        if not isinstance(block_bbox, list) or len(block_bbox) != 4:
            continue
        try:
            current = [int(float(value)) for value in block_bbox]
        except (TypeError, ValueError):
            continue
        if _bbox_overlap_ratio(current, target) < 0.25 and not _bbox_contains(current, target):
            continue
        text = str(block.get("text") or "").strip()
        if text:
            candidates.append(text)
    return " ".join(candidates[:3]).strip()


def _bbox_overlap_ratio(source_bbox: list[int], target_bbox: list[int]) -> float:
    sx1, sy1, sx2, sy2 = source_bbox
    tx1, ty1, tx2, ty2 = target_bbox
    ix1, iy1 = max(sx1, tx1), max(sy1, ty1)
    ix2, iy2 = min(sx2, tx2), min(sy2, ty2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    source_area = max(1, (sx2 - sx1) * (sy2 - sy1))
    return ((ix2 - ix1) * (iy2 - iy1)) / source_area


def _bbox_contains(source_bbox: list[int], target_bbox: list[int]) -> bool:
    sx1, sy1, sx2, sy2 = source_bbox
    tx1, ty1, tx2, ty2 = target_bbox
    return sx1 <= tx1 and sy1 <= ty1 and sx2 >= tx2 and sy2 >= ty2


def _charts_from_report_images(report: dict[str, Any]) -> list[dict[str, object]] | None:
    images = report.get("images") or []
    if not images:
        meta = json.loads(Path(report["meta_json"]["path"]).read_text(encoding="utf-8"))
        images = _meta_image_url_refs(meta.get("images", []))
        if not images:
            return None
    charts: list[dict[str, object]] = []
    for index, image in enumerate(images, start=1):
        path_value = str(image.get("path") or "")
        file_name = str(image.get("file") or Path(path_value).name or f"image-{index}")
        page_label = f"第{image.get('seq') or index}页报告图"
        charts.append(
            {
                "seq": image.get("seq") or index,
                "title": page_label,
                "image_path": path_value,
                "caption": page_label,
                "width": image.get("width"),
                "height": image.get("height"),
                "source_url": image.get("source_url"),
                "file_name": file_name,
            }
        )
    return charts


def _charts_for_raw_article(
    *,
    report: dict[str, Any],
    parsed_report: dict[str, Any] | None,
) -> list[dict[str, object]] | None:
    if parsed_report:
        parsed_charts = _charts_from_parsed_figures(parsed_report)
        if parsed_charts:
            return parsed_charts
    image_charts = _charts_from_report_images(report)
    if image_charts:
        return image_charts
    return None


def _chart_summary_from_markdown(title: str, markdown: str, *, nearby_text: str = "") -> str:
    if not markdown:
        return f"{title}：{nearby_text}".strip("：") if nearby_text else ""
    lines = []
    if nearby_text.strip():
        lines.append(nearby_text.strip())
    for line in markdown.splitlines():
        text = str(line).strip()
        if not text or text.startswith("![") or text.startswith("#"):
            continue
        lines.append(text.lstrip("- ").strip())
    if not lines:
        return ""
    unique: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    summary = "；".join(unique[:3]).strip()
    if title and title not in summary:
        return f"{title}：{summary}"
    return summary


def _copy_output_figures(
    artifacts: dict[str, Any] | None,
    *,
    parsed_base: Path,
    output_base: Path,
    allowed_paths: set[str] | None = None,
) -> None:
    figures = ((artifacts or {}).get("figures") or {}).get("figures") or []
    output_figures = output_base / "figures"
    if output_figures.exists():
        shutil.rmtree(output_figures)
    if not figures or allowed_paths == set():
        return
    output_figures.mkdir(parents=True, exist_ok=True)
    for figure in figures:
        relative_path = figure.get("chart_image_path")
        if not relative_path:
            continue
        if allowed_paths is not None and str(relative_path) not in allowed_paths:
            continue
        source = parsed_base / str(relative_path)
        if source.is_file():
            shutil.copy2(source, output_figures / source.name)


def _infer_category_code(category_name: str, folder_name: str) -> str | None:
    for code, names in JIN10_CATEGORY_ALIASES.items():
        if category_name in names or folder_name in names:
            return code
    return None


def _symbol(date: str, category: str | None) -> str:
    return f"jin10:{category or 'all'}:{date}"
