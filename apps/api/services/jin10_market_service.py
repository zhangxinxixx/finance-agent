"""Compatibility response for retired Jin10 numeric market routes."""

from __future__ import annotations

from typing import Any


def jin10_unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "quotes": {},
        "counts": {},
        "kline_codes": [],
    }
