from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.analysis.snapshots.report_continuity import (
    attach_prior_report_contexts,
    load_prior_report_contexts,
    validate_prior_report_contexts,
)
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables
from database.models.analysis import AnalysisBase, AnalysisSnapshot


CUTOFF = "2026-10-07T01:30:00+00:00"


@pytest.fixture
def registry(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'registry.sqlite'}")
    ensure_report_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield tmp_path, session
    engine.dispose()


def snapshot():
    return {
        "snapshot_id": "current-snapshot",
        "run_id": "current-run",
        "asset": "XAUUSD",
        "trade_date": "2026-10-07",
        "snapshot_time": CUTOFF,
        "input_snapshot_ids": {},
        "source_refs": [],
    }


def register(
    db,
    root,
    *,
    name,
    trade_date,
    generated_at,
    cadence="daily",
    body=None,
    family="final_report_markdown",
    report_type="final_report",
    asset="XAUUSD",
    metadata=None,
):
    text = body or f"# {name}\n\n完整历史正文。\n"
    path = root / "reports" / name / "main.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    content = path.read_bytes()
    report_metadata = {
        "publish_allowed": True,
        "review_status": "pass",
        "output_mode": "accepted",
        "input_snapshot_ids": {"analysis_snapshot": f"snapshot-{name}"},
        "report_cadence": cadence,
        "analysis_cutoff": (generated_at - timedelta(minutes=5)).isoformat(),
        **(metadata or {}),
    }
    item = ReportItem(
        report_id=f"report-{name}",
        family=family,
        report_type=report_type,
        title=name,
        asset=asset,
        trade_date=date.fromisoformat(trade_date),
        run_id=f"run-{name}",
        snapshot_id=f"snapshot-{name}",
        data_status="live",
        lifecycle_status="generated",
        source_refs=[{"source": "report_registry", "source_ref": f"report-{name}", "captured_at": generated_at.isoformat()}],
        report_metadata=report_metadata,
        # Synthetic receipt clocks: this fixture existed before the cutoff.
        created_at=generated_at,
        updated_at=generated_at,
    )
    item.artifacts = [ReportArtifact(
        artifact_id=f"artifact-{name}",
        artifact_type="analysis_md",
        file_path=str(path.relative_to(root)),
        storage_backend="local_fs",
        generated_at=generated_at,
        created_at=generated_at,
        updated_at=generated_at,
        status="generated",
        sha256=sha256(content).hexdigest(),
        byte_size=len(content),
        content_type="text/markdown",
        is_primary=True,
    )]
    db.add(item)
    db.flush()
    return item, path, text


def test_latest_valid_daily_and_weekly_are_selected_independently_and_attached(registry):
    root, db = registry
    register(db, root, name="daily-old", trade_date="2026-10-04",
             generated_at=datetime(2026, 10, 4, 12, tzinfo=timezone.utc))
    _, _, daily = register(db, root, name="daily-new", trade_date="2026-10-06",
                           generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    _, _, weekly = register(db, root, name="weekly", trade_date="2026-10-03", cadence="weekly",
                            generated_at=datetime(2026, 10, 3, 12, tzinfo=timezone.utc))

    loaded = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())

    assert loaded["status"] == "verified"
    assert loaded["contexts"]["daily"]["body"] == daily
    assert loaded["contexts"]["weekly"]["body"] == weekly
    assert loaded["contexts"]["daily"]["formal_state_authority"] is False
    original = snapshot()
    before = deepcopy(original)
    attached = attach_prior_report_contexts(original, loaded)
    assert original == before
    assert attached["input_snapshot_ids"] == {
        "prior_report_daily": "snapshot-daily-new",
        "prior_report_weekly": "snapshot-weekly",
    }
    assert {ref["report_type"] for ref in attached["source_refs"]} == {"final_report"}


def test_missing_weekly_and_missing_validity_metadata_are_explicit(registry):
    root, db = registry
    register(db, root, name="unreviewed", trade_date="2026-10-06",
             generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc),
             metadata={"review_status": None})

    loaded = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())

    assert loaded["contexts"]["daily"]["reason_code"] == "no_valid_report"
    assert loaded["contexts"]["daily"]["details"]["rejected_reason_counts"] == {
        "review_validity_not_proven": 1
    }
    assert loaded["contexts"]["weekly"]["reason_code"] == "no_matching_report"
    assert loaded["contexts"]["daily"]["failure_category"] == "cutoff_or_version_rejected"
    assert loaded["contexts"]["weekly"]["failure_category"] == "no_eligible_prior"


def test_registry_absence_wrong_asset_and_future_rows_never_fallback(tmp_path, registry):
    empty_engine = create_engine(f"sqlite:///{tmp_path / 'missing-tables.sqlite'}")
    empty_db = sessionmaker(bind=empty_engine)()
    unavailable = load_prior_report_contexts(empty_db, storage_root=tmp_path, snapshot=snapshot())
    assert {item["reason_code"] for item in unavailable["contexts"].values()} == {
        "report_registry_unavailable"
    }
    assert all(item['failure_category'] == 'database_unavailable' for item in unavailable['contexts'].values())
    empty_db.close()
    empty_engine.dispose()

    root, db = registry
    register(db, root, name="wrong-asset", trade_date="2026-10-06", asset="GC",
             generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    register(db, root, name="future", trade_date="2026-10-08",
             generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    loaded = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())
    assert all(item["reason_code"] == "no_matching_report" for item in loaded["contexts"].values())


@pytest.mark.parametrize("damage", ["tamper", "symlink_escape", "oversized"])
def test_body_integrity_storage_containment_and_size_fail_closed(registry, damage):
    root, db = registry
    item, path, _ = register(db, root, name=damage, trade_date="2026-10-06",
                             generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    if damage == "tamper":
        path.write_text("changed", encoding="utf-8")
    elif damage == "symlink_escape":
        outside = root.parent / f"outside-{root.name}.md"
        outside.write_text("outside", encoding="utf-8")
        path.unlink()
        path.symlink_to(outside)
    else:
        path.write_text("x" * 128, encoding="utf-8")
        item.artifacts[0].sha256 = sha256(path.read_bytes()).hexdigest()
        item.artifacts[0].byte_size = len(path.read_bytes())

    loaded = load_prior_report_contexts(
        db, storage_root=root, snapshot=snapshot(), max_report_bytes=64
    )

    reasons = loaded["contexts"]["daily"]["details"]["rejected_reason_counts"]
    expected = {
        "tamper": "stored_byte_size_mismatch",
        "symlink_escape": "artifact_missing_or_storage_escape",
        "oversized": "body_oversized",
    }[damage]
    assert reasons == {expected: 1}


def test_body_failure_and_cutoff_rejection_remain_separate_in_model_input(registry):
    from apps.analysis.snapshots.report_continuity import prior_report_context_model_input
    root, db = registry
    _, path, _ = register(db, root, name='missing-body', trade_date='2026-10-06',
                          generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    path.unlink()
    item, _, _ = register(db, root, name='late-version', trade_date='2026-10-06',
                          generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    item.updated_at = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    loaded = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())
    daily = loaded['contexts']['daily']
    assert daily['failure_category'] == 'body_unavailable'
    assert daily['failure_category_counts'] == {'body_unavailable': 1, 'cutoff_or_version_rejected': 1}
    projected = prior_report_context_model_input({**snapshot(), 'prior_report_contexts': loaded})['contexts']['daily']
    assert projected['details'] == daily['details']
    assert projected['failure_category_counts'] == daily['failure_category_counts']
    assert 'body' not in projected


def test_bound_snapshot_database_error_is_not_cutoff_rejection_or_older_fallback(registry):
    root, db = registry
    # Real SQLite query failure: report tables exist, analysis_snapshots does not.
    register(db, root, name='older-valid', trade_date='2026-10-05',
             generated_at=datetime(2026, 10, 5, 12, tzinfo=timezone.utc))
    item, _, _ = register(db, root, name='legacy-needs-lookup', trade_date='2026-10-06',
                          generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    item.report_metadata.pop('analysis_cutoff')
    daily = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())['contexts']['daily']
    assert daily['failure_category'] == 'database_unavailable'
    assert daily['reason_code'] == 'bound_analysis_snapshot_database_unavailable'
    assert daily['details']['verified_candidates'] == 1
    assert 'body' not in daily


def test_legacy_frozen_registry_error_keeps_diagnostics_without_retrying_database():
    from apps.analysis.snapshots.report_continuity import prior_report_context_model_input, CONTEXT_SCHEMA_VERSION
    context = {'schema_version': CONTEXT_SCHEMA_VERSION, 'contexts': {
        cadence: {'status': 'unavailable', 'reason_code': 'report_registry_unavailable',
                  'details': {'error_type': 'OperationalError'}, 'model_input_status': 'not_included'}
        for cadence in ('daily', 'weekly')}}
    before = deepcopy(context)
    projected = prior_report_context_model_input({**snapshot(), 'prior_report_contexts': context})
    assert context == before
    for item in projected['contexts'].values():
        assert item['failure_category'] == 'database_unavailable'
        assert item['details']['error_type'] == 'OperationalError'
        assert 'body' not in item


def test_equal_latest_cutoffs_are_ambiguous_not_filename_sorted(registry):
    root, db = registry
    generated = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    register(db, root, name="a", trade_date="2026-10-06", generated_at=generated)
    register(db, root, name="z", trade_date="2026-10-06", generated_at=generated)

    loaded = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())

    daily = loaded["contexts"]["daily"]
    assert daily["reason_code"] == "ambiguous_latest_valid_report"
    assert daily["details"]["report_ids"] == ["report-a", "report-z"]


def test_attached_body_tamper_and_future_final_cutoff_remove_lineage(registry):
    root, db = registry
    register(db, root, name="daily", trade_date="2026-10-06",
             generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    loaded = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())
    loaded["contexts"]["daily"]["body"] += "tampered"

    checked = validate_prior_report_contexts(loaded, cutoff=CUTOFF)
    attached = attach_prior_report_contexts(snapshot(), checked)

    assert checked["contexts"]["daily"]["reason_code"] == "attached_body_sha256_mismatch"
    assert "prior_report_daily" not in attached["input_snapshot_ids"]
    valid = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())
    future_checked = validate_prior_report_contexts(valid, cutoff="2026-10-06T10:00:00+00:00")
    assert future_checked["contexts"]["daily"]["reason_code"] == "context_time_not_before_final_cutoff"


def test_same_day_earlier_report_is_selected_by_cutoff_not_trade_date(registry):
    root, db = registry
    register(db, root, name="same-day", trade_date="2026-10-07",
             generated_at=datetime(2026, 10, 7, 1, tzinfo=timezone.utc))
    daily = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())["contexts"]["daily"]
    assert daily["status"] == "verified"
    assert daily["actual_cutoff"] == "2026-10-07T00:55:00+00:00"


def test_unknown_cutoff_never_uses_generated_time(registry):
    root, db = registry
    AnalysisBase.metadata.create_all(db.get_bind())
    item, _, _ = register(db, root, name="unknown-cutoff", trade_date="2026-10-06",
                          generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    item.report_metadata.pop("analysis_cutoff")
    daily = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())["contexts"]["daily"]
    assert daily["status"] == "unavailable"
    assert daily["details"]["rejected_reason_counts"] == {"report_cutoff_invalid": 1}


def test_legacy_registry_cutoff_uses_exact_hashed_analysis_snapshot(registry):
    import json
    root, db = registry
    AnalysisBase.metadata.create_all(db.get_bind())
    item, _, _ = register(db, root, name="legacy", trade_date="2026-10-06",
                          generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    item.report_metadata.pop("analysis_cutoff")
    payload = {"asset": item.asset, "run_id": item.run_id, "snapshot_id": item.snapshot_id,
               "trade_date": item.trade_date.isoformat(), "snapshot_time": "2026-10-06T11:00:00+00:00",
               "input_snapshot_ids": item.report_metadata["input_snapshot_ids"], "source_refs": item.source_refs}
    path = root / "bound-snapshot.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    db.add(AnalysisSnapshot(snapshot_id=item.snapshot_id, asset=item.asset, trade_date=item.trade_date,
                           run_id=item.run_id, snapshot_time=datetime(2026, 10, 6, 11, tzinfo=timezone.utc),
                           status="success", payload=payload, input_snapshot_ids=payload["input_snapshot_ids"],
                           source_refs=payload["source_refs"], artifact_path=str(path),
                           payload_sha256=sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()))
    db.flush()
    daily = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())["contexts"]["daily"]
    assert daily["status"] == "verified"
    assert daily["actual_cutoff"] == payload["snapshot_time"]
    assert daily["cutoff_source"] == "verified_analysis_snapshot.snapshot_time"
    path.write_text('{}', encoding="utf-8")
    invalid = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())["contexts"]["daily"]
    assert invalid["status"] == "unavailable"


@pytest.mark.parametrize("damage", ["asset", "snapshot", "cadence", "jin10"])
def test_attached_context_binding_and_excluded_source(registry, damage):
    root, db = registry
    register(db, root, name="daily", trade_date="2026-10-06",
             generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    loaded = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())
    if damage == "asset":
        loaded["contexts"]["daily"]["asset"] = "GC"
    elif damage == "snapshot":
        loaded["current_snapshot_id"] = "other-snapshot"
    elif damage == "cadence":
        loaded["contexts"]["daily"]["cadence"] = "weekly"
    else:
        loaded["contexts"]["daily"]["source_refs"].append({"source_url": "https://api.jin10.com/data"})
    attached = attach_prior_report_contexts(snapshot(), loaded)
    assert attached["prior_report_contexts"]["contexts"]["daily"]["status"] == "unavailable"
    assert "prior_report_daily" not in attached["input_snapshot_ids"]


def test_jin10_provenance_report_is_not_selected(registry):
    root, db = registry
    item, _, _ = register(db, root, name="excluded", trade_date="2026-10-06",
                          generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    item.source_refs = [{"source_url": "https://www.jin10.com/article"}]
    daily = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())["contexts"]["daily"]
    assert daily["details"]["rejected_reason_counts"] == {"excluded_jin10_provenance": 1}


def test_final_storage_recheck_detects_file_change_after_registry_load(registry):
    root, db = registry
    _, path, _ = register(db, root, name="daily", trade_date="2026-10-06",
                          generated_at=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    loaded = load_prior_report_contexts(db, storage_root=root, snapshot=snapshot())
    path.write_text("changed after load", encoding="utf-8")

    attached = attach_prior_report_contexts(snapshot(), loaded, storage_root=root)

    assert attached["prior_report_contexts"]["contexts"]["daily"]["reason_code"] == "persisted_body_sha256_mismatch"
    assert "prior_report_daily" not in attached["input_snapshot_ids"]
