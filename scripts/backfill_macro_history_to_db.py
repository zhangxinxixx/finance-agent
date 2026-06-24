from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.models.engine import DATABASE_URL, SessionLocal  # noqa: E402
from database.models.analysis import AnalysisSnapshot, ensure_analysis_tables  # noqa: E402
from database.queries.analysis import upsert_analysis_snapshot  # noqa: E402


@dataclass
class ImportResult:
    scanned: int = 0
    imported: int = 0
    skipped: int = 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill macro snapshot history into analysis_snapshots.")
    parser.add_argument("--months", type=int, default=3, help="How many recent months to include. Default: 3")
    parser.add_argument("--asset", default="XAUUSD", help="Asset name stored in analysis_snapshots. Default: XAUUSD")
    parser.add_argument(
        "--storage-root",
        default=str(PROJECT_ROOT / "storage"),
        help="Project storage root. Default: ./storage",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="Optional SQLAlchemy database URL. Defaults to DATABASE_URL.",
    )
    args = parser.parse_args()

    storage_root = Path(args.storage_root).resolve()
    macro_root = storage_root / "features" / "macro"
    cutoff = date.today() - timedelta(days=max(args.months, 1) * 31)
    database_url = args.database_url or DATABASE_URL

    session_factory = _session_factory(database_url)
    _ensure_sqlite_parent(database_url)

    result = ImportResult()
    imported_rows: list[dict[str, Any]] = []

    with session_factory() as session:
        try:
            ensure_analysis_tables(session)
            for snapshot_path in iter_macro_snapshot_paths(macro_root, cutoff=cutoff):
                result.scanned += 1
                payload = load_macro_snapshot_payload(snapshot_path, asset=args.asset)
                before_count = _snapshot_count(session)
                upsert_analysis_snapshot(
                    session,
                    payload=payload,
                    artifact_path=str(snapshot_path.relative_to(PROJECT_ROOT)),
                )
                after_count = _snapshot_count(session)
                if after_count > before_count:
                    imported_rows.append(
                        {
                            "trade_date": payload["trade_date"],
                            "run_id": payload["run_id"],
                            "snapshot_id": payload["snapshot_id"],
                        }
                    )
            session.commit()
        except Exception:
            session.rollback()
            raise

    unique_rows = {(row["snapshot_id"], row["run_id"]) for row in imported_rows}
    result.imported = len(unique_rows)
    result.skipped = max(result.scanned - result.imported, 0)

    print(
        json.dumps(
            {
                "cutoff_date": cutoff.isoformat(),
                "scanned": result.scanned,
                "imported": result.imported,
                "skipped": result.skipped,
                "database_url": _display_database_url(database_url),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def iter_macro_snapshot_paths(macro_root: Path, *, cutoff: date) -> list[Path]:
    if not macro_root.exists():
        return []

    paths: list[Path] = []
    for date_dir in sorted((d for d in macro_root.iterdir() if d.is_dir()), reverse=False):
        trade_date = _parse_iso_date(date_dir.name)
        if trade_date is None or trade_date < cutoff:
            continue

        direct = date_dir / "macro_snapshot.json"
        if direct.exists():
            paths.append(direct)

        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=False):
            nested = run_dir / "macro_snapshot.json"
            if nested.exists():
                paths.append(nested)

    return paths


def load_macro_snapshot_payload(snapshot_path: Path, *, asset: str) -> dict[str, Any]:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    trade_date = str(payload.get("as_of") or snapshot_path.parent.name)
    run_id = infer_run_id(snapshot_path)
    snapshot_id = f"{asset}:{trade_date}:macro:{run_id}"
    source_refs = payload.get("source_refs") if isinstance(payload.get("source_refs"), list) else []

    return {
        "snapshot_id": snapshot_id,
        "asset": asset,
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_time": None,
        "status": "success",
        "input_snapshot_ids": {"macro": f"macro:{trade_date}:{run_id}"},
        "source_refs": source_refs,
        "macro": payload,
        "options": None,
        "positioning": None,
        "news": None,
        "technical": None,
        "payload": {
            "macro_history": payload,
            "timeframe": "1d",
            "source": "storage/features/macro",
        },
    }


def infer_run_id(snapshot_path: Path) -> str:
    parent = snapshot_path.parent
    if parent.name == "macro":
        raise ValueError(f"unexpected macro snapshot path: {snapshot_path}")
    if parent.parent.name == "macro":
        return "default"
    return parent.name


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _session_factory(database_url: str):
    if database_url == DATABASE_URL:
        return SessionLocal
    engine = create_engine(database_url, echo=False)
    return sessionmaker(bind=engine)


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return
    db_path = Path(url.database)
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)


def _display_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.password:
        return str(url.set(password="***"))
    return str(url)


def _snapshot_count(session) -> int:
    return session.query(AnalysisSnapshot).count()


if __name__ == "__main__":
    main()
