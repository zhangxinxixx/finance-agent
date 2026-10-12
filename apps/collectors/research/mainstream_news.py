"""Current mainstream reporting via public publisher feeds and article bodies."""
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from uuid import uuid4
from xml.etree import ElementTree
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from apps.collectors.research.public_evidence import (
    _archive, _read, collect_news_discovery, collect_public_document, project_document, validate_public_url,
)

FEEDS = {
    'CNA': 'https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6936',
    'BBC': 'https://feeds.bbci.co.uk/news/business/rss.xml',
}
TOPICS = re.compile(r'\b(gold|oil|crude|fed|federal reserve|inflation|yields?|treasur\w*|dollar|interest rates?|pipeline|iran|petrol|diesel|bank of japan)\b', re.I)


def _time(value):
    if not value:
        raise ValueError('publication_time_missing')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        dt = parsedate_to_datetime(value)
    if dt.tzinfo is None:
        raise ValueError('publication_timezone_missing')
    return dt.astimezone(timezone.utc)


def freshness(value, *, as_of, max_age_hours=24):
    try:
        age = (_time(as_of)-_time(value)).total_seconds()/3600
    except (ValueError, TypeError, OverflowError):
        return {'status': 'UNKNOWN_TIME', 'age_hours': None, 'max_age_hours': max_age_hours}
    return {'status': 'FUTURE' if age < 0 else 'FRESH' if age <= max_age_hours else 'STALE',
            'age_hours': round(age, 2), 'max_age_hours': max_age_hours}


def collect_mainstream_news(*, as_of, storage_root, document_collector=collect_public_document,
                            discovery=collect_news_discovery, client=None):
    if client is None:
        with httpx.Client(timeout=15, trust_env=True) as caller:
            return collect_mainstream_news(as_of=as_of, storage_root=storage_root,
                                           document_collector=document_collector, discovery=discovery, client=caller)
    candidates, refs, errors = [], [], []
    for publisher, url in FEEDS.items():
        identity = uuid4().hex
        try:
            final_url, status, content = _read(client, url)
            raw_path = _archive(storage_root, 'raw', identity, {'url': final_url, 'http_status': status,
                                'retrieved_at': datetime.now(timezone.utc).isoformat(), 'body': content.decode(errors='replace')})
            refs.append({'source': publisher+' public feed', 'source_url': final_url, 'raw_path': raw_path})
            if status != 200:
                errors.append(publisher+':http_'+str(status))
                continue
            for node in ElementTree.fromstring(content).findall('.//item'):
                title, published = node.findtext('title') or '', node.findtext('pubDate')
                if not TOPICS.search(title):
                    continue
                try:
                    link = validate_public_url(node.findtext('link') or '')
                except ValueError:
                    continue
                quality = freshness(published, as_of=as_of)
                candidates.append({'title': title, 'url': link, 'published_at': published,
                                   'publisher': publisher, 'freshness': quality, 'feed_raw_path': raw_path})
        except Exception as exc:
            errors.append(publisher+':'+type(exc).__name__)
    # Three newest relevant CNA stories and one BBC story; URLs are deduplicated.
    # This is a news availability floor, not a daily list of analytical theses.
    selected = []
    for publisher, limit in (('CNA', 3), ('BBC', 1)):
        rows = sorted((r for r in candidates if r['publisher'] == publisher and r['freshness']['status'] == 'FRESH'),
                      key=lambda r: _time(r['published_at']), reverse=True)
        for row in rows:
            if row['url'] not in {r['url'] for r in selected}:
                selected.append(row)
                limit -= 1
            if limit == 0:
                break
    # RSS is a rolling window: a busy company-news day can push still-current
    # macro stories out. Discover from the publisher index before declaring a gap.
    if sum(r['publisher'] == 'CNA' for r in selected) < 3:
        index_url = 'https://www.channelnewsasia.com/business'
        try:
            final_url, status, content = _read(client, index_url)
            index_path = _archive(storage_root, 'raw', uuid4().hex, {
                'url': final_url, 'http_status': status,
                'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'body': content.decode(errors='replace')})
            refs.append({'source': 'CNA business index', 'source_url': final_url, 'raw_path': index_path})
            if status == 200:
                seen = {r['url'] for r in selected}
                count = 0
                for link in BeautifulSoup(content, 'html.parser').select('a[href]'):
                    title = link.get_text(' ', strip=True)
                    url = urljoin(index_url, link['href'])
                    if not TOPICS.search(title) or not url.startswith(index_url+'/') or url in seen:
                        continue
                    try:
                        url = validate_public_url(url)
                    except ValueError:
                        continue
                    row = {'title': title, 'url': url, 'publisher': 'CNA',
                           'published_at': None, 'discovery': 'publisher_index',
                           'freshness': freshness(None, as_of=as_of), 'feed_raw_path': index_path}
                    candidates.append(row)
                    selected.append(row)
                    seen.add(url)
                    count += 1
                    if count == 6:
                        break
            else:
                errors.append('CNA_index:http_'+str(status))
        except Exception as exc:
            errors.append('CNA_index:'+type(exc).__name__)
    if sum(r['publisher'] == 'CNA' for r in selected) < 3:
        try:
            found = discovery(query='CNA dollar oil', storage_root=storage_root, public_web=True)
            refs.extend(found.get('source_refs', []))
            errors.extend(found.get('errors', []))
            for lead in found.get('news', [])[:6]:
                quality = freshness(lead.get('published_at'), as_of=as_of)
                if quality['status'] != 'FRESH' or lead.get('url') in {r['url'] for r in selected}:
                    continue
                row = {**lead, 'publisher': 'CNA' if lead['url'].startswith('https://www.channelnewsasia.com/') else 'search',
                       'freshness': quality, 'discovery': 'public_news_search'}
                candidates.append(row)
                selected.append(row)
        except Exception as exc:
            errors.append('public_news_search:'+type(exc).__name__)
    documents = []
    for candidate in selected:
        raw = document_collector(key=candidate['url'], retrieved_date=as_of[:10], storage_root=storage_root)
        document = project_document(raw)
        # The article's own publication time wins over feed update timestamps.
        quality = freshness(document.get('published_at'), as_of=as_of)
        paragraphs = [p for part in raw.get('parts', []) for p in part]
        article_body = document.get('evidence_scope') == 'publisher_body' and sum(map(len, paragraphs)) >= 600
        document.update(freshness=quality, feed_candidate=candidate,
                        body_verified=article_body, eligible_current_news=bool(article_body and quality['status'] == 'FRESH'))
        documents.append(document)
        refs.extend(document.get('source_refs', []))
    coverage = assess_mainstream_coverage(documents, as_of=as_of)
    missing = coverage['critical_gaps']
    result = {'schema_version': 'mainstream_news.v1', 'as_of': as_of,
              'status': coverage['status'],
              'freshness_policy': {'max_age_hours': 24, 'time_basis': 'article_publication_not_fetch_or_feed_update'},
              'current_news_count': coverage['current_news_count'], 'reuters_count': coverage['reuters_count'],
              'critical_gaps': missing, 'documents': documents, 'candidates': candidates,
              'source_refs': refs, 'errors': errors,
              'limitations': ['转载平台不是第二个独立新闻源；Reuters署名只按原始机构计一次。',
                              '新闻日期不等于行情报价时间；旧稿更新时间不刷新原始发布时间。']}
    result['artifact_path'] = _archive(storage_root, 'parsed', uuid4().hex, result)
    return result


def assess_mainstream_coverage(documents, *, as_of):
    unique = {d.get('url'): d for d in documents if d.get('url')}
    usable = [d for d in unique.values() if d.get('status') == 'available'
              and (d.get('origin_publisher') in {'Reuters', 'AP', 'BBC'} or d.get('publisher') == 'CNA')
              and d.get('evidence_scope') == 'publisher_body'
              and (d.get('body_verified') or d.get('article_body_chars', 0) >= 600)
              and freshness(d.get('published_at'), as_of=as_of)['status'] == 'FRESH']
    reuters = [d for d in usable if d.get('origin_publisher') == 'Reuters']
    missing = ([] if reuters else ['FRESH_REUTERS_BODY']) + ([] if len(usable) >= 2 else ['FRESH_MAINSTREAM_COVERAGE'])
    return {'status': 'available' if not missing else 'partial' if usable else 'unavailable',
            'critical_gaps': missing, 'current_news_count': len(usable), 'reuters_count': len(reuters)}
