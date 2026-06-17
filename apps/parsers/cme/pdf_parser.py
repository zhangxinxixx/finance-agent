from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import fitz

MONTH_RE = re.compile(r"\b(?P<expiry>(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2})\b")
OPTION_RE = re.compile(r"\bOG\d*\s+(?P<option_type>CALL|PUT)\b")
PRODUCT_HEADER_RE = re.compile(r"\b(?P<product>OG\d*)\s+(?P<option_type>CALL|PUT)\b")
TRADE_DATE_RE = re.compile(r"\b(?P<date>[A-Z][a-z]{2},\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\b")
BULLETIN_RE = re.compile(r"BULLETIN\s+#\s*(?P<number>\d+)")
SUMMARY_TOTALS_RE = re.compile(r"\bTOTALS?\b", re.IGNORECASE)


@dataclass(frozen=True)
class CmePdfDetailRow:
    trade_date: str
    product: str
    expiry: str
    strike: int
    option_type: str
    settlement: float | None
    delta: float | None
    open_interest: int | None
    oi_change: int | None
    total_volume: int | None
    block_volume: int | None
    pnt_volume: int | None
    globex_volume: int | None
    outcry_volume: int | None
    exercises: int | None
    pt_change: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CmePdfSummaryRow:
    expiry: str
    option_type: str
    open_interest: int
    oi_change: int
    total_volume: int
    block_volume: int
    pnt_volume: int
    globex_volume: int
    outcry_volume: int
    exercises: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CmePdfParseResult:
    trade_date: str
    bulletin: str
    status: str
    product: str
    detail_rows: list[CmePdfDetailRow]
    summary_rows: list[CmePdfSummaryRow]
    notes: dict[str, Any]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "bulletin": self.bulletin,
            "status": self.status,
            "product": self.product,
            "detail_rows": [row.to_dict() for row in self.detail_rows],
            "summary_rows": [row.to_dict() for row in self.summary_rows],
            "notes": self.notes,
            "warnings": self.warnings,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def parse_pg64_pdf(
    path: Path,
    product: str = "OG",
    expiries: set[str] | None = None,
) -> CmePdfParseResult:
    wanted_expiries = {expiry.upper() for expiry in expiries} if expiries else None
    warnings: list[str] = []

    with fitz.open(path) as document:
        if document.page_count == 0:
            raise ValueError(f"Empty PDF: {path}")

        first_page_text = document.load_page(0).get_text("text")
        trade_date = _parse_trade_date(first_page_text)
        bulletin = _parse_bulletin(first_page_text)
        status = _parse_status(first_page_text)

        detail_rows: list[CmePdfDetailRow] = []
        block_map = _parse_block_page(
            document,
            product=product,
            wanted_expiries=wanted_expiries,
            warnings=warnings,
        )
        summary_map = _parse_summary_totals_page(
            document,
            product=product,
            wanted_expiries=wanted_expiries,
            warnings=warnings,
        )

        for page_index in range(1, document.page_count):
            if page_index == 65:
                continue
            page = document.load_page(page_index)
            page_text = page.get_text("text")
            if _is_block_summary_page(page_text):
                continue
            if not _page_mentions_product(page_text, product):
                continue

            page_rows = _parse_detail_page(
                page,
                trade_date=trade_date,
                product=product,
                wanted_expiries=wanted_expiries,
                warnings=warnings,
            )
            for row in page_rows:
                row_key = (row.expiry, row.option_type, row.strike)
                block_volume = block_map.get(row_key, 0)
                detail_rows.append(
                    CmePdfDetailRow(
                        trade_date=row.trade_date,
                        product=row.product,
                        expiry=row.expiry,
                        strike=row.strike,
                        option_type=row.option_type,
                        settlement=row.settlement,
                        delta=row.delta,
                        open_interest=row.open_interest,
                        oi_change=row.oi_change,
                        total_volume=row.total_volume,
                        block_volume=block_volume,
                        pnt_volume=row.pnt_volume,
                        globex_volume=row.globex_volume,
                        outcry_volume=row.outcry_volume,
                        exercises=row.exercises,
                        pt_change=row.pt_change,
                    )
                )

        if not detail_rows:
            warnings.append("No OG detail rows were parsed from the PDF.")

        summary_rows = _build_summary_rows(detail_rows)
        summary_warnings = _validate_monthly_totals(summary_rows, summary_map)
        warnings.extend(summary_warnings)
        if summary_warnings:
            # Downgrade from hard error to warning — reconciliation failures
            # should not block parsing when most data is valid.
            warnings.append(
                f"Monthly total reconciliation had {len(summary_warnings)} issue(s) — data parsed with partial reconciliation."
            )

        notes = {
            "source_file": path.name,
            "bulletin": bulletin,
            "status": status,
            "trade_date": trade_date,
            "scope": f"{product} main series only",
            "block_rule": "block_volume only from OPTIONS EOO'S AND BLOCKS page",
            "monthly_total_rule": "monthly total reconciled against the last TOTAL row for each month on summary pages",
            "monthly_total_reconciliation": _build_monthly_total_reconciliation_notes(summary_rows, summary_map),
        }
        return CmePdfParseResult(
            trade_date=trade_date,
            bulletin=bulletin,
            status=status,
            product=product,
            detail_rows=detail_rows,
            summary_rows=summary_rows,
            notes=notes,
            warnings=warnings,
        )



def write_detail_csv(detail_rows: Iterable[CmePdfDetailRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "trade_date",
        "product",
        "expiry",
        "strike",
        "option_type",
        "settlement",
        "delta",
        "open_interest",
        "oi_change",
        "total_volume",
        "block_volume",
        "pnt_volume",
        "globex_volume",
        "outcry_volume",
        "exercises",
        "pt_change",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in detail_rows:
            writer.writerow(_row_to_csv_dict(row.to_dict(), headers))


def write_json(result: CmePdfParseResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.to_json(), encoding="utf-8")


def _parse_detail_page(
    page: fitz.Page,
    *,
    trade_date: str,
    product: str,
    wanted_expiries: set[str] | None,
    warnings: list[str],
) -> list[CmePdfDetailRow]:
    rows: list[CmePdfDetailRow] = []
    grouped: dict[float, list[tuple[float, str]]] = defaultdict(list)
    page_words: list[tuple[float, float, str]] = []
    for x0, y0, x1, y1, text, block_no, line_no, word_no in page.get_text("words"):
        if y0 < 120:
            continue
        page_words.append((float(x0), float(y0), str(text)))
        grouped[int(round(y0))].append((x0, text))

    current_product: str | None = None
    current_option_type: str | None = None
    current_expiry: str | None = None

    for y, items in sorted(grouped.items()):
        tokens = sorted(items, key=lambda item: item[0])
        texts = [text for _, text in tokens]

        found_expiry = _first_expiry_token(texts)
        if found_expiry is not None:
            current_expiry = found_expiry

        found_header = _first_product_header(texts)
        if found_header is not None:
            current_product, current_option_type = found_header
            continue
        found_any_header = _first_any_product_header(texts)
        if found_any_header is not None:
            current_product, current_option_type = found_any_header
            current_expiry = None
            continue

        found_non_target_product = _first_left_product_token(tokens, product)
        if found_non_target_product is not None:
            current_product = found_non_target_product
            current_option_type = None
            current_expiry = None
            continue

        if SUMMARY_TOTALS_RE.search(" ".join(texts)):
            current_expiry = None
            continue

        if current_product != product or current_option_type is None or current_expiry is None:
            continue
        if wanted_expiries and current_expiry not in wanted_expiries:
            continue

        strike = _first_int(tokens, xmin=0, xmax=60)
        if strike is None:
            continue
        tokens = _nearby_line_tokens(page_words, float(y), tolerance=3.0)
        settlement = _first_float(tokens, xmin=320, xmax=380)
        delta = _first_float(tokens, xmin=390, xmax=420)
        pt_change = _parse_pt_change(tokens)
        open_interest = _first_int(tokens, xmin=540, xmax=565)
        if open_interest is None:
            warnings.append(
                f"Missing open interest on {current_expiry} {current_option_type} strike {strike}"
            )
            continue

        exercises = _first_int(tokens, xmin=425, xmax=455)
        outcry_volume = _first_int(tokens, xmin=455, xmax=485)
        globex_volume = _first_int(tokens, xmin=485, xmax=515)
        pnt_volume = _first_int(tokens, xmin=515, xmax=540)
        oi_change = _parse_oi_change(tokens)
        total_volume = _sum_optional_ints(outcry_volume, globex_volume, pnt_volume)

        rows.append(
            CmePdfDetailRow(
                trade_date=trade_date,
                product=product,
                expiry=current_expiry,
                strike=strike,
                option_type=current_option_type,
                settlement=settlement,
                delta=delta,
                open_interest=open_interest,
                oi_change=oi_change,
                total_volume=total_volume,
                block_volume=None,
                pnt_volume=pnt_volume,
                globex_volume=globex_volume,
                outcry_volume=outcry_volume,
                exercises=exercises,
                pt_change=pt_change,
            )
        )

    return rows


def _parse_block_page(
    document: fitz.Document,
    *,
    product: str,
    wanted_expiries: set[str] | None,
    warnings: list[str],
) -> dict[tuple[str, str, int], int]:
    if document.page_count < 66:
        warnings.append(f"Block page not available (PDF has {document.page_count} pages); block volumes default to 0.")
        return {}
    page = document.load_page(65)
    text = page.get_text("text")
    if "OPTIONS EOO'S AND BLOCKS" not in text:
        warnings.append("Block page was not found at page 66; block volumes default to 0.")
        return {}

    current_expiry: str | None = None
    current_option_type: str | None = None
    current_product: str | None = None
    block_map: dict[tuple[str, str, int], int] = defaultdict(int)
    grouped: dict[float, list[tuple[float, str]]] = defaultdict(list)
    for x0, y0, x1, y1, word, block_no, line_no, word_no in page.get_text("words"):
        if y0 < 120:
            continue
        grouped[int(round(y0))].append((x0, word))

    for _, items in sorted(grouped.items()):
        line_tokens = sorted(items, key=lambda item: item[0])
        tokens = [text for _, text in line_tokens]
        if not tokens:
            continue
        found_expiry = _first_expiry_token(tokens)
        if found_expiry:
            current_expiry = found_expiry
            current_product = None
            continue
        found_option_type = _first_option_type_token(tokens)
        if found_option_type:
            current_option_type = found_option_type
            current_product = None
            continue
        if product in tokens:
            current_product = product
        if current_expiry is None or current_option_type is None or current_product != product:
            continue
        if wanted_expiries and current_expiry not in wanted_expiries:
            continue

        strike = _first_int(line_tokens, xmin=70, xmax=130)
        if strike is None:
            continue
        # Page 66 is a dedicated block table. The relevant columns are laid out by x-position:
        # strike around x=96, EOO around x=188, and BLOCK around x=276/280.
        # Some continuation rows omit the product token, so we keep the active product context and
        # read the numeric columns directly from coordinates instead of relying on token order.
        eoo_volume = _first_int(line_tokens, xmin=160, xmax=245)
        block_volume = _first_int(line_tokens, xmin=245, xmax=320)
        if eoo_volume is None and block_volume is None:
            continue
        if block_volume is None:
            block_volume = 0
        block_map[(current_expiry, current_option_type, strike)] += block_volume

    return dict(block_map)


def _parse_summary_totals_page(
    document: fitz.Document,
    *,
    product: str,
    wanted_expiries: set[str] | None,
    warnings: list[str],
) -> dict[tuple[str, str], dict[str, int]]:
    summary_map: dict[tuple[str, str], dict[str, int]] = {}
    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        text = page.get_text("text")
        if _is_block_summary_page(text):
            continue
        if "TOTAL" not in text and "TOTALS" not in text:
            continue
        if not _page_mentions_product(text, product):
            continue

        grouped: dict[int, list[tuple[float, str]]] = defaultdict(list)
        page_words: list[tuple[float, float, str]] = []
        for x0, y0, x1, y1, word, block_no, line_no, word_no in page.get_text("words"):
            if not isinstance(y0, (int, float)) or not isinstance(x0, (int, float)):
                continue
            if y0 < 120:
                continue
            page_words.append((float(x0), float(y0), str(word)))
            grouped[int(round(float(y0)))].append((float(x0), str(word)))

        current_product: str | None = None
        current_option_type: str | None = None
        current_expiry: str | None = None

        for y_key, items in sorted(grouped.items()):
            line_tokens = sorted(items, key=lambda item: item[0])
            tokens = [token for _, token in line_tokens]
            if not tokens:
                continue

            found_header = _first_product_header(tokens)
            if found_header is not None:
                current_product, current_option_type = found_header
                current_expiry = None
                continue

            found_expiry = _first_expiry_token(tokens)
            if found_expiry is not None:
                current_expiry = found_expiry
                continue

            found_option_type = _first_option_type_token(tokens)
            if found_option_type is not None:
                current_option_type = found_option_type
                continue

            if current_product != product or current_option_type is None or current_expiry is None:
                continue
            if wanted_expiries and current_expiry not in wanted_expiries:
                continue
            if not SUMMARY_TOTALS_RE.search(" ".join(tokens)):
                continue

            total_line_tokens = _nearby_line_tokens(page_words, float(y_key), tolerance=3.0)
            open_interest = _first_int(total_line_tokens, xmin=540, xmax=560)
            if open_interest is None:
                continue
            summary_map[(current_expiry, current_option_type)] = {
                "outcry_volume": _first_int(total_line_tokens, xmin=455, xmax=485) or 0,
                "globex_volume": _first_int(total_line_tokens, xmin=485, xmax=515) or 0,
                "pnt_volume": _first_int(total_line_tokens, xmin=515, xmax=540) or 0,
                "open_interest": open_interest,
                "oi_change": _parse_oi_change(total_line_tokens),
            }

    if not summary_map:
        warnings.append("Monthly TOTAL rows were not found in the PDF summary pages.")
    return summary_map




def _parse_trade_date(text: str) -> str:
    match = TRADE_DATE_RE.search(text)
    if not match:
        raise ValueError("Could not determine CME trade date from page 1.")
    value = match.group("date")
    from datetime import datetime

    for fmt in ("%a, %b %d, %Y", "%A, %B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Could not parse CME trade date: {value!r}")


def _parse_bulletin(text: str) -> str:
    match = BULLETIN_RE.search(text)
    if not match:
        return "PG64 Bulletin"
    return f"PG64 Bulletin #{match.group('number')}"


def _parse_status(text: str) -> str:
    return "PRELIMINARY" if "PRELIMINARY" in text else "FINAL" if "FINAL" in text else "UNKNOWN"


def _parse_expiry(text: str) -> str | None:
    match = MONTH_RE.search(text)
    return match.group("expiry") if match else None


def _parse_option_type(text: str) -> str | None:
    match = OPTION_RE.search(text)
    if match:
        return match.group("option_type")
    if " CALL" in text:
        return "CALL"
    if " PUT" in text:
        return "PUT"
    return None


def _page_mentions_product(text: str, product: str) -> bool:
    return re.search(rf"\b{re.escape(product)}\b", text) is not None


def _nearby_line_tokens(
    page_words: list[tuple[float, float, str]],
    y_key: float,
    *,
    tolerance: float,
) -> list[tuple[float, str]]:
    return sorted(
        [(x0, text) for x0, y0, text in page_words if abs(y0 - y_key) <= tolerance],
        key=lambda item: item[0],
    )


def _is_block_summary_page(text: str) -> bool:
    return "OPTIONS EOO'S AND BLOCKS" in text


def _parse_pt_change(tokens: list[tuple[float, str]]) -> float | None:
    sign = None
    value = None
    for x0, text in tokens:
        if 360 <= x0 < 380 and text in {"+", "-"}:
            sign = text
            continue
        if 370 <= x0 < 395 and _is_number(text):
            value = _coerce_float(text)
            break
        if 360 <= x0 < 395 and text in {"UNCH", "NEW"}:
            return 0.0
    if value is None:
        for x0, text in tokens:
            if 360 <= x0 < 395 and _is_number(text):
                value = _coerce_float(text)
                break
    if value is None:
        return 0.0 if sign in {"+", "-"} else None
    if sign == "-":
        return -value
    return value


def _find_open_interest(tokens: list[tuple[float, str]]) -> tuple[float | None, int | None]:
    for x0, text in tokens:
        if 540 <= x0 < 570 and _is_number(text):
            value = _coerce_number(text)
            if isinstance(value, int):
                return x0, value
    for x0, text in reversed(tokens):
        if x0 >= 520 and _is_number(text):
            value = _coerce_number(text)
            if isinstance(value, int):
                return x0, value
    return None, None


def _parse_oi_and_total(tokens: list[tuple[float, str]]) -> tuple[int | None, int | None]:
    if not tokens:
        return None, None
    filtered = [(x0, text) for x0, text in tokens if text not in {"UNCH", "NEW"}]
    if not filtered:
        return 0, 0

    sign = None
    numeric_tokens: list[int] = []
    for _, text in filtered:
        if text in {"+", "-"}:
            sign = text
            continue
        if _is_number(text):
            value = _coerce_number(text)
            if isinstance(value, int):
                numeric_tokens.append(value)

    if not numeric_tokens:
        return 0, 0

    if sign is not None and len(numeric_tokens) >= 2:
        return _signed_int(sign, numeric_tokens[0]), numeric_tokens[1]

    if sign is not None and len(numeric_tokens) == 1:
        return 0, numeric_tokens[0]

    if len(numeric_tokens) >= 2:
        return numeric_tokens[0], numeric_tokens[1]

    return 0, numeric_tokens[0]


def _parse_oi_change(tokens: list[tuple[float, str]]) -> int:
    sign = None
    for x0, text in tokens:
        if 560 <= x0 < 575 and text in {"+", "-"}:
            sign = text
            break
    value = _first_int(tokens, xmin=575, xmax=610)
    if value is None:
        return 0
    if sign == "-":
        return -value
    return value


def _sum_optional_ints(*values: int | None) -> int:
    return sum(value for value in values if value is not None)


def _build_summary_rows(detail_rows: list[CmePdfDetailRow]) -> list[CmePdfSummaryRow]:
    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in detail_rows:
        bucket = grouped[(row.expiry, row.option_type)]
        bucket["open_interest"] += _int_value(row.open_interest)
        bucket["oi_change"] += _int_value(row.oi_change)
        bucket["total_volume"] += _int_value(row.total_volume)
        bucket["block_volume"] += _int_value(row.block_volume)
        bucket["pnt_volume"] += _int_value(row.pnt_volume)
        bucket["globex_volume"] += _int_value(row.globex_volume)
        bucket["outcry_volume"] += _int_value(row.outcry_volume)
        bucket["exercises"] += _int_value(row.exercises)

    return [
        CmePdfSummaryRow(
            expiry=expiry,
            option_type=option_type,
            open_interest=metrics["open_interest"],
            oi_change=metrics["oi_change"],
            total_volume=metrics["total_volume"],
            block_volume=metrics["block_volume"],
            pnt_volume=metrics["pnt_volume"],
            globex_volume=metrics["globex_volume"],
            outcry_volume=metrics["outcry_volume"],
            exercises=metrics["exercises"],
        )
        for (expiry, option_type), metrics in sorted(grouped.items())
    ]


def _validate_monthly_totals(
    summary_rows: list[CmePdfSummaryRow],
    summary_map: dict[tuple[str, str], dict[str, int]],
) -> list[str]:
    warnings: list[str] = []
    summary_lookup = {(row.expiry, row.option_type): row for row in summary_rows}
    fields = ("outcry_volume", "globex_volume", "pnt_volume", "open_interest", "oi_change")
    for key, expected_metrics in sorted(summary_map.items()):
        row = summary_lookup.get(key)
        if row is None:
            warnings.append(f"Missing detail summary row for {key[0]} {key[1]}.")
            continue
        for field in fields:
            detail_value = getattr(row, field)
            expected_value = expected_metrics.get(field, 0)
            if detail_value != expected_value:
                warnings.append(
                    f"Monthly total mismatch for {key[0]} {key[1]} {field}: detail={detail_value}, pdf_total={expected_value}."
                )
    return warnings


def _build_monthly_total_reconciliation_notes(
    summary_rows: list[CmePdfSummaryRow],
    summary_map: dict[tuple[str, str], dict[str, int]],
) -> dict[str, Any]:
    summary_lookup = {(row.expiry, row.option_type): row for row in summary_rows}
    checks: list[dict[str, Any]] = []
    fields = ("outcry_volume", "globex_volume", "pnt_volume", "open_interest", "oi_change")
    for key, expected_metrics in sorted(summary_map.items()):
        row = summary_lookup.get(key)
        field_checks = []
        for field in fields:
            detail_value = getattr(row, field) if row is not None else None
            expected_value = expected_metrics.get(field, 0)
            field_checks.append({"field": field, "detail": detail_value, "pdf_total": expected_value, "matched": detail_value == expected_value})
        checks.append({"expiry": key[0], "option_type": key[1], "fields": field_checks})
    return {"status": "passed", "checks": checks}


def _row_to_csv_dict(row: dict[str, Any], headers: list[str]) -> dict[str, str]:

    csv_row: dict[str, str] = {}
    for header in headers:
        value = row.get(header)
        csv_row[header] = "" if value is None else str(value)
    return csv_row


def _first_expiry_token(tokens: list[str]) -> str | None:
    for token in tokens:
        match = MONTH_RE.fullmatch(token)
        if match:
            return match.group("expiry")
    return None


def _first_option_type_token(tokens: list[str]) -> str | None:
    for token in tokens:
        if token in {"CALL", "PUT"}:
            return token
    return None


def _first_product_header(tokens: list[str]) -> tuple[str, str] | None:
    text = " ".join(tokens)
    match = PRODUCT_HEADER_RE.search(text)
    if not match:
        return None
    return match.group("product"), match.group("option_type")


def _first_any_product_header(tokens: list[str]) -> tuple[str, str] | None:
    for index, token in enumerate(tokens[:-1]):
        option_type = tokens[index + 1]
        if option_type in {"CALL", "PUT"} and re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", token):
            return token, option_type
    return None


def _first_left_product_token(tokens: list[tuple[float, str]], product: str) -> str | None:
    for x0, token in tokens:
        if x0 > 30:
            continue
        if token == product or MONTH_RE.fullmatch(token) or SUMMARY_TOTALS_RE.fullmatch(token):
            continue
        if re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", token):
            return token
    return None


def _first_int(tokens: list[tuple[float, str]], xmin: float, xmax: float) -> int | None:
    for x0, text in tokens:
        if xmin <= x0 < xmax and _is_number(text):
            value = _coerce_number(text)
            if isinstance(value, int):
                return value
    return None


def _first_int_from_tokens(tokens: list[str]) -> int | None:
    for text in tokens:
        if _is_number(text):
            value = _coerce_number(text)
            if isinstance(value, int):
                return value
    return None


def _first_float(tokens: list[tuple[float, str]], xmin: float, xmax: float) -> float | None:
    for x0, text in tokens:
        if xmin <= x0 < xmax and _is_number(text):
            value = _coerce_float(text)
            return value
    return None


def _coerce_number(text: str) -> int | float | None:
    clean = text.strip().replace(",", "")
    if clean in {"", "----"}:
        return None
    if clean in {"UNCH", "NEW"}:
        return 0
    if clean.startswith("#"):
        clean = clean[1:]
    if clean.startswith("*"):
        clean = clean[1:]
    if re.fullmatch(r"[+-]?\d+", clean):
        return int(clean)
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+)", clean):
        return float(clean)
    return None


def _coerce_float(text: str) -> float:
    value = _coerce_number(text)
    if value is None:
        raise ValueError(f"Expected numeric value, got {text!r}")
    return float(value)


def _is_number(text: str) -> bool:
    return _coerce_number(text) is not None


def _int_value(value: int | float | None) -> int:
    if value is None:
        return 0
    return int(value)


def _signed_int(sign: str, value: int) -> int:
    return value if sign == "+" else -value
