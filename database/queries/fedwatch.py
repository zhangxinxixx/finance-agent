"""Validated persistence and read APIs for normalized FedWatch snapshots."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid
from collections import OrderedDict
from datetime import UTC, date, datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from database.models.fedwatch import (
    FedWatchFactor,
    FedWatchFutures,
    FedWatchMeetingSnapshot,
    FedWatchProbability,
    FedWatchRawSnapshot,
)


FEDWATCH_SOURCE = "cme_fedwatch_free"
PARSE_STATUSES = frozenset({"ok", "parse_failed", "missing"})
COMPARISON_WINDOWS = frozenset({"current", "1d", "1w", "1m"})
MAX_HISTORY_LIMIT = 1000
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_OFFICIAL_SOURCE_HOSTS = ("cmegroup.com", "quikstrike.net")
_SNAPSHOT_KEYS = frozenset(
    {
        "source",
        "snapshot_id",
        "collected_at",
        "as_of",
        "source_url",
        "collector_version",
        "http_status",
        "content_hash",
        "raw_artifact_ref",
        "parse_status",
        "reason",
        "source_refs",
        "rows",
        "futures",
    }
)


def save_fedwatch_snapshot(
    session: Session,
    snapshot: dict[str, Any],
    *,
    factor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and stage one immutable snapshot without committing the session.

    Re-saving the exact same ``snapshot_id`` and payload is idempotent. A changed
    payload under an existing id is rejected before any ORM state is added.
    """

    normalized, meetings = _validate_snapshot(snapshot)
    snapshot_hash = _payload_hash(normalized)
    normalized_factor = _validate_factor(factor, normalized) if factor is not None else None
    factor_hash = _payload_hash(normalized_factor) if normalized_factor is not None else None

    existing = session.get(FedWatchRawSnapshot, normalized["snapshot_id"])
    if existing is not None:
        if existing.payload_hash != snapshot_hash:
            raise ValueError("snapshot_id already exists with conflicting payload")
        _stage_factor_if_needed(
            session,
            existing,
            normalized_factor=normalized_factor,
            factor_hash=factor_hash,
        )
        return copy.deepcopy(normalized)

    raw = FedWatchRawSnapshot(
        snapshot_id=normalized["snapshot_id"],
        source=normalized["source"],
        collected_at=_parse_datetime(normalized["collected_at"], "collected_at"),
        as_of=_parse_optional_datetime(normalized["as_of"], "as_of"),
        source_url=normalized["source_url"],
        collector_version=normalized["collector_version"],
        http_status=normalized["http_status"],
        content_hash=normalized["content_hash"],
        raw_artifact_ref=normalized["raw_artifact_ref"],
        parse_status=normalized["parse_status"],
        reason=normalized["reason"],
        source_refs=copy.deepcopy(normalized["source_refs"]),
        snapshot_metadata={
            key: copy.deepcopy(value)
            for key, value in normalized.items()
            if key not in _SNAPSHOT_KEYS
        },
        payload_hash=snapshot_hash,
    )

    for meeting_index, meeting in enumerate(meetings):
        meeting_model = FedWatchMeetingSnapshot(
            row_index=meeting_index,
            meeting_date=meeting["meeting_date"],
            contract_ref=meeting["contract_ref"],
            comparison_window=meeting["comparison_window"],
            as_of=meeting["as_of"],
        )
        for row_index, row in enumerate(meeting["rows"]):
            meeting_model.probabilities.append(
                FedWatchProbability(
                    row_index=row_index,
                    target_low=row["target_low"],
                    target_high=row["target_high"],
                    probability=row["probability"],
                )
            )
        raw.meetings.append(meeting_model)

    for row_index, future in enumerate(normalized["futures"]):
        future_as_of = _parse_optional_datetime(future.get("as_of"), f"futures[{row_index}].as_of")
        raw.futures.append(
            FedWatchFutures(
                row_index=row_index,
                contract_ref=_optional_string(future.get("contract_ref"), f"futures[{row_index}].contract_ref"),
                as_of=future_as_of,
                payload=copy.deepcopy(future),
            )
        )

    if normalized_factor is not None:
        raw.factor = _factor_model(normalized_factor, factor_hash)

    # Validation and conflict checks happen before ORM state is added. A flush
    # failure invalidates the whole caller transaction, so parent/children can
    # only be committed together; the final commit remains caller-controlled.
    session.add(raw)
    session.flush()
    return copy.deepcopy(normalized)


def get_latest_fedwatch_snapshot(
    session: Session,
    *,
    as_of: datetime | str | None = None,
    valid_only: bool = True,
) -> dict[str, Any] | None:
    """Return the latest snapshot without allowing retrieval-time lookahead.

    Valid snapshots are ordered by source observation time. With
    ``valid_only=False``, collection-event order is used so a latest failed
    collection remains independently observable.
    """

    cutoff = _parse_optional_datetime(as_of, "as_of")
    statement = _snapshot_select()
    if valid_only:
        statement = statement.where(
            FedWatchRawSnapshot.parse_status == "ok",
            FedWatchRawSnapshot.as_of.is_not(None),
        )
    if cutoff is not None:
        statement = statement.where(FedWatchRawSnapshot.collected_at <= cutoff)
        if valid_only:
            statement = statement.where(FedWatchRawSnapshot.as_of <= cutoff)
        else:
            statement = statement.where(
                or_(FedWatchRawSnapshot.as_of.is_(None), FedWatchRawSnapshot.as_of <= cutoff)
            )

    if valid_only:
        statement = statement.order_by(
            FedWatchRawSnapshot.as_of.desc(),
            FedWatchRawSnapshot.collected_at.desc(),
            FedWatchRawSnapshot.snapshot_id.desc(),
        )
    else:
        statement = statement.order_by(
            FedWatchRawSnapshot.collected_at.desc(),
            FedWatchRawSnapshot.as_of.desc(),
            FedWatchRawSnapshot.snapshot_id.desc(),
        )
    model = session.scalars(statement.limit(1)).first()
    return _snapshot_to_dict(model) if model is not None else None


def get_fedwatch_history(
    session: Session,
    *,
    meeting_date: date | str | None = None,
    limit: int = 100,
    as_of: datetime | str | None = None,
) -> list[dict[str, Any]]:
    """Return bounded snapshot history, optionally requiring one meeting date."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_HISTORY_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_HISTORY_LIMIT}")
    cutoff = _parse_optional_datetime(as_of, "as_of")
    requested_meeting = _parse_optional_date(meeting_date, "meeting_date")

    statement = _snapshot_select()
    if requested_meeting is not None:
        statement = statement.where(
            FedWatchRawSnapshot.meetings.any(
                FedWatchMeetingSnapshot.meeting_date == requested_meeting
            )
        )
    if cutoff is not None:
        statement = statement.where(
            FedWatchRawSnapshot.collected_at <= cutoff,
            or_(FedWatchRawSnapshot.as_of.is_(None), FedWatchRawSnapshot.as_of <= cutoff),
        )
    statement = statement.order_by(
        FedWatchRawSnapshot.collected_at.desc(),
        FedWatchRawSnapshot.as_of.desc(),
        FedWatchRawSnapshot.snapshot_id.desc(),
    ).limit(limit)
    return [_snapshot_to_dict(model) for model in session.scalars(statement).all()]


def get_latest_fedwatch_factor(
    session: Session,
    *,
    as_of: datetime | str | None = None,
) -> dict[str, Any] | None:
    """Return the latest factor whose observation, collection, and evaluation are in cutoff."""

    cutoff = _parse_optional_datetime(as_of, "as_of")
    statement = select(FedWatchFactor).join(FedWatchFactor.snapshot)
    if cutoff is not None:
        statement = statement.where(
            FedWatchFactor.as_of <= cutoff,
            FedWatchRawSnapshot.collected_at <= cutoff,
            or_(FedWatchRawSnapshot.as_of.is_(None), FedWatchRawSnapshot.as_of <= cutoff),
        )
    statement = statement.order_by(
        FedWatchFactor.as_of.desc(),
        FedWatchRawSnapshot.as_of.desc(),
        FedWatchRawSnapshot.collected_at.desc(),
        FedWatchFactor.id.desc(),
    ).limit(1)
    model = session.scalars(statement).first()
    return copy.deepcopy(model.payload) if model is not None else None


def _snapshot_select():
    return select(FedWatchRawSnapshot).options(
        selectinload(FedWatchRawSnapshot.meetings).selectinload(
            FedWatchMeetingSnapshot.probabilities
        ),
        selectinload(FedWatchRawSnapshot.futures),
    )


def _validate_snapshot(snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a dictionary")
    missing = sorted(_SNAPSHOT_KEYS - snapshot.keys())
    if missing:
        raise ValueError(f"snapshot missing required fields: {', '.join(missing)}")
    if any(not isinstance(key, str) for key in snapshot):
        raise ValueError("snapshot keys must be strings")

    source = _required_string(snapshot["source"], "source")
    if source != FEDWATCH_SOURCE:
        raise ValueError(f"source must be {FEDWATCH_SOURCE!r}")
    snapshot_id = _uuid_string(snapshot["snapshot_id"], "snapshot_id")
    collected_at = _parse_datetime(snapshot["collected_at"], "collected_at")
    source_as_of = _parse_optional_datetime(snapshot["as_of"], "as_of")
    if source_as_of is not None and source_as_of > collected_at:
        raise ValueError("as_of cannot be later than collected_at")

    source_url = _required_string(snapshot["source_url"], "source_url")
    parsed_url = urlparse(source_url)
    if parsed_url.scheme.lower() != "https" or not parsed_url.netloc:
        raise ValueError("source_url must be an absolute https URL")
    source_host = (parsed_url.hostname or "").lower()
    if not any(
        source_host == official or source_host.endswith(f".{official}")
        for official in _OFFICIAL_SOURCE_HOSTS
    ):
        raise ValueError("source_url must use an official CME or QuikStrike host")
    collector_version = _required_string(snapshot["collector_version"], "collector_version")

    http_status = snapshot["http_status"]
    if http_status is not None and (
        isinstance(http_status, bool) or not isinstance(http_status, int) or not 100 <= http_status <= 599
    ):
        raise ValueError("http_status must be null or an integer from 100 to 599")
    content_hash = snapshot["content_hash"]
    if content_hash is not None:
        content_hash = _required_string(content_hash, "content_hash").lower()
        if _SHA256_RE.fullmatch(content_hash) is None:
            raise ValueError("content_hash must be a SHA-256 hex digest")
    raw_artifact_ref = snapshot["raw_artifact_ref"]
    if raw_artifact_ref is not None:
        raw_artifact_ref = _required_string(raw_artifact_ref, "raw_artifact_ref")
        posix_ref = PurePosixPath(raw_artifact_ref)
        windows_ref = PureWindowsPath(raw_artifact_ref)
        if (
            posix_ref.is_absolute()
            or windows_ref.is_absolute()
            or ".." in posix_ref.parts
            or ".." in windows_ref.parts
            or urlparse(raw_artifact_ref).scheme
        ):
            raise ValueError("raw_artifact_ref must be a safe relative path")

    parse_status = _required_string(snapshot["parse_status"], "parse_status")
    if parse_status not in PARSE_STATUSES:
        raise ValueError(f"parse_status must be one of {sorted(PARSE_STATUSES)}")
    reason = _optional_string(snapshot["reason"], "reason")
    if parse_status != "ok" and reason is None:
        raise ValueError("failed or missing snapshots require a reason")
    source_refs = _source_refs(snapshot["source_refs"], "source_refs")

    rows = snapshot["rows"]
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    if parse_status == "ok" and not rows:
        raise ValueError("ok snapshots require probability rows")
    current_window_start = None
    time_window = (snapshot.get("coverage") or {}).get("source_time_window")
    if snapshot.get("transport") in {"native_chromium_direct", "curl_cffi_webforms"} and time_window:
        current_window_start = _parse_datetime(time_window["start"], "source_time_window.start")
        end = _parse_datetime(time_window["end"], "source_time_window.end")
        if end != source_as_of or not 0 <= (end - current_window_start).total_seconds() <= 60:
            raise ValueError("invalid source_time_window")
    normalized_rows, meetings = _validate_rows(rows, collected_at, source_as_of, parse_status,
                                             current_window_start=current_window_start)
    if parse_status == "ok" and not any(
        meeting["comparison_window"] == "current" for meeting in meetings
    ):
        raise ValueError("ok snapshots require a current comparison window")

    futures = snapshot["futures"]
    if not isinstance(futures, list):
        raise ValueError("futures must be a list")
    normalized_futures: list[dict[str, Any]] = []
    for index, future in enumerate(futures):
        if not isinstance(future, dict) or any(not isinstance(key, str) for key in future):
            raise ValueError(f"futures[{index}] must be a dictionary with string keys")
        future_copy = copy.deepcopy(future)
        if "contract_ref" in future_copy:
            future_copy["contract_ref"] = _optional_string(
                future_copy["contract_ref"], f"futures[{index}].contract_ref"
            )
        if "as_of" in future_copy and future_copy["as_of"] is not None:
            future_time = _parse_datetime(future_copy["as_of"], f"futures[{index}].as_of")
            if future_time > collected_at:
                raise ValueError(f"futures[{index}].as_of cannot be later than collected_at")
            future_copy["as_of"] = _iso(future_time)
        _assert_json(future_copy, f"futures[{index}]")
        normalized_futures.append(future_copy)

    normalized = {
        "source": source,
        "snapshot_id": snapshot_id,
        "collected_at": _iso(collected_at),
        "as_of": _iso(source_as_of) if source_as_of is not None else None,
        "source_url": source_url,
        "collector_version": collector_version,
        "http_status": http_status,
        "content_hash": content_hash,
        "raw_artifact_ref": raw_artifact_ref,
        "parse_status": parse_status,
        "reason": reason,
        "source_refs": source_refs,
        "rows": normalized_rows,
        "futures": normalized_futures,
    }
    for key, value in snapshot.items():
        if key not in _SNAPSHOT_KEYS:
            normalized[key] = copy.deepcopy(value)
    _assert_json(normalized, "snapshot")
    return normalized, meetings


def _validate_rows(
    rows: list[Any],
    collected_at: datetime,
    source_as_of: datetime | None,
    parse_status: str,
    *,
    current_window_start: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_rows: list[dict[str, Any]] = []
    groups: OrderedDict[tuple[date, str], dict[str, Any]] = OrderedDict()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"rows[{index}] must be a dictionary")
        expected = {
            "meeting_date",
            "contract_ref",
            "comparison_window",
            "as_of",
            "target_low",
            "target_high",
            "probability",
        }
        missing = sorted(expected - row.keys())
        extra = sorted(row.keys() - expected)
        if missing or extra:
            detail = []
            if missing:
                detail.append(f"missing {missing}")
            if extra:
                detail.append(f"unexpected {extra}")
            raise ValueError(f"rows[{index}] has invalid shape: {'; '.join(detail)}")
        meeting_date = _parse_date(row["meeting_date"], f"rows[{index}].meeting_date")
        contract_ref = _optional_string(row["contract_ref"], f"rows[{index}].contract_ref")
        window = _required_string(row["comparison_window"], f"rows[{index}].comparison_window")
        if window not in COMPARISON_WINDOWS:
            raise ValueError(f"rows[{index}].comparison_window is invalid")
        row_as_of = _parse_datetime(row["as_of"], f"rows[{index}].as_of")
        if row_as_of > collected_at:
            raise ValueError(f"rows[{index}].as_of cannot be later than collected_at")
        if source_as_of is not None and row_as_of > source_as_of:
            raise ValueError(f"rows[{index}].as_of cannot be later than snapshot as_of")
        target_low = _finite_float(row["target_low"], f"rows[{index}].target_low")
        target_high = _finite_float(row["target_high"], f"rows[{index}].target_high")
        probability = _finite_float(row["probability"], f"rows[{index}].probability")
        if not 0 <= target_low <= target_high <= 100:
            raise ValueError(f"rows[{index}] target range must be within 0..100")
        if not 0 <= probability <= 1:
            raise ValueError(f"rows[{index}].probability must be within 0..1")

        normalized_row = {
            "meeting_date": meeting_date.isoformat(),
            "contract_ref": contract_ref,
            "comparison_window": window,
            "as_of": _iso(row_as_of),
            "target_low": target_low,
            "target_high": target_high,
            "probability": probability,
        }
        normalized_rows.append(normalized_row)
        key = (meeting_date, window)
        group = groups.setdefault(
            key,
            {
                "meeting_date": meeting_date,
                "contract_ref": contract_ref,
                "comparison_window": window,
                "as_of": row_as_of,
                "rows": [],
            },
        )
        if group["contract_ref"] != contract_ref or group["as_of"] != row_as_of:
            raise ValueError("one meeting/window must use one contract_ref and actual source as_of")
        group["rows"].append(normalized_row)

    for group in groups.values():
        ordered = sorted(group["rows"], key=lambda item: (item["target_low"], item["target_high"]))
        for previous, current in zip(ordered, ordered[1:]):
            if current["target_low"] < previous["target_high"]:
                raise ValueError("target probability ranges must not overlap")
        if parse_status == "ok":
            total = math.fsum(item["probability"] for item in group["rows"])
            if not 0.99 <= total <= 1.01:
                raise ValueError("each successful meeting/window probability sum must be within 0.99..1.01")
        if (
            source_as_of is not None
            and group["comparison_window"] == "current"
            and group["as_of"] != source_as_of
            and not (current_window_start is not None and current_window_start <= group["as_of"] <= source_as_of)
        ):
            raise ValueError("current window as_of must match snapshot as_of")
    return normalized_rows, list(groups.values())


def _validate_factor(factor: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot["parse_status"] != "ok" or snapshot["as_of"] is None:
        raise ValueError("factor requires an ok snapshot with a source as_of")
    if not isinstance(factor, dict) or any(not isinstance(key, str) for key in factor):
        raise ValueError("factor must be a dictionary with string keys")
    normalized = copy.deepcopy(factor)
    factor_snapshot_id = _uuid_string(normalized.get("snapshot_id"), "factor.snapshot_id")
    if factor_snapshot_id != snapshot["snapshot_id"]:
        raise ValueError("factor.snapshot_id must match snapshot.snapshot_id")
    normalized["snapshot_id"] = factor_snapshot_id
    version_key = next(
        (key for key in ("version", "factor_version", "repricing_version") if key in normalized),
        None,
    )
    if version_key is None:
        raise ValueError("factor requires version, factor_version, or repricing_version")
    normalized[version_key] = _required_string(normalized[version_key], f"factor.{version_key}")
    factor_as_of = _parse_datetime(normalized.get("as_of"), "factor.as_of")
    snapshot_as_of = _parse_optional_datetime(snapshot["as_of"], "snapshot.as_of")
    if snapshot_as_of is not None and factor_as_of < snapshot_as_of:
        raise ValueError("factor.as_of cannot be earlier than snapshot.as_of")
    collected_at = _parse_datetime(snapshot["collected_at"], "snapshot.collected_at")
    if factor_as_of < collected_at:
        raise ValueError("factor.as_of cannot be earlier than snapshot.collected_at")
    normalized["as_of"] = _iso(factor_as_of)
    normalized["source_refs"] = _source_refs(normalized.get("source_refs"), "factor.source_refs")
    _assert_json(normalized, "factor")
    return normalized


def _stage_factor_if_needed(
    session: Session,
    snapshot: FedWatchRawSnapshot,
    *,
    normalized_factor: dict[str, Any] | None,
    factor_hash: str | None,
) -> None:
    if normalized_factor is None:
        return
    existing_factor = session.scalar(
        select(FedWatchFactor).where(FedWatchFactor.snapshot_id == snapshot.snapshot_id)
    )
    if existing_factor is not None:
        if existing_factor.payload_hash != factor_hash:
            raise ValueError("snapshot_id already has a conflicting factor payload")
        return
    session.add(_factor_model(normalized_factor, factor_hash))
    session.flush()


def _factor_model(factor: dict[str, Any], factor_hash: str | None) -> FedWatchFactor:
    version_key = next(
        key for key in ("version", "factor_version", "repricing_version") if key in factor
    )
    return FedWatchFactor(
        snapshot_id=factor["snapshot_id"],
        factor_version=factor[version_key],
        as_of=_parse_datetime(factor["as_of"], "factor.as_of"),
        source_refs=copy.deepcopy(factor["source_refs"]),
        payload=copy.deepcopy(factor),
        payload_hash=factor_hash or _payload_hash(factor),
    )


def _snapshot_to_dict(model: FedWatchRawSnapshot) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for meeting in model.meetings:
        for probability in meeting.probabilities:
            rows.append(
                {
                    "meeting_date": meeting.meeting_date.isoformat(),
                    "contract_ref": meeting.contract_ref,
                    "comparison_window": meeting.comparison_window,
                    "as_of": _iso(_database_datetime(meeting.as_of)),
                    "target_low": probability.target_low,
                    "target_high": probability.target_high,
                    "probability": probability.probability,
                }
            )
    result = {
        "source": model.source,
        "snapshot_id": model.snapshot_id,
        "collected_at": _iso(_database_datetime(model.collected_at)),
        "as_of": _iso(_database_datetime(model.as_of)) if model.as_of is not None else None,
        "source_url": model.source_url,
        "collector_version": model.collector_version,
        "http_status": model.http_status,
        "content_hash": model.content_hash,
        "raw_artifact_ref": model.raw_artifact_ref,
        "parse_status": model.parse_status,
        "reason": model.reason,
        "source_refs": copy.deepcopy(model.source_refs),
        "rows": rows,
        "futures": [copy.deepcopy(future.payload) for future in model.futures],
    }
    result.update(copy.deepcopy(model.snapshot_metadata))
    return result


def _payload_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field} must be a non-empty UTC datetime")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO datetime") from exc
    else:
        raise ValueError(f"{field} must be an ISO datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _parse_optional_datetime(value: Any, field: str) -> datetime | None:
    return None if value is None else _parse_datetime(value, field)


def _database_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"{field} must be a YYYY-MM-DD date")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a YYYY-MM-DD date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a YYYY-MM-DD date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must be a YYYY-MM-DD date")
    return parsed


def _parse_optional_date(value: Any, field: str) -> date | None:
    return None if value is None else _parse_date(value, field)


def _uuid_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a UUID string")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a UUID string") from exc


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field)


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{field} must be a finite number")
    return converted


def _source_refs(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{field} must be a list of dictionaries")
    copied = copy.deepcopy(value)
    _assert_json(copied, field)
    return copied


def _assert_json(value: Any, field: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON serializable") from exc


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
