"""Bounded cleanup for archived research outputs with explicit quality failures.

This module deliberately has no scheduler and creates no tables.  It rewrites
derived output rows to small tombstones, records durable file-delete intents in
the existing execution timeline, and only then unlinks verified output files
and explicitly allowlisted legacy report-render bodies below ``storage_root``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Text, and_, cast, func, literal, or_, select, text
from sqlalchemy.dialects.postgresql import JSONPATH

from apps.runtime.storage_paths import remap_storage_path
from database.models.analysis import AgentOutput, AnalysisSnapshot, FinalAnalysisResult
from database.models.execution import ExecutionEvent, RunArtifact
from database.models.report import ReportArtifact, ReportItem
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep


SCHEMA_VERSION = 1
FAILED_SYNTHESIS_STATUSES = frozenset({"failed", "blocked", "rejected", "invalid", "error", "rule_fallback"})
FAILED_MACRO_REVIEW_STATUSES = frozenset({"needs_revision", "failed", "blocked", "rejected"})
FAILED_REPORT_STATUSES = frozenset({"failed", "blocked", "rejected", "invalid", "error"})
STANDALONE_AGENT_STATUSES = frozenset({"failed", "unavailable"})
ACTIVE_TASK_STATUSES = frozenset({TaskStatus.pending, TaskStatus.running})
COMPOSITE_REPORT_TYPES = frozenset({"final_report", "strategy_card", "observation_report", "observation_strategy_card"})
DERIVED_RUN_ARTIFACT_TYPES = frozenset(
    {
        "analysis_md",
        "final_report",
        "strategy_card",
        "observation_report",
        "observation_strategy_card",
        "report_render",
        "structured_json",
    }
)
DERIVED_TASK_STEP_NAMES = frozenset(
    {
        "final_report",
        "strategy_card",
        "observation_report",
        "observation_strategy_card",
        "research_generation",
        "report_render",
        "render_report",
    }
)
PENDING_EVENT = "output_cleanup_file_pending"
DELETED_EVENT = "output_cleanup_file_deleted"
BLOCKED_EVENT = "output_cleanup_file_blocked"
SUMMARY_EVENT = "output_cleanup_summary"
MAX_LIMIT = 1000


class OutputRetentionError(RuntimeError):
    """Stable, non-secret error code returned by the cleanup boundary."""


@dataclass
class _FileCandidate:
    path: str
    run_ids: set[str] = field(default_factory=set)
    expected_hashes: set[str] = field(default_factory=set)
    owners: list[str] = field(default_factory=list)


@dataclass
class _Selection:
    run_reasons: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    report_reasons: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    standalone_agent_reasons: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    report_items: dict[str, ReportItem] = field(default_factory=dict)
    report_artifacts: dict[str, ReportArtifact] = field(default_factory=dict)
    final_results: dict[str, FinalAnalysisResult] = field(default_factory=dict)
    agent_outputs: dict[str, AgentOutput] = field(default_factory=dict)
    run_artifacts: dict[str, RunArtifact] = field(default_factory=dict)
    task_steps: dict[str, TaskStep] = field(default_factory=dict)
    files: dict[str, _FileCandidate] = field(default_factory=dict)
    blocked_runs: dict[str, str] = field(default_factory=dict)


@dataclass
class _ReferenceIndex:
    paths: set[PurePosixPath] = field(default_factory=set)
    identities: set[tuple[int, int]] = field(default_factory=set)
    hashes: set[str] = field(default_factory=set)


def _norm_status(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _payload_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _iso(instant: datetime) -> str:
    return instant.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _now(value: datetime | None) -> datetime:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise OutputRetentionError("OUTPUT_CLEANUP_NOW_INVALID")
    return instant.astimezone(UTC)


def _bounded_run_ids(run_ids: Iterable[str] | None) -> list[str] | None:
    if run_ids is None:
        return None
    result = sorted({str(value).strip() for value in run_ids if str(value).strip()})
    if not result:
        raise OutputRetentionError("OUTPUT_CLEANUP_RUN_IDS_REQUIRED")
    if len(result) > MAX_LIMIT:
        raise OutputRetentionError("OUTPUT_CLEANUP_RUN_IDS_LIMIT")
    return result


def _bounded_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise OutputRetentionError("OUTPUT_CLEANUP_LIMIT_INVALID")
    return limit


def _storage_root(value: str | Path) -> Path:
    root = Path(os.path.abspath(Path(value).expanduser()))
    try:
        current = Path(root.anchor)
        for part in root.parts[1:]:
            current = current / part
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise OutputRetentionError("OUTPUT_CLEANUP_STORAGE_ROOT_INVALID")
        root_info = os.lstat(root)
    except OutputRetentionError:
        raise
    except OSError as exc:
        raise OutputRetentionError("OUTPUT_CLEANUP_STORAGE_ROOT_INVALID") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise OutputRetentionError("OUTPUT_CLEANUP_STORAGE_ROOT_INVALID")
    outputs = root / "outputs"
    if os.path.lexists(outputs):
        info = os.lstat(outputs)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise OutputRetentionError("OUTPUT_CLEANUP_OUTPUTS_ROOT_INVALID")
    return root


def _cleanup_marker(
    *, payload: Any, reasons: Iterable[str], instant: datetime, run_id: str | None, snapshot_id: str | None
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "purged",
        "reason_codes": sorted({str(reason) for reason in reasons if reason}),
        "purged_at": _iso(instant),
        "original_payload_sha256": _payload_hash(payload),
        "run_id": run_id,
        "snapshot_id": snapshot_id,
    }


def _existing_marker(value: Any) -> dict[str, Any] | None:
    payload = _mapping(value)
    marker = _mapping(payload.get("output_cleanup"))
    return marker if _norm_status(marker.get("status")) == "purged" else None


def _failure_reasons(payload: Any) -> set[str]:
    body = _mapping(payload)
    reasons: set[str] = set()
    input_payload = _mapping(body.get("input_payload"))
    synthesis = _mapping(input_payload.get("research_synthesis"))
    synthesis_status = _norm_status(synthesis.get("status"))
    if synthesis_status in FAILED_SYNTHESIS_STATUSES:
        reasons.add(f"RESEARCH_SYNTHESIS_{synthesis_status.upper()}")
    macro_status = _norm_status(_mapping(synthesis.get("macro_review")).get("status"))
    if macro_status in FAILED_MACRO_REVIEW_STATUSES:
        reasons.add(f"MACRO_REVIEW_{macro_status.upper()}")
    direct_synthesis_status = _norm_status(body.get("synthesis_status"))
    if direct_synthesis_status in FAILED_SYNTHESIS_STATUSES:
        reasons.add(f"SYNTHESIS_STATUS_{direct_synthesis_status.upper()}")
    for validation in (
        _mapping(body.get("input_validation")),
        _mapping(input_payload.get("input_validation")),
    ):
        if validation.get("can_analyze") is False:
            reasons.add("INPUT_VALIDATION_BLOCKED")
    marker = _existing_marker(body)
    if marker is not None:
        reasons.update(str(item) for item in marker.get("reason_codes") or [] if item)
    return reasons


def _projected_failure_reasons(
    *,
    research_synthesis: Any = None,
    synthesis_status: Any = None,
    input_validation: Any = None,
    nested_input_validation: Any = None,
    output_cleanup: Any = None,
) -> set[str]:
    return _failure_reasons(
        {
            "input_payload": {
                "research_synthesis": _mapping(research_synthesis),
                "input_validation": _mapping(nested_input_validation),
            },
            "synthesis_status": synthesis_status,
            "input_validation": _mapping(input_validation),
            "output_cleanup": _mapping(output_cleanup),
        }
    )


def _composite_reasons(reasons: Iterable[str]) -> set[str]:
    return {reason for reason in reasons if not str(reason).startswith("AGENT_OUTPUT_")}


def _is_composite_report_values(report_id: Any, report_type: Any, family: Any) -> bool:
    values = {
        _norm_status(report_type),
        _norm_status(family),
        _norm_status(str(report_id).split(":", 1)[0]),
    }
    if any("gold_policy" in value for value in values):
        return False
    return bool(values & COMPOSITE_REPORT_TYPES) or any(
        value in {"final_report_markdown", "observation_report_markdown"} for value in values
    )


def _is_derived_task_step(value: Any) -> bool:
    name = _norm_status(value)
    return name in DERIVED_TASK_STEP_NAMES or any(
        token in name for token in ("final_report", "strategy_card", "research_generation", "report_render")
    )


def _agent_has_body(row: AgentOutput) -> bool:
    if _existing_marker(row.payload) is not None:
        return False
    return bool(
        row.summary
        or row.key_findings
        or row.risk_points
        or row.watchlist
        or row.invalid_conditions
        or (_mapping(row.payload) and set(_mapping(row.payload)) != {"output_cleanup"})
    )


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _producer_active(session, run_id: str) -> bool:
    parsed = _uuid(run_id)
    if parsed is None:
        return False
    row = session.get(TaskRun, parsed)
    if row is not None and row.status in ACTIVE_TASK_STATUSES:
        return True
    # A finished failed run can retain never-started pending steps after an
    # interrupted legacy workflow. They cannot still produce output. Running
    # steps remain protected even when their parent's status is inconsistent.
    finished_parent = row is not None and row.status not in ACTIVE_TASK_STATUSES and row.ended_at is not None
    active_step = TaskStep.status.in_((StepStatus.pending, StepStatus.running))
    if finished_parent:
        active_step = or_(
            TaskStep.status == StepStatus.running,
            and_(TaskStep.status == StepStatus.pending, TaskStep.started_at.is_not(None)),
        )
    return (
        session.scalar(
            select(TaskStep.id)
            .where(
                TaskStep.task_run_id == parsed,
                active_step,
            )
            .limit(1)
        )
        is not None
    )


def _candidate_path(selection: _Selection, path: Any, *, run_id: str, owner: str, sha256: Any = None) -> None:
    if not isinstance(path, str) or not path.strip():
        return
    if path.strip().lower().startswith("purged://"):
        return
    item = selection.files.setdefault(path, _FileCandidate(path=path))
    item.run_ids.add(run_id)
    item.owners.append(owner)
    digest = _norm_status(sha256)
    if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
        item.expected_hashes.add(digest)


def _path_values(value: Any, key: str = "") -> Iterable[str]:
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            yield from _path_values(child, str(child_key))
    elif isinstance(value, (list, tuple, set)):
        for child in value:
            yield from _path_values(child, key)
    elif isinstance(value, str) and (
        "path" in key.lower()
        or key.lower() in {"file", "file_path", "output_ref", "source_ref", "artifact_ref"}
        or "/outputs/" in value.replace("\\", "/")
        or value.replace("\\", "/").startswith("outputs/")
        or "analysis/gold_mainlines/" in value.replace("\\", "/")
    ):
        yield value


def _json_path(column, *parts: str):
    expression = column
    for part in parts:
        expression = expression[part]
    return expression


def _agent_output_files(value: Any, field: str = "") -> Iterable[tuple[str, str | None]]:
    """Walk emitted output references once; inputs and evidence are upstream."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            key = str(key).lower()
            if key in {"input_payload", "source_refs", "input_snapshot_ids", "prompt_messages", "evidence_refs"}:
                continue
            if isinstance(child, str) and ("path" in key or key in {"output_ref", "artifact_ref"}):
                normalized = child.replace("\\", "/")
                if "/outputs/" not in normalized and not normalized.startswith("outputs/"):
                    continue
                digest = value.get(f"{key.removesuffix('_path')}_sha256") or value.get("sha256")
                verified = (
                    digest.lower() if isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest) else None
                )
                yield child, verified
            elif isinstance(child, (Mapping, list, tuple)):
                yield from _agent_output_files(child, key)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _agent_output_files(child, field)
    elif isinstance(value, str) and ("path" in field or field in {"artifact_refs", "output_refs", "outputs"}):
        normalized = value.replace("\\", "/")
        if "/outputs/" in normalized or normalized.startswith("outputs/"):
            # String lists have no path-specific registered digest. They remain
            # blocked unless another selected registration supplies that hash.
            yield value, None


def _stream_mappings(session, statement):
    return session.execute(statement.execution_options(yield_per=200)).mappings()


def _select(session, *, requested_run_ids: list[str] | None, limit: int) -> _Selection:
    requested = set(requested_run_ids) if requested_run_ids is not None else None
    selection = _Selection()
    agent_rows: list[dict[str, Any]] = []
    agent_stmt = select(
        AgentOutput.id.label("id"),
        AgentOutput.run_id.label("run_id"),
        AgentOutput.agent_name.label("agent_name"),
        AgentOutput.module.label("module"),
        AgentOutput.status.label("status"),
        _json_path(AgentOutput.payload, "input_payload", "research_synthesis").label("research_synthesis"),
        _json_path(AgentOutput.payload, "synthesis_status").label("synthesis_status"),
        _json_path(AgentOutput.payload, "input_validation").label("input_validation"),
        _json_path(AgentOutput.payload, "input_payload", "input_validation").label("nested_input_validation"),
        _json_path(AgentOutput.payload, "output_cleanup").label("output_cleanup"),
    ).order_by(AgentOutput.run_id, AgentOutput.id)
    if requested is not None:
        agent_stmt = agent_stmt.where(AgentOutput.run_id.in_(requested))
    for projected in _stream_mappings(session, agent_stmt):
        row = dict(projected)
        agent_rows.append(row)
        run_id = str(row["run_id"])
        reasons = _projected_failure_reasons(
            research_synthesis=row["research_synthesis"],
            synthesis_status=row["synthesis_status"],
            input_validation=row["input_validation"],
            nested_input_validation=row["nested_input_validation"],
            output_cleanup=row["output_cleanup"],
        )
        composite_reasons = _composite_reasons(reasons)
        if composite_reasons and (
            _norm_status(row["agent_name"]) in {"coordinator", "coordinator_agent", "synthesis_agent"}
            or _norm_status(row["module"]) in {"coordinator", "research_synthesis", "synthesis"}
            or "INPUT_VALIDATION_BLOCKED" in composite_reasons
        ):
            selection.run_reasons[run_id].update(composite_reasons)
        if _norm_status(row["status"]) in STANDALONE_AGENT_STATUSES:
            selection.standalone_agent_reasons[str(row["id"])].add(
                f"AGENT_OUTPUT_{_norm_status(row['status']).upper()}"
            )

    final_stmt = select(
        FinalAnalysisResult.id.label("id"),
        FinalAnalysisResult.run_id.label("run_id"),
        _json_path(FinalAnalysisResult.payload, "input_payload", "research_synthesis").label("research_synthesis"),
        _json_path(FinalAnalysisResult.payload, "synthesis_status").label("synthesis_status"),
        _json_path(FinalAnalysisResult.payload, "input_validation").label("input_validation"),
        _json_path(FinalAnalysisResult.payload, "input_payload", "input_validation").label("nested_input_validation"),
        _json_path(FinalAnalysisResult.payload, "output_cleanup").label("output_cleanup"),
    ).order_by(FinalAnalysisResult.run_id)
    if requested is not None:
        final_stmt = final_stmt.where(FinalAnalysisResult.run_id.in_(requested))
    for row in _stream_mappings(session, final_stmt):
        reasons = _projected_failure_reasons(
            research_synthesis=row["research_synthesis"],
            synthesis_status=row["synthesis_status"],
            input_validation=row["input_validation"],
            nested_input_validation=row["nested_input_validation"],
            output_cleanup=row["output_cleanup"],
        )
        if reasons:
            selection.run_reasons[str(row["run_id"])].update(reasons)

    snapshot_stmt = select(
        AnalysisSnapshot.run_id.label("run_id"),
        _json_path(AnalysisSnapshot.payload, "input_validation").label("input_validation"),
        _json_path(AnalysisSnapshot.payload, "output_cleanup").label("output_cleanup"),
    ).order_by(AnalysisSnapshot.run_id)
    if requested is not None:
        snapshot_stmt = snapshot_stmt.where(AnalysisSnapshot.run_id.in_(requested))
    for row in _stream_mappings(session, snapshot_stmt):
        reasons = _projected_failure_reasons(
            input_validation=row["input_validation"], output_cleanup=row["output_cleanup"]
        )
        if reasons:
            selection.run_reasons[str(row["run_id"])].update(reasons)

    report_rows: list[dict[str, Any]] = []
    report_stmt = select(
        ReportItem.report_id.label("report_id"),
        ReportItem.run_id.label("run_id"),
        ReportItem.report_type.label("report_type"),
        ReportItem.family.label("family"),
        ReportItem.data_status.label("data_status"),
        ReportItem.lifecycle_status.label("lifecycle_status"),
        _json_path(ReportItem.report_metadata, "input_payload", "research_synthesis").label("research_synthesis"),
        _json_path(ReportItem.report_metadata, "synthesis_status").label("synthesis_status"),
        _json_path(ReportItem.report_metadata, "input_validation").label("input_validation"),
        _json_path(ReportItem.report_metadata, "input_payload", "input_validation").label("nested_input_validation"),
        _json_path(ReportItem.report_metadata, "output_cleanup").label("output_cleanup"),
    ).order_by(ReportItem.run_id, ReportItem.report_id)
    if requested is not None:
        report_stmt = report_stmt.where(ReportItem.run_id.in_(requested))
    for projected in _stream_mappings(session, report_stmt):
        row = dict(projected)
        report_rows.append(row)
        run_id = str(row["run_id"] or "")
        statuses = {_norm_status(row["data_status"]), _norm_status(row["lifecycle_status"])}
        failures = statuses & FAILED_REPORT_STATUSES
        if failures:
            reasons = {f"REPORT_STATUS_{value.upper()}" for value in failures}
            selection.report_reasons[str(row["report_id"])].update(reasons)
            if _is_composite_report_values(row["report_id"], row["report_type"], row["family"]):
                selection.run_reasons[run_id].update(reasons)
        metadata_reasons = _projected_failure_reasons(
            research_synthesis=row["research_synthesis"],
            synthesis_status=row["synthesis_status"],
            input_validation=row["input_validation"],
            nested_input_validation=row["nested_input_validation"],
            output_cleanup=row["output_cleanup"],
        )
        if metadata_reasons:
            if _is_composite_report_values(row["report_id"], row["report_type"], row["family"]):
                selection.run_reasons[run_id].update(metadata_reasons)
            else:
                selection.report_reasons[str(row["report_id"])].update(metadata_reasons)

    report_runs = {
        str(row["run_id"]) for row in report_rows if str(row["report_id"]) in selection.report_reasons and row["run_id"]
    }
    standalone_runs = {str(row["run_id"]) for row in agent_rows if str(row["id"]) in selection.standalone_agent_reasons}
    run_order = sorted(set(selection.run_reasons) | report_runs | standalone_runs)
    allowed_runs = set(run_order[:limit])
    invalid_runs = set(selection.run_reasons) & allowed_runs
    selection.run_reasons = defaultdict(set, {run_id: selection.run_reasons[run_id] for run_id in sorted(invalid_runs)})
    selection.report_reasons = defaultdict(
        set,
        {
            report_id: reasons
            for report_id, reasons in selection.report_reasons.items()
            if str(next((row["run_id"] for row in report_rows if row["report_id"] == report_id), "")) in allowed_runs
        },
    )
    selection.standalone_agent_reasons = defaultdict(
        set,
        {
            row_id: reasons
            for row_id, reasons in selection.standalone_agent_reasons.items()
            if str(next((row["run_id"] for row in agent_rows if str(row["id"]) == row_id), "")) in allowed_runs
        },
    )

    for run_id in sorted(allowed_runs):
        if _producer_active(session, run_id):
            selection.blocked_runs[run_id] = "ACTIVE_PRODUCER"

    candidate_report_ids = set(selection.report_reasons)
    for row in report_rows:
        run_id = str(row["run_id"] or "")
        if run_id in invalid_runs and _is_composite_report_values(row["report_id"], row["report_type"], row["family"]):
            candidate_report_ids.add(str(row["report_id"]))
    if candidate_report_ids:
        for row in session.scalars(select(ReportItem).where(ReportItem.report_id.in_(sorted(candidate_report_ids)))):
            selection.report_items[row.report_id] = row

    if candidate_report_ids:
        for row in session.scalars(
            select(ReportArtifact).where(ReportArtifact.report_id.in_(sorted(candidate_report_ids)))
        ):
            selection.report_artifacts[str(row.artifact_id)] = row
            report = selection.report_items.get(row.report_id)
            if report is not None and str(report.run_id) not in selection.blocked_runs:
                _candidate_path(
                    selection,
                    row.file_path,
                    run_id=str(report.run_id),
                    owner=f"report_artifact:{row.artifact_id}",
                    sha256=row.sha256,
                )

    parsed_run_ids = [_uuid(run_id) for run_id in invalid_runs]
    parsed_run_ids = [run_id for run_id in parsed_run_ids if run_id is not None]
    if invalid_runs:
        for row in session.scalars(
            select(FinalAnalysisResult).where(FinalAnalysisResult.run_id.in_(sorted(invalid_runs)))
        ):
            run_id = str(row.run_id)
            selection.final_results[str(row.id)] = row
            if run_id in selection.blocked_runs:
                continue
            _candidate_path(
                selection,
                row.final_report_path,
                run_id=run_id,
                owner=f"final:{row.id}:report",
                sha256=row.final_report_sha256,
            )
            _candidate_path(
                selection,
                row.strategy_card_json_path,
                run_id=run_id,
                owner=f"final:{row.id}:strategy_json",
                sha256=row.strategy_card_sha256,
            )
            _candidate_path(
                selection,
                row.strategy_card_md_path,
                run_id=run_id,
                owner=f"final:{row.id}:strategy_md",
            )
            _candidate_path(
                selection,
                row.run_summary_path,
                run_id=run_id,
                owner=f"final:{row.id}:summary",
            )

    selected_agent_ids = {
        str(row["id"])
        for row in agent_rows
        if (
            str(row["run_id"]) in invalid_runs
            and (
                _norm_status(row["agent_name"])
                in {"coordinator", "coordinator_agent", "synthesis_agent", "report_render_agent"}
                or _norm_status(row["module"]) in {"coordinator", "research_synthesis", "synthesis", "report_render"}
            )
        )
        or str(row["id"]) in selection.standalone_agent_reasons
    }
    if selected_agent_ids:
        statement = (
            select(AgentOutput).where(AgentOutput.id.in_(sorted(selected_agent_ids))).execution_options(yield_per=1)
        )
        for row in session.scalars(statement):
            run_id = str(row.run_id)
            row._retention_cleanup_marker = _existing_marker(row.payload)
            standalone = str(row.id) in selection.standalone_agent_reasons
            if standalone and not _agent_has_body(row) and not _existing_marker(row.payload):
                selection.standalone_agent_reasons.pop(str(row.id), None)
                if run_id not in selection.run_reasons:
                    continue
            selection.agent_outputs[str(row.id)] = row
            if run_id not in selection.blocked_runs:
                for path, digest in _agent_output_files(row.payload):
                    _candidate_path(
                        selection,
                        path,
                        run_id=run_id,
                        owner=f"agent_output:{row.id}",
                        sha256=digest,
                    )
            # Only retain identity/columns in the selection. Rehydrate one
            # rejected body at a time when hashing and replacing it in apply.
            session.expire(row, ["payload"])

    if parsed_run_ids:
        for row in session.scalars(
            select(RunArtifact).where(RunArtifact.run_id.in_(parsed_run_ids)).execution_options(yield_per=1)
        ):
            if not _derived_run_artifact(row):
                continue
            run_id = str(row.run_id)
            selection.run_artifacts[str(row.artifact_id)] = row
            if run_id not in selection.blocked_runs:
                _candidate_path(
                    selection,
                    row.file_path,
                    run_id=run_id,
                    owner=f"run_artifact:{row.artifact_id}",
                    sha256=row.sha256,
                )
        for row in session.scalars(
            select(TaskStep).where(
                TaskStep.task_run_id.in_(parsed_run_ids),
                or_(
                    TaskStep.name.in_(sorted(DERIVED_TASK_STEP_NAMES)),
                    TaskStep.name.contains("final_report"),
                    TaskStep.name.contains("strategy_card"),
                    TaskStep.name.contains("research_generation"),
                    TaskStep.name.contains("report_render"),
                ),
            )
        ):
            if _is_derived_task_step(row.name):
                selection.task_steps[str(row.id)] = row
    return selection


def _derived_run_artifact(row: RunArtifact) -> bool:
    if _existing_marker(row.artifact_metadata) or _existing_marker(row.metadata_json):
        # Purged URIs have lost their original family path. Their rejected
        # owner must remain excluded from the valid reference graph on retry.
        return True
    path = str(row.file_path or "").replace("\\", "/").lower()
    metadata = _mapping(row.artifact_metadata) or _mapping(row.metadata_json)
    family_values = [
        str(metadata.get(key) or "").lower()
        for key in ("family", "report_type", "artifact_type", "bundle_type")
    ]
    if "gold_policy" in path or any("gold_policy" in value for value in family_values):
        return False
    artifact_type = _norm_status(row.artifact_type)
    if artifact_type not in DERIVED_RUN_ARTIFACT_TYPES:
        return False
    return (
        "report_render_output" in path
        or any(metadata.get(key) == "report_render_agent" for key in ("agent_name", "agent_id", "module"))
        or any(
            token in path
            for token in (
                "/final_report/",
                "/strategy_card/",
                "/observation_report/",
                "/observation_strategy_card/",
                "/report_render/",
            )
        )
        or artifact_type
        in {
            "final_report",
            "strategy_card",
            "observation_report",
            "observation_strategy_card",
            "report_render",
        }
    )


def _legacy_render_output(relative: PurePosixPath) -> bool:
    parts = relative.parts
    if (
        len(parts) != 6
        or parts[:2] != ("analysis", "gold_mainlines")
        or parts[4:] != ("agent_outputs", "report_render_output.json")
        or _uuid(parts[3]) is None
    ):
        return False
    try:
        return date.fromisoformat(parts[2]).isoformat() == parts[2]
    except ValueError:
        return False


def _relative_output_path(root: Path, value: str) -> PurePosixPath:
    normalized = value.strip().replace("\\", "/")
    try:
        supplied = remap_storage_path(normalized, storage_root=root)
    except ValueError as exc:
        raise OutputRetentionError("FILE_PATH_INVALID") from exc
    if supplied.is_absolute():
        try:
            relative = supplied.relative_to(root)
        except ValueError as exc:
            raise OutputRetentionError("FILE_OUTSIDE_STORAGE_ROOT") from exc
    else:
        parts = PurePosixPath(normalized).parts
        if len(parts) > 1 and parts[0] in {root.name, "storage"} and parts[1] in {"outputs", "analysis"}:
            parts = parts[1:]
        relative = Path(*parts)
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise OutputRetentionError("FILE_PATH_INVALID")
    if pure.parts[0] != "outputs" and not _legacy_render_output(pure):
        raise OutputRetentionError("FILE_OUTSIDE_OUTPUTS")
    if any("gold_policy" in part.lower() for part in pure.parts):
        raise OutputRetentionError("GOLD_POLICY_BUNDLE_PROTECTED")
    return pure


def _file_identity(root: Path, relative: PurePosixPath) -> tuple[str, int, tuple[int, int, int, int]]:
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError as exc:
            raise OutputRetentionError("FILE_NOT_FOUND") from exc
        if stat.S_ISLNK(info.st_mode):
            raise OutputRetentionError("FILE_SYMLINK_BLOCKED")
        if not stat.S_ISDIR(info.st_mode):
            raise OutputRetentionError("FILE_PATH_INVALID")
    full = root / relative.as_posix()
    try:
        info = os.lstat(full)
    except FileNotFoundError as exc:
        raise OutputRetentionError("FILE_NOT_FOUND") from exc
    if stat.S_ISLNK(info.st_mode):
        raise OutputRetentionError("FILE_SYMLINK_BLOCKED")
    if not stat.S_ISREG(info.st_mode):
        raise OutputRetentionError("FILE_NOT_REGULAR")
    if info.st_nlink != 1:
        raise OutputRetentionError("FILE_HARDLINK_BLOCKED")
    digest = hashlib.sha256()
    with full.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        read_info = os.fstat(handle.fileno())
    identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if identity != (read_info.st_dev, read_info.st_ino, read_info.st_size, read_info.st_mtime_ns):
        raise OutputRetentionError("FILE_CHANGED_DURING_READ")
    return digest.hexdigest(), info.st_size, identity


def _hash_values(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _hash_values(child)
    elif isinstance(value, (list, tuple, set)):
        for child in value:
            yield from _hash_values(child)
    elif isinstance(value, str):
        normalized = value.strip().lower()
        if len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized):
            yield normalized
            return
        if normalized[:1] in {"{", "["}:
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return
            yield from _hash_values(parsed)


def _reference_match(columns: Iterable[Any], tokens: set[str]):
    clauses = [cast(column, Text).contains(token, autoescape=True) for column in columns for token in sorted(tokens)]
    return or_(*clauses) if clauses else None


def _add_reference_value(
    index: _ReferenceIndex,
    value: Any,
    *,
    key: str,
    root: Path,
    candidate_hashes: set[str],
) -> None:
    parsed = value
    if isinstance(value, str) and value.strip()[:1] in {"{", "["}:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = value
    for digest in _hash_values(parsed):
        if digest in candidate_hashes:
            index.hashes.add(digest)
    for path in _path_values(parsed, key):
        try:
            relative = _relative_output_path(root, path)
        except OutputRetentionError:
            continue
        index.paths.add(relative)
        try:
            resolved = (root / relative.as_posix()).resolve(strict=True)
            if not resolved.is_relative_to(root):
                continue
            _relative_output_path(root, str(resolved))
            info = resolved.stat()
        except (OSError, RuntimeError, ValueError, OutputRetentionError):
            continue
        if stat.S_ISREG(info.st_mode):
            index.identities.add((info.st_dev, info.st_ino))


def _scan_reference_columns(
    session,
    index: _ReferenceIndex,
    *,
    id_column,
    columns: list[Any],
    root: Path,
    path_tokens: set[str],
    candidate_hashes: set[str],
    excluded_ids: set[Any] | None = None,
    scan_all: bool = False,
) -> None:
    if not scan_all and not path_tokens and not candidate_hashes:
        return
    pg_projection = session.get_bind().dialect.name == "postgresql" and not scan_all
    projected_columns = columns
    if pg_projection:
        # Walk binary JSON in PostgreSQL and transfer only possible path/hash
        # strings. This preserves arbitrary nested references without loading
        # multi-megabyte snapshots/prompts or matching each token against them.
        relative_roots = "|".join(re.escape(value) for value in sorted({"outputs", "analysis", "storage", root.name}))
        path_prefix = rf"^\s*(?:[/\\]|[A-Za-z]:[/\\]|(?:\.\.?|{relative_roots})[/\\])"
        hash_pattern = r"^\s*[a-fA-F0-9]{64}\s*$"
        encoded_json_prefix = r"^\s*[\[{]"
        predicate = (
            '$.** ? (@.type() == "string" && '
            f'((@ like_regex {json.dumps(path_prefix)} flag "i" && '
            '@ like_regex "outputs|gold_mainlines" flag "i") '
            f'|| @ like_regex {json.dumps(hash_pattern)} '
            f'|| @ like_regex {json.dumps(encoded_json_prefix)}))'
        )
        path = cast(literal(predicate), JSONPATH)
        projected_columns = [
            func.jsonb_path_query_array(column, path) if isinstance(column.type, JSON) else column for column in columns
        ]
    base = select(id_column, *projected_columns)
    if excluded_ids:
        base = base.where(id_column.not_in(excluded_ids))
    token_batches: list[set[str] | None]
    if scan_all or pg_projection:
        token_batches = [None]
    else:
        tokens = sorted(path_tokens | candidate_hashes)
        if not tokens:
            return
        # Keep each OR tree comfortably below SQLite's expression-depth limit
        # while retaining bounded SQL on PostgreSQL for large explicit run sets.
        batch_size = max(1, 200 // max(1, len(columns)))
        token_batches = [set(tokens[offset : offset + batch_size]) for offset in range(0, len(tokens), batch_size)]
    for token_batch in token_batches:
        statement = base
        if token_batch is not None:
            matcher = _reference_match(columns, token_batch)
            if matcher is None:
                continue
            statement = statement.where(matcher)
        for row in session.execute(statement.execution_options(yield_per=200 if scan_all else 1)):
            for column, value in zip(columns, row[1:], strict=True):
                if value is not None:
                    _add_reference_value(
                        index,
                        value,
                        key=str(getattr(column, "key", "")),
                        root=root,
                        candidate_hashes=candidate_hashes,
                    )


def _reference_index(
    session,
    selection: _Selection,
    root: Path,
    *,
    path_tokens: set[str],
    candidate_hashes: set[str],
) -> _ReferenceIndex:
    index = _ReferenceIndex()
    selected_reports = {
        report_id
        for report_id, row in selection.report_items.items()
        if str(row.run_id or "") not in selection.blocked_runs or _existing_marker(row.report_metadata)
    }
    selected_artifacts = {
        artifact_id
        for artifact_id, row in selection.report_artifacts.items()
        if (row.report_id in selected_reports or _existing_marker(row.artifact_metadata))
    }
    selected_agents = {
        row_id
        for row_id, row in selection.agent_outputs.items()
        if str(row.run_id) not in selection.blocked_runs or getattr(row, "_retention_cleanup_marker", None)
    }
    selected_finals = {
        row_id
        for row_id, row in selection.final_results.items()
        if str(row.run_id) not in selection.blocked_runs or _existing_marker(row.payload)
    }
    selected_run_artifacts = {
        _uuid(row_id) or row_id
        for row_id, row in selection.run_artifacts.items()
        if (
            str(row.run_id) not in selection.blocked_runs
            or _existing_marker(row.artifact_metadata)
            or _existing_marker(row.metadata_json)
        )
    }
    selected_steps = {
        _uuid(row_id) or row_id
        for row_id, row in selection.task_steps.items()
        if str(row.task_run_id) not in selection.blocked_runs or _existing_marker(row.output_json)
    }

    # Direct scalar paths and hashes are cheap to project in full.  This also
    # catches a differently-spelled path to the same inode (hard-link alias).
    _scan_reference_columns(
        session,
        index,
        id_column=ReportArtifact.artifact_id,
        columns=[ReportArtifact.file_path, ReportArtifact.sha256],
        root=root,
        path_tokens=path_tokens,
        candidate_hashes=candidate_hashes,
        excluded_ids=selected_artifacts,
        scan_all=True,
    )
    _scan_reference_columns(
        session,
        index,
        id_column=FinalAnalysisResult.id,
        columns=[
            FinalAnalysisResult.final_report_path,
            FinalAnalysisResult.strategy_card_json_path,
            FinalAnalysisResult.strategy_card_md_path,
            FinalAnalysisResult.run_summary_path,
            FinalAnalysisResult.final_report_sha256,
            FinalAnalysisResult.strategy_card_sha256,
        ],
        root=root,
        path_tokens=path_tokens,
        candidate_hashes=candidate_hashes,
        excluded_ids=selected_finals,
        scan_all=True,
    )
    _scan_reference_columns(
        session,
        index,
        id_column=RunArtifact.artifact_id,
        columns=[RunArtifact.file_path, RunArtifact.sha256, RunArtifact.structured_payload_sha256],
        root=root,
        path_tokens=path_tokens,
        candidate_hashes=candidate_hashes,
        excluded_ids=selected_run_artifacts,
        scan_all=True,
    )
    _scan_reference_columns(
        session,
        index,
        id_column=AnalysisSnapshot.id,
        columns=[AnalysisSnapshot.artifact_path, AnalysisSnapshot.payload_sha256],
        root=root,
        path_tokens=path_tokens,
        candidate_hashes=candidate_hashes,
        scan_all=True,
    )
    _scan_reference_columns(
        session,
        index,
        id_column=TaskStep.id,
        columns=[TaskStep.output_ref],
        root=root,
        path_tokens=path_tokens,
        candidate_hashes=candidate_hashes,
        excluded_ids=selected_steps,
        scan_all=True,
    )

    # JSON/text bodies are filtered in the database by the concrete candidate
    # path/hash, so unrelated multi-megabyte snapshots never enter the ORM or
    # Python process.
    specs = [
        (
            ReportArtifact.artifact_id,
            [ReportArtifact.artifact_metadata, ReportArtifact.source_refs, ReportArtifact.metadata_text],
            selected_artifacts,
        ),
        (ReportItem.report_id, [ReportItem.report_metadata, ReportItem.source_refs], selected_reports),
        (
            FinalAnalysisResult.id,
            [
                FinalAnalysisResult.payload,
                FinalAnalysisResult.strategy_card,
                FinalAnalysisResult.run_summaries,
                FinalAnalysisResult.source_refs,
                FinalAnalysisResult.input_snapshot_ids,
            ],
            selected_finals,
        ),
        (
            RunArtifact.artifact_id,
            [
                RunArtifact.source_refs_data,
                RunArtifact.artifact_metadata,
                RunArtifact.source_refs,
                RunArtifact.metadata_json,
                RunArtifact.structured_payload,
            ],
            selected_run_artifacts,
        ),
        (AgentOutput.id, [AgentOutput.payload, AgentOutput.source_refs], selected_agents),
        (
            AnalysisSnapshot.id,
            [AnalysisSnapshot.payload, AnalysisSnapshot.source_refs, AnalysisSnapshot.input_snapshot_ids],
            set(),
        ),
    ]
    for id_column, columns, excluded in specs:
        _scan_reference_columns(
            session,
            index,
            id_column=id_column,
            columns=columns,
            root=root,
            path_tokens=path_tokens,
            candidate_hashes=candidate_hashes,
            excluded_ids=excluded,
        )

    # Candidate output fields are intentionally excluded, but their input and
    # source lineage still protects any referenced artifact.
    _scan_reference_columns(
        session,
        index,
        id_column=TaskStep.id,
        columns=[TaskStep.input_refs, TaskStep.source_refs, TaskStep.input_json],
        root=root,
        path_tokens=path_tokens,
        candidate_hashes=candidate_hashes,
    )
    _scan_reference_columns(
        session,
        index,
        id_column=TaskStep.id,
        columns=[
            TaskStep.output_refs,
            TaskStep.artifact_refs,
            TaskStep.output_json,
            TaskStep.error_json,
            TaskStep.error,
        ],
        root=root,
        path_tokens=path_tokens,
        candidate_hashes=candidate_hashes,
        excluded_ids=selected_steps,
    )
    return index


def _file_preview(
    session,
    selection: _Selection,
    root: Path,
    *,
    reference_index: _ReferenceIndex | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, tuple[PurePosixPath, _FileCandidate, list[str]]] = {}
    result: list[dict[str, Any]] = []
    for value, candidate in sorted(selection.files.items()):
        try:
            relative = _relative_output_path(root, value)
            if _legacy_render_output(relative) and relative.parts[3] not in candidate.run_ids:
                raise OutputRetentionError("LEGACY_OUTPUT_RUN_MISMATCH")
        except OutputRetentionError as exc:
            result.append(
                {
                    "file_path": value,
                    "path_aliases": [value],
                    "run_ids": sorted(candidate.run_ids),
                    "owners": sorted(candidate.owners),
                    "eligible": False,
                    "reason": str(exc),
                }
            )
            continue
        key = relative.as_posix()
        if key not in grouped:
            grouped[key] = (relative, _FileCandidate(path=value), [])
        _, merged, aliases = grouped[key]
        merged.run_ids.update(candidate.run_ids)
        merged.expected_hashes.update(candidate.expected_hashes)
        merged.owners.extend(candidate.owners)
        aliases.append(value)

    prepared: list[tuple[dict[str, Any], PurePosixPath, tuple[int, int] | None]] = []
    path_tokens: set[str] = set()
    candidate_hashes: set[str] = set()
    for key, (relative, candidate, aliases) in sorted(grouped.items()):
        item: dict[str, Any] = {
            "file_path": aliases[0],
            "path_aliases": sorted(set(aliases)),
            "run_ids": sorted(candidate.run_ids),
            "owners": sorted(candidate.owners),
            "eligible": False,
            "reason": None,
            "relative_path": key,
        }
        identity_key: tuple[int, int] | None = None
        try:
            digest, byte_size, identity = _file_identity(root, relative)
            identity_key = identity[:2]
            item["sha256"] = digest
            item["byte_size"] = byte_size
            if len(candidate.expected_hashes) > 1:
                raise OutputRetentionError("REGISTERED_HASH_CONFLICT")
            if not candidate.expected_hashes:
                raise OutputRetentionError("FILE_HASH_UNVERIFIED")
            if digest not in candidate.expected_hashes:
                raise OutputRetentionError("FILE_HASH_CHANGED")
            item["eligible"] = True
            path_tokens.add(relative.as_posix())
            path_tokens.update(alias.replace("\\", "/") for alias in aliases)
            candidate_hashes.update(candidate.expected_hashes)
        except OutputRetentionError as exc:
            item["reason"] = str(exc)
        prepared.append((item, relative, identity_key))
        result.append(item)

    if reference_index is None:
        reference_index = _reference_index(
            session,
            selection,
            root,
            path_tokens=path_tokens,
            candidate_hashes=candidate_hashes,
        )
    for item, relative, identity_key in prepared:
        if not item["eligible"]:
            continue
        if (
            relative in reference_index.paths
            or identity_key in reference_index.identities
            or item.get("sha256") in reference_index.hashes
        ):
            item["eligible"] = False
            item["reason"] = "FILE_SHARED_REFERENCE"
    return result


def _pending_file_preview(
    session,
    selection: _Selection,
    root: Path,
    item: Mapping[str, Any],
    *,
    reference_index: _ReferenceIndex | None = None,
) -> dict[str, Any]:
    """Re-run path, reference, and hash checks for one durable intent."""
    candidate_selection = _Selection(
        run_reasons=selection.run_reasons,
        report_reasons=selection.report_reasons,
        standalone_agent_reasons=selection.standalone_agent_reasons,
        report_items=selection.report_items,
        report_artifacts=selection.report_artifacts,
        final_results=selection.final_results,
        agent_outputs=selection.agent_outputs,
        run_artifacts=selection.run_artifacts,
        task_steps=selection.task_steps,
        blocked_runs=selection.blocked_runs,
    )
    relative = _relative_output_path(root, str(item.get("relative_path") or ""))
    digest = _norm_status(item.get("sha256"))
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise OutputRetentionError("FILE_HASH_UNVERIFIED")
    candidate = _FileCandidate(path=relative.as_posix())
    candidate.run_ids.update(str(value) for value in item.get("target_run_ids") or [])
    candidate.expected_hashes.add(digest)
    candidate.owners.append(f"pending:{item.get('operation_id')}")
    candidate_selection.files = {relative.as_posix(): candidate}
    result = _file_preview(session, candidate_selection, root, reference_index=reference_index)
    if len(result) != 1:
        raise OutputRetentionError("PENDING_FILE_IDENTITY_INVALID")
    return result[0]


def _selection_result(session, selection: _Selection, root: Path, *, limit: int) -> dict[str, Any]:
    files = _file_preview(session, selection, root)
    return {
        "storage_root": str(root),
        "limit": limit,
        "candidate_run_count": len(selection.run_reasons),
        "candidate_report_count": len(selection.report_items),
        "candidate_agent_output_count": len(selection.agent_outputs),
        "candidate_file_count": len(files),
        "eligible_file_count": sum(bool(item["eligible"]) for item in files),
        "blocked_file_count": sum(not bool(item["eligible"]) for item in files),
        "runs": [
            {
                "run_id": run_id,
                "reason_codes": sorted(reasons),
                "eligible": run_id not in selection.blocked_runs,
                "reason": selection.blocked_runs.get(run_id),
            }
            for run_id, reasons in sorted(selection.run_reasons.items())
        ],
        "standalone_agent_output_ids": sorted(selection.standalone_agent_reasons),
        "files": files,
    }


def preview_unqualified_outputs(session, storage_root, run_ids=None, limit=100):
    """Read-only preview of explicitly failed archived derived outputs."""
    bounded_ids = _bounded_run_ids(run_ids)
    bounded_limit = _bounded_limit(limit)
    root = _storage_root(storage_root)
    selection = _select(session, requested_run_ids=bounded_ids, limit=bounded_limit)
    result = _selection_result(session, selection, root, limit=bounded_limit)
    result["dry_run"] = True
    return result


def _tombstone_report_item(row: ReportItem, reasons: set[str], instant: datetime) -> None:
    existing = _existing_marker(row.report_metadata)
    marker = existing or _cleanup_marker(
        payload=row.report_metadata,
        reasons=reasons,
        instant=instant,
        run_id=str(row.run_id) if row.run_id else None,
        snapshot_id=row.snapshot_id,
    )
    row.report_metadata = {"output_cleanup": marker}
    row.data_status = "unavailable"
    row.lifecycle_status = "purged"


def _tombstone_report_artifact(
    row: ReportArtifact, reasons: set[str], instant: datetime, run_id: str | None, snapshot_id: str | None
) -> None:
    existing = _existing_marker(row.artifact_metadata)
    payload = {"metadata": row.artifact_metadata, "metadata_text": row.metadata_text}
    marker = existing or _cleanup_marker(
        payload=payload, reasons=reasons, instant=instant, run_id=run_id, snapshot_id=snapshot_id
    )
    row.status = "purged"
    row.file_path = f"purged://report-artifact/{row.artifact_id}"
    row.artifact_metadata = {"output_cleanup": marker}
    row.metadata_text = None


def _tombstone_final(row: FinalAnalysisResult, reasons: set[str], instant: datetime) -> None:
    existing = _existing_marker(row.payload)
    marker = existing or _cleanup_marker(
        payload=row.payload,
        reasons=reasons,
        instant=instant,
        run_id=str(row.run_id),
        snapshot_id=row.snapshot_id,
    )
    tombstone = {
        "status": "blocked",
        "publish_allowed": False,
        "run_id": str(row.run_id),
        "snapshot_id": row.snapshot_id,
        "asset": row.asset,
        "trade_date": row.trade_date.isoformat() if row.trade_date else None,
        "output_cleanup": marker,
    }
    row.final_bias = "unavailable"
    row.confidence = 0.0
    row.market_state = "unavailable"
    row.scenario_summary = ""
    row.is_trade_instruction = False
    row.source_agent_outputs = []
    row.risk_points = []
    row.watchlist = []
    row.invalid_conditions = []
    row.strategy_card = None
    row.run_summaries = {"output_cleanup": marker}
    row.payload = tombstone
    row.final_report_path = None
    row.strategy_card_json_path = None
    row.strategy_card_md_path = None
    row.run_summary_path = None
    row.final_report_sha256 = None
    row.strategy_card_sha256 = None
    row.payload_sha256 = _payload_hash(tombstone)


def _tombstone_agent(row: AgentOutput, reasons: set[str], instant: datetime) -> None:
    existing = _existing_marker(row.payload)
    marker = existing or _cleanup_marker(
        payload=row.payload,
        reasons=reasons,
        instant=instant,
        run_id=str(row.run_id),
        snapshot_id=row.snapshot_id,
    )
    payload = {"output_cleanup": marker}
    row.status = "failed" if _norm_status(row.status) == "failed" else "unavailable"
    row.bias = "unavailable"
    row.confidence = 0.0
    row.key_findings = []
    row.risk_points = []
    row.watchlist = []
    row.invalid_conditions = []
    row.summary = ""
    row.payload = payload
    row.payload_sha256 = _payload_hash(payload)


def _tombstone_run_artifact(row: RunArtifact, reasons: set[str], instant: datetime) -> None:
    existing = _existing_marker(row.artifact_metadata) or _existing_marker(row.metadata_json)
    marker = existing or _cleanup_marker(
        payload={
            "structured_payload": row.structured_payload,
            "artifact_metadata": row.artifact_metadata,
            "metadata_json": row.metadata_json,
        },
        reasons=reasons,
        instant=instant,
        run_id=str(row.run_id),
        snapshot_id=_mapping(row.artifact_metadata).get("snapshot_id"),
    )
    metadata = {"output_cleanup": marker}
    row.file_path = f"purged://run-artifact/{row.artifact_id}"
    row.artifact_metadata = metadata
    row.metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    row.structured_payload = None
    row.structured_payload_sha256 = None
    row.structured_status = "purged"
    row.structured_error = "OUTPUT_PURGED"


def _tombstone_task_step(row: TaskStep, reasons: set[str], instant: datetime) -> None:
    original = {
        "output_json": row.output_json,
        "output_refs": row.output_refs,
        "artifact_refs": row.artifact_refs,
        "output_ref": row.output_ref,
        "error_json": row.error_json,
        "error": row.error,
        "blocked_reason": row.blocked_reason,
    }
    existing = _existing_marker(row.output_json)
    marker = existing or _cleanup_marker(
        payload=original,
        reasons=reasons,
        instant=instant,
        run_id=str(row.task_run_id),
        snapshot_id=None,
    )
    marker_json = json.dumps({"output_cleanup": marker}, ensure_ascii=False, sort_keys=True)
    row.output_json = marker_json
    row.output_refs = marker_json
    row.artifact_refs = marker_json
    row.output_ref = f"purged://task-step/{row.id}"
    if row.error_json is not None:
        row.error_json = marker_json
    if row.error is not None:
        row.error = "OUTPUT_PURGED"
    if row.blocked_reason is not None:
        row.blocked_reason = "OUTPUT_PURGED"


def _identity_source(session, run_id: str, selection: _Selection) -> dict[str, Any]:
    finals = [row for row in selection.final_results.values() if str(row.run_id) == run_id]
    agents = [row for row in selection.agent_outputs.values() if str(row.run_id) == run_id]
    snapshot = session.execute(
        select(
            AnalysisSnapshot.asset,
            AnalysisSnapshot.trade_date,
            AnalysisSnapshot.snapshot_id,
            AnalysisSnapshot.created_at,
            AnalysisSnapshot.source_refs,
        )
        .where(AnalysisSnapshot.run_id == run_id)
        .order_by(AnalysisSnapshot.created_at.asc())
        .limit(1)
    ).first()
    task_id = _uuid(run_id)
    task = session.get(TaskRun, task_id) if task_id is not None else None
    source = finals[0] if finals else agents[0] if agents else snapshot
    trade_date = getattr(source, "trade_date", None) or getattr(task, "trade_date", None)
    if isinstance(trade_date, str):
        try:
            trade_date = date.fromisoformat(trade_date[:10])
        except ValueError:
            trade_date = None
    return {
        "asset": getattr(source, "asset", None) or "XAUUSD",
        "trade_date": trade_date,
        "snapshot_id": getattr(source, "snapshot_id", None) or getattr(task, "snapshot_id", None),
        "created_at": getattr(source, "created_at", None) or getattr(task, "created_at", None),
        "source_refs": list(getattr(source, "source_refs", None) or []),
    }


def _ensure_final_report_tombstone(
    session, run_id: str, reasons: set[str], instant: datetime, selection: _Selection
) -> None:
    report_id = f"final_report:{run_id}"
    if session.get(ReportItem, report_id) is not None:
        return
    identity = _identity_source(session, run_id, selection)
    marker = _cleanup_marker(
        payload={"run_id": run_id, "snapshot_id": identity["snapshot_id"]},
        reasons=reasons,
        instant=instant,
        run_id=run_id,
        snapshot_id=identity["snapshot_id"],
    )
    row = ReportItem(
        report_id=report_id,
        family="final_report_markdown",
        report_type="final_report",
        title=f"{identity['asset']} 历史研究（正文已清理）",
        asset=identity["asset"],
        trade_date=identity["trade_date"],
        run_id=run_id,
        snapshot_id=identity["snapshot_id"],
        data_status="unavailable",
        lifecycle_status="purged",
        source_refs=identity["source_refs"],
        report_metadata={"output_cleanup": marker},
    )
    if identity["created_at"] is not None:
        row.created_at = identity["created_at"]
        row.updated_at = identity["created_at"]
    session.add(row)


def _completed_operations(session) -> set[str]:
    result: set[str] = set()
    for payload in session.scalars(
        select(ExecutionEvent.payload)
        .where(ExecutionEvent.event_type == DELETED_EVENT)
        .execution_options(yield_per=200)
    ):
        operation_id = _mapping(payload).get("operation_id")
        if operation_id:
            result.add(str(operation_id))
    return result


def _pending_operations(session, requested_runs: set[str]) -> list[dict[str, Any]]:
    completed = _completed_operations(session)
    result: list[dict[str, Any]] = []
    for raw_payload in session.scalars(
        select(ExecutionEvent.payload)
        .where(ExecutionEvent.event_type == PENDING_EVENT)
        .order_by(ExecutionEvent.created_at)
        .execution_options(yield_per=200)
    ):
        payload = _mapping(raw_payload)
        operation_id = str(payload.get("operation_id") or "")
        target_runs = {str(value) for value in payload.get("target_run_ids") or []}
        if operation_id and operation_id not in completed and target_runs and target_runs <= requested_runs:
            result.append(payload)
    return result


def _record_event(
    session, *, audit_run_id: UUID, audit_step_id: UUID, event_type: str, payload: Mapping[str, Any], instant: datetime
) -> None:
    session.add(
        ExecutionEvent(
            run_id=audit_run_id,
            task_id=audit_step_id,
            event_type=event_type,
            payload=json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str),
            created_at=instant,
        )
    )


def _safe_unlink(root: Path, relative: PurePosixPath, expected_hash: str, expected_size: int) -> None:
    digest, byte_size, expected_identity = _file_identity(root, relative)
    if digest != expected_hash or byte_size != expected_size:
        raise OutputRetentionError("FILE_CHANGED_BEFORE_UNLINK")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        parent_fd = os.open(root, flags)
    except OSError as exc:
        raise OutputRetentionError("FILE_UNLINK_FAILED") from exc
    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(part, flags, dir_fd=parent_fd)
            except OSError as exc:
                raise OutputRetentionError("FILE_CHANGED_BEFORE_UNLINK") from exc
            os.close(parent_fd)
            parent_fd = next_fd
        try:
            current = os.stat(relative.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise OutputRetentionError("FILE_CHANGED_BEFORE_UNLINK") from exc
        identity = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
        if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or identity != expected_identity:
            raise OutputRetentionError("FILE_CHANGED_BEFORE_UNLINK")
        try:
            os.unlink(relative.name, dir_fd=parent_fd)
        except OSError as exc:
            raise OutputRetentionError("FILE_UNLINK_FAILED") from exc
    finally:
        os.close(parent_fd)


def _audit_rows(session, instant: datetime) -> tuple[TaskRun, TaskStep]:
    run = TaskRun(
        id=uuid4(),
        name="unqualified-output-cleanup",
        task_type="output_retention",
        status=TaskStatus.running,
        current_stage="output_cleanup",
        started_at=instant,
    )
    step = TaskStep(
        id=uuid4(),
        task_run_id=run.id,
        name="prune_unqualified_outputs",
        stage="output_cleanup",
        task_kind="output_retention",
        status=StepStatus.running,
        started_at=instant,
    )
    session.add(run)
    session.flush([run])
    session.add(step)
    return run, step


def _acquire_cleanup_locks(session) -> None:
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        if not session.in_transaction():
            session.execute(text("BEGIN IMMEDIATE"))
        return
    if dialect == "postgresql":
        session.execute(
            text(
                "LOCK TABLE task_runs, task_steps, execution_events, run_artifacts, "
                "analysis_snapshots, agent_outputs, final_analysis_results, "
                "report_items, report_artifacts IN SHARE ROW EXCLUSIVE MODE"
            )
        )


def _finish_failed_audit(session, run_id: UUID, step_id: UUID, instant: datetime) -> None:
    run = session.get(TaskRun, run_id)
    step = session.get(TaskStep, step_id)
    if run is not None:
        run.status = TaskStatus.failed
        run.current_stage = "failed"
        run.ended_at = instant
        run.error_summary = "OUTPUT_CLEANUP_INTERRUPTED"
    if step is not None:
        step.status = StepStatus.failed
        step.finished_at = instant
        step.error_type = "output_cleanup_interrupted"
        step.error = "OUTPUT_CLEANUP_INTERRUPTED"
    session.commit()


def _pending_reference_index(
    session,
    selection: _Selection,
    root: Path,
    pending: Iterable[Mapping[str, Any]],
) -> _ReferenceIndex:
    path_tokens: set[str] = set()
    candidate_hashes: set[str] = set()
    for item in pending:
        raw_path = str(item.get("relative_path") or "")
        if raw_path:
            path_tokens.add(raw_path.replace("\\", "/"))
        digest = _norm_status(item.get("sha256"))
        if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
            candidate_hashes.add(digest)
    return _reference_index(
        session,
        selection,
        root,
        path_tokens=path_tokens,
        candidate_hashes=candidate_hashes,
    )


def apply_unqualified_outputs(session_factory, storage_root, run_ids, now=None, *, limit=100):
    """Apply cleanup for explicit ``run_ids`` and recover their pending unlinks."""
    bounded_ids = _bounded_run_ids(run_ids)
    if bounded_ids is None:
        raise OutputRetentionError("OUTPUT_CLEANUP_RUN_IDS_REQUIRED")
    bounded_limit = _bounded_limit(limit)
    if len(bounded_ids) > bounded_limit:
        raise OutputRetentionError("OUTPUT_CLEANUP_RUN_IDS_LIMIT")
    instant = _now(now)
    root = _storage_root(storage_root)
    requested = set(bounded_ids)
    result: dict[str, Any] = {
        "dry_run": False,
        "storage_root": str(root),
        "requested_run_ids": bounded_ids,
        "tombstoned_run_count": 0,
        "tombstoned_report_count": 0,
        "tombstoned_agent_output_count": 0,
        "pending_file_count": 0,
        "deleted_file_count": 0,
        "blocked_file_count": 0,
        "reconciled_file_count": 0,
        "deleted": [],
        "blocked": [],
    }
    with session_factory() as session:
        audit_run, audit_step = _audit_rows(session, instant)
        session.flush()
        audit_run_id = audit_run.id
        audit_step_id = audit_step.id
        session.commit()
        result["task_run_id"] = str(audit_run_id)
        result["task_step_id"] = str(audit_step_id)
        try:
            # Freeze producers and all reference-bearing tables while selecting,
            # writing tombstones, and recording durable delete intents.
            _acquire_cleanup_locks(session)
            selection = _select(session, requested_run_ids=bounded_ids, limit=bounded_limit)
            preview = _selection_result(session, selection, root, limit=bounded_limit)
            result["preview"] = preview

            for run_id, reason in sorted(selection.blocked_runs.items()):
                result["blocked"].append({"run_id": run_id, "reason": reason})
                result["blocked_file_count"] += 1

            for report_id, row in selection.report_items.items():
                run_id = str(row.run_id or "")
                if run_id in selection.blocked_runs:
                    continue
                reasons = selection.run_reasons.get(run_id) or selection.report_reasons.get(report_id) or set()
                _tombstone_report_item(row, reasons, instant)
                result["tombstoned_report_count"] += 1
            for row in selection.report_artifacts.values():
                report = selection.report_items.get(row.report_id)
                run_id = str(report.run_id or "") if report is not None else ""
                if run_id in selection.blocked_runs:
                    continue
                reasons = selection.run_reasons.get(run_id) or selection.report_reasons.get(row.report_id) or set()
                _tombstone_report_artifact(
                    row,
                    reasons,
                    instant,
                    run_id or None,
                    report.snapshot_id if report is not None else None,
                )
            for row in selection.final_results.values():
                run_id = str(row.run_id)
                if run_id not in selection.blocked_runs:
                    _tombstone_final(row, selection.run_reasons[run_id], instant)
            for row_id, row in selection.agent_outputs.items():
                run_id = str(row.run_id)
                if run_id in selection.blocked_runs:
                    continue
                reasons = selection.run_reasons.get(run_id) or selection.standalone_agent_reasons.get(row_id) or set()
                _tombstone_agent(row, reasons, instant)
                # Release old large JSON values from ORM attribute history
                # within this transaction; the commit boundary stays unchanged.
                session.flush()
                result["tombstoned_agent_output_count"] += 1
            for row in selection.run_artifacts.values():
                run_id = str(row.run_id)
                if run_id not in selection.blocked_runs:
                    _tombstone_run_artifact(row, selection.run_reasons[run_id], instant)
            for row in selection.task_steps.values():
                run_id = str(row.task_run_id)
                if run_id not in selection.blocked_runs:
                    _tombstone_task_step(row, selection.run_reasons[run_id], instant)
            for run_id, reasons in selection.run_reasons.items():
                if run_id not in selection.blocked_runs:
                    _ensure_final_report_tombstone(session, run_id, reasons, instant, selection)
                    result["tombstoned_run_count"] += 1

            existing_pending = _pending_operations(session, requested)
            pending_keys = {
                (str(item.get("storage_root") or ""), str(item.get("relative_path") or "")) for item in existing_pending
            }
            for item in preview["files"]:
                if not item["eligible"]:
                    result["blocked"].append(
                        {
                            "file_path": item["file_path"],
                            "reason": item["reason"],
                            "run_ids": item["run_ids"],
                        }
                    )
                    result["blocked_file_count"] += 1
                    continue
                if any(run_id in selection.blocked_runs for run_id in item["run_ids"]):
                    continue
                pending_key = (str(root), item["relative_path"])
                if pending_key in pending_keys:
                    continue
                pending = {
                    "schema_version": SCHEMA_VERSION,
                    "operation_id": str(uuid4()),
                    "status": "pending",
                    "storage_root": str(root),
                    "target_run_ids": item["run_ids"],
                    "relative_path": item["relative_path"],
                    "sha256": item["sha256"],
                    "byte_size": item["byte_size"],
                    "recorded_at": _iso(instant),
                }
                _record_event(
                    session,
                    audit_run_id=audit_run_id,
                    audit_step_id=audit_step_id,
                    event_type=PENDING_EVENT,
                    payload=pending,
                    instant=instant,
                )
                pending_keys.add(pending_key)

            # Tombstones and all new file intents are durable before any unlink.
            session.commit()

            # Freeze the same producer/reference graph for the whole file phase,
            # build one reference index, and append all outcomes in one commit.
            _acquire_cleanup_locks(session)
            refreshed = _select(session, requested_run_ids=bounded_ids, limit=bounded_limit)
            pending = _pending_operations(session, requested)
            result["pending_file_count"] = len(pending)
            reference_index = _pending_reference_index(session, refreshed, root, pending)

            for item in pending:
                event_payload = dict(item)
                event_payload["completed_at"] = _iso(instant)
                relative: PurePosixPath | None = None
                try:
                    if str(item.get("storage_root") or "") != str(root):
                        raise OutputRetentionError("PENDING_STORAGE_ROOT_MISMATCH")
                    target_runs = {str(value) for value in item.get("target_run_ids") or []}
                    if not target_runs or not target_runs <= requested:
                        raise OutputRetentionError("PENDING_TARGET_INVALID")
                    qualified_runs = set(refreshed.run_reasons)
                    qualified_runs.update(str(row.run_id) for row in refreshed.report_items.values())
                    qualified_runs.update(str(row.run_id) for row in refreshed.agent_outputs.values())
                    if not target_runs <= qualified_runs:
                        raise OutputRetentionError("PENDING_TARGET_NOT_QUALIFIED")
                    if any(
                        run_id in refreshed.blocked_runs or _producer_active(session, run_id) for run_id in target_runs
                    ):
                        raise OutputRetentionError("ACTIVE_PRODUCER")
                    relative = _relative_output_path(root, str(item.get("relative_path") or ""))
                    expected_size = int(item["byte_size"])
                    if expected_size < 0:
                        raise ValueError
                    digest = _norm_status(item.get("sha256"))
                    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                        raise ValueError
                    if relative in reference_index.paths or digest in reference_index.hashes:
                        raise OutputRetentionError("FILE_SHARED_REFERENCE")

                    full = root / relative.as_posix()
                    if not os.path.lexists(full):
                        event_payload["status"] = "deleted"
                        event_payload["reconciled"] = True
                        _record_event(
                            session,
                            audit_run_id=audit_run_id,
                            audit_step_id=audit_step_id,
                            event_type=DELETED_EVENT,
                            payload=event_payload,
                            instant=instant,
                        )
                        result["deleted_file_count"] += 1
                        result["reconciled_file_count"] += 1
                        result["deleted"].append(relative.as_posix())
                        continue

                    current = _pending_file_preview(
                        session,
                        refreshed,
                        root,
                        item,
                        reference_index=reference_index,
                    )
                    if not current["eligible"]:
                        raise OutputRetentionError(str(current["reason"]))
                    _safe_unlink(root, relative, digest, expected_size)
                    event_payload["status"] = "deleted"
                    _record_event(
                        session,
                        audit_run_id=audit_run_id,
                        audit_step_id=audit_step_id,
                        event_type=DELETED_EVENT,
                        payload=event_payload,
                        instant=instant,
                    )
                    result["deleted_file_count"] += 1
                    result["deleted"].append(relative.as_posix())
                except (KeyError, TypeError, ValueError, OutputRetentionError) as exc:
                    reason = str(exc) if isinstance(exc, OutputRetentionError) else "PENDING_FILE_IDENTITY_INVALID"
                    event_payload["status"] = "blocked"
                    event_payload["reason"] = reason
                    _record_event(
                        session,
                        audit_run_id=audit_run_id,
                        audit_step_id=audit_step_id,
                        event_type=BLOCKED_EVENT,
                        payload=event_payload,
                        instant=instant,
                    )
                    result["blocked_file_count"] += 1
                    result["blocked"].append(
                        {
                            "file_path": (relative.as_posix() if relative is not None else item.get("relative_path")),
                            "reason": reason,
                            "run_ids": item.get("target_run_ids") or [],
                        }
                    )

            audit_run = session.get(TaskRun, audit_run_id)
            audit_step = session.get(TaskStep, audit_step_id)
            audit_run.status = TaskStatus.partial_success if result["blocked"] else TaskStatus.success
            audit_run.current_stage = "completed"
            audit_run.progress = 1.0
            audit_run.ended_at = instant
            audit_step.status = StepStatus.success
            audit_step.finished_at = instant
            audit_step.output_json = json.dumps(
                {
                    "tombstoned_run_count": result["tombstoned_run_count"],
                    "deleted_file_count": result["deleted_file_count"],
                    "blocked_file_count": result["blocked_file_count"],
                },
                sort_keys=True,
            )
            _record_event(
                session,
                audit_run_id=audit_run_id,
                audit_step_id=audit_step_id,
                event_type=SUMMARY_EVENT,
                payload={
                    "schema_version": SCHEMA_VERSION,
                    **json.loads(audit_step.output_json),
                },
                instant=instant,
            )
            session.commit()
            return result
        except BaseException:
            session.rollback()
            try:
                _finish_failed_audit(session, audit_run_id, audit_step_id, instant)
            except Exception:
                session.rollback()
            raise


__all__ = [
    "OutputRetentionError",
    "apply_unqualified_outputs",
    "preview_unqualified_outputs",
]
