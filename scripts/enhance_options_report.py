#!/usr/bin/env python3
"""LLM-enhanced analysis post-processor for CME gold options reports.

Architecture:
  Pipeline output (options_analysis.json)
      ↓
  build_enhancement_prompt() → prompt for fixed-role analyst agent
      ↓
  Agent (GPT-5.5, fixed role) generates full Markdown report
      ↓
  apply_enhancement() → writes enhanced report

This is a SEPARATE post-processing step, NOT embedded in the main pipeline.
The agent is a fixed-role "黄金期权结构分析师" that reads structured data
and produces a publishable Chinese report.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate LLM enhancement prompt from options analysis snapshot"
    )
    parser.add_argument(
        "--snapshot-json",
        required=True,
        help="Path to options_analysis.json",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for the prompt (default: stdout)",
    )
    parser.add_argument(
        "--agent-response",
        default=None,
        help="Path to agent's Markdown response. If provided, writes enhanced report.",
    )
    parser.add_argument(
        "--report-output",
        default=None,
        help="Path for the enhanced report (only with --agent-response)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run id used for AgentOutput traceability when persisting enhanced output.",
    )
    args = parser.parse_args()

    snap_path = Path(args.snapshot_json)
    if not snap_path.exists():
        print(f"ERROR: snapshot not found: {snap_path}", file=sys.stderr)
        sys.exit(1)

    snapshot = json.loads(snap_path.read_text(encoding="utf-8"))

    if args.agent_response:
        _apply_enhancement(snapshot, args.agent_response, args.report_output, run_id=args.run_id)
        return

    from apps.analysis.options.llm_conclusion import build_conclusion_prompt

    prompt = build_conclusion_prompt(snapshot)
    if args.output:
        Path(args.output).write_text(prompt, encoding="utf-8")
        print(f"Prompt written: {args.output}")
    else:
        print(prompt)


def _apply_enhancement(
    snapshot: dict,
    agent_response_path: str,
    report_output: str | None,
    run_id: str | None = None,
) -> None:
    """Apply the agent's Markdown response to create an enhanced report."""
    from apps.analysis.options.agent_output import persist_options_agent_output
    from apps.analysis.options.llm_conclusion import parse_llm_response

    response_text = Path(agent_response_path).read_text(encoding="utf-8")
    markdown = parse_llm_response(response_text)

    if not markdown:
        print("ERROR parsing agent response: empty markdown", file=sys.stderr)
        sys.exit(1)

    if report_output:
        Path(report_output).write_text(markdown, encoding="utf-8")
        print(f"Enhanced report written: {report_output}")
        persisted = persist_options_agent_output(
            snapshot,
            artifact_dir=Path(report_output).resolve().parent,
            run_id=run_id,
            llm_markdown=markdown,
        )
        print(f"Enhanced agent output persisted: {persisted['agent_output_id']}")
    else:
        print(markdown)


if __name__ == "__main__":
    main()
