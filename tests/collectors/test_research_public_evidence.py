import json

import httpx
import pytest

from apps.collectors.research.public_evidence import (
    collect_public_document, collect_news_discovery, project_document, read_document_part, validate_public_url,
)
from apps.parsers.research.public_evidence import parse_public_document, parse_fedwatch


def test_iau_levels_have_their_own_dates():
    html = '<h1>IAU</h1><div>Shares Outstanding 791,100,000 as of Sep 14, 2026</div><div>Tonnes in Trust 462.59 as of Sep 11, 2026</div>'
    parsed = parse_public_document(html, url='https://www.ishares.com/us/products/239561/iau-ishares-gold-trust-fund')
    assert parsed['observations'][0]['value'] == 791100000
    assert parsed['observations'][1]['observation_date'] == '2026-09-11'
    assert all(o['value_kind'] == 'level_not_flow' for o in parsed['observations'])


@pytest.mark.parametrize('url', ['http://apnews.com/article/a', 'https://apnews.com.evil.test/a',
                                'https://apnews.com@127.0.0.1/a', 'https://127.0.0.1/a',
                                'https://apnews.com:8000/a', 'file:///etc/passwd'])
def test_untrusted_document_urls_rejected(url):
    with pytest.raises(ValueError):
        validate_public_url(url)


def test_redirect_cannot_access_localhost(tmp_path):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'location': 'http://127.0.0.1:8000/private'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect_public_document(key='https://apnews.com/article/a', retrieved_date='2026-09-15', storage_root=tmp_path, client=client)
    assert len(calls) == 1
    assert result['status'] == 'unavailable'


def test_document_body_is_archived_and_expanded_without_refetch(tmp_path):
    body = '<article><h1>Supply</h1>' + ''.join('<p>'+str(i)+'x'*1500+'</p>' for i in range(10)) + '</article>'
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body))) as client:
        result = collect_public_document(key='https://apnews.com/article/a', retrieved_date='2026-09-15', storage_root=tmp_path, client=client)
    summary = project_document(result)
    assert summary['part_count'] > 1
    assert summary['body_is_complete'] is False
    expanded = read_document_part(key=result['document_id']+':1', known_documents=[summary], storage_root=tmp_path)
    assert expanded['text_blocks'] != summary['text_blocks']
    assert json.loads((tmp_path/result['parsed_path']).read_text())['parts'][1] == expanded['text_blocks']
    assert (tmp_path/result['source_refs'][0]['raw_path']).is_file()
    with pytest.raises(ValueError):
        read_document_part(key='0'*32+':0', known_documents=[summary], storage_root=tmp_path)
    (tmp_path/result['parsed_path']).write_text('{}')
    with pytest.raises(ValueError, match='hash_mismatch'):
        read_document_part(key=result['document_id']+':1', known_documents=[summary], storage_root=tmp_path)


def test_fedwatch_does_not_invent_authorization_or_current_target(tmp_path, monkeypatch):
    monkeypatch.delenv('CME_FEDWATCH_ACCESS_TOKEN', raising=False)
    result = collect_public_document(key='FEDWATCH', retrieved_date='2026-09-15', storage_root=tmp_path, client=object())
    assert result['reason'] == 'cme_fedwatch_entitled_oauth_token_missing'
    payload = {'payload': [{'calculationTimestamp': '2026-09-15T02:00:00',
                           'meetingDt': '2026-09-16', 'currentReportingRt': '350-375',
                           'rateRange': [{'lowerRt': 350, 'upperRt': 375, 'probability': .2},
                                         {'lowerRt': 375, 'upperRt': 400, 'probability': .8}]}]}
    distribution = parse_fedwatch(payload, source_ref={'source': 'CME'})
    assert distribution['observed_at'].endswith('+00:00')
    assert distribution['current_target_midpoint'] is None
    assert distribution['meetings'][0]['bins'][1]['upper'] == 4
    payload['payload'][0]['rateRange'][0]['probability'] = .8
    with pytest.raises(ValueError):
        parse_fedwatch(payload, source_ref={'source': 'CME'})


def test_source_tables_keep_headings_dates_and_units():
    result = parse_public_document('<main><table><tr><th>million barrels</th><th>2026-09-04</th></tr><tr><td>SPR</td><td>285.4</td></tr></table></main>', url='https://www.eia.gov/a')
    assert result['tables'][0]['rows'] == [['million barrels', '2026-09-04'], ['SPR', '285.4']]


def test_news_links_unwrap_and_reject_off_topic_or_foreign_destinations(tmp_path):
    xml = '''<rss><channel>
    <item><title>Saudi pipeline outage</title><link>http://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fapnews.com%2Farticle%2Fsupply</link></item>
    <item><title>Election results</title><link>https://apnews.com/article/election</link></item>
    <item><title>Saudi pipeline</title><link>http://www.bing.com/news/apiclick.aspx?url=http%3A%2F%2F127.0.0.1%2Fsecret</link></item>
    </channel></rss>'''
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=xml))) as client:
        result = collect_news_discovery(query='Saudi pipeline', storage_root=tmp_path, client=client)
    assert [n['url'] for n in result['news']] == ['https://apnews.com/article/supply']
    assert result['news'][0]['full_text_available'] is False


def test_eia_nested_layout_retains_one_dated_stock_series():
    html = '''<h1>Stocks (Thousand Barrels)</h1><table><tr><td>Layout</td></tr></table><table>
    <tr><td><table><tr><td>Show Data</td></tr></table></td><th>08/28/26</th><th>09/04/26</th></tr>
    <tr><td><table><tr><td>SPR</td></tr></table></td><td>286,604</td><td>285,360</td></tr></table>'''
    result = parse_public_document(html, url='https://www.eia.gov/dnav/pet/pet_stoc_wstk_dcu_nus_w.htm')
    assert len(result['tables']) == 1
    assert [(o['value'], o['observation_date']) for o in result['observations']] == [(286604, '2026-08-28'), (285360, '2026-09-04')]
