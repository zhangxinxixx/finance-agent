from datetime import datetime
import json
import uuid

from apps.analysis.snapshots.research_previous import load_previous_research
from apps.runtime.premarket_snapshot_authority import stage_premarket_snapshot_authority
from database.models.task import TaskStatus
from database.models.execution import RunArtifact
from tests.runtime.test_premarket_snapshot_authority import _factory, _running_run, _snapshot, _path, _write


def _stage(db, root, time):
    run = _running_run(db)
    payload = _snapshot(str(run.id), "2026-09-08")
    payload["snapshot_time"] = time
    payload["daily_research"] = {"schema_version": "daily_research.v1", "passport": []}
    path = _path(root, str(run.id), "2026-09-08")
    _write(path, payload)
    stage_premarket_snapshot_authority(db, run_id=str(run.id), snapshot=payload, snapshot_path=path, storage_root=root)
    run.status = TaskStatus.success
    db.commit()
    return payload, path


def test_latest_completed_strictly_older_research_and_tampering(tmp_path):
    root = tmp_path / "storage"
    factory = _factory(tmp_path)
    current = {"asset": "XAUUSD", "run_id": "new", "snapshot_time": "2026-09-08T03:40:00+00:00"}
    with factory() as db:
        first, _ = _stage(db, root, "2026-09-08T03:00:00+00:00")
        latest, path = _stage(db, root, "2026-09-08T03:20:00+00:00")
        db.add(RunArtifact(run_id=uuid.UUID(latest['run_id']), artifact_type='feature_json', file_path='analysis/gold_mainlines/feature_snapshot.v2.json'))
        db.commit()
        _stage(db, root, "2026-09-08T03:40:00+00:00")
        result = load_previous_research(db, storage_root=root, snapshot=current)
        assert result["snapshot_id"] == latest["snapshot_id"] != first["snapshot_id"]
        assert result["formal_state_authority"] is False
        assert datetime.fromisoformat(result["snapshot_time"]) < datetime.fromisoformat(current["snapshot_time"])
        latest["daily_research"]["passport"] = [{"value": 99999}]
        path.write_text(json.dumps(latest))
        bad = load_previous_research(db, storage_root=root, snapshot=current)
        assert bad["status"] == "unavailable"
        assert "passport" not in bad


def test_same_time_predecessors_are_ambiguous(tmp_path):
    root = tmp_path / "storage"
    with _factory(tmp_path)() as db:
        _stage(db, root, "2026-09-08T03:20:00+00:00")
        _stage(db, root, "2026-09-08T03:20:00+00:00")
        result = load_previous_research(db, storage_root=root, snapshot={"asset": "XAUUSD", "run_id": "new", "snapshot_time": "2026-09-08T03:40:00+00:00"})
        assert result["reason"] == "ambiguous_previous_research_time"


def test_report_delta_uses_levels_not_weekly_flows_and_rejects_source_changes():
    from copy import deepcopy
    from apps.features.research.workflow import _delta, report_comparison_rows

    refs = [{'source': 'official_etf', 'source_url': 'https://example.test/gld'}]
    old = {'official_etf': {'status': 'available', 'ticker': 'GLD', 'shares_outstanding': 100,
                           'shares_reported_on': '2026-09-09', 'shares_weekly_delta': -20, 'source_refs': refs},
           'spot_anchor': {'status': 'verified', 'instrument_type': 'spot', 'price': 4400,
                           'price_time': '2026-09-10T12:00:00Z', 'source_refs': [{'source': 'spot', 'source_url': 'https://example.test/spot'}]}}
    new = deepcopy(old)
    new['official_etf']['shares_weekly_delta'] = -30
    new['spot_anchor'].update(price=4380, price_time='2026-09-10T13:00:00Z')
    previous = {'status': 'verified', 'snapshot_id': 'old', 'snapshot_time': '2026-09-10T12:01:00Z',
                'comparison_rows': report_comparison_rows(old)}
    rows = {r['symbol']: r for r in _delta(report_comparison_rows(new), previous)['rows']}
    assert rows['GLD_SHARES']['delta'] == 0
    assert rows['XAUUSD_QUOTE']['delta'] == -20
    assert rows['GLD_TONNES']['delta'] is None
    new['spot_anchor']['source_refs'] = [{'source': 'different', 'source_url': 'https://example.test/spot'}]
    rows = {r['symbol']: r for r in _delta(report_comparison_rows(new), previous)['rows']}
    assert rows['XAUUSD_QUOTE']['delta'] is None
    new['official_etf']['shares_reported_on'] = '2026-09-08'
    rows = {r['symbol']: r for r in _delta(report_comparison_rows(new), previous)['rows']}
    assert rows['GLD_SHARES']['delta'] is None
    before = {'symbol': 'US02Y', 'value': 4.3, 'unit': '%', 'observation_date': '2026-09-11', 'source_refs': refs}
    after = {**before, 'value': 4.4}
    previous['passport'] = [before]
    assert _delta({'US02Y': after}, previous)['rows'][0]['delta'] is None
    previous['passport'][0]['observation_date'] = '2026-09-09'
    after.update(observation_date='2026-09-10', status='stale_or_invalid_time')
    assert _delta({'US02Y': after}, previous)['rows'][0]['delta'] is None


def test_comparison_anchors_respect_each_snapshots_cutoff():
    from apps.features.research.workflow import report_comparison_rows
    research = {'spot_anchor': {'status': 'verified', 'instrument_type': 'spot', 'price': 4400,
                                'price_time': '2026-09-10T12:00:00Z', 'source_refs': []},
                'official_etf': {'status': 'available', 'ticker': 'GLD', 'shares_outstanding': 100,
                                 'shares_reported_on': '2026-09-11'}}
    for cutoff in ('2026-09-10T11:59:00Z', '2026-09-10T12:16:00Z'):
        rows = report_comparison_rows(research, as_of=cutoff)
        assert rows['XAUUSD_QUOTE']['value'] is None
        assert rows['GLD_SHARES']['value'] is None
    assert report_comparison_rows(research, as_of='2026-09-10T12:01:00Z')['XAUUSD_QUOTE']['value'] == 4400
