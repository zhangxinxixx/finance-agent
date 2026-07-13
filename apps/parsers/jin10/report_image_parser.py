from __future__ import annotations

import base64
import inspect
import json
import os
import re
import shutil
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import cv2
import numpy as np

from apps.parsers.jin10.vision_recognition_agent import (
    DEFAULT_VISION_PROVIDER,
    DEFAULT_VISION_MODEL,
    normalize_page_markdown,
    recognize_figure_title_bands,
    recognize_pages_unified,
    recognize_pages_layout,
    recognize_pages_as_markdown,
)


PARSER_VERSION = "jin10-vlm-parser-v0.2"
DEFAULT_VISION_PAGE_LIMIT = 0

VisionMarkdownRunner = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]
VisionLayoutRunner = Callable[[list[dict[str, Any]]], dict[str, Any]]
VisionTitleRunner = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
VisionCoverRunner = Callable[[list[dict[str, Any]]], dict[str, Any]]


@dataclass(slots=True)
class PreparedPage:
    original: np.ndarray
    enhanced: np.ndarray
    width: int
    height: int


def parse_report_images(
    *,
    article_id: str,
    title: str,
    published_at: str | None,
    image_entries: list[dict[str, Any]],
    report_type: str | None = None,
    vision_cover_runner: VisionCoverRunner | None = None,
    vision_markdown_runner: VisionMarkdownRunner | None = None,
    vision_layout_runner: VisionLayoutRunner | None = None,
    vision_title_runner: VisionTitleRunner | None = None,
) -> dict[str, Any]:
    """Parse Jin10 report page images with VLM only.

    Legacy text-extraction fallback is intentionally not supported. The deterministic
    image pass only prepares page metadata and crops visual chart regions; all
    article text comes from configured VLM markdown recognition or an
    injected vision runner in tests.
    """

    started_at = _utc_now()
    parser_run_id = started_at.replace(":", "").replace("-", "").replace("+00:00", "Z")
    warnings: list[str] = []
    page_payloads: list[dict[str, Any]] = []
    figures: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    empty_page_count = 0
    cover_page_count = 0
    vision_markdown_payload: dict[str, Any] | None = None
    vision_layout_payload: dict[str, Any] | None = None
    cover_page: dict[str, Any] | None = None
    prepared_pages: dict[int, PreparedPage] = {}

    for image_entry in sorted(image_entries, key=lambda item: int(item.get("seq") or 0)):
        page_no = int(image_entry.get("seq") or len(page_payloads) + 1)
        image_path_value = str(image_entry["path"])
        if _is_remote_image_path(image_path_value):
            warnings.append(f"page_{page_no:03d} remote_image_skipped")
            page_payloads.append(
                {
                    "page_no": page_no,
                    "image_path": image_path_value,
                    "width": int(image_entry.get("width") or 0),
                    "height": int(image_entry.get("height") or 0),
                    "debug_images": _debug_image_refs(page_no),
                }
            )
            continue
        image_path = Path(image_path_value)
        prepared = _prepare_page(image_path)
        if prepared is None:
            empty_page_count += 1
            warnings.append(f"page_{page_no:03d} image_unreadable")
            page_payloads.append(
                {
                    "page_no": page_no,
                    "image_path": str(image_path),
                    "width": 0,
                    "height": 0,
                    "debug_images": _debug_image_refs(page_no),
                }
            )
            continue
        prepared_pages[page_no] = prepared

        is_cover_page = _is_visual_cover_page(page_no=page_no, report_type=report_type)
        if is_cover_page:
            cover_page_count += 1
            warnings.append(f"page_{page_no:03d} cover_page_skipped")

        page_payloads.append(
            {
                "page_no": page_no,
                "image_path": str(image_path),
                "width": prepared.width,
                "height": prepared.height,
                "debug_images": _debug_image_refs(page_no),
            }
        )

        if is_cover_page:
            continue

    sections.sort(key=lambda item: (item.get("page_no") or 0, item["bbox"][1], item["section_id"]))
    page_images = {
        "article_id": article_id,
        "parser_version": PARSER_VERSION,
        "pages": page_payloads,
    }
    structured = {
        "article_id": article_id,
        "parser_version": PARSER_VERSION,
        "title": title,
        "published_at": published_at,
        "sections": sections,
    }
    body_markdown = render_report_structured_markdown(structured)

    cover_pages = [
        page
        for page in page_payloads
        if _is_visual_cover_page(page_no=int(page.get("page_no") or 0), report_type=report_type)
    ]
    if cover_pages:
        cover_runner = vision_cover_runner
        if cover_runner is None and vision_markdown_runner is None and vision_layout_runner is None:
            cover_runner = recognize_pages_unified
    else:
        cover_runner = None
    if cover_runner is not None:
        try:
            cover_payload = _run_vision_unified_runner(
                cover_runner,
                cover_pages[:1],
                report_type=report_type,
                preserve_cover_identity=True,
            )
            cover_page = _cover_page_evidence(cover_payload, expected_page_no=int(cover_pages[0]["page_no"]))
            if cover_page is None:
                warnings.append("cover_page_recognition_empty")
        except Exception as exc:  # pragma: no cover - optional remote parser shield
            message = str(exc).strip().replace("\n", " ")[:240]
            suffix = f":{message}" if message else ""
            warnings.append(f"cover_page_recognition_failed:{exc.__class__.__name__}{suffix}")

    try:
        vision_pages = _vision_target_pages(page_payloads, report_type=report_type)
        vision_candidate_count = sum(
            1
            for page in page_payloads
            if not _is_visual_cover_page(page_no=int(page.get("page_no") or 0), report_type=report_type)
        )
        if len(vision_pages) < vision_candidate_count:
            warnings.append(
                f"vision_page_limit_applied:{len(vision_pages)}/{vision_candidate_count}"
            )
        provisional_figures = _provisional_figures_from_pages(vision_pages, report_type=report_type)
        layout_failed = False
        unified_payload: dict[str, Any] | None = None
        layout_runner = vision_layout_runner
        if layout_runner is None and vision_markdown_runner is None:
            try:
                unified_payload = _run_vision_unified_runner(
                    recognize_pages_unified,
                    vision_pages,
                    report_type=report_type,
                )
                vision_layout_payload = _sanitize_layout_payload_for_report(unified_payload)
                warnings.append("vision_unified_page_recognition_primary")
            except Exception as exc:  # pragma: no cover - remote parser fallback
                layout_failed = True
                message = str(exc).strip().replace("\n", " ")[:240]
                if message:
                    warnings.append(f"vision_unified_failed:{exc.__class__.__name__}:{message}")
                else:
                    warnings.append(f"vision_unified_failed:{exc.__class__.__name__}")
                layout_runner = recognize_pages_layout
        if layout_runner is not None and vision_layout_payload is None:
            try:
                vision_layout_payload = layout_runner(vision_pages)
                vision_layout_payload = _sanitize_layout_payload_for_report(vision_layout_payload)
            except Exception as exc:  # pragma: no cover - remote parser fallback
                layout_failed = True
                message = str(exc).strip().replace("\n", " ")[:240]
                if message:
                    warnings.append(f"vision_layout_failed:{exc.__class__.__name__}:{message}")
                else:
                    warnings.append(f"vision_layout_failed:{exc.__class__.__name__}")

        if vision_layout_payload:
            figures = _merge_layout_figures(figures=[], layout_payload=vision_layout_payload)
            figures = _dedupe_and_prune_figures(figures=figures, page_payloads=page_payloads)
            figures = _snap_figures_to_white_chart_panels(figures=figures, prepared_pages=prepared_pages)
            figures = _fill_missing_titles_from_title_bands(
                figures=figures,
                prepared_pages=prepared_pages,
                title_runner=vision_title_runner,
            )
            if not figures and _layout_payload_has_chart_like_blocks(vision_layout_payload):
                figures = list(provisional_figures)
            if unified_payload is not None:
                layout_markdown_payload = _unified_payload_to_vision_markdown_payload(unified_payload)
            else:
                layout_markdown_payload = _layout_payload_to_vision_markdown_payload(
                    title=title,
                    published_at=published_at,
                    layout_payload=vision_layout_payload,
                    figures=figures,
                )
            layout_markdown_payload = _normalize_vision_markdown_payload(
                layout_markdown_payload,
                figures,
                prune_duplicate_images=True,
                prune_unmapped_local_images=True,
            )
            vision_markdown_payload = layout_markdown_payload
            vision_body_markdown = render_vision_markdown(
                title=title,
                published_at=published_at,
                vision_markdown=vision_markdown_payload,
            )
            if unified_payload is None:
                legacy_runner = vision_markdown_runner or recognize_pages_as_markdown
                try:
                    markdown_ocr_payload = _run_vision_markdown_runner(
                        legacy_runner,
                        vision_pages,
                        figures,
                        report_type=report_type,
                    )
                    markdown_ocr_payload = _normalize_vision_markdown_payload(
                        markdown_ocr_payload,
                        figures,
                        prune_duplicate_images=True,
                        prune_unmapped_local_images=True,
                    )
                    markdown_ocr_payload = _merge_markdown_ocr_pages(
                        base_payload=markdown_ocr_payload,
                        fallback_payload=layout_markdown_payload,
                    )
                    markdown_ocr_body = render_vision_markdown(
                        title=title,
                        published_at=published_at,
                        vision_markdown=markdown_ocr_payload,
                    )
                    if _has_substantive_vision_markdown(markdown_ocr_body, title=title):
                        vision_markdown_payload = markdown_ocr_payload
                        vision_body_markdown = markdown_ocr_body
                        warnings.append("vision_markdown_full_page_ocr_primary")
                except Exception as exc:  # pragma: no cover - remote parser fallback
                    message = str(exc).strip().replace("\n", " ")[:240]
                    if message:
                        warnings.append(f"vision_markdown_full_page_ocr_failed:{exc.__class__.__name__}:{message}")
                    else:
                        warnings.append(f"vision_markdown_full_page_ocr_failed:{exc.__class__.__name__}")

            fallback_pages = _pages_requiring_markdown_ocr(
                page_payloads=vision_pages,
                vision_markdown=vision_markdown_payload,
                report_type=report_type,
            )
            if fallback_pages:
                fallback_page_nos = [int(page["page_no"]) for page in fallback_pages]
                warnings.append(
                    "vision_markdown_page_ocr_fallback:"
                    + ",".join(str(page_no) for page_no in fallback_page_nos)
                )
                legacy_runner = vision_markdown_runner or recognize_pages_as_markdown
                fallback_payload = _run_vision_markdown_runner(
                    legacy_runner,
                    fallback_pages,
                    figures,
                    report_type=report_type,
                )
                fallback_payload = _normalize_vision_markdown_payload(
                    fallback_payload,
                    figures,
                    prune_duplicate_images=True,
                    prune_unmapped_local_images=True,
                )
                vision_markdown_payload = _merge_markdown_ocr_pages(
                    base_payload=vision_markdown_payload,
                    fallback_payload=fallback_payload,
                )
                vision_markdown_payload = _normalize_vision_markdown_payload(
                    vision_markdown_payload,
                    figures,
                    prune_duplicate_images=True,
                    prune_unmapped_local_images=True,
                )
                vision_body_markdown = render_vision_markdown(
                    title=title,
                    published_at=published_at,
                    vision_markdown=vision_markdown_payload,
                )
        else:
            vision_body_markdown = ""

        if not _has_substantive_vision_markdown(vision_body_markdown, title=title):
            legacy_runner = vision_markdown_runner or recognize_pages_as_markdown
            legacy_payload = _run_vision_markdown_runner(
                legacy_runner,
                vision_pages,
                figures,
                report_type=report_type,
            )
            legacy_payload = _normalize_vision_markdown_payload(
                legacy_payload,
                figures,
                prune_duplicate_images=True,
                prune_unmapped_local_images=vision_layout_payload is not None,
            )
            legacy_body_markdown = render_vision_markdown(
                title=title,
                published_at=published_at,
                vision_markdown=legacy_payload,
            )
            if _has_substantive_vision_markdown(legacy_body_markdown, title=title):
                vision_markdown_payload = legacy_payload
                vision_body_markdown = legacy_body_markdown

        if vision_markdown_payload:
            figures = _merge_missing_fallback_figures(
                figures=figures,
                page_payloads=page_payloads,
                prepared_pages=prepared_pages,
                vision_markdown=vision_markdown_payload,
            )
            figures = _dedupe_and_prune_figures(figures=figures, page_payloads=page_payloads)
            figures = _snap_figures_to_white_chart_panels(figures=figures, prepared_pages=prepared_pages)
            vision_markdown_payload = _normalize_vision_markdown_payload(
                vision_markdown_payload,
                figures,
                prune_duplicate_images=True,
                prune_unmapped_local_images=True,
            )
            vision_body_markdown = render_vision_markdown(
                title=title,
                published_at=published_at,
                vision_markdown=vision_markdown_payload,
            )
        if not figures and vision_layout_payload is None and not layout_failed:
            figures = _fallback_detect_visual_figures(
                page_payloads=page_payloads,
                prepared_pages=prepared_pages,
                report_type=report_type,
            )
        if figures:
            sections = _rebuild_sections_with_figures(article_id=article_id, figures=figures, sections=sections)
            structured["sections"] = sections
            if vision_markdown_payload:
                vision_markdown_payload = _normalize_vision_markdown_payload(
                    vision_markdown_payload,
                    figures,
                    prune_duplicate_images=True,
                    prune_unmapped_local_images=True,
                )
        if _has_substantive_vision_markdown(vision_body_markdown, title=title):
            body_markdown = vision_body_markdown
    except Exception as exc:  # pragma: no cover - defensive shield for optional remote parser
        message = str(exc).strip().replace("\n", " ")[:240]
        if message:
            warnings.append(f"vision_markdown_failed:{exc.__class__.__name__}:{message}")
        else:
            warnings.append(f"vision_markdown_failed:{exc.__class__.__name__}")

    figure_count = len(figures)
    finished_at = _utc_now()
    vision_provider = os.getenv("JIN10_VISION_PROVIDER", DEFAULT_VISION_PROVIDER).strip().lower() or DEFAULT_VISION_PROVIDER
    vision_model = (
        os.getenv("JIN10_VISION_MODEL", "").strip()
        or os.getenv("JIN10_MIMO_VL_MODEL", "").strip()
        or DEFAULT_VISION_MODEL
    )
    status = {
        "article_id": article_id,
        "parser_version": PARSER_VERSION,
        "parser_run_id": parser_run_id,
        "status": "success" if page_payloads else "empty",
        "recognition_mode": "vlm",
        "vision_provider": vision_provider,
        "vision_model": vision_model,
        "started_at": started_at,
        "finished_at": finished_at,
        "pages_total": len(page_payloads),
        "figures_total": figure_count,
        "section_count": len(sections),
        "paragraph_count": 0,
        "cover_page_count": cover_page_count,
        "cover_page_status": str((cover_page or {}).get("status") or ("failed" if cover_pages else "not_applicable")),
        "empty_page_count": empty_page_count,
        "warnings": warnings,
    }
    if vision_markdown_payload:
        status["vision_markdown_status"] = _vision_status(vision_markdown_payload)
        status["vision_pages_total"] = len(vision_markdown_payload.get("pages", []))
    if vision_layout_payload:
        status["vision_layout_status"] = _vision_status(vision_layout_payload)
    if any(str(item).startswith("vision_markdown_failed:") for item in warnings) and "vision_markdown_status" not in status:
        status["vision_markdown_status"] = "failed"
    if any(str(item).startswith("vision_layout_failed:") for item in warnings) and "vision_layout_status" not in status:
        status["vision_layout_status"] = "failed"
    return {
        "page_images": page_images,
        "figures": {
            "article_id": article_id,
            "parser_version": PARSER_VERSION,
            "figures": figures,
        },
        "report_structured": structured,
        "parse_status": status,
        "vision_markdown": vision_markdown_payload,
        "vision_layout": vision_layout_payload,
        "cover_page": cover_page,
        "body_markdown": body_markdown,
    }


def _cover_page_evidence(payload: dict[str, Any], *, expected_page_no: int) -> dict[str, Any] | None:
    pages = payload.get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, list):
        return None
    page = next(
        (item for item in pages if isinstance(item, dict) and int(item.get("page_no") or 0) == expected_page_no),
        None,
    )
    if page is None:
        return None
    markdown = str(page.get("markdown") or "").strip()
    block_texts = [
        str(block.get("text") or "").strip()
        for block in page.get("blocks") or []
        if isinstance(block, dict) and str(block.get("text") or "").strip()
    ]
    recognized_text = markdown or "\n".join(block_texts)
    return {
        "page_no": expected_page_no,
        "status": str(page.get("status") or ("success" if recognized_text else "empty")),
        "provider": str(payload.get("provider") or ""),
        "model": str(payload.get("model") or ""),
        "recognized_text": recognized_text,
        "markdown": markdown,
        "blocks": deepcopy(page.get("blocks") or []),
    }


def _fallback_detect_visual_figures(
    *,
    page_payloads: list[dict[str, Any]],
    prepared_pages: dict[int, PreparedPage],
    report_type: str | None = None,
) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for page in page_payloads:
        page_no = int(page.get("page_no") or 0)
        if _is_visual_cover_page(page_no=page_no, report_type=report_type):
            continue
        prepared = prepared_pages.get(page_no)
        if prepared is None:
            continue
        figures.extend(_detect_visual_figures(page_no=page_no, prepared=prepared))
    return figures


def _run_vision_markdown_runner(
    runner: VisionMarkdownRunner,
    pages: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    *,
    report_type: str | None = None,
) -> dict[str, Any]:
    if runner is recognize_pages_as_markdown:
        return recognize_pages_as_markdown(pages, figures, report_type=report_type)
    if "report_type" in inspect.signature(runner).parameters:
        return runner(pages, figures, report_type=report_type)
    return runner(pages, figures)


def _run_vision_unified_runner(
    runner: VisionLayoutRunner,
    pages: list[dict[str, Any]],
    *,
    report_type: str | None = None,
    preserve_cover_identity: bool = False,
) -> dict[str, Any]:
    parameters = inspect.signature(runner).parameters
    kwargs: dict[str, Any] = {}
    if "report_type" in parameters:
        kwargs["report_type"] = report_type
    if "preserve_cover_identity" in parameters:
        kwargs["preserve_cover_identity"] = preserve_cover_identity
    return runner(pages, **kwargs)


def _provisional_figures_from_pages(page_payloads: list[dict[str, Any]], *, report_type: str | None = None) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for page in page_payloads:
        page_no = int(page.get("page_no") or 0)
        if page_no <= 0 or _is_visual_cover_page(page_no=page_no, report_type=report_type):
            continue
        width = int(page.get("width") or 0)
        height = int(page.get("height") or 0)
        if width <= 0 or height <= 0:
            continue
        figures.append(
            {
                "figure_id": f"fig_p{page_no}_001",
                "page_no": page_no,
                "bbox": [0, 0, width, height],
                "chart_image_path": f"figures/fig_p{page_no}_001.png",
                "title": f"图表 {page_no}-1",
                "nearby_text": "",
                "chart_type": "unknown",
                "confidence": 0.0,
            }
        )
    return figures


def figure_image_data_url(artifacts: dict[str, Any], chart: dict[str, Any]) -> str:
    """Crop one parsed figure from its source page and return a PNG data URI."""

    crop = _figure_crop(artifacts, chart)
    ok, encoded = cv2.imencode(".png", crop)
    if not ok:
        raise ValueError("figure_image_encode_failed")
    payload = base64.b64encode(encoded.tobytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def figure_analysis_image_data_url(
    artifacts: dict[str, Any],
    chart: dict[str, Any],
    *,
    max_long_edge: int = 1600,
    jpeg_quality: int = 92,
) -> str:
    """Return a size-bounded JPEG data URI for formal Agent analysis."""

    crop = _figure_crop(artifacts, chart)
    height, width = crop.shape[:2]
    longest = max(height, width)
    if max_long_edge > 0 and longest > max_long_edge:
        scale = max_long_edge / longest
        crop = cv2.resize(
            crop,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    quality = max(1, min(100, int(jpeg_quality)))
    ok, encoded = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("figure_analysis_image_encode_failed")
    payload = base64.b64encode(encoded.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{payload}"


def _figure_crop(artifacts: dict[str, Any], chart: dict[str, Any]) -> np.ndarray:
    """Load and crop one parsed figure from its canonical source page."""

    page_no = int(chart.get("page_no") or 0)
    pages = ((artifacts.get("page_images") or {}).get("pages") or [])
    page = next((item for item in pages if int(item.get("page_no") or 0) == page_no), None)
    if not isinstance(page, dict):
        raise ValueError("figure_source_page_not_found")
    image_path = Path(str(page.get("image_path") or ""))
    prepared = _prepare_page(image_path)
    if prepared is None:
        raise ValueError("figure_source_image_unreadable")
    bbox = chart.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError("figure_bbox_invalid")
    return _crop_bbox(prepared.original, bbox)


def write_parse_artifacts(artifacts: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    debug_dir = output_dir / "debug"
    paths_to_reset = [figures_dir]
    if _write_debug_images_enabled():
        paths_to_reset.append(debug_dir)
    elif debug_dir.exists():
        shutil.rmtree(debug_dir)
    for path in paths_to_reset:
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    page_images_payload = deepcopy(artifacts["page_images"])
    figures_payload = deepcopy(artifacts["figures"])
    structured = deepcopy(artifacts["report_structured"])
    parse_status = deepcopy(artifacts["parse_status"])
    vision_markdown = deepcopy(artifacts.get("vision_markdown"))
    vision_layout = deepcopy(artifacts.get("vision_layout"))
    cover_page = deepcopy(artifacts.get("cover_page"))

    page_map = {page["page_no"]: page for page in page_images_payload["pages"]}
    page_image_paths = {page["page_no"]: Path(page["image_path"]) for page in page_images_payload["pages"] if page["image_path"]}

    if _write_debug_images_enabled():
        for page_no, image_path in page_image_paths.items():
            prepared = _prepare_page(image_path)
            if prepared is None:
                continue
            original_path = debug_dir / f"page_{page_no:03d}_original.png"
            enhanced_path = debug_dir / f"page_{page_no:03d}_enhanced.png"
            cv2.imwrite(str(original_path), prepared.original)
            cv2.imwrite(str(enhanced_path), prepared.enhanced)
            page_map[page_no]["debug_images"] = {
                "original": f"debug/{original_path.name}",
                "enhanced": f"debug/{enhanced_path.name}",
            }
    else:
        for page in page_map.values():
            page.pop("debug_images", None)

    figure_map = {item["figure_id"]: item for item in figures_payload["figures"]}
    for figure in figures_payload["figures"]:
        page_path = page_image_paths.get(figure["page_no"])
        if page_path is None:
            continue
        prepared = _prepare_page(page_path)
        if prepared is None:
            continue
        crop = _crop_bbox(prepared.original, figure["bbox"])
        figure_path = figures_dir / Path(figure["chart_image_path"]).name
        cv2.imwrite(str(figure_path), crop)
        figure["chart_image_path"] = f"figures/{figure_path.name}"

    for section in structured["sections"]:
        populated = []
        for figure in section.pop("figures", []):
            matched = figure_map.get(figure["figure_id"], figure)
            populated.append(
                {
                    "figure_id": matched["figure_id"],
                    "chart_image_path": matched["chart_image_path"],
                    "title": matched.get("title") or "",
                }
            )
        if populated:
            section["figures"] = populated

    targets = {
        "page_images": output_dir / "page_images.json",
        "figures": output_dir / "figures.json",
        "report_structured": output_dir / "report_structured.json",
        "parse_status": output_dir / "parse_status.json",
    }
    payloads = {
        "page_images": page_images_payload,
        "figures": figures_payload,
        "report_structured": structured,
        "parse_status": parse_status,
    }
    if vision_markdown:
        targets["vision_markdown"] = output_dir / "vision_markdown.json"
        payloads["vision_markdown"] = vision_markdown
    if vision_layout:
        targets["vision_layout"] = output_dir / "vision_layout.json"
        payloads["vision_layout"] = vision_layout
    if cover_page:
        targets["cover_page"] = output_dir / "cover_page.json"
        payloads["cover_page"] = cover_page
    for key, target in targets.items():
        target.write_text(json.dumps(payloads[key], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: str(path) for key, path in targets.items()}


def render_report_structured_markdown(structured: dict[str, Any]) -> str:
    lines = [f"# {structured.get('title') or structured.get('article_id')}", ""]
    published_at = structured.get("published_at")
    if published_at:
        lines.extend([f"- 发布时间: {published_at}", ""])
    for section in structured.get("sections", []):
        title = section.get("title") or ""
        if title:
            lines.extend([f"## {title}", ""])
        for figure in section.get("figures") or []:
            image_path = figure.get("chart_image_path")
            if image_path:
                caption = figure.get("title") or figure.get("figure_id") or "图表"
                lines.extend([f"![{caption}]({image_path})", ""])
        text = (section.get("text") or "").strip()
        if text:
            lines.extend([text, ""])
    return "\n".join(lines).strip() + "\n"


def render_vision_markdown(
    *,
    title: str,
    published_at: str | None,
    vision_markdown: dict[str, Any],
) -> str:
    normalized_title = _normalize_report_title(title)
    raw_page_chunks = []
    for page in sorted(vision_markdown.get("pages", []), key=lambda item: int(item.get("page_no") or 0)):
        markdown = str(page.get("markdown") or "").strip()
        page_no = int(page.get("page_no") or 0)
        if page.get("status") != "success" or not markdown:
            continue
        if _is_cover_page_markdown(page_no, markdown) or _should_skip_vision_page_markdown(page_no, markdown):
            continue
        cleaned = _clean_vision_page_chunk(markdown)
        cleaned = _strip_report_shell_lines(cleaned, title=title, published_at=published_at)
        if not cleaned:
            continue
        raw_page_chunks.append(cleaned)
    page_chunks = _stitch_vision_page_chunks(raw_page_chunks)
    if not page_chunks:
        return ""
    lines = [f"# {normalized_title or title}", ""]
    if published_at:
        lines.extend([f"- 发布时间: {published_at}", ""])
    lines.extend(page_chunks)
    return "\n\n".join(chunk for chunk in lines if chunk).strip() + "\n"


def _layout_payload_to_vision_markdown_payload(
    *,
    title: str,
    published_at: str | None,
    layout_payload: dict[str, Any],
    figures: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not layout_payload:
        return None
    figure_map: dict[int, list[dict[str, Any]]] = {}
    for figure in figures:
        figure_map.setdefault(int(figure["page_no"]), []).append(figure)

    normalized_pages: list[dict[str, Any]] = []
    for page in sorted(layout_payload.get("pages", []), key=lambda item: int(item.get("page_no") or 0)):
        page_no = int(page.get("page_no") or 0)
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        page_figures = figure_map.get(page_no, [])
        markdown = _render_layout_page_markdown(
            page_no=page_no,
            page=page,
            blocks=blocks,
            figures=page_figures,
            title=title,
        )
        page_payload = {
            "page_no": page_no,
            "status": "success" if markdown.strip() else "empty",
            "markdown": markdown,
            "blocks": blocks,
            "model": page.get("model") or layout_payload.get("model"),
        }
        image_size = page.get("image_size")
        if isinstance(image_size, dict):
            page_payload["image_size"] = image_size
        normalized_pages.append(page_payload)
    return {
        "provider": layout_payload.get("provider"),
        "model": layout_payload.get("model"),
        "pages": normalized_pages,
    }


def _unified_payload_to_vision_markdown_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    normalized_pages: list[dict[str, Any]] = []
    for page in sorted(payload.get("pages", []), key=lambda item: int(item.get("page_no") or 0)):
        if not isinstance(page, dict):
            continue
        page_payload = {
            "page_no": int(page.get("page_no") or 0),
            "status": page.get("status") or ("success" if str(page.get("markdown") or "").strip() else "empty"),
            "markdown": str(page.get("markdown") or ""),
            "blocks": page.get("blocks") if isinstance(page.get("blocks"), list) else [],
            "model": page.get("model") or payload.get("model"),
        }
        image_size = page.get("image_size")
        if isinstance(image_size, dict):
            page_payload["image_size"] = image_size
        normalized_pages.append(page_payload)
    return {
        "provider": payload.get("provider") or DEFAULT_VISION_PROVIDER,
        "model": payload.get("model"),
        "pages": normalized_pages,
    }


def _layout_payload_has_chart_like_blocks(layout_payload: dict[str, Any]) -> bool:
    for page in layout_payload.get("pages", []):
        if not isinstance(page, dict):
            continue
        if _layout_page_is_low_value_technical_indicator(page):
            continue
        blocks = page.get("blocks")
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if _layout_block_is_low_value_technical_indicator(block):
                continue
            if str(block.get("type") or "").strip().lower() in {"chart", "image", "table"}:
                return True
    return False


def _render_layout_page_markdown(
    *,
    page_no: int,
    page: dict[str, Any],
    blocks: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    title: str,
) -> str:
    if _layout_page_is_low_value_technical_indicator(page):
        return ""

    ordered_blocks = _order_layout_blocks(blocks)
    figure_iter = iter(sorted(figures, key=lambda item: (item["bbox"][1], item["bbox"][0], item["figure_id"])))
    lines: list[str] = []
    pending_title: str | None = None

    def flush_pending_title() -> None:
        nonlocal pending_title
        if pending_title and not _is_noise_line(pending_title):
            lines.extend([f"## {pending_title}", ""])
        pending_title = None

    page_title = str(page.get("title") or "").strip()
    if (
        page_title
        and not _is_noise_line(page_title)
        and not _is_low_value_technical_indicator_text(page_title)
    ):
        lines.extend([f"## {page_title}", ""])
    for block in ordered_blocks:
        block_type = str(block.get("type") or "unknown").strip().lower()
        text = _clean_layout_block_text(str(block.get("text") or ""))
        if _layout_block_is_low_value_technical_indicator(block):
            pending_title = None
            continue
        if block_type == "title":
            if text and text != title and not _is_noise_line(text):
                pending_title = text
            continue
        if block_type == "text":
            if text and not _is_noise_line(text):
                flush_pending_title()
                lines.extend([text, ""])
            continue
        if block_type in {"chart", "image", "table"}:
            figure = next(figure_iter, None)
            if figure is None:
                figure = {
                    "chart_image_path": f"figures/fig_p{page_no}_{len([line for line in lines if line.strip().startswith('![')]) + 1:03d}.png",
                    "title": text or f"图表 {page_no}",
                }
            figure_title = str(figure.get("title") or "").strip()
            text_caption = "" if _is_generic_chart_title(text) else text
            figure_caption = "" if _is_generic_chart_title(figure_title) else figure_title
            if (text_caption or figure_caption) and pending_title not in {text_caption, figure_caption}:
                flush_pending_title()
            caption = text_caption or figure_caption or pending_title or figure_title or text or f"图表 {page_no}"
            pending_title = None
            image_path = str(figure.get("chart_image_path") or "").strip()
            if image_path:
                if caption and not _is_noise_line(caption):
                    lines.extend([f"## {caption}", ""])
                lines.append(f"![{caption}]({image_path})")
                lines.append("")
            elif caption and not _is_noise_line(caption):
                lines.extend([caption, ""])
            continue
        if text and not _is_noise_line(text):
            flush_pending_title()
            lines.extend([text, ""])

    flush_pending_title()
    if not lines:
        fallback = [f"# {title}"] if page_no == 1 and title else []
        return "\n".join(fallback).strip()
    return "\n".join(lines).strip()


def _order_layout_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(block: dict[str, Any]) -> tuple[int, int, int]:
        bbox = block.get("bbox") if isinstance(block.get("bbox"), list) else [0, 0, 0, 0]
        try:
            x1, y1, _, _ = [int(float(value)) for value in bbox[:4]]
        except (TypeError, ValueError):
            x1, y1 = 0, 0
        priority_map = {"title": 0, "text": 1, "table": 2, "chart": 3, "image": 4, "unknown": 5}
        block_type = str(block.get("type") or "unknown").strip().lower()
        return (y1, x1, priority_map.get(block_type, 5))

    return sorted([block for block in blocks if isinstance(block, dict)], key=sort_key)


def _clean_layout_block_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned.strip()


def _sanitize_layout_payload_for_report(layout_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(layout_payload, dict):
        return layout_payload
    sanitized_pages: list[dict[str, Any]] = []
    for page in layout_payload.get("pages", []):
        if not isinstance(page, dict):
            continue
        if _layout_page_is_low_value_technical_indicator(page):
            continue
        page_copy = dict(page)
        blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
        page_copy["blocks"] = [
            dict(block)
            for block in blocks
            if isinstance(block, dict) and not _layout_block_is_low_value_technical_indicator(block)
        ]
        charts = page.get("charts") if isinstance(page.get("charts"), list) else []
        if charts:
            page_copy["charts"] = [
                dict(chart)
                for chart in charts
                if isinstance(chart, dict) and not _layout_block_is_low_value_technical_indicator(chart)
            ]
        sanitized_pages.append(page_copy)
    sanitized = dict(layout_payload)
    sanitized["pages"] = sanitized_pages
    return sanitized


def _layout_page_is_low_value_technical_indicator(page: dict[str, Any]) -> bool:
    blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
    if not blocks:
        return False
    texts = [
        _clean_layout_block_text(str(block.get("text") or block.get("title") or ""))
        for block in blocks
        if isinstance(block, dict)
    ]
    if not any(_is_low_value_technical_indicator_text(text) for text in texts):
        return False
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "unknown").strip().lower()
        if block_type in {"chart", "image", "table"}:
            continue
        text = _clean_layout_block_text(str(block.get("text") or block.get("title") or ""))
        if not text:
            continue
        if _is_low_value_technical_indicator_text(text) or _is_noise_line(text):
            continue
        if text in {"技术指标", "国际现货黄金", "国际现货白银"}:
            continue
        return False
    return True


def _layout_block_is_low_value_technical_indicator(block: dict[str, Any]) -> bool:
    text = _clean_layout_block_text(str(block.get("text") or block.get("title") or ""))
    return _is_low_value_technical_indicator_text(text)


def _is_low_value_technical_indicator_text(text: str) -> bool:
    compact = "".join(str(text or "").split())
    if not compact:
        return False
    if "恐惧贪婪指标" in compact:
        return True
    return "50为中性" in compact and "超过70" in compact and "低于30" in compact


def _is_generic_chart_title(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if normalized == "图表标题":
        return True
    return re.fullmatch(r"图表\s*\d+(?:-\d+)?", normalized) is not None


def _stitch_vision_page_chunks(page_chunks: list[str]) -> list[str]:
    if not page_chunks:
        return []
    stitched = [page_chunks[0]]
    for chunk in page_chunks[1:]:
        previous = stitched[-1]
        stitched[-1], current = _stitch_chunk_pair(previous, chunk)
        if current.strip():
            stitched.append(current)
    return stitched


def _stitch_chunk_pair(previous: str, current: str) -> tuple[str, str]:
    prev_lines = previous.splitlines()
    curr_lines = current.splitlines()

    prev_idx = _last_content_line_index(prev_lines)
    curr_idx = _first_content_line_index(curr_lines)
    if prev_idx is None or curr_idx is None:
        return previous, current

    prev_line = prev_lines[prev_idx].rstrip()
    curr_line = curr_lines[curr_idx].lstrip()

    if _should_merge_cross_page_lines(prev_line, curr_line):
        prev_lines[prev_idx] = f"{prev_line}{curr_line}"
        curr_lines[curr_idx] = ""
    return "\n".join(prev_lines), "\n".join(curr_lines)


def _last_content_line_index(lines: list[str]) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip():
            return index
    return None


def _first_content_line_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip():
            return index
    return None


def _should_merge_cross_page_lines(previous: str, current: str) -> bool:
    prev = previous.strip()
    curr = current.strip()
    if not prev or not curr:
        return False
    if any(curr.startswith(prefix) for prefix in ("#", "-", "!", ">", "* ", "1. ")):
        return False
    if any(prev.startswith(prefix) for prefix in ("#", "-", "!", ">", "* ", "1. ")):
        return False
    if prev.endswith(("。", "！", "？", "；", "：", ".", "”", "」", "』")):
        return False
    return True


def _clean_vision_page_chunk(markdown: str) -> str:
    cleaned_lines: list[str] = []
    skip_blank = False
    for raw_line in markdown.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("## 目录"):
            skip_blank = True
            continue
        if _is_noise_line(stripped):
            skip_blank = True
            continue
        if _looks_like_directory_item(stripped):
            skip_blank = True
            continue
        if _is_low_value_technical_indicator_text(stripped):
            skip_blank = True
            continue
        if skip_blank and not stripped:
            continue
        skip_blank = False
        cleaned_lines.append(_normalize_markdown_heading_line(raw_line) if stripped.startswith("#") else raw_line)
    cleaned = "\n".join(cleaned_lines).strip()
    if not cleaned:
        return ""

    normalized_lines = cleaned.splitlines()
    first_index = _first_content_line_index(normalized_lines)
    if first_index is not None:
        first_line = normalized_lines[first_index].strip()
        if first_line.startswith("#"):
            normalized_lines[first_index] = _normalize_markdown_heading_line(normalized_lines[first_index])
        elif _is_plain_section_heading_candidate(first_line):
            normalized_lines[first_index] = f"## {first_line}"
    return "\n".join(normalized_lines).strip()


def _strip_report_shell_lines(markdown: str, *, title: str, published_at: str | None) -> str:
    if not markdown.strip():
        return ""
    title_compact = _compact_report_shell_text(title)
    published_date = _compact_report_shell_date(published_at)
    cleaned: list[str] = []
    last_blank = False
    for raw_line in markdown.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if not last_blank:
                cleaned.append("")
            last_blank = True
            continue
        compact = _compact_report_shell_text(stripped.lstrip("#").strip())
        if title_compact and compact == title_compact:
            continue
        if published_date and compact == published_date:
            continue
        if _looks_like_report_shell_date_line(stripped):
            continue
        cleaned.append(raw_line)
        last_blank = False
    return "\n".join(cleaned).strip()


def _vision_target_pages(page_payloads: list[dict[str, Any]], *, report_type: str | None = None) -> list[dict[str, Any]]:
    page_payloads = [
        page
        for page in page_payloads
        if not _is_visual_cover_page(page_no=int(page.get("page_no") or 0), report_type=report_type)
    ]
    limit = _vision_page_limit()
    if limit <= 0 or len(page_payloads) <= limit:
        return page_payloads
    if _vision_page_selection_mode() == "head":
        return page_payloads[:limit]
    if len(page_payloads) > 12:
        return _distributed_vision_target_pages(page_payloads, limit)
    if limit == 1:
        return page_payloads[:1]
    head_count = max(1, limit // 2)
    tail_count = max(1, limit - head_count)
    selected = page_payloads[:head_count] + page_payloads[-tail_count:]
    deduped: list[dict[str, Any]] = []
    seen_pages: set[int] = set()
    for page in selected:
        page_no = int(page.get("page_no") or 0)
        if page_no in seen_pages:
            continue
        seen_pages.add(page_no)
        deduped.append(page)
    return deduped


def _distributed_vision_target_pages(page_payloads: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    total = len(page_payloads)
    head_count = min(2, limit)
    selected_indexes = list(range(head_count))
    remaining = max(0, limit - head_count)
    sample_start = head_count
    sample_pool = list(range(sample_start, total))
    if remaining >= len(sample_pool):
        selected_indexes.extend(sample_pool)
    elif remaining == 1:
        selected_indexes.append(sample_pool[-1])
    elif remaining > 1:
        max_pos = len(sample_pool) - 1
        positions = {
            round(index * max_pos / (remaining - 1))
            for index in range(remaining)
        }
        selected_indexes.extend(sample_pool[position] for position in sorted(positions))

    deduped: list[dict[str, Any]] = []
    seen_pages: set[int] = set()
    for index in selected_indexes:
        page = page_payloads[index]
        page_no = int(page.get("page_no") or 0)
        if page_no in seen_pages:
            continue
        seen_pages.add(page_no)
        deduped.append(page)
    return deduped


def _normalize_vision_markdown_payload(
    payload: dict[str, Any] | None,
    figures: list[dict[str, Any]],
    *,
    prune_duplicate_images: bool = False,
    prune_unmapped_local_images: bool = False,
) -> dict[str, Any] | None:
    if not payload:
        return payload
    figure_map: dict[int, list[dict[str, Any]]] = {}
    for figure in figures:
        figure_map.setdefault(int(figure["page_no"]), []).append(figure)

    normalized_pages: list[dict[str, Any]] = []
    for page in payload.get("pages", []):
        page_copy = dict(page)
        page_no = int(page_copy.get("page_no") or 0)
        normalized_markdown = normalize_page_markdown(
            str(page_copy.get("markdown") or ""),
            figure_map.get(page_no, []),
        )
        if prune_duplicate_images:
            normalized_markdown = _prune_duplicate_figure_markdown_refs(
                normalized_markdown,
                figure_map.get(page_no, []),
            )
        if prune_unmapped_local_images:
            normalized_markdown = _prune_unmapped_local_figure_markdown_refs(
                normalized_markdown,
                figure_map.get(page_no, []),
            )
        normalized_markdown = _promote_plain_chart_titles_before_images(normalized_markdown)
        normalized_markdown = _repair_multi_chart_gallery_sections(
            normalized_markdown,
            figure_map.get(page_no, []),
        )
        page_copy["markdown"] = normalized_markdown
        _attach_markdown_titles_to_figures(
            figures=figure_map.get(page_no, []),
            markdown=normalized_markdown,
        )
        _attach_nearby_text_to_figures(
            figures=figure_map.get(page_no, []),
            markdown=normalized_markdown,
        )
        normalized_pages.append(page_copy)
    normalized = dict(payload)
    normalized["pages"] = normalized_pages
    return normalized


def _pages_requiring_markdown_ocr(
    *,
    page_payloads: list[dict[str, Any]],
    vision_markdown: dict[str, Any] | None,
    report_type: str | None = None,
) -> list[dict[str, Any]]:
    if not vision_markdown:
        return list(page_payloads)
    page_map = {int(page["page_no"]): page for page in page_payloads}
    targets: list[dict[str, Any]] = []
    seen: set[int] = set()
    for page in vision_markdown.get("pages", []):
        page_no = int(page.get("page_no") or 0)
        if page_no <= 0 or _is_visual_cover_page(page_no=page_no, report_type=report_type):
            continue
        if not _vision_page_markdown_is_usable(page) or _layout_page_needs_markdown_ocr(page):
            page_payload = page_map.get(page_no)
            if page_payload:
                targets.append(page_payload)
                seen.add(page_no)
    for page_no, page_payload in sorted(page_map.items()):
        if page_no <= 0 or page_no in seen or _is_visual_cover_page(page_no=page_no, report_type=report_type):
            continue
        if not any(int(page.get("page_no") or 0) == page_no for page in vision_markdown.get("pages", [])):
            targets.append(page_payload)
    return targets


def _vision_page_markdown_is_empty(page: dict[str, Any]) -> bool:
    markdown = str(page.get("markdown") or "").strip()
    if page.get("status") != "success":
        return True
    if not markdown:
        return True
    return _should_skip_vision_page_markdown(int(page.get("page_no") or 0), markdown)


def _vision_page_markdown_is_usable(page: dict[str, Any]) -> bool:
    markdown = str(page.get("markdown") or "").strip()
    if page.get("status") != "success" or not markdown:
        return False
    if _should_skip_vision_page_markdown(int(page.get("page_no") or 0), markdown):
        return False
    return True


def _layout_page_needs_markdown_ocr(page: dict[str, Any]) -> bool:
    blocks = page.get("blocks") if isinstance(page.get("blocks"), list) else []
    if not blocks:
        return False
    has_chart_like_block = False
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if _layout_block_is_low_value_technical_indicator(block):
            continue
        block_type = str(block.get("type") or "unknown").strip().lower()
        if block_type == "text":
            text = _clean_layout_block_text(str(block.get("text") or ""))
            if text and not _is_noise_line(text):
                return False
            continue
        if block_type in {"chart", "image", "table"}:
            has_chart_like_block = True
    if not has_chart_like_block:
        return False
    markdown = str(page.get("markdown") or "").strip()
    if not markdown:
        return True
    return not _has_substantive_body_lines(markdown)


def _merge_markdown_ocr_pages(
    *,
    base_payload: dict[str, Any] | None,
    fallback_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not base_payload:
        return fallback_payload
    if not fallback_payload:
        return base_payload
    fallback_pages = {
        int(page.get("page_no") or 0): page
        for page in fallback_payload.get("pages", [])
        if _vision_page_markdown_is_usable(page)
    }
    if not fallback_pages:
        return base_payload
    merged_pages: list[dict[str, Any]] = []
    seen: set[int] = set()
    for page in base_payload.get("pages", []):
        page_no = int(page.get("page_no") or 0)
        replacement = fallback_pages.get(page_no)
        if replacement and _markdown_ocr_replacement_should_win(base_page=page, fallback_page=replacement):
            merged = dict(replacement)
            merged["source"] = "markdown_ocr_fallback"
            merged_pages.append(merged)
        else:
            merged_pages.append(page)
        seen.add(page_no)
    for page_no, page in sorted(fallback_pages.items()):
        if page_no not in seen:
            merged = dict(page)
            merged["source"] = "markdown_ocr_fallback"
            merged_pages.append(merged)
    merged_payload = dict(base_payload)
    merged_payload["pages"] = sorted(merged_pages, key=lambda item: int(item.get("page_no") or 0))
    if fallback_payload.get("model"):
        merged_payload["model"] = fallback_payload.get("model")
    return merged_payload


def _markdown_ocr_replacement_should_win(
    *, base_page: dict[str, Any], fallback_page: dict[str, Any]
) -> bool:
    if not _vision_page_markdown_is_usable(base_page):
        return True
    if not _vision_page_markdown_is_usable(fallback_page):
        return False
    if _layout_page_needs_markdown_ocr(base_page) and _has_substantive_body_lines(
        str(fallback_page.get("markdown") or "")
    ):
        return True
    return False


def _prune_duplicate_figure_markdown_refs(markdown: str, figures: list[dict[str, Any]]) -> str:
    figure_paths = {str(figure.get("chart_image_path")) for figure in figures if figure.get("chart_image_path")}
    if not figure_paths:
        return markdown
    image_pattern = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
    seen_paths: set[str] = set()
    output: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        match = image_pattern.fullmatch(stripped)
        if match:
            image_path = match.group(1).strip()
            if image_path in figure_paths:
                if image_path in seen_paths:
                    continue
                seen_paths.add(image_path)
        output.append(line)
    return "\n".join(output).strip()


def _prune_unmapped_local_figure_markdown_refs(markdown: str, figures: list[dict[str, Any]]) -> str:
    figure_paths = {str(figure.get("chart_image_path")) for figure in figures if figure.get("chart_image_path")}
    image_pattern = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
    output: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        match = image_pattern.fullmatch(stripped)
        if match:
            image_path = match.group(1).strip()
            if image_path.startswith("figures/") and image_path not in figure_paths:
                continue
        output.append(line)
    return "\n".join(output).strip()


def _promote_plain_chart_titles_before_images(markdown: str) -> str:
    if not markdown.strip():
        return markdown
    image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    output: list[str] = []
    for line in markdown.splitlines():
        current_line = line
        match = image_pattern.fullmatch(line.strip())
        if match:
            title, promote_index, drop_indexes = _extract_chart_title_context(output)
            section_title = _nearest_chart_section_heading(output)
            if promote_index is not None:
                output[promote_index] = f"## {title}"
            for drop_index in drop_indexes:
                output[drop_index] = ""
            alt_text = match.group(1).strip()
            image_path = match.group(2).strip()
            if not title and section_title:
                title = section_title
            if title and _should_prefer_heading_over_image_alt(title=title, alt_text=alt_text):
                current_line = f"![{title}]({image_path})"
        output.append(current_line)
    return _collapse_blank_lines("\n".join(output))


def _repair_multi_chart_gallery_sections(markdown: str, figures: list[dict[str, Any]]) -> str:
    if not markdown.strip() or len(figures) < 2:
        return markdown
    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith("#") and _is_generic_markdown_figure_heading(stripped.lstrip("#").strip()):
            section_lines = [lines[index]]
            index += 1
            while index < len(lines):
                candidate = lines[index].strip()
                if candidate.startswith("#") and not _belongs_to_chart_gallery_section(
                    candidate.lstrip("#").strip(),
                    figures,
                ):
                    break
                section_lines.append(lines[index])
                index += 1
            output.extend(_rebuild_multi_chart_gallery_section(section_lines, figures))
            continue
        output.append(lines[index])
        index += 1
    return "\n".join(output).strip()


def _belongs_to_chart_gallery_section(title: str, figures: list[dict[str, Any]]) -> bool:
    stripped = str(title or "").strip()
    if not stripped:
        return False
    if _is_generic_markdown_figure_heading(stripped):
        return True
    if _is_plain_chart_title_candidate(stripped):
        return True
    for figure in figures:
        figure_title = str(figure.get("title") or "").strip()
        if figure_title and stripped == figure_title:
            return True
    return False


def _rebuild_multi_chart_gallery_section(section_lines: list[str], figures: list[dict[str, Any]]) -> list[str]:
    image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    figure_by_path = {
        str(figure.get("chart_image_path")): figure
        for figure in figures
        if figure.get("chart_image_path")
    }
    present_paths: list[str] = []
    generic_alt_found = False
    title_stuck_to_body_found = False
    title_candidates: list[str] = []
    body_lines: list[str] = []

    for raw_line in section_lines[1:]:
        stripped = raw_line.strip()
        if not stripped:
            continue
        image_match = image_pattern.fullmatch(stripped)
        if image_match:
            image_path = image_match.group(2).strip()
            if image_path in figure_by_path and image_path not in present_paths:
                present_paths.append(image_path)
                if _is_generic_chart_title(image_match.group(1).strip()) or image_match.group(1).strip() == "图表标题":
                    generic_alt_found = True
            continue

        matched_title, remainder = _extract_gallery_title_and_remainder(stripped, figures)
        if matched_title:
            title_candidates.append(matched_title)
            if remainder:
                title_stuck_to_body_found = True
                body_lines.append(remainder)
            continue
        body_lines.append(raw_line)

    ordered_figures = [
        figure
        for figure in figures
        if str(figure.get("chart_image_path")) in set(present_paths)
    ]
    image_order_mismatch = present_paths != [str(figure.get("chart_image_path")) for figure in ordered_figures]
    if not ordered_figures or not (generic_alt_found or image_order_mismatch or title_stuck_to_body_found):
        return section_lines

    rebuilt: list[str] = [section_lines[0], ""]
    for figure in ordered_figures:
        title = str(figure.get("title") or "").strip()
        image_path = str(figure.get("chart_image_path") or "").strip()
        if not title or _is_generic_chart_title(title):
            title = _next_unused_gallery_title(title_candidates, rebuilt)
        if title and not _is_noise_line(title):
            rebuilt.append(f"## {title}")
            rebuilt.append("")
        if image_path:
            caption = title or "图表"
            rebuilt.append(f"![{caption}]({image_path})")
            rebuilt.append("")
    if body_lines:
        if rebuilt and rebuilt[-1] != "":
            rebuilt.append("")
        rebuilt.extend(_normalize_gallery_body_lines(body_lines))
    return rebuilt


def _extract_gallery_title_and_remainder(text: str, figures: list[dict[str, Any]]) -> tuple[str, str]:
    stripped = str(text or "").strip()
    if not stripped:
        return "", ""
    for figure in figures:
        title = str(figure.get("title") or "").strip()
        if not title or _is_generic_chart_title(title):
            continue
        if stripped == title:
            return title, ""
        if stripped.startswith(title):
            remainder = stripped[len(title) :].strip()
            if remainder:
                return title, remainder
    if _is_plain_chart_title_candidate(stripped):
        return stripped, ""
    return "", ""


def _next_unused_gallery_title(candidates: list[str], rebuilt_lines: list[str]) -> str:
    used_titles = {
        line.strip().lstrip("#").strip()
        for line in rebuilt_lines
        if line.strip().startswith("#")
    }
    for candidate in candidates:
        if candidate not in used_titles:
            return candidate
    return ""


def _normalize_gallery_body_lines(lines: list[str]) -> list[str]:
    normalized: list[str] = []
    last_blank = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            if not last_blank:
                normalized.append("")
            last_blank = True
            continue
        normalized.append(stripped)
        last_blank = False
    while normalized and not normalized[-1].strip():
        normalized.pop()
    return normalized


def _last_output_content_line_index(lines: list[str]) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip():
            return index
    return None


def _is_plain_chart_title_candidate(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or stripped.startswith(("#", "![", "-", "*", ">")):
        return False
    if len(stripped) > 40:
        return False
    if stripped.endswith(("。", "，", "；", "、", ".", ",", ";")):
        return False
    title_tokens = ("机构动向", "CFTC", "ETF", "PMI", "持仓", "净多", "消费者信心", "美联储")
    return any(token in stripped for token in title_tokens)


def _extract_chart_title_context(lines: list[str]) -> tuple[str, int | None, list[int]]:
    drop_indexes: list[int] = []
    for index in range(len(lines) - 1, -1, -1):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if _looks_like_chart_date_heading(stripped.lstrip("#").strip()):
            drop_indexes.append(index)
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if _is_plain_chart_title_candidate(title):
                return title, None, sorted(drop_indexes)
            return "", None, []
        if _is_plain_chart_title_candidate(stripped):
            return stripped, index, sorted(drop_indexes)
        return "", None, []
    return "", None, []


def _nearest_chart_section_heading(lines: list[str]) -> str:
    for index in range(len(lines) - 1, -1, -1):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if stripped.startswith("!["):
            return ""
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            return title if _is_plain_section_heading_candidate(title) else ""
    return ""


def _looks_like_chart_date_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    return re.fullmatch(r"20\d{6}", stripped) is not None


def _should_prefer_heading_over_image_alt(*, title: str, alt_text: str) -> bool:
    if not title:
        return False
    if not alt_text or _is_generic_chart_title(alt_text) or _looks_like_chart_date_heading(alt_text):
        return True
    if alt_text == title:
        return False
    if alt_text in {"CFTC商品类净/空/多头仓位", "CFTC商品类净多头仓位"} and "CFTC" in title:
        return True
    anchor_tokens = ("黄金", "白银", "原油", "铜", "铂金", "钯金")
    if any(token in title for token in anchor_tokens) and not any(token in alt_text for token in anchor_tokens):
        return True
    return False


def _is_plain_section_heading_candidate(text: str) -> bool:
    stripped = str(text or "").strip()
    if _is_role_name_heading_candidate(stripped):
        return True
    if not _is_plain_chart_title_candidate(stripped):
        return False
    section_tokens = ("机构动向", "CFTC", "ETF", "PMI", "持仓", "净多", "消费者信心", "初请", "图表")
    return any(token in stripped for token in section_tokens)


def _is_role_name_heading_candidate(text: str) -> bool:
    stripped = str(text or "").strip().lstrip("#").strip()
    if not stripped or len(stripped) > 48:
        return False
    if stripped.startswith(("分析师", "策略师", "交易员")):
        return True
    return any(token in stripped for token in ("总裁", "首席商业官", "固定收益策略师"))


def _normalize_markdown_heading_line(line: str) -> str:
    stripped = str(line or "").strip()
    if not stripped.startswith("#"):
        return str(line or "")
    level = len(stripped) - len(stripped.lstrip("#"))
    title = stripped[level:].strip().lstrip("#").strip()
    if not title:
        return ""
    return f"{'#' * level} {title}"


def _collapse_blank_lines(markdown: str) -> str:
    collapsed: list[str] = []
    last_blank = False
    for raw_line in markdown.splitlines():
        if not raw_line.strip():
            if last_blank:
                continue
            collapsed.append("")
            last_blank = True
            continue
        collapsed.append(raw_line)
        last_blank = False
    return "\n".join(collapsed).strip()


def _pages_requiring_layout_fallback(
    *,
    page_payloads: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    vision_markdown: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not vision_markdown:
        return []
    page_map = {int(page["page_no"]): page for page in page_payloads}
    figure_counts: dict[int, int] = {}
    for figure in figures:
        figure_counts[int(figure["page_no"])] = figure_counts.get(int(figure["page_no"]), 0) + 1

    targets: list[dict[str, Any]] = []
    for page in vision_markdown.get("pages", []):
        if page.get("status") != "success":
            continue
        page_no = int(page.get("page_no") or 0)
        markdown = str(page.get("markdown") or "")
        heading_count = _count_chart_like_headings(markdown)
        image_count = _count_markdown_images(markdown)
        local_count = figure_counts.get(page_no, 0)
        if heading_count > local_count or image_count > local_count:
            page_payload = page_map.get(page_no)
            if page_payload:
                page_copy = dict(page_payload)
                page_copy["expected_chart_count"] = max(heading_count, image_count)
                page_copy["hint_titles"] = _extract_chart_hints(markdown)
                targets.append(page_copy)
    return targets


def _attach_nearby_text_to_figures(*, figures: list[dict[str, Any]], markdown: str) -> None:
    if not figures or not markdown.strip():
        return
    lines = [line.rstrip() for line in markdown.splitlines()]
    image_indexes = [index for index, line in enumerate(lines) if line.strip().startswith("![") and "](" in line]
    for index, figure in enumerate(figures):
        if index >= len(image_indexes):
            break
        line_index = image_indexes[index]
        nearby: list[str] = []
        for candidate in lines[line_index + 1 :]:
            stripped = candidate.strip()
            if not stripped:
                if nearby:
                    break
                continue
            if stripped.startswith("#") or stripped.startswith("!["):
                break
            if _is_noise_line(stripped):
                if nearby:
                    break
                continue
            nearby.append(stripped.lstrip("- ").strip())
            if len(" ".join(nearby)) >= 220:
                break
        if nearby:
            figure["nearby_text"] = " ".join(nearby)[:260]


def _attach_markdown_titles_to_figures(*, figures: list[dict[str, Any]], markdown: str) -> None:
    if not figures or not markdown.strip():
        return
    figure_by_path = {
        str(figure.get("chart_image_path")): figure
        for figure in figures
        if figure.get("chart_image_path")
    }
    if not figure_by_path:
        return
    image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        match = image_pattern.fullmatch(line.strip())
        if not match:
            continue
        alt_text = match.group(1).strip()
        image_path = match.group(2).strip()
        figure = figure_by_path.get(image_path)
        if figure is None:
            continue
        heading = _nearest_heading_before_image(lines=lines, image_line_index=index)
        candidate = heading or alt_text
        if not candidate:
            continue
        if _is_noise_line(candidate) or _is_low_value_technical_indicator_text(candidate):
            continue
        if _is_generic_chart_title(candidate):
            continue
        existing_title = str(figure.get("title") or "").strip()
        if (
            _is_generic_markdown_figure_heading(candidate)
            and existing_title
            and not _is_generic_chart_title(existing_title)
            and not _is_generic_markdown_figure_heading(existing_title)
        ):
            continue
        figure["title"] = candidate


def _nearest_heading_before_image(*, lines: list[str], image_line_index: int) -> str:
    for line in reversed(lines[:image_line_index]):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("!["):
            return ""
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title and not _is_noise_line(title):
                return title
            return ""
        if stripped:
            return ""
    return ""


def _is_generic_markdown_figure_heading(text: str) -> bool:
    compact = "".join(str(text or "").split())
    return compact in {"关键图表", "重点图表", "图表", "图表解读", "数据图表"}


def _count_chart_like_headings(markdown: str) -> int:
    count = 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("#").strip()
        if not title or title in {"关键图表", "技术指标"}:
            continue
        if any(keyword in title for keyword in ("PMI", "CFTC", "持仓", "机构动向", "人数", "图表", "指标", "恐惧贪婪")):
            count += 1
    return count


def _count_markdown_images(markdown: str) -> int:
    return sum(1 for line in markdown.splitlines() if line.strip().startswith("!["))


def _extract_chart_hints(markdown: str) -> list[str]:
    hints: list[str] = []
    seen: set[str] = set()
    image_pattern = re.compile(r"!\[([^\]]+)\]\(")

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title and title not in seen:
                seen.add(title)
                hints.append(title)
        for match in image_pattern.finditer(stripped):
            title = match.group(1).strip()
            if title and title not in seen:
                seen.add(title)
                hints.append(title)
    return hints


def _merge_layout_figures(*, figures: list[dict[str, Any]], layout_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not layout_payload:
        return figures
    merged = list(figures)
    figure_counts: dict[int, int] = {}
    for figure in merged:
        figure_counts[int(figure["page_no"])] = max(
            figure_counts.get(int(figure["page_no"]), 0),
            int(str(figure["figure_id"]).split("_")[-1]),
        )
    for page in layout_payload.get("pages", []):
        page_no = int(page.get("page_no") or 0)
        if _layout_page_is_low_value_technical_indicator(page):
            continue
        layout_blocks = page.get("blocks") or []
        chart_blocks = _layout_chart_blocks_with_bound_titles(layout_blocks)
        source_items = chart_blocks or page.get("charts", [])
        for chart in source_items:
            if _layout_block_is_low_value_technical_indicator(chart):
                continue
            bbox = chart.get("bbox")
            if not isinstance(bbox, list):
                continue
            if _is_page_sized_bbox(bbox=bbox, page=page):
                continue
            replacement_index: int | None = None
            skip_insert = False
            for index, existing in enumerate(merged):
                if int(existing["page_no"]) != page_no:
                    continue
                if _bbox_overlap_ratio(existing["bbox"], bbox) < 0.35:
                    continue
                if float(existing.get("confidence") or 0.0) <= 0.0:
                    replacement_index = index
                else:
                    skip_insert = True
                break
            if skip_insert:
                continue
            next_index = figure_counts.get(page_no, 0) + 1
            if replacement_index is not None:
                existing = dict(merged[replacement_index])
                merged[replacement_index] = {
                    **existing,
                    "bbox": bbox,
                    "title": str(_layout_chart_title(chart) or existing.get("title") or f"图表 {page_no}-{next_index}"),
                    "confidence": 0.62,
                }
            else:
                figure_counts[page_no] = next_index
                figure_id = f"fig_p{page_no}_{next_index:03d}"
                merged.append(
                    {
                        "figure_id": figure_id,
                        "page_no": page_no,
                        "bbox": bbox,
                        "chart_image_path": f"figures/{figure_id}.png",
                        "title": str(_layout_chart_title(chart) or f"图表 {page_no}-{next_index}"),
                        "nearby_text": "",
                        "chart_type": "unknown",
                        "confidence": 0.62,
                    }
                )
    merged.sort(key=lambda item: (int(item["page_no"]), item["bbox"][1], item["bbox"][0], item["figure_id"]))
    return merged


def _layout_chart_blocks_with_bound_titles(layout_blocks: list[Any]) -> list[dict[str, Any]]:
    chart_blocks: list[dict[str, Any]] = []
    pending_title: str | None = None
    for block in _order_layout_blocks([item for item in layout_blocks if isinstance(item, dict)]):
        block_type = str(block.get("type") or "unknown").strip().lower()
        text = _clean_layout_block_text(str(block.get("text") or block.get("title") or ""))
        if _layout_block_is_low_value_technical_indicator(block):
            pending_title = None
            continue
        if block_type == "title":
            pending_title = text if text and not _is_noise_line(text) else None
            continue
        if block_type in {"chart", "image", "table"}:
            chart = dict(block)
            chart_title = _layout_chart_title(chart)
            if (not chart_title or _is_generic_chart_title(chart_title)) and pending_title:
                chart["title"] = pending_title
                chart["text"] = pending_title
            chart_blocks.append(chart)
            pending_title = None
            continue
        if text:
            pending_title = None
    return chart_blocks


def _layout_chart_title(chart: dict[str, Any]) -> str:
    return _clean_layout_block_text(str(chart.get("title") or chart.get("text") or ""))


def _is_page_sized_bbox(*, bbox: list[int], page: dict[str, Any]) -> bool:
    image_size = page.get("image_size") if isinstance(page.get("image_size"), dict) else {}
    page_width = int(image_size.get("width") or page.get("width") or 0)
    page_height = int(image_size.get("height") or page.get("height") or 0)
    if page_width <= 0 or page_height <= 0:
        return False
    x1, y1, x2, y2 = bbox
    box_width = max(0, x2 - x1)
    box_height = max(0, y2 - y1)
    if box_width <= 0 or box_height <= 0:
        return False
    return (box_width / page_width) >= 0.92 and (box_height / page_height) >= 0.92


def _merge_missing_fallback_figures(
    *,
    figures: list[dict[str, Any]],
    page_payloads: list[dict[str, Any]],
    prepared_pages: dict[int, PreparedPage],
    vision_markdown: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not vision_markdown:
        return figures
    merged = list(figures)
    expected_counts = _expected_figure_counts_from_markdown(vision_markdown)
    existing_counts: dict[int, int] = {}
    for figure in merged:
        page_no = int(figure.get("page_no") or 0)
        existing_counts[page_no] = existing_counts.get(page_no, 0) + 1

    for page in page_payloads:
        page_no = int(page.get("page_no") or 0)
        expected_count = expected_counts.get(page_no, 0)
        if expected_count <= existing_counts.get(page_no, 0):
            continue
        prepared = prepared_pages.get(page_no)
        if prepared is None:
            continue
        fallback_figures = _detect_visual_figures(page_no=page_no, prepared=prepared)
        for fallback in fallback_figures:
            if any(
                int(existing["page_no"]) == page_no and _bbox_overlap_ratio(existing["bbox"], fallback["bbox"]) >= 0.35
                for existing in merged
            ):
                continue
            merged.append(fallback)
            existing_counts[page_no] = existing_counts.get(page_no, 0) + 1
            if existing_counts[page_no] >= expected_count:
                break

    merged.sort(key=lambda item: (int(item["page_no"]), item["bbox"][1], item["bbox"][0], item["figure_id"]))
    return merged


def _dedupe_and_prune_figures(*, figures: list[dict[str, Any]], page_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not figures:
        return []
    page_sizes = {
        int(page.get("page_no") or 0): (int(page.get("width") or 0), int(page.get("height") or 0))
        for page in page_payloads
    }
    ordered = sorted(
        figures,
        key=lambda item: (
            int(item.get("page_no") or 0),
            float(item.get("confidence") or 0.0),
            _bbox_area(item.get("bbox") or []),
        ),
        reverse=True,
    )
    kept: list[dict[str, Any]] = []
    for candidate in ordered:
        page_no = int(candidate.get("page_no") or 0)
        bbox = candidate.get("bbox")
        if not isinstance(bbox, list):
            continue
        page_width, page_height = page_sizes.get(page_no, (0, 0))
        if (
            float(candidate.get("confidence") or 0.0) <= 0.0
            and _is_near_full_page_bbox(bbox=bbox, page_width=page_width, page_height=page_height)
            and any(int(existing.get("page_no") or 0) == page_no for existing in kept)
        ):
            continue
        if any(
            int(existing.get("page_no") or 0) == page_no
            and _bbox_overlap_over_min_area(existing.get("bbox") or [], bbox) >= 0.90
            for existing in kept
        ):
            continue
        kept.append(dict(candidate))

    kept.sort(key=lambda item: (int(item["page_no"]), item["bbox"][1], item["bbox"][0], item["figure_id"]))
    used_ids: set[str] = set()
    page_counts: dict[int, int] = {}
    normalized: list[dict[str, Any]] = []
    for figure in kept:
        page_no = int(figure["page_no"])
        page_counts[page_no] = page_counts.get(page_no, 0) + 1
        figure_id = str(figure.get("figure_id") or "")
        if not figure_id or figure_id in used_ids:
            figure_id = _next_available_figure_id(page_no=page_no, used_ids=used_ids)
        used_ids.add(figure_id)
        figure["figure_id"] = figure_id
        figure["chart_image_path"] = f"figures/{figure_id}.png"
        normalized.append(figure)
    return normalized


def _fill_missing_titles_from_title_bands(
    *,
    figures: list[dict[str, Any]],
    prepared_pages: dict[int, PreparedPage],
    title_runner: VisionTitleRunner | None,
) -> list[dict[str, Any]]:
    if not figures:
        return []
    by_page: dict[int, list[dict[str, Any]]] = {}
    for figure in figures:
        by_page.setdefault(int(figure.get("page_no") or 0), []).append(dict(figure))

    updated: list[dict[str, Any]] = []
    for page_no, page_figures in by_page.items():
        prepared = prepared_pages.get(page_no)
        if prepared is None:
            updated.extend(page_figures)
            continue
        ordered = sorted(page_figures, key=lambda item: ((item.get("bbox") or [0, 0, 0, 0])[1], item.get("figure_id") or ""))
        title_band_requests: list[dict[str, Any]] = []
        for index, figure in enumerate(ordered):
            if not _figure_title_needs_ocr(str(figure.get("title") or "")):
                continue
            band = _extract_title_band(
                image=prepared.original,
                bbox=figure.get("bbox") or [],
                previous_bbox=(ordered[index - 1].get("bbox") or []) if index > 0 else None,
            )
            if band is None:
                continue
            title_band_requests.append(
                {
                    "figure_id": str(figure.get("figure_id") or ""),
                    "image": band,
                }
            )
        title_lookup: dict[str, str] = {}
        if title_band_requests:
            runner = title_runner or recognize_figure_title_bands
            for item in runner(title_band_requests):
                figure_id = str(item.get("figure_id") or "")
                title = _normalize_candidate_title(str(item.get("title") or ""))
                if figure_id and title:
                    title_lookup[figure_id] = title
        for figure in ordered:
            patched = dict(figure)
            resolved = title_lookup.get(str(figure.get("figure_id") or ""))
            if resolved:
                patched["title"] = resolved
            updated.append(patched)
    updated.sort(key=lambda item: (int(item["page_no"]), item["bbox"][1], item["bbox"][0], item["figure_id"]))
    return updated


def _snap_figures_to_white_chart_panels(
    *,
    figures: list[dict[str, Any]],
    prepared_pages: dict[int, PreparedPage],
) -> list[dict[str, Any]]:
    if not figures:
        return []
    by_page: dict[int, list[dict[str, Any]]] = {}
    for figure in figures:
        by_page.setdefault(int(figure.get("page_no") or 0), []).append(dict(figure))

    snapped: list[dict[str, Any]] = []
    for page_no, page_figures in by_page.items():
        prepared = prepared_pages.get(page_no)
        panels = _detect_white_chart_panels(prepared.original) if prepared is not None else []
        if not panels or len(panels) != len(page_figures):
            snapped.extend(page_figures)
            continue
        ordered_figures = sorted(page_figures, key=lambda item: ((item.get("bbox") or [0, 0, 0, 0])[1], item.get("figure_id") or ""))
        for index, (figure, panel_bbox) in enumerate(zip(ordered_figures, panels)):
            current_bbox = figure.get("bbox") or []
            if _should_snap_to_white_panel(current_bbox, panel_bbox):
                figure["bbox"] = panel_bbox
                figure["confidence"] = max(float(figure.get("confidence") or 0.0), 0.7)
            snapped.append(figure)
    snapped.sort(key=lambda item: (int(item["page_no"]), item["bbox"][1], item["bbox"][0], item["figure_id"]))
    return snapped


def _expand_panel_bbox_with_heading(
    *,
    panel_bbox: list[int],
    previous_panel_bbox: list[int] | None,
    page_height: int,
) -> list[int]:
    left, top, right, bottom = panel_bbox
    heading_padding = max(140, int(page_height * 0.065))
    inter_panel_margin = max(20, int(page_height * 0.015))
    min_top = (previous_panel_bbox[3] + inter_panel_margin) if previous_panel_bbox else 0
    expanded_top = max(min_top, top - heading_padding)
    return [left, expanded_top, right, bottom]


def _figure_title_needs_ocr(title: str) -> bool:
    return bool(re.fullmatch(r"图表\s+\d+-\d+", title.strip()))


def _extract_title_band(
    *,
    image: np.ndarray,
    bbox: list[Any],
    previous_bbox: list[Any] | None,
) -> np.ndarray | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        left, top, right, _ = [int(float(value)) for value in bbox]
    except (TypeError, ValueError):
        return None
    height, width = image.shape[:2]
    band_top = max(0, top - max(220, int(height * 0.08)))
    if previous_bbox and len(previous_bbox) == 4:
        try:
            previous_bottom = int(float(previous_bbox[3]))
        except (TypeError, ValueError):
            previous_bottom = 0
        band_top = max(band_top, previous_bottom + max(12, int(height * 0.01)))
    band_bottom = max(0, top - max(12, int(height * 0.005)))
    if band_bottom <= band_top:
        return None
    crop_left = max(0, min(left, width))
    crop_right = max(crop_left + 1, min(right, width))
    band = image[band_top:band_bottom, crop_left:crop_right]
    if band.size == 0:
        return None
    return band


def _normalize_candidate_title(title: str) -> str:
    stripped = " ".join(title.split()).strip()
    if not stripped or _figure_title_needs_ocr(stripped):
        return ""
    if _is_noise_line(stripped):
        return ""
    return stripped


def _detect_white_chart_panels(image: np.ndarray) -> list[list[int]]:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 210, 255, cv2.THRESH_BINARY)
    mask[: int(height * 0.10), :] = 0
    mask[int(height * 0.94) :, :] = 0
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    panels: list[list[int]] = []
    for label in range(1, num_labels):
        x, y, w, h, area = [int(value) for value in stats[label]]
        if w < width * 0.45 or h < height * 0.04:
            continue
        if area < w * h * 0.55:
            continue
        panels.append([x, y, x + w, y + h])
    panels = _drop_nested_white_panels(panels)
    panels.sort(key=lambda bbox: (bbox[1], bbox[0]))
    return panels


def _drop_nested_white_panels(panels: list[list[int]]) -> list[list[int]]:
    if len(panels) < 2:
        return panels
    kept: list[list[int]] = []
    for panel in sorted(panels, key=_bbox_area, reverse=True):
        if any(_bbox_overlap_over_min_area(existing, panel) >= 0.95 for existing in kept):
            continue
        kept.append(panel)
    return kept


def _should_snap_to_white_panel(current_bbox: list[Any], panel_bbox: list[int]) -> bool:
    if not isinstance(current_bbox, list) or len(current_bbox) != 4:
        return True
    try:
        current = [int(float(value)) for value in current_bbox]
    except (TypeError, ValueError):
        return True
    current_area = _bbox_area(current)
    panel_area = _bbox_area(panel_bbox)
    if current_area <= 0 or panel_area <= 0:
        return True
    overlap = _bbox_overlap_over_min_area(current, panel_bbox)
    if overlap >= 0.35 and panel_area > current_area * 1.35:
        return True
    current_width = max(0, current[2] - current[0])
    panel_width = max(0, panel_bbox[2] - panel_bbox[0])
    if panel_width > current_width * 1.5:
        return True
    current_height = max(0, current[3] - current[1])
    panel_height = max(0, panel_bbox[3] - panel_bbox[1])
    horizontal_overlap = max(0, min(current[2], panel_bbox[2]) - max(current[0], panel_bbox[0]))
    vertical_overlap = max(0, min(current[3], panel_bbox[3]) - max(current[1], panel_bbox[1]))
    horizontal_overlap_ratio = horizontal_overlap / max(1, min(current_width, panel_width))
    vertical_overlap_ratio = vertical_overlap / max(1, min(current_height, panel_height))
    panel_extends_below = panel_bbox[3] > current[3] + max(24, int(panel_height * 0.12))
    current_starts_above_panel = current[1] < panel_bbox[1] - max(24, int(panel_height * 0.08))
    return (
        horizontal_overlap_ratio >= 0.75
        and vertical_overlap_ratio >= 0.20
        and (panel_extends_below or current_starts_above_panel)
    )


def _next_available_figure_id(*, page_no: int, used_ids: set[str]) -> str:
    index = 1
    while True:
        figure_id = f"fig_p{page_no}_{index:03d}"
        if figure_id not in used_ids:
            return figure_id
        index += 1


def _is_near_full_page_bbox(*, bbox: list[int], page_width: int, page_height: int) -> bool:
    if page_width <= 0 or page_height <= 0:
        return False
    if len(bbox) != 4:
        return False
    x1, y1, x2, y2 = bbox
    box_width = max(0, x2 - x1)
    box_height = max(0, y2 - y1)
    return (box_width / page_width) >= 0.90 and (box_height / page_height) >= 0.90


def _bbox_area(bbox: list[int]) -> int:
    if len(bbox) != 4:
        return 0
    x1, y1, x2, y2 = bbox
    return max(0, x2 - x1) * max(0, y2 - y1)


def _bbox_overlap_over_min_area(source_bbox: list[int], target_bbox: list[int]) -> float:
    if len(source_bbox) != 4 or len(target_bbox) != 4:
        return 0.0
    sx1, sy1, sx2, sy2 = source_bbox
    tx1, ty1, tx2, ty2 = target_bbox
    ix1, iy1 = max(sx1, tx1), max(sy1, ty1)
    ix2, iy2 = min(sx2, tx2), min(sy2, ty2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    min_area = max(1, min(_bbox_area(source_bbox), _bbox_area(target_bbox)))
    return ((ix2 - ix1) * (iy2 - iy1)) / min_area


def _expected_figure_counts_from_markdown(vision_markdown: dict[str, Any]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for page in vision_markdown.get("pages", []):
        page_no = int(page.get("page_no") or 0)
        if page_no <= 0:
            continue
        markdown = str(page.get("markdown") or "")
        image_count = _count_markdown_images(markdown)
        heading_count = _count_chart_like_headings(markdown)
        if image_count:
            counts[page_no] = image_count
        elif heading_count:
            counts[page_no] = heading_count
    return counts


def _rebuild_sections_with_figures(
    *,
    article_id: str,
    figures: list[dict[str, Any]],
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    paragraph_sections = [section for section in sections if section.get("section_type") == "paragraph_section"]
    if not figures:
        return paragraph_sections
    figure_map = {item["figure_id"]: item for item in figures}
    _, chart_sections = _build_chart_sections(article_id=article_id, figures=figures, start_index=0)
    for section in chart_sections:
        section["figures"] = [figure_map[figure_id] for figure_id in section["figure_ids"] if figure_id in figure_map]
    rebuilt = paragraph_sections + chart_sections
    rebuilt.sort(key=lambda item: (item.get("page_no") or 0, item["bbox"][1], item["section_id"]))
    return rebuilt


def _is_cover_page_markdown(page_no: int, markdown: str) -> bool:
    if page_no != 1:
        return False
    text = markdown.strip()
    return "目录" in text or "VIP专属报告系列" in text


def _should_skip_vision_page_markdown(page_no: int, markdown: str) -> bool:
    text = markdown.strip()
    if not text:
        return True
    if _markdown_has_low_value_technical_indicator(text) and not _has_substantive_body_lines(markdown):
        return True
    return False


def _markdown_has_low_value_technical_indicator(markdown: str) -> bool:
    return any(
        _is_low_value_technical_indicator_text(line.strip().lstrip("#").strip())
        for line in str(markdown or "").splitlines()
    )


def _vision_status(payload: dict[str, Any]) -> str:
    pages = payload.get("pages") or []
    if not pages:
        return "empty"
    if all(page.get("status") == "success" for page in pages):
        return "success"
    if any(page.get("status") == "success" for page in pages):
        return "partial"
    return "failed"


def _has_substantive_vision_markdown(markdown: str, *, title: str) -> bool:
    text = str(markdown or "").strip()
    if not text:
        return False
    return _has_meaningful_markdown_content(text)


def _has_meaningful_markdown_content(markdown: str) -> bool:
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- 发布时间:"):
            continue
        if stripped.startswith("# "):
            continue
        if _is_noise_line(stripped):
            continue
        return True
    return False


def _has_substantive_body_lines(markdown: str) -> bool:
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "![", "- 发布时间:")):
            continue
        if _is_low_value_technical_indicator_text(stripped):
            continue
        if _is_noise_line(stripped):
            continue
        if len(stripped) >= 12:
            return True
    return False


def _is_noise_line(text: str) -> bool:
    normalized = str(text).strip()
    if normalized.startswith("#"):
        normalized = normalized.lstrip("#").strip()
    compact = "".join(normalized.split()).lower()
    if not compact:
        return False
    if "请提供第" in compact and "页的图片" in compact and "进行转录" in compact:
        return True
    if "@" in compact and "jin10.com" in compact:
        return True
    noise_tokens = (
        "联系方式",
        "vipteam",
        "content",
        "目录",
        "vip专属报告系列",
        "金十vip专享",
        "欢迎点击查看",
        "更多金银信号和消息汇总",
        "来看今天最新的金银报告",
        "金十数据research",
        "每日金银报告",
        "即时市场展望",
        "即时市场洞察",
        "每日市场观察",
        "本材料中的信息来自其撰写者的观点",
        "本文中的意见仅代表",
    )
    return any(token in compact for token in noise_tokens)


def _looks_like_directory_item(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if len(stripped) > 24:
        return False
    if re.fullmatch(r"\d{2}\s+\S.*", stripped) is None:
        return False
    directory_tokens = (
        "隔夜要闻",
        "市场聚焦",
        "市场分析",
        "关键图表",
        "机构动向",
        "技术指标",
        "行情回顾",
        "观点分享",
    )
    return any(token in stripped for token in directory_tokens)


def _looks_like_report_shell_date_line(text: str) -> bool:
    stripped = str(text or "").strip()
    return re.fullmatch(r"\d{4}年\d{2}月\d{2}日", stripped) is not None


def _normalize_report_title(title: str) -> str:
    normalized = str(title or "").strip()
    normalized = re.sub(r"\s*[-－—–]\s*金十数据VIP\s*$", "", normalized)
    return normalized.strip()


def _compact_report_shell_text(text: str) -> str:
    return "".join(str(text or "").split()).replace("-金十数据VIP", "").lower()


def _compact_report_shell_date(published_at: str | None) -> str:
    value = str(published_at or "").strip()
    if not value:
        return ""
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return ""
    return f"{match.group(1)}年{match.group(2)}月{match.group(3)}日"


def _prepare_page(image_path: Path) -> PreparedPage | None:
    source = cv2.imread(str(image_path))
    if source is None:
        return None
    cropped = _crop_page_borders(source)
    enlarged = cv2.resize(cropped, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    contrast = cv2.convertScaleAbs(gray, alpha=1.25, beta=12)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(contrast)
    enhanced = cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR)
    height, width = source.shape[:2]
    return PreparedPage(
        original=source,
        enhanced=enhanced,
        width=width,
        height=height,
    )


def _crop_page_borders(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = gray > 8
    if not mask.any():
        return image
    ys, xs = np.where(mask)
    top, bottom = ys.min(), ys.max()
    left, right = xs.min(), xs.max()
    return image[top : bottom + 1, left : right + 1]


def _is_visual_cover_page(*, page_no: int, report_type: str | None = None) -> bool:
    if str(report_type or "").strip().lower() in {"positioning", "technical_levels", "oil", "fx"}:
        return False
    return page_no == 1


def _detect_visual_figures(*, page_no: int, prepared: PreparedPage) -> list[dict[str, Any]]:
    image = prepared.original
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Light-background charts and beige gauge arcs are both much brighter than
    # the dark report background. Dilating merges chart strokes into one region.
    bright_mask = cv2.inRange(gray, 115, 255)
    bright_mask[: int(height * 0.10), :] = 0
    bright_mask[int(height * 0.93) :, :] = 0
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (45, 35))
    merged = cv2.dilate(bright_mask, kernel, iterations=2)
    contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[list[int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < width * 0.28 or h < 180:
            continue
        if w * h < width * height * 0.025:
            continue
        if y < height * 0.08 or y + h > height * 0.96:
            continue
        pad_x = int(width * 0.03)
        pad_y = 30
        candidates.append(
            [
                max(0, x - pad_x),
                max(0, y - pad_y),
                min(width, x + w + pad_x),
                min(height, y + h + pad_y),
            ]
        )

    figures: list[dict[str, Any]] = []
    for index, bbox in enumerate(_merge_overlapping_bboxes(candidates), start=1):
        figure_id = f"fig_p{page_no}_{index:03d}"
        figures.append(
            {
                "figure_id": figure_id,
                "page_no": page_no,
                "bbox": bbox,
                "chart_image_path": f"figures/{figure_id}.png",
                "title": f"图表 {page_no}-{index}",
                "nearby_text": "",
                "chart_type": "unknown",
                "confidence": 0.65,
            }
        )
    return figures


def _merge_overlapping_bboxes(bboxes: list[list[int]]) -> list[list[int]]:
    ordered = sorted(bboxes, key=lambda bbox: (bbox[1], bbox[0]))
    merged: list[list[int]] = []
    for bbox in ordered:
        if not merged:
            merged.append(bbox)
            continue
        previous = merged[-1]
        if _bbox_overlap_ratio(bbox, previous) > 0.10 or bbox[1] <= previous[3] + 80:
            merged[-1] = _union_bbox([previous, bbox])
            continue
        merged.append(bbox)
    return merged


def _bbox_overlap_ratio(source_bbox: list[int], target_bbox: list[int]) -> float:
    sx1, sy1, sx2, sy2 = source_bbox
    tx1, ty1, tx2, ty2 = target_bbox
    ix1, iy1 = max(sx1, tx1), max(sy1, ty1)
    ix2, iy2 = min(sx2, tx2), min(sy2, ty2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    source_area = max(1, (sx2 - sx1) * (sy2 - sy1))
    return ((ix2 - ix1) * (iy2 - iy1)) / source_area


def _union_bbox(bboxes: list[list[int]]) -> list[int]:
    return [
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    ]


def _build_chart_sections(
    *,
    article_id: str,
    figures: list[dict[str, Any]],
    start_index: int,
) -> tuple[int, list[dict[str, Any]]]:
    sections: list[dict[str, Any]] = []
    index = start_index
    for figure in figures:
        index += 1
        sections.append(
            {
                "section_id": f"sec_{index:03d}",
                "section_type": "chart_section",
                "title": figure.get("title") or "",
                "page_no": figure["page_no"],
                "bbox": figure["bbox"],
                "text": "",
                "figure_ids": [figure["figure_id"]],
                "confidence": figure["confidence"],
            }
        )
    return index, sections


def _crop_bbox(image: np.ndarray, bbox: list[int]) -> np.ndarray:
    left, top, right, bottom = bbox
    return image[max(0, top) : max(top + 1, bottom), max(0, left) : max(left + 1, right)]


def _debug_image_refs(page_no: int) -> dict[str, str]:
    return {
        "original": f"debug/page_{page_no:03d}_original.png",
        "enhanced": f"debug/page_{page_no:03d}_enhanced.png",
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_remote_image_path(path: str) -> bool:
    parsed = urlparse(path)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _vision_page_limit() -> int:
    raw = str(__import__("os").environ.get("JIN10_VISION_PAGE_LIMIT", DEFAULT_VISION_PAGE_LIMIT)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_VISION_PAGE_LIMIT


def _vision_page_selection_mode() -> str:
    raw = str(__import__("os").environ.get("JIN10_VISION_PAGE_SELECTION", "head_tail")).strip().lower()
    if raw in {"head", "head_tail"}:
        return raw
    return "head_tail"


def _write_debug_images_enabled() -> bool:
    raw = os.environ.get("JIN10_WRITE_DEBUG_IMAGES", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
