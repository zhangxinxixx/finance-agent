from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.collectors.news.base import NewsCollectionResult, RawNewsItem
from apps.collectors.news.feishu_jin10 import collect_feishu_jin10_messages
from apps.collectors.news.jin10_detail_fetcher import (
    DEFAULT_JIN10_BROWSER_PROFILE,
    LIMITED_ACCESS_STATUSES,
    MIN_VLM_IMAGE_BYTES,
    MIN_VLM_IMAGE_HEIGHT,
    MIN_VLM_IMAGE_WIDTH,
    Jin10DetailFetchResult,
    fetch_jin10_detail_page,
)
from apps.features.news.daily_analysis_triggers import archive_daily_analysis_triggers, build_daily_analysis_triggers
from apps.features.news.event_candidates import build_event_candidates
from apps.features.news.impact_classifier import build_impact_assessments
from apps.features.news.jin10_article_briefs import archive_jin10_article_briefs, build_jin10_article_briefs

DEDICATED_ENV_KEYS = {
    "FEISHU_NEWS_APP_ID",
    "FEISHU_NEWS_APP_SECRET",
    "FEISHU_JIN10_CHAT_ID",
}


def _collect_messages(**kwargs: Any) -> NewsCollectionResult:
    return collect_feishu_jin10_messages(**kwargs)


def _fetch_detail_page(**kwargs: Any) -> Jin10DetailFetchResult:
    return fetch_jin10_detail_page(**kwargs)


def _analysis_as_of(retrieved_date: str) -> str:
    try:
        parsed = datetime.fromisoformat(f"{retrieved_date}T23:59:59+00:00")
    except ValueError:
        return datetime.now(timezone.utc).isoformat()
    return parsed.isoformat()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pull Jin10 messages from a dedicated Feishu chat and fetch accepted detail links."
    )
    parser.add_argument("--storage-root", default="storage", help="finance-agent storage root.")
    parser.add_argument(
        "--retrieved-date",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="Retrieved date in YYYY-MM-DD format. Default: current UTC date.",
    )
    parser.add_argument("--run-id", default=_default_run_id(), help="Logical run id for the summary artifact.")
    parser.add_argument("--chat-id", default=None, help="Optional override for FEISHU_JIN10_CHAT_ID.")
    parser.add_argument("--page-size", type=int, default=20, help="Feishu message page size.")
    parser.add_argument("--max-pages", type=int, default=1, help="Maximum Feishu message pages to pull.")
    parser.add_argument("--max-items", type=int, default=8, help="Maximum accepted detail links to fetch.")
    parser.add_argument("--max-images", type=int, default=8, help="Maximum images to inspect per detail page.")
    parser.add_argument("--run-vlm", action="store_true", help="Run VLM on images that pass size/byte thresholds.")
    parser.add_argument("--min-vlm-width", type=int, default=MIN_VLM_IMAGE_WIDTH)
    parser.add_argument("--min-vlm-height", type=int, default=MIN_VLM_IMAGE_HEIGHT)
    parser.add_argument("--min-vlm-bytes", type=int, default=MIN_VLM_IMAGE_BYTES)
    parser.add_argument(
        "--run-browser-fallback",
        action="store_true",
        help="Use an existing Jin10 browser profile when HTTP detail fetch returns VIP/JS-limited content.",
    )
    parser.add_argument(
        "--browser-profile",
        default=os.getenv("JIN10_BROWSER_PROFILE") or (str(DEFAULT_JIN10_BROWSER_PROFILE) if DEFAULT_JIN10_BROWSER_PROFILE else None),
        help="Jin10 Chromium user data dir for browser fallback. Default: JIN10_BROWSER_PROFILE when set.",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Optional env file to load dedicated Feishu keys from. Default: .env.",
    )
    parser.add_argument("--no-env-file", action="store_true", help="Do not load an env file.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned pull/fetch operation without calling Feishu or writing artifacts.",
    )
    return parser


def _default_run_id() -> str:
    return "feishu-jin10-detail-smoke-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_env_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    loaded: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in DEDICATED_ENV_KEYS or os.getenv(key):
            continue
        os.environ[key] = _strip_env_value(value.strip())
        loaded.append(key)
    return loaded


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _select_detail_items(items: list[RawNewsItem], *, max_items: int) -> list[RawNewsItem]:
    if max_items <= 0:
        return []
    candidates = [
        (index, item)
        for index, item in enumerate(items)
        if item.url.startswith(("http://", "https://"))
    ]
    candidates.sort(key=lambda row: (_detail_item_score(row[1]), -row[0]), reverse=True)
    return [item for _, item in candidates[:max_items]]


def _detail_item_score(item: RawNewsItem) -> float:
    text = " ".join(part for part in (item.title, item.summary) if part)
    raw_payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
    relevance = raw_payload.get("relevance_decision") if isinstance(raw_payload, dict) else {}
    relevance = relevance if isinstance(relevance, dict) else {}
    score = _float(relevance.get("score")) * 0.30
    decision = str(relevance.get("decision") or "")
    if decision == "high_value":
        score += 0.30
    elif decision == "candidate":
        score += 0.16
    if bool(relevance.get("need_detail_fetch")):
        score += 0.10
    if "xnews.jin10.com/details/" in item.url:
        score += 0.18
    elif "flash.jin10.com/detail/" in item.url:
        score += 0.06

    has_gold = _contains_any(text, ["黄金", "金价", "现货黄金", "xau", "gold"])
    has_macro = _contains_any(text, ["美联储", "fed", "fomc", "通胀", "cpi", "pce", "利率", "宽松", "降息", "收益率", "美元", "鸽派"])
    has_energy = _contains_any(text, ["能源", "原油", "油价", "wti", "brent", "霍尔木兹", "伊朗", "美伊"])
    has_level = _contains_any(text, ["动量", "催化剂", "收复", "关键位", "支撑", "阻力", "破位", "多头", "空头"])
    if has_gold:
        score += 0.25
    if has_macro:
        score += 0.18
    if has_energy:
        score += 0.10
    if has_level:
        score += 0.08
    if has_gold and (has_macro or has_energy or has_level):
        score += 0.20
    return round(score, 4)


def _collection_summary(result: NewsCollectionResult) -> dict[str, Any]:
    return {
        "source_key": result.source_key,
        "status": result.status,
        "item_count": len(result.items),
        "warning_count": len(result.warnings),
        "unavailable_feeds": list(result.unavailable_feeds),
        "source_ref_count": len(result.source_refs),
    }


def _detail_summary(*, item: RawNewsItem, result: Jin10DetailFetchResult) -> dict[str, Any]:
    image_assets = list(result.image_assets)
    image_insights = list(result.image_insights)
    return {
        "source_title": item.title,
        "source_url": item.url,
        "status": result.status,
        "access_status": result.access_status,
        "detail_url": result.detail_url,
        "final_url": result.final_url,
        "content_type": result.content_type,
        "title": result.title,
        "raw_text_preview": result.raw_text[:320],
        "raw_html_path": result.raw_html_path,
        "parsed_path": result.parsed_path,
        "image_asset_count": len(image_assets),
        "vlm_eligible_image_count": sum(1 for asset in image_assets if asset.get("vlm_eligible")),
        "vlm_insight_count": len(image_insights),
        "image_assets": image_assets,
        "image_insights": image_insights,
        "error_reason": result.error_reason,
        "fetch_method": result.fetch_method,
        "browser_fallback_attempted": result.browser_fallback_attempted,
        "browser_fallback_status": result.browser_fallback_status,
        "browser_fallback_error": result.browser_fallback_error,
    }


def _write_summary(*, storage_root: Path, retrieved_date: str, run_id: str, payload: dict[str, Any]) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "feishu_jin10_detail_smoke.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    storage_root = Path(args.storage_root).expanduser()
    env_loaded: list[str] = []
    if not args.no_env_file and args.env_file:
        env_loaded = _load_env_file(Path(args.env_file).expanduser())

    base_payload: dict[str, Any] = {
        "run_id": args.run_id,
        "retrieved_date": args.retrieved_date,
        "storage_root": str(storage_root.resolve()),
        "dry_run": bool(args.dry_run),
        "env_file_loaded_keys": sorted(env_loaded),
        "chat_id_configured": bool(args.chat_id or os.getenv("FEISHU_JIN10_CHAT_ID")),
        "page_size": args.page_size,
        "max_pages": args.max_pages,
        "max_items": args.max_items,
        "run_vlm": bool(args.run_vlm),
        "run_browser_fallback": bool(args.run_browser_fallback),
        "browser_profile_configured": bool(args.browser_profile),
        "browser_profile_exists": bool(Path(args.browser_profile).expanduser().exists()) if args.browser_profile else False,
        "vlm_thresholds": {
            "min_width": args.min_vlm_width,
            "min_height": args.min_vlm_height,
            "min_bytes": args.min_vlm_bytes,
        },
    }

    if args.dry_run:
        payload = {
            **base_payload,
            "overall_status": "dry_run",
            "planned_writes": [
                "raw/news/jin10_feishu/<retrieved_date>/messages-page-*.json",
                "parsed/news/jin10_feishu/<retrieved_date>/messages-*.json",
                "raw/news/jin10_detail_pages/<retrieved_date>/*.html",
                "parsed/news/jin10_detail_pages/<retrieved_date>/*.json",
                "features/news/<retrieved_date>/<run_id>/daily_analysis_triggers.json",
                "features/news/<retrieved_date>/<run_id>/jin10_article_briefs.json",
                "features/news/<retrieved_date>/<run_id>/feishu_jin10_detail_smoke.json",
            ],
            "browser_fallback": {
                "enabled": bool(args.run_browser_fallback),
                "profile_configured": bool(args.browser_profile),
                "profile_exists": bool(Path(args.browser_profile).expanduser().exists()) if args.browser_profile else False,
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    collection = _collect_messages(
        retrieved_date=args.retrieved_date,
        storage_root=storage_root,
        chat_id=args.chat_id,
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    as_of = _analysis_as_of(args.retrieved_date)
    event_bundle = build_event_candidates(
        collection.items,
        as_of=as_of,
        source_refs=collection.source_refs,
    )
    impact_assessments = build_impact_assessments(event_bundle.event_candidates, as_of=as_of)
    daily_analysis_trigger_bundle = build_daily_analysis_triggers(
        event_bundle=event_bundle,
        impact_assessments=impact_assessments,
        as_of=as_of,
    )
    daily_analysis_triggers_path = archive_daily_analysis_triggers(
        storage_root=storage_root,
        retrieved_date=args.retrieved_date,
        run_id=args.run_id,
        bundle=daily_analysis_trigger_bundle,
    )
    detail_items = _select_detail_items(collection.items, max_items=max(args.max_items, 0))

    detail_results: list[dict[str, Any]] = []
    detail_pairs: list[tuple[RawNewsItem, Jin10DetailFetchResult]] = []
    for item in detail_items:
        detail = _fetch_detail_page(
            url=item.url,
            storage_root=storage_root,
            retrieved_date=args.retrieved_date,
            run_vlm=args.run_vlm,
            max_images=args.max_images,
            min_vlm_width=args.min_vlm_width,
            min_vlm_height=args.min_vlm_height,
            min_vlm_bytes=args.min_vlm_bytes,
            run_browser_fallback=bool(args.run_browser_fallback),
            browser_profile=Path(args.browser_profile).expanduser() if args.browser_profile else None,
        )
        detail_pairs.append((item, detail))
        detail_results.append(_detail_summary(item=item, result=detail))

    article_brief_bundle = build_jin10_article_briefs(
        items_with_details=detail_pairs,
        as_of=datetime.now(timezone.utc).isoformat(),
    )
    article_briefs_path = archive_jin10_article_briefs(
        storage_root=storage_root,
        retrieved_date=args.retrieved_date,
        run_id=args.run_id,
        bundle=article_brief_bundle,
    )

    failed_details = [row for row in detail_results if row.get("status") != "fetched"]
    payload = {
        **base_payload,
        "overall_status": _overall_status(collection=collection, detail_results=detail_results),
        "collection": _collection_summary(collection),
        "detail_fetch": {
            "requested_count": len(detail_items),
            "fetched_count": sum(1 for row in detail_results if row.get("status") == "fetched"),
            "failed_count": len(failed_details),
            "image_asset_count": sum(int(row.get("image_asset_count") or 0) for row in detail_results),
            "vlm_eligible_image_count": sum(int(row.get("vlm_eligible_image_count") or 0) for row in detail_results),
            "vlm_insight_count": sum(int(row.get("vlm_insight_count") or 0) for row in detail_results),
            "browser_fallback_attempted_count": sum(1 for row in detail_results if row.get("browser_fallback_attempted")),
            "browser_fallback_success_count": sum(
                1
                for row in detail_results
                if row.get("browser_fallback_attempted")
                and row.get("browser_fallback_status") == "success"
                and row.get("access_status") not in LIMITED_ACCESS_STATUSES
            ),
            "results": detail_results,
        },
        "daily_analysis_triggers": {
            "trigger_count": len(daily_analysis_trigger_bundle.triggers),
            "artifact_path": daily_analysis_triggers_path,
            "priority_counts": _count_trigger_priorities(daily_analysis_trigger_bundle.triggers),
            "triggers": [trigger.to_dict() for trigger in daily_analysis_trigger_bundle.triggers],
        },
        "article_briefs": {
            "brief_count": len(article_brief_bundle.briefs),
            "artifact_path": article_briefs_path,
            "display_bucket_counts": article_brief_bundle.data_quality.get("display_bucket_counts", {}),
            "briefs": [brief.to_dict() for brief in article_brief_bundle.briefs],
        },
    }
    payload["artifact_path"] = _write_summary(
        storage_root=storage_root,
        retrieved_date=args.retrieved_date,
        run_id=args.run_id,
        payload=payload,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if payload["overall_status"] in {"unavailable", "error"} else 0


def _overall_status(*, collection: NewsCollectionResult, detail_results: list[dict[str, Any]]) -> str:
    if collection.status != "success":
        return "unavailable"
    if not detail_results:
        return "unavailable"
    if any(row.get("status") != "fetched" for row in detail_results):
        return "partial"
    return "success"


def _count_trigger_priorities(triggers: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trigger in triggers:
        priority = str(getattr(trigger, "priority", "") or "unknown")
        counts[priority] = counts.get(priority, 0) + 1
    return counts


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
