"""Read the latest registered research report without granting state authority."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from apps.api.services._storage import _PROJECT_ROOT, _try_db_session
from apps.api.services.research_trade_plan import project_research_trade_plan
from apps.api.services.research_identity import build_research_identity, project_research_levels
from apps.api.services.gold_research_topics import verified_report_topics
from database.models.analysis import AnalysisSnapshot, AgentOutput
from database.models.report import ReportItem
from database.models.task import TaskRun, TaskStatus

logger = logging.getLogger(__name__)


def _read_registered_json(path: str, root: Path, sha256: str | None = None) -> dict:
    from apps.runtime.storage_paths import project_artifact_path
    candidate = project_artifact_path(path, project_root=root)
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to((root / "storage").resolve()):
        raise ValueError("research artifact outside storage")
    data = resolved.read_bytes()
    if sha256 is not None and hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("research artifact hash mismatch")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("research artifact is not an object")
    return payload


def _project_report(db, report: ReportItem, root: Path) -> dict[str, Any]:
    if report.data_status not in {"live", "available", "partial"} or report.lifecycle_status in {"blocked", "failed", "draft", "archived"}:
        return {"status": "unavailable", "reason": "research_record_unavailable", "run_id": report.run_id}
    run = db.get(TaskRun, UUID(str(report.run_id)))
    if (run is None or run.status != TaskStatus.success or run.name != "premarket"
            or run.task_type != "premarket" or run.trade_date != report.trade_date.isoformat()):
        raise ValueError("research run not complete")
    snapshot = db.scalar(select(AnalysisSnapshot).where(
        AnalysisSnapshot.snapshot_id == report.snapshot_id,
        AnalysisSnapshot.run_id == report.run_id,
        AnalysisSnapshot.asset == "XAUUSD",
        AnalysisSnapshot.trade_date == report.trade_date,
    ))
    if snapshot is None or snapshot.status != "success" or run.snapshot_id != snapshot.snapshot_id:
        raise ValueError("research snapshot identity mismatch")
    payload = _read_registered_json(snapshot.artifact_path, root)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if payload != snapshot.payload or digest != snapshot.payload_sha256:
        raise ValueError("research snapshot payload mismatch")
    if payload.get("run_id") != report.run_id or payload.get("snapshot_id") != report.snapshot_id:
        raise ValueError("research payload identity mismatch")
    from apps.analysis.snapshots.input_validation import prepare_analysis_inputs, research_enabled, research_report_rejection_reasons
    validated_payload = prepare_analysis_inputs(payload)
    validation = validated_payload.get("input_validation") or {}
    if validation.get("can_analyze") is False:
        return {"status": "unavailable", "reason": "input_validation_blocked", "run_id": report.run_id,
                "snapshot_id": report.snapshot_id, "reason_codes": validation.get("reason_codes", [])}
    coordinator = db.scalar(select(AgentOutput).where(AgentOutput.run_id == report.run_id,
        AgentOutput.snapshot_id == report.snapshot_id, AgentOutput.agent_name == "coordinator_agent"))
    if research_enabled(payload):
        reasons = research_report_rejection_reasons(payload, coordinator.payload if coordinator else None)
        if reasons:
            return {"status": "unavailable", "reason": "research_generation_failed", "reason_codes": reasons,
                    "run_id": report.run_id, "snapshot_id": report.snapshot_id}
    artifacts = [a for a in report.artifacts if a.artifact_type == "structured_json"]
    if len(artifacts) != 1 or not artifacts[0].sha256:
        raise ValueError("registered research report missing or ambiguous")
    structured = _read_registered_json(artifacts[0].file_path, root, artifacts[0].sha256)
    version = structured.get("version") or {}
    metadata = artifacts[0].artifact_metadata or {}
    expected = {"run_id": report.run_id, "snapshot_id": report.snapshot_id}
    if any(version.get(k) != v or metadata.get(k) != v for k, v in expected.items()):
        raise ValueError("registered report identity mismatch")
    if version.get("trade_date") != report.trade_date.isoformat():
        raise ValueError("registered report date mismatch")
    # Facts become readable only after all snapshot and report checks above.
    # Narrative availability grants no additional strategy or state authority.
    facts = {
        "facts_status": "available",
        "macro": (validated_payload.get("macro") or {}).get("data"),
        "options": (validated_payload.get("options") or {}).get("data"),
        "source_refs": payload.get("source_refs") or [],
    }
    narrative = next((s.get("body") for s in structured.get("sections", [])
                      if isinstance(s, dict) and s.get("section_id") in {"model_research", "research_judgment"}), None)
    missing_narrative = {
        "status": "unavailable", "reason": "research_narrative_unavailable",
        "authority": "observation_only", "publish_allowed": False,
        "report_id": report.report_id, "run_id": report.run_id,
        "snapshot_id": report.snapshot_id, "trade_date": report.trade_date.isoformat(),
        "as_of": payload.get("snapshot_time"),
        **facts,
    }
    if not isinstance(narrative, str) or not narrative.strip():
        return missing_narrative
    workflow = payload.get("gold_workflow") or {}
    synthesis = (structured.get("research_synthesis") or {})
    outputs = version.get("source_agent_outputs") or []
    if any("rule_fallback" in (a.get("data_quality") or []) or a.get("research_synthesis_status") in {"rule_fallback", "failed", "blocked"} or
           (a.get("input_payload") or {}).get("research_synthesis", {}).get("status") in {"rule_fallback", "failed", "blocked"}
           for a in outputs) or synthesis.get("status") in {"rule_fallback", "failed", "blocked"}:
        return {"status": "unavailable", "reason": "research_generation_failed", "run_id": report.run_id}
    if not research_enabled(payload) and not any(
            a.get("status") == "success" and a.get("research_synthesis_status") == "success" for a in outputs):
        return {"status": "unavailable", "reason": "research_generation_unverified", "run_id": report.run_id}

    # Headings alone are not research. Check for prose without changing the
    # registered body: headings, Markdown and trailing risks remain readable.
    prose = re.sub(r"(?m)^[^\n]+\n[ \t]*(?:=+|-+)[ \t]*$", "", narrative)
    if not any(line.strip() and not re.fullmatch(r"#{1,6}(?:\s+.*)?", line.strip())
               for line in prose.splitlines()):
        return missing_narrative
    agent = next((a for a in version.get("source_agent_outputs", [])
                  if a.get("agent_name") == "report_observation_projection"), {})
    coordinator_payload = coordinator.payload if coordinator and isinstance(coordinator.payload, dict) else {}
    coordinator_input = coordinator_payload.get("input_payload")
    coordinator_synthesis = coordinator_input.get("research_synthesis") if isinstance(coordinator_input, dict) else None
    topic_analysis = verified_report_topics(
        synthesis=coordinator_synthesis, narrative=narrative,
        identity={"report_id": report.report_id, "run_id": report.run_id, "snapshot_id": report.snapshot_id,
                  "trade_date": report.trade_date.isoformat(), "as_of": payload.get("snapshot_time")})
    identity = build_research_identity(
        report_id=report.report_id, run_id=report.run_id, snapshot_id=report.snapshot_id,
        trade_date=report.trade_date.isoformat(), snapshot=payload, generated_at=report.created_at)
    return {
        "status": "available", "authority": "observation_only", "publish_allowed": False,
        "report_id": report.report_id, "run_id": report.run_id, "snapshot_id": report.snapshot_id,
        "trade_date": report.trade_date.isoformat(), "as_of": payload.get("snapshot_time"),
        "summary": narrative, "bias": agent.get("bias", "neutral"),
        "research_identity": identity,
        "topic_analysis": topic_analysis,
        "final_trade_plan": project_research_trade_plan(
            narrative=narrative, snapshot=payload, report_id=report.report_id,
            run_id=report.run_id, snapshot_id=report.snapshot_id,
            trade_date=report.trade_date.isoformat()),
        "confidence": agent.get("confidence"),
        "risks": [], "invalid_conditions": [],
        **facts,
        "price_anchor": workflow.get("price_anchor") or {},
        "key_levels": project_research_levels(workflow.get("key_levels"), identity),
        "execution": {k: (workflow.get("execution") or {}).get(k)
                      for k in ("flat", "long", "short", "event_rule")},
        "state": {k: (workflow.get("state") or {}).get(k)
                  for k in ("accepted_state", "candidate_state", "transition_status")},
    }


def get_dashboard_research_context(*, include_historical: bool = False) -> dict[str, Any] | None:
    """Fail closed on the latest item; never quietly replace a broken report with an older one."""
    try:
        db = _try_db_session()
        if db is None:
            return {"status": "unavailable", "reason": "research_database_unavailable"}
        with db:
            report = db.scalar(select(ReportItem).where(
                ReportItem.family == "observation_report_markdown", ReportItem.asset == "XAUUSD",
            ).order_by(ReportItem.trade_date.desc(), ReportItem.created_at.desc()).limit(1))
            latest = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.asset == "XAUUSD").order_by(
                AnalysisSnapshot.trade_date.desc(), AnalysisSnapshot.created_at.desc()).limit(1))
            if latest is not None and (latest.payload or {}).get("input_validation"):
                validation = latest.payload["input_validation"]
                newer = report is None or latest.trade_date > report.trade_date or (
                    latest.trade_date == report.trade_date and latest.run_id != report.run_id and
                    latest.created_at.replace(tzinfo=None) >= report.created_at.replace(tzinfo=None))
                if newer:
                    result = {"status": "unavailable", "reason": "input_validation_blocked" if not validation.get("can_analyze") else "research_not_completed",
                        "run_id": latest.run_id, "snapshot_id": latest.snapshot_id, "reason_codes": validation.get("reason_codes", [])}
                    # Explicit reading context only. The current result stays unavailable;
                    # broken registrations are never skipped in favour of an older report.
                    if include_historical and report is not None:
                        try:
                            historical = _project_report(db, report, _PROJECT_ROOT)
                            if historical.get("status") == "available":
                                result["historical_research"] = {**historical, "historical_only": True}
                        except (ValueError, TypeError, OSError, KeyError):
                            pass
                    return result
            if report is None:
                return None
            try:
                return _project_report(db, report, _PROJECT_ROOT)
            except (ValueError, TypeError, OSError, KeyError):
                return {"status": "unavailable", "reason": "research_identity_or_artifact_unverified",
                        "run_id": report.run_id, "authority": "observation_only"}
    except Exception:
        logger.warning("Dashboard research projection unavailable", extra={"degraded": True})
        return {"status": "unavailable", "reason": "research_projection_unavailable"}
