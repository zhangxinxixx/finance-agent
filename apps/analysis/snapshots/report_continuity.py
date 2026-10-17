"""Verified historical report context for Gold research.

This module is deliberately independent from the formal predecessor resolver.
An older report can inform a new inquiry, but it never proves an Accepted state
or becomes a canonical predecessor merely because its prose is readable.
"""

from __future__ import annotations

from copy import deepcopy
import json
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from database.models.report import ReportArtifact, ReportItem
from database.models.analysis import AnalysisSnapshot


CONTEXT_SCHEMA_VERSION = "gold_report_context.v1"
DEFAULT_MAX_REPORT_BYTES = 100_000
MAX_REGISTRY_CANDIDATES = 512
_CADENCES = ("daily", "weekly")
_VALID_DATA_STATUS = {"live", "available"}
_VALID_LIFECYCLE_STATUS = {"generated", "snapshot_bound", "published", "exported"}
_BAD_STATUS = {
    "blocked", "degraded", "error", "failed", "fallback", "invalid", "missing",
    "needs_review", "partial", "rejected", "rule_fallback", "stale", "unavailable",
}
_DAILY_IDENTITIES = {
    ("final_report_markdown", "final_report"),
    ("gold_policy_daily_report", "gold_policy_daily"),
    ("gold_macro_daily_markdown", "gold_macro_daily"),
}
_WEEKLY_IDENTITIES = {
    ("gold_macro_weekly_markdown", "gold_macro_weekly"),
    ("gold_weekly_report", "gold_weekly"),
    ("weekly_report_markdown", "weekly_report"),
}


def _aware_time(value: Any, *, database_timezone_utc: bool = False) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        # ReportArtifact.generated_at is declared DateTime(timezone=True).
        # SQLite drops the tzinfo on round-trip, so portable registry tests
        # restore the model field's UTC convention. User/metadata strings and
        # the current snapshot cutoff must still carry an explicit timezone.
        if database_timezone_utc and isinstance(value, datetime):
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            return None
    return parsed.astimezone(timezone.utc)


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _failure_category(reason: str) -> str:
    if reason in {"report_registry_unavailable", "report_registry_session_not_supplied",
                  "bound_analysis_snapshot_database_unavailable"}:
        return "database_unavailable"
    if reason == "no_matching_report":
        return "no_eligible_prior"
    if reason in {"artifact_missing_or_storage_escape", "artifact_read_failed", "body_empty",
                  "body_oversized", "body_not_utf8", "primary_main_markdown_not_unique",
                  "unsupported_storage_backend", "primary_artifact_not_markdown"}:
        return "body_unavailable"
    return "cutoff_or_version_rejected"


def _classify_failure(item: dict[str, Any]) -> dict[str, Any]:
    """Add recovery categories without erasing rejection reasons or mixed failures."""
    reasons = (item.get("details") or {}).get("rejected_reason_counts") or {
        item.get("reason_code", "context_missing"): 1
    }
    counts: dict[str, int] = {}
    for reason, count in reasons.items():
        category = _failure_category(reason)
        counts[category] = counts.get(category, 0) + count
    item["failure_category"] = next(category for category in (
        "database_unavailable", "body_unavailable", "cutoff_or_version_rejected", "no_eligible_prior"
    ) if category in counts)
    item["failure_category_counts"] = counts
    return item


def _unavailable(cadence: str, reason_code: str, **details: Any) -> dict[str, Any]:
    result = {
        "status": "unavailable",
        "cadence": cadence,
        "reason_code": reason_code,
        "model_input_status": "not_included",
        "formal_state_authority": False,
    }
    if details:
        result["details"] = details
    return _classify_failure(result)


def _classify(item: ReportItem) -> str | None:
    metadata = item.report_metadata if isinstance(item.report_metadata, dict) else {}
    family = str(item.family or "").strip().lower()
    report_type = str(item.report_type or "").strip().lower()
    identity = (family, report_type)
    if "jin10" in family or "jin10" in report_type:
        return None
    cadence = str(
        metadata.get("report_cadence")
        or metadata.get("cadence")
        or metadata.get("report_period")
        or ""
    ).strip().lower()
    # The current final-report registry identity is daily by default, but an
    # explicitly registered weekly instance may use the same storage family.
    if cadence in _CADENCES and identity in (_DAILY_IDENTITIES | _WEEKLY_IDENTITIES):
        return cadence
    if identity in _DAILY_IDENTITIES:
        return "daily"
    if identity in _WEEKLY_IDENTITIES:
        return "weekly"
    return None


def _metadata_gate(item: ReportItem) -> str | None:
    metadata = item.report_metadata if isinstance(item.report_metadata, dict) else {}
    if item.data_status not in _VALID_DATA_STATUS:
        return "unsupported_data_status"
    if item.lifecycle_status not in _VALID_LIFECYCLE_STATUS:
        return "unsupported_lifecycle_status"
    for key in ("status", "quality_status", "generation_status"):
        if str(metadata.get(key, "")).strip().lower() in _BAD_STATUS:
            return "quality_blocked"
    publish_allowed = metadata.get("publish_allowed")
    publication_status = str(metadata.get("publication_status") or "").strip().lower()
    output_mode = str(metadata.get("output_mode") or "").strip().lower()
    review_status = str(metadata.get("review_status") or "").strip().lower()
    publication_proved = publish_allowed is True or publication_status in {"accepted", "published"}
    review_proved = review_status in {"approved", "not_required", "pass", "passed"} or publication_status == "accepted"
    if not publication_proved:
        return "publishability_not_proven"
    if output_mode and output_mode not in {"accepted", "published"}:
        return "observation_or_nonfinal_output"
    if not review_proved:
        return "review_validity_not_proven"
    if not item.report_id or not item.run_id or not item.snapshot_id:
        return "report_identity_incomplete"
    if not isinstance(metadata.get("input_snapshot_ids"), dict) or not metadata["input_snapshot_ids"]:
        return "input_lineage_missing"
    if not isinstance(item.source_refs, list) or not item.source_refs:
        return "report_provenance_missing"
    if _uses_jin10(item.source_refs):
        return "excluded_jin10_provenance"
    return None


def _uses_jin10(value: Any) -> bool:
    """Inspect provenance fields, never the report's prose or a no-source note."""
    from urllib.parse import urlsplit

    if isinstance(value, list):
        return any(_uses_jin10(item) for item in value)
    if not isinstance(value, Mapping):
        return False
    for key, item in value.items():
        if key in {"url", "source_url"} and isinstance(item, str):
            host = (urlsplit(item).hostname or "").lower()
            if host == "jin10.com" or host.endswith(".jin10.com"):
                return True
        elif key in {"source", "provider"} and isinstance(item, str):
            if item.strip().lower() in {"jin10", "金十", "金十数据"}:
                return True
        elif isinstance(item, (Mapping, list)) and _uses_jin10(item):
            return True
    return False


def _resolve_local_path(storage_root: Path, raw_path: str) -> Path | None:
    root = storage_root.resolve()
    path = Path(raw_path)
    candidates = [path] if path.is_absolute() else [root / path, root.parent / path]
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved.is_relative_to(root) and resolved.is_file():
            return resolved
    return None


def _cutoff_from(
    item: ReportItem, artifact: ReportArtifact, *, db_session: Any = None,
    storage_root: Path | None = None,
) -> tuple[datetime | None, str]:
    report_metadata = item.report_metadata if isinstance(item.report_metadata, dict) else {}
    artifact_metadata = artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {}
    for owner, metadata in (("report_metadata", report_metadata), ("artifact_metadata", artifact_metadata)):
        for key in ("analysis_cutoff", "cutoff", "snapshot_time"):
            if key in metadata:
                return _aware_time(metadata[key]), f"{owner}.{key}"
    # Legacy registry rows do not store cutoff metadata. Resolve the exact
    # bound AnalysisSnapshot instead of substituting publication time.
    if db_session is None or storage_root is None:
        return None, "analysis_cutoff_missing"
    try:
        row = db_session.scalar(select(AnalysisSnapshot).where(
            AnalysisSnapshot.snapshot_id == item.snapshot_id,
            AnalysisSnapshot.run_id == item.run_id,
            AnalysisSnapshot.asset == item.asset,
            AnalysisSnapshot.trade_date == item.trade_date,
            AnalysisSnapshot.status == "success",
        ))
        if row is None:
            return None, "bound_analysis_snapshot_missing"
        path = _resolve_local_path(storage_root, row.artifact_path)
        if path is None or path.stat().st_size > 20 * 1024 * 1024:
            return None, "bound_analysis_snapshot_artifact_invalid"
        payload = json.loads(path.read_text(encoding="utf-8"))
        from apps.runtime.premarket_snapshot_authority import _validate_snapshot_row

        _validate_snapshot_row(
            row, asset=item.asset, trade_date=item.trade_date.isoformat(),
            run_id=item.run_id, snapshot_id=item.snapshot_id, expected_path=path,
            storage_root=storage_root, payload=payload,
        )
        actual = _aware_time(payload.get("snapshot_time"))
        if (actual is None or actual != _aware_time(row.snapshot_time, database_timezone_utc=True)
                or any(payload.get(key) != getattr(item, key)
                       for key in ("asset", "run_id", "snapshot_id"))
                or payload.get("trade_date") != item.trade_date.isoformat()
                or report_metadata.get("input_snapshot_ids") != row.input_snapshot_ids):
            return None, "bound_analysis_snapshot_identity_invalid"
        return actual, "verified_analysis_snapshot.snapshot_time"
    except SQLAlchemyError:
        return None, "bound_analysis_snapshot_database_unavailable"
    except (OSError, ValueError, TypeError, KeyError):
        return None, "bound_analysis_snapshot_invalid"
    except Exception:
        return None, "bound_analysis_snapshot_unavailable"


def _validate_candidate(
    item: ReportItem,
    *,
    cadence: str,
    storage_root: Path,
    current_cutoff: datetime,
    current_trade_date: date,
    max_report_bytes: int,
    db_session: Any = None,
) -> tuple[dict[str, Any] | None, str | None]:
    reason = _metadata_gate(item)
    if reason:
        return None, reason
    if item.asset is None or not item.trade_date or item.trade_date > current_trade_date:
        return None, "report_not_strictly_older"
    primary = [
        artifact for artifact in item.artifacts
        if artifact.is_primary and artifact.artifact_type == "analysis_md"
    ]
    if len(primary) != 1:
        return None, "primary_main_markdown_not_unique"
    artifact = primary[0]
    if artifact.storage_backend != "local_fs":
        return None, "unsupported_storage_backend"
    if artifact.content_type != "text/markdown":
        return None, "primary_artifact_not_markdown"
    if str(artifact.status or "").lower() in _BAD_STATUS:
        return None, "artifact_status_invalid"
    generated_at = _aware_time(artifact.generated_at, database_timezone_utc=True)
    if generated_at is None or generated_at >= current_cutoff:
        return None, "generated_time_missing_or_not_before_cutoff"
    actual_cutoff, cutoff_source = _cutoff_from(item, artifact, db_session=db_session, storage_root=storage_root)
    if cutoff_source == "bound_analysis_snapshot_database_unavailable":
        return None, cutoff_source
    if actual_cutoff is None or actual_cutoff >= current_cutoff or actual_cutoff > generated_at:
        return None, "report_cutoff_invalid"
    if not isinstance(artifact.sha256, str) or len(artifact.sha256) != 64:
        return None, "stored_sha256_missing"
    path = _resolve_local_path(storage_root, artifact.file_path)
    if path is None:
        return None, "artifact_missing_or_storage_escape"
    try:
        with path.open("rb") as stream:
            content = stream.read(max_report_bytes + 1)
    except OSError:
        return None, "artifact_read_failed"
    if not content:
        return None, "body_empty"
    if len(content) > max_report_bytes:
        return None, "body_oversized"
    if artifact.byte_size is not None and artifact.byte_size != len(content):
        return None, "stored_byte_size_mismatch"
    digest = sha256(content).hexdigest()
    if digest != artifact.sha256.lower():
        return None, "stored_sha256_mismatch"
    try:
        body = content.decode("utf-8")
    except UnicodeDecodeError:
        return None, "body_not_utf8"
    if not body.strip():
        return None, "body_empty"
    registry_times = [_aware_time(value, database_timezone_utc=True) for value in
                      (item.created_at, item.updated_at, artifact.created_at, artifact.updated_at)]
    if not all(registry_times):
        return None, "registry_availability_missing"
    available_at = max(generated_at, *registry_times)
    if available_at >= current_cutoff:
        return None, "registry_revision_not_available_before_cutoff"
    metadata = item.report_metadata if isinstance(item.report_metadata, dict) else {}
    provenance = deepcopy(item.source_refs)
    context_ref = {
        "source": "verified_prior_report_context",
        "source_ref": item.report_id,
        "report_type": item.report_type,
        "artifact_ref": str(path.relative_to(storage_root.resolve())),
        "sha256": digest,
        "snapshot_id": item.snapshot_id,
        "status": "verified",
        "asset": item.asset,
    }
    return {
        "status": "verified",
        "asset": item.asset,
        "cadence": cadence,
        "report_id": item.report_id,
        "run_id": item.run_id,
        "snapshot_id": item.snapshot_id,
        "trade_date": item.trade_date.isoformat(),
        "actual_cutoff": actual_cutoff.isoformat(),
        "cutoff_source": cutoff_source,
        "generated_at": generated_at.isoformat(),
        "available_at": available_at.isoformat(),
        "availability_basis": "report_and_artifact_registry_revision",
        "family": item.family,
        "report_type": item.report_type,
        "body": body,
        "body_utf8_bytes": len(content),
        "verified_body_sha256": digest,
        "artifact_ref": context_ref["artifact_ref"],
        "provenance": provenance,
        "source_refs": [*provenance, context_ref],
        "input_snapshot_ids": deepcopy(metadata["input_snapshot_ids"]),
        "model_input_status": "included_full_body",
        "data_category": "historical_opinion",
        "formal_state_authority": False,
        "accepted_authority": False,
    }, None


def load_prior_report_contexts(
    db_session: Any,
    *,
    storage_root: Path,
    snapshot: Mapping[str, Any],
    max_report_bytes: int = DEFAULT_MAX_REPORT_BYTES,
) -> dict[str, Any]:
    """Load the latest independently valid daily and weekly report bodies."""
    cutoff = _aware_time(snapshot.get("snapshot_time"))
    trade_date = _date(snapshot.get("trade_date"))
    asset = snapshot.get("asset")
    base = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "asset": asset,
        "current_snapshot_id": snapshot.get("snapshot_id"),
        "cutoff": snapshot.get("snapshot_time"),
        "contexts": {},
    }
    if cutoff is None:
        base["status"] = "unavailable"
        base["contexts"] = {cadence: _unavailable(cadence, "invalid_current_cutoff") for cadence in _CADENCES}
        return base
    if trade_date is None or not isinstance(asset, str) or not asset:
        base["status"] = "unavailable"
        base["contexts"] = {cadence: _unavailable(cadence, "current_identity_incomplete") for cadence in _CADENCES}
        return base
    if not isinstance(max_report_bytes, int) or max_report_bytes <= 0:
        raise ValueError("max_report_bytes must be a positive integer")
    try:
        rows = list(db_session.scalars(
            select(ReportItem)
            .options(selectinload(ReportItem.artifacts))
            .where(ReportItem.asset == asset, ReportItem.trade_date <= trade_date,
                   ReportItem.run_id != snapshot.get("run_id"),
                   ReportItem.snapshot_id != snapshot.get("snapshot_id"))
            .order_by(ReportItem.trade_date.desc(), ReportItem.updated_at.desc(), ReportItem.report_id.asc())
            .limit(MAX_REGISTRY_CANDIDATES + 1)
        ).all())
    except Exception as exc:  # registry availability is an explicit input state
        base["status"] = "unavailable"
        base["contexts"] = {
            cadence: _unavailable(cadence, "report_registry_unavailable", error_type=type(exc).__name__)
            for cadence in _CADENCES
        }
        return base
    if len(rows) > MAX_REGISTRY_CANDIDATES:
        base["status"] = "unavailable"
        base["contexts"] = {
            cadence: _unavailable(cadence, "registry_scan_limit_exceeded", limit=MAX_REGISTRY_CANDIDATES)
            for cadence in _CADENCES
        }
        return base

    for cadence in _CADENCES:
        valid: list[dict[str, Any]] = []
        rejected: dict[str, int] = {}
        classified = 0
        for item in rows:
            if _classify(item) != cadence:
                continue
            classified += 1
            context, reason = _validate_candidate(
                item,
                cadence=cadence,
                storage_root=storage_root,
                current_cutoff=cutoff,
                current_trade_date=trade_date,
                max_report_bytes=max_report_bytes,
                db_session=db_session,
            )
            if context is not None:
                valid.append(context)
            else:
                rejected[reason or "invalid_candidate"] = rejected.get(reason or "invalid_candidate", 0) + 1
        # A failed lookup can hide a newer eligible candidate. Do not silently
        # substitute an older body or say that the registry contains no reports.
        if "bound_analysis_snapshot_database_unavailable" in rejected:
            base["contexts"][cadence] = _unavailable(
                cadence, "bound_analysis_snapshot_database_unavailable",
                classified_candidates=classified, rejected_reason_counts=rejected,
                verified_candidates=len(valid),
            )
            continue
        if not valid:
            reason = "no_matching_report" if classified == 0 else "no_valid_report"
            base["contexts"][cadence] = _unavailable(
                cadence, reason, classified_candidates=classified, rejected_reason_counts=rejected
            )
            continue
        valid.sort(key=lambda item: (item["actual_cutoff"], item["trade_date"]), reverse=True)
        latest = valid[0]
        tied = [item for item in valid if item["actual_cutoff"] == latest["actual_cutoff"]]
        if len(tied) > 1:
            base["contexts"][cadence] = _unavailable(
                cadence,
                "ambiguous_latest_valid_report",
                report_ids=sorted(item["report_id"] for item in tied),
                actual_cutoff=latest["actual_cutoff"],
            )
        else:
            base["contexts"][cadence] = latest
    statuses = [base["contexts"][cadence]["status"] for cadence in _CADENCES]
    base["status"] = "verified" if statuses == ["verified", "verified"] else "partial" if "verified" in statuses else "unavailable"
    return base


def validate_prior_report_contexts(
    payload: Any,
    *,
    cutoff: Any,
    max_report_bytes: int = DEFAULT_MAX_REPORT_BYTES,
    storage_root: Path | None = None,
    expected_asset: str | None = None,
    current_snapshot_id: str | None = None,
    require_availability: bool = False,
) -> dict[str, Any]:
    """Revalidate attached bodies against the final snapshot cutoff."""
    final_cutoff = _aware_time(cutoff)
    if not isinstance(payload, Mapping) or payload.get("schema_version") != CONTEXT_SCHEMA_VERSION:
        return {
            "schema_version": CONTEXT_SCHEMA_VERSION,
            "status": "unavailable",
            "cutoff": cutoff,
            "contexts": {cadence: _unavailable(cadence, "context_contract_missing") for cadence in _CADENCES},
        }
    result = deepcopy(dict(payload))
    contexts = result.get("contexts") if isinstance(result.get("contexts"), Mapping) else {}
    checked: dict[str, Any] = {}
    for cadence in _CADENCES:
        item = deepcopy(contexts.get(cadence)) if isinstance(contexts.get(cadence), Mapping) else None
        if not item or item.get("status") != "verified":
            checked[cadence] = (_classify_failure(item) if item and item.get("status") == "unavailable"
                                else _unavailable(cadence, "context_missing"))
            continue
        body = item.get("body")
        actual_cutoff = _aware_time(item.get("actual_cutoff"))
        generated_at = _aware_time(item.get("generated_at"))
        reason = None
        if ((expected_asset is not None and (result.get("asset") != expected_asset or item.get("asset") != expected_asset))
                or (current_snapshot_id is not None and result.get("current_snapshot_id") != current_snapshot_id)
                or item.get("snapshot_id") == current_snapshot_id
                or item.get("cadence") != cadence):
            reason = "attached_context_identity_mismatch"
        elif _uses_jin10(item.get("source_refs", [])):
            reason = "excluded_jin10_provenance"
        elif (not all(isinstance(item.get(key), str) and item[key].strip()
                    for key in ("report_id", "run_id", "snapshot_id", "artifact_ref"))
                or not isinstance(item.get("input_snapshot_ids"), dict)
                or not item["input_snapshot_ids"]):
            reason = "attached_identity_or_lineage_missing"
        elif not isinstance(body, str) or not body.strip():
            reason = "body_empty"
        else:
            encoded = body.encode("utf-8")
            if len(encoded) > max_report_bytes:
                reason = "body_oversized"
            elif sha256(encoded).hexdigest() != item.get("verified_body_sha256"):
                reason = "attached_body_sha256_mismatch"
            elif item.get("body_utf8_bytes") != len(encoded):
                reason = "attached_body_size_mismatch"
            else:
                context_ref = next((
                    ref for ref in item.get("source_refs", [])
                    if isinstance(ref, dict) and ref.get("source") == "verified_prior_report_context"
                ), None)
                if (not context_ref
                        or context_ref.get("source_ref") != item.get("report_id")
                        or context_ref.get("snapshot_id") != item.get("snapshot_id")
                        or context_ref.get("artifact_ref") != item.get("artifact_ref")
                        or context_ref.get("sha256") != item.get("verified_body_sha256")):
                    reason = "attached_hash_provenance_mismatch"
        if not reason and storage_root is not None:
            path = _resolve_local_path(storage_root, str(item["artifact_ref"]))
            if path is None:
                reason = "artifact_missing_or_storage_escape"
            else:
                try:
                    persisted = path.read_bytes()
                except OSError:
                    reason = "artifact_read_failed"
                else:
                    if persisted != body.encode("utf-8") or sha256(persisted).hexdigest() != item["verified_body_sha256"]:
                        reason = "persisted_body_sha256_mismatch"
        if not reason and (final_cutoff is None or actual_cutoff is None or generated_at is None
                           or actual_cutoff >= final_cutoff or generated_at >= final_cutoff
                           or actual_cutoff > generated_at):
            reason = "context_time_not_before_final_cutoff"
        if not reason and require_availability:
            available_at = _aware_time(item.get("available_at"))
            if (available_at is None or not generated_at <= available_at < final_cutoff
                    or item.get("availability_basis") != "report_and_artifact_registry_revision"):
                reason = "context_availability_not_verified_before_cutoff"
        if not reason and (item.get("formal_state_authority") is not False
                           or item.get("accepted_authority") is not False
                           or item.get("data_category") != "historical_opinion"):
            reason = "context_authority_boundary_invalid"
        if reason:
            checked[cadence] = _unavailable(cadence, reason, report_id=item.get("report_id"))
        else:
            item["model_input_status"] = "included_full_body"
            checked[cadence] = item
    result["contexts"] = checked
    result["cutoff"] = cutoff
    statuses = [checked[cadence]["status"] for cadence in _CADENCES]
    result["status"] = "verified" if statuses == ["verified", "verified"] else "partial" if "verified" in statuses else "unavailable"
    return result


def attach_prior_report_contexts(
    snapshot: Mapping[str, Any],
    payload: Any,
    *,
    storage_root: Path | None = None,
) -> dict[str, Any]:
    """Attach verified context and bind only its proven lineage to a snapshot."""
    result = deepcopy(dict(snapshot))
    validated = validate_prior_report_contexts(
        payload,
        cutoff=result.get("snapshot_time"),
        storage_root=storage_root,
        expected_asset=result.get("asset"),
        current_snapshot_id=result.get("snapshot_id"),
        require_availability=_requires_availability(result),
    )
    result["prior_report_contexts"] = validated
    input_ids = result.setdefault("input_snapshot_ids", {})
    refs = [
        ref for ref in result.setdefault("source_refs", [])
        if not (isinstance(ref, dict) and ref.get("source") == "verified_prior_report_context")
    ]
    for cadence in _CADENCES:
        lineage_key = f"prior_report_{cadence}"
        item = validated["contexts"][cadence]
        if item.get("status") != "verified":
            input_ids.pop(lineage_key, None)
            continue
        existing = input_ids.get(lineage_key)
        if existing not in (None, item["snapshot_id"]):
            validated["contexts"][cadence] = _unavailable(
                cadence, "snapshot_lineage_conflict", existing=existing, expected=item["snapshot_id"]
            )
            input_ids.pop(lineage_key, None)
            continue
        input_ids[lineage_key] = item["snapshot_id"]
        context_ref = next(
            (ref for ref in item.get("source_refs", [])
             if isinstance(ref, dict) and ref.get("source") == "verified_prior_report_context"),
            None,
        )
        if context_ref and context_ref not in refs:
            refs.append(deepcopy(context_ref))
    result["source_refs"] = refs
    statuses = [validated["contexts"][cadence]["status"] for cadence in _CADENCES]
    validated["status"] = "verified" if statuses == ["verified", "verified"] else "partial" if "verified" in statuses else "unavailable"
    return result


def load_and_attach_prior_report_contexts(
    db_session: Any,
    *,
    storage_root: Path,
    snapshot: Mapping[str, Any],
    max_report_bytes: int = DEFAULT_MAX_REPORT_BYTES,
) -> dict[str, Any]:
    """Graph-safe convenience helper: registry load followed by lineage attach."""
    loaded = load_prior_report_contexts(
        db_session,
        storage_root=storage_root,
        snapshot=snapshot,
        max_report_bytes=max_report_bytes,
    )
    return attach_prior_report_contexts(snapshot, loaded, storage_root=storage_root)


def prior_report_context_model_input(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return the non-recursive, full-body model view or explicit rejection."""
    validated = validate_prior_report_contexts(
        snapshot.get("prior_report_contexts"), cutoff=snapshot.get("snapshot_time"),
        expected_asset=snapshot.get("asset"), current_snapshot_id=snapshot.get("snapshot_id"),
        require_availability=_requires_availability(snapshot),
    )
    return {
        "schema_version": validated["schema_version"],
        "status": validated["status"],
        "cutoff": validated.get("cutoff"),
        "authority_boundary": (
            "Historical reports are prior opinion only. Recheck every hypothesis against current facts; "
            "they never establish Accepted state or current market truth."
        ),
        "contexts": {
            cadence: ({
                key: deepcopy(item[key])
                for key in (
                    "status", "asset", "cadence", "reason_code", "failure_category", "failure_category_counts",
                    "details", "report_id", "run_id", "snapshot_id",
                    "trade_date", "actual_cutoff", "generated_at", "available_at", "availability_basis", "family", "report_type",
                    "body", "body_utf8_bytes", "verified_body_sha256", "artifact_ref",
                    "source_refs", "model_input_status", "data_category", "formal_state_authority",
                    "accepted_authority",
                ) if key in item
            })
            for cadence, item in validated["contexts"].items()
        },
    }


def _requires_availability(snapshot):
    flow = snapshot.get("gold_workflow") or {}
    return (flow.get("reader_report_version") == "gold_reader.v4"
            or flow.get("reader_presentation") == "gold_reader.research.v1")


__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "DEFAULT_MAX_REPORT_BYTES",
    "attach_prior_report_contexts",
    "load_and_attach_prior_report_contexts",
    "load_prior_report_contexts",
    "prior_report_context_model_input",
    "validate_prior_report_contexts",
]
