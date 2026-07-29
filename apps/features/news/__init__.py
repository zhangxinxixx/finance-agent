"""Deterministic news-derived feature contracts."""

from .formal_events import (
    OfficialEvent,
    OfficialEventCandleReference,
    OfficialEventSnapshot,
    OfficialEventSourceReference,
    archive_official_event_snapshot,
    build_official_event_snapshot,
)

__all__ = [
    "OfficialEvent",
    "OfficialEventCandleReference",
    "OfficialEventSnapshot",
    "OfficialEventSourceReference",
    "archive_official_event_snapshot",
    "build_official_event_snapshot",
]
