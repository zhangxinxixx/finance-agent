"""Pure parser for official CFTC disaggregated Gold COT reports.

The CFTC publishes two disaggregated datasets with the same row layout:
futures-only and futures-and-options combined.  The report type is part of
the parsed contract so downstream consumers cannot silently compare the two
different open-interest universes.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal


COTReportType = Literal["futures_only", "combined"]
CFTC_REPORT_TYPES: tuple[COTReportType, ...] = ("futures_only", "combined")

COL_REPORT_DATE = "Report_Date_as_YYYY-MM-DD"
COL_MARKET = "Market_and_Exchange_Names"
COL_CONTRACT_CODE = "CFTC_Contract_Market_Code"
COL_OPEN_INTEREST = "Open_Interest_All"
COL_PROD_LONG = "Prod_Merc_Positions_Long_All"
COL_PROD_SHORT = "Prod_Merc_Positions_Short_All"
COL_SWAP_LONG = "Swap_Positions_Long_All"
COL_SWAP_SHORT = "Swap__Positions_Short_All"
COL_MM_LONG = "M_Money_Positions_Long_All"
COL_MM_SHORT = "M_Money_Positions_Short_All"
COL_OTHER_LONG = "Other_Rept_Positions_Long_All"
COL_OTHER_SHORT = "Other_Rept_Positions_Short_All"
COL_REPORT_TYPE = "FutOnly_or_Combined"

GOLD_CONTRACT_CODE = "088691"
GOLD_MARKET_NAME = "GOLD - COMMODITY EXCHANGE INC."

_NUMERIC_COLUMNS = (
    COL_OPEN_INTEREST,
    COL_PROD_LONG,
    COL_PROD_SHORT,
    COL_SWAP_LONG,
    COL_SWAP_SHORT,
    COL_MM_LONG,
    COL_MM_SHORT,
    COL_OTHER_LONG,
    COL_OTHER_SHORT,
)


@dataclass(frozen=True)
class COTRow:
    """One normalized official Gold row from one CFTC report universe."""

    report_date: date
    market: str
    contract_code: str
    report_type: COTReportType
    open_interest: float
    producer_long: float
    producer_short: float
    swap_long: float
    swap_short: float
    managed_money_long: float
    managed_money_short: float
    other_long: float
    other_short: float

    @property
    def producer_net(self) -> float:
        return self.producer_long - self.producer_short

    @property
    def swap_net(self) -> float:
        return self.swap_long - self.swap_short

    @property
    def managed_money_net(self) -> float:
        return self.managed_money_long - self.managed_money_short

    @property
    def commercial_net(self) -> float:
        """Compatibility aggregate: Producer/Merchant plus Swap Dealers."""

        return self.producer_net + self.swap_net

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["report_date"] = self.report_date.isoformat()
        payload.update(
            {
                "producer_net": self.producer_net,
                "swap_net": self.swap_net,
                "managed_money_net": self.managed_money_net,
                "commercial_net": self.commercial_net,
            }
        )
        return payload


@dataclass(frozen=True)
class COTReport:
    """Filtered Gold rows plus parse diagnostics for one report type."""

    report_type: COTReportType
    rows: tuple[COTRow, ...]
    skipped_rows: int = 0
    raw_rows: tuple[dict[str, str], ...] = ()

    def latest_pair(self) -> tuple[COTRow, COTRow | None]:
        """Return latest and immediately previous published Gold report rows."""

        ordered = sorted(self.rows, key=lambda row: row.report_date)
        if not ordered:
            raise ValueError("CFTC report contains no eligible Gold rows")
        latest = ordered[-1]
        previous = next(
            (row for row in reversed(ordered[:-1]) if row.report_date < latest.report_date),
            None,
        )
        return latest, previous

    def to_dict(self) -> dict[str, object]:
        return {
            "report_type": self.report_type,
            "rows": [row.to_dict() for row in self.rows],
            "skipped_rows": self.skipped_rows,
        }


def parse_cftc_disaggregated_zip(
    payload: bytes,
    *,
    report_type: COTReportType,
    cutoff_date: date,
    contract_code: str = GOLD_CONTRACT_CODE,
    market_name: str = GOLD_MARKET_NAME,
) -> COTReport:
    """Parse a CFTC disaggregated ZIP and retain Gold rows on/before cutoff.

    The parser is pure: it does not create files, call the network, or infer
    missing numeric values.  Rows with incomplete/invalid required fields are
    counted as skipped and never converted to zero.
    """

    _validate_report_type(report_type)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".txt")]
            if not names:
                raise ValueError("CFTC COT zip contains no .txt (CSV) file")
            # Official annual archives contain one report.  Sorting keeps the
            # choice deterministic for a synthetic archive with several files.
            csv_text = archive.read(sorted(names)[0]).decode("utf-8-sig", errors="replace")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"CFTC COT zip is corrupt: {exc}") from exc

    return parse_cftc_disaggregated_text(
        csv_text,
        report_type=report_type,
        cutoff_date=cutoff_date,
        contract_code=contract_code,
        market_name=market_name,
    )


def parse_cftc_disaggregated_text(
    csv_text: str,
    *,
    report_type: COTReportType,
    cutoff_date: date,
    contract_code: str = GOLD_CONTRACT_CODE,
    market_name: str = GOLD_MARKET_NAME,
) -> COTReport:
    """Parse normalized CFTC text for one report universe."""

    _validate_report_type(report_type)
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise ValueError("CFTC CSV has no header row")
    missing_columns = [column for column in (COL_REPORT_DATE, COL_MARKET, COL_CONTRACT_CODE, *_NUMERIC_COLUMNS) if column not in reader.fieldnames]
    if missing_columns:
        raise ValueError(f"CFTC CSV is missing required columns: {', '.join(missing_columns)}")

    expected_market = " ".join(market_name.upper().split())
    rows: list[COTRow] = []
    raw_rows: list[dict[str, str]] = []
    skipped_rows = 0
    for raw in reader:
        market = " ".join(str(raw.get(COL_MARKET) or "").upper().split())
        if str(raw.get(COL_CONTRACT_CODE) or "").strip() != contract_code or market != expected_market:
            continue
        try:
            report_date = date.fromisoformat(str(raw.get(COL_REPORT_DATE) or "").strip())
        except ValueError:
            skipped_rows += 1
            continue
        if report_date > cutoff_date:
            continue
        raw_rows.append(dict(raw))
        declared_type = _declared_report_type(raw.get(COL_REPORT_TYPE))
        declared_text = str(raw.get(COL_REPORT_TYPE) or "").strip()
        if declared_text and (declared_type is None or declared_type != report_type):
            skipped_rows += 1
            continue
        numbers = {column: _number(raw.get(column)) for column in _NUMERIC_COLUMNS}
        if any(value is None for value in numbers.values()):
            skipped_rows += 1
            continue
        rows.append(
            COTRow(
                report_date=report_date,
                market=market_name,
                contract_code=contract_code,
                report_type=report_type,
                open_interest=numbers[COL_OPEN_INTEREST],
                producer_long=numbers[COL_PROD_LONG],
                producer_short=numbers[COL_PROD_SHORT],
                swap_long=numbers[COL_SWAP_LONG],
                swap_short=numbers[COL_SWAP_SHORT],
                managed_money_long=numbers[COL_MM_LONG],
                managed_money_short=numbers[COL_MM_SHORT],
                other_long=numbers[COL_OTHER_LONG],
                other_short=numbers[COL_OTHER_SHORT],
            )
        )
    rows.sort(key=lambda row: row.report_date)
    return COTReport(
        report_type=report_type,
        rows=tuple(rows),
        skipped_rows=skipped_rows,
        raw_rows=tuple(raw_rows),
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _validate_report_type(report_type: str) -> None:
    if report_type not in CFTC_REPORT_TYPES:
        raise ValueError(f"unsupported CFTC report_type: {report_type!r}")


def _declared_report_type(value: object) -> COTReportType | None:
    """Normalize the official row-level ``FutOnly_or_Combined`` label."""

    text = " ".join(str(value or "").strip().lower().replace("_", " ").split())
    if not text:
        return None
    if "combined" in text:
        return "combined"
    if text in {"futonly", "futuresonly", "futures only"}:
        return "futures_only"
    return None
