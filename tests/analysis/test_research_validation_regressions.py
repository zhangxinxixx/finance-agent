from copy import deepcopy
from hashlib import sha256
import pytest

from apps.analysis.snapshots.input_validation import prepare_analysis_inputs
from tests.analysis.test_input_validation import row, valid_snapshot


def test_rejected_inputs_are_idempotent_and_tampered_flags_do_not_grant_authority():
    source = valid_snapshot()
    source['daily_research']['passport'] = [row(value=float('nan'))]
    source['macro'] = {'status': 'available', 'data': {'fedwatch': {'status': 'failed', 'probability': .99}}}
    source['daily_research']['execution_timeframes'] = {}
    first = prepare_analysis_inputs(source)
    assert prepare_analysis_inputs(first) == first
    altered = deepcopy(first)
    altered['input_validation']['can_analyze'] = True
    altered['input_validation']['status'] = 'valid'
    assert prepare_analysis_inputs(altered)['input_validation']['can_analyze'] is False


def test_archive_presence_hash_and_storage_boundary_are_verified(tmp_path):
    source = valid_snapshot()
    assert prepare_analysis_inputs(source, storage_root=tmp_path)['input_validation']['can_analyze'] is False
    source = valid_snapshot(tmp_path)
    assert prepare_analysis_inputs(source, storage_root=tmp_path)['input_validation']['can_analyze'] is True
    frame = source['daily_research']['execution_timeframes']['timeframes']['15m']
    frame['source_refs'][0]['raw_sha256'] = sha256((tmp_path/'raw/test.json').read_bytes()).hexdigest()
    assert prepare_analysis_inputs(source, storage_root=tmp_path)['input_validation']['can_analyze'] is True
    (tmp_path/'raw/test.json').write_text('changed')
    assert prepare_analysis_inputs(source, storage_root=tmp_path)['input_validation']['can_analyze'] is False
    frame['source_refs'][0]['raw_path'] = str(tmp_path.parent)
    assert prepare_analysis_inputs(source, storage_root=tmp_path)['input_validation']['can_analyze'] is False


def test_valid_local_growth_labor_and_inflation_survive_missing_peer_records():
    source = valid_snapshot()
    ref = row()['source_refs'][0]
    source['daily_research']['growth'] = {'metrics': {
        'GDP_NOW': {'symbol': 'GDP_NOW', 'value': 2.5, 'unit': '% q/q saar', 'status': 'available',
                    'observation_date': '2026-10-02', 'source_ref': ref},
        'ISM_SERVICES': {'symbol': 'ISM_SERVICES', 'value': 54, 'status': 'failed',
                         'observation_date': '2026-09-01', 'source_ref': ref}}}
    source['daily_research']['employment'] = {'metrics': {
        'CES0000000001': {'current_value': 100, 'unit': 'thousand_persons', 'current_month': '2026-09',
                         'status': 'available', 'source_refs': [ref], 'new_jobs_thousands': 20}},
        'new_jobs_thousands': 20, 'source_refs': {'CES0000000001': ref}}
    source['daily_research']['inflation'] = {'series': {
        'headline_cpi': {'symbol': 'CPIAUCSL', 'level': 330.1, 'observation_date': '2026-09-01',
                         'status': 'available', 'source_refs': [ref], 'mom_pct': .2}}}
    prepared = prepare_analysis_inputs(source)
    research = prepared['daily_research']
    assert research['growth']['metrics']['GDP_NOW']['value'] == 2.5
    assert research['growth']['metrics']['ISM_SERVICES']['status'] == 'unavailable'
    assert research['employment']['new_jobs_thousands'] == 20
    assert research['inflation']['series']['headline_cpi']['level'] == 330.1
    assert prepare_analysis_inputs(prepared) == prepared


def test_legacy_indicator_cannot_override_validated_passport_value():
    source = valid_snapshot()
    source['daily_research']['passport'] = [row(value=4.1)]
    source['macro'] = {'status': 'available', 'data': {'indicators': {'US10Y': {'value': 999}}}}
    prepared = prepare_analysis_inputs(source)
    assert prepared['macro']['data']['indicators']['US10Y']['value'] == 4.1


def test_verified_predecessor_and_accepted_state_remain_independent_of_rejected_current_data():
    source = valid_snapshot()
    source['daily_research']['passport'] = [row(value=float('nan'))]
    source['input_snapshot_ids']['previous_research'] = 'previous-verified'
    source['gold_workflow'].update(
        state_record={'accepted_state': 'S2', 'accepted_at': '2026-10-02T12:00:00Z'},
        previous_research={'status': 'verified', 'snapshot_id': 'previous-verified'},
        delta_vs_previous={'status': 'available', 'previous_snapshot_id': 'previous-verified',
                           'rows': [{'symbol': 'US10Y', 'current': 4.1, 'current_date': '2026-10-02', 'delta': .1}]})
    prepared = prepare_analysis_inputs(source)
    flow = prepared['gold_workflow']
    assert flow['state']['accepted_state'] == 'S2'
    assert flow['previous_research']['snapshot_id'] == 'previous-verified'
    assert flow['delta_vs_previous']['rows'][0]['delta'] is None


@pytest.mark.parametrize('invalid', [
    {'unit': 'USD/oz'}, {'retrieved_at': '2026-10-06T00:00:00Z'},
    {'release_time': '2026-10-05T12:00:00Z'}, {'release_date': '2026-10-06'},
])
def test_grouped_record_rejects_wrong_units_and_future_clocks(invalid):
    source = valid_snapshot()
    metric = {'series_id': 'CES0000000001', 'current_value': 100,
              'unit': 'thousand_persons', 'current_month': '2026-09', 'status': 'available',
              'current_source': row()['source_refs'][0], **invalid}
    source['daily_research']['employment'] = {'metrics': {'CES0000000001': metric}}
    prepared = prepare_analysis_inputs(source)
    assert prepared['daily_research']['employment']['metrics']['CES0000000001']['status'] == 'unavailable'
    assert prepare_analysis_inputs(prepared) == prepared


@pytest.mark.parametrize('proven', [False, True])
def test_daily_close_does_not_authorize_stale_technical_derivatives(proven):
    source = valid_snapshot()
    daily = row(symbol='XAUUSD_DAILY', unit='USD/oz', value=4000)
    daily['source_refs'][0].update(symbol='XAUUSD', instrument_type='spot')
    source['daily_research']['passport'] = [daily]
    refs = daily['source_refs']
    source['technical'] = {'status': 'available', 'data': {
        'price': 4000, 'as_of': '2026-10-02' if proven else '2026-09-18',
        'trend': 'bullish', 'atr14': 10, 'source_refs': refs,
        'price_structure': {'status': 'available', 'as_of': '2026-09-18', 'source_refs': refs,
                            'levels': [{'kind': 'prior_5d_high', 'price': 1}]}}}
    prepared = prepare_analysis_inputs(source)
    data = prepared['technical']['data']
    assert data['price'] == 4000
    assert 'price_structure' not in data
    assert (data.get('atr14') == 10) == proven
    assert data['trend'] == ('bullish' if proven else 'unavailable')
    assert prepare_analysis_inputs(prepared) == prepared


def test_cme_and_cftc_producer_refs_keep_real_collection_times(tmp_path):
    from datetime import datetime, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database.models.cme import CmeRawFile, CmeOptionRow, CmeParseRun
    from database.queries.cme import ensure_cme_tables
    from apps.worker.pipelines.cme import _selected_cme_lineage
    from apps.analysis.snapshots.builder import _build_positioning_section
    from tests.helpers.warehouse import create_collection_schema
    from apps.data_layer.warehouse_sources import load_source_warehouse
    from database.queries.warehouse_cme import get_cme_option_rows

    engine = create_engine('sqlite://')
    ensure_cme_tables(engine)
    create_collection_schema(engine)
    collected = datetime(2026, 10, 5, 6, tzinfo=timezone.utc)
    archive = tmp_path / 'raw/test.pdf'
    archive.parent.mkdir()
    archive.write_bytes(b'fixture PDF')
    with Session(engine) as db:
        db.add(CmeRawFile(id='raw-id', source='cme', section='PG64', raw_path='raw/test.pdf',
                         sha256=sha256(archive.read_bytes()).hexdigest(), report_date='2026-10-02',
                         source_url='https://www.cmegroup.com/fixture.pdf', bytes=11, retrieved_at=collected))
        db.flush()
        db.add(CmeParseRun(raw_file_id='raw-id', status='FINAL', detail_rows_count=1,
                          summary_rows_count=0, created_at=collected))
        db.add(CmeOptionRow(raw_file_id='raw-id', trade_date='2026-10-02', report_date='2026-10-02',
                            version_type='FINAL', product_code='OG', expiry='DEC26', strike=4000,
                            option_type='CALL', open_interest=10))
        db.flush()
        loaded = load_source_warehouse(db, 'cme-options', record_ids=['raw-id'], dry_run=False)
        assert loaded['rejected'] == 0
        refs = _selected_cme_lineage(db, get_cme_option_rows(db, report_date='2026-10-02'))['source_refs']
    source = valid_snapshot(tmp_path)
    source['options'] = {'status': 'available', 'data': {'as_of': '2026-10-02', 'source_refs': refs, 'total_oi': 10}}
    assert refs[0]['retrieved_at'] == collected.isoformat()
    assert prepare_analysis_inputs(source, storage_root=tmp_path)['input_validation']['domains']['options']['status'] == 'available'

    points = [dict(symbol='COT_GOLD_' + suffix, value=10, date='2026-09-29', source='cftc',
                   source_url='https://www.cftc.gov/fixture.zip', raw_path='raw/test.json',
                   retrieved_at=collected.isoformat()) for suffix in ('commercial_net', 'noncomm_net')]
    source['positioning'] = _build_positioning_section(points)
    assert all(ref['retrieved_at'] == collected.isoformat() for ref in source['positioning']['data']['source_refs'])
    assert prepare_analysis_inputs(source, storage_root=tmp_path)['input_validation']['domains']['positioning']['status'] == 'available'


@pytest.mark.parametrize('bad_ref', [
    {'source': 'comex_gc', 'symbol': 'GC_CONTINUOUS', 'instrument_type': 'futures'},
    {'source_url': 'https://example.test/unrelated'},
])
def test_technical_source_cannot_borrow_spot_raw_path(bad_ref):
    source = valid_snapshot()
    daily = row(symbol='XAUUSD_DAILY', unit='USD/oz', value=4000)
    daily['source_refs'][0].update(symbol='XAUUSD', instrument_type='spot')
    refs = deepcopy(daily['source_refs'])
    refs[0].update(bad_ref)
    source['daily_research']['passport'] = [daily]
    source['technical'] = {'data': {'price': 4000, 'as_of': '2026-10-02', 'source_refs': refs,
                                   'trend': 'bullish', 'atr14': 999}}
    prepared = prepare_analysis_inputs(source)
    assert prepared['technical']['data']['trend'] == 'unavailable'
    assert 'atr14' not in prepared['technical']['data']
    assert prepare_analysis_inputs(prepared) == prepared


def test_sourced_technical_scalars_and_levels_still_require_valid_coordinates():
    source = valid_snapshot()
    daily = row(symbol='XAUUSD_DAILY', unit='USD/oz', value=4000)
    daily['source_refs'][0].update(symbol='XAUUSD', instrument_type='spot')
    source['daily_research']['passport'] = [daily]
    source['technical'] = {'data': {'price': 4000, 'as_of': '2026-10-02', 'source_refs': daily['source_refs'],
        'atr14': -10, 'rsi14': 101, 'ma20': float('inf'), 'trend': 'fabricated',
        'key_levels': [{'price': 3999, 'as_of': '2025-01-01'}]}}
    prepared = prepare_analysis_inputs(source)
    data = prepared['technical']['data']
    assert not any(key in data for key in ('atr14', 'rsi14', 'ma20', 'key_levels'))
    assert data['trend'] == 'unavailable'
    assert prepare_analysis_inputs(prepared) == prepared
