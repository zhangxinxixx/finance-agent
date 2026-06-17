from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.analysis.jin10.agent_analysis import build_jin10_agent_analysis_report_with_llm
from apps.renderer.markdown.jin10_agent_analysis import render_jin10_agent_analysis_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Jin10 agent analysis from existing raw_article_report.json and daily_analysis.json.")
    parser.add_argument("--raw-report-json", required=True, help="Path to raw_article_report.json")
    parser.add_argument("--daily-analysis-json", required=True, help="Path to daily_analysis.json")
    parser.add_argument("--output-dir", required=True, help="Directory to write agent_analysis_report.{json,md}")
    args = parser.parse_args()

    raw_path = Path(args.raw_report_json)
    daily_path = Path(args.daily_analysis_json)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_report = json.loads(raw_path.read_text(encoding="utf-8"))
    daily_report = json.loads(daily_path.read_text(encoding="utf-8"))

    report = build_jin10_agent_analysis_report_with_llm(raw_report, daily_report)
    markdown = render_jin10_agent_analysis_markdown(report)

    payload = report.model_dump(mode="json") if hasattr(report, "model_dump") else report.to_dict()
    (output_dir / "agent_analysis_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "agent_analysis_report.md").write_text(markdown, encoding="utf-8")

    print(
        json.dumps(
            {
                "raw_report_json": str(raw_path),
                "daily_analysis_json": str(daily_path),
                "agent_analysis_report_json": str(output_dir / "agent_analysis_report.json"),
                "agent_analysis_report_md": str(output_dir / "agent_analysis_report.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
