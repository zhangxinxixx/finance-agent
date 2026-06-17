from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.collectors.jin10.adapter import (
    build_jin10_outputs,
    persist_jin10_agent_outputs,
    write_jin10_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Index already-fetched Jin10 VIP reports.")
    parser.add_argument("--date", required=True, help="Report date, for example 2026-05-06.")
    parser.add_argument("--category", help="Jin10 category code, for example 270.")
    parser.add_argument("--external-root", default="~/jin10-reports", help="External Jin10 output root.")
    parser.add_argument("--storage-root", default="storage", help="finance-agent storage root.")
    args = parser.parse_args()

    outputs = build_jin10_outputs(
        external_root=Path(args.external_root).expanduser(),
        date=args.date,
        category=args.category,
    )
    written = write_jin10_outputs(outputs, storage_root=args.storage_root)
    persisted_agent_outputs = persist_jin10_agent_outputs(outputs, storage_root=args.storage_root)

    summary = {
        "date": args.date,
        "category": args.category,
        "reports": len(outputs["parsed"]["reports"]),
        "unavailable_symbols": outputs["parsed"]["unavailable_symbols"],
        "persisted_agent_outputs": persisted_agent_outputs,
        "written": {layer: str(path) for layer, path in written.items()},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
