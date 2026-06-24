"""Parser for Jin10 datacenter JavaScript report payloads."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Jin10DatacenterParsedReport:
    slug: str
    report_name: str = ""
    as_of: str | None = None
    types: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    min_no: int | None = None
    max_no: int | None = None
    checksum: str | None = None
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    provider_role: str = "supplemental_source"
    status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_datacenter_js(
    js_text: str,
    *,
    slug: str,
    report_name: str = "",
    source_refs: list[dict[str, Any]] | None = None,
) -> Jin10DatacenterParsedReport:
    """Parse ``var dataCenter_data = {...}`` into a normalized report."""
    refs = list(source_refs or [])
    object_text = _extract_assignment_object(js_text, "dataCenter_data")
    if object_text is None:
        return _schema_changed(
            slug=slug,
            report_name=report_name,
            source_refs=refs,
            reason_code="missing_dataCenter_data",
            reason="Jin10 datacenter JS did not contain dataCenter_data assignment",
        )

    try:
        payload = json.loads(object_text)
    except json.JSONDecodeError as exc:
        return _schema_changed(
            slug=slug,
            report_name=report_name,
            source_refs=refs,
            reason_code="invalid_dataCenter_json",
            reason=f"{type(exc).__name__}: {exc}",
        )
    if not isinstance(payload, dict):
        return _schema_changed(
            slug=slug,
            report_name=report_name,
            source_refs=refs,
            reason_code="invalid_dataCenter_payload",
            reason="dataCenter_data is not an object",
        )

    items = payload.get("list")
    if not isinstance(items, list):
        return _schema_changed(
            slug=slug,
            report_name=report_name,
            source_refs=refs,
            reason_code="missing_report_list",
            reason="dataCenter_data.list is not a list",
        )

    types = _string_list(payload.get("types"))
    kinds = _string_list(payload.get("kinds"))
    rows = [_normalize_row(item, types=types, kinds=kinds) for item in items if isinstance(item, dict)]
    return Jin10DatacenterParsedReport(
        slug=slug,
        report_name=report_name,
        as_of=_latest_as_of(rows),
        types=types,
        kinds=kinds,
        rows=rows,
        min_no=_coerce_int(payload.get("minNo") or payload.get("min_no")),
        max_no=_coerce_int(payload.get("maxNo") or payload.get("max_no")),
        checksum=_coerce_str(payload.get("md5") or payload.get("checksum")),
        source_refs=refs,
    )


def _schema_changed(
    *,
    slug: str,
    report_name: str,
    source_refs: list[dict[str, Any]],
    reason_code: str,
    reason: str,
) -> Jin10DatacenterParsedReport:
    refs = list(source_refs)
    refs.append(
        {
            "source_key": "jin10_datacenter_reports",
            "status": "schema_changed",
            "reason_code": reason_code,
            "reason": reason,
        }
    )
    return Jin10DatacenterParsedReport(
        slug=slug,
        report_name=report_name,
        rows=[],
        source_refs=refs,
        status="schema_changed",
    )


def _extract_assignment_object(js_text: str, variable_name: str) -> str | None:
    marker = js_text.find(variable_name)
    if marker < 0:
        return None
    equals = js_text.find("=", marker + len(variable_name))
    if equals < 0:
        return None
    start = js_text.find("{", equals)
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    quote = ""
    for idx in range(start, len(js_text)):
        ch = js_text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                in_string = False
            continue
        if ch in ("'", '"'):
            in_string = True
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return js_text[start : idx + 1]
    return None


def _normalize_row(item: dict[str, Any], *, types: list[str], kinds: list[str]) -> dict[str, Any]:
    datas = item.get("datas")
    values: list[dict[str, str]] = []
    if isinstance(datas, dict):
        data_types = types or [str(key) for key in datas.keys()]
        for type_name in data_types:
            raw_values = datas.get(type_name)
            if not isinstance(raw_values, list):
                continue
            for idx, raw_value in enumerate(raw_values):
                kind = kinds[idx] if idx < len(kinds) else f"value_{idx}"
                values.append(
                    {
                        "type": str(type_name),
                        "kind": str(kind),
                        "value": str(raw_value),
                    }
                )
    return {
        "date": _normalize_date(item.get("date")),
        "data_time": _coerce_str(item.get("dataTime") or item.get("data_time")),
        "values": values,
        "raw": item,
    }


def _latest_as_of(rows: list[dict[str, Any]]) -> str | None:
    candidates = [
        str(row.get("data_time") or row.get("date") or "")
        for row in rows
        if row.get("data_time") or row.get("date")
    ]
    return max(candidates) if candidates else None


def _normalize_date(value: Any) -> str:
    raw = str(value or "")
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
