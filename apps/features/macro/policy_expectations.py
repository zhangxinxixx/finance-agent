"""Market-implied marginal distributions; never inferred from 2Y or gold OI."""

from datetime import datetime, date, timedelta
from math import isfinite, sqrt


def _time(value):
    if not isinstance(value, str):
        raise ValueError("timestamp required")
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("timezone required")
    return t


def build_policy_expectations(source, *, as_of):
    empty = {
        "schema_version": "policy_expectations.v4",
        "status": "unavailable",
        "family": "policy_expectation",
        "meetings": [],
        "reason": "verified_market_distribution_missing",
        "source_refs": [],
        "first_action_timing": "unavailable_without_joint_path_distribution",
    }
    if not source or not isinstance(source, dict):
        return empty
    try:
        cutoff, observed = _time(as_of), _time(source["observed_at"])
        max_age = source.get('max_age_seconds', 900)
        if not isinstance(max_age, (int, float)) or isinstance(max_age, bool) or not isfinite(max_age) or not 0 < max_age <= 900:
            return {**empty, 'reason': 'invalid_policy_freshness_limit'}
        if observed > cutoff or (cutoff - observed).total_seconds() > max_age:
            return {**empty, "reason": "stale_or_future_policy_distribution"}
        if (
            source.get("probability_unit") != "fraction"
            or source.get("rate_unit") != "percent"
            or not source.get("source_refs")
        ):
            return empty
        if source.get('current_target_midpoint') is None:
            return {**empty, 'reason': 'verified_current_target_midpoint_missing',
                    'source_refs': source['source_refs']}
        current = float(source["current_target_midpoint"])
        if not isfinite(current):
            return empty
        meetings, seen = [], set()
        for m in source["meetings"]:
            d = date.fromisoformat(m["meeting_date"])
            if d < cutoff.date() or d in seen:
                raise ValueError("duplicate or past meeting")
            if m.get('observed_at'):
                meeting_observed = _time(m['observed_at'])
                if meeting_observed > cutoff or not 0 <= (cutoff - meeting_observed).total_seconds() <= max_age:
                    raise ValueError('invalid meeting observation time')
            seen.add(d)
            bins = sorted([(float(b["lower"]), float(b["upper"]), float(b["probability"])) for b in m["bins"]])
            if not bins or any(not all(isfinite(v) for v in b) or b[0] >= b[1] or not 0 <= b[2] <= 1 for b in bins):
                raise ValueError("invalid bins")
            if any(a[1] > b[0] for a, b in zip(bins, bins[1:])) or abs(sum(b[2] for b in bins) - 1) > 0.001:
                raise ValueError("overlap or incomplete probability mass")
            # Published percentages may round slightly away from one. Keep
            # expectations on a normalized distribution, and expose the input mass.
            input_mass = sum(b[2] for b in bins)
            bins = [(lo, hi, p / input_mass) for lo, hi, p in bins]
            mean = sum((lo + hi) / 2 * p for lo, hi, p in bins)
            sd = sqrt(sum(p * ((lo + hi) / 2 - mean) ** 2 for lo, hi, p in bins))
            row = {
                "meeting_date": d.isoformat(),
                "input_probability_mass": input_mass,
                "expected_target_midpoint_pct": mean,
                "distribution_sd_bp": sd * 100,
                "cumulative_bp_vs_current": (mean - current) * 100,
                "hike_vs_current_probability": sum(p for lo, hi, p in bins if (lo + hi) / 2 > current),
                "cut_vs_current_probability": sum(p for lo, hi, p in bins if (lo + hi) / 2 < current),
                "hold_vs_current_probability": sum(p for lo, hi, p in bins if (lo + hi) / 2 == current),
                "expected_upside_bp_vs_current": sum(p * max((lo + hi) / 2 - current, 0) * 100 for lo, hi, p in bins),
                "expected_downside_bp_vs_current": sum(p * max(current - (lo + hi) / 2, 0) * 100 for lo, hi, p in bins),
                "repricing_1d_bp": None,
                "repricing_1w_bp": None,
            }
            meetings.append(row)
        meetings.sort(key=lambda m: m["meeting_date"])
        if not meetings:
            return empty
        # Only compare the same meeting and provider; historical snapshots
        # must carry their original timestamps and current target reference.
        comparisons = source.get('comparisons')
        comparisons = comparisons if isinstance(comparisons, dict) else {}
        for label, days in [("1d", 1), ("1w", 7)]:
            prior = comparisons.get(label)
            if not isinstance(prior, dict) or not source.get('provider') or prior.get("provider") != source.get("provider"):
                continue
            try:
                pt = _time(prior["observed_at"])
            except (KeyError, ValueError, TypeError):
                continue
            if (observed.date() - pt.date()).days != days or pt >= observed:
                continue
            old = build_policy_expectations({**prior, "comparisons": {}}, as_of=prior["observed_at"])
            previous = {m["meeting_date"]: m for m in old["meetings"]}
            for row in meetings:
                if row["meeting_date"] in previous:
                    row["repricing_" + label + "_bp"] = (
                        row["expected_target_midpoint_pct"]
                        - previous[row["meeting_date"]]["expected_target_midpoint_pct"]
                    ) * 100
        horizons = {}
        for n in (3, 6, 12):
            target = observed.date() + timedelta(days=round(n * 365.25 / 12))
            available = [m for m in meetings if date.fromisoformat(m["meeting_date"]) <= target]
            chosen = available[-1] if available else None
            horizons[str(n) + "m"] = (
                chosen if chosen and (target - date.fromisoformat(chosen["meeting_date"])).days <= 62 else None
            )
        year_end = [m for m in meetings if m["meeting_date"][:4] == str(observed.year)]
        return {
            **empty,
            "status": "available",
            "reason": None,
            "observed_at": observed.isoformat(),
            "meetings": meetings,
            "next_meeting": meetings[0],
            "horizons": horizons,
            "year_end": year_end[-1] if year_end and year_end[-1]["meeting_date"][5:7] == "12" else None,
            "peak_in_observed_window": max(meetings, key=lambda m: m["expected_target_midpoint_pct"]),
            "source_refs": source["source_refs"],
            "limitations": [
                "marginal distributions do not identify first-action probability",
                "target midpoint expectation is not EFFR or OIS",
                "peak observed is not full-cycle terminal rate",
                "FedWatch,2Y,SOFR,fed funds,OIS share one policy family; no duplicate votes",
            ],
        }
    except (KeyError, ValueError, TypeError, OverflowError):
        return {**empty, "reason": "invalid_policy_distribution_contract"}
