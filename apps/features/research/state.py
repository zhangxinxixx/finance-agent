"""Pure research proposal contract. Acceptance is a separate audited operation."""

from copy import deepcopy
from hashlib import sha256
import json

NAMESPACE = "gold_research_s.v1"
RULE_VERSION = "gold_research_state.v1"
STATES = {"S1", "S2", "S3", "S4", "S5", "S6", "SX"}


def payload_hash(payload):
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_state_proposal(snapshot, flow, accepted=None):
    accepted = accepted or {}
    state = flow["state"]
    candidate = state.get("candidate_state")
    if candidate is not None and candidate not in STATES:
        raise ValueError("unsupported research state")
    prior = accepted.get("accepted_state")
    technical = snapshot.get("technical", {}).get("data", {})
    price_evidence = bool(technical.get("source_refs") and technical.get("price_structure", {}).get("status") == "available")
    macro_evidence = any(x.get("status") == "available" and x.get("source_refs") for x in flow.get("factor_families", []))
    tests = [{"id": "candidate_rule", "passed": candidate in STATES, "condition": state.get("requirements", {}).get(candidate, "候选证据不足")},
             {"id": "price_evidence", "passed": price_evidence, "condition": "可追溯价格结构"},
             {"id": "macro_evidence", "passed": macro_evidence, "condition": "可追溯宏观因子；与价格属于不同证据类"}]
    tests.extend({"id": q["id"], "passed": q["passed"], "condition": q["reason"]} for q in flow["quality_gate"]["checks"] if q["id"] in {"Q1", "Q2", "Q3", "Q8", "Q10", "Q11"})
    missing = [x for x in tests if not x["passed"]]
    body = {
        "schema_version": "market_state_snapshot.v1", "namespace": NAMESPACE,
        "asset": snapshot["asset"], "run_id": snapshot["run_id"], "source_snapshot_id": snapshot["snapshot_id"],
        "as_of": snapshot["snapshot_time"], "event_type": "proposal",
        "accepted_state": prior, "current_state": prior, "previous_state": accepted.get("previous_state"),
        "candidate_state": candidate, "candidate_label": state.get("candidate_label"),
        "predecessor_id": accepted.get("state_id"), "accepted_at": accepted.get("accepted_at"),
        "transition_status": "INITIALIZATION_REQUIRED" if prior is None else "UNCHANGED" if candidate == prior else "PENDING",
        "transition_confirmed": False, "transition_score": None,
        "trigger_conditions": tests, "confirmed_conditions": [x for x in tests if x["passed"]],
        "missing_conditions": missing,
        "invalidation_conditions": ["前序 Accepted 已变化", "输入快照或来源哈希校验失败", "新数据否定候选的价格与宏观共同条件"],
        "rule_validation": "PASS" if not missing else "BLOCKED",
        "acceptance_policy": "explicit_human_review_in_production_shadow",
        "calculation_version": RULE_VERSION, "input_snapshot_ids": deepcopy(snapshot.get("input_snapshot_ids", {})),
        "source_refs": deepcopy(snapshot.get("source_refs", [])) + deepcopy(accepted.get("source_refs", [])),
        "formal_gold_authority": False, "automatic_trading_allowed": False,
    }
    body["state_id"] = "market_state.v1:" + payload_hash(body)
    return body
