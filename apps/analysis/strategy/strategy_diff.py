"""Deterministic, read-only diffs for ``live_strategy.v1`` read models.

The diff deliberately describes observed value changes only.  It does not infer
why a strategy changed, whether an event should trigger a recompute, or what an
institution may be doing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

DIFF_SCHEMA_VERSION = "live_strategy.diff.v1"

# ``updated_at`` is the only currently approved non-decision timestamp.  Keep
# this allowlist path-specific so a future timestamp inside event evidence is
# not silently hidden from the audit trail.
IGNORED_PATHS: frozenset[tuple[str, ...]] = frozenset({("updated_at",)})

_MISSING = object()


def diff_live_strategy(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic diff between two live strategy read models.

    Mapping keys are traversed in canonical (lexicographic) order.  Sequences
    retain their original order and are compared by index, so a reordered list
    is visible as a change rather than being treated as a set.
    """

    if not isinstance(previous, Mapping) or not isinstance(current, Mapping):
        raise TypeError("previous and current must be mappings")

    changes: list[dict[str, Any]] = []
    _compare(previous, current, (), changes)
    result_without_id = {
        "schema_version": DIFF_SCHEMA_VERSION,
        "from_strategy_id": _text_or_none(previous.get("strategy_id")),
        "to_strategy_id": _text_or_none(current.get("strategy_id")),
        "from_strategy_version": _text_or_none(previous.get("strategy_version")),
        "to_strategy_version": _text_or_none(current.get("strategy_version")),
        "changed": bool(changes),
        "changes": changes,
    }
    canonical = _canonical_json(result_without_id)
    result = {
        **result_without_id,
        "diff_id": f"diff-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}",
    }
    return result


def _compare(previous: Any, current: Any, path: tuple[str, ...], changes: list[dict[str, Any]]) -> None:
    if path in IGNORED_PATHS:
        return
    if previous is _MISSING or current is _MISSING:
        if previous is not _MISSING and current is not _MISSING:
            return
        _append_change(path, previous, current, changes)
        return

    if isinstance(previous, Mapping) and isinstance(current, Mapping):
        keys = set(previous) | set(current)
        for key in sorted(keys, key=_canonical_key):
            if not isinstance(key, str):
                raise TypeError("strategy diff mapping keys must be strings")
            _compare(previous.get(key, _MISSING), current.get(key, _MISSING), path + (key,), changes)
        return

    if _is_sequence(previous) and _is_sequence(current):
        length = max(len(previous), len(current))
        for index in range(length):
            old = previous[index] if index < len(previous) else _MISSING
            new = current[index] if index < len(current) else _MISSING
            _compare(old, new, path + (f"[{index}]",), changes)
        return

    if _canonical_json(previous) != _canonical_json(current):
        _append_change(path, previous, current, changes)


def _append_change(path: tuple[str, ...], previous: Any, current: Any, changes: list[dict[str, Any]]) -> None:
    changes.append(
        {
            "path": _format_path(path),
            "old_value": None if previous is _MISSING else previous,
            "new_value": None if current is _MISSING else current,
            "old_present": previous is not _MISSING,
            "new_present": current is not _MISSING,
        }
    )


def _format_path(path: tuple[str, ...]) -> str:
    if not path:
        return "$"
    result = ""
    for part in path:
        if part.startswith("["):
            result += part
        else:
            result = f"{result}.{part}" if result else part
    return result


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _canonical_key(value: Any) -> str:
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


__all__ = ["DIFF_SCHEMA_VERSION", "IGNORED_PATHS", "diff_live_strategy"]
