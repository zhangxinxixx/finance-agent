"""Shared runtime switches for optional external data sources."""

from __future__ import annotations

import os


_DISABLE_JIN10_ENV = "FINANCE_AGENT_DISABLE_JIN10"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def jin10_disabled() -> bool:
    """Return whether Jin10 access is explicitly disabled at runtime."""

    return os.environ.get(_DISABLE_JIN10_ENV, "").strip().casefold() in _TRUE_VALUES
