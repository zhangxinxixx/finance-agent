"""Validate saved domain features without erasing independent usable records."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path

from apps.features.research.workflow import _row_time_valid
from apps.features.macro.growth import _UNITS as GROWTH_UNITS
from apps.parsers.bls.employment import BLS_SERIES_BY_ID


def _clock_reasons(record, cutoff):
    """Publication and collection clocks are distinct from observation periods."""
    reasons = []
    for key in ("retrieved_at", "release_time", "release_datetime", "published_at"):
        value = record.get(key)
        if value is None or str(value).lower() in {"", "unknown", "unavailable", "n/a"}:
            continue
        try:
            clock = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            bound = datetime.fromisoformat(str(cutoff).replace("Z", "+00:00"))
            valid = clock.utcoffset() is not None and bound.utcoffset() is not None and clock <= bound
        except (ValueError, TypeError):
            valid = False
        if not valid:
            reasons.append("future_or_invalid_" + key)
    value = record.get("release_date")
    if value and str(value).lower() not in {"unknown", "unavailable", "n/a"}:
        try:
            if date.fromisoformat(str(value)) > date.fromisoformat(str(cutoff)[:10]):
                reasons.append("future_or_invalid_release_date")
        except (TypeError, ValueError):
            reasons.append("future_or_invalid_release_date")
    return reasons


def archived_ref_valid(ref, storage_root):
    """An archived source must exist under the configured storage, with any saved hash."""
    if storage_root is None:
        return True
    try:
        root = Path(storage_root).resolve()
        path = Path(ref['raw_path'])
        if not path.is_absolute():
            if path.parts and path.parts[0] == 'storage':
                path = Path(*path.parts[1:])
            path = root / path
        path = path.resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(root):
            return False
        expected = ref.get('raw_sha256') or ref.get('sha256')
        return not expected or sha256(path.read_bytes()).hexdigest() == expected
    except (KeyError, TypeError, ValueError, OSError):
        return False


def validate_grouped_domain(group, *, domain, cutoff, trade_date, refs_valid, reject):
    """Keep dated, sourced feature records; invalidate dependent summaries locally."""
    if not isinstance(group, dict) or not group:
        return {"status": "unavailable", "reason": "no_domain_features"}
    fields = ("series",) if domain == "inflation" else ("metrics", "industry_employment") if domain == "employment" else ("metrics",)
    if not any(field in group for field in fields):
        return {"status": "unavailable", "reason": "no_domain_features"}
    result = deepcopy(group)
    references = group.get("source_refs") or {}
    counts = []

    def finite_tree(value):
        if isinstance(value, dict):
            return all(finite_tree(v) for v in value.values())
        if isinstance(value, list):
            return all(finite_tree(v) for v in value)
        if type(value) in (int, float):
            try:
                return isfinite(value)
            except OverflowError:
                return False
        return True

    def clean_records(records, field):
        if not isinstance(records, dict):
            return {}
        cleaned = {}
        for key, record in records.items():
            path = f"daily_research.{domain}.{field}.{key}"
            if not isinstance(record, dict):
                reject(path, ["invalid_shape"])
                continue
            if record.get("status") == "unavailable" and record.get("reason") == "input_validation_rejected":
                cleaned[key] = deepcopy(record)
                counts.append(False)
                continue
            symbol = record.get("symbol") or record.get("series_id") or key
            refs = record.get("source_refs")
            if not refs:
                ref = record.get("current_source") or record.get("source_ref") or (references.get(symbol) if isinstance(references, dict) else None)
                refs = [ref] if isinstance(ref, dict) else references if isinstance(references, list) else []
            observed = record.get("observation_date") or record.get("current_month") or record.get("reference_period")
            if isinstance(observed, str) and len(observed) == 7:
                observed += "-01"
            value = record.get("value", record.get("current_value", record.get("level")))
            frequency = record.get("frequency") or ("weekly" if symbol == "GDP_NOW" else "monthly")
            reasons = []
            expected_unit = (BLS_SERIES_BY_ID[symbol].unit if domain == "employment" and symbol in BLS_SERIES_BY_ID
                             else GROWTH_UNITS.get(symbol) if domain == "growth" else None)
            if expected_unit and record.get("unit") != expected_unit:
                reasons.append("invalid_unit")
            # Inflation level indices have an implicit index unit in the feature contract.
            if domain == "inflation" and record.get("unit") not in {None, "", "index", "Index", "index_points"}:
                reasons.append("invalid_unit")
            reasons.extend(_clock_reasons(record, cutoff))
            for source_key in ("current_source", "source_ref"):
                if isinstance(record.get(source_key), dict):
                    reasons.extend(_clock_reasons(record[source_key], cutoff))
            if type(value) not in (int, float) or not finite_tree(record):
                reasons.append("non_finite_or_missing_value")
            if not refs_valid(refs, cutoff):
                reasons.append("unverified_source_lineage")
            if record.get("status") in {"failed", "error", "missing", "unavailable", "stale", "not_published"}:
                reasons.append("source_failed_or_unavailable")
            if not _row_time_valid({"observation_date": observed, "frequency": frequency, "status": "fresh"},
                                   analysis_cutoff=cutoff, trade_date=trade_date):
                reasons.append("stale_or_invalid_observation")
            if reasons:
                reject(path, reasons)
                cleaned[key] = {"symbol": symbol, "status": "unavailable", "reason": "input_validation_rejected"}
                counts.append(False)
            else:
                cleaned[key] = deepcopy(record)
                counts.append(True)
        return cleaned

    for field in fields:
        if field in group:
            result[field] = clean_records(group[field], field)
    usable = any(counts)
    result["status"] = "available" if counts and all(counts) else "partial" if usable else "unavailable"
    if not usable:
        result["reason"] = "no_validated_domain_records"
    if domain == "employment":
        metrics = result.get("metrics") or {}
        # Summaries inherit availability from their precise upstream metric.
        for key, source in (("new_jobs_thousands", "CES0000000001"),
                            ("wage_mom", "CES0500000003"), ("wage_yoy", "CES0500000003")):
            if metrics.get(source, {}).get("status") in {None, "unavailable"}:
                result[key] = None
    return result


def validate_technical_features(data, daily_row, *, cutoff, refs_valid, reject):
    """A current daily close cannot give cached technical features new authority."""
    result = deepcopy(data)
    refs = result.get("source_refs") or []
    day = str(daily_row.get("observation_date") or "")[:10]
    daily_refs = daily_row.get("source_refs", [])
    def same_source(ref):
        return (ref.get("instrument_type", "spot") == "spot"
                and ref.get("symbol", ref.get("ticker", "XAUUSD")) in {"XAUUSD", "XAU/USD", "OANDA:XAUUSD"}
                and any(all(ref.get(key) == daily.get(key) for key in ("source", "source_url", "raw_path"))
                        and all(not ref.get(key) or not daily.get(key) or ref[key] == daily[key]
                                for key in ("sha256", "raw_sha256")) for daily in daily_refs))
    proven = (result.get("as_of") == day and result.get("price") == daily_row.get("value")
              and result.get("unit") in {None, "USD/oz"} and refs_valid(refs, cutoff)
              and not _clock_reasons(result, cutoff) and all(same_source(ref) for ref in refs))
    derived = ("ma20", "ma50", "rsi14", "atr14", "daily_range", "trend", "volatility",
               "key_levels", "technical_levels", "price_structure")
    if not proven:
        if any(result.get(key) is not None for key in derived):
            reject("technical.data.derived", ["unverified_technical_feature_lineage"])
        for key in derived:
            result.pop(key, None)
        result["trend"] = "unavailable"
    else:
        for key, upper in (("ma20", 100000), ("ma50", 100000), ("rsi14", 100),
                           ("atr14", daily_row["value"]), ("daily_range", daily_row["value"])):
            value = result.get(key)
            if value is not None:
                try:
                    valid = type(value) in (int, float) and isfinite(value) and 0 <= value <= upper
                except OverflowError:
                    valid = False
                if not valid:
                    reject("technical.data." + key, ["invalid_technical_numeric_coordinate"])
                    result.pop(key, None)
        for key, allowed in (("trend", {"bullish", "bearish", "neutral", "unavailable"}),
                             ("volatility", {"high", "normal", "low", "unavailable"})):
            if result.get(key) is not None and result[key] not in allowed:
                reject("technical.data." + key, ["invalid_technical_classification"])
                result[key] = "unavailable"
        def valid_levels(levels):
            if not isinstance(levels, list):
                return False
            for level in levels:
                if not isinstance(level, dict):
                    return False
                value = level.get("price")
                try:
                    finite = type(value) in (int, float) and isfinite(value) and 0 < value < 100000
                except OverflowError:
                    finite = False
                evaluated = level.get("evaluation_date") or level.get("as_of") or level.get("date")
                if not finite or evaluated != day:
                    return False
            return True
        if "key_levels" in result and not valid_levels(result["key_levels"]):
            reject("technical.data.key_levels", ["unverified_technical_feature_lineage"])
            result.pop("key_levels", None)
        for key in ("price_structure", "technical_levels"):
            feature = result.get(key)
            if feature is not None and (not isinstance(feature, dict) or feature.get("as_of") != day
                    or not refs_valid(feature.get("source_refs"), cutoff) or _clock_reasons(feature, cutoff)
                    or not all(same_source(ref) for ref in feature.get("source_refs", []))
                    or ("levels" in feature and not valid_levels(feature["levels"]))):
                reject("technical.data." + key, ["unverified_technical_feature_lineage"])
                result.pop(key, None)
    return result
