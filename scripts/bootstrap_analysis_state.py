"""Bootstrap the first canonical analysis state from accepted artifacts."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.analysis.state.bootstrap import (  # noqa: E402
    BootstrapApproval,
    build_bootstrap_candidate,
    build_recovery_artifact_scoped,
    materialize_bootstrap_candidate,
    validate_artifact_path,
    write_json_artifact,
)
from apps.analysis.state.hashing import content_hash  # noqa: E402
from database.models.analysis import AnalysisSnapshot, FinalAnalysisResult  # noqa: E402
from database.models.engine import DATABASE_URL, SessionLocal  # noqa: E402


logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    storage_root = Path(args.storage_root).expanduser().resolve()
    final_path = _optional_input_path(args.final_result_json, storage_root=storage_root)
    overview_path = _input_path(args.gold_overview_json, storage_root=storage_root)
    card_path = _optional_input_path(args.strategy_card_json, storage_root=storage_root)
    database_url = args.database_url or DATABASE_URL

    session_factory = _session_factory(database_url)
    with session_factory() as session:
        final_result: FinalAnalysisResult | dict[str, Any]
        if final_path is not None:
            if args.commit:
                parser.error("--commit requires FinalAnalysisResult from PostgreSQL, not --final-result-json")
            final_result = _read_json(final_path)
        else:
            final_result = _find_final_result(
                session,
                asset=args.asset,
                trade_date=args.trade_date,
                run_id=args.run_id,
            )
            if final_result is None:
                parser.error("exact FinalAnalysisResult was not found")

        overview = _read_json(overview_path)
        strategy_card = _read_json(card_path) if card_path is not None else None
        candidate = build_bootstrap_candidate(
            final_result=final_result,
            gold_macro_overview=overview,
            strategy_card=strategy_card,
            state_scope=args.state_scope,
        )
        if args.commit:
            _validate_db_bound_overview(
                session,
                final_result=final_result,
                overview=overview,
            )
        logger.info(
            "resolved bootstrap candidate asset=%s state_scope=%s run_id=%s hash=%s",
            candidate.document.asset,
            args.state_scope,
            candidate.source_run_id,
            candidate.candidate_hash,
        )
        candidate_path = _output_path(
            args.output_json,
            storage_root=storage_root,
            default_relative=Path("outputs")
            / "analysis_state"
            / "bootstrap"
            / _safe_segment(args.asset)
            / _safe_segment(args.state_scope)
            / _safe_segment(args.trade_date)
            / _safe_segment(args.run_id)
            / "candidate.json",
        )

        if not args.commit:
            logger.info("dry-run complete; no database or artifact writes performed")
            print(
                json.dumps(
                    {
                        "status": "planned",
                        "dry_run": True,
                        "candidate_hash": candidate.candidate_hash,
                        "asset": candidate.document.asset,
                        "state_scope": args.state_scope,
                        "run_id": candidate.source_run_id,
                        "planned_candidate_path": _relative(candidate_path, storage_root),
                        "database_url": _display_database_url(database_url),
                        "writes": [],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0

        approval = _approval(args, candidate_hash=candidate.candidate_hash, parser=parser)
        try:
            result = materialize_bootstrap_candidate(session, candidate=candidate, approval=approval)
            recovery = build_recovery_artifact_scoped(
                session,
                asset=candidate.document.asset,
                state_scope=args.state_scope,
            )
            recovery_path = _output_path(
                args.recovery_output_json,
                storage_root=storage_root,
                default_relative=candidate_path.parent / "canonical_recovery.json",
            )
            candidate_written = write_json_artifact(
                payload=candidate,
                path=candidate_path,
                allowed_root=storage_root,
            )
            recovery_written = write_json_artifact(
                payload=recovery,
                path=recovery_path,
                allowed_root=storage_root,
            )
            session.commit()
            logger.info(
                "canonical head ready state_id=%s version=%s replayed=%s",
                result.canonical_state_id,
                result.canonical_version,
                result.replayed,
            )
        except Exception:
            session.rollback()
            raise

    print(
        json.dumps(
            {
                "status": "canonical_ready",
                "dry_run": False,
                **result.model_dump(mode="json"),
                "state_scope": args.state_scope,
                "candidate_path": _relative(candidate_path, storage_root),
                "candidate_written": candidate_written,
                "recovery_path": _relative(recovery_path, storage_root),
                "recovery_written": recovery_written,
                "database_url": _display_database_url(database_url),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministically bootstrap the first canonical AnalysisState."
    )
    parser.add_argument("--asset", required=True, help="Exact asset identifier, for example XAUUSD.")
    parser.add_argument(
        "--state-scope",
        choices=("intraday", "daily_close", "weekly_fundamental"),
        default="daily_close",
        help="Canonical state scope; legacy CLI calls default to daily_close.",
    )
    parser.add_argument("--trade-date", required=True, help="Exact FinalAnalysisResult date (YYYY-MM-DD).")
    parser.add_argument("--run-id", required=True, help="Exact TaskRun/FinalAnalysisResult run ID.")
    parser.add_argument(
        "--gold-overview-json",
        required=True,
        help="GoldMacroOverview JSON inside --storage-root.",
    )
    parser.add_argument(
        "--strategy-card-json",
        default="",
        help="Optional StrategyCard JSON inside --storage-root; defaults to the DB result payload.",
    )
    parser.add_argument(
        "--final-result-json",
        default="",
        help="Dry-run-only FinalAnalysisResult JSON inside --storage-root.",
    )
    parser.add_argument(
        "--storage-root",
        default=str(PROJECT_ROOT / "storage"),
        help="Allowed artifact root. All input/output paths must stay inside it.",
    )
    parser.add_argument("--output-json", default="", help="Optional candidate path inside --storage-root.")
    parser.add_argument(
        "--recovery-output-json",
        default="",
        help="Optional canonical recovery path inside --storage-root.",
    )
    parser.add_argument("--database-url", default="", help="Optional SQLAlchemy URL; defaults to DATABASE_URL.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only and perform no writes (default).")
    mode.add_argument("--commit", action="store_true", help="Append state, establish head, and write sealed artifacts.")
    parser.add_argument("--manual-reviewer", default="", help="Optional explicit human reviewer name.")
    parser.add_argument(
        "--manual-reviewed-at",
        default="",
        help="Timezone-aware ISO timestamp required with --manual-reviewer.",
    )
    parser.add_argument("--manual-review-note", default="", help="Optional manual approval note.")
    return parser


def _find_final_result(session, *, asset: str, trade_date: str, run_id: str):
    return session.scalar(
        select(FinalAnalysisResult).where(
            FinalAnalysisResult.asset == asset,
            FinalAnalysisResult.trade_date == datetime.strptime(trade_date, "%Y-%m-%d").date(),
            FinalAnalysisResult.run_id == run_id,
        )
    )


def _validate_db_bound_overview(
    session,
    *,
    final_result: FinalAnalysisResult | dict[str, Any],
    overview: dict[str, Any],
) -> None:
    snapshot_db_id = _result_field(final_result, "analysis_snapshot_db_id")
    if not snapshot_db_id:
        raise ValueError("--commit requires FinalAnalysisResult.analysis_snapshot_db_id")
    snapshot = session.get(AnalysisSnapshot, str(snapshot_db_id))
    if snapshot is None:
        raise ValueError("--commit analysis snapshot was not found")
    if snapshot.asset != _result_field(final_result, "asset"):
        raise ValueError("--commit analysis snapshot asset does not match FinalAnalysisResult")
    if snapshot.run_id != _result_field(final_result, "run_id"):
        raise ValueError("--commit analysis snapshot run_id does not match FinalAnalysisResult")
    payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
    news = payload.get("news") if isinstance(payload.get("news"), dict) else {}
    news_data = news.get("data") if isinstance(news.get("data"), dict) else news
    persisted = news_data.get("gold_macro_overview") if isinstance(news_data, dict) else None
    if not isinstance(persisted, dict):
        raise ValueError("--commit analysis snapshot has no GoldMacroOverview")
    if content_hash(persisted, exclude_keys=frozenset()) != content_hash(
        overview, exclude_keys=frozenset()
    ):
        raise ValueError("--commit GoldMacroOverview does not match the accepted analysis snapshot")


def _result_field(final_result: FinalAnalysisResult | dict[str, Any], field: str) -> Any:
    return final_result.get(field) if isinstance(final_result, dict) else getattr(final_result, field)


def _approval(args, *, candidate_hash: str, parser: argparse.ArgumentParser):
    reviewer = str(args.manual_reviewer).strip()
    reviewed_at = str(args.manual_reviewed_at).strip()
    if bool(reviewer) != bool(reviewed_at):
        parser.error("--manual-reviewer and --manual-reviewed-at must be supplied together")
    if not reviewer:
        return None
    return BootstrapApproval(
        candidate_hash=candidate_hash,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        note=args.manual_review_note,
    )


def _input_path(value: str, *, storage_root: Path) -> Path:
    if not str(value).strip():
        raise ValueError("required artifact path is blank")
    return validate_artifact_path(_join_root(value, storage_root), allowed_root=storage_root, must_exist=True)


def _optional_input_path(value: str, *, storage_root: Path) -> Path | None:
    return _input_path(value, storage_root=storage_root) if str(value).strip() else None


def _output_path(value: str, *, storage_root: Path, default_relative: Path) -> Path:
    raw = Path(value) if str(value).strip() else default_relative
    if not raw.is_absolute():
        raw = storage_root / raw
    return validate_artifact_path(raw, allowed_root=storage_root, must_exist=False)


def _join_root(value: str, storage_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else storage_root / path


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
    return value


def _session_factory(database_url: str):
    if database_url == DATABASE_URL:
        return SessionLocal
    return sessionmaker(bind=create_engine(database_url), expire_on_commit=False)


def _safe_segment(value: str) -> str:
    normalized = str(value).strip()
    if not normalized or normalized in {".", ".."} or not re_fullmatch(normalized):
        raise ValueError(f"unsafe path segment: {value!r}")
    return normalized


def re_fullmatch(value: str) -> bool:
    import re

    return re.fullmatch(r"[A-Za-z0-9._-]+", value) is not None


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _display_database_url(database_url: str) -> str:
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return "<invalid database url>"


if __name__ == "__main__":
    raise SystemExit(main())
