"""Pure parsers for the official GLD NAV and holdings workbooks."""

from __future__ import annotations

import io
import math
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class GldNavRow:
    report_date: date
    nav_per_share: float
    shares_outstanding: float
    total_net_assets_usd: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["report_date"] = self.report_date.isoformat()
        return payload


@dataclass(frozen=True)
class GldNavHistory:
    rows: tuple[GldNavRow, ...]
    skipped_rows: int = 0

    def latest_pair(self) -> tuple[GldNavRow, GldNavRow | None]:
        return _latest_pair(self.rows)

    def weekly_anchor(self, latest: GldNavRow | None = None) -> GldNavRow | None:
        """Return the row on or before seven calendar days before ``latest``."""

        if not self.rows:
            return None
        current = latest or max(self.rows, key=lambda row: row.report_date)
        return _weekly_anchor(self.rows, current)

    def to_dict(self) -> dict[str, object]:
        return {"rows": [row.to_dict() for row in self.rows], "skipped_rows": self.skipped_rows}


@dataclass(frozen=True)
class GldHoldingsRow:
    report_date: date
    gold_holdings_ounces: float
    gold_holdings_tonnes: float
    total_net_asset_value_usd: float

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["report_date"] = self.report_date.isoformat()
        return payload


@dataclass(frozen=True)
class GldHoldingsHistory:
    rows: tuple[GldHoldingsRow, ...]
    skipped_rows: int = 0

    def latest_pair(self) -> tuple[GldHoldingsRow, GldHoldingsRow | None]:
        return _latest_pair(self.rows)

    def weekly_anchor(self, latest: GldHoldingsRow | None = None) -> GldHoldingsRow | None:
        """Return the row on or before seven calendar days before ``latest``."""

        if not self.rows:
            return None
        current = latest or max(self.rows, key=lambda row: row.report_date)
        return _weekly_anchor(self.rows, current)

    def to_dict(self) -> dict[str, object]:
        return {"rows": [row.to_dict() for row in self.rows], "skipped_rows": self.skipped_rows}


def parse_gld_nav_history(payload: bytes, *, cutoff_date: date) -> GldNavHistory:
    """Parse the SSGA ``navhist-us-en-gld.xlsx`` workbook up to a cutoff."""

    rows = _read_workbook_rows(payload, sheet_name=None)
    header_index, columns = _find_columns(
        rows,
        required=("date", "nav", "shares outstanding", "total net assets"),
    )
    parsed_by_date: dict[date, GldNavRow] = {}
    skipped = 0
    for values in rows[header_index + 1 :]:
        report_date = _date_value(_cell(values, columns["date"]))
        if report_date is None:
            # Blank trailing rows are normal workbook structure.
            if any(str(value or "").strip() for value in values):
                skipped += 1
            continue
        if report_date > cutoff_date:
            continue
        nav = _number(_cell(values, columns["nav"]))
        shares = _number(_cell(values, columns["shares outstanding"]))
        assets = _number(_cell(values, columns["total net assets"]))
        if nav is None or shares is None or assets is None:
            skipped += 1
            continue
        row = GldNavRow(
            report_date=report_date,
            nav_per_share=nav,
            shares_outstanding=shares,
            total_net_assets_usd=assets,
        )
        previous = parsed_by_date.get(report_date)
        if previous is not None:
            if previous != row:
                raise ValueError(f"Conflicting duplicate GLD NAV row for {report_date.isoformat()}")
            continue
        parsed_by_date[report_date] = row
    parsed = sorted(parsed_by_date.values(), key=lambda row: row.report_date)
    return GldNavHistory(rows=tuple(parsed), skipped_rows=skipped)


def parse_gld_historical_archive(payload: bytes, *, cutoff_date: date) -> GldHoldingsHistory:
    """Parse the official SPDR historical archive XLSX up to a cutoff."""

    rows = _read_workbook_rows(payload, sheet_name="US GLD Historical Archive")
    header_index, columns = _find_columns(
        rows,
        required=(
            "date",
            "total ounces of gold in the trust",
            "tonnes of gold",
            "total net asset value in the trust",
        ),
    )
    parsed_by_date: dict[date, GldHoldingsRow] = {}
    skipped = 0
    for values in rows[header_index + 1 :]:
        report_date = _date_value(_cell(values, columns["date"]))
        if report_date is None:
            if any(str(value or "").strip() for value in values):
                skipped += 1
            continue
        if report_date > cutoff_date:
            continue
        ounces = _number(_cell(values, columns["total ounces of gold in the trust"]))
        tonnes = _number(_cell(values, columns["tonnes of gold"]))
        assets = _number(_cell(values, columns["total net asset value in the trust"]))
        if ounces is None or tonnes is None or assets is None:
            skipped += 1
            continue
        row = GldHoldingsRow(
            report_date=report_date,
            gold_holdings_ounces=ounces,
            gold_holdings_tonnes=tonnes,
            total_net_asset_value_usd=assets,
        )
        previous = parsed_by_date.get(report_date)
        if previous is not None:
            if previous != row:
                raise ValueError(f"Conflicting duplicate GLD holdings row for {report_date.isoformat()}")
            continue
        parsed_by_date[report_date] = row
    parsed = sorted(parsed_by_date.values(), key=lambda row: row.report_date)
    return GldHoldingsHistory(rows=tuple(parsed), skipped_rows=skipped)


def _read_workbook_rows(payload: bytes, *, sheet_name: str | None) -> list[list[Any]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"GLD workbook is corrupt: {exc}") from exc
    with archive:
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise ValueError("GLD workbook is missing xl/workbook.xml")
        shared_strings = _shared_strings(archive.read("xl/sharedStrings.xml")) if "xl/sharedStrings.xml" in names else []
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {}
        if "xl/_rels/workbook.xml.rels" in names:
            rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            rels = {
                item.attrib.get("Id", ""): item.attrib.get("Target", "")
                for item in rel_root
            }
        selected_path = _sheet_path(workbook, rels, sheet_name)
        if selected_path not in names:
            raise ValueError(f"GLD workbook sheet is missing: {selected_path}")
        return _sheet_rows(archive.read(selected_path), shared_strings)


def _sheet_path(workbook: ET.Element, rels: dict[str, str], sheet_name: str | None) -> str:
    sheets = workbook.find(_q("sheets"))
    if sheets is None:
        raise ValueError("GLD workbook has no sheets")
    chosen = None
    for sheet in list(sheets):
        if sheet_name is None or sheet.attrib.get("name") == sheet_name:
            chosen = sheet
            break
    if chosen is None:
        raise ValueError(f"GLD workbook sheet not found: {sheet_name}")
    relationship_id = chosen.attrib.get("{%s}id" % "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
    target = rels.get(relationship_id or "")
    if not target:
        raise ValueError("GLD workbook sheet relationship is missing")
    target = target.lstrip("/")
    return target if target.startswith("xl/") else f"xl/{target}"


def _shared_strings(payload: bytes) -> list[str]:
    root = ET.fromstring(payload)
    values: list[str] = []
    for item in root.findall(_q("si")):
        values.append("".join(text.text or "" for text in item.iter(_q("t"))))
    return values


def _sheet_rows(payload: bytes, shared_strings: list[str]) -> list[list[Any]]:
    root = ET.fromstring(payload)
    rows: list[list[Any]] = []
    for row in root.findall(f".//{_q('row')}"):
        cells: dict[int, Any] = {}
        for cell in row.findall(_q("c")):
            reference = cell.attrib.get("r", "")
            column = _column_index(reference)
            if column is None:
                continue
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value = "".join(text.text or "" for text in cell.iter(_q("t")))
            else:
                value_node = cell.find(_q("v"))
                raw_value = value_node.text if value_node is not None else ""
                if cell_type == "s":
                    try:
                        value = shared_strings[int(raw_value or "0")]
                    except (IndexError, ValueError):
                        value = ""
                else:
                    value = raw_value
            cells[column] = value
        if not cells:
            rows.append([])
            continue
        width = max(cells) + 1
        rows.append([cells.get(index, "") for index in range(width)])
    return rows


def _find_columns(rows: list[list[Any]], *, required: tuple[str, ...]) -> tuple[int, dict[str, int]]:
    for index, row in enumerate(rows):
        normalized = [_header_text(value) for value in row]
        columns: dict[str, int] = {}
        for key in required:
            for position, value in enumerate(normalized):
                if _header_matches(value, key):
                    columns[key] = position
                    break
        if len(columns) == len(required):
            return index, columns
    raise ValueError(f"GLD workbook is missing required columns: {', '.join(required)}")


def _header_matches(value: str, required: str) -> bool:
    if value == required:
        return True
    # SSGA uses "Total Net Assets" while the archive adds a scope suffix.
    return required in value


def _header_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip().lower()


def _cell(values: list[Any], index: int) -> Any:
    return values[index] if 0 <= index < len(values) else None


def _column_index(reference: str) -> int | None:
    match = re.match(r"([A-Z]+)", reference.upper())
    if match is None:
        return None
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def _date_value(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    number = _number(text)
    if number is not None and 1 <= number <= 100000:
        try:
            return date(1899, 12, 30) + timedelta(days=int(number))
        except OverflowError:
            return None
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(",", "").replace("$", "")
        if not text:
            return None
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1]
        try:
            number = float(text)
        except ValueError:
            return None
        if negative:
            number = -number
    return number if math.isfinite(number) else None


def _latest_pair(rows: tuple[Any, ...]) -> tuple[Any, Any | None]:
    if not rows:
        raise ValueError("GLD workbook contains no eligible rows")
    ordered = sorted(rows, key=lambda row: row.report_date)
    latest = ordered[-1]
    previous = next(
        (row for row in reversed(ordered[:-1]) if row.report_date < latest.report_date),
        None,
    )
    return latest, previous


def _weekly_anchor(rows: tuple[Any, ...], latest: Any) -> Any | None:
    target_date = latest.report_date - timedelta(days=7)
    return max(
        (row for row in rows if row.report_date <= target_date),
        key=lambda row: row.report_date,
        default=None,
    )


def _q(tag: str) -> str:
    return f"{{http://schemas.openxmlformats.org/spreadsheetml/2006/main}}{tag}"
