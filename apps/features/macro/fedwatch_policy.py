"""Compatibility projection of normalized FedWatch into macro evidence."""

from copy import deepcopy
from math import sqrt
from math import isfinite
from datetime import datetime

from apps.features.macro.policy_path import _compare_sep


def project_fedwatch_policy(view, *, as_of, sep=None):
    factor = view.get("factor") or {}
    path = factor.get("market_implied_path") or {}
    health = view.get("source_health") or {}
    fresh = health.get("status") == "fresh"
    meetings = []
    for m in path.get("meetings", []):
        expected = m["expected_rate_pct"]
        meetings.append({**deepcopy(m), "expected_target_midpoint_pct": expected,
                         "distribution_sd_bp": sqrt(sum(b["probability"] * ((b["target_low"]+b["target_high"])/2-expected)**2 for b in m["bins"])) * 100,
                         **{"repricing_"+w+"_bp": m.get("comparisons", {}).get(w, {}).get("expected_rate_delta_bp") if fresh else None for w in ("1d", "1w", "1m")}})
    by_date = {m["meeting_date"]: m for m in meetings}
    rows = []
    for horizon in ("next_meeting", "year_end", "3m", "6m", "12m"):
        selection = path.get(horizon) if horizon in {"next_meeting", "year_end"} else path.get("horizons", {}).get(horizon, {}).get("selected_meeting")
        selected = by_date.get((selection or {}).get("meeting_date"))
        rows.append({"horizon": horizon, "meeting_date": selected["meeting_date"] if selected else None,
                     "status": "available" if selected and fresh else "stale" if selected else "unavailable",
                     "reason": health.get("reason") if selected else "meeting_coverage_missing",
                     "expected_target_midpoint_pct": selected["expected_target_midpoint_pct"] if selected else None,
                     **{"repricing_"+w+"_bp": selected["repricing_"+w+"_bp"] if selected else None for w in ("1d", "1w", "1m")},
                     "observed_at": selected.get("source_as_of") if selected else None,
                     "source_refs": deepcopy(view.get("source_refs", []))})
    return {"schema_version": "fedwatch_policy_projection.v1", "status": ("available" if view.get("coverage_status") == "complete" else "partial") if fresh and meetings else "unavailable",
            "reason": health.get("reason"), "observed_at": view.get("as_of"), "snapshot_id": view.get("snapshot_id"),
            "source_refs": deepcopy(view.get("source_refs", [])), "meetings": meetings,
            "official_policy": deepcopy(factor.get("official_policy", {})),
            "market_implied_path": deepcopy(path), "repricing": deepcopy(factor.get("repricing", {})),
            "source_health": deepcopy(health), "confirmation": deepcopy(factor.get("confirmation", {})),
            "policy_path": {"rows": rows, "market_vs_sep": _compare_sep(rows[1], sep, as_of=as_of)}}


def daily_confirmation_context(rows, *, as_of):
    """Date-only daily changes are auxiliary evidence, not event confirmation."""
    cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00")).date().isoformat()
    by = {r.get("symbol"): r for r in rows}
    items = {}
    for symbol in ("US02Y", "REAL10Y", "BROAD_DOLLAR"):
        row = by.get(symbol, {})
        value = row.get("change")
        valid = (row.get("status") == "fresh" and bool(row.get("source_refs"))
                 and isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
                 and isinstance(row.get("observation_date"), str) and isinstance(row.get("previous_date"), str)
                 and row["previous_date"] < row["observation_date"] <= cutoff)
        items[symbol] = {"status": "available_auxiliary" if valid else "unavailable",
                         "window_start": row.get("previous_date"), "window_end": row.get("observation_date"),
                         "change": value * (1 if symbol == "BROAD_DOLLAR" else 100) if valid else None,
                         "unit": "index_points" if symbol == "BROAD_DOLLAR" else "bp",
                         "source_refs": deepcopy(row.get("source_refs", [])),
                         "window_aligned": False, "aligned_with_repricing": None}
    return {"status": "partial" if any(i["status"] == "available_auxiliary" for i in items.values()) else "missing",
            "items": items, "included_in_repricing_score": False,
            "reason": "daily_source_dates_do_not_verify_intraday_FedWatch_comparison_windows"}
