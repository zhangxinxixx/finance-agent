import pytest
from copy import deepcopy
from datetime import UTC, datetime

from apps.analysis.agents.research_context import build_research_assessment
from apps.analysis.snapshots.builder import build_analysis_snapshot
from apps.renderer.markdown.final_report import render_final_report_markdown, build_structured_report


def _snapshot():
    rows = {key: {'symbol':key,'date':'2026-09-04','value':value,'daily_change':delta,'previous_date':'2026-09-03'} for key,value,delta in [('US02Y',4.38,.05),('US10Y',4.77,.01),('REAL_10Y',2.42,0)]}
    refs = {key: {'source':'fred','source_url':f'https://fred.stlouisfed.org/series/{key}','raw_path':f'raw/{key}.json','retrieved_at':'2026-09-05T15:00:00+00:00'} for key in ('DGS2','DGS10','T10YIE')}
    return build_analysis_snapshot(asset='XAUUSD',trade_date='2026-09-05',run_id='test',macro_snapshot={'as_of':'2026-09-05','indicators':rows,'source_refs':refs},options_snapshot=None,snapshot_time='2026-09-05T16:00:00+00:00',include_daily_research=True,disabled_sources=('jin10',))


def test_research_curve_requires_both_comparison_dates_and_is_immutable():
    snapshot = _snapshot()
    before = deepcopy(snapshot)
    assessment = build_research_assessment(snapshot)
    assert any('短端利率上行更明显' in value for value in assessment['drivers'])
    assert snapshot == before
    for row in snapshot['daily_research']['passport']:
        if row['symbol'] == 'US10Y':
            row['previous_date'] = '2026-09-02'
    # Projection is recomputed when source inputs change, never in the renderer.
    snapshot['daily_research']['rate_changes_same_window'] = False
    assessment = build_research_assessment(snapshot)
    assert not any('短端利率上行更明显' in value for value in assessment['drivers'])


def test_research_passport_exposes_official_real_curve_and_long_end_slope():
    from apps.features.research.daily import build_daily_research_features

    snapshot = {
        'snapshot_time': '2026-09-05T16:00:00+00:00',
        'trade_date': '2026-09-05',
        'macro': {
            'status': 'available',
            'data': {
                'indicators': {
                    'US30Y': {'value': 5.24, 'date': '2026-09-04', 'previous_value': 5.20,
                              'previous_date': '2026-09-03', 'daily_change': .04,
                              'weekly_anchor_value': 5.19, 'weekly_anchor_date': '2026-08-28',
                              'weekly_change': .05},
                    'US10Y': {'value': 4.78, 'date': '2026-09-04', 'previous_value': 4.77,
                              'previous_date': '2026-09-03', 'daily_change': .01,
                              'weekly_anchor_value': 4.73, 'weekly_anchor_date': '2026-08-28',
                              'weekly_change': .05},
                    'REAL10Y': {'value': 2.43, 'date': '2026-09-04', 'previous_value': 2.42,
                                'previous_date': '2026-09-03', 'daily_change': .01,
                                'weekly_anchor_value': 2.41, 'weekly_anchor_date': '2026-08-28',
                                'weekly_change': .02},
                    'DGS30': {'value': 5.24, 'date': '2026-09-04', 'previous_value': 5.20,
                              'previous_date': '2026-09-03', 'daily_change': .04,
                              'weekly_anchor_value': 5.19, 'weekly_anchor_date': '2026-08-28',
                              'weekly_change': .05},
                    'DGS10': {'value': 4.78, 'date': '2026-09-04', 'previous_value': 4.77,
                              'previous_date': '2026-09-03', 'daily_change': .01,
                              'weekly_anchor_value': 4.73, 'weekly_anchor_date': '2026-08-28',
                              'weekly_change': .05},
                    'YIELD_SPREAD_30Y_10Y': {'value': .46, 'date': '2026-09-04', 'previous_value': .43,
                                             'previous_date': '2026-09-03', 'daily_change': .03,
                                             'weekly_anchor_value': .46, 'weekly_anchor_date': '2026-08-28',
                                             'weekly_change': 0.0},
                },
                'source_refs': {
                    symbol: {'source': 'treasury_rates', 'source_url': 'https://home.treasury.gov/test',
                             'raw_path': f'raw/{symbol}.csv', 'retrieved_at': '2026-09-05T15:00:00+00:00'}
                    for symbol in ('DGS30', 'DGS10', 'DFII10')
                },
            },
        },
    }
    result = build_daily_research_features(snapshot)
    passport = {row['symbol']: row for row in result['passport']}
    assert passport['REAL10Y']['value'] == 2.43
    assert passport['REAL10Y']['status'] == 'fresh'
    assert result['project_signals']['real_rate']['authority'] == 'official_dfii10'
    assert result['project_signals']['real_rate']['selected_symbol'] == 'REAL10Y'
    signal = result['project_signals']['long_end_curve']
    assert signal['status'] == 'fresh'
    assert signal['spread'] == 0.46
    assert signal['formula'] == 'US30Y - US10Y (DGS30 - DGS10)'


def test_monthly_release_uses_release_window_and_does_not_pose_as_daily_change():
    from apps.features.research.daily import build_daily_research_features

    refs = {
        symbol: {
            'source': 'fred', 'source_url': f'https://fred.test/{source}',
            'raw_path': f'raw/{source}.json', 'retrieved_at': '2026-09-08T00:00:00+00:00',
        }
        for symbol, source in {
            'CPIAUCSL': 'CPIAUCSL', 'PCEPI': 'PCEPI', 'NAPM': 'NAPM',
        }.items()
    }
    snapshot = {
        'snapshot_time': '2026-09-08T12:00:00+00:00', 'trade_date': '2026-09-08',
        'macro': {'status': 'available', 'data': {
            'indicators': {
                'CPI': {'value': 330.0, 'date': '2026-08-01', 'previous_value': 329.0,
                        'previous_date': '2026-07-01', 'daily_change': 1.0,
                        'monthly_change': 1.0, 'weekly_change': 1.0},
                'PCE': {'value': 130.0, 'date': '2026-05-01', 'previous_value': 129.0,
                        'previous_date': '2026-04-01', 'monthly_change': 1.0},
                'ISM_MANUFACTURING': {'value': 49.0, 'date': '2025-01-01', 'previous_value': 48.0,
                                      'previous_date': '2024-12-01', 'monthly_change': 1.0},
            }, 'source_refs': refs,
        }},
    }
    result = build_daily_research_features(snapshot)
    rows = {row['symbol']: row for row in result['passport']}
    assert rows['CPI']['status'] == 'fresh'
    assert rows['CPI']['change'] is None and rows['CPI']['weekly_change'] is None
    assert rows['CPI']['monthly_change'] == 1.0
    assert rows['CPI']['monthly_change_pct'] is None
    assert rows['CPI']['yoy_status'] == 'unavailable_no_12m_same_vintage'
    assert rows['PCE']['status'] == 'stale'
    # Discontinued FRED NAPM cannot satisfy the current official ISM source.
    assert rows['ISM_MANUFACTURING']['status'] == 'unavailable'
    assert rows['ISM_MANUFACTURING']['lineage_status'] == 'missing_or_future_source'
    assert '不能称为当前 ISM' in rows['ISM_MANUFACTURING']['freshness_note']


def test_walcl_is_a_fresh_weekly_point_observation_not_a_weekly_average():
    from apps.features.research.daily import build_daily_research_features

    snapshot = {
        'snapshot_time': '2026-09-17T12:00:00+00:00',
        'trade_date': '2026-09-17',
        'macro': {'status': 'available', 'data': {
            'indicators': {
                'WALCL': {
                    'value': 7123.4567,
                    'date': '2026-09-09',
                    'previous_value': 7119.0,
                    'previous_date': '2026-09-02',
                    'daily_change': 4.4567,
                },
            },
            'source_refs': {
                'WALCL': {
                    'source': 'fred',
                    'source_url': 'https://fred.stlouisfed.org/series/WALCL',
                    'raw_path': 'raw/macro/fred/2026-09-17/WALCL.json',
                    'retrieved_at': '2026-09-17T11:00:00+00:00',
                },
            },
        }},
    }

    row = next(
        row for row in build_daily_research_features(snapshot)['passport']
        if row['symbol'] == 'WALCL'
    )

    assert row['observation_date'] == '2026-09-09'
    assert row['frequency'] == 'weekly'
    assert row['frequency'] != 'weekly_average'
    assert row['status'] == 'fresh'


def test_spot_metadata_follows_selected_technical_source_and_rejects_future_quote_ref():
    from apps.features.research.daily import build_daily_research_features

    snapshot = {
        'snapshot_time': '2026-09-08T12:00:00+00:00', 'trade_date': '2026-09-08',
        'technical': {'status': 'available', 'data': {
            'source_refs': [{
                'source': 'twelvedata_xauusd_daily', 'raw_path': 'raw/current.json',
                'retrieved_at': '2026-09-08T11:00:00+00:00',
            }],
        }},
        'source_refs': [
            {
                'symbol': 'XAUUSD', 'source': 'twelvedata_xauusd_daily', 'raw_path': 'raw/old.json',
                'retrieved_at': '2026-09-08T10:00:00+00:00',
                'notes': {'spot_anchor': {'price': 1.0, 'price_time': '2026-09-08T10:00:00+00:00',
                    'instrument_type': 'spot', 'status': 'verified', 'source_refs': [{'source': 'old', 'source_url': 'old',
                        'raw_path': 'raw/old.json', 'retrieved_at': '2026-09-08T10:00:00+00:00'}]}},
            },
            {
                'symbol': 'XAUUSD', 'source': 'twelvedata_xauusd_daily', 'raw_path': 'raw/current.json',
                'retrieved_at': '2026-09-08T11:00:00+00:00',
                'notes': {
                    'spot_anchor': {'price': 2.0, 'price_time': '2026-09-08T11:59:00+00:00',
                        'instrument_type': 'spot', 'status': 'verified', 'source_refs': [{'source': 'quote', 'source_url': 'quote',
                            'raw_path': 'raw/quote.json', 'retrieved_at': '2026-09-08T11:59:00+00:00'}]},
                },
            },
        ],
    }
    result = build_daily_research_features(snapshot)
    assert result['spot_anchor']['price'] == 2.0
    assert result['spot_anchor']['status'] == 'verified'

    snapshot['source_refs'][1]['notes']['spot_anchor']['source_refs'][0]['retrieved_at'] = '2026-09-08T12:01:00+00:00'
    blocked = build_daily_research_features(snapshot)['spot_anchor']
    assert blocked['status'] == 'partial'
    assert blocked['price'] is None


def test_versioned_markdown_json_share_sections_and_keep_gaps_visible():
    snapshot = _snapshot()
    assessment = build_research_assessment(snapshot)
    kwargs = dict(snapshot=snapshot,macro_output=None,options_output=None,risk_output=None,coordinator_output=None,created_at=datetime(2026,9,5,16,tzinfo=UTC),research_assessment=assessment)
    # Historical section projections remain inspectable, but no model success
    # and no credible spot must never become a newly generated final report.
    with pytest.raises(ValueError, match="research report blocked"):
        render_final_report_markdown(**kwargs)
    with pytest.raises(ValueError, match="research report blocked"):
        build_structured_report(**kwargs)
    from apps.renderer.markdown.daily_research import daily_research_sections, render_daily_research_report
    sections = daily_research_sections(snapshot, {}, assessment)
    md = render_daily_research_report(snapshot, sections)
    assert all(f"## {section['title']}" in md and section['body'] in md for section in sections)
    assert '本次 CME 输入不可用' in md
    assert '未赋予统计概率' in md
    assert '不沿用范例' in md
    legacy_snapshot = deepcopy(snapshot)
    legacy_snapshot.pop("daily_research")
    legacy_snapshot.pop("gold_workflow", None)
    legacy = build_structured_report(**{**{key:value for key,value in kwargs.items() if key!='research_assessment'}, "snapshot": legacy_snapshot})
    assert legacy.version.report_version == '1.0.0'
    assert len(legacy.sections) == 11


def test_missing_or_future_lineage_cannot_drive_current_research():
    from apps.features.research.daily import build_daily_research_features

    snapshot = _snapshot()
    snapshot['macro']['data']['source_refs']['DGS2']['retrieved_at'] = '2026-09-06T01:00:00+00:00'
    snapshot['daily_research'] = build_daily_research_features(snapshot)
    row = next(row for row in snapshot['daily_research']['passport'] if row['symbol'] == 'US02Y')
    assert row['status'] == 'unavailable'
    assessment = build_research_assessment(snapshot)
    assert not any('短端利率上行更明显' in item for item in assessment['drivers'])
    assert all('价格路径不可用' in item['path'] for item in assessment['scenarios'])


def test_future_research_observation_blocks_macro_and_official_calendar_renders():
    snapshot = build_analysis_snapshot(asset='XAUUSD', trade_date='2026-09-05', run_id='test', macro_snapshot={'as_of':'2026-09-05','official_etf':{'shares_reported_on':'2026-09-06'}}, options_snapshot=None, snapshot_time='2026-09-05T16:00:00+00:00')
    assert snapshot['macro']['reason'] == 'future_dated_input'
    snapshot = _snapshot()
    snapshot['news'] = {'status':'available','data':{'official_calendar':{'events':[{'event_type':'fomc_meeting','start_date':'2026-09-15','end_date':'2026-09-16','is_sep':True}]}}}
    assessment = build_research_assessment(snapshot)
    with pytest.raises(ValueError, match="research report blocked"):
        render_final_report_markdown(snapshot=snapshot, macro_output=None, options_output=None, risk_output=None, coordinator_output=None, created_at=datetime(2026,9,5,16,tzinfo=UTC), research_assessment=assessment)
    from apps.renderer.markdown.daily_research import daily_research_sections, render_daily_research_report
    md = render_daily_research_report(snapshot, daily_research_sections(snapshot, {}, assessment))
    assert '2026-09-15 至 2026-09-16' in md
    assert '具体时刻未提供' in md


def test_old_accepted_intraday_bar_is_not_promoted_to_complete_daily_price():
    from apps.features.research.daily import build_daily_research_features

    snapshot = _snapshot()
    ref = {'source': 'provider', 'reference': 'https://example.test/daily', 'raw_path': 'raw/bar.json', 'retrieved_at': '2026-09-04T12:00:00+00:00'}
    snapshot['oil'] = {'status': 'available', 'data': {'wti': {'value': 91.48, 'quality_status': 'accepted', 'alignment_status': 'aligned', 'freshness_status': 'fresh', 'bar_open_time': '2026-09-04T04:00:00+00:00', 'bar_close_time': '2026-09-05T04:00:00+00:00', 'source_refs': [ref]}}}
    row = next(row for row in build_daily_research_features(snapshot)['passport'] if row['symbol'] == 'WTI_FUTURES_PROXY')
    assert row['value'] is None and row['status'] == 'unavailable'
    ref['retrieved_at'] = '2026-09-05T04:01:00+00:00'
    row = next(row for row in build_daily_research_features(snapshot)['passport'] if row['symbol'] == 'WTI_FUTURES_PROXY')
    assert row['value'] == 91.48 and row['status'] == 'fresh'


def test_release_revisions_require_own_lineage_and_missing_consensus_stays_visible():
    from apps.renderer.markdown.daily_research import _employment_body

    release = {'status': 'partial', 'source_kind': 'fred_vintage', 'release_date': '2026-09-04',
               'source_refs': [{'source': 'fred', 'source_url': 'https://fred.stlouisfed.org/series/PAYEMS'}],
               'revisions': [{'observation_month': '2026-07', 'previous_value_thousands': -10,
                              'revised_value_thousands': 15, 'delta_thousands': 25}]}
    data = {'metrics': {'CES0000000001': {'current_month': '2026-08', 'new_jobs_thousands': 160}}, 'release_context': release}
    body = _employment_body(data)
    assert '2026-07 | -10 | +15 | +25' in body
    assert '当前未取得可核验的市场预期' in body
    assert '前次值不一定是首次发布值' in body
    release['source_refs'] = []
    body = _employment_body(data)
    assert '| +25 |' not in body
    assert '历史版本未取得可核验证据' in body


def test_news_zero_new_items_keeps_existing_context_and_source_scope():
    from apps.renderer.markdown.daily_research import _news_body

    news = {'news_coverage': {'collected_item_count': 2, 'novel_item_count': 0, 'context_item_count': 2},
            'daily_market_brief': {'candidate_events': [{'title': 'A public headline',
                'published_at': '2026-09-04T12:00:00Z', 'verification_status': 'unverified',
                'source_refs': [{'source': 'Reuters public discovery', 'source_url': 'https://example.test/article'}]}]}}
    body = _news_body(news)
    assert '新增 0 条；保留上下文 2 条' in body and 'A public headline' in body
    assert '候选报道：1 条' in body and '没有可用于本报告' not in body


def test_technical_overbought_does_not_reverse_trend_and_stale_input_cannot_vote():
    from apps.analysis.agents.technical import analyze_technical

    snapshot = _snapshot()
    row = {'symbol': 'XAUUSD_DAILY'}
    snapshot['daily_research']['passport'].append(row)
    row.update(status='fresh', lineage_status='verified', source_refs=[{'source': 'spot', 'raw_path': 'raw/spot.json'}])
    snapshot['technical'] = {'status': 'available', 'data': {'price': 4500, 'ma20': 4400,
        'ma50': 4200, 'trend': 'bullish', 'rsi14': 85, 'atr14': 130, 'volatility': 'high'}}
    assert analyze_technical(snapshot).bias.value == 'bullish'
    row['status'] = 'stale'
    result = analyze_technical(snapshot)
    assert result.status.value == 'unavailable' and result.bias.value == 'unavailable'


def _treasury_be_snapshot():
    indicators = {
        'US10Y': {'value': 5.0, 'date': '2026-10-02', 'previous_date': '2026-10-01',
                  'previous_value': 4.8, 'weekly_anchor_date': '2026-09-25', 'weekly_anchor_value': 4.7},
        'REAL10Y': {'value': 2.5, 'date': '2026-10-02', 'previous_date': '2026-10-01',
                    'previous_value': 2.4, 'weekly_anchor_date': '2026-09-25', 'weekly_anchor_value': 2.35},
        'BREAKEVEN_10Y': {'value': 2.1, 'date': '2026-10-01', 'previous_value': 2.0,
                         'previous_date': '2026-09-30', 'daily_change': .1},
        'REAL_10Y': {'value': 2.7, 'date': '2026-10-01'},
    }
    refs = {
        symbol: {'source': 'treasury_rates', 'source_url': f'https://home.treasury.gov/{symbol}',
                 'raw_path': f'raw/{symbol}.csv', 'retrieved_at': '2026-10-03T10:00:00+00:00'}
        for symbol in ('DGS10', 'DFII10')
    }
    refs['T10YIE'] = {'source': 'fred', 'source_url': 'https://fred.test/BE',
                      'raw_path': 'raw/BE.json', 'retrieved_at': '2026-10-03T10:00:00+00:00'}
    return {'snapshot_time': '2026-10-03T12:00:00+00:00', 'trade_date': '2026-10-03',
            'macro': {'status': 'available', 'data': {'indicators': indicators, 'source_refs': refs}}}


def test_treasury_same_day_be_replaces_asynchronous_fred_in_research_only():
    from apps.features.research.daily import build_daily_research_features

    snapshot = _treasury_be_snapshot()
    before = deepcopy(snapshot)
    rows = {r['symbol']: r for r in build_daily_research_features(snapshot)['passport']}
    be = rows['BREAKEVEN_10Y']
    assert be['value'] == 2.5 and be['observation_date'] == '2026-10-02'
    assert be['previous_value'] == 2.4 and be['change'] == .1
    assert be['weekly_anchor_value'] == 2.35 and be['weekly_change'] == .15
    assert be['previous_date'] == '2026-10-01' and be['weekly_anchor_date'] == '2026-09-25'
    assert be['provenance_kind'] == 'deterministic_calculation'
    assert be['derivation_version'] == 'treasury_be10y.v1'
    assert {r['raw_path'] for r in be['source_refs']} == {'raw/DGS10.csv', 'raw/DFII10.csv'}
    assert {(c['source_symbol'], c['date'], c['value']) for c in be['components']} == {
        ('DGS10', '2026-10-02', 5.0), ('DFII10', '2026-10-02', 2.5)}
    assert rows['REAL_10Y']['value'] == 2.7
    assert snapshot == before


def test_treasury_be_does_not_invent_comparison_with_staggered_or_missing_endpoints():
    from apps.features.research.daily import build_daily_research_features

    snapshot = _treasury_be_snapshot()
    real = snapshot['macro']['data']['indicators']['REAL10Y']
    real['previous_date'] = '2026-09-30'
    real['weekly_anchor_value'] = None
    be = next(r for r in build_daily_research_features(snapshot)['passport'] if r['symbol'] == 'BREAKEVEN_10Y')
    assert be['value'] == 2.5
    for key in ('previous_date', 'previous_value', 'change', 'weekly_anchor_date', 'weekly_change'):
        assert be[key] is None


def test_treasury_be_requires_same_current_date_and_verified_nonfuture_lineage():
    from apps.features.research.daily import build_daily_research_features

    for case in ('staggered', 'future_lineage', 'missing_lineage', 'fred_tips'):
        snapshot = _treasury_be_snapshot()
        macro = snapshot['macro']['data']
        if case == 'staggered':
            macro['indicators']['REAL10Y']['date'] = '2026-10-01'
        elif case == 'future_lineage':
            macro['source_refs']['DFII10']['retrieved_at'] = '2026-10-04T12:00:00+00:00'
        elif case == 'missing_lineage':
            del macro['source_refs']['DFII10']
        else:
            macro['source_refs']['DFII10']['source'] = 'fred'
        be = next(r for r in build_daily_research_features(snapshot)['passport'] if r['symbol'] == 'BREAKEVEN_10Y')
        assert be['value'] == 2.1 and be['observation_date'] == '2026-10-01'
        assert 'derivation_version' not in be


def test_treasury_be_retains_each_leg_endpoint_for_detailed_comparison():
    from apps.features.research.daily import build_daily_research_features
    from apps.analysis.agents.research_input import detailed_comparison

    snapshot = _treasury_be_snapshot()
    be = next(r for r in build_daily_research_features(snapshot)['passport'] if r['symbol'] == 'BREAKEVEN_10Y')
    for weekly in (True, False):
        comparison = detailed_comparison(be, cutoff=snapshot['snapshot_time'], weekly=weekly)
        assert comparison['comparison_allowed'], comparison['constraints']
    assert [c['weekly_anchor_value'] for c in be['components']] == [4.7, 2.35]
    assert {c['weekly_anchor_date'] for c in be['components']} == {'2026-09-25'}
