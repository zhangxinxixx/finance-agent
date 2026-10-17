"""Read existing macro/event archives and report registry; never collect or infer.

Archive selection belongs to the caller. This adapter accepts existing producer
contracts, not prose or FRED index values masquerading as release events.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from apps.analysis.snapshots.report_continuity import load_and_attach_prior_report_contexts
from apps.features.news.formal_events import OfficialEventSnapshot

MAX_ARCHIVE_BYTES = 8_000_000
KINDS = {'macro_release_events', 'official_events', 'fedwatch'}


def _path(root, value):
    path = Path(value)
    path = (path if path.is_absolute() else root/path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('macro_context_storage_escape')
    return path


def verify_context_archives(snapshot, *, source_root):
    """Frozen intake cannot silently switch files between preparation and inference."""
    root = source_root.resolve()
    for ref in snapshot.get('macro_daily_context_archives', []):
        path = _path(root, ref['path'])
        if (not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES
                or sha256(path.read_bytes()).hexdigest() != ref['sha256']):
            raise ValueError('frozen_macro_context_archive_changed')


def _bind_raw_paths(value, *, root, raw_root):
    """Resolve collector-relative refs without inventing receipt times or hashes."""
    if isinstance(value, list):
        return [_bind_raw_paths(v, root=root, raw_root=raw_root) for v in value]
    if not isinstance(value, dict):
        return value
    result = {k: _bind_raw_paths(v, root=root, raw_root=raw_root) for k, v in value.items()}
    for key in ('raw_path', 'raw_artifact_ref'):
        if isinstance(result.get(key), str):
            p = Path(result[key])
            result[key] = str(_path(root, p if p.is_absolute() else raw_root/p))
    if result.get('source') and (result.get('raw_path') or result.get('raw_artifact_ref')):
        result.setdefault('raw_path', result.get('raw_artifact_ref'))
        if result.get('collected_at'):
            result.setdefault('retrieved_at', result['collected_at'])
        if result.get('content_hash'):
            result.setdefault('raw_sha256', result['content_hash'])
    return result


def attach_macro_daily_inputs(
    snapshot, *, source_root: Path, archive_refs=(), db_session=None, prior_report_root: Path | None = None,
):
    """Attach explicitly selected archived evidence, then use the existing gates.

The optional session must be supplied by the caller and read-only. No engine,
table initialization, flush, transaction commit or default model is created.
    """
    candidate = deepcopy(snapshot)
    root = source_root.resolve()
    verify_context_archives(candidate, source_root=root)
    if archive_refs and candidate.get('macro_daily_context_archives'):
        raise ValueError('macro_context_already_frozen')
    bound, status = [], []
    staged = {}
    for ref in archive_refs:
        kind = ref.get('kind')
        if kind not in KINDS or kind in staged:
            raise ValueError('unsupported_or_duplicate_macro_context_kind')
        path = _path(root, ref['path'])
        if not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError('macro_context_archive_missing_or_oversized')
        raw = path.read_bytes()
        if not ref.get('sha256') or sha256(raw).hexdigest() != ref['sha256']:
            raise ValueError('macro_context_archive_hash_mismatch')
        payload = json.loads(raw)
        if kind == 'fedwatch' and isinstance(payload, dict) and payload.get('job') == 'fedwatch':
            payload = payload.get('result')
        if not isinstance(payload, dict):
            raise ValueError('macro_context_object_required')
        if kind == 'macro_release_events':
            payload = {'release_events': payload.get('release_events')}
        raw_root = _path(root, ref.get('raw_root', '.'))
        payload = _bind_raw_paths(payload, root=root, raw_root=raw_root)
        if kind == 'macro_release_events':
            # Existing MacroSnapshot extension: never derive events from rows.
            rows = payload.get('release_events')
            if rows is not None and not isinstance(rows, list):
                raise ValueError('macro_release_events_must_be_a_list')
            staged[kind] = rows or []
            status.append({'kind': kind, 'status': 'loaded' if rows else 'unavailable',
                           'reason': None if rows else 'structured_release_events_absent'})
        elif kind == 'official_events':
            parsed = OfficialEventSnapshot.model_validate(payload)
            staged[kind] = {'status': 'unavailable' if parsed.readiness == 'blocked' else 'available',
                            'data': parsed.model_dump(mode='json')}
            status.append({'kind': kind, 'status': 'loaded', 'events': len(parsed.events)})
        else:
            if 'parse_status' not in payload:
                raise ValueError('fedwatch_collector_contract_required')
            staged[kind] = payload
            status.append({'kind': kind, 'status': 'loaded', 'parse_status': payload['parse_status']})
        bound.append({'kind': kind, 'path': str(path), 'sha256': ref['sha256'],
                      'raw_root': str(raw_root)})
    if candidate.get('macro') is None:
        candidate['macro'] = {}
    if candidate['macro'].get('data') is None:
        candidate['macro']['data'] = {}
    macro = candidate['macro']['data']
    if 'macro_release_events' in staged:
        # Existing and supplied events both survive; duplicate IDs are rejected
        # by build_release_evidence rather than picking an arbitrary winner.
        macro['release_events'] = [*macro.get('release_events', []), *staged['macro_release_events']]
    if 'fedwatch' in staged:
        macro['fedwatch'] = staged['fedwatch']
    if 'official_events' in staged:
        candidate['official_events'] = staged['official_events']
    if bound:
        candidate['macro_daily_context_archives'] = bound
        candidate['macro_daily_context_intake'] = status
    if db_session is not None:
        # Protect read-only preparation even if the supplied Session has pending
        # objects; it must never flush them as a side effect of the SELECT.
        with db_session.no_autoflush:
            candidate = load_and_attach_prior_report_contexts(
                db_session, storage_root=prior_report_root or root, snapshot=candidate,
            )
    elif 'prior_report_contexts' not in candidate:
        from apps.analysis.snapshots.report_continuity import attach_prior_report_contexts
        candidate = attach_prior_report_contexts(candidate, None)
        for item in candidate['prior_report_contexts']['contexts'].values():
            item['reason_code'] = 'report_registry_session_not_supplied'
    return candidate
