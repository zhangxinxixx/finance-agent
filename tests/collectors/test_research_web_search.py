from types import SimpleNamespace

from apps.collectors.research.web_search import collect_web_research


def test_unavailable_hosted_search_uses_public_alternative_and_keeps_attempts(tmp_path):
    def hosted(**kwargs):
        assert kwargs['request_timeout'] == 30
        return SimpleNamespace(items=[], source_refs=[{'source': 'hosted', 'status': 'unavailable'}])
    def public(**kwargs):
        assert kwargs['public_web'] is True
        return {'news': [{'title': 'Supply update', 'evidence_scope': 'search_metadata_only'}],
                'source_refs': [{'source': 'rss'}], 'errors': []}
    result = collect_web_research(query='supply', retrieved_date='2026-09-15', storage_root=tmp_path,
                                  hosted=hosted, public=public)
    assert result['method'] == 'public_rss_fallback'
    assert result['errors'] == []
    assert len(result['source_refs']) == 2
    assert result['news'][0]['evidence_scope'] == 'search_metadata_only'


def test_grounded_summary_is_not_a_quote_or_full_policy_distribution(tmp_path):
    item = SimpleNamespace(title='Fed odds', url='https://apnews.com/article/fed',
                           published_at='2026-09-14T10:00:00Z', summary='Reported odds', raw_path='raw/a.json')
    result = collect_web_research(query='Fed odds', retrieved_date='2026-09-15', storage_root=tmp_path,
        hosted=lambda **kw: SimpleNamespace(items=[item], source_refs=[]),
        public=lambda **kw: (_ for _ in ()).throw(AssertionError('not needed')))
    assert result['news'][0]['summary_origin'] == 'retrieval_model_not_publisher_quote'
    assert result['news'][0]['full_text_available'] is False
    assert result['news'][0]['numeric_use'].endswith('not_official_distribution')


def test_both_methods_unavailable_are_explicit(tmp_path):
    result = collect_web_research(query='Fed odds', retrieved_date='2026-09-15', storage_root=tmp_path,
        hosted=lambda **kw: SimpleNamespace(items=[], source_refs=[]),
        public=lambda **kw: {'news': [], 'source_refs': [], 'errors': ['empty']})
    assert result['errors'] == ['hosted_web_search_unavailable', 'empty']
