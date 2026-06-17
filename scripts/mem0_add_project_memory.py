#!/usr/bin/env python3
"""Add a single project-mainline memory to Mem0 via finance-agent memory layers.

This is the stable CLI for project memory updates. Do not write ad-hoc
MemoryClient.add scripts in agent sessions; use this wrapper so writes pass
through mem0_client + MemoryService + MemoryPolicy and can be verified through
MemoryRouter.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Allow running this file directly via `uv run python scripts/mem0_add_project_memory.py`
# without requiring callers to remember PYTHONPATH=.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.analysis.memory.mem0_client import get_mem0_client  # noqa: E402
from apps.analysis.memory.memory_policy import MemoryPolicy  # noqa: E402
from apps.analysis.memory.memory_router import MemoryRouter  # noqa: E402
from apps.analysis.memory.memory_service import MemoryService  # noqa: E402


def _parse_tags(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _find_matches(ctx: dict[str, list[dict[str, Any]]], needles: list[str], memory_type: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for section, items in ctx.items():
        for item in items:
            text = item.get("memory") or item.get("content") or ""
            meta = item.get("metadata") or {}
            if meta.get("memory_type") == memory_type or any(n and n in text for n in needles):
                out.append(
                    {
                        "section": section,
                        "id": item.get("id"),
                        "memory": text,
                        "metadata": meta,
                    }
                )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Add project-mainline memory to Mem0.")
    parser.add_argument("--content", required=True, help="Memory content summary, <= 2000 chars.")
    parser.add_argument("--memory-type", required=True, help="One of MemoryPolicy allowed project memory types.")
    parser.add_argument("--importance", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--tags", default="", help="Comma-separated tags.")
    parser.add_argument("--source", default="manual")
    parser.add_argument("--user-id", default="xinxi")
    parser.add_argument("--app-id", default="finance_analysis_system")
    parser.add_argument("--project-id", default="finance_analysis_system")
    parser.add_argument("--verify-query", default="", help="Query used for post-write retrieval verification.")
    parser.add_argument("--verify-needle", action="append", default=[], help="Substring expected in retrieved memory; repeatable.")
    parser.add_argument("--verify-attempts", type=int, default=6)
    parser.add_argument("--verify-sleep", type=float, default=5.0)
    args = parser.parse_args()

    ok, reason = MemoryPolicy.validate_record(args.memory_type, args.content)
    if not ok:
        print(json.dumps({"ok": False, "error": reason}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    svc = MemoryService(memory_client=get_mem0_client())
    result = svc.add_memory(
        args.content,
        user_id=args.user_id,
        app_id=args.app_id,
        memory_type=args.memory_type,
        importance=args.importance,
        tags=_parse_tags(args.tags),
        source=args.source,
        infer=False,
        metadata={"scope": "project_mainline", "project_id": args.project_id},
    )

    output: dict[str, Any] = {"ok": True, "add_result": result}

    query = args.verify_query or args.content[:120]
    needles = args.verify_needle or [args.content[:30]]
    router = MemoryRouter(memory_service=svc)
    found: list[dict[str, Any]] = []
    for attempt in range(1, max(args.verify_attempts, 1) + 1):
        if attempt > 1:
            time.sleep(args.verify_sleep)
        ctx = router.retrieve(query, task=query, top_k=8)
        found = _find_matches(ctx, needles, args.memory_type)
        if found:
            output["verify"] = {"ok": True, "attempt": attempt, "matches": found[:5]}
            break
    else:
        output["verify"] = {"ok": False, "attempts": args.verify_attempts, "message": "not searchable yet"}

    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0 if output.get("verify", {}).get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
