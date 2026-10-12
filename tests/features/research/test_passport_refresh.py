from copy import deepcopy

import pytest

from apps.features.research.daily import merge_research_passport


def point(day, value, **extra):
    return {'symbol': 'REAL10Y', 'value': value, 'unit': '%',
            'observation_date': day, 'source_refs': [{'source_url': 'https://fred.stlouisfed.org/series/DFII10'}], **extra}


def test_newer_sourced_fact_replaces_child_only_and_out_of_order_rows_do_not_roll_back():
    parent = [point('2026-09-11', 2.6)]
    before = deepcopy(parent)
    rows = [point('2026-09-15', 2.64), point('2026-09-14', 2.61)]
    child = merge_research_passport(parent, rows, as_of='2026-09-16T10:00:00Z')
    assert child == [rows[0]]
    assert parent == before


@pytest.mark.parametrize('candidate', [
    point('2026-09-11', 2.7), point('2026-09-10', 2.7), point('2026-09-17', 2.7),
    point('2026-09-15', 2.7, source_refs=[]), point('2026-09-15', 270, unit='bp'),
    point('2026-09-15', float('nan')), point('2026-09-15', True), point('bad-date', 2.7),
])
def test_ambiguous_or_incompatible_rows_do_not_replace_existing_fact(candidate):
    parent = [point('2026-09-11', 2.6)]
    assert merge_research_passport(parent, [candidate], as_of='2026-09-16T10:00:00Z') == parent


def test_missing_fact_is_filled_without_deriving_asynchronous_spreads():
    nominal = {'symbol': 'US10Y', 'value': 4.96, 'observation_date': '2026-09-11', 'unit': '%'}
    parent = [nominal, {'symbol': 'REAL10Y', 'value': None, 'unit': '%'}]
    child = merge_research_passport(parent, [point('2026-09-15', 2.64)], as_of='2026-09-16T10:00:00Z')
    assert child[0] == nominal
    assert child[1]['observation_date'] == '2026-09-15'
    assert len(child) == 2
