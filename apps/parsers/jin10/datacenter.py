"""Parser for Jin10 datacenter JavaScript report payloads."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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
    freshness_status: str = "schema_changed"
    freshness_reason: str = "schema_changed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_datacenter_js(
    js_text: str,
    *,
    slug: str,
    report_name: str = "",
    source_refs: list[dict[str, Any]] | None = None,
    reference_date: str | None = None,
    stale_after_days: int = 45,
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
    as_of = _latest_as_of(rows)
    freshness_status, freshness_reason = _freshness(as_of, reference_date=reference_date, stale_after_days=stale_after_days)
    return Jin10DatacenterParsedReport(
        slug=slug,
        report_name=report_name,
        as_of=as_of,
        types=types,
        kinds=kinds,
        rows=rows,
        min_no=_coerce_int(payload.get("minNo") or payload.get("min_no")),
        max_no=_coerce_int(payload.get("maxNo") or payload.get("max_no")),
        checksum=_coerce_str(payload.get("md5") or payload.get("checksum")),
        source_refs=refs,
        freshness_status=freshness_status,
        freshness_reason=freshness_reason,
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


def _freshness(as_of: str | None, *, reference_date: str | None, stale_after_days: int) -> tuple[str, str]:
    if not as_of:
        return "schema_changed", "missing_as_of"
    parsed_as_of = _parse_datetime(as_of)
    if parsed_as_of is None:
        return "schema_changed", "invalid_as_of"
    reference = _parse_datetime(reference_date) if reference_date else datetime.now(timezone.utc)
    if reference is None:
        reference = datetime.now(timezone.utc)
    age_days = (reference.date() - parsed_as_of.date()).days
    if age_days < 0:
        return "ok_current", "future_or_same_period"
    if age_days > stale_after_days:
        return "ok_stale", "as_of_older_than_sla"
    return "ok_current", "within_sla"


def _parse_datetime(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if fmt.endswith("%S") else text[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


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


def datacenter_report_input_summary(
    parsed: Jin10DatacenterParsedReport,
    *,
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convert parsed datacenter report into a report input summary dict.

    The summary is suitable for inclusion in daily_market_brief.report_inputs
    or final report input sections. It never claims to be an official source.
    """
    data = parsed.to_dict()
    latest_row = data["rows"][0] if data["rows"] else {}
    latest_values = {
        str(v.get("kind")): str(v.get("value"))
        for v in latest_row.get("values", [])
        if isinstance(v, dict)
    }
    return {
        "source_key": "jin10_datacenter_reports",
        "slug": data["slug"],
        "report_name": data["report_name"],
        "as_of": data.get("as_of"),
        "status": data["status"],
        "freshness_status": data.get("freshness_status"),
        "freshness_reason": data.get("freshness_reason"),
        "provider_role": "supplemental_source",
        "verification_status": "single_source",
        "official_primary": False,
        "usable_for_production_conclusions": data.get("freshness_status") == "ok_current",
        "latest_values": latest_values,
        "row_count": len(data["rows"]),
        "types": data.get("types", []),
        "kinds": data.get("kinds", []),
        "source_refs": list(source_refs or data.get("source_refs", [])),
        "warnings": [
            "Jin10 datacenter data is supplemental only; official facts must be confirmed by FRED/CFTC/CME/BLS.",
            *(
                [f"Jin10 datacenter freshness is stale: as_of={data.get('as_of')}."]
                if data.get("freshness_status") == "ok_stale"
                else []
            ),
        ],
    }
