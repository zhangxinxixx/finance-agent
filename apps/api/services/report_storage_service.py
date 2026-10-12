from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy import or_, select

from apps.api.services import _storage
from apps.api.services._storage import _iso
from apps.runtime.output_disposition import (
    FAIL_CLOSED_AGENT_NAMES,
    OUTPUT_CLEANUP_KEY,
    is_output_purged,
    purged_output_summary,
)
from apps.runtime.storage_paths import project_artifact_path
from database.models.analysis import AgentOutput, FinalAnalysisResult
from database.models.report import ReportArtifact, ReportItem

logger = logging.getLogger(__name__)

_FINAL_REPORT_FILENAME = "final_report.md"
_STRUCTURED_REPORT_FILENAME = "structured_report.json"


def _safe_path_component(value: str) -> str | None:
    """Return a single path component accepted by the report API."""
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if value in {".", ".."} or "/" in value or "\\" in value:
        return None
    candidate = Path(value)
    if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.name != value:
        return None
    return value


def _trusted_outputs_root() -> Path | None:
    """Return the outputs boundary below the resolved, configured storage root.

    The storage directory itself may be the supported runtime symlink.  The
    ``outputs`` directory is the trust boundary and must remain its direct,
    non-symlink child; otherwise ``storage/outputs -> storage/raw`` would
    silently turn raw files into report artifacts.
    """
    project_root = Path(_storage._PROJECT_ROOT)
    try:
        logical_outputs = project_artifact_path("storage/outputs", project_root=project_root)
        storage_root = (project_root / "storage").resolve(strict=True)
        outputs = storage_root / "outputs"
        if logical_outputs.name != "outputs" or outputs.is_symlink() or not outputs.is_dir():
            return None
        return outputs
    except (OSError, ValueError, RuntimeError):
        return None


def _safe_final_report_file(file_path: str | Path, *, filename: str) -> Path | None:
    """Validate a report artifact and return its logical path for reading.

    ``storage`` itself may be a configured runtime symlink.  Directory and file
    symlinks below ``storage/outputs`` must still resolve inside that trusted
    directory.
    """
    raw_path = Path(file_path)
    if ".." in raw_path.parts:
        return None
    if raw_path.name != filename:
        return None
    try:
        candidate = project_artifact_path(raw_path, project_root=Path(_storage._PROJECT_ROOT))
        trusted_root = _trusted_outputs_root()
        if trusted_root is None:
            return None
        parent = candidate.parent.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        if not parent.is_relative_to(trusted_root):
            return None
        if not resolved.is_relative_to(trusted_root) or not resolved.is_file():
            return None
        return candidate
    except (OSError, ValueError, RuntimeError):
        return None


def _display_report_path(path: Path) -> str:
    """Keep the existing project-relative response path for runtime symlinks."""
    project_root = Path(_storage._PROJECT_ROOT)
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        try:
            storage_root = (project_root / "storage").resolve()
            resolved = path.resolve()
            return Path("storage", *resolved.relative_to(storage_root).parts).as_posix()
        except (OSError, ValueError, RuntimeError):
            return str(path)


def _report_quality_score(md_path: Path) -> tuple[int, float, str]:
    try:
        content = md_path.read_text(encoding="utf-8")
    except Exception:
        return (-100, 0.0, md_path.parent.name)
    score = 0
    if "# XAUUSD 相关报告" in content:
        score += 120
    if "# XAUUSD 盘前专业研究报告" in content:
        score += 90
    if "## 执行摘要" in content:
        score += 25
    if "## 分项证据链" in content:
        score += 15
    if "# XAUUSD 盘前综合报告" in content:
        score += 70
    if "## 协调器总结" in content:
        score += 20
    if "## 数据口径" in content:
        score += 10
    if "## CME 期权结构视图" in content or "### CME 期权结构视图" in content:
        score += 10
    if "# XAUUSD Premarket Final Report" in content:
        score -= 40
    if "## Coordinator Summary" in content:
        score -= 20
    if "options: unavailable" in content or "options status is 'unavailable'" in content:
        score -= 40
    if "No complete final view" in content:
        score -= 10
    try:
        mtime = md_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return score, mtime, md_path.parent.name


def _safe_model_rows(db, model, query_factory) -> list[Any]:
    """Read an optional model without dropping anchors from earlier tables."""
    try:
        if not sqlalchemy_inspect(db.get_bind()).has_table(model.__tablename__):
            return []
        with db.begin_nested():
            rows = list(query_factory())
        # Anchor queries use SQL column projections. Keep attribute-style
        # access for the guard code without hydrating ORM payloads.
        return [SimpleNamespace(**dict(row._mapping)) if hasattr(row, "_mapping") else row for row in rows]
    except Exception:
        return []


def _safe_row_artifacts(db, row) -> list[Any]:
    """Load optional report artifacts without invalidating the DB session."""
    try:
        if not sqlalchemy_inspect(db.get_bind()).has_table("report_artifacts"):
            return []
        report_id = getattr(row, "report_id", None)
        if not report_id:
            return []
        with db.begin_nested():
            rows = db.execute(
                select(
                    ReportArtifact.status,
                    ReportArtifact.artifact_metadata.label("artifact_metadata"),
                ).where(ReportArtifact.report_id == report_id)
            ).mappings().all()
        return [SimpleNamespace(**dict(projected)) for projected in rows]
    except Exception:
        return []


def _purged_final_report_anchors(db, asset: str) -> list[dict[str, Any]]:
    """Return tombstone identities using original research creation times."""
    anchors: list[dict[str, Any]] = []
    report_rows = _safe_model_rows(
        db,
        ReportItem,
        lambda: db.execute(
            select(
                ReportItem.report_id,
                ReportItem.run_id,
                ReportItem.snapshot_id,
                ReportItem.trade_date,
                ReportItem.lifecycle_status,
                ReportItem.report_metadata.label("report_metadata"),
                ReportItem.created_at,
            ).where(
                or_(ReportItem.asset == asset, ReportItem.asset.is_(None)),
                or_(
                    ReportItem.report_type == "final_report",
                    ReportItem.family.in_(("final_report", "final_report_markdown")),
                ),
            )
        ).mappings().all(),
    )
    for row in report_rows:
        if not (
            is_output_purged(row)
            or str(row.lifecycle_status or "").lower() == "purged"
            or any(is_output_purged(artifact) for artifact in _safe_row_artifacts(db, row))
        ):
            continue
        marker = purged_output_summary(row) or {}
        anchors.append(
            {
                "report_id": str(row.report_id),
                "run_id": str(row.run_id) if row.run_id else marker.get("run_id"),
                "snapshot_id": str(row.snapshot_id) if row.snapshot_id else marker.get("snapshot_id"),
                "trade_date": _iso(row.trade_date) if row.trade_date else None,
                # Cleanup updates updated_at; created_at is the research time.
                "created_at": getattr(row, "created_at", None),
            }
        )

    final_rows = _safe_model_rows(
        db,
        FinalAnalysisResult,
        lambda: db.execute(
            select(
                FinalAnalysisResult.id,
                FinalAnalysisResult.run_id,
                FinalAnalysisResult.snapshot_id,
                FinalAnalysisResult.trade_date,
                FinalAnalysisResult.created_at,
                FinalAnalysisResult.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
            ).where(FinalAnalysisResult.asset == asset)
        ).mappings().all(),
    )
    for row in final_rows:
        if not is_output_purged(row):
            continue
        marker = purged_output_summary(row) or {}
        anchors.append(
            {
                "report_id": str(row.run_id),
                "run_id": str(row.run_id),
                "snapshot_id": str(row.snapshot_id) if row.snapshot_id else marker.get("snapshot_id"),
                "trade_date": _iso(row.trade_date) if row.trade_date else None,
                "created_at": getattr(row, "created_at", None),
            }
        )

    # A blocked research stage may deliberately have no ReportItem or
    # FinalAnalysisResult. Its tombstone is still the newest research anchor.
    failure_rows = _safe_model_rows(
        db,
        AgentOutput,
        lambda: db.execute(
            select(
                AgentOutput.id,
                AgentOutput.snapshot_id,
                AgentOutput.asset,
                AgentOutput.trade_date,
                AgentOutput.run_id,
                AgentOutput.agent_name,
                AgentOutput.created_at,
                AgentOutput.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
            ).where(
                AgentOutput.asset == asset,
                AgentOutput.agent_name.in_(FAIL_CLOSED_AGENT_NAMES),
            )
        ).mappings().all(),
    )
    for row in failure_rows:
        if not is_output_purged(row):
            continue
        marker = purged_output_summary(row) or {}
        anchors.append(
            {
                "report_id": str(row.run_id),
                "run_id": str(row.run_id),
                "snapshot_id": str(row.snapshot_id) if row.snapshot_id else marker.get("snapshot_id"),
                "trade_date": _iso(row.trade_date) if row.trade_date else None,
                "created_at": getattr(row, "created_at", None),
            }
        )
    return anchors


def _research_created_at_for_run(
    db,
    asset: str,
    run_id: str,
    *,
    report_types: tuple[str, ...] = ("final_report", "final_report_markdown"),
) -> Any | None:
    """Return a trusted DB creation time for a non-tombstoned FS run."""
    values: list[Any] = []
    report_rows = _safe_model_rows(
        db,
        ReportItem,
        lambda: db.execute(
            select(
                ReportItem.run_id,
                ReportItem.trade_date,
                ReportItem.lifecycle_status,
                ReportItem.report_metadata.label("report_metadata"),
                ReportItem.created_at,
            ).where(
                ReportItem.run_id == run_id,
                or_(ReportItem.asset == asset, ReportItem.asset.is_(None)),
                or_(
                    ReportItem.report_type.in_(report_types),
                    ReportItem.family.in_(report_types),
                ),
            )
        ).mappings().all(),
    )
    values.extend(
        getattr(row, "created_at", None)
        for row in report_rows
        if not is_output_purged(row) and str(row.lifecycle_status or "").lower() != "purged"
    )
    final_rows = _safe_model_rows(
        db,
        FinalAnalysisResult,
        lambda: db.execute(
            select(
                FinalAnalysisResult.run_id,
                FinalAnalysisResult.trade_date,
                FinalAnalysisResult.created_at,
                FinalAnalysisResult.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
            ).where(FinalAnalysisResult.asset == asset, FinalAnalysisResult.run_id == run_id)
        ).mappings().all(),
    )
    values.extend(getattr(row, "created_at", None) for row in final_rows if not is_output_purged(row))
    timed = [(stamp, _timestamp(stamp)) for stamp in values]
    valid = [(stamp, timestamp) for stamp, timestamp in timed if timestamp is not None]
    return max(valid, key=lambda item: item[1])[0] if valid else None


def _timestamp(value: Any) -> float | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _purged_anchor_blocks_filesystem(
    anchors: list[dict[str, Any]],
    fs_best: tuple[str, str, Path] | None,
    *,
    candidate_created_at: Any | None = None,
) -> bool:
    if not anchors:
        return False
    if fs_best is None:
        return True
    fs_date, fs_run_id, _fs_path = fs_best
    for anchor in anchors:
        if str(anchor.get("run_id") or "") == str(fs_run_id) or str(anchor.get("report_id") or "") == str(fs_run_id):
            return True
        anchor_date = str(anchor.get("trade_date") or "")
        if anchor_date > str(fs_date):
            return True
        if anchor_date != str(fs_date):
            continue
        anchor_time = _timestamp(anchor.get("created_at"))
        candidate_time = _timestamp(candidate_created_at)
        # Filesystem mtime is mutable and cannot establish research order.
        # Same-date reads without both trusted DB times fail closed.
        if anchor_time is None or candidate_time is None or anchor_time >= candidate_time:
            return True
    return False


def _purged_anchor_matches_request(
    anchors: list[dict[str, Any]], *, trade_date: str, run_id: str
) -> bool:
    return any(
        str(anchor.get("run_id") or "") == str(run_id)
        or str(anchor.get("report_id") or "") in {str(run_id), f"final_report:{run_id}"}
        or str(anchor.get("snapshot_id") or "") == str(run_id)
        for anchor in anchors
    )


def _purged_anchor_blocks_row(anchors: list[dict[str, Any]], row: Any) -> bool:
    row_date = _iso(row.trade_date) if getattr(row, "trade_date", None) else ""
    row_time = _timestamp(getattr(row, "created_at", None))
    for anchor in anchors:
        if str(anchor.get("run_id") or "") == str(getattr(row, "run_id", "")):
            return True
        anchor_date = str(anchor.get("trade_date") or "")
        if anchor_date > row_date:
            return True
        if anchor_date == row_date:
            anchor_time = _timestamp(anchor.get("created_at"))
            if anchor_time is None or row_time is None or anchor_time >= row_time:
                return True
    return False


def _build_final_report_response(
    asset: str,
    trade_date: str,
    run_id: str,
    md_path: Path,
    *,
    include_structured: bool = True,
) -> dict[str, Any] | None:
    safe_md_path = _safe_final_report_file(md_path, filename=_FINAL_REPORT_FILENAME)
    if safe_md_path is None:
        return None
    result: dict[str, Any] = {
        "asset": asset,
        "trade_date": trade_date,
        "run_id": run_id,
        "content": safe_md_path.read_text(encoding="utf-8"),
        "format": "markdown",
        "path": _display_report_path(safe_md_path),
    }
    if include_structured:
        json_path = safe_md_path.parent / _STRUCTURED_REPORT_FILENAME
        if json_path.exists():
            safe_json_path = _safe_final_report_file(json_path, filename=_STRUCTURED_REPORT_FILENAME)
            if safe_json_path is None:
                result["structured_sections"] = None
            else:
                try:
                    result["structured_sections"] = json.loads(safe_json_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    result["structured_sections"] = None
    return result


def _latest_final_report_from_filesystem(asset: str = "XAUUSD") -> tuple[str, str, Path] | None:
    asset_component = _safe_path_component(asset)
    if asset_component is None:
        return None
    base = Path(_storage._PROJECT_ROOT) / "storage" / "outputs" / "final_report" / asset_component
    trusted_root = _trusted_outputs_root()
    if trusted_root is None:
        return None
    try:
        resolved_base = base.resolve(strict=True)
    except (OSError, ValueError, RuntimeError):
        return None
    if not resolved_base.is_dir() or not resolved_base.is_relative_to(trusted_root):
        return None
    candidates: list[tuple[str, str, Path]] = []
    for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        try:
            resolved_date_dir = date_dir.resolve(strict=True)
        except (OSError, ValueError, RuntimeError):
            continue
        if not resolved_date_dir.is_dir() or not resolved_date_dir.is_relative_to(trusted_root):
            continue
        for run_dir in (d for d in date_dir.iterdir() if d.is_dir()):
            try:
                resolved_run_dir = run_dir.resolve(strict=True)
            except (OSError, ValueError, RuntimeError):
                continue
            if not resolved_run_dir.is_dir() or not resolved_run_dir.is_relative_to(trusted_root):
                continue
            md_path = _safe_final_report_file(run_dir / _FINAL_REPORT_FILENAME, filename=_FINAL_REPORT_FILENAME)
            if md_path is not None:
                candidates.append((date_dir.name, run_dir.name, md_path))
        if candidates:
            break
    return max(candidates, key=lambda item: _report_quality_score(item[2])) if candidates else None


def get_final_report_latest(asset: str = "XAUUSD") -> dict[str, Any] | None:
    # Current latest is a live read model.  A missing/broken DB cannot fall
    # back to a shared file that may be a cleaned output left on disk.
    try:
        db = _storage._try_db_session()
    except Exception:
        return None
    if db is None:
        return None
    try:
        db.execute(select(1))
        # Resolve the authoritative DB identity/path and cleanup marker before
        # considering any file.  The projection deliberately excludes the
        # persisted report payload and source arrays.
        row = db.execute(
            select(
                FinalAnalysisResult.id,
                FinalAnalysisResult.asset,
                FinalAnalysisResult.trade_date,
                FinalAnalysisResult.run_id,
                FinalAnalysisResult.snapshot_id,
                FinalAnalysisResult.final_report_path,
                FinalAnalysisResult.created_at,
                FinalAnalysisResult.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
            )
            .where(FinalAnalysisResult.asset == asset)
            .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
            .limit(1)
        ).mappings().first()
        purged_anchors = _purged_final_report_anchors(db, asset)
        fs_best = _latest_final_report_from_filesystem(asset)
        candidate_created_at = (
            _research_created_at_for_run(db, asset, fs_best[1]) if fs_best is not None else None
        )
        if _purged_anchor_blocks_filesystem(
            purged_anchors, fs_best, candidate_created_at=candidate_created_at
        ):
            return None
        if fs_best is not None:
            trade_date, run_id, md_path = fs_best
            return _build_final_report_response(asset, trade_date, run_id, md_path)

        if row is not None and (is_output_purged(row) or _purged_anchor_blocks_row(purged_anchors, row)):
            return None
        if row is not None and row.final_report_path:
            path = _safe_final_report_file(row.final_report_path, filename=_FINAL_REPORT_FILENAME)
            if path is not None:
                result = _build_final_report_response(asset, _iso(row.trade_date), row.run_id, path)
                if result is not None:
                    return result
    except Exception:
        # Current reads fail closed on connection/query errors; historical
        # date/run reads retain their explicit filesystem compatibility.
        return None
    finally:
        db.close()
    return None


def get_final_report(date: str, run_id: str, asset: str = "XAUUSD") -> dict[str, Any] | None:
    date_component = _safe_path_component(date)
    run_component = _safe_path_component(run_id)
    asset_component = _safe_path_component(asset)
    if date_component is None or run_component is None or asset_component is None:
        return None

    expected_path = _safe_final_report_file(
        Path(_storage._PROJECT_ROOT)
        / "storage"
        / "outputs"
        / "final_report"
        / asset_component
        / date_component
        / run_component
        / _FINAL_REPORT_FILENAME,
        filename=_FINAL_REPORT_FILENAME,
    )
    db = _storage._try_db_session()
    if db is not None:
        try:
            if _purged_anchor_matches_request(
                _purged_final_report_anchors(db, asset), trade_date=date, run_id=run_id
            ):
                return None
            from database.queries.analysis import get_final_analysis

            row = get_final_analysis(db, asset, date, run_id)
            if row is not None and is_output_purged(row):
                return None
            if row is not None and row.final_report_path:
                path = _safe_final_report_file(row.final_report_path, filename=_FINAL_REPORT_FILENAME)
                if path is not None:
                    result = _build_final_report_response(
                        asset,
                        date,
                        run_id,
                        path,
                    )
                    if result is not None:
                        return result
        except Exception:
            pass
        finally:
            db.close()
    return _build_final_report_response(asset, date, run_id, expected_path) if expected_path is not None else None
