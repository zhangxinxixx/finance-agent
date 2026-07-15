"""Canonical JSON and content hashing for immutable analysis state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel


VOLATILE_KEYS = frozenset({"id", "created_at", "updated_at"})


def canonical_json(value: Any, *, exclude_keys: frozenset[str] = VOLATILE_KEYS) -> str:
    """Serialize data deterministically after removing top-level volatile fields."""

    normalized = _normalize(value, exclude_keys=exclude_keys, is_root=True)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_hash(value: Any, *, exclude_keys: frozenset[str] = VOLATILE_KEYS) -> str:
    """Return SHA256 over canonical JSON rather than database identity metadata."""

    return hashlib.sha256(canonical_json(value, exclude_keys=exclude_keys).encode("utf-8")).hexdigest()


def _normalize(value: Any, *, exclude_keys: frozenset[str], is_root: bool = False) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item, exclude_keys=exclude_keys)
            for key, item in value.items()
            if not is_root or str(key) not in exclude_keys
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item, exclude_keys=exclude_keys) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value
