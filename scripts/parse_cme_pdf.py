from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.parsers.cme.pdf_parser import parse_pg64_pdf, write_detail_csv, write_json  # noqa: E402

MONTH_ORDER = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a CME PG64 Daily Bulletin PDF.")
    parser.add_argument("--pdf", required=True, help="Path to the PG64 PDF")
    parser.add_argument("--product", default="OG", help="Product code to parse")
    parser.add_argument(
        "--expiries",
        default="",
        help="Comma-separated expiry filter, e.g. JUN26,JUL26",
    )
    parser.add_argument("--out-dir", required=True, help="Output directory for parsed files")
    args = parser.parse_args()

    expiries = {item.strip().upper() for item in args.expiries.split(",") if item.strip()}
    expiry_tag = "_".join(sorted(expiries, key=_expiry_sort_key)) if expiries else "ALL"

    try:
        result = parse_pg64_pdf(Path(args.pdf), product=args.product, expiries=expiries or None)
    except Exception as exc:
        print(f"cme parse failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    status_tag = "PRELIM" if result.status == "PRELIMINARY" else result.status
    stem = f"{args.product}_{expiry_tag}_detail_{result.trade_date.replace('-', '')}_{status_tag}"
    json_path = out_dir / f"{stem}.json"
    csv_path = out_dir / f"{stem}.csv"

    write_json(result, json_path)
    write_detail_csv(result.detail_rows, csv_path)

    print(
        json.dumps(
            {
                "json_path": json_path.as_posix(),
                "csv_path": csv_path.as_posix(),
                "trade_date": result.trade_date,
                "rows": len(result.detail_rows),
                "summary_rows": len(result.summary_rows),
            },
            ensure_ascii=False,
        )
    )

def _expiry_sort_key(expiry: str) -> tuple[int, int]:
    month = MONTH_ORDER.get(expiry[:3].upper(), 99)
    year = int(expiry[3:]) if len(expiry) == 5 and expiry[3:].isdigit() else 99
    return (year, month)


if __name__ == "__main__":
    main()
