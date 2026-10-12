from copy import deepcopy

from apps.analysis.agents.research_input import _share_policy_records, encode, pack_evidence


def restore_policy(projected):
    records = projected['shared_policy_records']

    def restore(value):
        if isinstance(value, list):
            return [restore(item) for item in value]
        if not isinstance(value, dict):
            return value
        if set(value) == {'policy_ref'}:
            return restore(records[value['policy_ref']])
        if set(value) in ({'policy_columns_table'}, {'policy_mapping_table'}):
            mapping = 'policy_mapping_table' in value
            table = restore(value['policy_mapping_table' if mapping else 'policy_columns_table'])
            vectors = []
            for vector in table['column_values']:
                if isinstance(vector, dict) and 'value_runs' in vector:
                    vector = [cell for cell, count in vector['value_runs'] for _ in range(count)]
                vectors.append(vector)
            rows = [
                {column: vectors[j][i] for j, column in enumerate(table['columns'])
                 if j not in table.get('missing_by_row', {}).get(str(i), [])}
                for i in range(len(vectors[0]))
            ]
            return dict(zip(table['keys'], rows)) if mapping else rows
        return {key: restore(child) for key, child in value.items()}

    return restore({key: value for key, value in projected.items()
                    if key not in {'shared_policy_records', 'policy_projection'}})


def test_policy_projection_preserves_distributions_types_missing_and_sources():
    meetings = []
    for month in range(1, 11):
        bins = [{'target_bps': i * 25, 'probability': 0.0, 'source_ids': ['s0']}
                for i in range(80)]
        bins[20]['probability'] = 0.32
        bins[21]['probability'] = 0.68
        bins[0].update(qualification=None, observed=False)
        bins[1].update(observed=0)
        bins[2].update(observed=0.0)
        meetings.append({'date': f'2027-{month:02d}-01', 'distribution': bins,
                         'status': 'available', 'source_ids': ['s0', 's1']})
    policy = {'meetings': meetings, 'path': {'meetings': deepcopy(meetings)},
              'next_meeting': meetings[0], 'history': deepcopy(meetings)}
    policy['history'][0]['distribution'][20]['probability'] = 0.31
    original = deepcopy(policy)
    projected = _share_policy_records(policy)
    assert policy == original
    assert encode(restore_policy(projected)) == encode(original)
    assert len(encode(projected)) < len(encode(policy)) / 3


def test_policy_projection_round_trips_empty_and_sparse_records():
    for policy in ({}, {'meetings': [{}, {}, {}]},
                   {'meetings': [{'rate': None}, {}, {'rate': 0}]}):
        assert restore_policy(_share_policy_records(policy)) == policy


def test_keyed_comparisons_retain_keys_dates_and_distinct_qualifications():
    comparisons = {
        key: {'observed_at': f'2026-09-{i + 1:02d}T00:00:00Z',
              'qualification': 'Historical comparison only, not a forecast. ' * 20,
              'delta_bp': i * 0.1, 'probability': None if i == 1 else 0.0}
        for i, key in enumerate(('1d', '1w', '1m'))
    }
    comparisons['1d']['extra'] = None
    policy = {'comparisons': comparisons}
    before = deepcopy(policy)
    compact = _share_policy_records(policy)
    assert 'policy_mapping_table' in encode(compact)
    assert encode(restore_policy(compact)) == encode(before)
    assert policy == before
    assert len(encode(compact)) < len(encode(policy))


def test_policy_projection_keeps_packed_source_ids_resolvable():
    policy = {'meetings': [
        {'date': f'2027-0{i}-01', 'source_refs': [
            {'source': 'cme_fedwatch', 'source_url': 'https://www.cmegroup.com/fedwatch',
             'observed_at': '2026-09-28T10:00:00Z'}],
         'qualification': 'Source-labeled probabilities; not a forecast. ' * 8}
        for i in range(1, 4)
    ]}
    original = pack_evidence({'policy': policy}, stage='test')
    packed = pack_evidence({'policy': policy}, stage='test',
                           packed_projection=lambda p: p.update(policy=_share_policy_records(p['policy'])))
    restored = restore_policy(packed['policy'])
    assert restored == original['policy']
    assert packed['source_catalog'] == original['source_catalog']
    assert packed['url_catalog'] == original['url_catalog']
    assert all(source in packed['source_catalog'] for meeting in restored['meetings']
               for source in meeting['source_ids'])
