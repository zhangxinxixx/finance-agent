"""Core-source freshness SLA, separate from market-direction Quality Gate."""

from copy import deepcopy
from datetime import UTC, datetime

VERSION = "gold_core_source_health.v1"


def _time(value):
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def build_core_source_health(snapshot):
    macro = snapshot.get("macro", {}).get("data", {})
    growth = macro.get("growth", {})
    raw = macro.get("collector_health") or growth.get("collector_health", {})
    now = _time(snapshot.get("snapshot_time"))
    items = []
    for name in ("gdp_now", "ism_manufacturing", "ism_services", "fedwatch"):
        item = deepcopy(raw.get(name) or {})
        item.update(source_key=name)
        for key in ("expected_release_time", "actual_latest_date", "official_latest_date"):
            item.setdefault(key, None)
        item.setdefault("collector_status", "not_configured" if name == "fedwatch" else "not_connected")
        item.setdefault("staleness", "unknown")
        item.setdefault("expected_freshness", "intraday_15min" if name == "fedwatch" else "official_update_checked_each_run" if name == "gdp_now" else "monthly_release_checked_each_run")
        actual, official = str(item.get("actual_latest_date") or ""), str(item.get("official_latest_date") or "")
        expected, fetched = _time(item.get("expected_release_time")), _time(item.get("retrieved_at"))
        failed = item["collector_status"] not in {"success", "available"}
        reason = item.get("reason")
        status = "FAILED" if failed else "HEALTHY"
        if official and (not actual or actual < official):
            status, reason = "FAILED", "official_published_data_newer_than_local"
            item["staleness"] = "collector_stale"
        elif item.get("staleness") in {"stale", "local_old_value", "future"}:
            status, reason = "FAILED", "latest_observation_not_current"
        elif item["collector_status"] == "not_published" and expected and now and now < expected:
            status, reason = "WAITING_RELEASE", "release_not_due_yet"
        elif item["collector_status"] == "not_published" and (not expected or not now):
            status, reason = "UNKNOWN", "release_schedule_unverified"
        elif item["collector_status"] == "not_published":
            status, reason = "FAILED", "expected_release_due_but_collector_has_no_value"
        elif not failed and (not actual or not official):
            status, reason = "UNKNOWN", "official_latest_observation_unverified"
        if status == "HEALTHY" and (not fetched or not now or not 0 <= (now-fetched).total_seconds() <= 86400):
            status, reason = "FAILED", "source_health_probe_stale_or_future"
        if name == "fedwatch":
            item.setdefault("source_url", "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html")
            normalized = macro.get("fedwatch", {}).get("source_health")
            if normalized:
                item.update(deepcopy(normalized), configured=True, source_key="fedwatch")
                observed = _time(normalized.get("last_updated"))
                age = (now - observed).total_seconds() if now and observed else None
                fresh = (normalized.get("status") == "fresh" and age is not None
                         and 0 <= age <= normalized.get("allowed_staleness_seconds", 3600))
                status = "HEALTHY" if fresh else "FAILED"
                reason = "fedwatch_source_observation_fresh" if fresh else normalized.get("reason") or "fedwatch_not_fresh"
                effective_status = "stale" if not fresh and normalized.get("status") == "fresh" else normalized.get("status")
                item.update(actual_latest_date=normalized.get("last_updated"),
                            collector_status="success" if fresh else effective_status,
                            freshness_seconds=age, expected_freshness="configured_source_timestamp_SLA",
                            status="fresh" if fresh else effective_status,
                            actionable=fresh, staleness="fresh" if fresh else effective_status)
            elif not item.get("configured"):
                status, reason = "FAILED", "fedwatch_collector_not_configured; gold_options_odds_are_not_FedWatch"
            elif not fetched or not now or not 0 <= (now-fetched).total_seconds() <= 900:
                status, reason = "FAILED", "fedwatch_intraday_SLA_exceeded"
        item.update(source_health=status, reason=reason or "official_and_local_latest_match", alert_required=status in {"FAILED", "UNKNOWN"})
        items.append(item)
    if snapshot.get('tradingview_cross_asset'):
        from apps.features.research.cross_asset import build_cross_asset_features
        cross = build_cross_asset_features(snapshot['tradingview_cross_asset'], as_of=snapshot['snapshot_time'])
        chart_rows = {r['ticker']: r for r in cross.get('chart_windows', {}).get('series_health', [])}
        usable_tickers = {r['ticker'] for window in cross.get('chart_windows', {}).get('windows', [])
                          if window.get('aligned_comparison_allowed') for r in window.get('changes', [])}
        for row in cross['observations']:
            expected_closed = row['freshness'] in {'MARKET_CLOSED', 'EXPECTED_STALE'}
            chart_usable = row['ticker'] in usable_tickers
            chart = chart_rows.get(row['ticker'], {}) if chart_usable else {}
            healthy = row['intraday_confirmation_allowed'] or expected_closed or chart_usable
            items.append({'source_key': 'tv_' + row['symbol'].lower(), 'source_type': 'secondary_market_data',
                          'access_method': 'tradingview_scanner_and_chart' if chart_usable else 'tradingview_scanner', 'ticker': row['ticker'],
                          'source_url': 'https://www.tradingview.com/chart/' if chart_usable else 'https://scanner.tradingview.com/global/scan',
                          'actual_latest_date': chart.get('last_completed_bar_end') or row.get('minute_bar_time'), 'official_latest_date': None,
                          'expected_release_time': None, 'expected_freshness': 'completed_aligned_chart_window; realtime_separate' if chart_usable else 'minute_bar_age_15min; quote_clock_separate',
                          'retrieved_at': chart.get('retrieved_at') or row.get('retrieved_at'), 'delay_seconds': chart.get('delay_seconds', row.get('delay_seconds')),
                          'raw_path': next((r.get('raw_path') for r in chart.get('source_refs', row.get('source_refs', [])) if r.get('raw_path')), None),
                          'collector_status': 'success' if row['status'] == 'available' or chart_usable else row['status'],
                          'staleness': row['freshness'], 'source_health': 'EXPECTED_STALE' if expected_closed else 'HEALTHY' if healthy else 'FAILED',
                          'reason': 'ALIGNED_HISTORICAL_CHART_WINDOW; realtime_gate_separate' if chart_usable else row['freshness'], 'alert_required': not healthy,
                          'realtime_confirmation_available': row['intraday_confirmation_allowed'],
                          'aligned_window_available': chart_usable,
                          'critical_freshness_failure': 'ENERGY_INTRADAY' if row['symbol'] in {'WTI', 'BRENT'} and not healthy else None})
    return {"schema_version": VERSION, "as_of": snapshot.get("snapshot_time"), "items": items,
            "overall_status": "FAILED" if any(x["source_health"] == "FAILED" for x in items) else "UNKNOWN" if any(x["source_health"] == "UNKNOWN" for x in items) else "HEALTHY",
            "production_ready": all(x["source_health"] in {"HEALTHY", "WAITING_RELEASE", "EXPECTED_STALE"} for x in items),
            "alerts": [{"source_key": x["source_key"], "severity": "error", "reason": x["reason"]} for x in items if x["alert_required"]]}
