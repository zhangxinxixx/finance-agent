"""Point-in-time release facts and consensus, separate from index calculations.

Consumes archived evidence only. Never infers publication/receipt clocks from
an observation month or extracts official numbers from a news headline.
"""
from copy import deepcopy
from datetime import datetime
from math import isfinite

from apps.runtime.source_controls import has_news_only_numeric_lineage


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def _qualified(item, *, cutoff, release_at=None):
    if not isinstance(item, dict) or item.get('status') != 'available':
        return 'evidence_missing'
    if type(item.get('value')) not in (int, float) or not isfinite(item['value']):
        return 'value_invalid'
    if not all(item.get(k) for k in ('indicator', 'reference_period', 'measure', 'unit')):
        return 'metric_identity_missing'
    kind = 'pre_release_consensus' if release_at is not None else 'official_release_value'
    if item.get('evidence_kind') != kind:
        return 'release_or_consensus_kind_not_verified'
    published, received = _time(item.get('published_at')), _time(item.get('retrieved_at'))
    if not cutoff or not published or not received or not published <= received <= cutoff:
        return 'publication_or_receipt_not_verified'
    if release_at is not None and not published <= received < release_at:
        return 'consensus_not_received_before_release'
    refs = item.get('source_refs')
    if not isinstance(refs, list) or not refs or has_news_only_numeric_lineage(item):
        return 'source_lineage_missing_or_excluded'
    for ref in refs:
        if not isinstance(ref, dict):
            return 'source_lineage_missing_or_excluded'
        at = _time(ref.get('retrieved_at'))
        if (not ref.get('source') or not ref.get('raw_path')
                or not (ref.get('source_url') or ref.get('reference'))
                or not at or not published <= at <= received):
            return 'source_lineage_missing_or_excluded'
        if release_at is None and ref.get('source_type') != 'official':
            return 'actual_release_not_official'
    return None


def build_release_evidence(snapshot):
    """Use optional archived releases and the existing formal-event contract.

``macro.data.release_events`` rows carry an event_id plus actual/consensus
observations. Each observation binds indicator, reference_period, measure,
unit, value, published_at, retrieved_at and source_refs. Validation of stored
bytes belongs to prepare_analysis_inputs; this feature enforces time/units.
    """
    cutoff = _time(snapshot.get('snapshot_time'))
    macro = (snapshot.get('macro') or {}).get('data') or {}
    supplied = macro.get('release_events') or []
    if not isinstance(supplied, list):
        supplied = []
    events, rejected = [], []
    counts = {}
    for row in supplied:
        if isinstance(row, dict):
            key = row.get('event_id')
            counts[key] = counts.get(key, 0) + 1
    for row in supplied:
        if not isinstance(row, dict):
            rejected.append({'reason': 'invalid_release_shape'})
            continue
        identity = row.get('event_id')
        actual = row.get('actual')
        reason = _qualified(actual, cutoff=cutoff)
        if not identity or counts[identity] != 1:
            reason = 'missing_or_ambiguous_event_identity'
        if reason:
            rejected.append({'event_id': identity, 'reason': reason})
            continue
        consensus = row.get('consensus')
        reason = _qualified(consensus, cutoff=cutoff, release_at=_time(actual['published_at']))
        if not reason and any(actual[k] != consensus[k] for k in ('indicator', 'reference_period', 'measure', 'unit')):
            reason = 'consensus_metric_mismatch'
        surprise = {'status': 'unavailable', 'reason': reason, 'value': None}
        if not reason:
            surprise = {'status': 'available', 'value': actual['value'] - consensus['value'],
                        'unit': 'percentage_points' if actual['unit'] == 'percent' else actual['unit'],
                        'formula': 'actual_minus_pre_release_consensus',
                        'interpretation': 'numeric_surprise_not_a_gold_direction_or_causal_effect'}
        events.append({'event_id': identity, 'actual': deepcopy(actual),
                       'consensus': deepcopy(consensus) if not reason else {'status': 'unavailable', 'reason': reason},
                       'surprise': surprise,
                       'market_response': {'status': 'unavailable', 'reason': 'no_matched_formal_event_reaction'}})

    # Existing official-event records supply occurrence and bounded responses;
    # their titles do not become numerical actual/consensus observations.
    formal = snapshot.get('official_events') or {}
    formal_status = 'unavailable'
    if isinstance(formal.get('data'), dict):
        from apps.features.news.formal_events import OfficialEventSnapshot
        try:
            parsed = OfficialEventSnapshot.model_validate(formal['data'])
            if (formal.get('status') == 'unavailable' or parsed.readiness == 'blocked'
                    or not cutoff or parsed.as_of > cutoff or any(r.retrieved_at > cutoff for r in parsed.source_refs)):
                raise ValueError('formal_event_after_cutoff')
            formal_status = 'available'
            for event in parsed.events:
                refs = [*event.source_refs, *event.reaction_source_refs]
                if (event.occurred_at > cutoff or any(r.retrieved_at > cutoff for r in refs)
                        or (event.reaction_after_time and event.reaction_after_time > cutoff)):
                    continue
                existing = next((v for v in events if v['event_id'] == event.event_id
                                 and _time(v['actual'].get('published_at') or v.get('published_at'))
                                 == event.occurred_at), None)
                if existing is None:
                    existing = {'event_id': event.event_id, 'title': event.title,
                                'published_at': event.occurred_at.isoformat(),
                                'source_refs': [r.model_dump(mode='json') for r in event.source_refs],
                                'actual': {'status': 'unavailable', 'reason': 'numeric_release_observation_missing'},
                                'consensus': {'status': 'unavailable', 'reason': 'pre_release_consensus_missing'},
                                'surprise': {'status': 'unavailable', 'value': None}}
                    events.append(existing)
                # One official article can appear in multiple feeds. Keep one
                # occurrence and all its archival references, without inventing
                # a numeric actual for records that contain occurrence only.
                source_refs = existing.setdefault('source_refs', [])
                for ref in event.source_refs:
                    value = ref.model_dump(mode='json')
                    if value not in source_refs:
                        source_refs.append(value)
                existing['market_response'] = {
                    'status': event.reaction_status, 'asset': event.reaction_asset,
                    'baseline_time': event.reaction_baseline_time.isoformat() if event.reaction_baseline_time else None,
                    'after_time': event.reaction_after_time.isoformat() if event.reaction_after_time else None,
                    'return_pct': event.reaction_return_pct,
                    'source_refs': [r.model_dump(mode='json') for r in event.reaction_source_refs],
                    'scope': 'bounded_price_response_not_identified_causality',
                }
        except ValueError:
            rejected.append({'reason': 'formal_event_contract_invalid_or_after_cutoff'})
    return {'schema_version': 'macro_release_evidence.v1', 'cutoff': snapshot.get('snapshot_time'),
            'status': 'partial' if events else 'unavailable', 'events': events, 'rejected': rejected,
            'formal_event_coverage': formal_status,
            'reason': None if events else 'no_qualified_release_evidence_in_frozen_input',
            'index_change_is_release_surprise': False,
            'policy_response': {'status': 'unverified',
                                'evidence_ref': 'macro_causal.engines.policy',
                                'reason': 'FedWatch_distribution_is_not_automatically_an_event_aligned_repricing'},
            'causal_attribution': 'requires_competing_explanations_and_matched_windows'}
