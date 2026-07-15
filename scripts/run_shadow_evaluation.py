"""Freeze live strategy output and write local shadow-evaluation artifacts."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_STORAGE_ROOT = _PROJECT_ROOT / "storage"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from apps.analysis.evaluation.runner import run_shadow_evaluation as _run_shadow_evaluation  # noqa: E402


def run_shadow_evaluation(
    *,
    trade_date: str,
    as_of: datetime,
    storage_root: Path,
    write: bool = False,
    database_url: str | None = None,
    live_output: Mapping[str, Any] | None = None,
    market_candles: Mapping[str, Any] | None = None,
    evaluated_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Load runtime inputs and delegate one evaluation to the reusable runner.

    ``as_of`` freezes the strategy snapshot. ``evaluated_at`` (or the
    compatibility alias ``now``) controls outcome maturity and defaults to the
    current UTC time. Naive timestamps are rejected rather than guessed.
    """

    normalized_as_of = _normalize_timestamp(as_of, argument="as_of")
    if evaluated_at is not None and now is not None:
        raise ValueError("provide only one of evaluated_at or now")
    normalized_evaluated_at = _normalize_timestamp(
        evaluated_at if evaluated_at is not None else now or datetime.now(timezone.utc),
        argument="evaluated_at",
    )

    if database_url:
        os.environ["DATABASE_URL"] = database_url
    if live_output is None or market_candles is None:
        live_output, market_candles, session = _load_runtime_inputs(as_of=normalized_as_of)
    else:
        session = None
    try:
        return _run_shadow_evaluation(
            trade_date=trade_date,
            as_of=normalized_as_of,
            evaluated_at=normalized_evaluated_at,
            storage_root=storage_root,
            live_output=live_output,
            market_candles=market_candles,
            write=write,
        )
    finally:
        if session is not None:
            session.close()


def _load_runtime_inputs(*, as_of: datetime) -> tuple[dict[str, Any], dict[str, Any], Any]:
    from apps.api.services.live_strategy_service import get_live_strategy_latest
    from apps.api.services.market_candle_service import get_market_candles
    from database.models.engine import SessionLocal

    session = SessionLocal()
    try:
        live = get_live_strategy_latest(asset="XAUUSD", db=session, now=as_of)
        candles = get_market_candles(asset="XAUUSD", timeframe="5m", limit=500, session=session)
    except Exception:
        session.close()
        raise
    return live, candles, session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", dest="trade_date", required=True, help="Trade date in YYYY-MM-DD format")
    parser.add_argument("--as-of", default=None, help="Timezone-aware ISO-8601 snapshot timestamp")
    parser.add_argument(
        "--evaluated-at",
        default=None,
        help="Timezone-aware ISO-8601 maturity timestamp (default: current UTC)",
    )
    parser.add_argument("--storage-root", default=str(_DEFAULT_STORAGE_ROOT), help="Repo storage root")
    parser.add_argument("--database-url", default=None, help="Optional DATABASE_URL override")
    parser.add_argument("--write", action="store_true", help="Persist artifacts; default is dry-run")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    trade_date = _validate_date(args.trade_date)
    as_of = _parse_timestamp_arg(args.as_of, argument="--as-of")
    evaluated_at = _parse_timestamp_arg(
        args.evaluated_at,
        argument="--evaluated-at",
        default_now=True,
    )
    storage_root = _validate_storage_root(Path(args.storage_root))
    summary = run_shadow_evaluation(
        trade_date=trade_date,
        as_of=as_of,
        storage_root=storage_root,
        write=args.write,
        database_url=args.database_url,
        evaluated_at=evaluated_at,
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


def _parse_timestamp_arg(
    value: str | None,
    *,
    argument: str,
    default_now: bool = True,
) -> datetime:
    if value is None or not value.strip():
        if default_now:
            return datetime.now(timezone.utc)
        raise SystemExit(f"{argument} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"{argument} must be ISO-8601") from exc
    try:
        return _normalize_timestamp(parsed, argument=argument)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _parse_as_of(value: str | None) -> datetime:
    """Backward-compatible parser name retained for current callers."""

    return _parse_timestamp_arg(value, argument="--as-of")


def _normalize_timestamp(value: datetime, *, argument: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{argument} must include a timezone")
    return value.astimezone(timezone.utc)


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
