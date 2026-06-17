#!/usr/bin/env python3.14
"""P4-10: Minimal, safe report-to-Obsidian sync.

Syncs structured summaries from storage/outputs/ to the Obsidian vault under
``05-分析记录/`` and ``11-输出/``. Never copies raw data, secrets, or large
artifacts.

Usage::

    uv run python scripts/sync_outputs_to_obsidian.py --dry-run       # default
    uv run python scripts/sync_outputs_to_obsidian.py                  # real sync
    uv run python scripts/sync_outputs_to_obsidian.py --overwrite     # force overwrite

Design constraints:
  - Dry-run by default.
  - No raw market data, CME PDFs, or API keys copied.
  - Existing notes are not overwritten unless ``--overwrite``.
  - All vault paths are validated to prevent escape.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Defaults ────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VAULT_ROOT = Path.home() / "wiki" / "Finance-Agent-Knowledge-Vault"
STORAGE_ROOT = PROJECT_ROOT / "storage"

ANALYSIS_RECORDS_DIR = "05-分析记录/每日快照"
OUTPUT_INDEX_DIR = "11-输出"

MAX_REPORT_LENGTH = 800  # chars of summary to sync per report


# ── Public API ───────────────────────────────────────────────────────────


def sync_to_obsidian(
    *,
    storage_root: Path,
    vault_root: Path,
    dry_run: bool = True,
    overwrite: bool = False,
    max_entries: int = 30,
) -> dict[str, Any]:
    """Sync the latest reports to the Obsidian vault.

    Returns a summary dict with counts for reporting.
    """
    vault_root = vault_root.resolve()
    storage_root = storage_root.resolve()

    if not vault_root.exists():
        return {"error": f"Vault root not found: {vault_root}", "synced": 0, "skipped": 0}

    if not storage_root.exists():
        return {"error": f"Storage root not found: {storage_root}", "synced": 0, "skipped": 0}

    # ── Discover reports ────────────────────────────────────────────
    reports = _discover_reports(storage_root, max_entries)

    if not reports:
        return {"message": "No reports found.", "synced": 0, "skipped": 0}

    synced = 0
    skipped = 0
    index_entries: list[dict[str, Any]] = []

    for report in reports:
        note_path = _build_note_path(vault_root, report)
        if note_path is None:
            skipped += 1
            continue

        content = _build_note_content(report, note_path)

        if dry_run:
            print(f"[DRY-RUN] Would write: {note_path.name} ({len(content)} chars)")
            synced += 1
            index_entries.append(report)
            continue

        if note_path.exists() and not overwrite:
            print(f"[SKIP] Already exists (use --overwrite): {note_path.name}")
            skipped += 1
            index_entries.append(report)
            continue

        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(content, encoding="utf-8")
        print(f"[WRITE] {note_path.name}")
        synced += 1
        index_entries.append(report)

    # ── Write/update the output index ───────────────────────────────
    _write_index(vault_root, index_entries, dry_run, overwrite)

    return {"synced": synced, "skipped": skipped, "reports": len(reports)}


# ── Discovery ───────────────────────────────────────────────────────────


def _discover_reports(storage_root: Path, max_entries: int) -> list[dict[str, Any]]:
    """Find final reports and snapshots, sorted by recency."""
    reports: list[dict[str, Any]] = []

    # Scan final_report/XAUUSD/
    final_base = storage_root / "outputs" / "final_report" / "XAUUSD"
    if final_base.exists():
        for date_dir in sorted(final_base.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            for run_dir in sorted(date_dir.iterdir(), reverse=True):
                if not run_dir.is_dir():
                    continue
                md_path = run_dir / "final_report.md"
                json_path = run_dir / "final_report.json"
                if md_path.exists():
                    report = _extract_final_report(date_dir.name, run_dir.name, md_path, json_path)
                    reports.append(report)

    # Scan snapshots
    snap_base = storage_root / "features" / "snapshots" / "XAUUSD"
    if snap_base.exists():
        for date_dir in sorted(snap_base.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            for run_dir in sorted(date_dir.iterdir(), reverse=True):
                if not run_dir.is_dir():
                    continue
                snap_path = run_dir / "premarket_snapshot.json"
                if snap_path.exists():
                    report = _extract_snapshot_report(date_dir.name, run_dir.name, snap_path)
                    # Only add if not already covered by final_report for this date+run
                    existing = {r.get("key") for r in reports}
                    if report.get("key") not in existing:
                        reports.append(report)

    # Sort by trade_date desc, then take max
    reports.sort(key=lambda r: (r.get("trade_date", ""), r.get("generated_at", "")), reverse=True)
    return reports[:max_entries]


def _extract_final_report(
    trade_date: str, run_id: str, md_path: Path, json_path: Path | None
) -> dict[str, Any]:
    """Extract metadata from a final report."""
    content = ""
    try:
        content = md_path.read_text(encoding="utf-8")
    except Exception:
        pass

    # Try to extract structured data from JSON
    structured: dict[str, Any] = {}
    if json_path and json_path.exists():
        try:
            structured = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    stat = md_path.stat()
    return {
        "key": f"final:{trade_date}:{run_id}",
        "type": "final_report",
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_id": structured.get("snapshot_id") or f"XAUUSD:{trade_date}:{run_id}",
        "generated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "status": structured.get("status", "unknown"),
        "bias": structured.get("coordinator_bias") or structured.get("bias", ""),
        "confidence": structured.get("confidence"),
        "source_refs": structured.get("source_refs", []),
        "market_phase": structured.get("market_phase"),
        "market_odds_status": _mo_status(structured),
        "summary": _first_lines(content, MAX_REPORT_LENGTH),
        "content_lines": content.count("\n") + 1,
    }


def _extract_snapshot_report(
    trade_date: str, run_id: str, snap_path: Path
) -> dict[str, Any]:
    """Extract metadata from a premarket analysis snapshot."""
    snap: dict[str, Any] = {}
    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    mo = snap.get("market_odds") or {}
    stat = snap_path.stat()
    return {
        "key": f"snap:{trade_date}:{run_id}",
        "type": "analysis_snapshot",
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_id": snap.get("snapshot_id", f"XAUUSD:{trade_date}:{run_id}"),
        "generated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "status": snap.get("status", "unknown"),
        "bias": "",
        "confidence": None,
        "source_refs": snap.get("source_refs", []),
        "market_phase": _section_status(snap, "macro"),
        "market_odds_status": mo.get("status") if isinstance(mo, dict) else None,
        "aggregate_signal": mo.get("aggregate_signal") if isinstance(mo, dict) else None,
        "summary": _snapshot_summary(snap),
        "content_lines": 0,
    }


# ── Note builder ────────────────────────────────────────────────────────


def _build_note_path(vault_root: Path, report: dict[str, Any]) -> Path | None:
    """Build the output .md path, ensuring it stays inside the vault."""
    trade_date = _safe_component(report.get("trade_date", "unknown"))
    run_id_short = _safe_component(report.get("run_id", "unknown"))[:8]
    rtype = "report" if report.get("type") == "final_report" else "snapshot"
    filename = f"{trade_date}-{run_id_short}-{rtype}.md"
    target = (vault_root / ANALYSIS_RECORDS_DIR / filename).resolve()

    if not str(target).startswith(str(vault_root)):
        print(f"[SECURITY] Path escape blocked: {target}")
        return None
    return target


def _build_note_content(report: dict[str, Any], note_path: Path) -> str:
    """Build a structured markdown note for a report."""
    trade_date = report.get("trade_date", "?")
    run_id = report.get("run_id", "?")
    rtype = report.get("type", "?")
    snapshot_id = report.get("snapshot_id", "?")

    lines = [
        "---",
        "type: analysis-record",
        f"report_type: {rtype}",
        f"trade_date: {trade_date}",
        f"run_id: {run_id}",
        f"snapshot_id: {snapshot_id}",
        f"synced_at: {datetime.now(timezone.utc).isoformat()}",
        "---",
        "",
        f"# {trade_date} 分析快照 ({run_id[:8]})",
        "",
    ]

    status = report.get("status", "unknown")
    bias = report.get("bias", "")
    confidence = report.get("confidence")
    market_phase = report.get("market_phase")
    mo_status = report.get("market_odds_status")

    if status:
        lines.append(f"- **状态**: {status}")
    if bias:
        lines.append(f"- **方向**: {bias}")
    if confidence is not None:
        lines.append(f"- **置信度**: {confidence:.2f}")
    if market_phase:
        lines.append(f"- **宏观阶段**: {market_phase}")
    if mo_status:
        lines.append(f"- **市场赔率**: {mo_status}")
    if report.get("aggregate_signal"):
        lines.append(f"- **赔率信号**: {report['aggregate_signal']}")

    # Source refs
    source_refs = report.get("source_refs", [])
    if source_refs:
        lines.append("")
        lines.append("## 数据来源")
        for ref in source_refs[:10]:
            if isinstance(ref, dict):
                src = ref.get("source", ref.get("symbol", "?"))
                lines.append(f"- `{src}`")

    # Summary
    summary = report.get("summary", "")
    if summary:
        lines.append("")
        lines.append("## 摘要")
        lines.append("")
        lines.append(summary[:MAX_REPORT_LENGTH])

    lines.append("")
    lines.append("---")
    lines.append("*由 [[../../../scripts/sync_outputs_to_obsidian.py|P4-10 同步脚本]] 自动生成*")

    return "\n".join(lines) + "\n"


def _write_index(
    vault_root: Path,
    entries: list[dict[str, Any]],
    dry_run: bool,
    overwrite: bool,
) -> None:
    """Write/update the output index under ``11-输出/``."""
    index_dir = vault_root / OUTPUT_INDEX_DIR
    index_path = index_dir / "报告索引.md"

    if dry_run:
        print(f"[DRY-RUN] Would update index: {index_path}")
        return

    if index_path.exists() and not overwrite:
        print("[SKIP] Index already exists (use --overwrite to rebuild)")
        return

    index_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        "type: index",
        "title: 报告索引",
        f"updated: {datetime.now(timezone.utc).isoformat()}",
        "---",
        "",
        "# 报告索引",
        "",
        "自动同步的生产报告列表。",
        "",
        "| 日期 | Run ID | 类型 | 状态 | 方向 | 赔率 |",
        "|------|--------|------|------|------|------|",
    ]

    for e in entries:
        td = e.get("trade_date", "?")
        rid = e.get("run_id", "?")[:8]
        rtype = "报告" if e.get("type") == "final_report" else "快照"
        status = e.get("status", "?")
        bias = e.get("bias", "-")
        mo = e.get("market_odds_status") or "-"
        lines.append(f"| {td} | {rid} | {rtype} | {status} | {bias} | {mo} |")

    lines.append("")
    lines.append("*由 P4-10 同步脚本自动维护*")

    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[INDEX] Updated: {index_path}")


# ── Helpers ─────────────────────────────────────────────────────────────


def _mo_status(structured: dict[str, Any]) -> str | None:
    mo = structured.get("market_odds") or {}
    if isinstance(mo, dict):
        return mo.get("status")
    return None


def _section_status(snap: dict[str, Any], section: str) -> str | None:
    sec = snap.get(section) or {}
    if isinstance(sec, dict):
        return sec.get("status")
    return None


def _first_lines(text: str, max_chars: int) -> str:
    """Extract first N chars of text, breaking at a paragraph boundary."""
    if len(text) <= max_chars:
        return text
    # Try to break at a double newline
    cutoff = text[:max_chars]
    last_para = cutoff.rfind("\n\n")
    if last_para > max_chars * 0.5:
        return text[:last_para] + "\n\n… (截断)"
    return cutoff + "…"


def _snapshot_summary(snap: dict[str, Any]) -> str:
    """Build a brief summary from snapshot sections."""
    parts = []
    mo = snap.get("market_odds") or {}
    if isinstance(mo, dict):
        agg = mo.get("aggregate_signal")
        if agg and agg != "unavailable":
            parts.append(f"赔率信号: {agg}")
    macro = snap.get("macro") or {}
    if isinstance(macro, dict):
        phase = macro.get("market_phase") or macro.get("status")
        if phase:
            parts.append(f"宏观: {phase}")
    options = snap.get("options") or {}
    if isinstance(options, dict):
        status = options.get("status") or options.get("data_source", {}).get("status", "")
        if status:
            parts.append(f"期权: {status}")
    return "; ".join(parts) if parts else "等待分析"


def _safe_component(value: str) -> str:
    """Normalize a string for use in filenames/paths."""
    import re

    return re.sub(r"[^a-zA-Z0-9._-]", "_", value)


# ── CLI ─────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync finance-agent reports to Obsidian vault",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Preview changes without writing (default: True)",
    )
    parser.add_argument(
        "--no-dry-run", dest="dry_run", action="store_false",
        help="Actually write files",
    )
    parser.add_argument(
        "--overwrite", action="store_true", default=False,
        help="Overwrite existing notes (default: False)",
    )
    parser.add_argument(
        "--vault", type=Path, default=VAULT_ROOT,
        help=f"Obsidian vault root (default: {VAULT_ROOT})",
    )
    parser.add_argument(
        "--storage", type=Path, default=STORAGE_ROOT,
        help=f"Storage root (default: {STORAGE_ROOT})",
    )
    parser.add_argument(
        "--max-entries", type=int, default=30,
        help="Max reports to sync (default: 30)",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("🔍 DRY-RUN mode — no files will be written.\n")

    result = sync_to_obsidian(
        storage_root=args.storage,
        vault_root=args.vault,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        max_entries=args.max_entries,
    )

    print()
    if "error" in result:
        print(f"❌ Error: {result['error']}")
        sys.exit(1)

    print(f"📊 Synced: {result.get('synced', 0)} | Skipped: {result.get('skipped', 0)} | Total: {result.get('reports', 0)}")
    if args.dry_run:
        print("🔍 DRY-RUN complete — re-run with --no-dry-run to write files.")


if __name__ == "__main__":
    main()
