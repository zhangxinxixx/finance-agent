from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.models.analysis import ensure_analysis_tables  # noqa: E402
from database.models.engine import DATABASE_URL, SessionLocal  # noqa: E402
from database.models.execution import RunArtifact, ensure_execution_tables  # noqa: E402
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables  # noqa: E402
from database.models.task import TaskRun, ensure_task_tables  # noqa: E402
from database.queries.report import upsert_report_artifact, upsert_report_item  # noqa: E402


KNOWN_FAMILIES: dict[str, tuple[str, ...]] = {
    "jin10": ("outputs", "jin10"),
    "cme": ("outputs", "cme"),
    "macro": ("outputs", "macro"),
    "final_report": ("outputs", "final_report"),
    "strategy_card": ("outputs", "strategy_card"),
    "snapshots": ("features", "snapshots"),
    "news": ("features", "news"),
}
FAMILY_ALIASES = {
    "jin10_daily_report": "jin10",
    "jin10_weekly_report": "jin10",
}
REPORT_FAMILIES = frozenset({"final_report", "strategy_card", "macro", "jin10"})


@dataclass(frozen=True)
class Candidate:
    family: str
    relative_path: str
    absolute_path: Path
    trade_date: str | None
    run_id: str | None
    asset: str | None
    generated_at: datetime | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill legacy storage artifacts into artifact registry tables.")
    parser.add_argument("--date", help="Only scan artifacts matching YYYY-MM-DD in the known family path.")
    parser.add_argument(
        "--family",
        choices=sorted({*KNOWN_FAMILIES, *FAMILY_ALIASES}),
        help="Restrict scanning to one known family.",
    )
    parser.add_argument("--limit", type=int, help="Maximum number of candidate files to process after filtering.")
    parser.add_argument(
        "--storage-root",
        default=str(PROJECT_ROOT / "storage"),
        help="Storage root to scan. Must resolve inside the repo project root storage directory.",
    )
    parser.add_argument("--database-url", default="", help="Optional SQLAlchemy database URL. Defaults to project DATABASE_URL.")
    parser.add_argument("--dry-run", action="store_true", help="Preview planned writes without touching the database.")
    parser.add_argument("--commit", action="store_true", help="Persist changes to the database.")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    session_factory=None,
    project_root: Path | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    dry_run = not args.commit
    if args.commit and args.dry_run:
        parser.error("--dry-run and --commit are mutually exclusive")

    root = (project_root or PROJECT_ROOT).resolve()
    storage_root = _resolve_storage_root(root=root, raw_storage_root=args.storage_root)

    candidates = list(iter_candidates(storage_root=storage_root, family=args.family, target_date=args.date, limit=args.limit))
    summary = {
        "dry_run": dry_run,
        "storage_root": str(storage_root),
        "scanned": len(candidates),
        "planned": 0,
        "written": 0,
        "skipped": 0,
        "families": sorted({candidate.family for candidate in candidates}),
    }

    if not candidates:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0

    database_url = args.database_url or DATABASE_URL
    session_factory = session_factory or _session_factory(database_url)
    _ensure_sqlite_parent(database_url)

    with session_factory() as session:
        if dry_run:
            for candidate in candidates:
                planned, skipped = _plan_candidate(session, candidate)
                summary["planned"] += planned
                summary["skipped"] += skipped
        else:
            try:
                ensure_task_tables(session)
                ensure_execution_tables(session)
                ensure_analysis_tables(session)
                ensure_report_tables(session)
                for candidate in candidates:
                    planned, written, skipped = _write_candidate(session, candidate)
                    summary["planned"] += planned
                    summary["written"] += written
                    summary["skipped"] += skipped
                session.commit()
            except Exception:
                session.rollback()
                raise

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def iter_candidates(
    *,
    storage_root: Path,
    family: str | None,
    target_date: str | None,
    limit: int | None,
) -> Iterable[Candidate]:
    selected_families = [_canonical_family(family)] if family else list(KNOWN_FAMILIES)
    seen = 0

    for family_name in selected_families:
        family_root = storage_root.joinpath(*KNOWN_FAMILIES[family_name])
        if not family_root.exists():
            continue
        for path in sorted(_iter_files(family_root)):
            candidate = _build_candidate(storage_root=storage_root, family=family_name, path=path)
            if candidate is None:
                continue
            if target_date and candidate.trade_date != target_date:
                continue
            yield candidate
            seen += 1
            if limit is not None and seen >= max(limit, 0):
                return


def _iter_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def _build_candidate(*, storage_root: Path, family: str, path: Path) -> Candidate | None:
    relative_storage = path.relative_to(storage_root)
    relative_path = Path("storage") / relative_storage
    parts = relative_storage.parts
    trade_date = None
    run_id = None
    asset = None

    if family == "final_report":
        if len(parts) < 5:
            return None
        asset = parts[2]
        trade_date = parts[3]
        run_id = parts[4]
    elif family == "strategy_card":
        if len(parts) < 5:
            return None
        asset = parts[2]
        trade_date = parts[3]
        run_id = parts[4]
    elif family == "macro":
        if len(parts) < 4:
            return None
        trade_date = parts[2]
        run_id = parts[3] if len(parts) >= 5 else None
    elif family == "cme":
        trade_date = _first_iso_date(parts)
        run_id = _first_uuid_like(parts)
    elif family == "jin10":
        if len(parts) < 4:
            return None
        trade_date = parts[2]
        run_id = parts[3]
    elif family in {"snapshots", "news"}:
        trade_date = _first_iso_date(parts)
        run_id = _first_uuid_like(parts)

    return Candidate(
        family=family,
        relative_path=relative_path.as_posix(),
        absolute_path=path,
        trade_date=trade_date,
        run_id=run_id,
        asset=asset,
        generated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
    )


def _plan_candidate(session: Session, candidate: Candidate) -> tuple[int, int]:
    if _should_write_report_item(candidate):
        return 1, 0
    if _can_write_run_artifact(session, candidate):
        return 1, 0
    return 0, 1 if candidate.run_id is not None else 0


def _write_candidate(session: Session, candidate: Candidate) -> tuple[int, int, int]:
    should_write_report = _should_write_report_item(candidate)
    can_write_run_artifact = _can_write_run_artifact(session, candidate)
    planned = 1 if should_write_report or can_write_run_artifact else 0
    written = 0
    skipped = 0

    report_id = None
    if should_write_report:
        report_id = _report_id_for_candidate(candidate)
        existing_report = session.get(ReportItem, report_id)
        upsert_report_item(
            session,
            {
                "report_id": report_id,
                "family": _report_family_name(candidate.family),
                "report_type": _report_type_for_candidate(candidate),
                "title": _title_for_candidate(candidate),
                "asset": candidate.asset,
                "trade_date": candidate.trade_date,
                "run_id": candidate.run_id,
                "snapshot_id": None,
                "data_status": "legacy_backfill",
                "lifecycle_status": "generated",
                "source_refs": [],
                "metadata": _artifact_metadata(candidate),
            },
        )
        if existing_report is None:
            written += 1

    digest = _hash_file(candidate.absolute_path)
    artifact_type = _artifact_type_for_candidate(candidate)

    run = _resolve_run(session, candidate.run_id)
    if run is not None:
        existing_run_artifact = session.scalar(
            select(RunArtifact).where(RunArtifact.run_id == run.id, RunArtifact.file_path == candidate.relative_path)
        )
        if existing_run_artifact is None:
            session.add(
                RunArtifact(
                    run_id=run.id,
                    task_id=None,
                    artifact_type=artifact_type,
                    file_path=candidate.relative_path,
                    storage_backend="local_fs",
                    sha256=digest,
                    content_type=_guess_content_type(candidate.absolute_path),
                    byte_size=candidate.absolute_path.stat().st_size,
                    generated_at=candidate.generated_at,
                    source_refs_data=[],
                    artifact_metadata=_artifact_metadata(candidate),
                    source_refs="[]",
                    metadata_json=json.dumps(_artifact_metadata(candidate), ensure_ascii=False, sort_keys=True),
                )
            )
            written += 1
    elif candidate.run_id is not None:
        skipped += 1

    if report_id is not None:
        artifact_id = f"{report_id}:{candidate.relative_path}"
        existing_report_artifact = session.get(ReportArtifact, artifact_id)
        upsert_report_artifact(
            session,
            {
                "artifact_id": artifact_id,
                "report_id": report_id,
                "artifact_type": artifact_type,
                "file_path": candidate.relative_path,
                "storage_backend": "local_fs",
                "generated_at": candidate.generated_at.isoformat() if candidate.generated_at else None,
                "status": "generated",
                "sha256": digest,
                "content_type": _guess_content_type(candidate.absolute_path),
                "byte_size": candidate.absolute_path.stat().st_size,
                "is_primary": _is_primary_report_artifact(candidate),
                "source_refs": [],
                "metadata": _artifact_metadata(candidate),
            },
        )
        if existing_report_artifact is None:
            written += 1

    return planned, written, skipped


def _resolve_storage_root(*, root: Path, raw_storage_root: str) -> Path:
    candidate = Path(raw_storage_root).expanduser()
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    else:
        candidate = candidate.resolve()

    allowed_root = (root / "storage").resolve()
    if candidate != allowed_root and allowed_root not in candidate.parents:
        raise ValueError(f"storage root must stay inside {allowed_root}")
    return candidate


def _resolve_run(session: Session, run_id: str | None) -> TaskRun | None:
    if run_id is None:
        return None
    try:
        return session.get(TaskRun, uuid.UUID(run_id))
    except ValueError:
        return None


def _can_write_run_artifact(session: Session, candidate: Candidate) -> bool:
    return _resolve_run(session, candidate.run_id) is not None


def _should_write_report_item(candidate: Candidate) -> bool:
    return candidate.family in REPORT_FAMILIES and candidate.run_id is not None


def _report_id_for_candidate(candidate: Candidate) -> str:
    if candidate.family == "final_report":
        return f"final_report:{candidate.run_id}"
    if candidate.family == "strategy_card":
        return f"strategy_card:{candidate.run_id}"
    if candidate.family == "jin10":
        return str(candidate.run_id)
    return f"macro_report:{candidate.run_id}"


def _report_family_name(family: str) -> str:
    if family == "final_report":
        return "final_report_markdown"
    if family == "strategy_card":
        return "strategy_card"
    if family == "jin10":
        return "jin10_daily_visual"
    return "macro_report"


def _report_type_for_candidate(candidate: Candidate) -> str:
    if candidate.family == "jin10":
        return "jin10_daily_report"
    if candidate.family == "macro":
        return "macro_report"
    return candidate.family


def _title_for_candidate(candidate: Candidate) -> str:
    asset = candidate.asset or "Unknown"
    if candidate.family == "final_report":
        return f"{asset} 综合报告（{candidate.trade_date}）" if candidate.trade_date else f"{asset} 综合报告"
    if candidate.family == "strategy_card":
        return f"{asset} 策略卡片（{candidate.trade_date}）" if candidate.trade_date else f"{asset} 策略卡片"
    if candidate.family == "jin10":
        return f"Jin10 daily report（{candidate.trade_date}）" if candidate.trade_date else "Jin10 daily report"
    return f"宏观数据报告（{candidate.trade_date}）" if candidate.trade_date else "宏观数据报告"


def _artifact_type_for_candidate(candidate: Candidate) -> str:
    suffix = candidate.absolute_path.suffix.lower()
    if suffix == ".md":
        return "analysis_md"
    if suffix == ".json":
        return "structured_json"
    if suffix == ".html":
        return "visual_html"
    return "raw_file"


def _is_primary_report_artifact(candidate: Candidate) -> bool:
    name = candidate.absolute_path.name
    if candidate.family == "final_report":
        return name == "final_report.md"
    if candidate.family == "strategy_card":
        return name == "strategy_card.json"
    if candidate.family == "macro":
        return name in {"macro_report.md", "macro_snapshot.md"}
    if candidate.family == "jin10":
        return name in {"daily_analysis.json", "daily_analysis.html"}
    return False


def _artifact_metadata(candidate: Candidate) -> dict[str, Any]:
    return {
        "backfill_family": candidate.family,
        "relative_path": candidate.relative_path,
        "storage_backend": "local_fs",
    }


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _guess_content_type(path: Path) -> str | None:
    return mimetypes.guess_type(path.name)[0]


def _first_iso_date(parts: tuple[str, ...]) -> str | None:
    for part in parts:
        try:
            date.fromisoformat(part)
        except ValueError:
            continue
        return part
    return None


def _canonical_family(family: str | None) -> str | None:
    if family is None:
        return None
    return FAMILY_ALIASES.get(family, family)


def _first_uuid_like(parts: tuple[str, ...]) -> str | None:
    for part in parts:
        try:
            uuid.UUID(part)
        except ValueError:
            continue
        return part
    return None


def _session_factory(database_url: str):
    if database_url == DATABASE_URL:
        return SessionLocal
    engine = create_engine(database_url, echo=False)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return
    db_path = Path(url.database)
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
