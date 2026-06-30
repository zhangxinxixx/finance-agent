from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.analysis.gold_mainline_engine import archive_gold_macro_overview, build_gold_macro_overview
from apps.features.news.gold_event_mainlines import archive_gold_event_mainlines, build_gold_event_mainlines


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild gold_event_mainlines and gold_macro_overview from existing news feature artifacts."
    )
    parser.add_argument("--storage-root", default="storage", help="finance-agent storage root.")
    parser.add_argument("--date", default=None, help="Source artifact date under features/news/YYYY-MM-DD.")
    parser.add_argument("--run-id", default=None, help="Source artifact run id under features/news/<date>/<run-id>.")
    parser.add_argument(
        "--output-run-id",
        default=None,
        help="Output run id. Defaults to gold-mainlines-refresh-<UTC timestamp>.",
    )
    parser.add_argument(
        "--macro-date",
        default=None,
        help="Macro snapshot date under features/macro/YYYY-MM-DD. Defaults to source date when available.",
    )
    parser.add_argument(
        "--macro-run-id",
        default=None,
        help="Macro snapshot run id under features/macro/<date>/<run-id>. Defaults to latest run for macro date.",
    )
    parser.add_argument(
        "--market-context",
        default=None,
        help="Optional JSON file containing deterministic market context, e.g. XAUUSD price/candles.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    storage_root = Path(args.storage_root)
    try:
        source_date, source_run_id = _resolve_source_run(
            storage_root=storage_root,
            date=args.date,
            run_id=args.run_id,
        )
        output_run_id = args.output_run_id or _default_output_run_id()
        event_candidates_payload = _read_json(
            storage_root / "features" / "news" / source_date / source_run_id / "event_candidates.json"
        )
        impact_assessments_payload = _read_json(
            storage_root / "features" / "news" / source_date / source_run_id / "impact_assessments.json"
        )
        events = list(event_candidates_payload.get("event_candidates") or [])
        impacts = list(impact_assessments_payload.get("impact_assessments") or [])
        as_of = str(event_candidates_payload.get("as_of") or datetime.now(timezone.utc).isoformat())

        gold_event_mainlines = build_gold_event_mainlines(
            events,
            impact_assessments=impacts,
            as_of=as_of,
        )
        gold_event_mainlines_path = archive_gold_event_mainlines(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            bundle=gold_event_mainlines,
        )
        gold_event_mainlines_payload = gold_event_mainlines.to_dict()
        gold_event_mainlines_payload["artifact_refs"] = [
            {"artifact_type": "event_candidates", "path": f"features/news/{source_date}/{source_run_id}/event_candidates.json"},
            {"artifact_type": "impact_assessments", "path": f"features/news/{source_date}/{source_run_id}/impact_assessments.json"},
            {"artifact_type": "gold_event_mainlines", "path": gold_event_mainlines_path},
        ]
        macro_context, macro_snapshot_path = _resolve_macro_context(
            storage_root=storage_root,
            source_date=source_date,
            macro_date=args.macro_date,
            macro_run_id=args.macro_run_id,
        )
        market_context, market_context_path = _resolve_market_context(args.market_context)
        if macro_snapshot_path:
            gold_event_mainlines_payload["artifact_refs"].append({"artifact_type": "macro_snapshot", "path": macro_snapshot_path})
        if market_context_path:
            gold_event_mainlines_payload["artifact_refs"].append({"artifact_type": "market_context", "path": market_context_path})
        gold_macro_overview = build_gold_macro_overview(
            gold_event_mainlines_payload,
            macro_context=macro_context,
            market_context=market_context,
        )
        input_snapshot_ids = {"gold_event_mainlines": gold_event_mainlines_path}
        if macro_snapshot_path:
            input_snapshot_ids["macro_snapshot"] = macro_snapshot_path
        if market_context_path:
            input_snapshot_ids["market_context"] = market_context_path
        gold_macro_overview_path = archive_gold_macro_overview(
            storage_root=storage_root,
            retrieved_date=source_date,
            run_id=output_run_id,
            overview=gold_macro_overview,
            input_snapshot_ids=input_snapshot_ids,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1

    summary = {
        "status": "success",
        "retrieved_date": source_date,
        "source_run_id": source_run_id,
        "output_run_id": output_run_id,
        "gold_event_mainlines_path": gold_event_mainlines_path,
        "gold_macro_overview_path": gold_macro_overview_path,
        "gold_mainline_count": len(gold_event_mainlines.mainlines),
        "gold_event_link_count": len(gold_event_mainlines.event_links),
        "gold_macro_theme_count": len(gold_macro_overview.theme_rankings),
        "gold_verification_item_count": len(gold_macro_overview.verification_matrix),
        "gold_dominant_mainline": gold_macro_overview.dominant_mainline,
        "gold_readiness": gold_macro_overview.analysis_readiness.to_dict(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _resolve_source_run(*, storage_root: Path, date: str | None, run_id: str | None) -> tuple[str, str]:
    if bool(date) != bool(run_id):
        raise ValueError("--date and --run-id must be provided together.")
    if date and run_id:
        source_dir = storage_root / "features" / "news" / date / run_id
        _require_source_files(source_dir)
        return date, run_id

    base = storage_root / "features" / "news"
    if not base.exists():
        raise FileNotFoundError(f"No news feature artifacts found under {base}")
    for date_dir in sorted((item for item in base.iterdir() if item.is_dir()), reverse=True):
        for run_dir in sorted((item for item in date_dir.iterdir() if item.is_dir()), reverse=True):
            if _has_source_files(run_dir):
                return date_dir.name, run_dir.name
    raise FileNotFoundError(f"No event_candidates.json + impact_assessments.json pair found under {base}")


def _require_source_files(source_dir: Path) -> None:
    missing = [
        path.name
        for path in [source_dir / "event_candidates.json", source_dir / "impact_assessments.json"]
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(f"Missing source artifact(s) in {source_dir}: {', '.join(missing)}")


def _has_source_files(source_dir: Path) -> bool:
    return (source_dir / "event_candidates.json").exists() and (source_dir / "impact_assessments.json").exists()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _resolve_macro_context(*, storage_root: Path, source_date: str, macro_date: str | None, macro_run_id: str | None) -> tuple[dict[str, Any], str | None]:
    if bool(macro_date) != bool(macro_run_id) and macro_run_id:
        raise ValueError("--macro-date must be provided when --macro-run-id is provided.")
    date = macro_date or source_date
    base = storage_root / "features" / "macro"
    candidates: list[tuple[Path, str]] = []
    if macro_run_id:
        path = base / date / macro_run_id / "macro_snapshot.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing macro snapshot: {path}")
        candidates.append((path, f"features/macro/{date}/{macro_run_id}/macro_snapshot.json"))
    else:
        date_dir = base / date
        if date_dir.exists():
            for run_dir in sorted((item for item in date_dir.iterdir() if item.is_dir()), reverse=True):
                path = run_dir / "macro_snapshot.json"
                if path.exists():
                    candidates.append((path, f"features/macro/{date}/{run_dir.name}/macro_snapshot.json"))
                    break
    if not candidates:
        return {}, None
    path, rel_path = candidates[0]
    return _read_json(path), rel_path


def _resolve_market_context(value: str | None) -> tuple[dict[str, Any], str | None]:
    if not value:
        return {}, None
    path = Path(value)
    payload = _read_json(path)
    return payload, path.as_posix()


def _default_output_run_id() -> str:
    return "gold-mainlines-refresh-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
