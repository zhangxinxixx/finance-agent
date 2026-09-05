"""Read-only Gold result identities for API responses."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from apps.analysis.gold_policy.daily_close_store import verify_gold_daily_close_bundle
from apps.analysis.strategy.gold_baseline_adapter import resolve_verified_gold_baseline


RESULT_IDENTITY_SCHEMA_VERSION = "gold_result_identity.v1"

_GOLD_REPORT_FAMILY = "gold_policy_daily_report"
_REPORT_MANIFEST_VERSIONS = {
    "gold_policy_report_manifest.v1": "gold_policy_report_structured.v1",
    "gold_policy_report_manifest.v2": "gold_policy_report_structured.v2",
}
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_BUNDLE_BASE = Path("analysis") / "gold_mainlines"
_CORE_IDS = ("result_id", "feature_snapshot_id", "state_id", "strategy_id")
_SUBJECT_FIELDS = (
    "run_id",
    "premarket_snapshot_id",
    "feature_snapshot_id",
    "result_id",
    "state_id",
    "strategy_id",
    "receipt_id",
    "bundle_ref",
    "verification_status",
    "reason_code",
)


def build_report_result_identity(
    *,
    storage_root: Path,
    run_id: str | None,
    trade_date: str | None,
    report_family: str,
    report_snapshot_id: str | None,
    report_identity: dict | None,
) -> dict[str, Any]:
    """Verify and project one registered Gold daily-close report."""

    root = _root(storage_root)
    family = _text(report_family) or _GOLD_REPORT_FAMILY
    safe_run_id = _safe_run_id(run_id)
    safe_trade_date = _safe_trade_date(trade_date)
    subject = _empty_subject(family)
    subject["run_id"] = safe_run_id
    if root is None:
        return _unavailable(subject, "gold_result_identity_storage_root_unavailable")
    baseline = _resolve_baseline(root)
    effective = _effective_baseline(baseline, root=root)
    if family != _GOLD_REPORT_FAMILY:
        return _identity(subject, effective, "gold_report_family_unverified", baseline=baseline)

    bundle = _bundle_path(root, safe_trade_date, safe_run_id)
    if bundle is None:
        reason = (
            "gold_report_bundle_path_invalid"
            if safe_run_id is not None and safe_trade_date is not None
            else "gold_report_bundle_unavailable"
        )
        return _identity(subject, effective, reason, baseline=baseline)

    subject["bundle_ref"] = _bundle_ref(root, bundle)
    manifest = _read_json(root, bundle / "report_manifest.json")
    subject.update(
        _declared_report_subject(
            report_identity=report_identity,
            manifest=manifest,
            run_id=safe_run_id,
            report_snapshot_id=report_snapshot_id,
            bundle_ref=subject["bundle_ref"],
        )
    )

    verification, reason = _verify_bundle(root, bundle)
    if verification is None:
        subject["verification_status"] = "unverified"
        subject["reason_code"] = reason
    else:
        receipt = getattr(verification, "receipt", None)
        current_feature_id = _text(getattr(verification, "current_feature_id", None))
        subject.update(_verified_subject(receipt, current_feature_id))
        valid, reason = _registered_fields_match(
            receipt=receipt,
            current_feature_id=current_feature_id,
            manifest=manifest,
            report_identity=report_identity,
            run_id=safe_run_id,
            trade_date=safe_trade_date,
            report_snapshot_id=report_snapshot_id,
        )
        subject["verification_status"] = "verified" if valid else "unverified"
        subject["reason_code"] = "gold_report_bundle_verified" if valid else reason

    return _identity(
        subject,
        effective,
        baseline=baseline,
    )


def build_mainline_result_identity(*, storage_root: Path, run_id: str | None) -> dict[str, Any]:
    """Project a legacy GoldMainlines result without assigning formal IDs."""

    root = _root(storage_root)
    safe_run_id = _safe_run_id(run_id)
    subject = _empty_subject("gold_mainlines")
    subject["run_id"] = safe_run_id
    if root is None:
        return _unavailable(subject, "gold_result_identity_storage_root_unavailable")
    baseline = _resolve_baseline(root)
    effective = _effective_baseline(baseline, root=root)
    if safe_run_id is None:
        reason = "gold_mainline_run_id_unavailable"
        subject["verification_status"] = "unavailable"
        subject["reason_code"] = reason
        return _identity(subject, effective, baseline=baseline)

    # The caller has already selected the legacy artifact.  Its run ID is
    # display metadata only; no legacy payload can claim the canonical head.
    subject["verification_status"] = "unverified"
    subject["reason_code"] = "gold_legacy_mainline_unverified"
    return _identity(
        subject,
        effective,
        baseline=baseline,
        relationship={"status": "unverified", "reason_code": subject["reason_code"]},
    )


def build_live_result_identity(*, storage_root: Path, baseline: dict) -> dict[str, Any]:
    """Project the already-resolved Gold baseline used by live strategy."""

    root = _root(storage_root)
    projection = baseline if isinstance(baseline, Mapping) else {}
    subject = _subject_from_baseline(projection, root=root)
    effective = _effective_baseline(projection, root=root)
    if effective is None:
        relationship = {"status": "unavailable", "reason_code": subject["reason_code"]}
    elif subject["verification_status"] == "verified":
        relationship = {
            "status": "same_effective_head",
            "reason_code": "gold_live_baseline_same_effective_head",
        }
    else:
        relationship = {"status": "unverified", "reason_code": subject["reason_code"]}
    return _identity(subject, effective, relationship=relationship)


def _identity(
    subject: dict[str, Any],
    effective: dict[str, Any] | None,
    reason: str | None = None,
    *,
    baseline: Mapping[str, Any] | None = None,
    relationship: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    if reason is not None:
        subject["verification_status"] = "unverified"
        subject["reason_code"] = reason
    return {
        "schema_version": RESULT_IDENTITY_SCHEMA_VERSION,
        "subject": subject,
        "effective_baseline": effective,
        "relationship": relationship or _relationship(subject, effective, baseline),
    }


def _unavailable(subject: dict[str, Any], reason: str) -> dict[str, Any]:
    subject["verification_status"] = "unavailable"
    subject["reason_code"] = reason
    return _identity(
        subject,
        None,
        relationship={"status": "unavailable", "reason_code": reason},
    )


def _empty_subject(kind: str) -> dict[str, Any]:
    return {"kind": kind, **{field: None for field in _SUBJECT_FIELDS}}


def _subject_from_baseline(baseline: Mapping[str, Any], *, root: Path | None) -> dict[str, Any]:
    subject = _empty_subject("gold_daily_close_baseline")
    for field in _SUBJECT_FIELDS:
        if field not in {"verification_status", "reason_code", "bundle_ref"}:
            subject[field] = _text(baseline.get(field))
    bundle_ref, bundle_run_id = _baseline_refs(root, baseline)
    subject["bundle_ref"] = bundle_ref
    subject["run_id"] = subject["run_id"] or bundle_run_id
    complete = all(subject[field] is not None for field in _CORE_IDS)
    if baseline.get("lineage_verified") is True and complete:
        status = "verified"
    elif subject["receipt_id"] is not None or not complete:
        status = "unverified"
    else:
        status = "unavailable"
    subject["verification_status"] = status
    subject["reason_code"] = _text(baseline.get("reason_code")) or "gold_daily_close_baseline_unavailable"
    return subject


def _effective_baseline(
    baseline: Mapping[str, Any], *, root: Path | None,
) -> dict[str, Any] | None:
    if not isinstance(baseline, Mapping) or baseline.get("lineage_verified") is not True:
        return None
    if any(_text(baseline.get(field)) is None for field in _CORE_IDS):
        return None
    bundle_ref, bundle_run_id = _baseline_refs(root, baseline)
    effective = _empty_subject("gold_daily_close_effective_head")
    for field in _SUBJECT_FIELDS:
        if field == "bundle_ref":
            effective[field] = bundle_ref
        elif field == "verification_status":
            effective[field] = "verified"
        elif field == "reason_code":
            effective[field] = _text(baseline.get("reason_code")) or "gold_daily_close_head_verified"
        else:
            effective[field] = _text(baseline.get(field))
    effective.update(
        status=_text(baseline.get("status")) or "unavailable",
        held=baseline.get("gold_head_held") is True,
        authority_ready=baseline.get("authority_ready") is True,
        quality_status=_text(baseline.get("quality_status")),
        strategy_status=_text(baseline.get("strategy_status")),
        decision_as_of=_text(baseline.get("decision_as_of")),
    )
    effective["run_id"] = _text(baseline.get("run_id")) or bundle_run_id
    return effective


def _relationship(
    subject: Mapping[str, Any],
    effective: Mapping[str, Any] | None,
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, str | None]:
    if effective is None:
        reason = _text(baseline.get("reason_code")) if isinstance(baseline, Mapping) else None
        return {"status": "unavailable", "reason_code": reason or "gold_effective_head_unavailable"}
    if subject.get("verification_status") != "verified":
        return {
            "status": "unverified",
            "reason_code": _text(subject.get("reason_code")) or "gold_result_identity_unverified",
        }
    subject_ids = [_text(subject.get(field)) for field in _CORE_IDS]
    effective_ids = [_text(effective.get(field)) for field in _CORE_IDS]
    if any(value is None for value in (*subject_ids, *effective_ids)):
        return {"status": "unverified", "reason_code": "gold_result_identity_incomplete"}
    if subject_ids == effective_ids:
        return {
            "status": "same_effective_head",
            "reason_code": "gold_result_identity_same_effective_head",
        }
    return {"status": "different_result", "reason_code": "gold_result_identity_different_result"}


def _verify_bundle(root: Path, bundle: Path) -> tuple[Any | None, str]:
    try:
        verification = verify_gold_daily_close_bundle(storage_root=root, bundle_path=bundle)
    except Exception:
        return None, "gold_report_bundle_verification_failed"
    if getattr(verification, "status", None) != "valid":
        return None, _text(getattr(verification, "reason_code", None)) or "gold_report_bundle_verification_failed"
    returned = _path_from_value(getattr(verification, "bundle_path", None))
    expected_ref = _bundle_ref(root, bundle)
    if returned is None or expected_ref is None or _bundle_ref(root, returned) != expected_ref:
        return None, "gold_report_bundle_path_mismatch"
    return verification, "gold_report_bundle_verified"


def _registered_fields_match(
    *,
    receipt: Any,
    current_feature_id: str | None,
    manifest: dict[str, Any] | None,
    report_identity: dict | None,
    run_id: str | None,
    trade_date: str | None,
    report_snapshot_id: str | None,
) -> tuple[bool, str]:
    """Compare registry metadata with the already verified canonical bundle."""

    if receipt is None or manifest is None or not isinstance(report_identity, Mapping):
        return False, "gold_report_identity_mismatch"
    if _text(getattr(receipt, "run_id", None)) != run_id:
        return False, "gold_report_identity_mismatch"
    if _date_text(getattr(receipt, "session_date", None)) != trade_date:
        return False, "gold_report_identity_mismatch"

    manifest_schema = _text(manifest.get("schema_version"))
    if manifest_schema not in _REPORT_MANIFEST_VERSIONS:
        return False, "gold_report_manifest_schema_invalid"
    expected_result_id = _text(getattr(receipt, "result_id", None))
    if expected_result_id is None or _text(manifest.get("authority_result_id")) != expected_result_id:
        return False, "gold_report_identity_mismatch"

    if manifest_schema == "gold_policy_report_manifest.v2":
        if (
            _text(manifest.get("asset")) != "XAUUSD"
            or _text(manifest.get("trade_date")) != trade_date
            or _text(manifest.get("run_id")) != run_id
            or _text(manifest.get("snapshot_id")) != current_feature_id
            or report_snapshot_id is None
            or _text(report_snapshot_id) != current_feature_id
        ):
            return False, "gold_report_identity_mismatch"
    elif report_snapshot_id is not None and _text(report_snapshot_id) != current_feature_id:
        return False, "gold_report_identity_mismatch"

    receipt_id = _text(getattr(receipt, "receipt_id", None))
    if _text(report_identity.get("canonical_receipt_id")) != receipt_id:
        return False, "gold_report_registry_receipt_mismatch"
    checks = (
        ("authority_result_id", expected_result_id, False),
        ("report_context_id", _text(manifest.get("context_id")), False),
        ("report_render_id", _text(manifest.get("render_id")), False),
        ("manifest_schema_version", manifest_schema, False),
        ("structured_schema_version", _REPORT_MANIFEST_VERSIONS[manifest_schema], False),
        ("canonical_receipt_revision_no", getattr(receipt, "revision_no", None), True),
        ("canonical_commit_action", _enum_text(getattr(receipt, "action", None)), False),
        (
            "publication_status",
            _text(manifest.get("publication_status")) or _text(manifest.get("report_status")),
            False,
        ),
    )
    for key, expected, numeric in checks:
        if not _optional_equal(report_identity, key, expected, numeric=numeric):
            return False, f"gold_report_registry_{key}_mismatch"
    return True, "gold_report_bundle_verified"


def _verified_subject(receipt: Any, current_feature_id: str | None) -> dict[str, Any]:
    return {
        "feature_snapshot_id": current_feature_id,
        "result_id": _text(getattr(receipt, "result_id", None)),
        "state_id": _text(getattr(receipt, "candidate_state_id", None)),
        "strategy_id": _text(getattr(receipt, "candidate_strategy_id", None)),
        "receipt_id": _text(getattr(receipt, "receipt_id", None)),
    }


def _declared_report_subject(
    *,
    report_identity: dict | None,
    manifest: dict[str, Any] | None,
    run_id: str | None,
    report_snapshot_id: str | None,
    bundle_ref: str | None,
) -> dict[str, Any]:
    identity = report_identity if isinstance(report_identity, Mapping) else {}
    return {
        "run_id": run_id,
        "premarket_snapshot_id": _text(identity.get("premarket_snapshot_id")),
        "feature_snapshot_id": _text(report_snapshot_id) or _text((manifest or {}).get("snapshot_id")),
        "result_id": _text(identity.get("authority_result_id")) or _text((manifest or {}).get("authority_result_id")),
        "state_id": _text(identity.get("candidate_state_id")),
        "strategy_id": _text(identity.get("candidate_strategy_id")),
        "receipt_id": _text(identity.get("canonical_receipt_id")),
        "bundle_ref": bundle_ref,
    }


def _resolve_baseline(root: Path) -> dict[str, Any]:
    try:
        value = resolve_verified_gold_baseline(storage_root=root, now=datetime.now(UTC))
    except Exception:
        return {
            "status": "invalid",
            "reason_code": "gold_daily_close_baseline_resolution_failed",
            "lineage_verified": False,
            "authority_ready": False,
            "gold_head_held": False,
        }
    if isinstance(value, Mapping):
        return dict(value)
    return {
        "status": "invalid",
        "reason_code": "gold_daily_close_baseline_invalid",
        "lineage_verified": False,
        "authority_ready": False,
        "gold_head_held": False,
    }


def _bundle_path(root: Path, trade_date: str | None, run_id: str | None) -> Path | None:
    if trade_date is None or run_id is None:
        return None
    candidate = root / _BUNDLE_BASE / trade_date / run_id / "daily_close"
    try:
        current = root
        for part in candidate.relative_to(root).parts:
            current /= part
            if current.is_symlink():
                return None
        if not candidate.resolve(strict=False).is_relative_to(root):
            return None
        return candidate
    except (OSError, ValueError):
        return None


def _bundle_ref(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(root) or not path.is_dir() or path.is_symlink():
            return None
        return resolved.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def _baseline_refs(root: Path | None, baseline: Mapping[str, Any]) -> tuple[str | None, str | None]:
    if root is None:
        return None, None
    ref: str | None = None
    explicit = _text(baseline.get("bundle_ref"))
    if explicit is not None:
        path = Path(explicit)
        if not path.is_absolute():
            path = root / path
        ref = _bundle_ref(root, path)
    if ref is None:
        refs = baseline.get("artifact_refs")
        if isinstance(refs, (list, tuple)):
            for item in refs:
                value = _text(item)
                if value is not None and value.endswith("/daily_close"):
                    ref = _bundle_ref(root, root / value)
                    if ref is not None:
                        break
    if ref is None:
        return None, None
    parts = PurePosixPath(ref).parts
    if (
        len(parts) != 5
        or parts[:2] != ("analysis", "gold_mainlines")
        or _safe_trade_date(parts[2]) is None
        or _safe_run_id(parts[3]) is None
        or parts[4] != "daily_close"
    ):
        return None, None
    return ref, parts[3]


def _read_json(root: Path, path: Path) -> dict[str, Any] | None:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or path.is_symlink() or not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _root(value: Path) -> Path | None:
    try:
        return Path(value).expanduser().resolve()
    except (OSError, TypeError, ValueError):
        return None


def _path_from_value(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value
    return Path(value) if isinstance(value, str) and value else None


def _safe_run_id(value: Any) -> str | None:
    value = _text(value)
    return value if value is not None and _RUN_ID.fullmatch(value) else None


def _safe_trade_date(value: Any) -> str | None:
    value = _text(value)
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.isoformat() == value else None


def _date_text(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, date) else _safe_trade_date(value)


def _optional_equal(mapping: Mapping[str, Any], key: str, expected: Any, *, numeric: bool = False) -> bool:
    if key not in mapping:
        return True
    if numeric:
        actual = mapping[key]
        return isinstance(actual, int) and not isinstance(actual, bool) and actual == expected
    return _text(mapping[key]) == _text(expected)


def _enum_text(value: Any) -> str | None:
    return _text(getattr(value, "value", value))


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


__all__ = [
    "RESULT_IDENTITY_SCHEMA_VERSION",
    "build_live_result_identity",
    "build_mainline_result_identity",
    "build_report_result_identity",
]
