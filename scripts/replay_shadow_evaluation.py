"""Replay one legacy shadow outcome into a new immutable revision."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_STORAGE_ROOT = _PROJECT_ROOT / "storage"
_DEFAULT_DATABASE_URL = "postgresql://finance_agent:finance_agent@127.0.0.1:55432/finance_agent"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from apps.analysis.evaluation.replay import run_shadow_replay  # noqa: E402
from apps.analysis.evaluation.store import EvaluationStore  # noqa: E402
from database.models.analysis import MarketCandle  # noqa: E402


def replay_shadow_evaluation(
    *,
    trade_date: str,
    evaluation_id: str,
    horizon: str,
    storage_root: Path,
    write: bool = False,
    database_url: str | None = None,
    snapshot_payload: Mapping[str, Any] | None = None,
    market_rows: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Load one legacy snapshot and its historical 5m rows, then replay it."""

    store = EvaluationStore(storage_root)
    context = {
        "account_id": "codex-xauusd-shadow",
        "asset": "XAUUSD",
        "trade_date": trade_date,
        "evaluation_id": evaluation_id,
    }
    payload = dict(snapshot_payload) if snapshot_payload is not None else store.read_snapshot(context)
    if payload.get("evaluation_id") != evaluation_id or payload.get("trade_date") != trade_date:
        raise ValueError("snapshot context does not match requested evaluation")
    if market_rows is None:
        market_rows = _load_market_rows(
            database_url=database_url or os.getenv("DATABASE_URL") or _DEFAULT_DATABASE_URL,
            as_of=_parse_timestamp(payload.get("as_of")),
            horizon=horizon,
        )
    return run_shadow_replay(
        snapshot_payload=payload,
        market_rows=market_rows,
        horizon=horizon,
        storage_root=storage_root,
        write=write,
    )


def _load_market_rows(*, database_url: str, as_of: datetime, horizon: str) -> list[MarketCandle]:
    horizon_end = _horizon_end(as_of, horizon)
    engine = create_engine(database_url, echo=False)
    try:
        with Session(engine) as session:
            return list(
                session.scalars(
                    select(MarketCandle)
                    .where(
                        MarketCandle.asset == "XAUUSD",
                        MarketCandle.timeframe == "5m",
                        MarketCandle.open_time > as_of - timedelta(minutes=5),
                        MarketCandle.open_time < horizon_end,
                    )
                    .order_by(MarketCandle.open_time.asc(), MarketCandle.id.asc())
                ).all()
            )
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", dest="trade_date", required=True, help="Trade date in YYYY-MM-DD format")
    parser.add_argument("--evaluation-id", required=True, help="Legacy evaluation id to supersede")
    parser.add_argument("--horizon", required=True, choices=("1h", "4h", "session", "24h"))
    parser.add_argument("--storage-root", default=str(_DEFAULT_STORAGE_ROOT), help="Repo storage root")
    parser.add_argument("--database-url", default=None, help="Optional DATABASE_URL override")
    parser.add_argument("--write", action="store_true", help="Persist the replay revision; default is dry-run")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    trade_date = _validate_date(args.trade_date)
    evaluation_id = _validate_id(args.evaluation_id)
    storage_root = _validate_storage_root(Path(args.storage_root))
    summary = replay_shadow_evaluation(
        trade_date=trade_date,
        evaluation_id=evaluation_id,
        horizon=args.horizon,
        storage_root=storage_root,
        write=args.write,
        database_url=args.database_url,
    )
    print(summary)
    return 0


def _validate_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit("--date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise SystemExit("--date must be YYYY-MM-DD")
    return value


def _validate_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise SystemExit("--evaluation-id must be one safe path component")
    return value


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("snapshot as_of is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("snapshot as_of must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("snapshot as_of must include a timezone")
    return parsed.astimezone(UTC)


def _horizon_end(as_of: datetime, horizon: str) -> datetime:
    if horizon == "session":
        return datetime.combine(as_of.date(), datetime.max.time(), tzinfo=UTC)
    try:
        hours = {"1h": 1, "4h": 4, "24h": 24}[horizon]
    except KeyError as exc:
        raise ValueError(f"unsupported horizon: {horizon}") from exc
    return as_of + timedelta(hours=hours)


def _validate_storage_root(value: Path) -> Path:
    error = "--storage-root must be a safe directory inside project storage"
    allowed = _DEFAULT_STORAGE_ROOT.absolute()
    if allowed.is_symlink():
        raise SystemExit(error)
    raw = value.expanduser()
    candidate = Path(raw if raw.is_absolute() else _PROJECT_ROOT / raw)
    candidate = Path(os.path.abspath(candidate))
    try:
        relative_parts = candidate.relative_to(allowed).parts
    except ValueError as exc:
        raise SystemExit(error) from exc
    current = allowed
    for part in relative_parts:
        current /= part
        if current.is_symlink():
            raise SystemExit(error)
    if candidate.exists() and not candidate.is_dir():
        raise SystemExit(error)
    return candidate


if __name__ == "__main__":
    raise SystemExit(main())
