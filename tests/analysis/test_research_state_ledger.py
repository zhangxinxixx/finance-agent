from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import json
from hashlib import sha256
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.features.research.state import build_state_proposal
from apps.runtime.premarket_snapshot_authority import canonicalize_premarket_snapshot_payload
from database.models.analysis import AnalysisSnapshot, ensure_analysis_tables
from database.models.market_state import MarketStateSnapshot
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables
from database.models.task import TaskRun, TaskStatus
from database.queries.market_state import accept_reviewed_proposal, load_accepted_state, stage_state_proposal
from database.queries.analysis import _sha256_hex

NOW = datetime(2026, 9, 8, 8, tzinfo=UTC)


@pytest.fixture
def db(tmp_path):
    engine = create_engine("sqlite://")
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    TaskRun.__table__.create(engine)
    with Session(engine) as session:
        yield session


def proposal(db, root, *, key="first", candidate="S4", at=NOW, missing=False):
    flow = {"state": {"candidate_state": candidate, "requirements": {candidate: "two evidence classes"}}, "factor_families": [{"status": "available", "source_refs": [{"source": "Treasury"}]}], "quality_gate": {"checks": [{"id": "Q1", "passed": not missing, "reason": "spot freshness"}]}}
    run_id = str(uuid.uuid5(uuid.NAMESPACE_DNS,key))
    snapshot = {"snapshot_id": key, "asset": "XAUUSD", "trade_date": "2026-09-08", "run_id": run_id, "snapshot_time": at.isoformat(), "technical": {"data": {"source_refs": [{"source": "prices"}], "price_structure": {"status": "available"}}}, "source_refs": [{"source": "Treasury"}], "gold_workflow": flow}
    p = build_state_proposal(snapshot, flow, load_accepted_state(db, as_of=at))
    flow["state_record"] = p
    path = root / (key + ".json")
    path.write_text(json.dumps(snapshot))
    db.add(AnalysisSnapshot(snapshot_id=key, asset="XAUUSD", trade_date=date(2026,9,8), run_id=run_id, snapshot_time=at, payload=snapshot, payload_sha256=_sha256_hex(snapshot), artifact_path=str(path)))
    db.add(TaskRun(id=uuid.UUID(run_id),name="premarket",task_type="premarket",status=TaskStatus.success,snapshot_id=key,trade_date="2026-09-08"))
    report_path = root / (key + ".md")
    report_path.write_text("Reviewed research")
    db.add(ReportItem(report_id=key,family="observation_report_markdown",report_type="observation_report",title="test",snapshot_id=key,run_id=run_id))
    db.add(ReportArtifact(artifact_id=key,report_id=key,artifact_type="analysis_md",file_path=str(report_path),is_primary=True,sha256=sha256(report_path.read_bytes()).hexdigest()))
    db.flush()
    stage_state_proposal(db, snapshot)
    db.commit()
    return p, snapshot


def accept(db, root, p, **extra):
    args = dict(proposal_id=p["state_id"], expected_head=p["predecessor_id"], actor="test-human", reason="reviewed exact report", storage_root=root, now=NOW+timedelta(minutes=10))
    args.update(extra)
    return accept_reviewed_proposal(db, **args)


def test_proposals_never_advance_and_acceptance_survives_reload(db,tmp_path):
    p, s = proposal(db,tmp_path)
    assert p["transition_status"] == "INITIALIZATION_REQUIRED"
    assert load_accepted_state(db)["accepted_state"] is None
    stage_state_proposal(db,s)
    assert len(db.scalars(select(MarketStateSnapshot)).all()) == 1
    accepted = accept(db,tmp_path,p)
    db.commit()
    db.expire_all()
    assert load_accepted_state(db)["accepted_state"] == "S4"
    assert accept(db,tmp_path,p) == accepted
    p2,_ = proposal(db,tmp_path,key="second",candidate="S5",at=NOW+timedelta(hours=1))
    assert p2["accepted_state"] == "S4" and p2["transition_status"] == "PENDING"
    assert load_accepted_state(db)["accepted_state"] == "S4"
    a2 = accept(db,tmp_path,p2,now=NOW+timedelta(hours=2))
    db.commit()
    assert a2["previous_state"] == "S4"
    assert load_accepted_state(db)["accepted_state"] == "S5"


def test_stale_concurrent_proposal_cannot_replace_new_head(db,tmp_path):
    p,_ = proposal(db,tmp_path)
    concurrent,_ = proposal(db,tmp_path,key="concurrent",candidate="S5")
    accept(db,tmp_path,p)
    db.commit()
    with pytest.raises(ValueError,match="predecessor"):
        accept(db,tmp_path,concurrent)
    db.rollback()
    assert load_accepted_state(db)["accepted_state"] == "S4"


def test_tampered_snapshot_missing_ack_and_expiry_fail_closed(db,tmp_path):
    p,s = proposal(db,tmp_path,missing=True)
    with pytest.raises(ValueError,match="acknowledge"):
        accept(db,tmp_path,p)
    with pytest.raises(ValueError,match="expired"):
        accept(db,tmp_path,p,now=NOW+timedelta(days=4),acknowledge_missing=True)
    s["technical"]["data"]["price"] = 9999
    (tmp_path/"first.json").write_text(json.dumps(s))
    with pytest.raises(ValueError,match="artifact mismatch"):
        accept(db,tmp_path,p,acknowledge_missing=True)


def test_hash_tamper_and_future_head_rejected(db,tmp_path):
    p,_ = proposal(db,tmp_path)
    a = accept(db,tmp_path,p)
    db.commit()
    with pytest.raises(ValueError,match="later than"):
        load_accepted_state(db,as_of=NOW)
    row=db.get(MarketStateSnapshot,a["state_id"])
    changed = deepcopy(row.payload)
    changed["accepted_state"] = "SX"
    row.payload = changed
    db.flush()
    with pytest.raises(ValueError,match="hash mismatch"):
        load_accepted_state(db)


def test_malformed_proposal_is_rejected_before_it_enters_ledger(db, tmp_path):
    p, snapshot = proposal(db, tmp_path)
    db.query(MarketStateSnapshot).delete()
    db.commit()
    forged = deepcopy(p)
    forged["transition_confirmed"] = True
    body = {key: value for key, value in forged.items() if key != "state_id"}
    from apps.features.research.state import payload_hash

    forged["state_id"] = "market_state.v1:" + payload_hash(body)
    snapshot["gold_workflow"]["state_record"] = forged
    row = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == snapshot["snapshot_id"]))
    row.payload = snapshot
    row.payload_sha256 = _sha256_hex(snapshot)
    db.flush()

    with pytest.raises(ValueError, match="cannot confirm"):
        stage_state_proposal(db, snapshot)
    assert db.scalars(select(MarketStateSnapshot)).all() == []


def test_stage_canonicalizes_tuple_bearing_snapshot_without_weakening_binding_guards(db):
    run_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "tuple-bearing-snapshot"))
    flow = {
        "state": {"candidate_state": "S4", "requirements": {"S4": "two evidence classes"}},
        "factor_families": [{"status": "available", "source_refs": [{"source": "Treasury"}]}],
        "quality_gate": {"checks": [{"id": "Q1", "passed": True, "reason": "spot freshness"}]},
        "key_levels": {"_identity": ("key-levels", "v1")},
        "execution_zones": {"raw_levels": {"_identity": ("execution-zones", "v1")}},
    }
    snapshot = {
        "snapshot_id": "tuple-bearing-snapshot",
        "asset": "XAUUSD",
        "trade_date": "2026-09-08",
        "run_id": run_id,
        "snapshot_time": NOW.isoformat(),
        "technical": {"data": {"source_refs": [{"source": "prices"}], "price_structure": {"status": "available"}}},
        "source_refs": [{"source": "Treasury"}],
        "gold_workflow": flow,
    }
    proposal_payload = build_state_proposal(snapshot, flow, load_accepted_state(db, as_of=NOW))
    flow["state_record"] = proposal_payload
    persisted_snapshot = canonicalize_premarket_snapshot_payload(snapshot)
    assert persisted_snapshot["gold_workflow"]["key_levels"]["_identity"] == ["key-levels", "v1"]
    assert persisted_snapshot["gold_workflow"]["execution_zones"]["raw_levels"]["_identity"] == ["execution-zones", "v1"]
    db.add(AnalysisSnapshot(
        snapshot_id=snapshot["snapshot_id"], asset="XAUUSD", trade_date=date(2026, 9, 8),
        run_id=run_id, snapshot_time=NOW, payload=persisted_snapshot,
        payload_sha256=_sha256_hex(persisted_snapshot), artifact_path="tuple-bearing-snapshot.json",
    ))
    db.flush()

    staged = stage_state_proposal(db, snapshot)
    assert staged.state_id == proposal_payload["state_id"]
    assert load_accepted_state(db)["accepted_state"] is None

    different_payload = deepcopy(snapshot)
    different_payload["technical"]["data"]["price_structure"]["status"] = "missing"
    with pytest.raises(ValueError, match="exact persisted input snapshot"):
        stage_state_proposal(db, different_payload)

    different_lineage = deepcopy(snapshot)
    different_lineage["gold_workflow"]["state_record"]["run_id"] = str(uuid.uuid4())
    state_record = different_lineage["gold_workflow"]["state_record"]
    body = {key: value for key, value in state_record.items() if key != "state_id"}
    from apps.features.research.state import payload_hash

    state_record["state_id"] = "market_state.v1:" + payload_hash(body)
    with pytest.raises(ValueError, match="exact persisted input snapshot"):
        stage_state_proposal(db, different_lineage)

    row = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == snapshot["snapshot_id"]))
    row.payload_sha256 = "0" * 64
    db.flush()
    with pytest.raises(ValueError, match="exact persisted input snapshot"):
        stage_state_proposal(db, snapshot)


def test_initialization_readiness_is_read_only_and_strict_accept_is_audited(db, tmp_path):
    from database.queries.market_state import initialization_readiness
    empty = initialization_readiness(db, storage_root=tmp_path, now=NOW)
    assert empty['blockers'] == ['persisted_proposal_missing']
    p, _ = proposal(db, tmp_path)
    ready = initialization_readiness(db, storage_root=tmp_path, now=NOW+timedelta(minutes=1))
    assert ready['status'] == 'ready_for_explicit_initialization'
    assert ready['state_delta'] == {'from': None, 'to_candidate': 'S4', 'kind': 'initialization', 'confirmed': False}
    assert load_accepted_state(db)['accepted_state'] is None
    accepted = accept(db, tmp_path, p, initialize=True)
    db.commit()
    assert accepted['accepted_state'] == 'S4'
    assert accepted['source_snapshot_id'] == p['source_snapshot_id']
    assert accepted['accepted_at'] and accepted['calculation_version']
    assert accepted['formal_gold_authority'] is False


def test_initialization_cannot_waive_missing_conditions_or_reuse_stale_evidence(db, tmp_path):
    from database.queries.market_state import initialization_readiness
    p, _ = proposal(db, tmp_path, missing=True)
    r = initialization_readiness(db, storage_root=tmp_path, now=NOW)
    assert r['status'] == 'blocked' and r['blockers'] == ['Q1']
    with pytest.raises(ValueError, match='all proposal conditions'):
        accept(db, tmp_path, p, initialize=True)
    with pytest.raises(ValueError, match='cannot waive'):
        accept(db, tmp_path, p, initialize=True, acknowledge_missing=True)
    r = initialization_readiness(db, storage_root=tmp_path, now=NOW+timedelta(days=4))
    assert r['blockers'] == ['proposal_evidence_validation_failed']
    assert load_accepted_state(db)['accepted_state'] is None
