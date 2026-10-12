"""Research state ledger with immutable records and compare-and-swap acceptance.

Callers own the transaction. This does not call any model or write canonical
Gold daily-close state; S1–SX is a separately versioned research taxonomy.
"""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from apps.features.research.state import NAMESPACE, STATES, build_state_proposal, payload_hash
from apps.runtime.premarket_snapshot_authority import canonicalize_premarket_snapshot_payload
from database.models.analysis import AnalysisSnapshot
from database.models.market_state import MarketStateHead, MarketStateSnapshot
from database.models.report import ReportArtifact, ReportItem
from database.models.task import TaskRun, TaskStatus
from database.queries.analysis import _sha256_hex


def _time(value):
    t = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def _storage_path(value, root):
    path = Path(value)
    if not path.is_absolute():
        direct = path.resolve()
        path = direct if direct.is_relative_to(root) and direct.exists() else root / path
    if not path.resolve().is_relative_to(root):
        raise ValueError("state artifact is outside storage root")
    return path


def _verified_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("market state payload must be an object")
    required = {
        "state_id", "namespace", "asset", "event_type", "source_snapshot_id",
        "run_id", "as_of", "candidate_state", "transition_status",
        "transition_confirmed", "calculation_version",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError("market state payload fields missing: " + ", ".join(missing))
    if payload["event_type"] not in {"proposal", "acceptance"}:
        raise ValueError("unsupported market state event type")
    if any(payload.get(key) is not None and payload[key] not in STATES for key in ("accepted_state", "candidate_state", "previous_state")):
        raise ValueError("market state taxonomy mismatch")
    if payload["event_type"] == "proposal":
        if payload.get("transition_confirmed") is not False or payload.get("accepted_proposal_id") is not None:
            raise ValueError("proposal cannot confirm or accept a transition")
    elif (payload.get("transition_confirmed") is not True
          or not payload.get("accepted_proposal_id")
          or payload.get("accepted_state") != payload.get("candidate_state")):
        raise ValueError("acceptance event is incomplete")
    body = {key: value for key, value in payload.items() if key != "state_id"}
    if payload["state_id"] != "market_state.v1:" + payload_hash(body):
        raise ValueError("market state content identity mismatch")
    return deepcopy(payload)


def _verified(row):
    if row is None or payload_hash(row.payload) != row.payload_sha256:
        raise ValueError("market state record hash mismatch")
    p = _verified_payload(row.payload)
    for key in ("state_id", "namespace", "asset", "event_type", "source_snapshot_id", "run_id", "accepted_state", "candidate_state", "previous_state", "transition_status", "predecessor_id", "calculation_version", "accepted_proposal_id"):
        if getattr(row, key) != p.get(key):
            raise ValueError("market state indexed projection mismatch: " + key)
    if _time(row.as_of) != _time(p["as_of"]) or (row.accepted_at is None) != (p.get("accepted_at") is None):
        raise ValueError("market state indexed timestamp mismatch")
    if row.accepted_at is not None and _time(row.accepted_at) != _time(p["accepted_at"]):
        raise ValueError("market state accepted timestamp mismatch")
    return deepcopy(p)


def load_accepted_state(db, *, asset="XAUUSD", as_of=None):
    head = db.get(MarketStateHead, (NAMESPACE, asset))
    if head is None or head.state_id is None:
        return {"status": "initialization_required", "namespace": NAMESPACE, "accepted_state": None, "previous_state": None, "state_id": None, "source_refs": []}
    payload = _verified(db.get(MarketStateSnapshot, head.state_id))
    if payload["event_type"] != "acceptance" or payload["namespace"] != NAMESPACE or payload["asset"] != asset:
        raise ValueError("accepted state head is not an acceptance")
    if as_of is not None and _time(payload["accepted_at"]) > _time(as_of):
        raise ValueError("accepted state is later than analysis cutoff")
    # Verify the immutable acceptance lineage, not the most recent report.
    seen = set()
    current = payload
    while current:
        if current["event_type"] != "acceptance" or current["namespace"] != NAMESPACE or current["asset"] != asset or current.get("transition_confirmed") is not True:
            raise ValueError("invalid accepted predecessor record")
        if current["state_id"] in seen:
            raise ValueError("market state predecessor cycle")
        seen.add(current["state_id"])
        proposal = _verified(db.get(MarketStateSnapshot, current["accepted_proposal_id"]))
        if (proposal["event_type"] != "proposal" or proposal["namespace"] != current["namespace"] or proposal["asset"] != current["asset"]
                or proposal["source_snapshot_id"] != current["source_snapshot_id"] or proposal["run_id"] != current["run_id"]
                or proposal["candidate_state"] != current["accepted_state"] or proposal["predecessor_id"] != current["predecessor_id"]):
            raise ValueError("acceptance does not match proposal")
        predecessor = current.get("predecessor_id")
        prior = _verified(db.get(MarketStateSnapshot, predecessor)) if predecessor else None
        if prior is None and current["previous_state"] is not None:
            raise ValueError("bootstrap acceptance has a previous state without predecessor")
        if prior and (prior["accepted_state"] != current["previous_state"] or _time(prior["accepted_at"]) >= _time(current["accepted_at"])):
            raise ValueError("broken accepted predecessor continuity")
        current = prior
    return {**payload, "status": "accepted", "source_refs": [{"source": "market_state_acceptance", "record_id": payload["state_id"], "sha256": payload_hash(payload), "source_snapshot_id": payload["source_snapshot_id"]}]}


def _insert(db, payload):
    old = db.get(MarketStateSnapshot, payload["state_id"])
    if old is not None:
        if _verified(old) != payload:
            raise ValueError("immutable market state conflict")
        return old
    row = MarketStateSnapshot(
        **{k: payload.get(k) for k in ("state_id", "namespace", "asset", "event_type", "source_snapshot_id", "run_id", "accepted_state", "candidate_state", "previous_state", "transition_status", "predecessor_id", "calculation_version")},
        proposal_key=payload["source_snapshot_id"] if payload["event_type"] == "proposal" else None,
        accepted_proposal_id=payload.get("accepted_proposal_id"),
        as_of=_time(payload["as_of"]), accepted_at=_time(payload["accepted_at"]) if payload.get("accepted_at") else None,
        payload=deepcopy(payload), payload_sha256=payload_hash(payload),
    )
    db.add(row)
    db.flush()
    return row


def stage_state_proposal(db, snapshot):
    snapshot = canonicalize_premarket_snapshot_payload(snapshot)
    proposal = _verified_payload(snapshot["gold_workflow"]["state_record"])
    row = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == snapshot["snapshot_id"]))
    if (row is None or row.payload != snapshot or _sha256_hex(row.payload) != row.payload_sha256
            or proposal["source_snapshot_id"] != row.snapshot_id or proposal["run_id"] != row.run_id
            or proposal["asset"] != row.asset or proposal["namespace"] != NAMESPACE
            or _time(proposal["as_of"]) != _time(snapshot["snapshot_time"])):
        raise ValueError("proposal must bind the exact persisted input snapshot")
    if proposal["event_type"] != "proposal" or proposal.get("transition_confirmed"):
        raise ValueError("analysis pipeline can only stage a proposal")
    accepted = load_accepted_state(db, asset=proposal["asset"], as_of=proposal["as_of"])
    if proposal.get("predecessor_id") != accepted.get("state_id"):
        raise ValueError("proposal predecessor changed before staging")
    if build_state_proposal(snapshot, snapshot["gold_workflow"], accepted) != proposal:
        raise ValueError("proposal conditions do not reconstruct before staging")
    return _insert(db, proposal)


def acceptance_review(db, *, proposal_id, storage_root, now=None):
    now = now or datetime.now(UTC)
    proposal = _verified(db.get(MarketStateSnapshot, proposal_id))
    if proposal["event_type"] != "proposal" or not proposal.get("candidate_state"):
        raise ValueError("a concrete research proposal is required")
    row = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == proposal["source_snapshot_id"]))
    root = Path(storage_root).resolve()
    path = _storage_path(row.artifact_path, root) if row else None
    if row is None or _sha256_hex(row.payload) != row.payload_sha256 or not path.resolve().is_relative_to(root) or json.loads(path.read_text()) != row.payload or row.payload.get("gold_workflow", {}).get("state_record") != proposal:
        raise ValueError("proposal source snapshot artifact mismatch")
    task = db.get(TaskRun, uuid.UUID(row.run_id))
    if task is None or task.name != "premarket" or task.task_type != "premarket" or task.status != TaskStatus.success:
        raise ValueError("proposal task has not completed successfully")
    source = row.payload
    if (task.snapshot_id != row.snapshot_id or task.trade_date != row.trade_date.isoformat()
            or source.get("snapshot_id") != row.snapshot_id or source.get("run_id") != row.run_id
            or source.get("asset") != row.asset or source.get("trade_date") != row.trade_date.isoformat()
            or proposal["asset"] != row.asset or proposal["run_id"] != row.run_id
            or _time(source["snapshot_time"]) != _time(row.snapshot_time)
            or _time(proposal["as_of"]) != _time(row.snapshot_time)
            or date.fromisoformat(source["trade_date"]) > _time(source["snapshot_time"]).astimezone(ZoneInfo("Asia/Shanghai")).date()):
        raise ValueError("proposal task/source projection mismatch")
    report = db.scalar(select(ReportItem).where(ReportItem.snapshot_id == row.snapshot_id, ReportItem.run_id == row.run_id, ReportItem.report_type.in_(["observation_report", "final_report"])))
    artifact = db.scalar(select(ReportArtifact).where(ReportArtifact.report_id == report.report_id, ReportArtifact.artifact_type == "analysis_md", ReportArtifact.is_primary.is_(True))) if report else None
    report_path = _storage_path(artifact.file_path, root) if artifact else None
    if artifact is None or not report_path.resolve().is_relative_to(root) or not report_path.is_file() or sha256(report_path.read_bytes()).hexdigest() != artifact.sha256:
        raise ValueError("proposal report artifact missing or hash mismatch")
    if not timedelta(0) <= _time(now) - _time(proposal["as_of"]) <= timedelta(days=3):
        raise ValueError("proposal is future dated or expired; refresh analysis")
    head = load_accepted_state(db, asset=proposal["asset"], as_of=now)
    if proposal["predecessor_id"] != head.get("state_id"):
        raise ValueError("stale proposal predecessor; refresh analysis")
    if build_state_proposal(source, source["gold_workflow"], head) != proposal:
        raise ValueError("proposal conditions do not reconstruct from input and accepted predecessor")
    return {"proposal": proposal, "expected_head": head.get("state_id"), "requires_missing_data_acknowledgement": bool(proposal["missing_conditions"]), "scope": "research_state_only_no_trading_authority"}


def accept_reviewed_proposal(db, *, proposal_id, expected_head, actor, reason, storage_root, acknowledge_missing=False, now=None, initialize=False):
    """Explicit human operation only; no pipeline calls this function."""
    if not actor.strip() or not reason.strip():
        raise ValueError("actor and review reason are required")
    if initialize and (expected_head is not None or acknowledge_missing):
        raise ValueError('initialization requires NONE head and cannot waive missing conditions')
    old = db.scalar(select(MarketStateSnapshot).where(MarketStateSnapshot.accepted_proposal_id == proposal_id, MarketStateSnapshot.namespace == NAMESPACE))
    if old:
        prior = _verified(old)
        if initialize and (prior.get('rule_validation') != 'PASS' or prior.get('missing_conditions')):
            raise ValueError('initialization cannot reuse acceptance with missing conditions')
        if prior["predecessor_id"] == expected_head and prior["approval"]["actor"] == actor and prior["approval"]["reason"] == reason:
            return prior
        raise ValueError("proposal already accepted with different review")
    now = _time(now or datetime.now(UTC))
    review = acceptance_review(db, proposal_id=proposal_id, storage_root=storage_root, now=now)
    proposal = review["proposal"]
    if initialize and (review['expected_head'] is not None or proposal['rule_validation'] != 'PASS'
                       or review['requires_missing_data_acknowledgement']):
        raise ValueError('initialization requires no accepted head and all proposal conditions passing')
    if expected_head != review["expected_head"]:
        raise ValueError("accepted head changed; compare-and-swap rejected")
    if review["requires_missing_data_acknowledgement"] and not acknowledge_missing:
        raise ValueError("review must explicitly acknowledge listed missing conditions")
    head = db.get(MarketStateHead, (NAMESPACE, proposal["asset"]))
    if head is None:
        head = MarketStateHead(namespace=NAMESPACE, asset=proposal["asset"], state_id=None, generation=0)
        db.add(head)
        db.flush()  # Concurrent bootstrap is rejected by the primary key.
    generation = head.generation
    if head.state_id != expected_head:
        raise ValueError("accepted head changed before commit")
    body = {k: deepcopy(v) for k, v in proposal.items() if k != "state_id"}
    body.update(event_type="acceptance", accepted_proposal_id=proposal_id,
                accepted_state=proposal["candidate_state"], current_state=proposal["candidate_state"], previous_state=proposal["accepted_state"],
                transition_status="ACCEPTED", transition_confirmed=True, accepted_at=now.isoformat(),
                approval={"kind": "human", "actor": actor, "reason": reason, "acknowledged_missing_conditions": deepcopy(proposal["missing_conditions"]) if acknowledge_missing else []})
    body["state_id"] = "market_state.v1:" + payload_hash(body)
    _insert(db, body)
    changed = db.execute(update(MarketStateHead).where(MarketStateHead.namespace == NAMESPACE, MarketStateHead.asset == proposal["asset"], MarketStateHead.generation == generation, MarketStateHead.state_id == expected_head).values(state_id=body["state_id"], generation=generation + 1))
    if changed.rowcount != 1:
        raise ValueError("concurrent state acceptance; transaction must roll back")
    return body


def state_history(db, *, asset="XAUUSD", limit=30):
    rows = db.scalars(select(MarketStateSnapshot).where(MarketStateSnapshot.namespace == NAMESPACE, MarketStateSnapshot.asset == asset).order_by(MarketStateSnapshot.as_of.desc(), MarketStateSnapshot.state_id).limit(limit)).all()
    return [_verified(x) for x in rows]


def initialization_readiness(db, *, storage_root, proposal_id=None, asset='XAUUSD', now=None):
    """Read-only readiness, reconstructed from the same evidence as acceptance."""
    now = now or datetime.now(UTC)
    head = load_accepted_state(db, asset=asset, as_of=now)
    result = {'schema_version': 'research_state_readiness.v1', 'namespace': NAMESPACE,
              'status': 'already_initialized' if head.get('state_id') else 'blocked',
              'accepted_state': head.get('accepted_state'), 'accepted_at': head.get('accepted_at'),
              'expected_head': head.get('state_id'), 'candidate_state': None,
              'proposal_id': proposal_id, 'blockers': [], 'state_delta': None,
              'formal_gold_authority': False, 'automatic_trading_allowed': False}
    if proposal_id is None:
        latest = db.scalar(select(MarketStateSnapshot).where(
            MarketStateSnapshot.namespace == NAMESPACE, MarketStateSnapshot.asset == asset,
            MarketStateSnapshot.event_type == 'proposal'
        ).order_by(MarketStateSnapshot.as_of.desc(), MarketStateSnapshot.state_id).limit(1))
        proposal_id = latest.state_id if latest else None
    result['proposal_id'] = proposal_id
    if not proposal_id:
        result['blockers'] = ['persisted_proposal_missing']
        return result
    try:
        review = acceptance_review(db, proposal_id=proposal_id, storage_root=storage_root, now=now)
        p = review['proposal']
        if p['asset'] != asset:
            raise ValueError('proposal asset mismatch')
        result.update(candidate_state=p['candidate_state'], source_snapshot_id=p['source_snapshot_id'],
                      rule_version=p['calculation_version'], as_of=p['as_of'],
                      missing_conditions=deepcopy(p['missing_conditions']))
        result['state_delta'] = {'from': head.get('accepted_state'), 'to_candidate': p['candidate_state'],
                                 'kind': 'initialization' if not head.get('state_id') else 'unchanged' if p['candidate_state'] == head['accepted_state'] else 'pending_transition',
                                 'confirmed': False}
        result['blockers'] = [x['id'] for x in p['missing_conditions']]
        if not result['blockers'] and not head.get('state_id'):
            result['status'] = 'ready_for_explicit_initialization'
        result['next_action'] = 'review exact report then --accept --initialize --expected-head NONE' if result['status'] == 'ready_for_explicit_initialization' else 'refresh missing evidence and create a new proposal'
    except (ValueError, OSError) as exc:
        # Do not emit source payloads or exception text containing source URLs.
        result['blockers'] = ['proposal_evidence_validation_failed']
        result['validation_error_type'] = type(exc).__name__
        result['next_action'] = 'review the proposal with --proposal-id; refresh expired or invalid evidence'
    return result
