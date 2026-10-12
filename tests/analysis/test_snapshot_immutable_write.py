from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from apps.analysis.snapshots import write_analysis_snapshot
from apps.runtime.immutable_artifact import ImmutableArtifactConflictError


def test_snapshot_retries_are_idempotent_and_conflicts_preserve_original(tmp_path):
    payload = {"asset": "XAUUSD", "trade_date": "2026-10-09", "run_id": "run-1", "snapshot_id": "snap-1", "value": 1}
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: write_analysis_snapshot(payload, storage_root=tmp_path), range(8)))
    assert len(set(paths)) == 1
    before = paths[0].read_bytes()
    with pytest.raises(ImmutableArtifactConflictError):
        write_analysis_snapshot({**payload, "value": 2}, storage_root=tmp_path)
    assert paths[0].read_bytes() == before
    assert json.loads(before) == payload


def test_invalid_json_cannot_leave_a_partial_snapshot(tmp_path):
    payload = {"asset": "XAUUSD", "trade_date": "2026-10-09", "run_id": "run-1", "value": float('nan')}
    with pytest.raises(ValueError):
        write_analysis_snapshot(payload, storage_root=tmp_path)
    assert not list(tmp_path.rglob('premarket_snapshot.json'))
