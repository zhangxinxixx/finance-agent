"""Normalize actual CME 305 settlement payloads, never FedWatch probabilities."""

import json
import math
import re
from datetime import date, datetime

PARSER_VERSION = "cme-fed-funds.v1"
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def parse_settlements(body: bytes, *, trade_date: date) -> dict:
    def invalid_constant(_):
        raise ValueError("non_finite_json")

    payload = json.loads(body, parse_constant=invalid_constant)
    if not isinstance(payload, dict):
        raise ValueError("object_required")
    required = {"settlements", "tradeDate", "dsHeader", "reportType", "empty", "updateTime"}
    if not required <= payload.keys():
        raise ValueError("missing_fields")
    if datetime.strptime(payload["tradeDate"], "%m/%d/%Y").date() != trade_date:
        raise ValueError("trade_date_mismatch")
    if payload["dsHeader"] != "30 Day Federal Funds Future":
        raise ValueError("product_mismatch")
    rows = payload["settlements"]
    if not isinstance(rows, list) or type(payload["empty"]) is not bool:
        raise ValueError("invalid_rows_or_empty_flag")
    warnings = ["additional_top_level_fields"] if payload.keys() - required else []
    result = {
        "parser_version": PARSER_VERSION,
        "trade_date": trade_date.isoformat(),
        "source_update_time_raw": payload["updateTime"],
        "source_time_timezone": None,
        "settlement_status": None,
        "rows": [],
        "warnings": warnings,
    }
    if payload["empty"]:
        if rows:
            raise ValueError("empty_flag_with_rows")
        return {**result, "data_status": "upstream_empty"}
    if not rows:
        raise ValueError("nonempty_flag_without_rows")
    status = {"Final": "FINAL", "Preliminary": "PRELIMINARY"}.get(payload["reportType"])
    if status is None:
        raise ValueError("unknown_settlement_status")
    result["settlement_status"] = status
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid_contract")
        if row.get("month") == "Total":
            continue
        month = row.get("month", "")
        if not isinstance(month, str) or not re.fullmatch(r"[A-Z]{3} \d{2}", month):
            raise ValueError("invalid_contract_month")
        if month[:3] not in MONTHS or month in seen:
            raise ValueError("invalid_or_duplicate_contract")
        seen.add(month)
        if not {"settle", "volume", "openInterest"} <= row.keys():
            raise ValueError("missing_contract_fields")
        raw_settle = row["settle"]
        if raw_settle in (None, "", "-"):
            settle = None
        else:
            if isinstance(raw_settle, bool):
                raise ValueError("invalid_settlement")
            settle = float(raw_settle)
            if not math.isfinite(settle):
                raise ValueError("nonfinite_settlement")

        def integer(value):
            if value in (None, "", "-"):
                return None
            if isinstance(value, bool) or not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)", str(value)):
                raise ValueError("invalid_volume_or_oi")
            return int(str(value).replace(",", ""))

        normalized = {
            "contract": month,
            "contract_month": date(2000 + int(month[-2:]), MONTHS.index(month[:3]) + 1, 1).isoformat(),
            "settle": settle,
            "volume": integer(row["volume"]),
            "open_interest": integer(row["openInterest"]),
        }
        result["rows"].append(normalized)
    if not result["rows"] or all(row["settle"] is None for row in result["rows"]):
        raise ValueError("no_usable_settlements")
    if any(None in (r["settle"], r["volume"], r["open_interest"]) for r in result["rows"]):
        warnings.append("missing_contract_values")
    return {**result, "data_status": "available"}
