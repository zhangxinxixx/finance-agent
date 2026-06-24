"""Mem0 上下文预取脚本。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.analysis.memory.automation_adapter import build_automation_memory_context  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("用法: python scripts/mem0_prefetch_context.py <task>", file=sys.stderr)
        return 2

    task = " ".join(arg.strip() for arg in args if arg.strip()).strip()
    if not task:
        print("用法: python scripts/mem0_prefetch_context.py <task>", file=sys.stderr)
        return 2

    try:
        context = build_automation_memory_context(task)
    except Exception as exc:
        print(f"Mem0 上下文预取执行失败: {exc}", file=sys.stderr)
        return 1

    print("# Mem0 上下文预取")
    print(f"# task: {task}")
    print()
    print(context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
