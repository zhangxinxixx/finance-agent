"""Date-aligned document observations; prose remains publisher evidence."""
from collections import defaultdict
from datetime import datetime


def build_public_evidence_features(documents, *, as_of):
    cutoff = datetime.fromisoformat(as_of.replace('Z', '+00:00')).date().isoformat()
    result = {}
    for document in documents:
        key = document.get('key')
        if key not in {'IAU', 'WGC', 'EIA_STOCKS', 'EIA_SUPPLY', 'FEDWATCH'}:
            continue
        if key in result and document.get('part_index', 0) > 0:
            continue
        source = {'status': document.get('status'), 'reason': document.get('reason'),
                  'document_id': document.get('document_id'), 'source_refs': document.get('source_refs', []),
                  'published_at': document.get('published_at'), 'series': {}}
        groups = defaultdict(dict)
        for observation in document.get('observations', []):
            date = observation.get('observation_date')
            if date and date <= cutoff and observation.get('source_refs'):
                groups[observation['symbol']][date] = observation
        for symbol, rows in groups.items():
            ordered = sorted(rows.values(), key=lambda row: row['observation_date'])
            current, previous = ordered[-1], ordered[-2] if len(ordered) > 1 else None
            comparable = previous and current['unit'] == previous['unit']
            source['series'][symbol] = {
                'current': current, 'previous': previous,
                'delta': current['value']-previous['value'] if comparable else None,
                'comparison_status': 'dated_pair' if comparable else 'level_only',
            }
        source['interpretation'] = ('Dated levels only; no verified subscription flow.' if key == 'IAU'
                                    else 'Monthly publisher commentary; not evidence of daily buying.' if key == 'WGC'
                                    else 'Weekly stocks and dated changes; not proof of cause.' if key == 'EIA_STOCKS'
                                    else 'Source scope and observation time govern use.')
        result[key] = source
    return result
