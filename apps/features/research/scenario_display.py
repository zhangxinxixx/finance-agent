"""Safe presentation of rule-based scenario weights.

Scenario weights describe the research engine's rule score.  This module only
normalizes them for display and never presents them as calibrated probabilities.
"""

from __future__ import annotations

from copy import deepcopy
from math import floor, isfinite
from typing import Any, Mapping, Sequence

SCENARIO_DISPLAY_SCHEMA_VERSION = "scenario_display.v1"
_DISPLAY_MODES = {"5pct", "level"}


def build_scenario_display(
    scenarios: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    mode: str = "5pct",
) -> dict[str, Any]:
    """Return raw and display scenario weights with explicit semantics.

    The default display rounds normalized weights to five-percent buckets using
    a largest-remainder allocation so the displayed total is exactly 100.
    ``mode="level"`` adds High/Medium/Low labels without claiming statistical
    calibration.  Invalid or empty weights remain visible but do not receive a
    fabricated display value.
    """

    display_mode = _mode(mode)
    rows = _rows(scenarios)
    raw_scenarios = deepcopy(rows)
    parsed: list[float | None] = [_weight(_raw_weight(row)) for row in rows]
    valid = (
        bool(rows)
        and all(value is not None and value >= 0 for value in parsed)
        and len(
            {str(row.get("id") or row.get("scenario") or row.get("name") or index) for index, row in enumerate(rows)}
        )
        == len(rows)
    )
    total = sum(value for value in parsed if value is not None) if valid else 0.0
    normalized = [value / total * 100.0 for value in parsed] if valid and total > 0 else [None] * len(rows)
    display_values = _round_to_five(normalized) if display_mode == "5pct" else [None] * len(rows)
    result_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        identifier = str(row.get("id") or row.get("scenario") or row.get("name") or index)
        item = deepcopy(row)
        item["id"] = identifier
        item["raw_weight"] = _raw_weight(row)
        item["normalized_weight_pct"] = _round(normalized[index], 4) if normalized[index] is not None else None
        item["display_weight_pct"] = display_values[index]
        item["display_level"] = _level(normalized[index]) if normalized[index] is not None else None
        item["uncalibrated"] = True
        result_rows.append(item)

    status = "available" if valid and total > 0 else "partial"
    return {
        "schema_version": SCENARIO_DISPLAY_SCHEMA_VERSION,
        "status": status,
        "display_mode": display_mode,
        "weight_semantics": "rule_weight_display",
        "raw_scenarios": raw_scenarios,
        "raw_total": _round(total, 8) if valid else None,
        "scenarios": result_rows,
        "display_weights_sum": sum(item["display_weight_pct"] or 0 for item in result_rows)
        if status == "available" and display_mode == "5pct"
        else None,
        "uncalibrated": True,
        "is_probability": False,
        "calibration_status": "uncalibrated",
        "brier_score": None,
        "calibration": {"status": "uncalibrated", "brier_score": None},
        "note": "展示权重按规则总和归一化，不是统计概率；当前没有校准或 Brier 评估。",
        "reason": None if status == "available" else "scenario weights missing, invalid, duplicated, or sum to zero",
    }


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        nested = value.get("scenarios")
        if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes, bytearray)):
            return [dict(item) for item in nested if isinstance(item, Mapping)]
        engine = value.get("scenario_engine")
        if isinstance(engine, Mapping):
            return _rows(engine)
        for key in ("weights", "normalized_weights", "weight_by_scenario"):
            nested_weights = value.get(key)
            if isinstance(nested_weights, Mapping):
                rows = []
                for identifier, weight in nested_weights.items():
                    rows.append({"id": identifier, "weight": weight})
                return rows
        result: list[dict[str, Any]] = []
        for key, item in value.items():
            if isinstance(item, Mapping):
                row = dict(item)
                row.setdefault("id", key)
                result.append(row)
            elif _weight(item) is not None:
                result.append({"id": key, "weight": item})
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _mode(value: Any) -> str:
    normalized = str(value or "5pct").strip().lower().replace("%", "").replace("_", "").replace("/", "")
    return "level" if normalized in {"level", "levels", "band", "bands", "highmedium", "qualitative"} else "5pct"


def _weight(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        value = value.strip().rstrip("%").strip()
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _raw_weight(row: Mapping[str, Any]) -> Any:
    """Resolve both feature-engine and workflow scenario field names."""

    for key in ("weight", "weight_pct", "raw_weight", "normalized_weight"):
        if key in row:
            return row[key]
    return None


def _round_to_five(values: Sequence[float | None]) -> list[int | None]:
    if not values or any(value is None for value in values):
        return [None] * len(values)
    units_exact = [float(value) / 5.0 for value in values if value is not None]
    units = [floor(value) for value in units_exact]
    remainder = 20 - sum(units)
    order = sorted(range(len(units)), key=lambda index: (units_exact[index] - units[index], -index), reverse=True)
    for index in order[: max(0, remainder)]:
        units[index] += 1
    return [unit * 5 for unit in units]


def _level(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 60:
        return "High"
    if value >= 30:
        return "Medium"
    return "Low"


def _round(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


__all__ = ["SCENARIO_DISPLAY_SCHEMA_VERSION", "build_scenario_display"]
