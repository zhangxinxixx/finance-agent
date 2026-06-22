#!/usr/bin/env python3
"""Switch visible Codex skill directories by task profile.

The router is intentionally file-system based because Codex discovers skills
from configured directories before a session starts. Moving a skill directory
to the matching disabled root hides it from future sessions; applying `full`
restores all hidden skills.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SkillRoot:
    name: str
    active: Path
    disabled: Path


ROOTS = [
    SkillRoot(
        "repo",
        REPO_ROOT / ".codex" / "skills",
        REPO_ROOT / ".codex" / "skills-disabled",
    ),
    SkillRoot(
        "codex",
        Path.home() / ".codex" / "skills",
        Path.home() / ".codex" / "skills-disabled",
    ),
    SkillRoot(
        "agents",
        Path.home() / ".agents" / "skills",
        Path.home() / ".agents" / "skills-disabled",
    ),
]


LEAN = {
    "repo": {
        "finance-agent-grill-with-docs",
        "finance-agent-planning-with-files",
        "finance-agent-live-acceptance",
        "finance-agent-script-hardening",
        "repo-map",
        "release-checklist",
    },
    "codex": {
        "api-and-interface-design",
        "code-review-and-quality",
        "git-workflow-and-versioning",
        "incremental-implementation",
        "sqlalchemy-db-models",
        "systematic-debugging",
        "test-driven-development",
    },
    "agents": {
        "caveman",
        "caveman-help",
        "caveman-stats",
    },
}

FRONTEND = {
    "repo": {
        "finance-agent-browser-trace",
        "finance-agent-frontend-design-qa",
        "finance-agent-frontend-visual-polish",
        "frontend-page-refactor",
    },
    "codex": {
        "browser-testing-with-devtools",
        "design-taste-frontend",
        "finance-agent-frontend-dev",
        "frontend-api-integration-patterns",
        "frontend-design",
        "frontend-ui-engineering",
        "open-design-finance-polish",
        "playwright",
        "react-best-practices",
        "webapp-testing",
    },
    "agents": {
        "design-taste-frontend",
        "gpt-taste",
        "high-end-visual-design",
        "image-to-code",
        "imagegen-frontend-mobile",
        "imagegen-frontend-web",
        "minimalist-ui",
        "redesign-existing-projects",
    },
}

REPORTS = {
    "repo": {
        "cme-bulletin-debug",
        "cme-gold-parser-regression",
        "cme-options-analysis",
        "finance-agent-report-artifact-qa",
        "gold-daily-analysis",
        "macro-pipeline",
        "macro-snapshot-check",
        "premarket-smoke-test",
        "vault-sync-guard",
    },
    "codex": {
        "finance-agent-analysis-pipelines",
        "source-driven-development",
    },
    "agents": set(),
}

OBSIDIAN = {
    "repo": {
        "vault-sync-guard",
    },
    "codex": {
        "documentation-and-adrs",
        "obsidian-bases",
        "obsidian-cli",
        "obsidian-markdown",
    },
    "agents": set(),
}

LARK = {
    "repo": {
        "feishu-doc-renderer",
        "feishu-section-publish",
    },
    "codex": set(),
    "agents": {
        "lark-approval",
        "lark-apps",
        "lark-attendance",
        "lark-base",
        "lark-calendar",
        "lark-contact",
        "lark-doc",
        "lark-drive",
        "lark-event",
        "lark-im",
        "lark-mail",
        "lark-markdown",
        "lark-minutes",
        "lark-note",
        "lark-okr",
        "lark-openapi-explorer",
        "lark-shared",
        "lark-sheets",
        "lark-skill-maker",
        "lark-slides",
        "lark-task",
        "lark-vc",
        "lark-vc-agent",
        "lark-whiteboard",
        "lark-wiki",
        "lark-workflow-meeting-summary",
        "lark-workflow-standup-report",
    },
}

AGENT_GOVERNANCE = {
    "repo": {
        "finance-agent-agent-governance",
    },
    "codex": {
        "security-and-hardening",
        "security-best-practices",
        "security-threat-model",
    },
    "agents": set(),
}


PROFILE_EXTRAS = {
    "lean": {},
    "frontend": FRONTEND,
    "reports": REPORTS,
    "obsidian": OBSIDIAN,
    "lark": LARK,
    "agent-governance": AGENT_GOVERNANCE,
}


def merge_profile(profile: str) -> dict[str, set[str]] | None:
    if profile == "full":
        return None

    allow = {root.name: set(LEAN.get(root.name, set())) for root in ROOTS}
    extras = PROFILE_EXTRAS[profile]
    for root_name, names in extras.items():
        allow.setdefault(root_name, set()).update(names)
    return allow


def skill_dirs(path: Path) -> dict[str, Path]:
    if not path.exists():
        return {}
    return {
        child.name: child
        for child in path.iterdir()
        if child.is_dir() and (child / "SKILL.md").exists()
    }


def move_skill(src: Path, dst: Path, apply: bool) -> str:
    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            raise RuntimeError(f"destination already exists: {dst}")
        shutil.move(str(src), str(dst))
    return f"{src} -> {dst}"


def restore_all(apply: bool) -> list[str]:
    changes: list[str] = []
    for root in ROOTS:
        for name, src in sorted(skill_dirs(root.disabled).items()):
            dst = root.active / name
            if dst.exists():
                changes.append(f"skip existing active {root.name}/{name}")
                continue
            changes.append(move_skill(src, dst, apply))
    return changes


def apply_profile(profile: str, apply: bool) -> list[str]:
    changes = restore_all(apply)
    allow = merge_profile(profile)
    if allow is None:
        return changes

    for root in ROOTS:
        allowed = allow.get(root.name, set())
        for name, src in sorted(skill_dirs(root.active).items()):
            if name in allowed:
                continue
            dst = root.disabled / name
            changes.append(move_skill(src, dst, apply))
    return changes


def status() -> list[str]:
    lines: list[str] = []
    for root in ROOTS:
        active = sorted(skill_dirs(root.active))
        disabled = sorted(skill_dirs(root.disabled))
        lines.append(
            f"{root.name}: active={len(active)} disabled={len(disabled)} "
            f"active_names={','.join(active)}"
        )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status")

    for command in ("dry-run", "apply"):
        sub = subparsers.add_parser(command)
        sub.add_argument(
            "profile",
            choices=[
                "lean",
                "frontend",
                "reports",
                "obsidian",
                "lark",
                "agent-governance",
                "full",
            ],
        )

    args = parser.parse_args()

    if args.command == "status":
        lines = status()
    else:
        lines = apply_profile(args.profile, apply=args.command == "apply")

    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
