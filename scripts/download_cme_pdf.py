from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.collectors.cme.downloader import DEFAULT_SECTION_FILE, download_cme_pdf  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and archive a CME Daily Bulletin PDF.")
    parser.add_argument("--section", default=DEFAULT_SECTION_FILE, help="Daily bulletin section PDF filename")
    parser.add_argument("--date", default="latest", help="YYYY-MM-DD or latest")
    parser.add_argument("--storage-root", default=str(PROJECT_ROOT), help="Project root / storage root")
    args = parser.parse_args()

    try:
        result = download_cme_pdf(
            section_file=args.section,
            report_date=args.date,
            storage_root=Path(args.storage_root),
        )
    except Exception as exc:
        print(f"cme download failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
