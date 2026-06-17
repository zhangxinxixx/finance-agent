#!/usr/bin/env python3
"""每日会话整理：读取 run-staging 桶 → 分类 → 提升到永久层 → 清空 run。

用法：
  uv run python scripts/mem0_daily_consolidate.py                          # 整理昨天的
  uv run python scripts/mem0_daily_consolidate.py --date 2026-05-21        # 指定日期
  uv run python scripts/mem0_daily_consolidate.py --date 2026-05-21 --dry-run  # 预览不执行
  uv run python scripts/mem0_daily_consolidate.py --run-id run-staging-test-smoke --dry-run  # 测试/特殊桶
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.analysis.memory.mem0_client import get_mem0_client  # noqa: E402
from apps.analysis.memory.memory_policy import classify_entity  # noqa: E402

# ── 常量 ──────────────────────────────────────────────
USER_ID = "xinxi"
APP_ID = "finance_analysis_system"
DEFAULT_SIMILARITY_THRESHOLD = 0.85  # 去重阈值（暂用内容前 80 字符比较）


def _build_run_id(date_str: str) -> str:
    return f"run-staging-{date_str}"


def _normalize_date(raw: str) -> str:
    """Normalize YYYY-MM-DD / YYYYMMDD to YYYYMMDD for run-staging IDs."""
    value = raw.strip()
    if re.fullmatch(r"\d{8}", value):
        return value
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y%m%d")
    raise ValueError(f"日期格式无效: {raw!r}，请使用 YYYYMMDD 或 YYYY-MM-DD")


def _get_date(args: argparse.Namespace) -> str:
    if args.date:
        return _normalize_date(args.date)
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


def _fetch_run_memories(client: Any, run_id: str) -> list[dict[str, Any]]:
    """读取 run-staging 桶中的所有记忆。"""
    try:
        resp = client.get_all(
            filters={"run_id": run_id}
        )
        return resp.get("results", [])
    except Exception as e:
        print(f"读取 run 桶失败: {e}", file=sys.stderr)
        return []


def _search_existing(client: Any, entity: str, content: str) -> list[dict[str, Any]]:
    """在目标实体中搜索相似记忆，用于去重。"""
    filters: dict[str, Any] = {}
    if entity == "user":
        filters["user_id"] = USER_ID
    elif entity == "app":
        filters["app_id"] = APP_ID
    elif entity == "agent":
        filters["agent_id"] = "hermes"
    else:
        return []

    try:
        resp = client.search(
            query=content[:200],
            filters=filters,
            top_k=3,
        )
        return resp.get("results", [])
    except Exception:
        return []


def _is_duplicate(content: str, existing: list[dict[str, Any]]) -> bool:
    """简单去重：前 80 字符相同即视为重复。"""
    prefix = content[:80].strip().lower()
    if not prefix:
        return True
    for item in existing:
        existing_prefix = item.get("memory", "")[:80].strip().lower()
        if existing_prefix == prefix:
            return True
    return False


def _promote_memory(
    client: Any,
    entity: str,
    content: str,
    dry_run: bool,
) -> dict[str, Any]:
    """将一条记忆提升到目标实体层。"""
    if dry_run:
        return {"dry_run": True, "entity": entity}

    filters: dict[str, Any] = {}
    if entity == "user":
        filters["user_id"] = USER_ID
    elif entity == "app":
        filters["app_id"] = APP_ID
    elif entity == "agent":
        filters["agent_id"] = "hermes"

    memory_type_map = {
        "user": "user_feedback",
        "app": "architecture_decision",
        "agent": "agent_rule",
    }

    return client.add(
        messages=[{"role": "user", "content": content}],
        **filters,
        infer=False,
        metadata={
            "memory_type": memory_type_map.get(entity, "user_feedback"),
            "source": "daily_consolidate",
            "importance": "medium",
        },
    )


def _delete_run_bucket(client: Any, run_id: str, dry_run: bool) -> None:
    """清空 run-staging 桶（逐条删除，避免 delete_all 通配符误伤其他实体）。"""
    if dry_run:
        return
    try:
        # 只删除明确属于此 run_id 的记忆（不设 agent_id/app_id 通配符）
        resp = client.get_all(
            filters={"run_id": run_id}
        )
        items = resp.get("results", [])
        for item in items:
            try:
                client.delete(item["id"])
            except Exception:
                pass
    except Exception as e:
        print(f"清空 run 桶失败: {e}", file=sys.stderr)


def _classify_session_content(content: str) -> str | None:
    """复用 memory_policy 的 classify_entity 对会话内容分类。"""
    return classify_entity(content, "")


def main() -> int:
    parser = argparse.ArgumentParser(description="每日会话整理")
    parser.add_argument("--date", help="要整理的日期 (YYYYMMDD 或 YYYY-MM-DD)，默认昨天")
    parser.add_argument("--run-id", help="直接指定 run_id（用于测试或特殊补跑）；设置后优先于 --date")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入/删除")
    args = parser.parse_args()

    date_str = _get_date(args)
    run_id = args.run_id.strip() if args.run_id else _build_run_id(date_str)

    print(f"📋 整理日期: {date_str}  (run_id: {run_id})")
    if args.dry_run:
        print("⚠️  预览模式，不实际写入/删除")
    print()

    client = get_mem0_client()
    memories = _fetch_run_memories(client, run_id)

    if not memories:
        print(f"run-staging-{date_str} 桶为空，无需整理。")
        return 0

    print(f"读取到 {len(memories)} 条会话记录\n")

    stats = {"user": 0, "app": 0, "agent": 0, "discard": 0, "duplicate": 0}

    for i, item in enumerate(memories, 1):
        content = item.get("memory", "")
        if not content:
            stats["discard"] += 1
            continue

        entity = _classify_session_content(content)

        if entity is None:
            stats["discard"] += 1
            icon = "🗑️"
            detail = "丢弃"
        elif entity == "run":
            # 整理阶段：run 分类无规则信号，视为临时记录丢弃
            stats["discard"] += 1
            icon = "🗑️"
            detail = "丢弃（临时记录）"
        else:
            # 去重检查
            existing = _search_existing(client, entity, content)
            if _is_duplicate(content, existing):
                stats["duplicate"] += 1
                icon = "♻️"
                detail = f"重复 → {entity}"
            else:
                _promote_memory(client, entity, content, args.dry_run)
                stats[entity] += 1
                icon = "📌"
                detail = f"提升到 {entity}"

        preview = content[:100].replace("\n", " ")
        print(f"  {i:3d}. {icon} [{detail}] {preview}")

    print()
    print("=" * 60)
    print("📊 整理结果:")
    print(f"  提升到 user  : {stats['user']:3d} 条")
    print(f"  提升到 app   : {stats['app']:3d} 条")
    print(f"  提升到 agent : {stats['agent']:3d} 条")
    print(f"  重复跳过     : {stats['duplicate']:3d} 条")
    print(f"  丢弃         : {stats['discard']:3d} 条")
    print("  ─────────────────────")
    print(f"  总计         : {len(memories):3d} 条")

    # 清空 run 桶
    if not args.dry_run and (stats["user"] + stats["app"] + stats["agent"] + stats["duplicate"] + stats["discard"]) == len(memories):
        print()
        _delete_run_bucket(client, run_id, False)
        print(f"✅ 已清空 {run_id} 桶")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
