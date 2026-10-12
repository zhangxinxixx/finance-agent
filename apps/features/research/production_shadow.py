"""Opt-in v0.9 projection; existing frozen v2 snapshots retain their rendering."""

from copy import deepcopy

from apps.features.research.levels import apply_session_confidence
from apps.features.research.scenario_display import build_scenario_display
from apps.features.research.sessions import build_session_quality
from apps.features.research.source_health import build_core_source_health
from apps.features.research.zones import build_execution_zones


def apply_production_shadow_features(snapshot, flow):
    result = deepcopy(flow)
    from apps.features.research.macro_causal import build_macro_causal
    result["macro_causal"] = build_macro_causal(snapshot)
    from apps.features.research.energy import build_energy_channels

    result['energy_channels'] = build_energy_channels(snapshot)
    if snapshot.get('tradingview_cross_asset'):
        from apps.features.research.cross_asset import build_cross_asset_features
        cross = build_cross_asset_features(snapshot['tradingview_cross_asset'], as_of=snapshot['snapshot_time'])
        result['cross_asset_freshness'] = cross
        result['energy_channels']['tradingview_intraday'] = [r for r in cross['observations'] if r['symbol'] in {'BRENT', 'WTI'}]
        result['energy_channels']['analysis_capability'] = cross['analysis_capability']['energy_regime_analysis']
        result['energy_channels']['window_comparison_capability'] = cross['analysis_capability'].get('energy_window_comparison', 'UNAVAILABLE')
        result['energy_channels']['aligned_windows'] = [w for w in cross.get('chart_windows', {}).get('windows', []) if w.get('group') == 'energy']
        passed = not cross['critical_freshness_failures']
        result['quality_gate']['checks'].append({'id': 'Q12', 'name': '跨资产盘中时效', 'passed': passed,
            'reason': ', '.join(cross['critical_freshness_failures']) or '能源分钟bar时钟与延迟符合研究要求'})
        if cross['overall_quality'] == 'Partial':
            result['quality_gate'].update(data_quality='Partial', strong_direction_allowed=False)
            result['state']['strong_direction_allowed'] = False
    result['reader_report_version'] = 'gold_reader.v3'
    technical = snapshot.get("technical", {}).get("data", {})
    daily_date = technical.get("as_of") or result["price_anchor"].get("daily_close_date")
    daily_session = build_session_quality({**snapshot, "trade_date": daily_date})
    daily_session["session_type"] = daily_session["session_class"]
    report_session = build_session_quality(snapshot)
    report_session["session_type"] = report_session["session_class"]
    result["price_anchor"]["session_quality"] = daily_session
    result["report_session_quality"] = report_session
    result["key_levels"] = apply_session_confidence(result["key_levels"], daily_session)
    result["execution_zones"] = build_execution_zones(snapshot, result["key_levels"], session_quality=daily_session)
    result["scenario_display"] = build_scenario_display(result["scenario_engine"])
    health = build_core_source_health(snapshot)
    result["core_source_health"] = health
    result["quality_gate"]["checks"].append({"id": "Q11", "name": "核心采集健康 SLA", "passed": health["production_ready"], "reason": "；".join(x["source_key"]+": "+x["reason"] for x in health["alerts"]) or "官方已发布值与本地最新值、采集探测时间已核对"})
    if not health["production_ready"]:
        result["quality_gate"].update(data_quality="Partial", strong_direction_allowed=False)
        result["state"]["strong_direction_allowed"] = False
    result["production_shadow"] = {"schema_version": "production_shadow.v1", "product": "Gold Research Agent v0.9 — Production Shadow", "automatic_acceptance": False, "automatic_trading_allowed": False}
    result["source_refs"].extend(daily_session.get("source_refs", []))
    # Numerical observations stay exact in the engine; user-facing paths use
    # precomputed, volatility-dependent spot zones, never futures strikes.
    zones = {x["price"]: x for x in result["execution_zones"].get("zones", []) if x.get("zone_status") == "available"}
    for item in result["scenario_display"]["scenarios"]:
        for key in ("trigger", "price_path", "invalidation"):
            text = item.get(key, "")
            for price, zone in sorted(zones.items(), key=lambda x: len(f"{x[0]:g}"), reverse=True):
                import re
                label = zone.get("display_label")
                if label:
                    text = re.sub(r"(?<![\d.])"+re.escape(f"{price:g}")+r"(?![\d.])",label,text)
            item[key] = text
    from apps.features.research.price_action import build_price_action, gate_execution_frames
    result['price_action'] = build_price_action(snapshot, previous_zones=result.get('previous_pa_zones', []),
        previous_time=result.get('previous_research', {}).get('snapshot_time'))
    ex = result['execution']
    ex.update(timeframes=['4H', '1H', '15m'], primary='15m', trigger=None,
              unimplemented_patterns=['second_entry', 'wedge', 'volume_confirmation'],
              flat='空仓：先检查4H/1H结构，再观察15m区间突破、收复及回测；无PA确认则保持观察。')
    ex['timeframe_features'] = [r for r in ex.get('timeframe_features', []) if r['timeframe'] != '5m']
    ex['status'] = 'available' if all(r.get('status') == 'available' for r in result['price_action']['timeframes'].values()) else 'partial'
    ex['reason'] = '本轮只分析4H、1H和15m；确认摆动需等待右侧两根收盘，PA事件与原短窗突破代理分列。'
    result['execution'] = gate_execution_frames(ex, result['price_action'])
    return result
