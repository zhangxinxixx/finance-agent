from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.analysis.jin10.agent_analysis import build_agent_analysis_prompt, parse_agent_analysis_markdown  # noqa: E402


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Jin10 agent analysis with a real LLM model.")
    parser.add_argument("--raw-report-json", required=True, help="Path to raw_article_report.json")
    parser.add_argument("--daily-report-json", default=None, help="Path to daily_analysis.json")
    parser.add_argument("--output", required=True, help="Path to output Markdown report")
    parser.add_argument("--raw-response-output", default=None, help="Optional path to save raw model output")
    parser.add_argument("--model", default="gpt-5.5", help="Model name, default gpt-5.5")
    parser.add_argument("--base-url", default=None, help="Optional OpenAI-compatible base URL")
    parser.add_argument("--api-key", default=None, help="Optional OpenAI-compatible API key")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature")
    parser.add_argument("--timeout", type=float, default=180.0, help="HTTP timeout seconds")
    parser.add_argument("--max-completion-tokens", type=int, default=5000, help="Max completion tokens")
    args = parser.parse_args()

    load_dotenv()
    raw_report_path = Path(args.raw_report_json)
    daily_report_path = Path(args.daily_report_json) if args.daily_report_json else None
    output_path = Path(args.output)
    raw_response_output = Path(args.raw_response_output) if args.raw_response_output else None

    if not raw_report_path.is_file():
        raise SystemExit(f"raw report not found: {raw_report_path}")
    if daily_report_path is not None and not daily_report_path.is_file():
        raise SystemExit(f"daily report not found: {daily_report_path}")

    raw_report = _load_json(raw_report_path)
    daily_report = _load_json(daily_report_path) if daily_report_path else None
    prompt = build_agent_analysis_prompt(raw_report, daily_report)

    resolved_api_key = (args.api_key or os.getenv("OPENAI_API_KEY") or "").strip()
    if not resolved_api_key:
        raise SystemExit("OPENAI_API_KEY is not configured")

    client = OpenAI(
        api_key=resolved_api_key,
        base_url=(args.base_url or os.getenv("OPENAI_BASE_URL") or None),
        timeout=args.timeout,
    )
    completion = client.chat.completions.create(
        model=args.model,
        temperature=args.temperature,
        max_completion_tokens=args.max_completion_tokens,
        messages=[
            {
                "role": "system",
                "content": "你是一名专业的宏观市场与贵金属分析 Agent。只输出最终中文 Markdown 报告正文。",
            },
            {"role": "user", "content": prompt},
        ],
    )
    content = completion.choices[0].message.content or ""
    markdown = parse_agent_analysis_markdown(content)
    if not markdown.strip():
        raise SystemExit("empty model response after markdown parsing")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    if raw_response_output is not None:
        raw_response_output.parent.mkdir(parents=True, exist_ok=True)
        raw_response_output.write_text(content, encoding="utf-8")

    summary = {
        "model": args.model,
        "raw_report_json": str(raw_report_path),
        "daily_report_json": str(daily_report_path) if daily_report_path else None,
        "output": str(output_path),
        "raw_response_output": str(raw_response_output) if raw_response_output else None,
        "markdown_chars": len(markdown),
        "prompt_chars": len(prompt),
        "timeout": args.timeout,
        "max_completion_tokens": args.max_completion_tokens,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
