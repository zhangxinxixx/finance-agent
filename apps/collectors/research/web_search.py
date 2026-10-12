"""Hosted search with a public RSS alternative; never synthesize missing facts."""
from apps.collectors.news.llm_web_search import collect_llm_web_search_news
from apps.collectors.research.public_evidence import collect_news_discovery


def collect_web_research(*, query, retrieved_date, storage_root,
                         hosted=collect_llm_web_search_news, public=collect_news_discovery):
    result = hosted(retrieved_date=retrieved_date, storage_root=storage_root,
                    query_groups={'adaptive': query}, max_items_per_group=4, request_timeout=30)
    refs = list(result.source_refs)
    if result.items:
        return {'news': [{'title': x.title, 'url': x.url, 'published_at': x.published_at,
                          'summary': x.summary, 'raw_path': x.raw_path,
                          'evidence_scope': 'tool_grounded_search_summary',
                          'summary_origin': 'retrieval_model_not_publisher_quote',
                          'full_text_available': False, 'verification_status': 'single_source',
                          'numeric_use': 'dated_reported_estimate_only_not_official_distribution'}
                         for x in result.items], 'source_refs': refs, 'errors': [],
                'method': 'hosted_web_search'}
    # Unsupported tool / transport failure must not make the overall source
    # unavailable while public discovery is still possible. Keep both attempts.
    try:
        fallback = public(query=query, storage_root=storage_root, public_web=True)
    except Exception as exc:
        return {'news': [], 'source_refs': refs,
                'errors': ['hosted_web_search_unavailable', 'public_web_search_failed:'+type(exc).__name__]}
    return {**fallback, 'source_refs': [*refs, *fallback['source_refs']],
            'method': 'public_rss_fallback',
            'errors': fallback['errors'] if fallback['news'] else ['hosted_web_search_unavailable', *fallback['errors']]}
