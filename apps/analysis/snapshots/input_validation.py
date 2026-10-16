"""Pure, fail-closed projection of research evidence; raw archives stay immutable."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any

from apps.features.research.daily import _valid_ref, _build_project_signals, _SPECS
from apps.features.research.workflow import _row_time_valid, build_gold_workflow
from apps.features.research.timeframes import build_execution_timeframe_features
from apps.features.research.tradingview_execution import _usable
from apps.runtime.source_controls import has_news_only_numeric_lineage

SCHEMA_VERSION = "analysis_input_validation.v1"
_BAD = {"failed", "failure", "error", "unavailable", "missing", "blocked", "invalid", "cached", "stale"}
_NUMERIC = {"value", "price", "previous_value", "weekly_anchor_value", "change", "weekly_change", "monthly_change", "monthly_change_pct", "yoy_change"}


def research_enabled(snapshot: dict) -> bool:
    return bool(snapshot.get("daily_research") or (snapshot.get("gold_workflow") or {}).get("schema_version") == "gold_workflow.v2")


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo and parsed.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def _finite(value):
    try:
        return type(value) in (int, float) and isfinite(value)
    except OverflowError:
        return False


def _refs_valid(refs, cutoff):
    return bool(isinstance(refs, list) and refs and all(
        isinstance(ref, dict) and _valid_ref({**ref, "source_url": ref.get("source_url") or ref.get("reference")}, cutoff)
        and not _failed(ref) and not has_news_only_numeric_lineage(ref) for ref in refs))


def _failed(item):
    return any(str(item.get(k, "")).lower() in _BAD for k in
               ("status", "source_status", "collector_status", "collection_status", "freshness_status")) or bool(item.get("error"))


def prepare_analysis_inputs(snapshot: dict, *, storage_root: Path | None = None) -> dict:
    """Return a complete derived snapshot; archives and inputs stay immutable.

    With storage_root, source archives and saved hashes are checked read-only.
    Repeated calls recheck usable evidence and preserve original rejection reasons.
    """
    result = deepcopy(snapshot)
    from database.numeric_source_policy import quarantine_numeric_payload

    for section in ("macro", "technical", "positioning", "options"):
        if section in result:
            result[section] = quarantine_numeric_payload(result[section])
    jin10 = result.get("jin10")
    if isinstance(jin10, dict):
        rejected = bool(jin10.get("numeric_quarantined") or jin10.get("quotes") or jin10.get("klines") or jin10.get("kline_codes"))
        for key in ("quotes", "klines"):
            if key in jin10:
                jin10[key] = {}
        jin10.update(kline_codes=[], numeric_quarantined=rejected, reason="jin10_news_only")
    if "prior_report_contexts" in result:
        from apps.analysis.snapshots.report_continuity import attach_prior_report_contexts

        result = attach_prior_report_contexts(
            result,
            result["prior_report_contexts"],
            storage_root=storage_root,
        )
    if not research_enabled(result):
        def has_rejection(value):
            if isinstance(value, dict):
                return value.get("reason") == "jin10_numeric_source_forbidden" or any(has_rejection(v) for v in value.values())
            return isinstance(value, list) and any(has_rejection(v) for v in value)

        quarantined = any(has_rejection(result.get(key)) for key in ("macro", "technical", "positioning", "options")) or bool((result.get("jin10") or {}).get("numeric_quarantined"))
        result["input_validation"] = {"schema_version": SCHEMA_VERSION, "status": "blocked" if quarantined else "legacy", "can_analyze": not quarantined,
            "reason_codes": ["jin10_numeric_source_forbidden"] if quarantined else [], "domains": {}, "field_rejections": [], "historical_background": [],
            "source_snapshot_id": snapshot.get("snapshot_id"), "run_id": snapshot.get("run_id")}
        return result
    prior = snapshot.get("input_validation") or {}
    def fingerprint(value):
        return sha256(json.dumps({k: v for k, v in value.items() if k != "input_validation"}, sort_keys=True, default=str).encode()).hexdigest()
    original_digest = fingerprint(snapshot)
    bound_digest = prior.get("input_sha256") if prior.get("derived_payload_sha256") == original_digest else original_digest
    rejects = deepcopy(prior.get("field_rejections", []))
    history = deepcopy(prior.get("historical_background", []))
    cutoff = result.get("snapshot_time")
    now = _time(cutoff)
    domains: dict[str, dict] = {}
    from apps.analysis.snapshots.validated_domains import archived_ref_valid, validate_grouped_domain, validate_technical_features
    archive_cache = {}

    def refs_valid(refs, cutoff):
        if not _refs_valid(refs, cutoff):
            return False
        for ref in refs:
            key = (ref.get("raw_path"), ref.get("raw_sha256") or ref.get("sha256"))
            if key not in archive_cache:
                archive_cache[key] = archived_ref_valid(ref, storage_root)
            if not archive_cache[key]:
                return False
        return True

    def reject(path, reasons, item=None):
        entry = {"path": path, "reason_codes": sorted(set(reasons))}
        if entry not in rejects:
            rejects.append(entry)
        if "stale_observation" in reasons and item is not None:
            historical = {"path": path, "scope": "historical_only", "observation": deepcopy(item)}
            if historical not in history:
                history.append(historical)

    research = result.setdefault("daily_research", {})
    safe_rows = []
    for index, row in enumerate(research.get("passport") or []):
        if not isinstance(row, dict):
            reject(f"daily_research.passport[{index}]", ["invalid_shape"])
            continue
        if row.get("lineage_status") == "rejected" and row.get("validation_reasons") and row.get("value") is None:
            safe_rows.append(deepcopy(row))
            reject(f"daily_research.passport[{index}]", row["validation_reasons"])
            continue
        reasons = []
        symbol = row.get("symbol")
        if not _finite(row.get("value")):
            reasons.append("non_finite_or_missing_value")
        if not refs_valid(row.get("source_refs"), cutoff) or row.get("lineage_status", "verified") != "verified":
            reasons.append("unverified_source_lineage")
        if _failed(row) and row.get("status") != "stale":
            reasons.append("source_failed_or_unavailable")
        if not now:
            reasons.append("invalid_cutoff_timezone")
        if not _row_time_valid(row, analysis_cutoff=cutoff, trade_date=result.get("trade_date")):
            reasons.append("stale_observation" if row.get("observation_date") and str(row["observation_date"])[:10] <= str(cutoff)[:10] else "future_or_invalid_observation_time")
        observed_clock = row.get("observation_date")
        if isinstance(observed_clock, str) and "T" in observed_clock and (not _time(observed_clock) or not now or _time(observed_clock) > now):
            reasons.append("future_or_invalid_observation_time")
        components = row.get("components") or []
        if components and any(not isinstance(c, dict) or (c.get("date") or c.get("observation_date")) != str(row.get("observation_date"))[:10]
                              or ("value" in c and not _finite(c["value"])) for c in components):
            reasons.append("component_window_not_verified")
        close = _time(row.get("bar_close_time"))
        if close and any(not _time(ref.get("retrieved_at")) or _time(ref["retrieved_at"]) < close for ref in row.get("source_refs", []) if isinstance(ref, dict)):
            reasons.append("source_retrieved_before_close")
        expected_unit = _SPECS[symbol].unit if symbol in _SPECS else "USD/oz" if symbol in {"XAUUSD_DAILY", "GC_CONTINUOUS"} else None
        if _finite(row.get("value")) and symbol in _SPECS:
            spec = _SPECS[symbol]
            value = row["value"]
            if ((spec.kind in {"rate", "spread"} and not -25 <= value <= 100)
                    or (spec.kind == "balance" and not 0 <= value <= 100000)
                    or (symbol in {"DXY", "BROAD_DOLLAR", "VIX"} and not 0 < value <= 1000)):
                reasons.append("invalid_numeric_coordinate")
        collector_health = ((result.get("macro") or {}).get("data") or {}).get("collector_health") or {}
        source_keys = {"GDP_NOW": "gdp_now", "ISM_MANUFACTURING": "ism_manufacturing", "ISM_SERVICES": "ism_services"}
        if symbol in source_keys and _failed(collector_health.get(source_keys[symbol]) or {}):
            reasons.append("source_failed_or_unavailable")
        if not row.get("unit") or (expected_unit and row["unit"] != expected_unit):
            reasons.append("invalid_unit")
        if symbol == "XAUUSD_DAILY" and (not _finite(row.get("value")) or not 0 < row["value"] < 100000
                or not any((r.get("symbol") or r.get("ticker")) in {"XAUUSD", "XAU/USD", "OANDA:XAUUSD"}
                           and (r.get("instrument_type") == "spot" or "xauusd" in str(r.get("source", "")).lower())
                           for r in row.get("source_refs", []) if isinstance(r, dict))
                or any(str(r.get("instrument_type", "spot")).lower() != "spot" or "GC" in str(r.get("symbol", r.get("ticker", ""))) for r in row.get("source_refs", []) if isinstance(r, dict))):
            reasons.append("invalid_spot_coordinate")
        for key in ("retrieved_at", "release_time", "bar_close_time"):
            if row.get(key) and (not now or not _time(row[key]) or _time(row[key]) > now):
                reasons.append("future_or_invalid_" + key)
        clean = deepcopy(row)
        if reasons:
            reject(f"daily_research.passport[{index}]", reasons, row)
            clean = {k: deepcopy(v) for k, v in row.items() if k in {"symbol", "label", "unit", "frequency", "source_refs", "observation_date"}}
            clean.update(value=None, status="unavailable", lineage_status="rejected", validation_reasons=sorted(set(reasons)))
        else:
            # Comparisons need finite endpoints and matching component windows.
            from apps.analysis.agents.research_input import detailed_comparison
            for weekly, fields in ((False, ("previous_value", "change")), (True, ("weekly_anchor_value", "weekly_change"))):
                if any(clean.get(k) is not None for k in fields):
                    comparison = detailed_comparison(clean, cutoff=cutoff, weekly=weekly)
                    if not comparison["comparison_allowed"]:
                        reject(f"daily_research.passport[{index}].{'weekly' if weekly else 'previous'}", comparison["constraints"])
                        for field in fields:
                            clean[field] = None
            for key in _NUMERIC - {"value"}:
                if clean.get(key) is not None and not _finite(clean[key]):
                    reject(f"daily_research.passport[{index}].{key}", ["non_finite_value"])
                    clean[key] = None
        safe_rows.append(clean)
    research["passport"] = safe_rows
    valid_symbols = {r.get("symbol") for r in safe_rows if r.get("status") == "fresh" and _finite(r.get("value"))}
    domains["macro"] = {"status": "available" if valid_symbols - {"XAUUSD_DAILY"} else "unavailable", "symbols": sorted(valid_symbols)}
    research["project_signals"] = _build_project_signals({r["symbol"]: r for r in safe_rows if r.get("symbol")})
    macro = (result.get("macro") or {}).setdefault("data", {}) if result.get("macro") else {}
    macro["indicators"] = {r["symbol"]: {**deepcopy(r), "date": r.get("observation_date"),
        "daily_change": r.get("change"), "change_1w": r.get("weekly_change")}
        for r in safe_rows if r.get("symbol") in valid_symbols and r.get("symbol") in _SPECS}
    macro["project_signals"] = deepcopy(research["project_signals"])
    # Grouped domains have their own dated records, not all of them in passport.
    for key in ("growth", "employment", "inflation"):
        research[key] = validate_grouped_domain(research.get(key) or macro.get(key), domain=key,
            cutoff=cutoff, trade_date=result.get("trade_date"), refs_valid=refs_valid, reject=reject)
        macro[key] = deepcopy(research[key])
        domains[key] = {"status": research[key]["status"]}

    anchor = research.get("spot_anchor") or {}
    anchor_time = _time(anchor.get("price_time"))
    anchor_ok = bool(now and anchor_time and 0 <= (now - anchor_time).total_seconds() <= 900
        and _finite(anchor.get("price")) and 0 < anchor["price"] < 100000
        and anchor.get("instrument_type") == "spot" and anchor.get("status") in {"available", "fresh", "verified"}
        and refs_valid(anchor.get("source_refs"), cutoff) and not _failed(anchor)
        and all(str(r.get("symbol", "XAUUSD")) in {"XAUUSD", "XAU/USD", "OANDA:XAUUSD"}
                and r.get("instrument_type", "spot") == "spot" for r in anchor.get("source_refs", [])))
    if not anchor_ok:
        reject("daily_research.spot_anchor", ["unverified_current_spot_anchor"])
        research["spot_anchor"] = {"price": None, "status": "unavailable", "source_refs": [], "instrument_type": "spot"}

    raw_frames = (research.get("execution_timeframes") or {}).get("timeframes") or {}
    frames = {}
    for key, item in raw_frames.items():
        reasons = []
        if not isinstance(item, dict):
            reject(f"daily_research.execution_timeframes.{key}", ["invalid_shape"])
            continue
        retrieved = _time(item.get("retrieved_at"))
        if not now or not retrieved or retrieved > now:
            reasons.append("future_or_invalid_retrieval")
        if not refs_valid(item.get("source_refs"), cutoff) or not item.get("raw_path"):
            reasons.append("unverified_source_lineage")
        coordinate = item.get("ticker") or item.get("symbol")
        if coordinate not in {"XAUUSD", "XAU/USD", "OANDA:XAUUSD"} or item.get("instrument_type", "spot") != "spot":
            reasons.append("invalid_spot_coordinate")
        if _failed(item):
            reasons.append("source_failed_or_unavailable")
        if item.get("delay_seconds", 0) != 0 or any(
                ref.get("raw_path") != item.get("raw_path") or (ref.get("symbol") or ref.get("ticker")) not in {None, "XAUUSD", "XAU/USD", "OANDA:XAUUSD"}
                or ref.get("instrument_type", "spot") != "spot"
                for ref in item.get("source_refs", []) if isinstance(ref, dict)):
            reasons.append("source_coordinate_or_archive_mismatch")
        checked = build_execution_timeframe_features({key: item}, analysis_date=result.get("trade_date"))[key]
        seconds = {"15m": 900, "1h": 3600, "4h": 14400, "5m": 300}.get(key, 0)
        if not _usable(checked, now, seconds) or checked.get("rejected_bar_count") or any(
                b[k] <= 0 or b[k] >= 100000 for b in checked.get("bars", []) for k in ("open", "high", "low", "close")):
            reasons.append("invalid_or_stale_completed_bars")
        if reasons:
            reject(f"daily_research.execution_timeframes.{key}", reasons)
        else:
            frames[key] = checked
    research["execution_timeframes"] = {"status": "available" if frames else "unavailable", "timeframes": frames}
    domains["spot"] = {"status": "available" if anchor_ok or frames or "XAUUSD_DAILY" in valid_symbols else "unavailable",
                       "quote_available": anchor_ok, "completed_timeframes": sorted(frames), "daily_available": "XAUUSD_DAILY" in valid_symbols}

    # Remove saved downstream inferences before rebuilding the existing main chain.
    old_workflow = result.get("gold_workflow") or {}
    technical = result.get("technical") or {}
    if isinstance(technical.get("data"), dict):
        if "XAUUSD_DAILY" in valid_symbols:
            daily_row = next(r for r in safe_rows if r.get("symbol") == "XAUUSD_DAILY")
            technical["data"] = validate_technical_features(technical["data"], daily_row,
                cutoff=cutoff, refs_valid=refs_valid, reject=reject)
            for field, source in (("price", "value"), ("daily_change", "change"), ("previous_price", "previous_value"), ("previous_date", "previous_date")):
                technical["data"][field] = daily_row.get(source)
            for key, value in list(technical["data"].items()):
                if type(value) is float and not isfinite(value):
                    reject("technical.data." + key, ["non_finite_value"])
                    technical["data"][key] = None
        technical["data"]["execution_timeframes"] = deepcopy(frames)
        technical["data"]["spot_anchor"] = deepcopy(research["spot_anchor"])
        if "XAUUSD_DAILY" not in valid_symbols:
            technical["data"] = {"status": "unavailable", "execution_timeframes": deepcopy(frames)}
            technical["status"] = "unavailable"
    def invalid_numbers(item):
        if isinstance(item, dict):
            return any(invalid_numbers(v) for v in item.values())
        if isinstance(item, list):
            return any(invalid_numbers(v) for v in item)
        return type(item) is float and not isfinite(item)

    for domain, field in (("options", "options"), ("positioning", "cot_reports")):
        section = result.get(domain) or {}
        data = section.get("data") or {}
        refs = data.get("source_refs") or section.get("source_refs") or []
        source = data.get("data_source") or {}
        if domain == "options" and not refs:
            from apps.features.research.workflow import _cme_refs
            refs = _cme_refs(result, data)
        observed = source.get("report_date") or data.get("as_of") or data.get("trade_date")
        row = {"observation_date": observed, "status": "fresh", "frequency": "weekly" if domain == "positioning" else "daily"}
        ok = bool(data and not _failed(section) and not _failed(data) and not _failed(source) and not invalid_numbers(data) and refs_valid(refs, cutoff)
                  and _row_time_valid(row, analysis_cutoff=cutoff, trade_date=result.get("trade_date")))
        if not ok:
            reject(domain, ["unverified_domain_evidence"])
            result[domain] = {"status": "unavailable", "data": {}, "source_refs": refs}
            research[field] = {"status": "unavailable"}
        domains[domain] = {"status": "available" if ok else "unavailable"}
    # Supplemental collector failures cannot inherit authority from cached numbers.
    def sanitize(item, path):
        if isinstance(item, list):
            return [sanitize(v, f"{path}[{i}]") for i, v in enumerate(item)]
        if not isinstance(item, dict):
            return None if isinstance(item, float) and not isfinite(item) else item
        if item.get("reason") == "input_validation_rejected" and item.get("status") == "unavailable":
            return deepcopy(item)
        if _failed(item):
            reject(path, ["source_failed_or_unavailable"])
            return {"status": "unavailable", "reason": "input_validation_rejected", "source_refs": deepcopy(item.get("source_refs", []))}
        return {k: sanitize(v, path + "." + k) for k, v in item.items()}
    for key in ("public_evidence", "supplemental_sources", "official_etf", "tradingview", "tradingview_series", "cross_asset"):
        if key in research:
            research[key] = sanitize(research[key], "daily_research." + key)
    # Validate supplemental numeric leaves with their own saved frequency/clock.
    def checked_evidence(item, path, inherited_refs=None, inherited_time=None):
        if isinstance(item, list):
            return [checked_evidence(v, f"{path}[{i}]", inherited_refs, inherited_time) for i, v in enumerate(item)]
        if not isinstance(item, dict):
            if type(item) is float and not isfinite(item):
                reject(path, ["non_finite_value"])
                return None
            return item
        if item.get("reason") == "input_validation_rejected" and item.get("status") == "unavailable":
            return deepcopy(item)
        refs = item.get("source_refs") or ([item["source_ref"]] if isinstance(item.get("source_ref"), dict) else inherited_refs)
        observed = item.get("observation_date") or item.get("date") or item.get("as_of") or inherited_time
        reasons = []
        health = item.get("source_health")
        if _failed(item) or (isinstance(health, dict) and _failed(health)) or str(health or "").lower() in _BAD:
            reasons.append("source_failed_or_unavailable")
        for key in ("retrieved_at", "last_updated", "published_at", "release_time", "provider_bar_time", "minute_bar_time"):
            if item.get(key) and (not now or not _time(item[key]) or _time(item[key]) > now):
                reasons.append("future_or_invalid_" + key)
        if "value" in item or "price" in item:
            if not refs_valid(refs, cutoff):
                reasons.append("unverified_source_lineage")
            for key in ("value", "price"):
                if key in item and not _finite(item[key]):
                    reasons.append("non_finite_value")
            if not item.get("unit") and "value" in item:
                reasons.append("invalid_unit")
            frequency = item.get("frequency", "daily")
            row = {**item, "observation_date": observed, "frequency": frequency, "status": "fresh"}
            if not _row_time_valid(row, analysis_cutoff=cutoff, trade_date=result.get("trade_date")):
                reasons.append("stale_or_invalid_observation")
        if reasons:
            reject(path, reasons)
            return {"status": "unavailable", "reason": "input_validation_rejected", "source_refs": deepcopy(refs or [])}
        return {k: deepcopy(v) if k in {"source_refs", "source_ref", "collector_health"} else checked_evidence(v, path + "." + k, refs, observed) for k, v in item.items()}
    for key in ("official_etf", "cot_reports", "supplemental_sources", "public_evidence"):
        if key in research:
            research[key] = checked_evidence(research[key], "daily_research." + key)
    for key in ("fedwatch", "official_etf", "cot_reports", "policy_distribution", "policy_target_reference", "fed_sep"):
        if key in macro:
            macro[key] = checked_evidence(macro[key], "macro.data." + key)
    if "tradingview_cross_asset" in result:
        cross = deepcopy(result["tradingview_cross_asset"])
        safe_observations = []
        for i, row in enumerate(cross.get("observations") or []):
            checked = checked_evidence(row, f"tradingview_cross_asset.observations[{i}]")
            if checked.get("status") != "unavailable":
                safe_observations.append(checked)
        cross["observations"] = safe_observations
        cross.pop("chart_windows", None)  # supplied derived windows cannot bypass chart validation
        series = []
        from apps.features.research.chart_windows import build_chart_windows
        for i, row in enumerate(cross.get("chart_series") or []):
            if refs_valid(row.get("source_refs"), cutoff) and not _failed(row):
                health = build_chart_windows([row], as_of=cutoff)["series_health"][0]
                if health["status"] == "AVAILABLE":
                    series.append(row)
                    continue
            reject(f"tradingview_cross_asset.chart_series[{i}]", ["unverified_chart_series"])
        cross["chart_series"] = series
        result["tradingview_cross_asset"] = cross
    for key in ("adaptive_research", "mainstream_news"):
        if key in result:
            result[key] = checked_evidence(result[key], key)
    workflow = build_gold_workflow(result) if now else {"schema_version": "gold_workflow.v2", "status": "blocked"}
    if now and (old_workflow.get("production_shadow") or old_workflow.get("macro_causal")):
        from apps.features.research.production_shadow import apply_production_shadow_features
        workflow = apply_production_shadow_features(result, workflow)
    if "reader_report_version" not in old_workflow and not old_workflow.get("production_shadow"):
        workflow.pop("reader_report_version", None)
        workflow.pop("production_shadow", None)
    for key in ("reader_report_version", "reader_presentation", "production_shadow", "state_record"):
        if key in old_workflow:
            workflow[key] = deepcopy(old_workflow[key])
    predecessor = old_workflow.get("previous_research") or {}
    if (predecessor.get("status") == "verified" and predecessor.get("snapshot_id")
            == (result.get("input_snapshot_ids") or {}).get("previous_research")):
        workflow["previous_research"] = deepcopy(predecessor)
        delta = deepcopy(old_workflow.get("delta_vs_previous") or {})
        from apps.features.research.workflow import report_comparison_rows
        current_rows = {r.get("symbol"): r for r in safe_rows if r.get("symbol")}
        current_rows.update(report_comparison_rows(research, as_of=cutoff))
        for row in delta.get("rows") or []:
            current = current_rows.get(row.get("symbol")) or {}
            if (not _finite(current.get("value")) or row.get("current") != current.get("value")
                    or row.get("current_date") != current.get("observation_date")):
                row.update(current=None, delta=None, change_kind="input_validation_rejected")
        workflow["delta_vs_previous"] = delta
        if domains["spot"]["status"] == "available":
            workflow["previous_pa_zones"] = deepcopy(old_workflow.get("previous_pa_zones") or [])
    if old_workflow.get("state_record") and isinstance(workflow.get("state"), dict):
        # Accepted authority is independent of rejected new observations.
        for key in ("accepted_state", "previous_state", "accepted_at", "predecessor_id"):
            if key in old_workflow["state_record"]:
                workflow["state"][key] = deepcopy(old_workflow["state_record"][key])
    result["gold_workflow"] = workflow
    can_analyze = domains["spot"]["status"] == "available"
    reasons = sorted({r for entry in rejects for r in entry["reason_codes"]} | (set() if can_analyze else {"no_trusted_current_spot_observation"}))
    digest = bound_digest
    result["input_validation"] = {"schema_version": SCHEMA_VERSION, "status": "partial" if can_analyze and rejects else "valid" if can_analyze else "blocked",
        "can_analyze": can_analyze, "reason_codes": reasons, "domains": domains, "field_rejections": rejects,
        "historical_background": history, "source_snapshot_id": snapshot.get("snapshot_id"), "run_id": snapshot.get("run_id"),
        "input_sha256": digest, "cutoff": cutoff, "derived_snapshot_id": f"{snapshot.get('snapshot_id', 'unknown')}:validated:{digest[:16]}"}
    if not can_analyze:
        result["status"] = "blocked"
        for key in ("scenario_engine", "scenario_display", "execution"):
            result["gold_workflow"][key] = {"status": "blocked", "reason": "no_trusted_current_spot_observation"}
    result["input_validation"]["derived_payload_sha256"] = fingerprint(result)
    return result


def research_report_rejection_reasons(snapshot: dict, coordinator: Any) -> list[str]:
    """Independent generation contract, shared by renderer and registry."""
    payload = coordinator.get("input_payload") if isinstance(coordinator, dict) else getattr(coordinator, "input_payload", None)
    if not research_enabled(snapshot) and not (payload or {}).get("research_synthesis"):
        return []
    reasons = []
    validation = prepare_analysis_inputs(snapshot).get("input_validation", {})
    if not validation.get("can_analyze"):
        reasons.append("input_validation_blocked")
    synthesis = ((coordinator.get("input_payload") if isinstance(coordinator, dict) else getattr(coordinator, "input_payload", None)) or {}).get("research_synthesis") or {}
    if synthesis.get("generation_status", synthesis.get("status")) != "success" or synthesis.get("generated_by") != "llm":
        reasons.append("research_generation_failed")
    quality_required = (snapshot.get('gold_workflow', {}).get('reader_report_version') == 'gold_reader.v4'
                        or 'research_quality_standard' in synthesis or bool(synthesis.get('quality_gate_version')))
    if quality_required and (synthesis.get('quality_eligible') is not True
                             or synthesis.get('review_status') != 'pass'
                             or synthesis.get('status') != 'success'):
        reasons.append('research_quality_not_eligible')
    binding = synthesis.get("input_validation") or {}
    if binding.get("input_sha256") != validation.get("input_sha256"):
        reasons.append("research_input_binding_missing_or_mismatched")
    analysis = synthesis.get("analysis") or {}
    if not isinstance(analysis, dict) or not analysis.get("dominant_factor") or not synthesis.get("evidence_ids"):
        reasons.append("research_body_contract_missing")
    if snapshot.get("gold_workflow", {}).get("reader_report_version") == "gold_reader.v4":
        from apps.analysis.agents.research_synthesis import validate_report_sections
        try:
            validate_report_sections(analysis.get("report_sections"), allowed_ids=set(synthesis.get("evidence_catalog_ids") or []))
        except (ValueError, TypeError, KeyError):
            reasons.append("research_body_contract_invalid")
        if snapshot.get("gold_workflow", {}).get("reader_presentation") == "gold_reader.research.v1":
            if not isinstance(analysis.get("reader_narrative"), str) or not analysis["reader_narrative"].strip():
                reasons.append("research_reader_narrative_missing")
    review = synthesis.get("macro_review") or {}
    if ((quality_required or snapshot.get("gold_workflow", {}).get("macro_causal")) and review.get("status") != "pass") or review.get("status") in {"needs_revision", "failed", "unavailable", "blocked"}:
        reasons.append("research_review_not_accepted")
    return sorted(set(reasons))
