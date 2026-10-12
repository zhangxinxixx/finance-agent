from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.features.jin10.positioning_cme_validation import (  # noqa: E402
    extract_positioning_oi_changes,
    validate_positioning_against_cme,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Jin10 positioning rows against CME option OI changes.")
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--article-id", required=True)
    parser.add_argument("--cme-date", required=True)
    parser.add_argument("--storage-root", default="storage")
    args = parser.parse_args()

    root = Path(args.storage_root)
    layout_path = root / "parsed" / "jin10" / args.report_date / args.article_id / "vision_layout.json"
    cme_path = root / "parsed" / "cme" / args.cme_date / f"OG_ALL_detail_{args.cme_date.replace('-', '')}_PRELIM.json"
    if not layout_path.is_file():
        raise FileNotFoundError(f"positioning layout not found: {layout_path}")
    if not cme_path.is_file():
        raise FileNotFoundError(f"CME detail rows not found: {cme_path}")

    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    cme_payload = json.loads(cme_path.read_text(encoding="utf-8"))
    report_rows = extract_positioning_oi_changes(list(layout.get("pages") or []))
    artifact = validate_positioning_against_cme(
        article_id=args.article_id,
        report_date=args.report_date,
        report_rows=report_rows,
        cme_payload=cme_payload,
        report_source_ref={
            "source": "jin10_positioning_report",
            "source_ref": f"jin10:274:{args.article_id}",
            "path": str(layout_path),
        },
        cme_source_ref={
            "source": "cme_daily_bulletin",
            "source_ref": f"cme:OG:{args.cme_date}:PRELIM",
            "path": str(cme_path),
            "status": cme_payload.get("status"),
        },
    )
    output_dir = root / "features" / "jin10" / args.report_date / args.article_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "positioning_cme_validation.json"
    output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), **artifact["summary"], "validation_status": artifact["validation_status"]}, ensure_ascii=False, indent=2))
    return 0 if artifact["validation_status"] == "confirmed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
