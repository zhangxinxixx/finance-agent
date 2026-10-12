"""Readonly verified D1 inputs for the Gold key-level market producer."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from apps.analysis.gold_policy.daily_close_store import DailyCloseCanonicalHead
from apps.analysis.gold_policy.key_level_controls import KeyLevelControlsInput
from apps.analysis.gold_policy.key_level_market_producer import (
    produce_gold_key_level_lifecycle_events,
)
from apps.analysis.gold_policy.key_level_schemas import KeyLevelReadModel
from database.models.analysis import MarketCandle
from database.queries.market import list_completed_market_candles


_DAY = timedelta(days=1)
_QUERY_LIMIT = 2
_RAW_DIGEST_FIELDS = frozenset(
    {
        "archive_sha256",
        "content_hash",
        "file_sha256",
        "raw_content_sha256",
        "raw_sha256",
        "sha256",
    }
)
_ARCHIVE_WRAPPER_FIELDS = frozenset(
    {
        "alignment_status",
        "asset",
        "bar_close_time",
        "close_time",
        "code",
        "freshness_status",
        "instrument_type",
        "interval",
        "provider",
        "provider_symbol",
        "provider_timeframe",
        "quality_status",
        "source",
        "source_ref",
        "symbol",
        "ticker",
        "timeframe",
    }
)


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FormalKeyLevelMarketSummary(_FrozenContract):
    """Small JSON-safe description of the readonly producer input decision."""

    schema_version: Literal["formal_key_level_market_summary.v1"] = "formal_key_level_market_summary.v1"
    status: Literal["not_applicable", "ready", "missing"]
    previous_key_level_count: int
    queried_row_count: int = 0
    verified_row_count: int = 0
    produced_event_count: int = 0
    reason_codes: tuple[str, ...]


class GoldKeyLevelMarketInputs(_FrozenContract):
    """Immutable control input and operator-visible summary for one CLI run."""

    schema_version: Literal["gold_key_level_market_inputs.v1"] = "gold_key_level_market_inputs.v1"
    controls_input: KeyLevelControlsInput | None = None
    summary: FormalKeyLevelMarketSummary


def load_gold_key_level_market_inputs(
    *,
    head: DailyCloseCanonicalHead | None,
    db: Session | None,
    storage_root: Path,
    decision_as_of: datetime,
) -> GoldKeyLevelMarketInputs:
    """Load archived D1 rows for exactly the verified predecessor key levels.

    This seam never discovers levels, fetches data, mutates ORM objects, or
    writes files.  SQLite may strip timezone information from a persisted
    ``MarketCandle.open_time``; that known database artifact alone is restored
    to UTC.  Source metadata timestamps remain strict and must be explicitly
    timezone-aware.
    """

    cutoff = _aware_utc(decision_as_of)
    states = _head_key_levels(head)
    if not states:
        return GoldKeyLevelMarketInputs(
            summary=FormalKeyLevelMarketSummary(
                status="not_applicable",
                previous_key_level_count=0,
                reason_codes=("NO_PREVIOUS_KEY_LEVEL_STATES",),
            )
        )

    unavailable = _unavailable_reason(db)
    if unavailable is not None:
        return _missing(states=states, cutoff=cutoff, reason=unavailable)

    assert db is not None
    try:
        with db.no_autoflush:
            rows = tuple(
                list_completed_market_candles(
                    db,
                    asset="XAUUSD",
                    timeframe="1d",
                    as_of=cutoff,
                    bar_duration=_DAY,
                    limit=_QUERY_LIMIT,
                )
            )
    except Exception:
        return _missing(states=states, cutoff=cutoff, reason="D1_MARKET_DATABASE_QUERY_FAILED")

    if not rows:
        return _missing(states=states, cutoff=cutoff, reason="D1_MARKET_CANDIDATES_MISSING")

    candidates: list[dict[str, Any]] = []
    rejection_codes: list[str] = []
    root = storage_root.expanduser().resolve()
    for row in rows:
        candidate, reason = _verified_candidate(row, storage_root=root)
        if candidate is None:
            rejection_codes.append(reason)
        else:
            candidates.append(candidate)
    if rejection_codes:
        return _missing(
            states=states,
            cutoff=cutoff,
            reason_codes=tuple(sorted(set(rejection_codes))),
            queried_row_count=len(rows),
        )

    try:
        production = produce_gold_key_level_lifecycle_events(
            previous_states=states,
            candidates=tuple(candidates),
            decision_as_of=cutoff,
        )
    except Exception:
        return _missing(
            states=states,
            cutoff=cutoff,
            reason="D1_MARKET_PRODUCTION_FAILED",
            queried_row_count=len(rows),
        )
    event_count = len(production.controls_input.ordered_events)
    return GoldKeyLevelMarketInputs(
        controls_input=production.controls_input,
        summary=FormalKeyLevelMarketSummary(
            status="ready" if event_count else "missing",
            previous_key_level_count=len(states),
            queried_row_count=len(rows),
            verified_row_count=len(candidates),
            produced_event_count=event_count,
            reason_codes=production.reason_codes,
        ),
    )


def _head_key_levels(head: DailyCloseCanonicalHead | None) -> tuple[KeyLevelReadModel, ...]:
    if head is None:
        return ()
    # The canonical store has already verified this typed artifact.  Do not
    # substitute report prose, snapshots, or another head field.
    return tuple(head.strategy_policy_input.key_levels)


def _unavailable_reason(db: Session | None) -> str | None:
    if db is None or not isinstance(db, Session):
        return "D1_MARKET_DATABASE_UNAVAILABLE"
    try:
        pending = (*db.new, *db.dirty, *db.deleted)
    except Exception:
        return "D1_MARKET_DATABASE_UNAVAILABLE"
    if any(isinstance(item, MarketCandle) for item in pending):
        return "D1_MARKET_UNCOMMITTED_DATA"
    return None


def _missing(
    *,
    states: tuple[KeyLevelReadModel, ...],
    cutoff: datetime,
    reason: str | None = None,
    reason_codes: tuple[str, ...] = (),
    queried_row_count: int = 0,
) -> GoldKeyLevelMarketInputs:
    controls = KeyLevelControlsInput(
        decision_as_of=cutoff,
        scope="daily_close",
        previous_states=states,
    )
    reasons = reason_codes or ((reason,) if reason is not None else ())
    return GoldKeyLevelMarketInputs(
        controls_input=controls,
        summary=FormalKeyLevelMarketSummary(
            status="missing",
            previous_key_level_count=len(states),
            queried_row_count=queried_row_count,
            reason_codes=tuple(sorted(set(reasons))),
        ),
    )


def _verified_candidate(
    row: MarketCandle,
    *,
    storage_root: Path,
) -> tuple[dict[str, Any] | None, str]:
    source_ref_value = row.source_ref
    if not isinstance(source_ref_value, Mapping):
        return None, "D1_MARKET_SOURCE_REF_MISSING"
    try:
        source_ref = json.loads(json.dumps(dict(source_ref_value), allow_nan=False))
    except (TypeError, ValueError):
        return None, "D1_MARKET_SOURCE_REF_INVALID"
    if not isinstance(source_ref, dict):
        return None, "D1_MARKET_SOURCE_REF_INVALID"

    try:
        open_time = _database_utc(row.open_time)
    except (TypeError, ValueError):
        return None, "D1_MARKET_WINDOW_TIME_INVALID"
    declared_close = source_ref.get("close_time", source_ref.get("bar_close_time"))
    if declared_close is None:
        close_time = open_time + _DAY
    else:
        close_time = _strict_time(declared_close)
        if close_time is None:
            return None, "D1_MARKET_WINDOW_TIME_INVALID"
    if close_time != open_time + _DAY:
        return None, "D1_MARKET_BAR_DURATION_INVALID"

    retrieved_at = _strict_time(source_ref.get("retrieved_at"))
    if retrieved_at is None:
        return None, "D1_MARKET_RETRIEVAL_TIME_MISSING"

    row_raw = str(row.raw_path or "").strip()
    ref_raw = str(source_ref.get("raw_path") or "").strip()
    if row_raw and ref_raw and row_raw != ref_raw:
        return None, "D1_MARKET_RAW_PATH_CONFLICT"
    raw_path = row_raw or ref_raw
    archive_path, path_reason = _raw_archive_path(storage_root, raw_path)
    if archive_path is None:
        return None, path_reason
    try:
        raw_bytes = archive_path.read_bytes()
    except OSError:
        return None, "D1_MARKET_RAW_ARCHIVE_UNREADABLE"
    digest = hashlib.sha256(raw_bytes).hexdigest()
    declarations, declaration_reason = _declared_raw_digests(source_ref)
    if declaration_reason is not None:
        return None, declaration_reason
    if declarations and any(item != digest for item in declarations):
        return None, "D1_MARKET_RAW_ARCHIVE_HASH_MISMATCH"
    try:
        archive = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "D1_MARKET_RAW_ARCHIVE_JSON_INVALID"

    candidate = {
        "asset": str(row.asset),
        "timeframe": str(row.timeframe),
        "open_time": open_time.isoformat(),
        "close_time": close_time.isoformat(),
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "source": str(row.source),
        "raw_path": raw_path,
        "source_ref": {
            **source_ref,
            "raw_path": raw_path,
            # This value is derived from bytes just read and is deliberately
            # independent from any normalized row/snapshot hash.
            "sha256": digest,
            "retrieved_at": retrieved_at.isoformat(),
        },
    }
    archive_records = _archive_records(archive)
    if not archive_records:
        return None, "D1_MARKET_RAW_ARCHIVE_SHAPE_UNSUPPORTED"
    if not any(
        _record_matches_candidate(record, context=context, candidate=candidate) for record, context in archive_records
    ):
        return None, "D1_MARKET_RAW_ARCHIVE_ROW_MISMATCH"
    return candidate, "D1_MARKET_ROW_VERIFIED"


def _raw_archive_path(storage_root: Path, raw_path: str) -> tuple[Path | None, str]:
    if not raw_path:
        return None, "D1_MARKET_RAW_ARCHIVE_MISSING"
    supplied = Path(raw_path).expanduser()
    if ".." in supplied.parts:
        return None, "D1_MARKET_RAW_ARCHIVE_OUTSIDE_STORAGE"
    raw_root = storage_root / "raw"
    candidate = supplied if supplied.is_absolute() else storage_root / supplied
    # abspath removes harmless '.' components without following symlinks.
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(raw_root)
    except ValueError:
        return None, "D1_MARKET_RAW_ARCHIVE_OUTSIDE_STORAGE"
    current = raw_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return None, "D1_MARKET_RAW_ARCHIVE_SYMLINK"
    if raw_root.is_symlink():
        return None, "D1_MARKET_RAW_ARCHIVE_SYMLINK"
    if not candidate.is_file():
        return None, "D1_MARKET_RAW_ARCHIVE_MISSING"
    try:
        if not candidate.resolve(strict=True).is_relative_to(raw_root.resolve(strict=True)):
            return None, "D1_MARKET_RAW_ARCHIVE_OUTSIDE_STORAGE"
    except (OSError, RuntimeError):
        return None, "D1_MARKET_RAW_ARCHIVE_UNREADABLE"
    return candidate, "D1_MARKET_RAW_ARCHIVE_VERIFIED"


def _declared_raw_digests(source_ref: Mapping[str, Any]) -> tuple[tuple[str, ...], str | None]:
    declared: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if str(key).lower() in _RAW_DIGEST_FIELDS and nested is not None:
                    declared.append(str(nested).strip().lower())
                elif isinstance(nested, (Mapping, list, tuple)):
                    visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)

    visit(source_ref)
    if any(len(item) != 64 or any(character not in "0123456789abcdef" for character in item) for item in declared):
        return (), "D1_MARKET_RAW_HASH_DECLARATION_INVALID"
    return tuple(declared), None


def _archive_records(archive: object) -> tuple[tuple[Mapping[str, Any], Mapping[str, Any]], ...]:
    found: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []

    def walk(value: object, context: Mapping[str, Any]) -> None:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    found.append((item, context))
            return
        if not isinstance(value, Mapping):
            return
        if _looks_like_bar(value):
            found.append((value, context))
        wrapper = {key: value[key] for key in _ARCHIVE_WRAPPER_FIELDS if key in value}
        wrappers = _archive_wrappers(context)
        nested_context = {"_archive_wrappers": (*wrappers, wrapper)} if wrapper else context
        for key in ("bars", "candles", "rows", "values", "latest", "klines", "list"):
            nested = value.get(key)
            if isinstance(nested, list):
                walk(nested, nested_context)
        for key in ("bar", "candle", "row", "data", "payload", "response", "result"):
            nested = value.get(key)
            if isinstance(nested, (Mapping, list)):
                walk(nested, nested_context)
        chart = value.get("chart")
        if isinstance(chart, Mapping):
            _append_yahoo_records(chart, context=nested_context, found=found)

    walk(archive, {})
    return tuple(found)


def _append_yahoo_records(
    chart: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    found: list[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> None:
    results = chart.get("result")
    if not isinstance(results, list):
        return
    for result in results:
        if not isinstance(result, Mapping):
            continue
        timestamps = result.get("timestamp")
        quotes = (
            (result.get("indicators") or {}).get("quote") if isinstance(result.get("indicators"), Mapping) else None
        )
        quote = quotes[0] if isinstance(quotes, list) and quotes and isinstance(quotes[0], Mapping) else None
        if not isinstance(timestamps, list) or quote is None:
            continue
        result_metadata = result.get("meta")
        wrappers = _archive_wrappers(context)
        if isinstance(result_metadata, Mapping):
            wrapper = {key: result_metadata[key] for key in _ARCHIVE_WRAPPER_FIELDS if key in result_metadata}
            result_context = {"_archive_wrappers": (*wrappers, wrapper)} if wrapper else context
        else:
            result_context = context
        for index, timestamp in enumerate(timestamps):
            try:
                record = {
                    "timestamp": timestamp,
                    "open": quote["open"][index],
                    "high": quote["high"][index],
                    "low": quote["low"][index],
                    "close": quote["close"][index],
                }
            except (KeyError, IndexError, TypeError):
                continue
            found.append((record, result_context))


def _looks_like_bar(value: Mapping[str, Any]) -> bool:
    return all(
        key in value or short in value for key, short in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))
    )


def _record_matches_candidate(
    record: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> bool:
    declarations = _archive_declaration_scopes(record, context)
    open_value = record.get("open", record.get("o"))
    high_value = record.get("high", record.get("h"))
    low_value = record.get("low", record.get("l"))
    close_value = record.get("close", record.get("c"))
    if not all(
        _same_number(actual, candidate[name])
        for name, actual in (
            ("open", open_value),
            ("high", high_value),
            ("low", low_value),
            ("close", close_value),
        )
    ):
        return False
    raw_open = next(
        (
            value
            for value in (
                record.get("open_time"),
                record.get("datetime"),
                record.get("date"),
                record.get("time"),
                record.get("timestamp"),
                record.get("t"),
            )
            if value is not None
        ),
        None,
    )
    if _archive_time(raw_open) != _strict_time(candidate["open_time"]):
        return False
    raw_closes = _declared_values(declarations, "close_time", "bar_close_time")
    if raw_closes and not all(_archive_time(value) == _strict_time(candidate["close_time"]) for value in raw_closes):
        return False
    identity_values = _declared_values(
        declarations,
        "asset",
        "symbol",
        "code",
        "provider_symbol",
        "ticker",
    )
    if not identity_values or not all(_is_xauusd_identity(value) for value in identity_values):
        return False
    instrument_types = _declared_values(declarations, "instrument_type")
    if instrument_types and not all(_is_xauusd_spot_instrument(value) for value in instrument_types):
        return False
    timeframe_values = _declared_values(
        declarations,
        "timeframe",
        "interval",
        "provider_timeframe",
    )
    if not timeframe_values and not raw_closes:
        return False
    if not all(str(value).strip().lower() in {"1d", "1day", "day", "daily"} for value in timeframe_values):
        return False
    required_statuses = {
        "quality_status": "accepted",
        "freshness_status": "fresh",
        "alignment_status": "aligned",
    }
    if any(
        any(str(value).strip().lower() != expected for value in _declared_values(declarations, field))
        for field, expected in required_statuses.items()
    ):
        return False
    source_values = tuple(
        str(value).strip().lower()
        for value in _declared_values(declarations, "source", "provider")
        if value is not None and str(value).strip()
    )
    expected_source = str(candidate["source"]).strip().lower()
    if source_values and not all(
        value == expected_source or expected_source.startswith(value) or value.startswith(expected_source)
        for value in source_values
    ):
        return False
    return True


def _archive_wrappers(context: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    wrappers = context.get("_archive_wrappers")
    if not isinstance(wrappers, (list, tuple)):
        return ()
    return tuple(item for item in wrappers if isinstance(item, Mapping))


def _archive_declaration_scopes(
    record: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    scopes: list[Mapping[str, Any]] = []

    def append_with_source_refs(value: Mapping[str, Any]) -> None:
        scopes.append(value)
        nested = value.get("source_ref")
        if isinstance(nested, Mapping):
            append_with_source_refs(nested)

    append_with_source_refs(record)
    for wrapper in _archive_wrappers(context):
        append_with_source_refs(wrapper)
    return tuple(scopes)


def _declared_values(scopes: tuple[Mapping[str, Any], ...], *fields: str) -> tuple[object, ...]:
    return tuple(scope[field] for scope in scopes for field in fields if scope.get(field) is not None)


def _database_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("database candle time must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _strict_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _archive_time(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip().isdigit():
        try:
            return datetime.fromtimestamp(float(value.strip()), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    # Provider date-only daily rows have a defined UTC day boundary; arbitrary
    # naive date-times do not.
    if isinstance(value, str) and len(value.strip()) == 10:
        try:
            return datetime.fromisoformat(value.strip()).replace(tzinfo=UTC)
        except ValueError:
            return None
    return _strict_time(value)


def _same_number(left: object, right: object) -> bool:
    try:
        left_decimal = Decimal(str(left))
        right_decimal = Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return left_decimal.is_finite() and right_decimal.is_finite() and left_decimal == right_decimal


def _is_xauusd_identity(value: object) -> bool:
    normalized = str(value).strip().upper().split(":")[-1].replace("/", "").replace("-", "")
    return normalized == "XAUUSD"


def _is_xauusd_spot_instrument(value: object) -> bool:
    return str(value).strip().lower() in {
        "composite_otc_spot_proxy",
        "otc_spot_quote_proxy",
        "spot",
    }


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision_as_of must be timezone-aware")
    return value.astimezone(UTC)
