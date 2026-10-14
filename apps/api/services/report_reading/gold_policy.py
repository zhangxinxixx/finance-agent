"""Gold registry read-model projection; never reads another report or grants trade authority."""

from __future__ import annotations

from typing import Any, Iterable

from apps.api.schemas.common import ReviewStatus
from apps.api.services.research_identity import build_research_identity


_IDENTITY_KEYS = (
    "report_context_id",
    "report_render_id",
    "authority_result_id",
    "canonical_receipt_id",
    "canonical_receipt_revision_no",
    "canonical_commit_action",
    "manifest_schema_version",
    "structured_schema_version",
    "publication_status",
)
_PUBLICATION_MODES = {"accepted": "accepted", "observe": "observe", "degraded": "observe"}
_COMMIT_ACTIONS = {"bootstrap", "advance", "maintain", "hold"}


def project_gold_policy_report_identity(metadata: dict[str, Any]) -> dict[str, Any] | None:
    identity: dict[str, Any] = {}
    for key in _IDENTITY_KEYS:
        value = metadata.get(key)
        if key == "canonical_receipt_revision_no":
            if type(value) is int and value > 0:
                identity[key] = value
        elif isinstance(value, str) and value.strip():
            if key == "publication_status" and value not in _PUBLICATION_MODES:
                continue
            if key == "canonical_commit_action" and value not in _COMMIT_ACTIONS:
                continue
            identity[key] = value
    return identity or None


def _contains_snapshot(value: Any, snapshot_id: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_snapshot(item, snapshot_id) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_snapshot(item, snapshot_id) for item in value)
    return value == snapshot_id


def project_gold_policy_research_identity(item: Any, snapshot: Any) -> dict[str, Any] | None:
    """Reuse detail's identity contract only with an exact persisted snapshot binding."""
    if not isinstance(snapshot, dict) or any(
        snapshot.get(key) != str(getattr(item, key)) for key in ("snapshot_id", "run_id", "trade_date")
    ):
        return None
    return build_research_identity(
        report_id=item.report_id,
        run_id=item.run_id,
        snapshot_id=item.snapshot_id,
        trade_date=str(item.trade_date),
        snapshot=snapshot,
        generated_at=item.updated_at or item.created_at,
    )


def project_gold_policy_report(item: Any, artifacts: Iterable[Any]) -> dict[str, Any]:
    """Use the same row and its registry artifact bindings for index and detail.

    The existing verified registry maps accepted to live/snapshot_bound and
    observe/degraded to partial/needs_review. A complete, consistent persisted
    registry record allows that mapping; availability alone proves nothing.
    """
    metadata = item.report_metadata if isinstance(item.report_metadata, dict) else {}
    artifacts = list(artifacts)
    publication = metadata.get("publication_status")
    mode = metadata.get("output_mode")
    pair_valid = (
        isinstance(publication, str) and publication in _PUBLICATION_MODES and mode == _PUBLICATION_MODES[publication]
    )
    if not pair_valid:
        publication = mode = None
    identity = project_gold_policy_report_identity(metadata)
    if identity and publication is None:
        identity.pop("publication_status", None)
        identity = identity or None

    snapshot_bound = bool(item.snapshot_id and _contains_snapshot(metadata.get("input_snapshot_ids"), item.snapshot_id))
    row_conflict = any(
        metadata.get(key) not in (None, "", getattr(item, key)) for key in ("report_id", "run_id", "snapshot_id")
    ) or bool(item.snapshot_id and metadata.get("input_snapshot_ids") and not snapshot_bound)
    artifact_metadata = [
        artifact.artifact_metadata if isinstance(artifact.artifact_metadata, dict) else {} for artifact in artifacts
    ]
    receipt = metadata.get("canonical_receipt_id")
    receipt_conflict = any(
        any(
            values.get(artifact_key) not in (None, "", metadata.get(report_key))
            for artifact_key, report_key in (
                ("receipt_id", "canonical_receipt_id"),
                ("receipt_revision_no", "canonical_receipt_revision_no"),
                ("canonical_commit_action", "canonical_commit_action"),
            )
        )
        for values in artifact_metadata
    )
    if any(
        values.get("publication_status") not in (None, "", metadata.get("publication_status"))
        for values in artifact_metadata
    ):
        publication = mode = None
        pair_valid = False
        if identity:
            identity.pop("publication_status", None)
            identity = identity or None
    if row_conflict or receipt_conflict:
        identity = None

    trusted = (
        metadata.get("writer") == "register_gold_policy_report_bundle"
        and bool(item.run_id and item.trade_date)
        and item.report_id == f"gold_policy_daily:{item.trade_date}:{item.run_id}"
        and snapshot_bound
        and not row_conflict
        and not receipt_conflict
        and all(
            isinstance(metadata.get(key), str) and metadata[key].strip()
            for key in ("canonical_receipt_id", "authority_result_id", "report_context_id", "report_render_id")
        )
        and type(metadata.get("canonical_receipt_revision_no")) is int
        and metadata["canonical_receipt_revision_no"] > 0
        and isinstance(metadata.get("canonical_commit_action"), str)
        and metadata["canonical_commit_action"] in _COMMIT_ACTIONS
        and bool(artifacts)
        and all(
            artifact.report_id == item.report_id
            and values.get("receipt_id") == receipt
            and values.get("receipt_revision_no") == metadata["canonical_receipt_revision_no"]
            and values.get("canonical_commit_action") == metadata.get("canonical_commit_action")
            and values.get("publication_status") == publication
            for artifact, values in zip(artifacts, artifact_metadata)
        )
    )
    permission = None
    if trusted and pair_valid:
        explicit = metadata.get("publish_allowed")
        if "publish_allowed" not in metadata or isinstance(explicit, bool):
            if publication in {"observe", "degraded"} or explicit is False:
                permission = False
            elif item.lifecycle_status in {"archived", "needs_review"} or item.data_status in {
                "partial",
                "stale",
                "fallback",
                "mock",
                "manual_required",
                "unavailable",
            }:
                permission = False
            elif item.data_status == "live" and item.lifecycle_status in {"snapshot_bound", "published", "exported"}:
                permission = True
    review = metadata.get("review_status")
    if not isinstance(review, str) or review not in {status.value for status in ReviewStatus}:
        review = None
    return {
        "publication_status": publication,
        "output_mode": mode,
        "publish_allowed": permission,
        "review_status": review,
        "report_identity": identity,
    }
