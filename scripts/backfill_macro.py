from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from apps.analysis.macro.conclusion import build_macro_conclusion  # noqa: E402
from apps.analysis.macro.full_report import render_macro_full_report_markdown  # noqa: E402
from apps.analysis.macro.summary import render_macro_snapshot_markdown  # noqa: E402
from apps.collectors.dxy.collector import collect_dxy_series  # noqa: E402
from apps.collectors.fed.collector import collect_fed_series  # noqa: E402
from apps.collectors.fred.collector import FRED_SERIES, collect_fred_series, fred_source_url  # noqa: E402
from apps.collectors.treasury.collector import collect_treasury_series  # noqa: E402
from apps.features.macro.snapshot import build_macro_snapshot  # noqa: E402
from apps.output.artifacts import artifact_run_dir, normalize_run_id  # noqa: E402
from apps.parsers.macro.models import CollectorResult, MacroPoint  # noqa: E402
from apps.runtime.task_recorder import record_task  # noqa: E402
from apps.worker.pipelines.macro import persist_macro_feature_snapshots, persist_macro_points  # noqa: E402
from database.models.analysis import ensure_analysis_tables  # noqa: E402
from database.models.engine import SessionLocal  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill macro collectors and snapshot.")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD or latest")
    parser.add_argument("--run-id", default=None, help="Run identifier for separate same-day artifacts.")
    parser.add_argument("--record-task-runs", action="store_true", help="Write macro_collect / macro_feature / report_render entries into task_runs/task_steps.")
    parser.add_argument("--no-db", action="store_true", help="Do not persist normalized observations/features to the database.")
    args = parser.parse_args()

    as_of = date.today().isoformat() if args.date == "latest" else _validate_iso_date(args.date)
    run_id = normalize_run_id(args.run_id)
    storage_root = PROJECT_ROOT / "storage"

    with _recorded_backfill_run(
        enabled=args.record_task_runs,
        task_type="macro_collect",
        task_name="Macro collect backfill",
        trade_date=as_of,
    ) as rec:
        fred = _collect_fred_or_unavailable(as_of=as_of, storage_root=storage_root)
        fed = collect_fed_series(retrieved_date=as_of, storage_root=storage_root)
        treasury = collect_treasury_series(retrieved_date=as_of, storage_root=storage_root)
        dxy = collect_dxy_series(retrieved_date=as_of, storage_root=storage_root)
        source_refs = [*fred.source_refs, *fed.source_refs, *treasury.source_refs, *dxy.source_refs]
        _record_step(
            rec,
            "macro_collect",
            source_refs=source_refs,
            output_refs=_raw_output_refs(source_refs),
        )

    all_points: list[MacroPoint] = [*fred.points, *fed.points, *treasury.points, *dxy.points]
    points = [point.to_dict() for point in all_points]
    unavailable = [*fred.unavailable_symbols, *fed.unavailable_symbols, *treasury.unavailable_symbols, *dxy.unavailable_symbols]
    source_refs = [*fred.source_refs, *fed.source_refs, *treasury.source_refs, *dxy.source_refs]

    output_dir = artifact_run_dir(storage_root, layer="features", domain="macro", date=as_of, run_id=run_id)
    report_dir = artifact_run_dir(storage_root, layer="outputs", domain="macro", date=as_of, run_id=run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    snapshot_json = output_dir / "macro_snapshot.json"
    conclusion_json = output_dir / "macro_conclusion.json"
    snapshot_md = report_dir / "macro_snapshot.md"
    full_report_md = report_dir / "macro_full_report.md"

    with _recorded_backfill_run(
        enabled=args.record_task_runs,
        task_type="macro_feature",
        task_name="Macro feature backfill",
        trade_date=as_of,
    ) as rec:
        snapshot = build_macro_snapshot(points, as_of=as_of, unavailable_symbols=unavailable, source_refs=source_refs)
        conclusion = build_macro_conclusion(snapshot)
        snapshot_json.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        conclusion_json.write_text(json.dumps(conclusion.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _record_step(
            rec,
            "macro_feature",
            source_refs=source_refs,
            output_refs=[
                {"artifact_type": "feature_json", "file_path": snapshot_json.as_posix()},
                {"artifact_type": "structured_json", "file_path": conclusion_json.as_posix()},
            ],
        )

    with _recorded_backfill_run(
        enabled=args.record_task_runs,
        task_type="report_render",
        task_name="Macro report render backfill",
        trade_date=as_of,
    ) as rec:
        snapshot_md.write_text(render_macro_snapshot_markdown(snapshot), encoding="utf-8")
        full_report_md.write_text(render_macro_full_report_markdown(snapshot, conclusion), encoding="utf-8")
        _record_step(
            rec,
            "report_render",
            source_refs=source_refs,
            output_refs=[
                {"artifact_type": "analysis_md", "file_path": snapshot_md.as_posix()},
                {"artifact_type": "analysis_md", "file_path": full_report_md.as_posix()},
            ],
        )

    database = _persist_to_database(
        enabled=not args.no_db,
        storage_root=storage_root,
        all_points=all_points,
        source_refs=source_refs,
        run_id=run_id,
        as_of=as_of,
        snapshot_payload=snapshot.to_dict(),
        conclusion_payload=conclusion.to_dict(),
        snapshot_path=snapshot_json,
        conclusion_path=conclusion_json,
    )

    print(json.dumps({
        "run_id": run_id,
        "json": snapshot_json.as_posix(),
        "conclusion": conclusion_json.as_posix(),
        "markdown": snapshot_md.as_posix(),
        "full_report": full_report_md.as_posix(),
        "unavailable": snapshot.unavailable_symbols,
        "database": database,
    }, ensure_ascii=False))


def _persist_to_database(
    *,
    enabled: bool,
    storage_root: Path,
    all_points: list[MacroPoint],
    source_refs: list[dict[str, str]],
    run_id: str,
    as_of: str,
    snapshot_payload: dict,
    conclusion_payload: dict,
    snapshot_path: Path,
    conclusion_path: Path,
) -> dict[str, object]:
    """Persist only normalized macro data and computed feature snapshots.

    Raw collector responses stay in ``storage/raw`` and are linked through
    ``raw_path``/``source_refs``; their response bodies are intentionally not
    copied into JSON/JSONB database columns.
    """
    result: dict[str, object] = {
        "enabled": enabled,
        "macro_observation_upserts": 0,
        "raw_artifact_registry_upserts": 0,
        "feature_snapshot_upserts": 0,
    }
    if not enabled:
        return result

    # A failed collection with no normalized points or raw files has nothing
    # useful to add to the DB. The feature/report files still record the
    # unavailable symbols and remain the source of the failed run's evidence.
    has_raw_files = any(str(ref.get("raw_path") or "").strip() for ref in source_refs)
    if not all_points and not has_raw_files:
        result["skipped"] = "no_normalized_data"
        return result

    with SessionLocal() as db_session:
        try:
            ensure_analysis_tables(db_session)
            observation_upserts, raw_artifact_upserts = persist_macro_points(
                db_session,
                storage_root=storage_root,
                all_points=all_points,
                all_refs=source_refs,
                run_id=run_id,
            )
            feature_snapshot_upserts = persist_macro_feature_snapshots(
                db_session,
                snapshot_payload=snapshot_payload,
                conclusion_payload=conclusion_payload,
                snapshot_artifact_path=snapshot_path,
                conclusion_artifact_path=conclusion_path,
                trade_date=as_of,
                run_id=run_id,
                source_refs=source_refs,
                unavailable_symbols=list(snapshot_payload.get("unavailable_symbols") or []),
            )
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    result["macro_observation_upserts"] = observation_upserts
    result["raw_artifact_registry_upserts"] = raw_artifact_upserts
    result["feature_snapshot_upserts"] = feature_snapshot_upserts
    return result


def _collect_fred_or_unavailable(*, as_of: str, storage_root: Path) -> CollectorResult:
    try:
        return collect_fred_series(retrieved_date=as_of, storage_root=storage_root)
    except Exception as exc:
        reason = f"FRED collector failed: {type(exc).__name__}: {exc}"
        return CollectorResult(points=[], unavailable_symbols=list(FRED_SERIES), source_refs=[
            {"symbol": symbol, "source": "fred", "source_url": fred_source_url(symbol), "reason": reason}
            for symbol in FRED_SERIES
        ])


class _NoopRecorder:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def _recorded_backfill_run(*, enabled: bool, task_type: str, task_name: str, trade_date: str):
    if not enabled:
        return _NoopRecorder()
    return record_task(task_type=task_type, task_name=task_name, trade_date=trade_date)


def _record_step(recorder, step_name: str, *, source_refs: list[dict[str, str]], output_refs: list[dict[str, str]]) -> None:
    if recorder is None:
        return
    recorder.step(
        step_name,
        status="success",
        source_refs=source_refs,
        output_refs=output_refs,
    )


def _raw_output_refs(source_refs: list[dict[str, str]]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for ref in source_refs:
        file_path = str(ref.get("raw_path") or "").strip()
        if not file_path or file_path in seen:
            continue
        seen.add(file_path)
        refs.append({"artifact_type": "raw_file", "file_path": file_path})
    return refs


def _validate_iso_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"--date must be YYYY-MM-DD or latest, got {value!r}") from exc
    return parsed.isoformat()


if __name__ == "__main__":
    main()
