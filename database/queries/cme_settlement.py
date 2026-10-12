"""Immutable history, cutoff-safe version preference and stability evidence."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import case, select

from database.models.cme_settlement import CmeSettlementContract, CmeSettlementSnapshot


def utc(value):
    at = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if at.tzinfo is None:
        raise ValueError("timezone_required")
    return at.astimezone(UTC)


def expected_trade_date(as_of):
    # Conservative EOD availability: after 06:00 Chicago, expect preceding weekday.
    # Exchange holiday exceptions are not guessed from a federal holiday calendar.
    local = utc(as_of).astimezone(ZoneInfo("America/Chicago"))
    day = local.date() - timedelta(days=1 if local.hour >= 6 else 2)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def save_settlement(session, observation):
    payload = deepcopy(observation)
    UUID(payload["snapshot_id"])
    if payload.get("source") != "cme_settlement" or payload.get("official_display_probability") is not False:
        raise ValueError("settlement_provenance_required")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
    existing = session.get(CmeSettlementSnapshot, payload["snapshot_id"])
    if existing:
        if existing.payload_hash != digest:
            raise ValueError("immutable_snapshot_conflict")
        return
    session.add(
        CmeSettlementSnapshot(
            snapshot_id=payload["snapshot_id"],
            trade_date=date.fromisoformat(payload["trade_date"]),
            observed_at=utc(payload["observed_at"]),
            settlement_status=payload["settlement_status"],
            data_status=payload["data_status"],
            payload_hash=digest,
            payload=payload,
        )
    )
    session.flush()
    for row in payload["rows"]:
        session.add(
            CmeSettlementContract(
                snapshot_id=payload["snapshot_id"],
                contract=row["contract"],
                contract_month=date.fromisoformat(row["contract_month"]),
                settle=row["settle"],
                volume=row["volume"],
                open_interest=row["open_interest"],
            )
        )
    session.flush()


def preferred_settlement(session, *, trade_date, as_of):
    statement = (
        select(CmeSettlementSnapshot)
        .where(
            CmeSettlementSnapshot.trade_date == trade_date,
            CmeSettlementSnapshot.observed_at <= utc(as_of),
            CmeSettlementSnapshot.data_status == "available",
        )
        .order_by(
            case((CmeSettlementSnapshot.settlement_status == "FINAL", 1), else_=0).desc(),
            CmeSettlementSnapshot.observed_at.desc(),
            CmeSettlementSnapshot.snapshot_id.desc(),
        )
        .limit(1)
    )
    value = session.scalar(statement)
    return deepcopy(value.payload) if value else None


def settlement_health(observation, *, as_of, no_trade_dates=(), retention_start=None, retention_evidence=None):
    if not observation:
        return {"status": "unavailable", "reason": "no_observation"}
    row = observation
    day = date.fromisoformat(row["trade_date"])
    status = row["health"]
    if utc(row["observed_at"]) > utc(as_of):
        return {"status": "unavailable", "reason": "observation_after_cutoff"}
    if row["data_status"] == "available":
        status = "fresh" if day >= expected_trade_date(as_of) else "stale"
        if day > utc(as_of).astimezone(ZoneInfo("America/Chicago")).date():
            status = "parse_failed"
    elif row["request_status"] == "success" and row["data_status"] in {"upstream_empty", "no_trade_day"}:
        if day.weekday() >= 5 or day in no_trade_dates:
            status = "no_trade_day"
        elif retention_start and retention_evidence and day < retention_start:
            status = "outside_free_retention"
        else:
            status = "upstream_empty"
    return {
        "status": status,
        "request_status": row["request_status"],
        "data_status": row["data_status"],
        "snapshot_id": row["snapshot_id"],
        "trade_date": row["trade_date"],
        "settlement_status": row["settlement_status"],
        "reason": row.get("reason"),
        "evaluated_at": utc(as_of).isoformat(),
        "retention_evidence": retention_evidence if status == "outside_free_retention" else None,
    }


def settlement_stability(session, *, as_of, lookback_days=30):
    cutoff = utc(as_of)
    records = session.scalars(
        select(CmeSettlementSnapshot)
        .where(
            CmeSettlementSnapshot.observed_at <= cutoff,
            CmeSettlementSnapshot.observed_at >= cutoff - timedelta(days=lookback_days),
        )
        .order_by(CmeSettlementSnapshot.observed_at, CmeSettlementSnapshot.snapshot_id)
    ).all()
    # Backfills and fixture replays must not buy elapsed-day stability credit.
    live = [
        x.payload
        for x in records
        if x.payload.get("collection_mode") == "live"
        and x.payload["trade_date"] == expected_trade_date(x.payload["observed_at"]).isoformat()
    ]
    successes = [x for x in live if x["data_status"] == "available"]
    dates = sorted({x["trade_date"] for x in successes})
    previous = {}
    changes = []
    for record in records:
        row = record.payload
        if row["data_status"] != "available":
            continue
        old = previous.get(row["trade_date"])
        if old:
            old_rows = {r["contract"]: r for r in old["rows"]}
            new_rows = {r["contract"]: r for r in row["rows"]}
            changes.append(
                {
                    "trade_date": row["trade_date"],
                    "previous_snapshot_id": old["snapshot_id"],
                    "snapshot_id": row["snapshot_id"],
                    "phase_change": old["settlement_status"] != row["settlement_status"],
                    "hash_changed": old["content_hash"] != row["content_hash"],
                    "contract_set_changed": old_rows.keys() != new_rows.keys(),
                    "changed_contracts": [k for k in old_rows.keys() & new_rows.keys() if old_rows[k] != new_rows[k]],
                }
            )
        previous[row["trade_date"]] = row
    return {
        "eligible_attempts": len(live),
        "successes": len(successes),
        "success_rate": len(successes) / len(live) if live else None,
        "successful_trade_dates": dates,
        "distinct_trade_days": len(dates),
        "observation_window_ready": len(dates) >= 5,
        "production_stability": "REVIEW_REQUIRED" if len(dates) >= 5 else "INSUFFICIENT_DAYS",
        "max_latency_ms": max((x["latency_ms"] for x in live), default=None),
        "parse_failures": sum(x["data_status"] == "parse_failed" for x in live),
        "reconciliation": changes,
    }
