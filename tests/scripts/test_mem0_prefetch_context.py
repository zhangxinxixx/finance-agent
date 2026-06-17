"""Codex Mem0 预取脚本测试。"""

from __future__ import annotations

from unittest.mock import patch

from scripts.mem0_prefetch_context import main


def test_main_prints_context_and_returns_zero(capsys) -> None:
    with patch(
        "scripts.mem0_prefetch_context.build_codex_memory_context",
        return_value="## 项目上下文（来自 Mem0 记忆系统）\n\n测试上下文",
    ):
        rc = main(["接入 mem0"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Codex Mem0 接入程序" in captured.out
    assert "测试上下文" in captured.out


def test_main_requires_task_arg(capsys) -> None:
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 2
    assert "用法" in captured.err


def test_main_handles_runtime_error(capsys) -> None:
    with patch(
        "scripts.mem0_prefetch_context.build_codex_memory_context",
        side_effect=RuntimeError("MEM0_API_KEY 未设置。"),
    ):
        rc = main(["接入 mem0"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "MEM0_API_KEY" in captured.err
