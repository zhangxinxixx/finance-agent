"""Strict parser for the public CME FedWatch comparison table.

The free QuikStrike iframe is an HTML application, not the paid FedWatch API.
This module deliberately has no guessed JSON schema.  It accepts only the
semantic table CME documents for the free tool: target-rate ranges in basis
points and the ``NOW``, ``1 DAY``, ``1 WEEK`` and ``1 MONTH`` columns.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo


PARSER_VERSION = "fedwatch-free-html-v2"
COMPARISON_WINDOWS = ("current", "1d", "1w", "1m")
_WINDOW_LABELS = {
    "current": re.compile(r"\b(?:now|current)\b", re.IGNORECASE),
    "1d": re.compile(r"\b1\s*day\b", re.IGNORECASE),
    "1w": re.compile(r"\b1\s*week\b", re.IGNORECASE),
    "1m": re.compile(r"\b1\s*month\b", re.IGNORECASE),
}
_MONTH_FORMATS = (
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%B %d %Y",
)
_RATE_NUMBER = r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_RATE_RANGE_RE = re.compile(rf"(?<![\d,])({_RATE_NUMBER})\s*[-–—]\s*({_RATE_NUMBER})(?![\d,])")
_PERCENT_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*%\s*$")
_AS_OF_RE = re.compile(
    r"\bdata\s+as\s+of\s+"
    r"(?P<date>\d{1,2}\s+(?:[A-Za-z]{3,9}|\d{1,2}月)\s+\d{4})"
    r"(?:\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?))?"
    r"(?:\s+(?P<zone>CT|CST|CDT))?\b",
    re.IGNORECASE,
)
_MEETING_TITLE_RE = re.compile(
    r"target\s+rate\s+probabilities\s+for\s+"
    r"(?P<date>\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s+fed\s+meeting",
    re.IGNORECASE,
)


class FedWatchParseError(ValueError):
    """Raised when a response cannot safely become normalized FedWatch rows."""


class _SemanticTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.text_parts: list[str] = []
        self._table_depth = 0
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._parents: list[tuple] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag == "table":
            self._parents.append((self._table, self._row, self._cell_parts))
            self._table_depth = 1
            self._table, self._row, self._cell_parts = [], None, None
        elif self._table_depth == 1 and tag == "tr":
            self._row = []
        elif self._table_depth == 1 and tag in {"td", "th"}:
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._table_depth == 1 and tag in {"td", "th"} and self._cell_parts is not None:
            if self._row is not None:
                self._row.append(_clean_text(" ".join(self._cell_parts)))
            self._cell_parts = None
        elif self._table_depth == 1 and tag == "tr" and self._row is not None:
            if any(self._row):
                assert self._table is not None
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._parents:
            if self._table:
                self.tables.append(self._table)
            self._table, self._row, self._cell_parts = self._parents.pop()
            self._table_depth = 1 if self._parents else 0

    def handle_data(self, data: str) -> None:
        cleaned = _clean_text(data)
        if not cleaned:
            return
        self.text_parts.append(cleaned)
        if self._cell_parts is not None:
            self._cell_parts.append(cleaned)


def parse_fedwatch_free_payload(payload: bytes, *, content_type: str | None = None) -> dict[str, Any]:
    """Parse an observed public iframe response into contract rows.

    Unknown JSON is rejected rather than interpreted as the separately sold
    FedWatch API.  The caller must retain the raw bytes when this raises.
    """

    if not payload:
        raise FedWatchParseError("FedWatch response body is empty")
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type == "application/json" or payload.lstrip().startswith((b"{", b"[")):
        raise FedWatchParseError("unrecognized structured payload; no verified free JSON schema is registered")
    try:
        html = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FedWatchParseError("FedWatch HTML is not valid UTF-8") from exc
    return parse_fedwatch_free_html(html)


def parse_fedwatch_free_html(html: str) -> dict[str, Any]:
    """Parse CME's semantic free-tool comparison table.

    The extractor uses visible labels instead of ASP.NET control IDs.  It does
    not execute scripts, submit postbacks, or infer unavailable meetings.
    """

    lowered = html.lower()
    if "unexpected null referrer" in lowered or "access to quikstrike has been denied" in lowered:
        raise FedWatchParseError("QuikStrike denied access because the official referrer session was not accepted")
    if "there was a problem loading this content or tool" in lowered:
        raise FedWatchParseError("QuikStrike returned its tool error page")

    parser = _SemanticTableParser()
    parser.feed(html)
    parser.close()
    visible_text = _clean_text(" ".join(parser.text_parts))
    current_as_of = _parse_current_as_of(visible_text)
    meeting_date, contract_ref = _parse_meeting_context(parser.tables, visible_text)
    table, header_index, windows = _find_probability_table(parser.tables)

    candidate_rows: list[dict[str, Any]] = []
    precision: dict[str, str] = {"current": "second"}
    window_as_of: dict[str, str] = {"current": current_as_of}
    valid_windows = []
    for column_index, window, header in windows:
        if window == "current":
            valid_windows.append((column_index, window, header))
            continue
        source_date = _date_from_text(header)
        if source_date is None:
            has_values = any(column_index < len(row) and row[column_index].strip()
                             for row in table[header_index + 1:]
                             if row and _RATE_RANGE_RE.search(row[0]))
            if not has_values:
                continue  # Newly listed distant meetings have blank history.
            raise FedWatchParseError(f"{window} comparison header has no actual source date")
        window_as_of[window] = datetime.combine(source_date, time.min, tzinfo=timezone.utc).isoformat()
        precision[window] = "date"
        valid_windows.append((column_index, window, header))

    for raw_row in table[header_index + 1 :]:
        if not raw_row or not _RATE_RANGE_RE.search(raw_row[0]):
            continue
        range_match = _RATE_RANGE_RE.search(raw_row[0])
        assert range_match is not None
        target_low = float(range_match.group(1).replace(",", "")) / 100.0
        target_high = float(range_match.group(2).replace(",", "")) / 100.0
        for column_index, window, _header in valid_windows:
            if column_index >= len(raw_row) or not raw_row[column_index].strip():
                continue
            probability = _parse_percent_probability(raw_row[column_index])
            candidate_rows.append(
                {
                    "meeting_date": meeting_date,
                    "contract_ref": contract_ref,
                    "comparison_window": window,
                    "as_of": window_as_of[window],
                    "target_low": target_low,
                    "target_high": target_high,
                    "probability": probability,
                }
            )

    rows, warnings, coverage = normalize_fedwatch_rows(candidate_rows)
    coverage["meeting_scope"] = "selected_rendered_meeting_only"
    coverage["all_future_meetings"] = False
    warnings.append(
        "HTML fallback does not infer unrendered meeting tabs; coverage is limited to the selected rendered meeting"
    )
    for window, value in precision.items():
        coverage["meetings"][meeting_date]["window_precision"][window] = value
    date_only = sorted(window for window, value in precision.items() if value == "date")
    if date_only:
        warnings.append(
            "historical comparison headers expose dates only; normalized as 00:00:00Z date boundaries "
            f"with date precision: {','.join(date_only)}"
        )
    return {
        "as_of": current_as_of,
        "rows": rows,
        "futures": [],
        "warnings": warnings,
        "coverage": coverage,
        "parser_version": PARSER_VERSION,
    }


def normalize_fedwatch_rows(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Validate already-normalized rows and normalize small sum drift once.

    This entry point is intentionally suitable for synthetic normalized unit
    rows; it is not a source-format adapter and performs no unit guessing.
    """

    normalized: list[dict[str, Any]] = []
    warnings: list[str] = []
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for index, raw in enumerate(rows):
        try:
            meeting_date = date.fromisoformat(str(raw["meeting_date"])).isoformat()
            window = str(raw["comparison_window"])
            if window not in COMPARISON_WINDOWS:
                raise ValueError(f"unsupported comparison_window {window!r}")
            as_of = _utc_iso(str(raw["as_of"]))
            target_low = _finite_float(raw["target_low"], "target_low")
            target_high = _finite_float(raw["target_high"], "target_high")
            probability = _finite_float(raw["probability"], "probability")
            contract_ref_value = raw.get("contract_ref")
            contract_ref = str(contract_ref_value).strip() if contract_ref_value is not None else None
        except (KeyError, TypeError, ValueError) as exc:
            raise FedWatchParseError(f"invalid normalized row {index}: {exc}") from exc
        if target_low < 0.0 or target_high <= target_low:
            raise FedWatchParseError(f"invalid target interval in normalized row {index}")
        if target_high > 100.0:
            raise FedWatchParseError(f"target interval exceeds percent bounds in normalized row {index}")
        if probability < 0.0 or probability > 1.0:
            raise FedWatchParseError(f"probability outside [0, 1] in normalized row {index}")
        item = {
            "meeting_date": meeting_date,
            "contract_ref": contract_ref or None,
            "comparison_window": window,
            "as_of": as_of,
            "target_low": target_low,
            "target_high": target_high,
            "probability": probability,
        }
        groups[(meeting_date, window, as_of)].append(item)

    if not groups:
        raise FedWatchParseError("FedWatch payload contains no probability rows")

    meetings: dict[str, dict[str, Any]] = {}
    for (meeting_date, window, as_of), group in sorted(groups.items()):
        ranges = sorted(group, key=lambda item: (item["target_low"], item["target_high"]))
        contract_refs = {item["contract_ref"] for item in ranges}
        if len(contract_refs) != 1:
            raise FedWatchParseError(f"inconsistent contract_ref for {meeting_date} {window} at {as_of}")
        for previous, current in zip(ranges, ranges[1:]):
            if current["target_low"] < previous["target_high"]:
                raise FedWatchParseError(
                    f"overlapping target intervals for {meeting_date} {window} at {as_of}"
                )
        total = math.fsum(item["probability"] for item in ranges)
        if not 0.99 <= total <= 1.01:
            raise FedWatchParseError(
                f"probabilities sum to {total:.12g} for {meeting_date} {window}; expected 0.99..1.01"
            )
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-12):
            for item in ranges:
                item["probability"] = item["probability"] / total
            warnings.append(
                f"normalized probability sum once for {meeting_date} {window}: {total:.12g} -> 1"
            )
        normalized.extend(ranges)
        info = meetings.setdefault(
            meeting_date,
            {
                "available_windows": [],
                "missing_windows": [],
                "window_as_of": {},
                "window_precision": {},
            },
        )
        if window in info["window_as_of"] and info["window_as_of"][window] != as_of:
            raise FedWatchParseError(f"multiple source timestamps for {meeting_date} {window}")
        info["available_windows"].append(window)
        info["window_as_of"][window] = as_of

    for meeting_date, info in meetings.items():
        available = [window for window in COMPARISON_WINDOWS if window in info["available_windows"]]
        missing = [window for window in COMPARISON_WINDOWS if window not in available]
        info["available_windows"] = available
        info["missing_windows"] = missing
        if "current" in missing:
            raise FedWatchParseError(f"meeting {meeting_date} has no current probability distribution")
        if missing:
            warnings.append(f"meeting {meeting_date} missing comparison windows: {','.join(missing)}")

    coverage = {
        "complete": all(not info["missing_windows"] for info in meetings.values()),
        "meetings": meetings,
    }
    normalized.sort(
        key=lambda item: (
            item["meeting_date"],
            COMPARISON_WINDOWS.index(item["comparison_window"]),
            item["target_low"],
        )
    )
    return normalized, warnings, coverage


def _find_probability_table(
    tables: list[list[list[str]]],
) -> tuple[list[list[str]], int, list[tuple[int, str, str]]]:
    for table in tables:
        for row_index, row in enumerate(table):
            if not row or not re.search(r"target\s+rate", row[0], re.IGNORECASE):
                continue
            if "bps" not in row[0].lower():
                raise FedWatchParseError("target-rate table does not declare basis-point units")
            windows: list[tuple[int, str, str]] = []
            seen: set[str] = set()
            headers = row[1:]
            # The live QuikStrike table has a two-row header: Target Rate
            # spans both rows, then NOW/1D/1W/1M occupy columns 1..4.
            if headers == ["Probability(%)"] and row_index + 1 < len(table):
                headers = table[row_index + 1]
                row_index += 1
            for column_index, header in enumerate(headers, start=1):
                matches = [window for window, pattern in _WINDOW_LABELS.items() if pattern.search(header)]
                if len(matches) != 1:
                    continue
                window = matches[0]
                if window in seen:
                    raise FedWatchParseError(f"duplicate {window} comparison column")
                seen.add(window)
                windows.append((column_index, window, header))
            if "current" in seen:
                return table, row_index, windows
    raise FedWatchParseError("no semantic target-rate probability table was found")


def _parse_meeting_context(tables: list[list[list[str]]], visible_text: str) -> tuple[str, str | None]:
    for table in tables:
        for row_index, row in enumerate(table[:-1]):
            headers = [cell.lower() for cell in row]
            meeting_columns = [index for index, cell in enumerate(headers) if "meeting date" in cell]
            if not meeting_columns:
                continue
            values = table[row_index + 1]
            meeting_column = meeting_columns[0]
            if meeting_column >= len(values):
                continue
            meeting = _date_from_text(values[meeting_column])
            if meeting is None:
                continue
            contract_ref = None
            contract_columns = [index for index, cell in enumerate(headers) if cell.strip() == "contract"]
            if contract_columns and contract_columns[0] < len(values):
                contract_ref = values[contract_columns[0]].strip() or None
            return meeting.isoformat(), contract_ref
    title_match = _MEETING_TITLE_RE.search(visible_text)
    if title_match:
        meeting = _date_from_text(title_match.group("date"))
        if meeting is not None:
            return meeting.isoformat(), None
    raise FedWatchParseError("FedWatch response has no unambiguous meeting date")


def _parse_current_as_of(visible_text: str) -> str:
    match = _AS_OF_RE.search(visible_text)
    if not match:
        raise FedWatchParseError("FedWatch response has no source 'Data as of' timestamp")
    source_date = _date_from_text(match.group("date"))
    if source_date is None:
        raise FedWatchParseError("FedWatch source timestamp has an unsupported date")
    if not match.group("time"):
        raise FedWatchParseError("FedWatch current source timestamp has no time")
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            source_time = datetime.strptime(match.group("time"), fmt).time()
            break
        except ValueError:
            continue
    else:
        raise FedWatchParseError("FedWatch source timestamp has an unsupported time")
    zone_label = (match.group("zone") or "").upper()
    if not zone_label:
        raise FedWatchParseError("FedWatch source timestamp has no timezone")
    if zone_label == "CST":
        tz = timezone(-timedelta(hours=6))
    elif zone_label == "CDT":
        tz = timezone(-timedelta(hours=5))
    else:
        tz = ZoneInfo("America/Chicago")
    return datetime.combine(source_date, source_time, tzinfo=tz).astimezone(timezone.utc).isoformat()


def _date_from_text(value: str) -> date | None:
    cleaned = _clean_text(value).replace(",", " ")
    chinese = re.search(r"(\d{1,2})\s+(\d{1,2})月\s+(\d{4})", cleaned)
    if chinese:
        try:
            return date(int(chinese[3]), int(chinese[2]), int(chinese[1]))
        except ValueError:
            return None
    cleaned = re.sub(r"\b(?:NOW|CURRENT|1\s*DAY|1\s*WEEK|1\s*MONTH)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = _clean_text(cleaned)
    candidates = [cleaned]
    match = re.search(r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}", cleaned)
    if match:
        candidates.insert(0, match.group(0))
    match = re.search(r"[A-Za-z]{3,9}\s+\d{1,2}\s+\d{4}", cleaned)
    if match:
        candidates.insert(0, match.group(0))
    for candidate in candidates:
        for fmt in _MONTH_FORMATS:
            try:
                return datetime.strptime(candidate.title(), fmt).date()
            except ValueError:
                continue
    return None


def _parse_percent_probability(value: str) -> float:
    match = _PERCENT_RE.match(value)
    if not match:
        raise FedWatchParseError(f"probability value does not declare percent units: {value!r}")
    probability = float(match.group(1)) / 100.0
    if not math.isfinite(probability):
        raise FedWatchParseError("probability is not finite")
    return probability


def _finite_float(value: Any, field: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _utc_iso(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("as_of must include a UTC offset")
    return parsed.astimezone(timezone.utc).isoformat()


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


__all__ = [
    "COMPARISON_WINDOWS",
    "FedWatchParseError",
    "PARSER_VERSION",
    "normalize_fedwatch_rows",
    "parse_fedwatch_free_html",
    "parse_fedwatch_free_payload",
]
