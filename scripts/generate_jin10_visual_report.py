#!/usr/bin/env python3
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

    parser = argparse.ArgumentParser(description="Generate or apply Jin10 visual HTML report from raw article report.")
    parser.add_argument("--raw-report-json", required=True, help="Path to raw_article_report.json")
    parser.add_argument("--output", default=None, help="Output path for the generated prompt")
    parser.add_argument("--agent-response", default=None, help="Path to the LLM HTML response")
    parser.add_argument("--html-output", default=None, help="Target HTML output path when --agent-response is provided")
    args = parser.parse_args()

    raw_path = Path(args.raw_report_json)
    if not raw_path.exists():
        print(f"ERROR: raw report not found: {raw_path}", file=sys.stderr)
        sys.exit(1)

    raw_report = json.loads(raw_path.read_text(encoding="utf-8"))

    if args.agent_response:
        _apply_html_response(raw_report, args.agent_response, args.html_output)
        return

    from apps.analysis.jin10.llm_visual_report import build_visual_report_prompt

    prompt = build_visual_report_prompt(raw_report)
    if args.output:
        Path(args.output).write_text(prompt, encoding="utf-8")
        print(f"Prompt written: {args.output}")
    else:
        print(prompt)


def _apply_html_response(raw_report: dict, response_path: str, html_output: str | None) -> None:
    from apps.analysis.jin10.llm_visual_report import parse_visual_report_html

    html = parse_visual_report_html(Path(response_path).read_text(encoding="utf-8"))
    if not html:
        print("ERROR parsing agent response: empty html", file=sys.stderr)
        sys.exit(1)
    if html_output:
        Path(html_output).write_text(html, encoding="utf-8")
        print(
            json.dumps(
                {
                    "trade_date": raw_report.get("trade_date"),
                    "article_id": raw_report.get("article_id"),
                    "html_output": html_output,
                },
                ensure_ascii=False,
            )
        )
        return
    print(html)


if __name__ == "__main__":
    main()
