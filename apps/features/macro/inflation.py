"""Same-download monthly momentum. Levels, rates and causal claims stay separate."""

from collections import defaultdict
from datetime import date, datetime
from math import isfinite

SERIES = {
    "CPIAUCSL": ("headline_cpi", "SA"),
    "CPILFESL": ("core_cpi", "SA"),
    "CPIAUCNS": ("headline_cpi_nsa", "NSA"),
    "CPILFENS": ("core_cpi_nsa", "NSA"),
    "PCEPI": ("headline_pce", "SA"),
    "PCEPILFE": ("core_pce", "SA"),
    "PPIFIS": ("ppi_final_demand", "SA"),
    "CPIENGSL": ("energy", "SA"),
    "CPIUFDSL": ("food", "SA"),
    "CUSR0000SAH1": ("shelter", "SA"),
    "CUSR0000SEHA": ("rent", "SA"),
    "CUSR0000SEHC": ("owners_equivalent_rent", "SA"),
    "CUSR0000SACL1E": ("core_goods", "SA"),
    "CUSR0000SASLE": ("services_ex_energy", "SA"),
}


def _month(d):
    return d.year * 12 + d.month


def build_inflation(points, *, as_of):
    cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    groups = defaultdict(list)
    for p in points:
        if p.get("symbol") not in SERIES:
            continue
        try:
            t = datetime.fromisoformat(p["retrieved_at"].replace("Z", "+00:00"))
            d = date.fromisoformat(p["date"])
            value = float(p["value"])
            if (
                not t.tzinfo
                or not cutoff.tzinfo
                or t > cutoff
                or d > cutoff.date()
                or not isfinite(value)
                or value <= 0
            ):
                continue
        except (ValueError, TypeError, KeyError):
            continue
        if p.get("raw_path") and p.get("source_url"):
            groups[(p["symbol"], p["raw_path"], p["retrieved_at"])].append(p)
    rows = {}
    for symbol, (label, adjustment) in SERIES.items():
        candidates = [(key, ps) for key, ps in groups.items() if key[0] == symbol]
        if not candidates:
            rows[label] = {"status": "unavailable", "reason": "no_dated_same_vintage_series", "symbol": symbol}
            continue
        key, ps = max(candidates, key=lambda item: datetime.fromisoformat(item[0][2].replace("Z", "+00:00")))
        by_month = defaultdict(set)
        for p in ps:
            by_month[_month(date.fromisoformat(p["date"]))].add(float(p["value"]))
        if any(len(v) != 1 for v in by_month.values()):
            rows[label] = {"status": "unavailable", "reason": "conflicting_months", "symbol": symbol}
            continue
        values = {m: next(iter(v)) for m, v in by_month.items()}
        last = max(values)

        def change(n, end=last, annual=False):
            required = range(end - n, end + 1) if annual else (end - n, end)
            if any(m not in values for m in required):
                return None
            return round(((values[end] / values[end - n]) ** (12 / n if annual else 1) - 1) * 100, 6)

        latest = max(ps, key=lambda p: p["date"])
        row = {
            "status": "available" if (cutoff.date() - date.fromisoformat(latest["date"])).days <= 100 else "stale",
            "symbol": symbol,
            "observation_date": latest["date"],
            "level": values[last],
            "adjustment": adjustment,
            "mom_pct": change(1) if adjustment == "SA" else None,
            "yoy_pct": change(12),
            "yoy_basis": adjustment,
            "saar_3m_pct": change(3, annual=True) if adjustment == "SA" else None,
            "saar_6m_pct": change(6, annual=True) if adjustment == "SA" else None,
            "previous_saar_3m_pct": change(3, end=last - 1, annual=True) if adjustment == "SA" else None,
            "source_refs": [{k: latest[k] for k in ("symbol", "source", "source_url", "raw_path", "retrieved_at")}],
            "formula": "100*((index_t/index_t-n)^(12/n)-1); exact contiguous months, one raw vintage",
        }
        a, b = row["saar_3m_pct"], row["previous_saar_3m_pct"]
        row["momentum"] = (
            "unavailable" if a is None or b is None else "accelerating" if a > b else "cooling" if a < b else "stable"
        )
        rows[label] = row
    return {
        "schema_version": "inflation_momentum.v4",
        "as_of": as_of,
        "series": rows,
        "surprise": {"status": "unavailable", "reason": "no_verified_pre_release_consensus"},
        "ppi_pce_mapping": {
            "status": "unavailable",
            "reason": "requires_matched_PPI_components_PCE_weights_and_vintage; no_one_to_one_pass_through",
        },
        "inflation_type": "model_hypothesis_required",
        "limitations": ["SA同比不冒充官方NSA同比", "价格分项本身不能识别供给或需求冲击", "缺分项权重不计算贡献"],
    }
