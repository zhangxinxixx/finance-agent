#!/usr/bin/env python
"""Review/accept one persisted research proposal. Default is read-only review."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from database.models.engine import SessionLocal
    from database.queries.market_state import acceptance_review, accept_reviewed_proposal, initialization_readiness, load_accepted_state, state_history

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal-id")
    parser.add_argument("--init-db", action="store_true", help="Create only the two additive research ledger tables")
    parser.add_argument("--storage-root", default=os.environ.get("STORAGE_ROOT", "./storage"))
    parser.add_argument("--accept", action="store_true")
    parser.add_argument('--readiness', action='store_true', help='Read-only evidence-backed initialization readiness')
    parser.add_argument('--initialize', action='store_true', help='Strict first acceptance: no missing-condition waiver')
    parser.add_argument("--expected-head", help="Exact state_id, or NONE for explicit initialization")
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    parser.add_argument("--acknowledge-missing", action="store_true")
    args = parser.parse_args()
    if args.initialize and (not args.accept or args.expected_head != 'NONE' or args.acknowledge_missing):
        parser.error('--initialize requires --accept --expected-head NONE without --acknowledge-missing')
    if args.readiness and (args.accept or args.init_db):
        parser.error('--readiness cannot mutate state or schema')
    if args.init_db:
        if args.accept or args.proposal_id:
            parser.error("--init-db cannot be combined with a state decision")
        from database.models.engine import engine
        from database.models.market_state import ensure_research_state_tables
        with engine.begin() as connection:
            ensure_research_state_tables(connection)
        print("market_state_snapshot and market_state_heads ready; no state accepted")
        return
    with SessionLocal() as db:
        if args.accept:
            if not all((args.proposal_id, args.expected_head, args.actor, args.reason)):
                parser.error("--accept requires --proposal-id --expected-head --actor --reason")
            try:
                result = accept_reviewed_proposal(db, proposal_id=args.proposal_id, expected_head=None if args.expected_head == "NONE" else args.expected_head,
                    actor=args.actor, reason=args.reason, acknowledge_missing=args.acknowledge_missing, storage_root=Path(args.storage_root), initialize=args.initialize)
                db.commit()
            except Exception:
                db.rollback()
                raise
        elif args.readiness:
            result = initialization_readiness(db, storage_root=Path(args.storage_root), proposal_id=args.proposal_id)
        elif args.proposal_id:
            result = acceptance_review(db, proposal_id=args.proposal_id, storage_root=Path(args.storage_root))
        else:
            result = {"accepted": load_accepted_state(db), "history": state_history(db)}
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
