"""Build ordered multimodal content for Jin10 report analysis."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable


ImageLoader = Callable[[dict[str, Any]], str | None]
_IMAGE_MARKDOWN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


@dataclass(slots=True)
class MultimodalContentPlan:
    content: list[dict[str, Any]]
    status: str
    submitted_image_count: int
    degraded_reasons: list[str]
    figure_results: list[dict[str, Any]]


def build_multimodal_user_content(
    prompt: str,
    raw_report: dict[str, Any],
    *,
    image_loader: ImageLoader | None,
    max_images: int = 12,
) -> MultimodalContentPlan:
    """Replace article image markers with metadata plus real image blocks."""

    article = str(raw_report.get("article_markdown") or "")
    before_prompt, article_text, after_prompt = _split_prompt(prompt, article)
    charts = [dict(item) for item in raw_report.get("charts") or [] if isinstance(item, dict)]
    chart_by_path = {
        _normalize_path(str(chart.get("image_path") or "")): chart
        for chart in charts
        if str(chart.get("image_path") or "").strip()
    }
    content: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    reasons: list[str] = []
    submitted = 0
    seen: set[str] = set()
    cursor = 0

    for match in _IMAGE_MARKDOWN.finditer(article_text):
        text = f"{before_prompt if cursor == 0 else ''}{article_text[cursor:match.start()]}"
        _append_text(content, text)
        path = _normalize_path(match.group(1))
        chart = chart_by_path.get(path)
        if chart is None or path in seen:
            _append_text(content, match.group(0))
            cursor = match.end()
            continue
        seen.add(path)
        _append_text(content, _figure_metadata(chart, raw_report))
        status, image_url, reason = _load_image(
            chart,
            image_loader=image_loader,
            submitted=submitted,
            max_images=max_images,
        )
        if image_url:
            content.append({"type": "image_url", "image_url": {"url": image_url, "detail": "original"}})
            submitted += 1
        if reason:
            reasons.append(reason)
        results.append(_figure_result(chart, raw_report=raw_report, status=status))
        cursor = match.end()

    supplemental_charts = [
        chart
        for chart in charts
        if (path := _normalize_path(str(chart.get("image_path") or ""))) and path not in seen
    ]
    prompt_tail = "" if supplemental_charts else after_prompt
    _append_text(content, f"{before_prompt if cursor == 0 else ''}{article_text[cursor:]}{prompt_tail}")

    supplemental_started = False
    for chart in supplemental_charts:
        path = _normalize_path(str(chart.get("image_path") or ""))
        if not supplemental_started:
            _append_text(
                content,
                "\n[Jin10 supplemental figure evidence omitted from article Markdown]\n",
            )
            supplemental_started = True
        _append_text(content, _figure_metadata(chart, raw_report))
        status, image_url, reason = _load_image(
            chart,
            image_loader=image_loader,
            submitted=submitted,
            max_images=max_images,
        )
        if image_url:
            content.append({"type": "image_url", "image_url": {"url": image_url, "detail": "original"}})
            submitted += 1
        if reason:
            reasons.append(reason)
        results.append(_figure_result(chart, raw_report=raw_report, status=status))

    if supplemental_charts:
        _append_text(content, after_prompt)

    if not charts:
        status = "not_applicable"
    elif reasons:
        status = "degraded"
    else:
        status = "success"
    return MultimodalContentPlan(
        content=content,
        status=status,
        submitted_image_count=submitted,
        degraded_reasons=reasons,
        figure_results=results,
    )


def _split_prompt(prompt: str, article: str) -> tuple[str, str, str]:
    if article and article in prompt:
        before, after = prompt.split(article, 1)
        return before, article, after
    return "", prompt, ""


def _append_text(content: list[dict[str, Any]], text: str) -> None:
    if text:
        content.append({"type": "text", "text": text})


def _load_image(
    chart: dict[str, Any],
    *,
    image_loader: ImageLoader | None,
    submitted: int,
    max_images: int,
) -> tuple[str, str | None, str | None]:
    figure_id = _figure_id(chart)
    if submitted >= max(0, max_images):
        return "omitted_limit", None, f"image_limit_exceeded:{figure_id}"
    if image_loader is None:
        return "unavailable", None, f"image_unavailable:{figure_id}"
    try:
        image_url = image_loader(chart)
    except Exception as exc:
        return "error", None, f"image_error:{figure_id}:{type(exc).__name__}"
    if not image_url or not str(image_url).startswith(("data:image/", "http://", "https://")):
        return "unavailable", None, f"image_unavailable:{figure_id}"
    return "submitted", str(image_url), None


def _figure_metadata(chart: dict[str, Any], raw_report: dict[str, Any]) -> str:
    source_ref = _source_ref(chart, raw_report)
    return (
        "\n[Jin10 figure evidence]\n"
        f"figure_id={_figure_id(chart)}\n"
        f"page_no={chart.get('page_no')}\n"
        f"bbox={chart.get('bbox')}\n"
        f"title={chart.get('title') or ''}\n"
        f"recognized_text={chart.get('recognized_text') or ''}\n"
        f"summary={chart.get('summary') or ''}\n"
        f"source_ref={json.dumps(source_ref, ensure_ascii=False, sort_keys=True)}\n"
        "分析图中信息时请引用对应 figure_id 和 page_no。\n"
    )


def _figure_result(chart: dict[str, Any], *, raw_report: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "figure_id": _figure_id(chart),
        "page_no": chart.get("page_no"),
        "bbox": chart.get("bbox"),
        "source_ref": _source_ref(chart, raw_report),
        "status": status,
    }


def _source_ref(chart: dict[str, Any], raw_report: dict[str, Any]) -> dict[str, Any]:
    explicit = chart.get("source_ref")
    if isinstance(explicit, dict):
        return dict(explicit)
    base = next((dict(item) for item in raw_report.get("source_refs") or [] if isinstance(item, dict)), {})
    return {
        **base,
        "article_id": str(raw_report.get("article_id") or base.get("article_id") or ""),
        "figure_id": _figure_id(chart),
        "page_no": chart.get("page_no"),
    }


def _figure_id(chart: dict[str, Any]) -> str:
    return str(chart.get("figure_id") or chart.get("image_path") or "unknown")


def _normalize_path(value: str) -> str:
    return value.strip().split("?", 1)[0].lstrip("./")
