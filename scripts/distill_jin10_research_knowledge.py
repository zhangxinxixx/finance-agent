from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path("storage/outputs/knowledge/items.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Knowledge Base candidate items from Jin10 research agent outputs.")
    parser.add_argument("--agent-report-json", required=True, help="Path to agent_analysis_report.json.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Knowledge read-model JSON output path.")
    parser.add_argument("--item-id", help="Override generated knowledge item id.")
    parser.add_argument("--replace", action="store_true", help="Replace the output file instead of upserting into existing items.")
    args = parser.parse_args()

    report_path = Path(args.agent_report_json)
    report = _read_json(report_path)
    item = build_knowledge_item(report, report_path=report_path, item_id=args.item_id)
    output_path = Path(args.output)
    payload = build_output_payload(item, output_path=output_path, replace=args.replace)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "item_id": item["id"],
                "items": len(payload["items"]),
                "output": str(output_path),
                "status": payload["status"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def build_knowledge_item(report: dict[str, Any], *, report_path: Path, item_id: str | None = None) -> dict[str, Any]:
    _validate_master_review_report(report)
    article_id = str(report.get("article_id") or report.get("run_id") or "")
    trade_date = str(report.get("trade_date") or "")
    title = str(report.get("title") or "Jin10 大师复盘知识候选").strip()
    generated_id = item_id or f"jin10-master-review-{trade_date}-{article_id}".strip("-")
    now = _utc_now()
    confidence = _confidence_from_quality(report)
    source_refs = _source_refs(report, report_path)

    return {
        "id": generated_id,
        "title": f"大师复盘候选：{title}",
        "type": "review",
        "typeLabel": "复盘",
        "topic": str(report.get("asset") or "黄金"),
        "status": "待复核",
        "summary": _text(report.get("one_line_conclusion"), fallback=title, limit=240),
        "thesis": _text(report.get("final_summary"), fallback=_text(report.get("one_line_conclusion"), fallback=title), limit=420),
        "updated": trade_date or now[:10],
        "createdAt": now,
        "verifiedAt": "",
        "version": "candidate-v1",
        "author": "jin10_report_analysis_agent",
        "confidence": confidence,
        "citations": len(source_refs),
        "references": len(source_refs),
        "dashboards": 0,
        "agentReady": False,
        "playbookReady": False,
        "pinned": False,
        "reviewQueued": True,
        "tags": _tags(report),
        "scenes": [
            "从 Jin10「周末·大师复盘」Agent 输出中沉淀候选规则。",
            "人工复核后再决定是否晋升为长期有效方法论或 Playbook。",
        ],
        "rules": _rules(report),
        "inputs": _inputs(report),
        "monitorMetrics": _monitor_metrics(report),
        "evidence": _evidence(report, report_path),
        "downstream": [
            {"name": "Knowledge Base", "state": "待复核", "note": "仅作为候选知识项展示，不自动注入 Agent。"},
            {"name": "Jin10 research reports", "state": "来源链路", "note": "引用 agent_analysis_report 与 source_refs。"},
        ],
        "timeline": [
            {"time": now, "title": "生成候选知识项", "copy": "由 Jin10 research/master_review agent output 离线蒸馏生成。"}
        ],
        "citationFlow": {
            "upstream": _citation_upstream(report, report_path),
            "downstream": [{"title": "Knowledge distillation review queue", "meta": "candidate / manual review required"}],
        },
        "source_refs": source_refs,
        "metadata": {
            "article_id": article_id,
            "trade_date": trade_date,
            "report_type": "research",
            "series": "master_review",
            "quality_audit": report.get("quality_audit") if isinstance(report.get("quality_audit"), dict) else {},
            "content_access": report.get("content_access") if isinstance(report.get("content_access"), dict) else {},
        },
    }


def build_output_payload(item: dict[str, Any], *, output_path: Path, replace: bool) -> dict[str, Any]:
    existing_items: list[dict[str, Any]] = []
    if not replace and output_path.is_file():
        payload = _read_json(output_path)
        raw_items = payload.get("items") if isinstance(payload, dict) else payload
        if isinstance(raw_items, list):
            existing_items = [entry for entry in raw_items if isinstance(entry, dict) and entry.get("id") != item["id"]]
    items = [item] if replace else [item, *existing_items]
    return {
        "status": "available" if items else "unavailable",
        "source": "storage_read_model",
        "updated_at": _utc_now(),
        "items": items,
        "stats": _stats(items),
        "source_refs": item.get("source_refs", []),
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_master_review_report(report: dict[str, Any]) -> None:
    content_access = report.get("content_access") if isinstance(report.get("content_access"), dict) else {}
    generated_from = report.get("generated_from") if isinstance(report.get("generated_from"), dict) else {}
    report_type = content_access.get("report_type") or generated_from.get("report_type")
    series = content_access.get("series") or generated_from.get("series")
    family = generated_from.get("daily_report_family") or report.get("source_report_family")
    if report_type != "research" or series != "master_review" or family != "jin10_research_report":
        raise ValueError("agent report is not a Jin10 research/master_review output")


def _confidence_from_quality(report: dict[str, Any]) -> int:
    quality = report.get("quality_audit") if isinstance(report.get("quality_audit"), dict) else {}
    status = str(quality.get("status") or "")
    content_access = report.get("content_access") if isinstance(report.get("content_access"), dict) else {}
    body_complete = bool(content_access.get("body_complete"))
    if status == "accepted":
        return 72 if body_complete else 58
    if status == "needs_review":
        return 52 if body_complete else 42
    return 45


def _tags(report: dict[str, Any]) -> list[str]:
    tags = ["Jin10", "大师复盘", "research", "待复核"]
    asset = str(report.get("asset") or "").strip()
    if asset:
        tags.insert(0, asset)
    return tags


def _rules(report: dict[str, Any]) -> list[str]:
    rules: list[str] = []
    for path in report.get("scenario_paths") or []:
        if not isinstance(path, dict):
            continue
        summary = _text(path.get("summary"), fallback="", limit=140)
        trigger = _text(path.get("trigger"), fallback="", limit=140)
        invalid = _text(path.get("invalid"), fallback="", limit=140)
        if summary:
            rules.append(f"{summary} 触发条件：{trigger or '待补充'}；失效条件：{invalid or '待补充'}。")
    for implication in report.get("trading_implications") or []:
        if not isinstance(implication, dict):
            continue
        stance = _text(implication.get("stance"), fallback="", limit=80)
        trigger = _text(implication.get("trigger"), fallback="", limit=140)
        if stance or trigger:
            rules.append(f"执行口径：{stance or '待观察'}；确认条件：{trigger or '待补充'}。")
    if not rules:
        rules.append(_text(report.get("one_line_conclusion"), fallback="该候选知识需要人工复核后再抽象为稳定规则。", limit=180))
    return rules[:6]


def _inputs(report: dict[str, Any]) -> list[str]:
    inputs = ["Jin10 research/master_review agent output", "source_refs", "quality_audit", "content_access"]
    for variable in report.get("key_variables") or []:
        if isinstance(variable, dict):
            name = str(variable.get("name") or "").strip()
            if name and name not in inputs:
                inputs.append(name)
    return inputs[:8]


def _monitor_metrics(report: dict[str, Any]) -> list[dict[str, str]]:
    quality = report.get("quality_audit") if isinstance(report.get("quality_audit"), dict) else {}
    content_access = report.get("content_access") if isinstance(report.get("content_access"), dict) else {}
    return [
        {"label": "review", "value": "queued", "change": "candidate", "tone": "negative"},
        {"label": "quality", "value": str(quality.get("status") or "unknown"), "change": "needs human gate", "tone": "neutral"},
        {"label": "content", "value": str(content_access.get("content_scope") or "unknown"), "change": "body_complete=" + str(bool(content_access.get("body_complete"))).lower(), "tone": "neutral"},
        {"label": "source", "value": "Jin10", "change": "master_review", "tone": "neutral"},
    ]


def _evidence(report: dict[str, Any], report_path: Path) -> list[dict[str, str]]:
    quality = report.get("quality_audit") if isinstance(report.get("quality_audit"), dict) else {}
    content_access = report.get("content_access") if isinstance(report.get("content_access"), dict) else {}
    reasons = quality.get("reasons") if isinstance(quality.get("reasons"), list) else []
    reason_text = "; ".join(str(item.get("code") or item.get("message") or item) for item in reasons if isinstance(item, dict)) or "no quality reason"
    return [
        {
            "title": "Agent output",
            "body": _text(report.get("final_summary"), fallback=_text(report.get("one_line_conclusion"), fallback=""), limit=360),
            "meta": f"{report_path.as_posix()} / {report.get('article_id') or report.get('run_id')}",
        },
        {
            "title": "Content access",
            "body": f"content_scope={content_access.get('content_scope') or 'unknown'}, body_complete={bool(content_access.get('body_complete'))}, vip_locked={bool(content_access.get('vip_locked'))}",
            "meta": "must stay visible before promotion",
        },
        {
            "title": "Quality gate",
            "body": reason_text,
            "meta": str(quality.get("status") or "unknown"),
        },
    ]


def _citation_upstream(report: dict[str, Any], report_path: Path) -> list[dict[str, str]]:
    article_id = str(report.get("article_id") or report.get("run_id") or "")
    return [
        {
            "title": str(report.get("title") or f"Jin10 article {article_id}"),
            "meta": f"agent_analysis_report / {report_path.as_posix()}",
        }
    ]


def _source_refs(report: dict[str, Any], report_path: Path) -> list[dict[str, Any]]:
    refs = report.get("source_refs") if isinstance(report.get("source_refs"), list) else []
    local_ref = {
        "source": "jin10_agent_analysis_report",
        "path": report_path.as_posix(),
        "sha256": _sha256(report_path),
        "article_id": report.get("article_id") or report.get("run_id"),
        "trade_date": report.get("trade_date"),
    }
    return [local_ref, *refs]


def _stats(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(items),
        "agent_ready": sum(1 for item in items if bool(item.get("agentReady"))),
        "playbook_count": sum(1 for item in items if item.get("type") == "playbook"),
        "playbook_candidate_count": sum(1 for item in items if item.get("type") != "playbook" and _as_int(item.get("confidence")) >= 80),
        "playbook_published_count": sum(1 for item in items if item.get("type") == "playbook" and bool(item.get("agentReady"))),
        "review_queue_count": sum(1 for item in items if bool(item.get("reviewQueued"))),
        "pinned_count": sum(1 for item in items if bool(item.get("pinned"))),
        "total_citations": sum(_as_int(item.get("citations")) for item in items),
    }


def _text(value: Any, *, fallback: str, limit: int | None = None) -> str:
    text = str(value or fallback or "").strip()
    text = " ".join(text.split())
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
