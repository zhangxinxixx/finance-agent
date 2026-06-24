from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT
from apps.api.services.agent_output_service import build_agent_output_summary
from apps.api.services.review_service import build_review_item_response
from database.queries.analysis import list_agent_outputs
from database.queries.review import list_review_items


from datetime import date as _date, timedelta
from sqlalchemy.orm import Session


def _get_t1_trade_date() -> str:
    """计算 T-1 交易日：周一~周四为前一天，周五为周四，周六/周日为周五。"""
    today = _date.today()
    weekday = today.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    if weekday == 0:  # Monday → Friday
        d = today - timedelta(days=3)
    elif weekday == 5:  # Saturday → Friday
        d = today - timedelta(days=1)
    elif weekday == 6:  # Sunday → Friday
        d = today - timedelta(days=2)
    else:  # Tue~Fri → previous day
        d = today - timedelta(days=1)
    return d.isoformat()


def get_options_snapshot(date_str: str | None = None, db: Session | None = None) -> dict[str, Any] | None:
    cme_new = _PROJECT_ROOT / "storage" / "outputs" / "cme"
    cme_base = _PROJECT_ROOT / "storage" / "outputs" / "cme_options"
    cme_features = _PROJECT_ROOT / "storage" / "features" / "cme"
    snap_base = _PROJECT_ROOT / "storage" / "features" / "snapshots" / "XAUUSD"

    def _load_new_cme_output(date: str) -> dict[str, Any] | None:
        # Prefer features directory (near-month-only data) over outputs
        features_date_dir = cme_features / date
        if features_date_dir.exists():
            for run_dir in sorted((d for d in features_date_dir.iterdir() if d.is_dir()), reverse=True):
                path = run_dir / "options_analysis.json"
                if not path.exists():
                    continue
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    return _finalize_snapshot_payload(payload, trade_date=date, run_id=run_dir.name)
                except Exception:
                    continue
        date_dir = cme_new / date
        if date_dir.exists():
            for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
                path = run_dir / "options_analysis.json"
                if not path.exists():
                    continue
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    return _finalize_snapshot_payload(payload, trade_date=date, run_id=run_dir.name)
                except Exception:
                    continue
        return None

    def _load_standalone(date: str) -> dict[str, Any] | None:
        path = cme_base / date / "options_analysis.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return _finalize_snapshot_payload(payload, trade_date=date, run_id=None)
        except Exception:
            return None

    def _load_from_snapshot(date: str) -> dict[str, Any] | None:
        date_dir = snap_base / date
        if not date_dir.exists():
            return None
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            snap_path = run_dir / "premarket_snapshot.json"
            if not snap_path.exists():
                continue
            try:
                snap = json.loads(snap_path.read_text(encoding="utf-8"))
                options_raw = snap.get("options")
                if isinstance(options_raw, dict) and options_raw.get("status") == "available":
                    options = options_raw.get("data")
                    if isinstance(options, dict):
                        return _finalize_snapshot_payload(options, trade_date=date, run_id=run_dir.name)
            except Exception:
                continue
        # Also check features directory (option_wall step output)
        features_date_dir = cme_features / date
        if features_date_dir.exists():
            for run_dir in sorted((d for d in features_date_dir.iterdir() if d.is_dir()), reverse=True):
                path = run_dir / "options_analysis.json"
                if not path.exists():
                    continue
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    return _finalize_snapshot_payload(payload, trade_date=date, run_id=run_dir.name)
                except Exception:
                    continue

    def _attach_analysis(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if payload is None:
            return None
        agent_rows: list[Any] = []
        if db is not None:
            snapshot_id = str(payload.get("snapshot_id") or "")
            agent_rows = list_agent_outputs(db, snapshot_id) if snapshot_id else []
            payload["analysis"] = _build_options_analysis(db, payload, rows=agent_rows)
        _enrich_options_snapshot_lineage(payload, agent_rows=agent_rows)
        return payload

    all_dates = list_options_report_dates()
    if not all_dates:
        return None
    if date_str:
        return _attach_analysis(_load_new_cme_output(date_str) or _load_standalone(date_str) or _load_from_snapshot(date_str))
    # 优先 T-1 交易日
    t1 = _get_t1_trade_date()
    if t1 in all_dates:
        loaded = _load_new_cme_output(t1) or _load_standalone(t1) or _load_from_snapshot(t1)
        if loaded is not None:
            return _attach_analysis(loaded)
    # T-1 无数据，降级到最新可用
    for candidate_date in all_dates:
        loaded = _load_new_cme_output(candidate_date) or _load_standalone(candidate_date) or _load_from_snapshot(candidate_date)
        if loaded is not None:
            return _attach_analysis(loaded)
    return None


def _finalize_snapshot_payload(
    payload: dict[str, Any],
    *,
    trade_date: str,
    run_id: str | None,
) -> dict[str, Any]:
    normalized = dict(payload)
    resolved_trade_date = str(normalized.get("trade_date") or trade_date)
    normalized.setdefault("trade_date", resolved_trade_date)
    if run_id:
        normalized.setdefault("run_id", run_id)
    elif normalized.get("run_id") is None:
        normalized["run_id"] = None
    snapshot_id = normalized.get("snapshot_id")
    if not snapshot_id:
        resolved_run_id = normalized.get("run_id")
        normalized["snapshot_id"] = (
            f"options:{resolved_trade_date}:{resolved_run_id}"
            if resolved_run_id
            else f"options:{resolved_trade_date}:legacy"
        )
    return normalized


def _enrich_options_snapshot_lineage(
    payload: dict[str, Any],
    *,
    agent_rows: list[Any],
) -> None:
    trade_date = str(payload.get("trade_date") or "")
    run_id = payload.get("run_id")
    snapshot_id = str(payload.get("snapshot_id") or "")
    data_source = dict(payload.get("data_source") or {})

    primary_agent_rows = [row for row in agent_rows if getattr(row, "agent_name", None) == "cme_options_agent"] or agent_rows

    merged_input_snapshot_ids = _merge_input_snapshot_id_maps(
        data_source.get("input_snapshot_ids"),
        *[getattr(row, "input_snapshot_ids", None) for row in primary_agent_rows],
    )
    if snapshot_id and snapshot_id not in merged_input_snapshot_ids.values():
        merged_input_snapshot_ids.setdefault("options_analysis_snapshot", snapshot_id)
    data_source["input_snapshot_ids"] = merged_input_snapshot_ids
    payload["data_source"] = data_source

    source_trace = list(payload.get("source_trace") or [])
    endpoint = _build_options_snapshot_endpoint(trade_date)
    source_url = data_source.get("source_url")
    if isinstance(source_url, str) and source_url:
        source_trace.append(
            _build_source_trace_item(
                name="CME Daily Bulletin",
                trade_date=trade_date,
                file_ref=source_url,
                snapshot_id=snapshot_id or None,
                source_ref=source_url,
                status=_trace_status(data_source.get("status")),
                endpoint=endpoint,
                model_version=payload.get("version"),
            )
        )

    for item in _collect_options_artifact_refs(
        trade_date=trade_date,
        run_id=str(run_id) if isinstance(run_id, str) and run_id else None,
        agent_rows=primary_agent_rows,
    ):
        source_trace.append(
            _build_source_trace_item(
                name=item.get("name") or "options_artifact",
                trade_date=trade_date,
                file_ref=item["file_ref"],
                snapshot_id=item.get("snapshot_id") or (snapshot_id or None),
                source_ref=item.get("source_ref") or item["file_ref"],
                status=item.get("status") or "ok",
                endpoint=endpoint,
                model_version=payload.get("version"),
            )
        )

    for row in primary_agent_rows:
        row_source_refs = row.source_refs if isinstance(getattr(row, "source_refs", None), list) else []
        for raw_ref in row_source_refs:
            if not isinstance(raw_ref, dict):
                continue
            source_ref = _first_non_empty(
                raw_ref.get("source_ref"),
                raw_ref.get("source_id"),
                raw_ref.get("source_url"),
                raw_ref.get("url"),
                raw_ref.get("source"),
            )
            file_ref = _first_non_empty(raw_ref.get("file_path"), raw_ref.get("source_url"), raw_ref.get("url"))
            if not source_ref and not file_ref:
                continue
            source_trace.append(
                _build_source_trace_item(
                    name=_first_non_empty(raw_ref.get("source_name"), raw_ref.get("source"), raw_ref.get("source_id"), row.agent_name)
                    or "source",
                    trade_date=_first_non_empty(raw_ref.get("data_date"), raw_ref.get("report_date"), trade_date) or trade_date,
                    file_ref=file_ref or source_ref,
                    snapshot_id=row.snapshot_id or (snapshot_id or None),
                    source_ref=source_ref or file_ref,
                    status=_trace_status(raw_ref.get("status") or row.status),
                    endpoint=endpoint,
                    model_version=payload.get("version"),
                )
            )

    payload["source_trace"] = _dedupe_source_trace_items(source_trace)


def _build_options_analysis(db: Session, snapshot: dict[str, Any], *, rows: list[Any] | None = None) -> dict[str, Any]:
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    run_id = snapshot.get("run_id")
    rows = rows if rows is not None else (list_agent_outputs(db, snapshot_id) if snapshot_id else [])
    by_name = {row.agent_name: row for row in rows}

    cme_summary = _build_agent_summary(by_name.get("cme_options_agent"))
    fact_review_summary = _build_agent_summary(by_name.get("fact_review_agent"))
    synthesis_summary = _build_synthesis_summary(by_name.get("synthesis_agent"))

    pending_reviews = [
        build_review_item_response(item).model_dump(mode="json")
        for item in (
            list_review_items(
                db,
                status="pending",
                source_module="options",
                run_id=str(run_id),
                limit=50,
            )
            if run_id
            else []
        )
    ]

    return {
        "snapshot_id": snapshot_id or None,
        "run_id": str(run_id) if run_id else None,
        "fact_review_status": (
            (fact_review_summary or {}).get("fact_review_status")
            or (synthesis_summary or {}).get("fact_review_status")
        ),
        "cme_options_agent": cme_summary,
        "fact_review": fact_review_summary,
        "synthesis": synthesis_summary,
        "pending_review_count": len(pending_reviews),
        "pending_reviews": pending_reviews,
    }


def _collect_options_artifact_refs(
    *,
    trade_date: str,
    run_id: str | None,
    agent_rows: list[Any],
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for path in _discover_options_artifact_paths(trade_date=trade_date, run_id=run_id):
        refs.append(
            {
                "name": Path(path).name,
                "file_ref": path,
                "source_ref": path,
                "status": "ok",
            }
        )

    for row in agent_rows:
        payload = row.payload if isinstance(getattr(row, "payload", None), dict) else {}
        artifact_refs = payload.get("artifact_refs")
        if not isinstance(artifact_refs, list):
            continue
        for artifact_ref in artifact_refs:
            if not isinstance(artifact_ref, str) or not artifact_ref:
                continue
            normalized_ref = _normalize_project_relative_path(artifact_ref)
            refs.append(
                {
                    "name": row.agent_name,
                    "file_ref": normalized_ref,
                    "source_ref": f"agent_output:{row.id}:{Path(normalized_ref).name}",
                    "snapshot_id": row.snapshot_id or "",
                    "status": _trace_status(row.status),
                }
            )
    return refs


def _discover_options_artifact_paths(*, trade_date: str, run_id: str | None) -> list[str]:
    bases: list[Path] = []
    if run_id:
        bases.append(_PROJECT_ROOT / "storage" / "features" / "cme" / trade_date / run_id)
        bases.append(_PROJECT_ROOT / "storage" / "outputs" / "cme" / trade_date / run_id)
    bases.append(_PROJECT_ROOT / "storage" / "outputs" / "cme_options" / trade_date)

    discovered: list[str] = []
    for base in bases:
        for filename in (
            "options_analysis.json",
            "options_analysis.md",
            "options_visual_report.json",
            "options_visual_report.html",
            "options_analysis_agent_report.md",
        ):
            path = base / filename
            if path.exists():
                discovered.append(_normalize_project_relative_path(path))
    return list(dict.fromkeys(discovered))


def _merge_input_snapshot_id_maps(*raw_values: Any) -> dict[str, str]:
    merged: dict[str, str] = {}
    for raw in raw_values:
        if isinstance(raw, dict):
            for key, value in raw.items():
                normalized = _normalize_snapshot_candidate(value)
                if normalized:
                    merged[str(key)] = normalized
        elif isinstance(raw, list):
            for index, value in enumerate(raw, start=1):
                normalized = _normalize_snapshot_candidate(value)
                if normalized:
                    merged.setdefault(f"snapshot_{index}", normalized)
    return merged


def _normalize_snapshot_candidate(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        nested = _first_non_empty(value.get("snapshot_id"), value.get("id"))
        if nested:
            return nested
    return None


def _build_source_trace_item(
    *,
    name: str,
    trade_date: str,
    file_ref: str,
    snapshot_id: str | None,
    source_ref: str,
    status: str,
    endpoint: str,
    model_version: Any,
) -> dict[str, Any]:
    return {
        "name": name,
        "trade_date": trade_date,
        "file": file_ref,
        "snapshot_id": snapshot_id,
        "source_ref": source_ref,
        "status": status,
        "endpoint": endpoint,
        "latest_raw_time": None,
        "latest_parsed_time": None,
        "model_version": str(model_version) if isinstance(model_version, str) and model_version else None,
    }


def _dedupe_source_trace_items(items: list[Any]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source_ref = str(item.get("source_ref") or "")
        file_ref = str(item.get("file") or "")
        snapshot_id = str(item.get("snapshot_id") or "")
        if not (source_ref or file_ref):
            continue
        key = (source_ref, file_ref, snapshot_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _build_options_snapshot_endpoint(trade_date: str) -> str:
    return "/api/options/snapshot" if not trade_date else f"/api/options/snapshot?date={trade_date}"


def _normalize_project_relative_path(path: str | Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        return str(candidate)
    try:
        return str(candidate.relative_to(_PROJECT_ROOT))
    except ValueError:
        return str(candidate)


def _trace_status(raw_status: Any) -> str:
    raw = str(raw_status or "").lower()
    if raw in {"success", "ok", "available", "generated", "final"}:
        return "ok"
    if raw in {"partial", "partial_success", "prelim", "stale", "fallback"}:
        return "warn"
    if raw in {"failed", "error", "missing", "unavailable"}:
        return "error"
    return "info"


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _build_agent_summary(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return build_agent_output_summary(row)


def _build_synthesis_summary(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    summary = build_agent_output_summary(row)
    payload = row.payload if isinstance(row.payload, dict) else {}
    input_payload = payload.get("input_payload") if isinstance(payload.get("input_payload"), dict) else {}
    fact_review_output = (
        input_payload.get("fact_review_output")
        if isinstance(input_payload.get("fact_review_output"), dict)
        else {}
    )
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    upstream_fact_review_status = fact_review_output.get("fact_review_status")
    if upstream_fact_review_status:
        summary["fact_review_status"] = str(upstream_fact_review_status)
    summary["synthesis_status"] = payload.get("synthesis_status") or summary.get("status")
    summary["warning_count"] = len(warnings)
    summary["warnings"] = warnings
    summary["reading_order"] = list(payload.get("reading_order") or [])
    summary["consensus_points"] = list(payload.get("consensus_points") or [])
    summary["divergent_points"] = list(payload.get("divergent_points") or [])
    summary["excluded_claim_ids"] = list(payload.get("excluded_claim_ids") or [])
    summary["review_item_ids"] = list(payload.get("review_item_ids") or [])
    return summary


def get_options_report_md(date_str: str | None = None) -> str | None:
    cme_base = _PROJECT_ROOT / "storage" / "outputs" / "cme"
    if date_str is None:
        all_dates = list_options_report_dates()
        if not all_dates:
            return None
        # 优先 T-1 交易日
        t1 = _get_t1_trade_date()
        date_str = t1 if t1 in all_dates else all_dates[0]

    date_dir = cme_base / date_str
    if date_dir.exists() and date_dir.is_dir():
        run_dirs = sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True)
        for filename in ("options_analysis_agent_report.md", "options_analysis.md"):
            for run_dir in run_dirs:
                path = run_dir / filename
                if path.exists():
                    return path.read_text(encoding="utf-8")

    legacy_base = _PROJECT_ROOT / "storage" / "outputs" / "cme_options"
    for legacy_name in ("options_analysis.md", "options_analysis_enhanced.md"):
        path = legacy_base / date_str / legacy_name
        if path.exists():
            return path.read_text(encoding="utf-8")

    snap = get_options_snapshot(date_str)
    return _render_options_summary_md(snap, date_str) if snap else None


def get_options_visual_report_html(date_str: str | None = None, run_id: str | None = None) -> dict[str, Any] | None:
    cme_base = _PROJECT_ROOT / "storage" / "outputs" / "cme"
    if not cme_base.exists():
        return None

    def _render_fallback_html(title: str, body: str) -> str:
        escaped_title = html.escape(title)
        escaped_body = html.escape(body)
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escaped_title}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #08111d;
      --panel: #0f1b2d;
      --border: #1c2a41;
      --text: #eef4ff;
      --muted: #8da2c4;
      --accent: #53c7ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 24px;
      background: linear-gradient(180deg, #08111d 0%, #050c14 100%);
      color: var(--text);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    .wrap {{
      max-width: 1200px;
      margin: 0 auto;
      border: 1px solid var(--border);
      background: var(--panel);
      border-radius: 12px;
      overflow: hidden;
    }}
    .head {{
      padding: 18px 20px;
      border-bottom: 1px solid var(--border);
    }}
    h1 {{
      margin: 0;
      font-size: 20px;
      line-height: 1.4;
    }}
    .sub {{
      margin-top: 6px;
      font-size: 12px;
      color: var(--muted);
    }}
    pre {{
      margin: 0;
      padding: 20px;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.65;
      font-size: 13px;
      color: var(--text);
    }}
    .tag {{
      color: var(--accent);
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <h1>{escaped_title}</h1>
      <div class="sub"><span class="tag">Fallback</span> 当前未生成专用 visual HTML，已自动回退为报告内容视图。</div>
    </div>
    <pre>{escaped_body}</pre>
  </div>
</body>
</html>"""

    def _fallback_payload(target_date: str, target_run: str | None = None) -> dict[str, Any] | None:
        report_md = get_options_report_md(target_date)
        if report_md:
            return {
                "trade_date": target_date,
                "run_id": target_run or "latest",
                "content": _render_fallback_html(f"CME 视觉报告 {target_date}", report_md),
                "format": "html",
                "path": f"fallback://options_report_md/{target_date}/{target_run or 'latest'}",
            }

        snapshot = get_options_snapshot(target_date)
        if snapshot:
            pretty_json = json.dumps(snapshot, ensure_ascii=False, indent=2)
            return {
                "trade_date": target_date,
                "run_id": target_run or "latest",
                "content": _render_fallback_html(f"CME 视觉报告 {target_date}", pretty_json),
                "format": "html",
                "path": f"fallback://options_snapshot/{target_date}/{target_run or 'latest'}",
            }

        return None

    def _load_run(target_date: str, target_run: str) -> dict[str, Any] | None:
        html_path = cme_base / target_date / target_run / "options_visual_report.html"
        if not html_path.exists():
            return _fallback_payload(target_date, target_run)
        return {
            "trade_date": target_date,
            "run_id": target_run,
            "content": html_path.read_text(encoding="utf-8"),
            "format": "html",
            "path": str(html_path),
        }

    if date_str and run_id:
        return _load_run(date_str, run_id)
    for date_dir in sorted(cme_base.iterdir(), reverse=True):
        if not date_dir.is_dir() or (date_str and date_dir.name != date_str):
            continue
        for candidate_run in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            loaded = _load_run(date_dir.name, candidate_run.name)
            if loaded is not None:
                return loaded
        if date_str:
            return _fallback_payload(date_dir.name)
    if date_str:
        return _fallback_payload(date_str)
    return None


def _render_options_summary_md(options: dict[str, Any], date_str: str) -> str:
    lines = [f"# CME 期权结构 • {date_str}", ""]
    ds = options.get("data_source") or {}
    lines.append(f"产品: {ds.get('product', '?')} | 行数: {ds.get('row_count', '?')} | 状态: {ds.get('status', '?')}")
    expiries = ds.get("expiries", [])
    if expiries:
        lines.append(f"到期月: {', '.join(expiries)}")
    gex = options.get("gex") or {}
    gz = (gex.get("netgex_aggregate") or {}).get("gamma_zero") or {}
    if gz.get("price"):
        lines.append(f"\n## Gamma Zero: {gz['price']:.1f} ({gz.get('method', '')})")
    wall_scores = options.get("wall_scores") or []
    if wall_scores:
        lines.extend(["\n## 墙位评分 Top 5", "| Strike | 类型 | OI | 评分 |", "|--------|------|----|------|"])
        for wall in wall_scores[:5]:
            lines.append(
                f"| {wall.get('strike', '?')} | {wall.get('wall_type', '?')} | {wall.get('oi', 0)} | {wall.get('wall_score', 0):.2f} |"
            )
    intent = options.get("intent") or {}
    if intent.get("type"):
        lines.append(f"\n## 机构意图: {intent.get('type')} (置信度 {intent.get('confidence', 0):.0%})")
    source_refs = options.get("source_refs") or []
    if source_refs:
        lines.append("\n## 数据来源")
        for ref in source_refs[:5]:
            if isinstance(ref, dict):
                lines.append(f"- {ref.get('source', ref.get('symbol', '?'))}")
    lines.append("\n*由统一分析快照自动生成*")
    return "\n".join(lines)


def list_options_report_dates() -> list[str]:
    cme_new = _PROJECT_ROOT / "storage" / "outputs" / "cme"
    cme_base = _PROJECT_ROOT / "storage" / "outputs" / "cme_options"
    cme_features = _PROJECT_ROOT / "storage" / "features" / "cme"
    snap_base = _PROJECT_ROOT / "storage" / "features" / "snapshots" / "XAUUSD"
    dates: set[str] = set()

    if cme_new.exists():
        for date_dir in cme_new.iterdir():
            if not date_dir.is_dir():
                continue
            for run_dir in (d for d in date_dir.iterdir() if d.is_dir()):
                if (run_dir / "options_analysis.json").exists():
                    dates.add(date_dir.name)
                    break
    if cme_base.exists():
        dates.update(d.name for d in cme_base.iterdir() if d.is_dir() and (d / "options_analysis.json").exists())
    if cme_features.exists():
        dates.update(d.name for d in cme_features.iterdir() if d.is_dir())
    if snap_base.exists():
        for date_dir in snap_base.iterdir():
            if not date_dir.is_dir():
                continue
            for run_dir in (d for d in date_dir.iterdir() if d.is_dir()):
                snap_path = run_dir / "premarket_snapshot.json"
                if not snap_path.exists():
                    continue
                try:
                    snap = json.loads(snap_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                options_raw = snap.get("options")
                if (
                    isinstance(options_raw, dict)
                    and options_raw.get("status") == "available"
                    and isinstance(options_raw.get("data"), dict)
                ):
                    dates.add(date_dir.name)
                    break
    return sorted(dates, reverse=True)
