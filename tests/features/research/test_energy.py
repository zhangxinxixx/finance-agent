from apps.features.research.energy import build_energy_channels


def test_spot_proxy_requires_same_date_units_and_lineage():
    rows = [dict(symbol='DIESEL_GULF_SPOT', value=4, unit='USD/gal'), dict(symbol='WTI_SPOT', value=90, unit='USD/bbl')]
    for r in rows:
        r.update(observation_date='2026-09-09', status='fresh', lineage_status='verified', source_refs=[{'raw_path': 'fixture'}])
    snapshot = {'daily_research': {'passport': rows}}
    def spread():
        return build_energy_channels(snapshot)['spot_product_spreads'][0]
    assert spread()['value'] == 78
    rows[0]['status'] = 'stale'
    assert spread()['status'] == 'historical_only'
    rows[0]['observation_date'] = '2026-09-08'
    assert spread()['value'] is None
    rows[0]['observation_date'] = '2026-09-09'
    rows[0]['unit'] = 'USD/bbl'
    assert spread()['value'] is None
