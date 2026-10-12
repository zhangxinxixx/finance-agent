from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEV_DISPATCH = ROOT / "scripts" / "dev-dispatch.sh"
DISPATCH_VISIBLE = ROOT / "scripts" / "dispatch-visible.sh"
CODEX_LIVE = ROOT / "scripts" / "codex-live.sh"


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(DEV_DISPATCH), *args],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_reuse_pane_rejects_routing_override(tmp_path: Path) -> None:
    task_file = tmp_path / "task.md"
    task_file.write_text("# Task\n", encoding="utf-8")

    result = _run("--reuse-pane", "--model", "sol", "backend", str(task_file))

    assert result.returncode == 1
    assert "cannot be combined with GPT-5.6 routing overrides" in result.stderr


def test_reuse_pane_rejects_dry_run(tmp_path: Path) -> None:
    task_file = tmp_path / "task.md"
    task_file.write_text("# Task\n", encoding="utf-8")

    result = _run("--reuse-pane", "--dry-run", "frontend", str(task_file))

    assert result.returncode == 1
    assert "cannot be combined with --dry-run" in result.stderr


def test_reuse_pane_rejects_task_front_matter_routing(tmp_path: Path) -> None:
    task_file = tmp_path / "task.md"
    task_file.write_text(
        "---\ncomplexity: low\nmodel: luna\n---\n\n# Task\n",
        encoding="utf-8",
    )

    result = _run("--reuse-pane", "frontend", str(task_file))

    assert result.returncode == 1
    assert "task routing metadata cannot be combined with --reuse-pane" in result.stderr


def test_visible_dispatch_passes_routing_values_into_tmux_command(tmp_path: Path) -> None:
    task_file = tmp_path / "task.md"
    task_file.write_text("# Task\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    tmux_log = tmp_path / "tmux.log"
    fake_tmux = fake_bin / "tmux"
    fake_tmux.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" >> "$TMUX_TEST_LOG"\n',
        encoding="utf-8",
    )
    fake_tmux.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["TMUX_TEST_LOG"] = str(tmux_log)
    env["FINANCE_TMUX_SESSION"] = "test-finance"

    result = subprocess.run(
        [
            str(DISPATCH_VISIBLE),
            "backend",
            str(task_file),
            "high",
            "critical",
            "sol",
            "xhigh",
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    command = next(
        line for line in tmux_log.read_text(encoding="utf-8").splitlines() if line.startswith("cd ")
    )
    assert "scripts/codex-live.sh" in command
    assert f"backend {task_file} high critical sol xhigh" in command


def test_codex_live_uses_role_instructions_without_legacy_profile_selector() -> None:
    script = CODEX_LIVE.read_text(encoding="utf-8")

    assert '--profile "$PROFILE"' not in script
    assert '--config "model_instructions_file=\\"$INSTRUCTIONS_FILE\\""' in script
    assert 'WORKDIR="${CODEX_LIVE_WORKDIR:-$DEFAULT_WORKDIR}"' in script
    assert 'CODEX_LIVE_WORKDIR must be the main checkout or a finance-agent worktree' in script
