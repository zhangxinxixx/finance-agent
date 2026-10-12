"""Small, dependency-free guards for cleaned derived outputs.

The cleanup worker records a reader tombstone in the existing payload/metadata
columns.  Readers must inspect that marker before opening a file or projecting
the persisted body.  Keeping this helper free of ORM imports makes it safe for
all read paths, including old SQLite schemas and filesystem-only fallbacks.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


OUTPUT_CLEANUP_KEY = "output_cleanup"
PURGED_OUTPUT_STATUS = "purged"
FAIL_CLOSED_AGENT_NAMES = ("coordinator_agent", "coordinator", "research_input_validation")


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def output_cleanup_metadata(value: Any) -> dict[str, Any] | None:
    """Return a normalized ``output_cleanup`` marker, if one is present.

    ``value`` may be a metadata/payload mapping, a serialized metadata column,
    or an ORM row.  The row form is intentionally limited to the existing
    fields used by the cleanup contract; no model import or schema migration is
    needed for old databases.
    """

    mapping = _as_mapping(value)
    if mapping is not None:
        marker = _as_mapping(mapping.get(OUTPUT_CLEANUP_KEY))
        if (
            marker is not None
            and marker.get("schema_version") == 1
            and str(marker.get("status") or "").strip().lower() == PURGED_OUTPUT_STATUS
        ):
            return dict(marker)
        # A few callers pass the marker itself after selecting JSON metadata.
        if (
            mapping.get("schema_version") == 1
            and str(mapping.get("status") or "").strip().lower() == PURGED_OUTPUT_STATUS
        ):
            return dict(mapping)

    # ``output_cleanup`` is also used as the label for SQL JSON projections.
    # Readers intentionally select that marker instead of hydrating a whole
    # payload, so accept the projection label alongside the persisted fields.
    for attribute in (
        "output_cleanup",
        "payload_output_cleanup",
        "report_metadata",
        "artifact_metadata",
        "metadata",
        "metadata_json",
        "payload",
    ):
        candidate = getattr(value, attribute, None)
        if candidate is None or candidate is value:
            continue
        marker = output_cleanup_metadata(candidate)
        if marker is not None:
            return marker
    return None


def is_output_purged(value: Any) -> bool:
    """Return whether a persisted output is reader-tombstoned.

    The explicit row status is checked as well as the nested marker because
    ``ReportArtifact.status`` is part of the public cleanup contract while
    ``AgentOutput`` keeps its original failed status for audit purposes.
    """

    marker = output_cleanup_metadata(value)
    if marker is not None and str(marker.get("status") or "").strip().lower() == PURGED_OUTPUT_STATUS:
        return True
    status = getattr(value, "status", None)
    return str(status or "").strip().lower() == PURGED_OUTPUT_STATUS


def purged_output_summary(value: Any) -> dict[str, Any] | None:
    """Expose only tombstone identity, never the cleaned output body."""

    marker = output_cleanup_metadata(value)
    if marker is None or str(marker.get("status") or "").strip().lower() != PURGED_OUTPUT_STATUS:
        return None
    return {
        key: marker[key]
        for key in (
            "schema_version",
            "status",
            "reason_codes",
            "purged_at",
            "original_payload_sha256",
            "run_id",
            "snapshot_id",
        )
        if key in marker
    }


__all__ = [
    "OUTPUT_CLEANUP_KEY",
    "PURGED_OUTPUT_STATUS",
    "FAIL_CLOSED_AGENT_NAMES",
    "is_output_purged",
    "output_cleanup_metadata",
    "purged_output_summary",
]
