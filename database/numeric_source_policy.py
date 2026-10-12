"""Numeric quarantine only; other sources still require freshness/lineage checks."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any


_TWELVE_DATA_DIAGNOSTIC_REASON = "jin10_incomplete_or_stale"
_TWELVE_DATA_SOURCE_KEY = "twelvedata_xauusd"
_TWELVE_DATA_CANDLE_SOURCES = frozenset(
    {
        "twelvedata_xauusd_1m",
        "twelvedata_xauusd_5m",
        "twelvedata_xauusd_15m",
        "twelvedata_xauusd_1h",
        "twelvedata_xauusd_4h",
        "twelvedata_xauusd_daily",
    }
)


def contains_jin10_source(value: Any) -> bool:
    """Inspect nested aggregate/cache lineage, not news or reading content."""
    if isinstance(value, str):
        return "jin10" in value.casefold() or "金十" in value
    if isinstance(value, Mapping):
        return any(contains_jin10_source(k) or contains_jin10_source(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_jin10_source(v) for v in value)
    return False


def _is_legacy_twelvedata_diagnostic(source: Any, value: Mapping[str, Any]) -> bool:
    """Recognize one historical fallback marker without treating it as lineage."""
    return (
        isinstance(source, str)
        and source in _TWELVE_DATA_CANDLE_SOURCES
        and value.get("provider") == "twelve_data"
        and value.get("source_key") == _TWELVE_DATA_SOURCE_KEY
        and value.get("source_role") == "fallback"
        and value.get("fallback_reason") == _TWELVE_DATA_DIAGNOSTIC_REASON
    )


def _remove_allowed_diagnostic(source: Any, value: Any) -> Any:
    """Remove only the exact legacy diagnostic value before recursive scanning.

    The diagnostic is allowed only inside an independently identified
    TwelveData fallback mapping. Every other key/value, including nested
    mappings and URL/path fields, remains subject to the original recursive
    Jin10 check.
    """
    if isinstance(value, Mapping):
        allowed = _is_legacy_twelvedata_diagnostic(source, value)
        return {
            key: _remove_allowed_diagnostic(source, item)
            for key, item in value.items()
            if not (
                allowed
                and key == "fallback_reason"
                and item == _TWELVE_DATA_DIAGNOSTIC_REASON
            )
        }
    if isinstance(value, list):
        return [_remove_allowed_diagnostic(source, item) for item in value]
    if isinstance(value, tuple):
        return tuple(_remove_allowed_diagnostic(source, item) for item in value)
    return value


def is_formal_numeric_source(source: str, source_ref: Any = None, raw_path: str | None = None) -> bool:
    return not contains_jin10_source(
        (source, _remove_allowed_diagnostic(source, source_ref), raw_path)
    )


def require_formal_numeric_source(source: str, source_ref: Any = None, raw_path: str | None = None) -> None:
    if not is_formal_numeric_source(source, source_ref, raw_path):
        raise ValueError("jin10_numeric_source_forbidden: Jin10 is news/historical reading only")


def quarantine_numeric_payload(value: Any, *, inherited_source: str = "", inherited_forbidden: bool = False) -> Any:
    """Project legacy numeric rows without modifying their stored artifacts.

    Call only for numeric sections. News prose and its citations belong to the
    separate news inputs, not this projection.
    """
    if isinstance(value, list):
        return [quarantine_numeric_payload(item, inherited_source=inherited_source, inherited_forbidden=inherited_forbidden) for item in value]
    if not isinstance(value, Mapping):
        if inherited_forbidden and isinstance(value, (int, float)) and not isinstance(value, bool):
            return None
        return value
    source = str(value.get("source") or value.get("provider") or inherited_source)
    financial_fields = {"value", "price", "open", "high", "low", "close", "bid", "ask", "previous_value",
                        "change", "change_pct", "daily_change", "change_1w", "weekly_change", "weekly_anchor_value"}
    forbidden = inherited_forbidden or not is_formal_numeric_source(source, value.get("source_refs") or value.get("source_ref"), value.get("raw_path"))
    projected = {key: item if key in {"source_refs", "source_ref"} else quarantine_numeric_payload(item, inherited_source=source, inherited_forbidden=forbidden)
                 for key, item in value.items()}
    if forbidden:
        projected.update({key: None for key in financial_fields.intersection(value)})
        projected.update(status="unavailable", reason="jin10_numeric_source_forbidden")
    return projected
