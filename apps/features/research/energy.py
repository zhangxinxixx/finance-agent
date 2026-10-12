"""Dated energy evidence; no causal votes or invented futures crack spreads."""

from math import isfinite


def build_energy_channels(snapshot):
    rows = {r['symbol']: r for r in snapshot.get('daily_research', {}).get('passport', [])}
    spreads = []
    crude = rows.get('WTI_SPOT', {})
    for symbol in ('DIESEL_GULF_SPOT', 'GASOLINE_GULF_SPOT'):
        product = rows.get(symbol, {})
        values = (product.get('value'), crude.get('value'))
        valid = (all(isinstance(x, (int, float)) and not isinstance(x, bool) and isfinite(x) for x in values)
                 and product.get('unit') == 'USD/gal' and crude.get('unit') == 'USD/bbl'
                 and product.get('observation_date') is not None
                 and product.get('observation_date') == crude.get('observation_date')
                 and all(r.get('lineage_status') == 'verified' and r.get('source_refs') for r in (product, crude)))
        fresh = valid and all(r.get('status') == 'fresh' for r in (product, crude))
        spreads.append({'product': symbol, 'value': round(values[0] * 42 - values[1], 4) if valid else None,
                        'unit': 'USD/bbl', 'observation_date': product.get('observation_date'),
                        'status': 'fresh' if fresh else 'historical_only' if valid else 'unavailable',
                        'method': 'US_Gulf_product_spot_USD_per_gallon_x42_minus_Cushing_WTI_spot',
                        'label': '跨地区现货产品价差代理；非期货裂解价差、非炼厂利润',
                        'source_refs': product.get('source_refs', []) + crude.get('source_refs', [])})
    return {'schema_version': 'gold_energy_channels.v1', 'spot_product_spreads': spreads,
            'observations': [rows[s] for s in ('BRENT_SPOT', 'WTI_SPOT', 'BRENT_FUTURES_PROXY', 'WTI_FUTURES_PROXY', 'DIESEL_GULF_SPOT', 'GASOLINE_GULF_SPOT') if s in rows],
            'unavailable': ['dated_futures_diesel_crack', 'dated_futures_gasoline_crack', 'SPR_official_latest', 'verified_shipping_flow'],
            'channel_tests': {
                'safe_haven': '核验事件发生及传播时点、黄金/风险资产/美元同窗口变化；仅有新闻或金价上涨不能确认因果。',
                'inflation_rates': '核验油价→成品油→通胀预期→2Y/实际利率的实际反应；油价上涨不保证实际利率上升。',
                'liquidation': '信用与融资价格若同步恶化，现金需求可能使黄金先被抛售；风险厌恶并不保证金价上涨。',
                'deescalation': '冲突缓和可能先消退避险溢价，再因实际利率下降支持黄金；需后续反应验证。'},
            'dominant_channel': 'requires_model_assessment_with_aligned_evidence', 'independent_direction_vote': False}
