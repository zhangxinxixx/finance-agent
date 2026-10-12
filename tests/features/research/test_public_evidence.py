from apps.features.research.public_evidence import build_public_evidence_features
from apps.features.research.flows import build_flow_diagnostics


def test_dated_pairs_are_calculated_but_future_or_unreferenced_rows_are_excluded():
    def row(date, value, unit='thousand_barrels'):
        return {'symbol': 'EIA_SPR', 'value': value, 'unit': unit, 'observation_date': date, 'source_refs': [{'source': 'EIA'}]}
    result = build_public_evidence_features([{'key': 'EIA_STOCKS', 'status': 'available',
        'observations': [row('2026-08-28', 286604), row('2026-09-04', 285360), row('2026-09-18', 100)]}],
        as_of='2026-09-15T00:00:00+00:00')
    series = result['EIA_STOCKS']['series']['EIA_SPR']
    assert series['delta'] == -1244
    assert series['current']['observation_date'] == '2026-09-04'
    assert series['previous']['observation_date'] == '2026-08-28'


def test_collected_iau_level_replaces_not_collected_status_without_creating_flow():
    supplemental = build_public_evidence_features([{'key': 'IAU', 'status': 'available',
        'source_refs': [{'source': 'ishares'}],
        'observations': [{'symbol': 'IAU_SHARES', 'value': 791100000, 'unit': 'shares',
                          'observation_date': '2026-09-14', 'source_refs': [{'source': 'ishares'}]}]}],
        as_of='2026-09-15T00:00:00+00:00')
    result = build_flow_diagnostics({'snapshot_time': '2026-09-15T00:00:00+00:00',
                                     'daily_research': {'supplemental_sources': supplemental}})
    iau = result['etf']['auxiliary']['IAU']
    assert iau['status'] == 'available'
    assert iau['series']['IAU_SHARES']['delta'] is None
    assert 'no verified subscription flow' in iau['interpretation']
