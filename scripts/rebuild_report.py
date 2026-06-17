"""Regenerate final_report.md with Chinese renderer for a given date."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path("/home/zxx/workspace/finance-agent")
sys.path.insert(0, str(PROJECT))

from apps.analysis.agents import AgentBias, AgentOutput, AgentStatus  # noqa: E402
from apps.renderer.markdown.final_report import render_final_report_markdown  # noqa: E402
from apps.output.final_report import write_final_report  # noqa: E402


def rebuild(date_str: str, run_id: str):
    snap_path = PROJECT / "storage" / "features" / "snapshots" / "XAUUSD" / date_str / run_id / "premarket_snapshot.json"
    if not snap_path.exists():
        print(f"Snapshot not found: {snap_path}")
        return

    snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)

    def _section(name, module_name="analysis"):
        sec = snapshot.get(name, {})
        data = sec.get("data") if isinstance(sec, dict) else {}
        available = isinstance(sec, dict) and sec.get("status") == "available"
        return AgentOutput(
            version="1.0",
            agent_name=name,
            module=module_name,
            snapshot_id=f"XAUUSD:{date_str}:{run_id}",
            input_snapshot_ids=snapshot.get("input_snapshot_ids", {}),
            status=AgentStatus.SUCCESS if available else AgentStatus.PARTIAL,
            bias=AgentBias.MIXED,
            confidence=0.5 if available else 0.0,
            summary=data.get("summary", "") if isinstance(data, dict) else ("No complete final view" if not available else ""),
            key_findings=data.get("key_findings", []) if isinstance(data, dict) else [],
            risk_points=data.get("risk_points", []) if isinstance(data, dict) else [],
            invalid_conditions=data.get("invalid_conditions", []) if isinstance(data, dict) else [],
            watchlist=data.get("watchlist", []) if isinstance(data, dict) else [],
            source_refs=data.get("source_refs", []) if isinstance(data, dict) and isinstance(data.get("source_refs"), list) else [],
            created_at=now,
        )

    macro_output = _section("macro")
    options_output = _section("options")
    risk_output = _section("risk")
    technical_output = _section("technical")
    positioning_output = _section("positioning")
    news_output = _section("news")
    coordinator_output = _section("coordinator")

    markdown = render_final_report_markdown(
        snapshot=snapshot,
        macro_output=macro_output,
        options_output=options_output,
        risk_output=risk_output,
        technical_output=technical_output,
        positioning_output=positioning_output,
        news_output=news_output,
        coordinator_output=coordinator_output,
        created_at=now,
    )

    write_final_report(
        storage_root=PROJECT / "storage",
        markdown=markdown,
        asset="XAUUSD",
        trade_date=date_str,
        run_id=run_id,
        overwrite=True,
    )
    print(f"✅ Regenerated: {date_str}/{run_id}/final_report.md")
    print("   First 3 lines:")
    for line in markdown.split("\n")[:5]:
        print(f"   {line}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: uv run python scripts/rebuild_report.py <date> <run_id>")
        sys.exit(1)
    rebuild(sys.argv[1], sys.argv[2])
