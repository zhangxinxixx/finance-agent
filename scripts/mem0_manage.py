#!/usr/bin/env python3
"""Mem0 统一管理入口：增删查改，不再写临时代码。

用法：
  uv run python scripts/mem0.py list user              # 列出 user 层
  uv run python scripts/mem0.py list app               # 列出 app 层
  uv run python scripts/mem0.py list agent             # 列出所有 agent
  uv run python scripts/mem0.py audit                  # 全量审计（检测污染）
  uv run python scripts/mem0.py delete --id <memory_id> # 按 ID 删除
  uv run python scripts/mem0.py purge --entity agent    # 清空 agent 层
  uv run python scripts/mem0.py clean --entity user     # 清理非偏好内容
  uv run python scripts/mem0.py add --entity app --type architecture_decision --content '...'
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("no_proxy", "*")

from apps.analysis.memory.mem0_client import get_mem0_client  # noqa: E402

USER_ID = "local_user"
APP_ID = "finance_agent"
AGENT_IDS = [
    "cme_options_agent", "macro_liquidity_agent", "risk_agent",
    "positioning_agent", "news_agent", "technical_agent",
    "market_odds_agent", "coordinator_agent",
]


def _get_client():
    return get_mem0_client()


def cmd_list(args):
    client = _get_client()
    if args.entity == "user":
        r = client.get_all(filters={"user_id": USER_ID})
    elif args.entity == "app":
        r = client.get_all(filters={"app_id": APP_ID})
    elif args.entity == "agent":
        items = []
        for aid in AGENT_IDS:
            r = client.get_all(filters={"agent_id": aid})
            items.extend(r.get("results", []))
        r = {"results": items}
    else:
        print(f"Unknown entity: {args.entity}")
        return 1

    items = r.get("results", [])
    print(f"{args.entity.upper()}: {len(items)} items\n")
    for i, item in enumerate(items, 1):
        mid = item.get("id", "")[:8]
        mem = item.get("memory", "")[:150]
        print(f"  {i}. [{mid}] {mem}")
    return 0


def cmd_delete(args):
    client = _get_client()
    if not args.id:
        print("需要 --id <memory_id>")
        return 1
    try:
        client.delete(args.id)
        print(f"DELETED {args.id[:12]}...")
    except Exception as e:
        print(f"FAIL: {e}")
        return 1
    return 0


def cmd_purge(args):
    client = _get_client()
    if args.entity == "user":
        r = client.get_all(filters={"user_id": USER_ID})
    elif args.entity == "app":
        r = client.get_all(filters={"app_id": APP_ID})
    elif args.entity == "agent":
        items = []
        for aid in AGENT_IDS:
            r = client.get_all(filters={"agent_id": aid})
            items.extend(r.get("results", []))
        r = {"results": items}
    else:
        print(f"Unknown entity: {args.entity}")
        return 1

    items = r.get("results", [])
    if not args.force:
        print(f"将要删除 {args.entity} 层全部 {len(items)} 条记忆")
        print("加 --force 确认执行")
        return 1

    for item in items:
        try:
            client.delete(item["id"])
        except Exception:
            pass
    print(f"已删除 {len(items)} 条")
    return 0


def cmd_audit(args):
    """全量审计：检测各层污染和异常。"""
    client = _get_client()

    print("=== USER (should be preferences only) ===")
    r = client.get_all(filters={"user_id": USER_ID})
    user_items = r.get("results", [])
    print(f"  Count: {len(user_items)}")
    # Check for non-preference content
    pref_kw = ["用户偏好", "User requires", "User defines"]
    for item in user_items:
        mem = item.get("memory", "")
        if not any(kw in mem for kw in pref_kw):
            print(f"  ⚠️ 非偏好: [{item['id'][:8]}] {mem[:80]}...")

    print("\n=== APP (should be rules/decisions only) ===")
    r = client.get_all(filters={"app_id": APP_ID})
    app_items = r.get("results", [])
    print(f"  Count: {len(app_items)}")
    # Check for duplicates
    seen = {}
    for item in app_items:
        prefix = item.get("memory", "")[:80]
        if prefix in seen:
            print(f"  ⚠️ 重复: [{item['id'][:8]}] ≈ [{seen[prefix][:8]}]")
        else:
            seen[prefix] = item["id"]

    print("\n=== AGENT ===")
    for aid in AGENT_IDS:
        r = client.get_all(filters={"agent_id": aid})
        n = len(r.get("results", []))
        print(f"  {aid}: {n}")

    # Cross-contamination check
    print("\n=== CROSS-CONTAMINATION ===")
    try:
        r = client.search(
            "Assistant reported explained noted updated",
            filters={"user_id": USER_ID, "app_id": APP_ID},
            top_k=50,
        )
        items = r.get("results", [])
        if items:
            print(f"  ⚠️ {len(items)} user+app hybrid items found (old plugin contamination)")
            for item in items:
                print(f"    [{item['id'][:8]}] {item.get('memory','')[:80]}...")
                if args.fix:
                    client.delete(item["id"])
                    print("      → DELETED")
            if args.fix:
                print("  ✅ Cleaned")
        else:
            print("  ✅ No contamination")
    except Exception as e:
        print(f"  Search error: {e}")

    return 0


def cmd_add(args):
    """通过 scripts/mem0_add_project_memory.py 写入。"""
    import subprocess
    script = PROJECT_ROOT / "scripts" / "mem0_add_project_memory.py"
    cmd = [
        "uv", "run", "python", str(script),
        "--content", args.content,
        "--memory-type", args.type or "architecture_decision",
        "--tags", args.tags or "",
    ]
    if args.entity == "app":
        cmd.extend(["--app-id", APP_ID])
    subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Mem0 统一管理")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="列出记忆")
    p_list.add_argument("entity", choices=["user", "app", "agent"])

    p_del = sub.add_parser("delete", help="按 ID 删除")
    p_del.add_argument("--id", required=True)

    p_purge = sub.add_parser("purge", help="清空实体")
    p_purge.add_argument("--entity", choices=["user", "app", "agent"], required=True)
    p_purge.add_argument("--force", action="store_true", help="确认执行")

    p_audit = sub.add_parser("audit", help="全量审计")
    p_audit.add_argument("--fix", action="store_true", help="自动修复污染")

    p_add = sub.add_parser("add", help="新增记忆")
    p_add.add_argument("--entity", choices=["user", "app", "agent"], default="app")
    p_add.add_argument("--type", help="记忆类型 (project_vision/architecture_decision 等)")
    p_add.add_argument("--content", required=True)
    p_add.add_argument("--tags", default="")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    cmds = {
        "list": cmd_list,
        "delete": cmd_delete,
        "purge": cmd_purge,
        "audit": cmd_audit,
        "add": cmd_add,
    }
    return cmds[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
