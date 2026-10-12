"""Dated public evidence. Page prose never becomes a computed market fact."""
import json
import re
from datetime import datetime, timezone
from math import isfinite
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


def parse_public_document(content, *, url):
    soup = BeautifulSoup(content, 'html.parser')
    title = soup.find('h1') or soup.title
    published = soup.find('meta', attrs={'property': 'article:published_time'})
    published = published.get('content') if published else None
    body = None
    updated, publisher = None, None
    for node in soup.find_all('script', type='application/ld+json'):
        try:
            pending = [json.loads(node.string or node.get_text())]
            while pending:
                item = pending.pop()
                if isinstance(item, list):
                    pending.extend(item)
                elif isinstance(item, dict):
                    pending.extend(item.get('@graph', []))
                    types = item.get('@type', [])
                    types = [types] if isinstance(types, str) else types
                    if any(t in {'NewsArticle', 'Article', 'ReportageNewsArticle'} for t in types):
                        published = item.get('datePublished') or published
                        updated = item.get('dateModified') or updated
                        publisher = item.get('publisher', {}).get('name') if isinstance(item.get('publisher'), dict) else publisher
                    if item.get('articleBody'):
                        body = str(item['articleBody'])
                        published = item.get('datePublished') or published
        except (ValueError, TypeError):
            continue
    for node in soup(['script', 'style', 'nav', 'footer', 'header', 'form']):
        node.decompose()
    article = soup.find('article') or soup.find('main')
    body_extraction = 'jsonld_article_body' if body else 'article_dom'
    host = urlsplit(url).hostname
    origin = ('Reuters' if host in {'reuters.com', 'www.reuters.com'} else 'AP'
              if host in {'apnews.com', 'www.apnews.com'} else 'BBC'
              if host in {'www.bbc.com', 'www.bbc.co.uk'} else None)
    if host == 'www.channelnewsasia.com':
        source = soup.select_one('.source')
        credit = source.get_text(' ', strip=True) if source else ''
        origin = 'Reuters' if re.match(r'^Source:\s*Reuters(?:\b|/)', credit) else 'AP' if re.match(r'^Source:\s*(?:AP|Associated Press)(?:\b|/)', credit) else None
        for widget in soup.select('.in-article-games'):
            widget.decompose()
        # Some publisher markup nests paragraphs inside a wrapping <p>.
        # Extract each text node once, excluding the inserted recommendation UI.
        paragraphs = []
        for node in soup.select('.text-long p, .text-long h2, .text-long h3'):
            if node.find(['p', 'h2', 'h3']):
                continue
            paragraphs.append(node.get_text(' ', strip=True))
        body_extraction = 'publisher_article_content_blocks'
    elif body:
        paragraphs = [p.strip() for p in body.splitlines() if p.strip()]
    elif article:
        paragraphs = [p.get_text(' ', strip=True) for p in article.find_all(['h2', 'h3', 'p', 'li'])]
    else:
        paragraphs = []
    text = soup.get_text(' ', strip=True)
    if not published:
        match = re.search(r'Published:\s*(\d{1,2} [A-Za-z]+,? \d{4})', text)
        if match:
            for fmt in ('%d %B, %Y', '%d %B %Y'):
                try:
                    published = datetime.strptime(match[1], fmt).date().isoformat()
                    break
                except ValueError:
                    pass
    metrics = []
    if 'ishares.com/' in url:
        for label, symbol, unit in (
            ('Shares Outstanding', 'IAU_SHARES', 'shares'),
            ('Tonnes in Trust', 'IAU_HOLDINGS', 'tonnes'),
        ):
            match = re.search(re.escape(label)+r'\s+([\d,.]+)\s+as of\s+([A-Za-z]{3} \d{1,2}, \d{4})', text)
            if match:
                metrics.append({'symbol': symbol, 'value': float(match[1].replace(',', '')),
                                'unit': unit, 'observation_date': datetime.strptime(match[2], '%b %d, %Y').date().isoformat(),
                                'value_kind': 'level_not_flow'})
    links = [{'title': a.get_text(' ', strip=True), 'url': urljoin(url, a['href'])}
             for a in (article or soup).find_all('a', href=True)
             if a.get_text(' ', strip=True) and any(k in a['href'] for k in ('.xls', '/goldhub/research/', '/article/', '/business/'))]
    tables = []
    for table in (article or soup).find_all('table'):
        rows = [[cell.get_text(' ', strip=True) for cell in row.find_all(['td', 'th'], recursive=False)]
                for row in table.find_all('tr') if row.find_parent('table') is table]
        if rows:
            tables.append({'caption': table.caption.get_text(' ', strip=True) if table.caption else None,
                           'rows': rows, 'interpretation': 'Source table; preserve headers, dates and units when citing.'})
    if 'pet_stoc_wstk_dcu_nus_w.htm' in url:
        selected = next((t for t in tables if any(sum(bool(re.fullmatch(r'\d{2}/\d{2}/\d{2}', c)) for c in r) >= 2 for r in t['rows'])), None)
        if selected and re.search(r'thousand\s+barrels', text, re.IGNORECASE):
            dates = next([datetime.strptime(c, '%m/%d/%y').date().isoformat() for c in r if re.fullmatch(r'\d{2}/\d{2}/\d{2}', c)] for r in selected['rows'] if sum(bool(re.fullmatch(r'\d{2}/\d{2}/\d{2}', c)) for c in r) >= 2)
            names = {'SPR': 'EIA_SPR', 'Commercial Crude Oil (Excl. Lease Stock)': 'EIA_COMMERCIAL_CRUDE',
                     'Total Motor Gasoline': 'EIA_GASOLINE_STOCKS', 'Distillate Fuel Oil': 'EIA_DISTILLATE_STOCKS'}
            for row in selected['rows']:
                label = next((c for c in row if c in names), None)
                values = [float(c.replace(',', '')) for c in row if re.fullmatch(r'[\d,]+', c)]
                if label and len(values) == len(dates):
                    for date, value in zip(dates[-2:], values[-2:]):
                        metrics.append({'symbol': names[label], 'value': value, 'unit': 'thousand_barrels',
                                        'observation_date': date, 'value_kind': 'weekly_stock_level_not_flow'})
            # Keep one source table for optional expansion, including date headers.
            tables = [selected]
    if metrics and 'ishares.com/' in url:
        paragraphs, tables = [], []
    return {'title': title.get_text(' ', strip=True) if title else None,
            'published_at': published, 'updated_at': updated, 'publisher': publisher,
            'origin_publisher': origin, 'body_extraction': body_extraction,
            'paragraphs': list(dict.fromkeys(p for p in paragraphs if p)),
            'observations': metrics, 'links': links, 'tables': tables,
            'evidence_scope': 'publisher_body' if paragraphs else 'page_without_article_body',
            'causal_attribution': 'not_established_by_publication_alone'}


def parse_fedwatch(payload, *, source_ref, current_target_midpoint=None):
    """CME lower/upper are basis points; calculationTimestamp is UTC per spec.

    currentReportingRt is NOT documented as today's target range. The current
    midpoint must come from separately verified policy data, never this field.
    """
    rows = payload.get('payload') or []
    if not rows or payload.get('metadata', {}).get('totalPages', 1) != 1:
        raise ValueError('missing_or_incomplete_fedwatch_payload')
    meetings, times = [], []
    for row in rows:
        timestamp = datetime.fromisoformat(row['calculationTimestamp'].replace('Z', '+00:00'))
        timestamp = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)
        times.append(timestamp)
        bins = [{'lower': b['lowerRt']/100, 'upper': b['upperRt']/100,
                 'probability': b['probability']} for b in row['rateRange'] if b.get('probability') is not None]
        if (not bins or any(not all(isfinite(float(x)) for x in b.values()) or not 0 <= b['probability'] <= 1
                           or b['lower'] >= b['upper'] for b in bins)
                or abs(sum(b['probability'] for b in bins)-1) > .001):
            raise ValueError('invalid_probability_distribution')
        ordered = sorted(bins, key=lambda b: b['lower'])
        if any(a['upper'] > b['lower'] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('overlapping_rate_ranges')
        meetings.append({'meeting_date': row['meetingDt'], 'bins': bins,
                         'observed_at': timestamp.isoformat()})
    if len({m['meeting_date'] for m in meetings}) != len(meetings):
        raise ValueError('duplicate_meetings')
    return {'provider': 'cme_fedwatch', 'observed_at': min(times).isoformat(),
            'probability_unit': 'fraction', 'rate_unit': 'percent',
            'current_target_midpoint': current_target_midpoint, 'meetings': meetings,
            'source_refs': [source_ref], 'max_age_seconds': 900}
