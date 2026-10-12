"""One read-only identity and clock contract for research reading surfaces."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def _time(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def project_level_validity(level: dict, *, data_as_of=None, historical=False, now=None) -> dict:
    """Expose saved validity bounds; never manufacture a lifetime or activation."""
    clock = now or datetime.now(timezone.utc)
    source_time = _time(level.get("data_as_of") or level.get("as_of") or data_as_of)
    until = level.get("valid_until") or level.get("expiry_date")
    end = _time(until)
    reasons = []
    state = str(level.get("status") or "").casefold()
    if historical:
        status, reasons = "historical", ["historical_research"]
    elif state in {"stale", "invalidated", "expired"} or end is not None and clock >= end:
        status, reasons = "expired", ["level_expired_or_invalidated"]
    elif isinstance(until, str) and len(until) == 10 and until < clock.date().isoformat():
        status, reasons = "expired", ["level_expiry_date_passed"]
    elif source_time is None or source_time > clock:
        status, reasons = "unavailable", ["data_time_unverified"]
    elif end is None:
        status, reasons = "unavailable", ["valid_until_time_unverified"]
    elif state != "active" or level.get("eligible_for_target") is False or not level.get("source_refs"):
        status, reasons = "unavailable", ["level_activation_unverified"]
    else:
        status = "active"
    return {"status": status, "data_as_of": source_time.isoformat() if source_time else None,
            "valid_until": end.isoformat() if end else str(until) if until else None, "reason_codes": reasons}


def build_research_identity(*, report_id, run_id, snapshot_id, trade_date,
                            snapshot=None, generated_at=None, historical=False, now=None) -> dict:
    clock = now or datetime.now(timezone.utc)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    bound = bool(snapshot_id and run_id and snapshot.get("snapshot_id") == snapshot_id
                 and snapshot.get("run_id") == run_id and str(snapshot.get("trade_date")) == str(trade_date))
    stamp = _time(snapshot.get("snapshot_time")) if bound else None
    # Research from another session remains readable with explicit history status.
    historical = historical or bool(trade_date and str(trade_date) < clock.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat())
    levels = ((snapshot.get("gold_workflow") or {}).get("key_levels") or []) if bound else []
    states = [project_level_validity(level, data_as_of=stamp, historical=historical, now=clock)
              for level in levels if isinstance(level, dict)]
    if states:
        status = "historical" if historical else "unavailable" if any(s["status"] == "unavailable" for s in states) else "expired" if any(s["status"] == "expired" for s in states) else "active"
        bounds = [_time(s["valid_until"]) for s in states if _time(s["valid_until"]) is not None]
        validity = {"status": status, "data_as_of": stamp.isoformat() if stamp else None,
                    "valid_until": min(bounds).isoformat() if len(bounds) == len(states) else None,
                    "reason_codes": sorted({reason for s in states for reason in s["reason_codes"]})}
    else:
        validity = {"status": "historical" if historical else "unavailable", "data_as_of": stamp.isoformat() if stamp else None,
                    "valid_until": None, "reason_codes": ["key_levels_unavailable"]}
    generated = _time(generated_at)
    return {"schema_version": "research_identity.v1", "report_id": report_id, "run_id": run_id,
            "snapshot_id": snapshot_id, "trade_date": str(trade_date) if trade_date else None,
            "research_version": snapshot_id or run_id or None,
            "data_as_of": stamp.isoformat() if stamp else None,
            "generated_at": generated.isoformat() if generated else None, "key_level_validity": validity}


def project_research_levels(levels, identity: dict) -> list[dict]:
    return [{**deepcopy(level), "validity": project_level_validity(
        level, data_as_of=identity["data_as_of"],
        historical=identity["key_level_validity"]["status"] == "historical")}
        for level in levels or [] if isinstance(level, dict)]
