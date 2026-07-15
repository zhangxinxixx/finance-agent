from __future__ import annotations

import csv
import json
import zipfile
from datetime import date
from io import BytesIO, StringIO
from pathlib import Path

import httpx

from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import utc_now_iso

CFTC_COT_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip"
COT_SOURCE = "cftc"
COT_SYMBOL = "COT_GOLD"

GOLD_CONTRACT_CODE = "088691"
GOLD_MARKET_NAME = "GOLD - COMMODITY EXCHANGE INC."

# CSV columns in the CFTC disaggregated futures report
COL_REPORT_DATE = "Report_Date_as_YYYY-MM-DD"
COL_MARKET = "Market_and_Exchange_Names"
COL_CONTRACT_CODE = "CFTC_Contract_Market_Code"
COL_OPEN_INTEREST = "Open_Interest_All"
# Commercial = Producer/Merchant + Swap Dealers
COL_PROD_LONG = "Prod_Merc_Positions_Long_All"
COL_PROD_SHORT = "Prod_Merc_Positions_Short_All"
COL_SWAP_LONG = "Swap_Positions_Long_All"
COL_SWAP_SHORT = "Swap__Positions_Short_All"  # CFTC uses double underscore
# Non-commercial = Managed Money
COL_MM_LONG = "M_Money_Positions_Long_All"
COL_MM_SHORT = "M_Money_Positions_Short_All"
# Other reportable
COL_OTHER_LONG = "Other_Rept_Positions_Long_All"
COL_OTHER_SHORT = "Other_Rept_Positions_Short_All"


def collect_positioning_cot(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    """Download CFTC COT disaggregated report, filter GOLD/COMEX rows, return MacroPoints.

    Archives raw CSV rows to ``storage/raw/positioning/<date>/cot_gold.json``.
    Gracefully returns unavailable result if CFTC is unreachable or data is missing.
    """
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
            response = client.get(CFTC_COT_URL)
            response.raise_for_status()
    except Exception as exc:
        return _unavailable(f"CFTC COT download failed: {type(exc).__name__}: {exc}")

    try:
        with zipfile.ZipFile(BytesIO(response.content)) as zf:
            # CFTC zip contains a single CSV file; find it
            csv_names = [name for name in zf.namelist() if name.lower().endswith(".txt")]
            if not csv_names:
                return _unavailable("CFTC COT zip contains no .txt (CSV) file")
            csv_text = zf.read(csv_names[0]).decode("utf-8", errors="replace")
    except zipfile.BadZipFile as exc:
        return _unavailable(f"CFTC COT zip is corrupt: {exc}")
    except Exception as exc:
        return _unavailable(f"CFTC COT zip extraction failed: {type(exc).__name__}: {exc}")

    reader = csv.DictReader(StringIO(csv_text))
    if reader.fieldnames is None:
        return _unavailable("CFTC CSV has no header row")

    try:
        cutoff_date = date.fromisoformat(retrieved_date[:10])
    except ValueError:
        return _unavailable(f"Invalid retrieved_date for COT cutoff: {retrieved_date!r}")

    gold_rows: list[dict[str, str]] = []
    for row in reader:
        market = " ".join(row.get(COL_MARKET, "").upper().split())
        contract_code = row.get(COL_CONTRACT_CODE, "").strip()
        if contract_code != GOLD_CONTRACT_CODE or market != GOLD_MARKET_NAME:
            continue
        try:
            report_date = date.fromisoformat(row.get(COL_REPORT_DATE, ""))
        except ValueError:
            continue
        if report_date <= cutoff_date:
            gold_rows.append(row)

    if not gold_rows:
        return _unavailable(
            f"No standard GOLD contract {GOLD_CONTRACT_CODE} rows found on or before "
            f"{cutoff_date.isoformat()} in CFTC COT CSV"
        )

    # Archive raw rows
    raw_dir = storage_root / "raw" / "positioning" / retrieved_date
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "cot_gold.json"
    raw_path.write_text(
        json.dumps(gold_rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    raw_path_rel = raw_path.relative_to(storage_root).as_posix()

    # Contract and point-in-time filtering above ensure the comparison is like-for-like.
    gold_rows.sort(key=lambda r: r.get(COL_REPORT_DATE, ""))
    latest_row = gold_rows[-1]
    latest_report_date = latest_row.get(COL_REPORT_DATE, "")
    previous_rows = [
        row for row in gold_rows
        if row.get(COL_REPORT_DATE, "") < latest_report_date
    ]
    prev_row = previous_rows[-1] if previous_rows else None

    retrieved_at = utc_now_iso()

    def _val(col: str) -> float:
        try:
            return float(latest_row.get(col, "0") or "0")
        except (TypeError, ValueError):
            return 0.0

    def _prev_val(col: str) -> float:
        if prev_row is None:
            return 0.0
        try:
            return float(prev_row.get(col, "0") or "0")
        except (TypeError, ValueError):
            return 0.0

    report_date = latest_row.get(COL_REPORT_DATE, retrieved_date[:10])
    open_interest = _val(COL_OPEN_INTEREST)
    prod_long = _val(COL_PROD_LONG)
    prod_short = _val(COL_PROD_SHORT)
    swap_long = _val(COL_SWAP_LONG)
    swap_short = _val(COL_SWAP_SHORT)
    mm_long = _val(COL_MM_LONG)
    mm_short = _val(COL_MM_SHORT)
    other_long = _val(COL_OTHER_LONG)
    other_short = _val(COL_OTHER_SHORT)

    producer_net = prod_long - prod_short
    swap_net = swap_long - swap_short
    # Compatibility aggregate proxy = Producer/Merchant + Swap Dealers.
    comm_long = prod_long + swap_long
    comm_short = prod_short + swap_short
    commercial_net = comm_long - comm_short
    # Non-commercial = Managed Money
    noncomm_net = mm_long - mm_short

    prev_prod_long = _prev_val(COL_PROD_LONG)
    prev_prod_short = _prev_val(COL_PROD_SHORT)
    prev_swap_long = _prev_val(COL_SWAP_LONG)
    prev_swap_short = _prev_val(COL_SWAP_SHORT)
    prev_mm_long = _prev_val(COL_MM_LONG)
    prev_mm_short = _prev_val(COL_MM_SHORT)
    prev_open_interest = _prev_val(COL_OPEN_INTEREST)

    prev_producer_net = prev_prod_long - prev_prod_short
    prev_swap_net = prev_swap_long - prev_swap_short
    prev_comm_long = prev_prod_long + prev_swap_long
    prev_comm_short = prev_prod_short + prev_swap_short
    prev_commercial_net = prev_comm_long - prev_comm_short
    prev_noncomm_net = prev_mm_long - prev_mm_short

    # Build MacroPoint for commercial_net (main signal) and supporting points
    points: list[MacroPoint] = []

    def _point(suffix: str, value: float) -> MacroPoint:
        return MacroPoint(
            symbol=f"{COT_SYMBOL}_{suffix}",
            date=report_date,
            value=round(value, 6),
            source=COT_SOURCE,
            source_url=CFTC_COT_URL,
            retrieved_at=retrieved_at,
            raw_path=raw_path_rel,
        )

    points.append(_point("commercial_net", commercial_net))
    points.append(_point("producer_net", producer_net))
    points.append(_point("swap_net", swap_net))
    points.append(_point("noncomm_net", noncomm_net))
    points.append(_point("open_interest", open_interest))
    points.append(_point("comm_long", comm_long))
    points.append(_point("comm_short", comm_short))
    points.append(_point("noncomm_long", mm_long))
    points.append(_point("noncomm_short", mm_short))
    points.append(_point("other_long", other_long))
    points.append(_point("other_short", other_short))

    # Also store previous week values as separate points
    if prev_row is not None:
        prev_report_date = prev_row.get(COL_REPORT_DATE, "")
        points.append(
            MacroPoint(
                symbol=f"{COT_SYMBOL}_commercial_net_prev",
                date=prev_report_date,
                value=round(prev_commercial_net, 6),
                source=COT_SOURCE,
                source_url=CFTC_COT_URL,
                retrieved_at=retrieved_at,
                raw_path=raw_path_rel,
            )
        )
        points.append(
            MacroPoint(
                symbol=f"{COT_SYMBOL}_producer_net_prev",
                date=prev_report_date,
                value=round(prev_producer_net, 6),
                source=COT_SOURCE,
                source_url=CFTC_COT_URL,
                retrieved_at=retrieved_at,
                raw_path=raw_path_rel,
            )
        )
        points.append(
            MacroPoint(
                symbol=f"{COT_SYMBOL}_swap_net_prev",
                date=prev_report_date,
                value=round(prev_swap_net, 6),
                source=COT_SOURCE,
                source_url=CFTC_COT_URL,
                retrieved_at=retrieved_at,
                raw_path=raw_path_rel,
            )
        )
        points.append(
            MacroPoint(
                symbol=f"{COT_SYMBOL}_noncomm_net_prev",
                date=prev_report_date,
                value=round(prev_noncomm_net, 6),
                source=COT_SOURCE,
                source_url=CFTC_COT_URL,
                retrieved_at=retrieved_at,
                raw_path=raw_path_rel,
            )
        )
        points.append(
            MacroPoint(
                symbol=f"{COT_SYMBOL}_open_interest_prev",
                date=prev_report_date,
                value=round(prev_open_interest, 6),
                source=COT_SOURCE,
                source_url=CFTC_COT_URL,
                retrieved_at=retrieved_at,
                raw_path=raw_path_rel,
            )
        )

    source_refs = [
        {
            "symbol": COT_SYMBOL,
            "source": COT_SOURCE,
            "source_url": CFTC_COT_URL,
            "raw_path": raw_path_rel,
            "contract_code": GOLD_CONTRACT_CODE,
            "market": GOLD_MARKET_NAME,
        }
    ]

    return CollectorResult(points=points, unavailable_symbols=[], source_refs=source_refs)


def _unavailable(reason: str) -> CollectorResult:
    return CollectorResult(
        points=[],
        unavailable_symbols=[COT_SYMBOL],
        source_refs=[
            {
                "symbol": COT_SYMBOL,
                "source": COT_SOURCE,
                "source_url": CFTC_COT_URL,
                "reason": reason,
            }
        ],
    )
