from pathlib import Path
import json

import httpx

from apps.collectors.research.mainstream_news import collect_mainstream_news, freshness, assess_mainstream_coverage
from apps.parsers.research.public_evidence import parse_public_document


def test_cna_source_credit_not_photo_credit_and_jsonld_date_without_article_body():
    html = '''<h1>Oil</h1><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-09-15T08:30:00+08:00","dateModified":"2026-09-15T09:00:00+08:00","publisher":{"name":"CNA"}}</script>
    <div class="text-long"><p>Oil supply report.</p></div><div class="source">Source: Reuters/fh</div>'''
    result = parse_public_document(html, url='https://www.channelnewsasia.com/business/oil')
    assert result['origin_publisher'] == 'Reuters'
    assert result['published_at'] == '2026-09-15T08:30:00+08:00'
    assert result['updated_at'] == '2026-09-15T09:00:00+08:00'
    photo_only = parse_public_document(html.replace('Source: Reuters/fh', 'Photo: REUTERS'), url='https://www.channelnewsasia.com/business/oil')
    assert photo_only['origin_publisher'] is None


def test_freshness_rejects_old_unknown_and_future_publication():
    as_of = '2026-09-15T04:00:00Z'
    assert freshness('2026-09-15T10:00:00+08:00', as_of=as_of)['age_hours'] == 2
    assert freshness('2026-09-13T10:00:00Z', as_of=as_of)['status'] == 'STALE'
    assert freshness(None, as_of=as_of)['status'] == 'UNKNOWN_TIME'
    assert freshness('2026-09-15T05:00:00Z', as_of=as_of)['status'] == 'FUTURE'
    assert freshness('2026-09-15T01:00:00', as_of=as_of)['status'] == 'UNKNOWN_TIME'


def test_cna_nested_paragraphs_exclude_games_and_duplicate_story():
    html = '''<div class="text-long"><p>First paragraph.</p><p>
    <div class="in-article-games"><p>CNA Games promotion.</p></div>
    <p>Second paragraph.</p><p>Third paragraph.</p></p></div>'''
    result = parse_public_document(html, url='https://www.channelnewsasia.com/business/oil')
    assert result['paragraphs'] == ['First paragraph.', 'Second paragraph.', 'Third paragraph.']


def test_feed_and_bodies_are_archived_and_old_feed_items_not_fetched(tmp_path):
    xml = '''<rss><channel><item><title>Oil supply</title><link>https://www.channelnewsasia.com/business/oil</link><pubDate>Tue, 15 Sep 2026 10:00:00 +0800</pubDate></item>
    <item><title>Fed rates</title><link>https://www.channelnewsasia.com/business/fed</link><pubDate>Tue, 15 Sep 2026 09:00:00 +0800</pubDate></item>
    <item><title>Old gold report</title><link>https://www.channelnewsasia.com/business/old</link><pubDate>Mon, 07 Sep 2026 09:00:00 +0800</pubDate></item></channel></rss>'''
    called = []
    def document(**kwargs):
        called.append(kwargs['key'])
        return {'url': kwargs['key'], 'document_id': str(len(called))*32, 'status': 'available',
                'origin_publisher': 'Reuters', 'parts': [['Oil and Fed '*100]], 'source_refs': [],
                'published_at': '2026-09-15T09:00:00+08:00', 'evidence_scope': 'publisher_body'}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=xml))) as client:
        result = collect_mainstream_news(as_of='2026-09-15T04:00:00Z', storage_root=tmp_path, client=client, document_collector=document,
                                         discovery=lambda **_: {'news': []})
    assert result['reuters_count'] == 2
    assert len(called) == 2
    assert not any('old' in url for url in called)
    assert json.loads((Path(tmp_path)/result['artifact_path']).read_text())['status'] == 'available'


def test_new_fetch_or_modified_date_cannot_make_old_article_fresh():
    doc = {'url': 'https://www.channelnewsasia.com/business/a', 'origin_publisher': 'Reuters',
           'status': 'available', 'evidence_scope': 'publisher_body', 'body_verified': True,
           'published_at': '2026-09-01T00:00:00Z', 'updated_at': '2026-09-15T03:00:00Z'}
    result = assess_mainstream_coverage([doc], as_of='2026-09-15T04:00:00Z')
    assert result['reuters_count'] == 0
    assert 'FRESH_REUTERS_BODY' in result['critical_gaps']


def test_publisher_index_fills_rolling_feed_gap_but_checks_article_date(tmp_path):
    index = '''<a href="/business/oil">Oil supply disruption</a>
    <a href="/business/fed">Fed rate outlook</a>
    <a href="/business/old">Gold rally last month</a>'''
    def response(request):
        return httpx.Response(200, text=index if request.url.path == '/business' else '<rss><channel/></rss>')
    def document(**kwargs):
        old = kwargs['key'].endswith('/old')
        return {'url': kwargs['key'], 'document_id': 'x', 'status': 'available',
                'origin_publisher': 'Reuters', 'parts': [['Market evidence '*80]],
                'published_at': '2026-08-15T01:00:00Z' if old else '2026-09-15T01:00:00Z',
                'source_refs': [], 'evidence_scope': 'publisher_body'}
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        result = collect_mainstream_news(as_of='2026-09-15T04:00:00Z', storage_root=tmp_path,
                                         client=client, document_collector=document, discovery=lambda **_: {'news': []})
    assert result['reuters_count'] == 2
    assert result['status'] == 'available'
    assert result['documents'][-1]['freshness']['status'] == 'STALE'
    assert result['documents'][-1]['eligible_current_news'] is False
    assert any(r['source'] == 'CNA business index' for r in result['source_refs'])


def test_search_fallback_fetches_body_and_rejects_stale_article_despite_fresh_snippet(tmp_path):
    def search(**_):
        return {'news': [{'url': 'https://www.channelnewsasia.com/business/'+key,
                         'title': 'Oil and dollar', 'published_at': '2026-09-15T01:00:00Z'}
                        for key in ('fresh', 'old')], 'source_refs': [{'source': 'public_news_search'}]}
    def document(**kwargs):
        return {'url': kwargs['key'], 'document_id': 'x', 'status': 'available',
                'origin_publisher': 'Reuters', 'parts': [['Oil market evidence '*80]],
                'published_at': '2026-09-01T01:00:00Z' if kwargs['key'].endswith('/old') else '2026-09-15T01:00:00Z',
                'source_refs': [], 'evidence_scope': 'publisher_body'}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='<rss><channel/></rss>'))) as client:
        result = collect_mainstream_news(as_of='2026-09-15T04:00:00Z', storage_root=tmp_path,
                                         client=client, document_collector=document, discovery=search)
    assert result['reuters_count'] == 1
    assert result['status'] == 'partial'
    assert result['documents'][1]['eligible_current_news'] is False
    assert any(r['source'] == 'public_news_search' for r in result['source_refs'])


def test_news_worker_attaches_archive_identity_without_mutating_parent(tmp_path):
    from apps.worker.mainstream_news import enrich_mainstream_news_snapshot
    parent = {'snapshot_id': 'parent', 'source_refs': [], 'input_snapshot_ids': {}}
    evidence = {'artifact_path': 'parsed/research_documents/news.json',
                'source_refs': [{'source': 'Reuters', 'source_url': 'https://www.channelnewsasia.com/business/oil'}],
                'status': 'available'}
    child = enrich_mainstream_news_snapshot(parent, storage_root=tmp_path, collector=lambda **_: evidence)
    assert parent['source_refs'] == []
    assert parent['input_snapshot_ids'] == {}
    assert child['mainstream_news'] == evidence
    assert child['input_snapshot_ids']['mainstream_news'] == evidence['artifact_path']
    assert child['source_refs'] == evidence['source_refs']
