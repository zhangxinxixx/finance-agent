from copy import deepcopy

import pytest

from apps.analysis.agents.research_input import (
    _encode_column_runs, _project_packed_tables, _rows_table, encode,
)


def restore_table(table):
    if 'rows' in table:
        rows = table['rows']
    else:
        vectors = []
        for vector in table['column_values']:
            if isinstance(vector, dict):
                vector = [cell for cell, count in vector['value_runs'] for _ in range(count)]
            vectors.append(vector)
        rows = list(zip(*vectors))
    return [{**deepcopy(table.get('shared_fields', {})),
             **{name: row[i] for i, name in enumerate(table['columns'])
                if i not in table.get('missing_by_row', {}).get(str(index), [])}}
            for index, row in enumerate(rows)]


def test_column_runs_preserve_types_missing_values_and_order():
    rows = [{'horizon': '15m', 'reason': 'Unavailable source clock. ' * 15,
             'value': value} for value in [None, False, 0, 0.0] * 20]
    rows[2].pop('value')
    original = deepcopy(rows)
    table = _rows_table(rows)
    assert _encode_column_runs(table)
    assert encode(restore_table(table)) == encode(original)
    assert rows == original
    assert not _encode_column_runs(table)  # Already encoded; no destructive second pass.


@pytest.mark.parametrize('field', ['history', 'adaptive_research'])
def test_planner_and_synthesis_project_all_horizons_losslessly(field):
    matrix_rows = []
    for index in range(60):
        matrix_rows.append({'horizon': f'h{index}', 'status': 'available' if index % 3 else 'unavailable',
                            'reason': ('Source timestamps are not aligned. ' * 8) if index < 30 else None,
                            'changes': [{'symbol': 'XAUUSD', 'change_pct': None if index % 3 == 0 else 1.25}]})
    record = {'market_observations': [{'symbol': 'XAUUSD', 'value': 4200}],
              'market_windows': [{'series_health': [], 'windows': [],
                                  'multi_horizon': {'rows': matrix_rows}}]}
    payload = {field: deepcopy(record)}
    original = deepcopy(payload)
    _project_packed_tables(payload)
    result = payload[field]
    assert restore_table(result['market_observations_table']) == record['market_observations']
    matrix = result['market_windows'][0]['multi_horizon']
    assert 'column_values' in matrix['rows_table']
    restored = restore_table(matrix['rows_table'])
    for row in restored:
        row['changes'] = []
    for change in restore_table(matrix['changes_table']):
        index = change.pop('row_index')
        restored[index]['changes'].append(change)
    assert restored == matrix_rows
    assert len(encode(payload)) < len(encode(original)) / 2


def test_small_tables_keep_the_existing_row_encoding():
    table = _rows_table([{'value': 1}, {'value': 2}])
    original = deepcopy(table)
    assert not _encode_column_runs(table)
    assert table == original


def test_large_evidence_uses_column_runs_without_dropping_source_health():
    rows = [{'source_key': str(index), 'source_health': 'degraded',
             'reason': ('clock unavailable; ' if index < 8 else 'source unavailable; ') * 30}
            for index in range(16)]
    payload = {'analytical_text': 'x' * 160001,
               'gold_workflow': {'core_source_health': {'items': deepcopy(rows)}}}
    _project_packed_tables(payload)
    table = payload['gold_workflow']['core_source_health']['items_table']
    assert 'column_values' in table
    assert restore_table(table) == rows
    assert payload['analytical_text'] == 'x' * 160001
    assert 'Row order, types, values and source references are unchanged.' in payload['table_encoding']
