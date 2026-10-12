from __future__ import annotations

import json
import logging
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from apps.api.services import _storage
from apps.api.services.report_reading.common import _generated_at_from_paths

logger = logging.getLogger(__name__)


_JIN10_EXTERNAL_ROOT = Path("~/jin10-reports").expanduser()



def get_jin10_daily_report_latest() -> dict[str, Any] | None:
    base = _storage._PROJECT_ROOT / "storage" / "outputs" / "jin10"
    if not base.exists():
        return None
    for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            payload = _load_jin10_daily_report(date_dir.name, run_dir.name)
            if payload is not None and _is_jin10_daily_storage_payload(payload):
                return payload
    return None


def get_jin10_agent_analysis_latest() -> dict[str, Any] | None:
    """Return the latest accepted Jin10 daily agent-analysis payload."""

    base = _storage._PROJECT_ROOT / "storage" / "outputs" / "jin10"
    if not base.exists():
        return None
    for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            daily_payload = _read_optional_json(run_dir / "daily_analysis.json")
            agent_payload = _read_optional_json(run_dir / "agent_analysis_report.json")
            if not daily_payload or not agent_payload:
                continue
            if not _is_jin10_daily_storage_payload(
                daily_payload,
                title_candidates=(agent_payload.get("title"),),
            ):
                continue
            quality_audit = _normalize_jin10_quality_audit(agent_payload, daily_payload)
            if _jin10_report_status(quality_audit) != "ready":
                return None
            result = dict(agent_payload)
            result.setdefault("trade_date", date_dir.name)
            result.setdefault("run_id", run_dir.name)
            return result
    return None


def get_jin10_daily_report(date: str, run_id: str) -> dict[str, Any] | None:
    payload = _load_jin10_daily_report(date, run_id)
    if payload is not None and not _is_jin10_daily_storage_payload(payload):
        return None
    return payload


def _load_jin10_daily_report(date: str, run_id: str) -> dict[str, Any] | None:
    base = _storage._PROJECT_ROOT / "storage" / "outputs" / "jin10" / date / run_id
    json_path = base / "daily_analysis.json"
    html_path = base / "daily_analysis.html"
    if not json_path.exists() or not html_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    raw_payload = _read_optional_json(base / "raw_article_report.json")
    external_meta = _find_external_jin10_meta(date, run_id)
    source_title = _jin10_source_title(raw_payload, external_meta)
    if source_title:
        payload["source_title"] = source_title
    payload["content"] = html_path.read_text(encoding="utf-8")
    payload["format"] = "html"
    payload["path"] = str(html_path.relative_to(_storage._PROJECT_ROOT))
    return payload


_JIN10_NON_DAILY_TITLE_MARKERS = ("黄金头条", "投行金评", "财料", "一周热榜精选")


def _has_jin10_non_daily_title_marker(*values: Any) -> bool:
    for value in values:
        text = str(value or "")
        if text and any(marker in text for marker in _JIN10_NON_DAILY_TITLE_MARKERS):
            return True
    return False


def _is_jin10_daily_storage_payload(payload: dict[str, Any], *, title_candidates: Iterable[Any] = ()) -> bool:
    report_type = str(payload.get("report_type") or "").strip().lower()
    family = str(payload.get("family") or "").strip()
    if not report_type and not family:
        return False
    if report_type and report_type != "daily":
        return False
    if family and family != "jin10_daily_visual":
        return False
    if _has_jin10_non_daily_title_marker(payload.get("title"), payload.get("source_title"), *title_candidates):
        return False
    return True


def get_jin10_report_bundle_latest() -> dict[str, Any] | None:
    base = _storage._PROJECT_ROOT / "storage" / "outputs" / "jin10"
    if not base.exists():
        return None
    for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            payload = _load_jin10_report_bundle(date_dir.name, run_dir.name)
            if payload is not None:
                return payload
    return None


def get_jin10_report_bundle(date: str, run_id: str) -> dict[str, Any] | None:
    return _load_jin10_report_bundle(date, run_id)


def get_jin10_report_bundle_asset_path(date: str, run_id: str, asset_path: str) -> Path | None:
    base = (_storage._PROJECT_ROOT / "storage" / "outputs" / "jin10" / date / run_id).resolve()
    if not base.exists():
        return None
    normalized = str(asset_path or "").strip().replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not normalized or len(parts) != 2 or parts[0] not in {"figures", "images"}:
        return None
    if any(part in {"", ".", ".."} for part in parts):
        return None
    if Path(parts[1]).suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        return None

    legacy_candidate = (base / parts[0] / parts[1]).resolve()
    if legacy_candidate.is_file():
        try:
            legacy_candidate.relative_to(base)
        except ValueError:
            return None
        return legacy_candidate

    # Parsed/original source directories are collector-only. A report may
    # expose an image only after the renderer copied it into this output bundle.
    return None


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _read_optional_text(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


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


def _jin10_report_status(quality_audit: dict[str, Any] | None) -> str:
    status = str((quality_audit or {}).get("status") or "accepted").strip().lower()
    if status in {"rejected", "needs_review", "failed"}:
        return "degraded"
    return "ready"


def _jin10_quality_blocks_content(quality_audit: dict[str, Any] | None) -> bool:
    status = str((quality_audit or {}).get("status") or "accepted").strip().lower()
    reason_codes = set((quality_audit or {}).get("reason_codes") or [])
    return status in {"rejected", "failed"} or (
        status == "needs_review"
        and bool(reason_codes & {"evidence_insufficient", "parse_degraded", "fallback_chart_only"})
    )


def _build_jin10_view_payload(
    *, kind: str, content: str | None, path: Path, asset_base_url: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "available": bool(content and content.strip()),
    }
    if content and content.strip():
        payload["content"] = content
        payload["path"] = str(path.relative_to(_storage._PROJECT_ROOT))
        if asset_base_url:
            payload["asset_base_url"] = asset_base_url
    return payload


def _pick_jin10_default_view(views: dict[str, dict[str, Any]]) -> str:
    for key in ("agent_analysis", "daily_visual"):
        if views.get(key, {}).get("available"):
            return key
    return "agent_analysis"


def _load_jin10_report_bundle(date: str, run_id: str) -> dict[str, Any] | None:
    base = _storage._PROJECT_ROOT / "storage" / "outputs" / "jin10" / date / run_id
    if not base.exists():
        return None
    asset_base_url = f"/api/jin10/report-bundle/{date}/{run_id}/asset/"

    daily_json = _read_optional_json(base / "daily_analysis.json")
    agent_json = _read_optional_json(base / "agent_analysis_report.json")

    views = {
        "agent_analysis": _build_jin10_view_payload(
            kind="markdown",
            content=_read_optional_text(base / "agent_analysis_report.md"),
            path=base / "agent_analysis_report.md",
            asset_base_url=asset_base_url,
        ),
        "daily_visual": _build_jin10_view_payload(
            kind="html",
            content=_read_optional_text(base / "daily_analysis.html"),
            path=base / "daily_analysis.html",
        ),
    }

    if not any(view["available"] for view in views.values()):
        return None

    title = (agent_json or {}).get("title") or (daily_json or {}).get("title")
    source_url = (agent_json or {}).get("source_url") or (daily_json or {}).get("source_url")
    article_id = (
        (agent_json or {}).get("article_id")
        or (daily_json or {}).get("article_id")
        or run_id
    )
    quality_audit = _normalize_jin10_quality_audit(agent_json, daily_json)

    payload = {
        "asset": "XAUUSD",
        "trade_date": date,
        "run_id": run_id,
        "article_id": article_id,
        "title": title,
        "source_url": source_url,
        "default_view": _pick_jin10_default_view(views),
        "views": views,
        "data_category": "external_opinion",
    }
    if quality_audit is not None:
        payload["quality_audit"] = quality_audit
    return payload


def _jin10_source_title(
    raw_payload: dict[str, Any] | None,
    external_meta: dict[str, Any] | None = None,
) -> str | None:
    title = (raw_payload or {}).get("title") or (external_meta or {}).get("title")
    if title:
        return str(title)
    markdown = str((raw_payload or {}).get("article_markdown") or "")
    for line in markdown.splitlines():
        text = line.strip()
        if text.startswith("#"):
            return text.lstrip("#").strip() or None
    return None


def _is_explicit_jin10_weekly(meta: dict[str, Any]) -> bool:
    category = str(meta.get("category") or "").strip()
    category_code = str(meta.get("category_code") or "").strip()
    title = str(meta.get("title") or "").strip()
    return category_code == "536" or "黄金周报" in category or "黄金周报" in title


def _collect_jin10_external_weekly_reports(
    seen: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    external = _JIN10_EXTERNAL_ROOT
    results: list[dict[str, Any]] = []
    seen = seen or set()
    if not external.exists():
        return results
    for date_dir in sorted((d for d in external.iterdir() if d.is_dir()), reverse=True):
        weekly_dir = date_dir / "weekly"
        if not weekly_dir.is_dir():
            continue
        for article_dir in sorted((d for d in weekly_dir.iterdir() if d.is_dir()), reverse=True):
            if (date_dir.name, article_dir.name) in seen:
                continue
            report_md = article_dir / "report.md"
            meta = _read_optional_json(article_dir / "meta.json") or {}
            if not _is_explicit_jin10_weekly(meta):
                continue
            results.append(
                {
                    "type": "jin10_weekly_report",
                    "trade_date": str(meta.get("date") or date_dir.name),
                    "run_id": article_dir.name,
                    "report_id": article_dir.name,
                    "article_id": str(meta.get("id") or article_dir.name),
                    "title": meta.get("title"),
                    "format": "markdown",
                    "available": report_md.exists(),
                    "generated_at": _generated_at_from_paths(report_md, article_dir / "meta.json"),
                }
            )
    return results


def _find_external_jin10_weekly_dir(report_id: str) -> tuple[str, Path] | None:
    external = _JIN10_EXTERNAL_ROOT
    if not external.exists():
        return None
    for date_dir in sorted((item for item in external.iterdir() if item.is_dir()), reverse=True):
        run_dir = date_dir / "weekly" / report_id
        meta = _read_optional_json(run_dir / "meta.json") if run_dir.is_dir() else None
        if run_dir.is_dir() and _is_explicit_jin10_weekly(meta or {}):
            return date_dir.name, run_dir
    return None


def _find_external_jin10_meta(date: str, article_id: str) -> dict[str, Any] | None:
    external = _JIN10_EXTERNAL_ROOT
    candidates = [
        external / date / "weekly" / article_id / "meta.json",
        external / date / "黄金周报" / article_id / "meta.json",
        external / date / "daily" / article_id / "meta.json",
        external / date / "金银报告" / article_id / "meta.json",
        external / date / "报告" / article_id / "meta.json",
    ]
    for path in candidates:
        meta = _read_optional_json(path)
        if isinstance(meta, dict):
            return meta
    return None
