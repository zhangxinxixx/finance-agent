"""Deterministic Jin10 report quality, materialized by the recorded news worker."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle


def report_quality_input_id(agent_payload: dict, daily_payload: dict) -> str:
    data = json.dumps([agent_payload, daily_payload], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def materialize_jin10_report_quality(*, storage_root: Path, run_dir: Path, raw_payload: dict,
                                   agent_payload: dict, daily_payload: dict) -> Path:
    root = storage_root.resolve()
    run_dir = run_dir.resolve()
    relative = run_dir.relative_to(root / "outputs" / "jin10")
    if len(relative.parts) != 2:
        raise ValueError("invalid Jin10 report directory")
    trace = build_jin10_report_quality(storage_root=root, run_dir=run_dir, raw_payload=raw_payload,
                                      agent_payload=agent_payload, daily_payload=daily_payload)
    payload = {"schema_version": "jin10_report_quality.v1", "trade_date": relative.parts[0],
               "run_id": relative.parts[1], "input_id": report_quality_input_id(agent_payload, daily_payload),
               "source_title": raw_payload.get("title"), "source_refs": raw_payload.get("source_refs") or [],
               "source_sha256": hashlib.sha256(json.dumps(raw_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
               "quality_audit": _normalize_jin10_quality_audit(agent_payload, daily_payload, raw_payload),
               "trace": trace}
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = root / "features" / "jin10_report_quality" / relative / (identity + ".json")
    write_immutable_artifact_bundle([immutable_json_item(path, payload)], storage_root=root)
    return path


def build_jin10_report_quality(
    *,
    run_dir: Path,
    storage_root: Path,
    raw_payload: dict[str, Any],
    agent_payload: dict[str, Any],
    daily_payload: dict[str, Any],
) -> dict[str, Any]:
    raw_generated_from = (
        raw_payload.get("generated_from") if isinstance(raw_payload.get("generated_from"), dict) else {}
    )
    agent_generated_from = (
        agent_payload.get("generated_from") if isinstance(agent_payload.get("generated_from"), dict) else {}
    )
    parser_trace = (
        raw_generated_from.get("parser_trace") if isinstance(raw_generated_from.get("parser_trace"), dict) else {}
    )
    parser_status = parser_trace.get("status") if isinstance(parser_trace.get("status"), dict) else {}

    def trace_value(key: str) -> Any:
        return parser_trace.get(key) or parser_status.get(key)

    charts = raw_payload.get("charts") if isinstance(raw_payload.get("charts"), list) else []
    quality_audit = _normalize_jin10_quality_audit(agent_payload, raw_payload, daily_payload) or {}
    asset_audit = _build_jin10_asset_audit(run_dir=run_dir, raw_payload=raw_payload, storage_root=storage_root)
    chart_text_issues = _jin10_chart_text_issues(charts)
    semantic_review_status = "needs_review" if chart_text_issues else "pass"
    vision_layout_path = run_dir / "vision_layout.json"
    vlm_provider = (
        trace_value("vision_provider") or raw_generated_from.get("provider") or raw_generated_from.get("source")
    )
    vlm_model = trace_value("vision_model") or raw_generated_from.get("model") or raw_generated_from.get("vlm_model")
    vision_layout_status = trace_value("vision_layout_status") or (
        "present" if vision_layout_path.exists() else "missing"
    )
    vlm_tracked = bool(vlm_model or trace_value("parser_run_id"))

    return {
        "llm": {
            "provider": agent_generated_from.get("provider") or agent_generated_from.get("source"),
            "model": agent_generated_from.get("model"),
            "generated_at": agent_generated_from.get("generated_at"),
            "token_usage": agent_generated_from.get("tokens"),
            "source": agent_generated_from.get("source"),
        },
        "vlm": {
            "provider": vlm_provider,
            "model": vlm_model,
            "content_stage": raw_generated_from.get("content_stage"),
            "parser_version": trace_value("parser_version"),
            "parser_run_id": trace_value("parser_run_id"),
            "recognition_mode": trace_value("recognition_mode"),
            "vision_markdown_status": trace_value("vision_markdown_status"),
            "chart_render_mode": (raw_generated_from.get("article_context") or {}).get("chart_render_mode")
            if isinstance(raw_generated_from.get("article_context"), dict)
            else None,
            "status": "tracked" if vlm_tracked else "untracked",
            "vision_layout_status": vision_layout_status,
            "reason": "vision_layout.json missing; parser output has no VLM model metadata"
            if vision_layout_status == "missing" and not vlm_tracked
            else None,
        },
        "quality_audit": {
            "status": quality_audit.get("status"),
            "checked_at": quality_audit.get("checked_at"),
            "reason_count": len(quality_audit.get("reasons") or [])
            if isinstance(quality_audit.get("reasons"), list)
            else 0,
            "semantic_review_status": semantic_review_status,
            "chart_text_issue_count": len(chart_text_issues),
            "chart_text_issues": chart_text_issues[:8],
        },
        "asset_audit": asset_audit,
        "source_counts": {
            "source_refs": len(raw_payload.get("source_refs") or []) + len(agent_payload.get("source_refs") or []),
            "charts": len(charts),
            "original_images": _count_jin10_source_images(raw_payload.get("source_refs")),
            "artifacts": len([path for path in run_dir.iterdir() if path.is_file()]) if run_dir.exists() else 0,
        },
        "strategy_handoff": {
            "scenario_paths": _summarize_named_items(agent_payload.get("scenario_paths")),
            "trading_implications": _summarize_named_items(
                agent_payload.get("trading_implications"), title_key="stance"
            ),
            "source_artifact_refs": agent_payload.get("source_artifact_refs") or [],
        },
    }


def _build_jin10_asset_audit(*, run_dir: Path, raw_payload: dict[str, Any], storage_root: Path) -> dict[str, Any]:
    markdown_image_refs = _extract_markdown_image_refs(run_dir / "raw_article_report.md")
    markdown_refs = {_normalize_jin10_image_ref(ref) for ref in markdown_image_refs}
    markdown_refs.discard("")
    charts = raw_payload.get("charts") if isinstance(raw_payload.get("charts"), list) else []
    chart_refs = {
        _normalize_jin10_image_ref(str(chart.get("image_path")))
        for chart in charts
        if isinstance(chart, dict) and chart.get("image_path")
    }
    chart_refs.discard("")
    article_id = str(raw_payload.get("article_id") or run_dir.name).strip()
    if not re.fullmatch(r"\d+", article_id):
        article_id = run_dir.name
    parsed_figures = storage_root / "parsed" / "jin10" / run_dir.parent.name / article_id / "figures"
    canonical_figure_paths = {
        _normalize_jin10_image_ref(f"figures/{path.name}") for path in parsed_figures.glob("*.png")
    }
    expected_refs = markdown_refs | chart_refs
    figure_paths = canonical_figure_paths & expected_refs
    parser_figures_total = _jin10_parser_figures_total(raw_payload)
    count_issues: list[dict[str, Any]] = []
    if len(markdown_image_refs) != len(markdown_refs):
        count_issues.append(
            {
                "code": "duplicate_markdown_refs",
                "markdown_image_refs": len(markdown_image_refs),
                "unique_markdown_image_refs": len(markdown_refs),
            }
        )
    if len(charts) != len(chart_refs):
        count_issues.append(
            {
                "code": "duplicate_or_missing_chart_refs",
                "chart_count": len(charts),
                "unique_chart_image_refs": len(chart_refs),
            }
        )
    if markdown_refs != chart_refs:
        count_issues.append(
            {
                "code": "markdown_chart_ref_mismatch",
                "markdown_only": sorted(markdown_refs - chart_refs),
                "chart_only": sorted(chart_refs - markdown_refs),
            }
        )
    if len(figure_paths) != len(expected_refs):
        count_issues.append(
            {
                "code": "figure_file_count_mismatch",
                "figure_files": len(figure_paths),
                "expected_refs": len(expected_refs),
            }
        )
    if parser_figures_total is not None and parser_figures_total != len(chart_refs):
        count_issues.append(
            {
                "code": "parser_figure_count_mismatch",
                "parser_figures_total": parser_figures_total,
                "chart_image_refs": len(chart_refs),
            }
        )
    missing_refs = sorted(ref for ref in expected_refs if ref not in canonical_figure_paths)
    extra_files: list[str] = []
    if missing_refs:
        status = "missing_assets"
    elif count_issues or extra_files:
        status = "needs_review"
    else:
        status = "pass"
    return {
        "markdown_image_refs": len(markdown_refs),
        "markdown_image_ref_occurrences": len(markdown_image_refs),
        "raw_chart_count": len(charts),
        "chart_image_refs": len(chart_refs),
        "figure_files": len(figure_paths),
        "canonical_figure_files": len(canonical_figure_paths),
        "parser_figures_total": parser_figures_total,
        "missing_refs": missing_refs,
        "extra_files": extra_files,
        "count_issues": count_issues,
        "status": status,
    }


def _extract_markdown_image_refs(path: Path) -> list[str]:
    text = _read_optional_text(path) or ""
    return [match.strip() for match in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text) if match.strip()]


def _normalize_jin10_image_ref(ref: str) -> str:
    value = str(ref or "").split("?", 1)[0].strip().replace("\\", "/")
    if not value:
        return ""
    if "/asset/" in value:
        value = "figures/" + value.rsplit("/", 1)[-1]
    if value.startswith("./"):
        value = value[2:]
    if value.startswith("/"):
        value = f"figures/{value.rsplit('/', 1)[-1]}"
    return value


def _jin10_parser_figures_total(raw_payload: dict[str, Any]) -> int | None:
    generated_from = raw_payload.get("generated_from")
    if not isinstance(generated_from, dict):
        return None
    parser_trace = generated_from.get("parser_trace")
    if not isinstance(parser_trace, dict):
        return None
    value = parser_trace.get("figures_total")
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _jin10_chart_text_issues(charts: Any) -> list[dict[str, Any]]:
    if not isinstance(charts, list):
        return []
    issues: list[dict[str, Any]] = []
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        recognized_text = str(chart.get("recognized_text") or "")
        too_long = len(recognized_text) >= 240
        paragraph_like = recognized_text.count("\n\n") >= 2
        looks_like_article = "。" in recognized_text and len(recognized_text) >= 160
        if too_long or paragraph_like or looks_like_article:
            issues.append(
                {
                    "figure_id": chart.get("figure_id"),
                    "image_path": chart.get("image_path"),
                    "title": chart.get("title"),
                    "text_len": len(recognized_text),
                }
            )
    return issues


def _count_jin10_source_images(source_refs: Any) -> int:
    if not isinstance(source_refs, list):
        return 0
    return sum(
        1 for ref in source_refs if isinstance(ref, dict) and str(ref.get("asset_type") or "").lower() == "image"
    )


def _summarize_named_items(raw_items: Any, *, title_key: str = "path") -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    summarized: list[dict[str, Any]] = []
    for item in raw_items[:3]:
        if not isinstance(item, dict):
            continue
        summarized.append(
            {
                "title": item.get(title_key) or item.get("title") or item.get("path") or item.get("stance"),
                "summary": item.get("summary") or item.get("trigger"),
                "invalid": item.get("invalid"),
            }
        )
    return summarized



def _normalize_jin10_quality_audit(*payloads: dict[str, Any] | None) -> dict[str, Any] | None:
    for payload in payloads:
        audit = (payload or {}).get("quality_audit")
        if not isinstance(audit, dict):
            continue
        status = str(audit.get("status") or "accepted")
        reasons = audit.get("reasons")
        reason_items = [item for item in reasons if isinstance(item, dict)] if isinstance(reasons, list) else []
        return {
            "status": status,
            "checked_at": audit.get("checked_at"),
            "reasons": reason_items,
            "reason_codes": [str(item.get("code")) for item in reason_items if item.get("code")],
        }
    return None



def _read_optional_text(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None
