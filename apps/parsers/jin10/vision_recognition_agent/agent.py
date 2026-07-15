from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
from dotenv import load_dotenv

from apps.data_layer.jin10_image_assets import (
    DEFAULT_JIN10_IMAGE_JPEG_QUALITY,
    DEFAULT_JIN10_IMAGE_MAX_LONG_EDGE,
)
from apps.llm.gateway import chat_sync


DEFAULT_VISION_PROVIDER = "cockpit"
DEFAULT_MIMO_VL_MODEL = "mimo-v2.5"
DEFAULT_VISION_MODEL = "gpt-5.6-luna"
DEFAULT_VISION_REASONING_EFFORT = "high"
DEFAULT_VISION_TIMEOUT = 120.0
DEFAULT_VISION_MAX_RETRIES = 0
DEFAULT_VISION_MAX_LONG_EDGE = DEFAULT_JIN10_IMAGE_MAX_LONG_EDGE
DEFAULT_VISION_JPEG_QUALITY = DEFAULT_JIN10_IMAGE_JPEG_QUALITY
MAX_IMAGE_DATA_URL_CHARS = 9_500_000
SUPPORTED_RAW_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _non_negative_int(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _bounded_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


@dataclass(slots=True)
class EncodedImage:
    data_url: str
    width: int
    height: int


class VisionMarkdownClient:
    """Vision client for formal Jin10 page recognition."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        reasoning_effort: str | None = None,
        max_image_long_edge: int | None = None,
        image_jpeg_quality: int | None = None,
    ) -> None:
        load_dotenv()
        self._explicit_runtime_config = any(
            value is not None
            for value in (
                provider,
                model,
                timeout,
                max_retries,
                reasoning_effort,
                max_image_long_edge,
                image_jpeg_quality,
            )
        )
        self.provider = self._resolve_provider(provider)
        self.model = self._resolve_model(model)
        self.timeout = _positive_float(
            timeout if timeout is not None else os.getenv("JIN10_VISION_TIMEOUT"),
            DEFAULT_VISION_TIMEOUT,
        )
        self.request_timeout = self.timeout
        self.max_retries = _non_negative_int(
            max_retries if max_retries is not None else os.getenv("JIN10_VISION_MAX_RETRIES"),
            DEFAULT_VISION_MAX_RETRIES,
        )
        self.reasoning_effort = (
            reasoning_effort
            if reasoning_effort is not None
            else os.getenv("JIN10_VISION_REASONING_EFFORT", DEFAULT_VISION_REASONING_EFFORT).strip()
        ) or DEFAULT_VISION_REASONING_EFFORT
        self.max_image_long_edge = _positive_int(
            max_image_long_edge if max_image_long_edge is not None else os.getenv("JIN10_VISION_MAX_LONG_EDGE"),
            DEFAULT_VISION_MAX_LONG_EDGE,
        )
        self.image_jpeg_quality = _bounded_int(
            image_jpeg_quality if image_jpeg_quality is not None else os.getenv("JIN10_VISION_JPEG_QUALITY"),
            DEFAULT_VISION_JPEG_QUALITY,
            minimum=1,
            maximum=100,
        )

    def recognize_page_markdown(
        self,
        *,
        image_path: Path,
        page_no: int,
        figures: list[dict[str, Any]],
        report_type: str | None = None,
    ) -> dict[str, Any]:
        if not image_path.is_file():
            return {
                "page_no": page_no,
                "status": "unavailable",
                "reason": "image_not_found",
                "markdown": "",
                "model": self.model,
            }

        try:
            encoded_image = _image_to_data_url(
                image_path,
                max_long_edge=self.max_image_long_edge,
                jpeg_quality=self.image_jpeg_quality,
            )
        except ValueError as exc:
            return {
                "page_no": page_no,
                "status": "unavailable",
                "reason": str(exc),
                "markdown": "",
                "model": self.model,
            }

        content = self._chat_with_image(
            image_data_url=encoded_image.data_url,
            text_prompt=_build_page_markdown_prompt(
                page_no=page_no,
                figures=figures,
                prompt_profile=_prompt_profile_for_report_type(report_type),
            ),
        )
        normalized = normalize_page_markdown(_strip_markdown_fences(content), figures)
        return {
            "page_no": page_no,
            "status": "success" if normalized.strip() else "empty",
            "markdown": normalized,
            "model": self.model,
        }

    def recognize_page_layout(
        self,
        *,
        image_path: Path,
        page_no: int,
        page_width: int,
        page_height: int,
        expected_chart_count: int = 0,
        hint_titles: list[str] | None = None,
    ) -> dict[str, Any]:
        if not image_path.is_file():
            return {
                "page_no": page_no,
                "status": "unavailable",
                "reason": "image_not_found",
                "image_size": {"width": page_width, "height": page_height},
                "blocks": [],
                "charts": [],
                "model": self.model,
            }

        try:
            encoded_image = _image_to_data_url(
                image_path,
                max_long_edge=self.max_image_long_edge,
                jpeg_quality=self.image_jpeg_quality,
            )
        except ValueError as exc:
            return {
                "page_no": page_no,
                "status": "unavailable",
                "reason": str(exc),
                "image_size": {"width": page_width, "height": page_height},
                "blocks": [],
                "charts": [],
                "model": self.model,
            }

        content = self._chat_with_image(
            image_data_url=encoded_image.data_url,
            text_prompt=_build_page_layout_prompt(
                page_no=page_no,
                page_width=encoded_image.width,
                page_height=encoded_image.height,
                original_page_width=page_width,
                original_page_height=page_height,
                expected_chart_count=expected_chart_count,
                hint_titles=hint_titles or [],
            ),
        )
        payload = _parse_layout_json(content)
        blocks = _normalize_layout_blocks(
            payload,
            page_width=page_width,
            page_height=page_height,
            fallback_coordinate_size=(encoded_image.width, encoded_image.height),
        )
        charts = [block for block in blocks if block.get("type") == "chart"]
        normalized_charts = []
        for index, chart in enumerate(charts or [], start=1):
            bbox = chart.get("bbox")
            if not isinstance(bbox, list):
                continue
            normalized_charts.append(
                {
                    "chart_id": chart.get("chart_id") or f"vlm_p{page_no}_{index:03d}",
                    "title": str(chart.get("title") or chart.get("text") or "").strip(),
                    "bbox": bbox,
                }
            )
        return {
            "page_no": page_no,
            "status": "success" if blocks else "empty",
            "image_size": payload.get("image_size") if isinstance(payload, dict) else {"width": encoded_image.width, "height": encoded_image.height},
            "source_image_size": {"width": page_width, "height": page_height},
            "blocks": blocks,
            "charts": normalized_charts,
            "model": self.model,
        }

    def recognize_page_unified(
        self,
        *,
        image_path: Path,
        page_no: int,
        page_width: int,
        page_height: int,
        report_type: str | None = None,
        preserve_cover_identity: bool = False,
    ) -> dict[str, Any]:
        if not image_path.is_file():
            return {
                "page_no": page_no,
                "status": "unavailable",
                "reason": "image_not_found",
                "image_size": {"width": page_width, "height": page_height},
                "markdown": "",
                "blocks": [],
                "charts": [],
                "model": self.model,
            }

        try:
            encoded_image = _image_to_data_url(
                image_path,
                max_long_edge=self.max_image_long_edge,
                jpeg_quality=self.image_jpeg_quality,
            )
        except ValueError as exc:
            return {
                "page_no": page_no,
                "status": "unavailable",
                "reason": str(exc),
                "image_size": {"width": page_width, "height": page_height},
                "markdown": "",
                "blocks": [],
                "charts": [],
                "model": self.model,
            }

        content = self._chat_with_image(
            image_data_url=encoded_image.data_url,
            text_prompt=_build_page_unified_prompt(
                page_no=page_no,
                page_width=encoded_image.width,
                page_height=encoded_image.height,
                original_page_width=page_width,
                original_page_height=page_height,
                prompt_profile=_prompt_profile_for_report_type(report_type),
                preserve_cover_identity=preserve_cover_identity,
            ),
        )
        payload = _parse_layout_json(content)
        blocks = _normalize_layout_blocks(
            payload,
            page_width=page_width,
            page_height=page_height,
            fallback_coordinate_size=(encoded_image.width, encoded_image.height),
        )
        markdown = str(payload.get("markdown") or "").strip() if isinstance(payload, dict) else ""
        charts = [block for block in blocks if block.get("type") == "chart"]
        normalized_charts = []
        for index, chart in enumerate(charts or [], start=1):
            bbox = chart.get("bbox")
            if not isinstance(bbox, list):
                continue
            normalized_charts.append(
                {
                    "chart_id": chart.get("chart_id") or f"vlm_p{page_no}_{index:03d}",
                    "title": str(chart.get("title") or chart.get("text") or "").strip(),
                    "bbox": bbox,
                }
            )
        return {
            "page_no": page_no,
            "status": "success" if markdown.strip() or blocks else "empty",
            "image_size": payload.get("image_size") if isinstance(payload, dict) else {"width": encoded_image.width, "height": encoded_image.height},
            "source_image_size": {"width": page_width, "height": page_height},
            "markdown": markdown,
            "blocks": blocks,
            "charts": normalized_charts,
            "model": self.model,
        }

    def recognize_title_band(
        self,
        *,
        image: Any,
    ) -> str:
        encoded_image = _image_array_to_data_url(image)
        content = self._chat_with_image(
            image_data_url=encoded_image.data_url,
            text_prompt=_build_title_band_prompt(
                page_width=encoded_image.width,
                page_height=encoded_image.height,
            ),
        )
        return _normalize_title_band_text(content)

    def _resolve_provider(self, provider: str | None) -> str:
        value = (provider or os.getenv("JIN10_VISION_PROVIDER") or DEFAULT_VISION_PROVIDER).strip().lower()
        if value in {"cockpit", "codex", "openai-cockpit"}:
            return "cockpit"
        if value in {"mimo", "mi-mo", "mimo2.5", "mimo-2.5"}:
            return "mimo"
        return DEFAULT_VISION_PROVIDER

    def _resolve_model(self, model: str | None) -> str:
        if model:
            return model.strip()
        configured = os.getenv("JIN10_VISION_MODEL", "").strip()
        if configured:
            return configured
        modern = os.getenv("JIN10_MIMO_VL_MODEL", "").strip()
        if modern:
            return modern
        return DEFAULT_VISION_MODEL

    def _chat_with_image(self, *, image_data_url: str, text_prompt: str) -> str:
        if (
            "PYTEST_CURRENT_TEST" in os.environ
            and os.getenv("FINANCE_AGENT_FORCE_LIVE_LLM", "").strip().lower() not in {"1", "true", "yes"}
            and not self._explicit_runtime_config
        ):
            raise RuntimeError("live vision disabled in pytest without explicit client config")
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url, "detail": "original"},
                    },
                    {"type": "text", "text": text_prompt},
                ],
            }
        ]
        kwargs: dict[str, Any] = {
            "messages": messages,
            "model": self.model,
            "temperature": 0,
            "max_tokens": 4096,
            "provider": self.provider,
        }
        if self.max_retries is not None:
            kwargs["max_retries"] = self.max_retries
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if self.request_timeout is not None:
            kwargs["request_timeout"] = self.request_timeout
        kwargs["audit_context"] = {
            "caller": "jin10_vision.VisionMarkdownClient._chat_with_image",
            "input_payload": {
                "text_prompt": text_prompt,
                "image_data_url": image_data_url,
                "provider": self.provider,
                "model": self.model,
            },
        }
        response = chat_sync(**kwargs)
        return response.content


def recognize_pages_as_markdown(
    pages: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    *,
    client: VisionMarkdownClient | None = None,
    report_type: str | None = None,
) -> dict[str, Any]:
    recognizer = client or VisionMarkdownClient()
    prompt_profile = _prompt_profile_for_report_type(report_type)
    figure_map: dict[int, list[dict[str, Any]]] = {}
    for figure in figures:
        figure_map.setdefault(int(figure["page_no"]), []).append(figure)

    page_results: list[dict[str, Any]] = []
    for page in pages:
        page_no = int(page["page_no"])
        image_path = Path(str(page["image_path"]))
        page_figures = figure_map.get(page_no, [])
        payload_hint = {
            "prompt_version": "markdown-v3-resized-shell-aware",
            "prompt_profile": prompt_profile,
            "report_type": _normalize_report_type(report_type),
            "figures": page_figures,
            "input_max_long_edge": int(
                getattr(recognizer, "max_image_long_edge", DEFAULT_VISION_MAX_LONG_EDGE)
            ),
            "input_jpeg_quality": int(
                getattr(recognizer, "image_jpeg_quality", DEFAULT_VISION_JPEG_QUALITY)
            ),
        }
        cached = _read_page_cache(
            kind="markdown",
            model=recognizer.model,
            image_path=image_path,
            page_no=page_no,
            payload_hint=payload_hint,
        )
        if cached is not None:
            print(f"[jin10-vlm] markdown page {page_no}: cache hit", file=sys.stderr, flush=True)
            page_results.append(cached)
            continue
        print(f"[jin10-vlm] markdown page {page_no}: start", file=sys.stderr, flush=True)
        result = recognizer.recognize_page_markdown(
            image_path=image_path,
            page_no=page_no,
            figures=page_figures,
            report_type=report_type,
        )
        print(
            f"[jin10-vlm] markdown page {page_no}: {result.get('status') or 'done'}",
            file=sys.stderr,
            flush=True,
        )
        _write_page_cache(
            kind="markdown",
            model=recognizer.model,
            image_path=image_path,
            page_no=page_no,
            payload_hint=payload_hint,
            result=result,
        )
        page_results.append(result)
    return {
        "provider": recognizer.provider,
        "model": recognizer.model,
        "pages": page_results,
    }


def recognize_pages_unified(
    pages: list[dict[str, Any]],
    *,
    client: VisionMarkdownClient | None = None,
    report_type: str | None = None,
    preserve_cover_identity: bool = False,
) -> dict[str, Any]:
    recognizer = client or VisionMarkdownClient()
    prompt_profile = _prompt_profile_for_report_type(report_type)
    page_results: list[dict[str, Any]] = []
    for page in pages:
        page_no = int(page["page_no"])
        image_path = Path(str(page["image_path"]))
        payload_hint = {
            "prompt_version": "unified-v6-resized-recognition-crop-only",
            "prompt_profile": prompt_profile,
            "report_type": _normalize_report_type(report_type),
            "page_width": int(page.get("width") or 0),
            "page_height": int(page.get("height") or 0),
            "input_max_long_edge": int(
                getattr(recognizer, "max_image_long_edge", DEFAULT_VISION_MAX_LONG_EDGE)
            ),
            "input_jpeg_quality": int(
                getattr(recognizer, "image_jpeg_quality", DEFAULT_VISION_JPEG_QUALITY)
            ),
        }
        if preserve_cover_identity:
            payload_hint["preserve_cover_identity"] = True
        cached = _read_page_cache(
            kind="unified",
            model=recognizer.model,
            image_path=image_path,
            page_no=page_no,
            payload_hint=payload_hint,
        )
        if cached is not None:
            print(f"[jin10-vlm] unified page {page_no}: cache hit", file=sys.stderr, flush=True)
            page_results.append(cached)
            continue
        print(f"[jin10-vlm] unified page {page_no}: start", file=sys.stderr, flush=True)
        recognition_kwargs: dict[str, Any] = {
            "image_path": image_path,
            "page_no": page_no,
            "page_width": payload_hint["page_width"],
            "page_height": payload_hint["page_height"],
            "report_type": report_type,
        }
        if preserve_cover_identity:
            recognition_kwargs["preserve_cover_identity"] = True
        result = recognizer.recognize_page_unified(**recognition_kwargs)
        print(
            f"[jin10-vlm] unified page {page_no}: {result.get('status') or 'done'}",
            file=sys.stderr,
            flush=True,
        )
        _write_page_cache(
            kind="unified",
            model=recognizer.model,
            image_path=image_path,
            page_no=page_no,
            payload_hint=payload_hint,
            result=result,
        )
        page_results.append(result)
    return {
        "provider": recognizer.provider,
        "model": recognizer.model,
        "pages": page_results,
    }


def recognize_pages_layout(
    pages: list[dict[str, Any]],
    *,
    client: VisionMarkdownClient | None = None,
) -> dict[str, Any]:
    recognizer = client or VisionMarkdownClient()
    page_results: list[dict[str, Any]] = []
    for page in pages:
        page_no = int(page["page_no"])
        image_path = Path(str(page["image_path"]))
        payload_hint = {
            "prompt_version": "layout-v6-resized-image-or-normalized-coordinate-space",
            "page_width": int(page.get("width") or 0),
            "page_height": int(page.get("height") or 0),
            "expected_chart_count": int(page.get("expected_chart_count") or 0),
            "hint_titles": [str(item) for item in (page.get("hint_titles") or [])],
            "input_max_long_edge": int(
                getattr(recognizer, "max_image_long_edge", DEFAULT_VISION_MAX_LONG_EDGE)
            ),
            "input_jpeg_quality": int(
                getattr(recognizer, "image_jpeg_quality", DEFAULT_VISION_JPEG_QUALITY)
            ),
        }
        cached = _read_page_cache(
            kind="layout",
            model=recognizer.model,
            image_path=image_path,
            page_no=page_no,
            payload_hint=payload_hint,
        )
        if cached is not None:
            print(f"[jin10-vlm] layout page {page_no}: cache hit", file=sys.stderr, flush=True)
            page_results.append(cached)
            continue
        print(f"[jin10-vlm] layout page {page_no}: start", file=sys.stderr, flush=True)
        result = recognizer.recognize_page_layout(
            image_path=image_path,
            page_no=page_no,
            page_width=payload_hint["page_width"],
            page_height=payload_hint["page_height"],
            expected_chart_count=payload_hint["expected_chart_count"],
            hint_titles=payload_hint["hint_titles"],
        )
        print(
            f"[jin10-vlm] layout page {page_no}: {result.get('status') or 'done'}",
            file=sys.stderr,
            flush=True,
        )
        _write_page_cache(
            kind="layout",
            model=recognizer.model,
            image_path=image_path,
            page_no=page_no,
            payload_hint=payload_hint,
            result=result,
        )
        page_results.append(result)
    return {
        "provider": recognizer.provider,
        "model": recognizer.model,
        "pages": page_results,
    }


def recognize_figure_title_bands(
    bands: list[dict[str, Any]],
    *,
    client: VisionMarkdownClient | None = None,
) -> list[dict[str, Any]]:
    recognizer = client or VisionMarkdownClient()
    results: list[dict[str, Any]] = []
    for band in bands:
        image = band.get("image")
        if image is None:
            continue
        results.append(
            {
                "figure_id": str(band.get("figure_id") or ""),
                "title": recognizer.recognize_title_band(image=image),
            }
        )
    return results


def _read_page_cache(
    *,
    kind: str,
    model: str,
    image_path: Path,
    page_no: int,
    payload_hint: dict[str, Any],
) -> dict[str, Any] | None:
    cache_path = _page_cache_path(kind=kind, model=model, image_path=image_path, page_no=page_no, payload_hint=payload_hint)
    if cache_path is None or not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    result = payload.get("result")
    return result if isinstance(result, dict) else None


def _write_page_cache(
    *,
    kind: str,
    model: str,
    image_path: Path,
    page_no: int,
    payload_hint: dict[str, Any],
    result: dict[str, Any],
) -> None:
    cache_path = _page_cache_path(kind=kind, model=model, image_path=image_path, page_no=page_no, payload_hint=payload_hint)
    if cache_path is None:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "kind": kind,
                "model": model,
                "page_no": page_no,
                "image_path": str(image_path),
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _page_cache_path(
    *,
    kind: str,
    model: str,
    image_path: Path,
    page_no: int,
    payload_hint: dict[str, Any],
) -> Path | None:
    root = _vision_page_cache_root()
    if root is None:
        return None
    key = _page_cache_key(kind=kind, model=model, image_path=image_path, page_no=page_no, payload_hint=payload_hint)
    return root / kind / model.replace("/", "_") / f"page_{page_no:03d}_{key}.json"


def _vision_page_cache_root() -> Path | None:
    raw = os.getenv("JIN10_VISION_CACHE_DIR", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _page_cache_key(*, kind: str, model: str, image_path: Path, page_no: int, payload_hint: dict[str, Any]) -> str:
    hasher = hashlib.sha256()
    hasher.update(kind.encode("utf-8"))
    hasher.update(model.encode("utf-8"))
    hasher.update(str(page_no).encode("utf-8"))
    hasher.update(json.dumps(payload_hint, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    if image_path.is_file():
        hasher.update(image_path.read_bytes())
    else:
        hasher.update(str(image_path).encode("utf-8"))
    return hasher.hexdigest()[:24]


def _normalize_report_type(report_type: str | None) -> str:
    return str(report_type or "").strip().lower()


def _prompt_profile_for_report_type(report_type: str | None) -> str:
    value = _normalize_report_type(report_type)
    if value in {"positioning", "technical_levels", "oil", "fx", "market_odds"}:
        return value
    return "default"


def _build_page_markdown_prompt(
    *,
    page_no: int,
    figures: list[dict[str, Any]],
    prompt_profile: str = "default",
) -> str:
    if prompt_profile == "positioning":
        return _build_positioning_page_markdown_prompt(page_no=page_no, figures=figures)
    if prompt_profile == "technical_levels":
        return _build_technical_levels_page_markdown_prompt(page_no=page_no, figures=figures)
    if prompt_profile == "oil":
        return _build_oil_page_markdown_prompt(page_no=page_no, figures=figures)
    if prompt_profile == "fx":
        return _build_fx_page_markdown_prompt(page_no=page_no, figures=figures)
    if prompt_profile == "market_odds":
        return _build_market_odds_page_markdown_prompt(page_no=page_no, figures=figures)
    return _build_default_page_markdown_prompt(page_no=page_no, figures=figures)


def _figure_prompt_block(figures: list[dict[str, Any]]) -> str:
    figure_lines = []
    for figure in figures:
        title = figure.get("title") or figure.get("figure_id") or "图表"
        figure_lines.append(f"- {title}: ![{title}]({figure['chart_image_path']})")
    return "\n".join(figure_lines) if figure_lines else "- 本页没有已裁剪图表"


def _build_default_page_markdown_prompt(*, page_no: int, figures: list[dict[str, Any]]) -> str:
    figure_block = _figure_prompt_block(figures)
    return f"""请把这张金十金银报告第 {page_no} 页逐字转写为 Markdown 原文。你是 OCR 转写器，不是摘要器，不要做市场分析。

要求：
1. 完整识别页面中的中文正文、标题、小标题、图表标题、图表说明和段落文字，保持原文顺序。
2. 不要输出页眉、页脚、免责声明、网址、联系方式、目录广告。
3. 如果页面中有图表，不要转述图表内部坐标轴和图例；在图表所在位置插入给定 Markdown 图片。
4. 如果页面没有图表，只输出识别到的文字。
5. 不要概括、不要压缩、不要改写、不要把多段内容合并成一句话。
6. 不要编造缺失内容，不要解释你的处理过程，只输出 Markdown。
7. 如果这一页是“封面/日期/导语/目录/免责声明”的壳页，只保留真正可读的导语或摘要正文。
8. 对壳页不要输出重复的报告总标题、日期、目录条目、联系方式、VIP 系列列表、免责声明。
9. 如果除了这些壳信息外没有正文，就返回空字符串。

本页可用图表图片：
{figure_block}
"""


def _build_market_odds_page_markdown_prompt(*, page_no: int, figures: list[dict[str, Any]]) -> str:
    figure_block = _figure_prompt_block(figures)
    return f"""请把这张金十市场赔率数据表第 {page_no} 页完整转写为 Markdown。你是结构化 OCR，不是分析师，不做市场预测。

要求：
1. 这是单页主内容，不是封面；必须保留标题、统计时间、品种、方向、目标价位、触及概率、月份和单位。
2. 按黄金、白银、原油、外汇、利率或报告实际出现的品种保持原始阅读顺序。
3. 明确区分“向上触及”和“向下触及”，不要把触及概率改写为方向预测。
4. 整页赔率面板插入给定 Markdown 图片，同时保留页面中可读的关键概率正文。
5. 不输出页眉、页脚、网址、联系方式、广告和免责声明；不补造模糊数字。

本页可用图表图片：
{figure_block}
"""


def _build_positioning_page_markdown_prompt(*, page_no: int, figures: list[dict[str, Any]]) -> str:
    figure_block = _figure_prompt_block(figures)
    return f"""请把这张金十持仓/期权分布报告第 {page_no} 页转写为 Markdown。你是结构化 OCR，不是分析师，不要给交易建议。

要求：
1. 页面标题类似“黄金持仓报告/白银持仓报告/欧元持仓报告/英镑持仓报告/澳元持仓报告”时，不要判定为封面，必须转写。
2. 对左右两栏“看涨期权/看跌期权”的图页，必须保留资产名称、两栏名称、图例含义（存量、单日新增/减）、价格/行权价轴范围和单位。
3. 图内最突出的单日新增/减柱、最大存量峰值、明显行权价/价格位要用项目符号列出；不确定图内数值写“约”，不要编造精确值。
4. 文字总结页必须逐项原样保留“期货持仓量、期货成交量、期权布局变化、期现价差、总结”中的数字、百分比、手数、价格位、增减方向和单位。
5. 不输出页眉、页脚、免责声明、网址和联系方式。
6. 不要概括、压缩或改写原文；只输出 Markdown。

本页可用图表图片：
{figure_block}
"""


def _build_technical_levels_page_markdown_prompt(*, page_no: int, figures: list[dict[str, Any]]) -> str:
    figure_block = _figure_prompt_block(figures)
    return f"""请把这张金十技术刘Pro/点位报告第 {page_no} 页转写为 Markdown。你是 OCR 转写器，不是摘要器，不做市场分析。

要求：
1. 保留品种名称，例如国际现货黄金、国际现货白银，以及“筹码形态”“形态解释”等栏目。
2. 必须保留图中明确标注的关键点位和缩写：VAH、VAL、POC、OTC、开/高/低/收、涨跌幅、时间周期、报价。
3. TradingHero/筹码分布图可插入给定 Markdown 图片，但正文里要同步保留图上可读的 VAH/VAL/POC 和形态结论文字。
4. 对图表内部难以精确读取的蜡烛细节不要编造；可读标签和正文精确数字必须原样保留。
5. 不输出页眉、页脚、免责声明、网址、联系方式。
6. 不要概括、压缩、改写；只输出 Markdown。

本页可用图表图片：
{figure_block}
"""


def _build_oil_page_markdown_prompt(*, page_no: int, figures: list[dict[str, Any]]) -> str:
    figure_block = _figure_prompt_block(figures)
    return f"""请把这张金十每日原油报告第 {page_no} 页转写为 Markdown。你是 OCR 转写器，不做市场分析。

要求：
1. 封面/目录页只保留报告标题、日期、导语核心句和目录；不要输出联系方式、VIP 系列列表和免责声明。
2. 正文页按原顺序保留栏目标题，例如行情回顾、隔夜要闻、今日原油市场聚焦、市场分析、关键图表、技术指标。
3. 原样保留 WTI、布伦特、EIA、API、OPEC、CFTC、霍尔木兹海峡、库存、钻井、裂解价差、期限结构等原油相关实体和指标。
4. 必须保留价格、百分比、桶/日、万桶、日期、合约月份、价差等数字和单位。
5. 图表页插入给定 Markdown 图片，并保留图表标题、数据来源、可读坐标轴名称和图后说明；不要编造看不清的序列数值。
6. 不输出页眉、页脚、免责声明、网址、联系方式；只输出 Markdown。

本页可用图表图片：
{figure_block}
"""


def _build_fx_page_markdown_prompt(*, page_no: int, figures: list[dict[str, Any]]) -> str:
    figure_block = _figure_prompt_block(figures)
    return f"""请把这张金十每日外汇报告第 {page_no} 页转写为 Markdown。你是 OCR 转写器，不做市场分析。

要求：
1. 封面/目录页只保留报告标题、日期、导语核心句和目录；不要输出联系方式、VIP 系列列表和免责声明。
2. 正文页按原顺序保留栏目标题，例如行情回顾、隔夜要闻、中东局势、市场分析、关键图表、技术指标。
3. 原样保留美元指数、美债收益率、FedWatch、PCE、核心PCE、实际利率、欧洲央行、主要货币和央行相关实体。
4. 必须保留指数点位、收益率、百分比、日期、预期概率、利差、通胀指标等数字和单位。
5. 图表页插入给定 Markdown 图片，并保留图表标题、数据来源、坐标轴名称和图后说明；不要编造看不清的序列数值。
6. 不输出页眉、页脚、免责声明、网址、联系方式；只输出 Markdown。

本页可用图表图片：
{figure_block}
"""


def _build_page_unified_prompt(
    *,
    page_no: int,
    page_width: int,
    page_height: int,
    original_page_width: int,
    original_page_height: int,
    prompt_profile: str = "default",
    preserve_cover_identity: bool = False,
) -> str:
    report_kind = {
        "positioning": "持仓或期权分布报告",
        "technical_levels": "技术点位报告",
        "oil": "每日原油报告",
        "fx": "每日外汇报告",
        "market_odds": "市场赔率数据表",
    }.get(prompt_profile, "金银日报或周报")

    if preserve_cover_identity:
        cover_rule = """这是封面页。只保留正式报告分类、日期、本期主题和导语；正式报告分类与本期主题分别返回 title block。正式分类可能位于页面底部，例如“黄金投资者周报”“每日金银报告”“每日市场观察”“周末·大师复盘”“持仓报告”。联系方式、VIP 列表、目录、APP 广告和免责声明不得进入 markdown 或 blocks。"""
    else:
        cover_rule = "忽略页眉、页脚、联系方式、网址、广告和免责声明。"
        if prompt_profile == "market_odds":
            cover_rule += " 这是市场赔率数据表主内容页，不是封面；整页赔率面板应作为一个完整 table/image bbox，并逐字保留品种、目标价位、向上/向下触及概率、月份和统计时间。"

    return f"""你是页面识别与裁剪定位器。唯一任务是 OCR 和 bbox 定位。

禁止总结、解释、改写、推断、比较、评价、计算趋势、分析市场或给出投资结论。不要回答页面内容提出的问题。只返回 JSON，不要 Markdown 代码块。

页面：第 {page_no} 页；类型提示：{report_kind}。
当前输入图片：{page_width}x{page_height}；原始报告页：{original_page_width}x{original_page_height}。
所有 bbox 使用当前输入图片的像素坐标 `[x1, y1, x2, y2]`，程序会按 `image_size` 缩放裁剪。

输出字段：
- `image_size`：当前输入图片尺寸。
- `markdown`：按阅读顺序逐字转写文章标题、正文、图表标题、图注和正文关键数字；不可概括。图表位置插入 `![图表标题](figures/fig_p{page_no}_001.png)`，按从上到下编号。
- `blocks`：只使用 title/text/chart/table/image/unknown。

裁剪规则：
1. chart/table/image bbox 必须覆盖可独立使用的完整视觉面板，包括面板边框或背景、面板内标题、图例、坐标轴、刻度标签、数据来源和紧邻图注。
2. 不得只框内部绘图区，不得漏掉左右边缘、顶部标题或底部标签。
3. 排除相邻正文、页面栏目标题、页眉、页脚和免责声明。面板外的标题或正文另建 title/text block。
4. 多个上下或左右排列的面板分别返回，按页面阅读顺序排列。
5. 没有真实图表、表格或图片时不要编造对应 block；不确定类型写 unknown。
6. chart/table/image block 的 `text` 只写面板标题，没有标题就写空字符串；不要转写面板内部序列、刻度、图例或数据点。

OCR 规则：
1. 原样保留文章标题、正文和图注中的日期、数值、百分比、单位及中英文专有名词，不补造模糊内容。
2. 不需要解释图中曲线、柱形或指标意味着什么。
3. 页眉、页脚、联系方式、网址、广告、目录和免责声明不得进入 markdown 或 blocks。
4. {cover_rule}

JSON 结构：
{{
  "image_size": {{"width": {page_width}, "height": {page_height}}},
  "markdown": "## 标题\\n\\n正文...\\n\\n![图表标题](figures/fig_p{page_no}_001.png)\\n\\n图后正文...",
  "blocks": [
    {{"id": "title_001", "type": "title", "text": "标题文字", "bbox": [100, 200, 900, 260]}},
    {{"id": "text_001", "type": "text", "text": "正文段落", "bbox": [100, 300, 900, 520]}},
    {{"id": "chart_001", "type": "chart", "text": "图表标题或留空", "bbox": [100, 560, 900, 1200]}}
  ]
}}
"""


def _build_page_layout_prompt(
    *,
    page_no: int,
    page_width: int,
    page_height: int,
    original_page_width: int,
    original_page_height: int,
    expected_chart_count: int,
    hint_titles: list[str],
) -> str:
    hint_block = "\n".join(f"- {title}" for title in hint_titles if title) or "- 无标题提示"
    return f"""你只做 OCR 与版面定位，不做市场分析。

核心任务：
- 识别金十图片报告中的“真实图表面板”。
- 图表面板通常是深色页面背景中的白色/浅色矩形区域，内部包含坐标轴、曲线、柱状图、图例、刻度或第三方图表截图。
- bbox 必须框住完整白色/浅色图表面板，而不是页眉、页面大标题、金色小标题、正文段落、页脚免责声明。

要求：
1. 请识别图片中的标题区域、正文文本块、表格区域、图表区域、图片/插图区域。
2. 只返回 JSON，不要解释，不要总结，不要 Markdown。
3. 只输出 `image_size` 和 `blocks`，不要输出 `charts` 字段或其他额外字段。
4. 坐标使用你当前看到的输入图片像素坐标 [x1, y1, x2, y2]；当前输入图片宽度为 {page_width}，高度为 {page_height}。
5. `image_size` 必须填写当前输入图片尺寸 {page_width}x{page_height}，不要填写原始报告页尺寸。
6. 原始报告页尺寸为 {original_page_width}x{original_page_height}，后续程序会按 `image_size` 自动缩放回原始报告页。
7. 正文按文本块或段落返回，不要逐字拆分。
8. 图表和图片区域即使没有文字，也必须返回 bbox。
9. 如果不确定某区域类型，type 写 unknown。
10. 图表区域要尽量贴合图表本体的白色/浅色矩形外框，必须覆盖完整图表宽度和高度。
11. 这页预期至少有 {expected_chart_count or 0} 张图表；优先关注以下标题相关区域。
12. 如果页面有多个上下排列的白色图表面板，必须分别返回多个 chart block，按从上到下顺序排列。
13. 不要把“关键图表”“技术指标”等页面章节标题当作 chart；这些是 title/text。
14. 不要漏掉图表上方的金色大标题，例如“黄金机构动向”“白银机构动向”；它们必须作为 title block 返回，不要纳入 chart bbox。
15. 不要把白色图表面板只截左半边；bbox 的 x2 应覆盖到图表面板右边界。
16. 不要把页脚免责声明、网址、顶部栏目名、报告名称纳入 chart bbox。
17. 如果页面主要是封面、导语、目录、联系方式或免责声明壳页，不要返回 chart block，除非页面里真的有独立图表面板。
18. 持仓/期权分布页中左右两栏“看涨期权/看跌期权”可以作为两个 chart block；若整页是一个连续分布图，也可以返回一个覆盖两栏的 chart block，但必须另有 title/text block 标明资产和两栏名称。

图表 bbox 正例：
- 白色折线图矩形整体：[左边界, 上边界, 右边界, 下边界]
- Polymarket / MacroMicro / TradingView 等嵌入图表截图整体

图表 bbox 反例：
- 只框住“10年期美债收益率回落”这类金色标题
- 只框住白色图表左半部分
- 把深色整页背景、页眉、页脚一起框进去
- 把正文段落误判为 chart

图表标题提示（仅供辅助判断）：
{hint_block}

JSON 结构：
{{
  "image_size": {{"width": {page_width}, "height": {page_height}}},
  "blocks": [
    {{
      "id": "title_001",
      "type": "title",
      "text": "标题文字",
      "bbox": [100, 200, 900, 700]
    }},
    {{
      "id": "chart_001",
      "type": "chart",
      "text": "图表标题或留空",
      "bbox": [100, 720, 900, 1300]
    }}
  ]
}}
"""


def _build_title_band_prompt(*, page_width: int, page_height: int) -> str:
    return f"""你只做标题识别，不做分析。

输入是一张从报告页中裁出的窄条区域，尺寸为 {page_width}x{page_height}。
要求：
1. 如果区域内存在图表标题、章节标题或表格标题，返回最主要的一行标题文字。
2. 只返回标题纯文本，不要加引号，不要加 Markdown，不要解释。
3. 如果没有可用标题，只返回空字符串。
4. 不要返回页眉、页脚、网址、水印、数轴刻度、Tooltip 数值。
"""


def _image_to_data_url(
    path: Path,
    *,
    max_long_edge: int | None = None,
    jpeg_quality: int | None = None,
) -> EncodedImage:
    normalized = cv2.imread(str(path))
    if normalized is not None:
        height, width = normalized.shape[:2]
        longest = max(height, width)
        if (
            path.suffix.lower() in {".jpg", ".jpeg"}
            and jpeg_quality is not None
            and (not max_long_edge or longest <= max_long_edge)
        ):
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            data_url = f"data:image/jpeg;base64,{encoded}"
            if len(data_url) <= MAX_IMAGE_DATA_URL_CHARS:
                return EncodedImage(data_url=data_url, width=width, height=height)
        return _image_array_to_data_url(
            normalized,
            max_long_edge=max_long_edge,
            jpeg_quality=jpeg_quality,
        )

    mime_type = _guess_mime_type(path)
    if not mime_type:
        raise ValueError("image_not_decodable_or_unsupported_format")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    data_url = f"data:{mime_type};base64,{encoded}"
    if len(data_url) > MAX_IMAGE_DATA_URL_CHARS:
        raise ValueError("encoded_image_exceeds_data_uri_limit")
    return EncodedImage(data_url=data_url, width=0, height=0)


def _image_array_to_data_url(
    image: Any,
    *,
    max_long_edge: int | None = None,
    jpeg_quality: int | None = None,
) -> EncodedImage:
    if image is None:
        raise ValueError("image_not_decodable_or_unsupported_format")
    if max_long_edge and max_long_edge > 0:
        height, width = image.shape[:2]
        longest = max(height, width)
        if longest > max_long_edge:
            scale = max_long_edge / longest
            image = cv2.resize(
                image,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
    height, width = image.shape[:2]
    if jpeg_quality is not None:
        quality = max(70, min(100, int(jpeg_quality)))
        jpg_url = _encoded_image_data_url(
            image,
            ".jpg",
            [int(cv2.IMWRITE_JPEG_QUALITY), quality],
        )
        if jpg_url and len(jpg_url) <= MAX_IMAGE_DATA_URL_CHARS:
            return EncodedImage(data_url=jpg_url, width=width, height=height)
    png_url = _encoded_image_data_url(image, ".png")
    if png_url and len(png_url) <= MAX_IMAGE_DATA_URL_CHARS:
        return EncodedImage(data_url=png_url, width=width, height=height)

    for scale in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3, 0.2, 0.15, 0.1):
        current = image
        if scale < 1.0:
            current = cv2.resize(
                image,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_AREA,
            )
        current_height, current_width = current.shape[:2]
        for quality in (90, 80, 70, 60, 50, 40, 30, 20):
            jpg_url = _encoded_image_data_url(
                current,
                ".jpg",
                [int(cv2.IMWRITE_JPEG_QUALITY), quality],
            )
            if jpg_url and len(jpg_url) <= MAX_IMAGE_DATA_URL_CHARS:
                return EncodedImage(data_url=jpg_url, width=current_width, height=current_height)

    raise ValueError("encoded_image_exceeds_data_uri_limit")


def _encoded_image_data_url(image: Any, ext: str, params: list[int] | None = None) -> str | None:
    ok, buffer = cv2.imencode(ext, image, params or [])
    if not ok:
        return None
    mime_type = "image/png" if ext == ".png" else "image/jpeg"
    encoded = base64.b64encode(buffer.tobytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _normalize_title_band_text(text: str) -> str:
    stripped = _strip_markdown_fences(text).strip().strip("\"'`")
    stripped = " ".join(stripped.split())
    if not stripped:
        return ""
    lowered = "".join(stripped.split()).lower()
    if any(token in lowered for token in ("金十数据", "www.", "tooltip", "公布值")):
        return ""
    return stripped


def _guess_mime_type(path: Path) -> str:
    return SUPPORTED_RAW_IMAGE_MIME_TYPES.get(path.suffix.lower(), "")


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_layout_json(text: str) -> dict[str, Any]:
    stripped = _strip_markdown_fences(text)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {"charts": []}
    try:
        return json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return {"charts": []}


def _normalize_layout_blocks(
    payload: dict[str, Any] | None,
    *,
    page_width: int,
    page_height: int,
    fallback_coordinate_size: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw_blocks = payload.get("blocks")
    if not isinstance(raw_blocks, list):
        raw_charts = payload.get("charts")
        if isinstance(raw_charts, list):
            raw_blocks = [
                {
                    "id": item.get("chart_id") or f"chart_{index:03d}",
                    "type": "chart",
                    "text": item.get("title") or "",
                    "bbox": item.get("bbox"),
                }
                for index, item in enumerate(raw_charts, start=1)
                if isinstance(item, dict)
            ]
        else:
            raw_blocks = []
    coordinate_width, coordinate_height = _layout_coordinate_size(
        payload,
        raw_blocks=raw_blocks,
        page_width=page_width,
        page_height=page_height,
        fallback_coordinate_size=fallback_coordinate_size,
    )

    normalized: list[dict[str, Any]] = []
    for index, block in enumerate(raw_blocks, start=1):
        if not isinstance(block, dict):
            continue
        bbox = _normalize_chart_bbox(
            block.get("bbox"),
            page_width=page_width,
            page_height=page_height,
            coordinate_width=coordinate_width,
            coordinate_height=coordinate_height,
        )
        if not bbox:
            continue
        block_type = str(block.get("type") or "unknown").strip().lower()
        if block_type not in {"title", "text", "table", "chart", "image", "unknown"}:
            block_type = "unknown"
        normalized.append(
            {
                "id": str(block.get("id") or f"{block_type}_{index:03d}"),
                "type": block_type,
                "text": str(block.get("text") or "").strip(),
                "bbox": bbox,
            }
        )
    return normalized


def _layout_coordinate_size(
    payload: dict[str, Any],
    *,
    raw_blocks: list[dict[str, Any]],
    page_width: int,
    page_height: int,
    fallback_coordinate_size: tuple[int, int] | None = None,
) -> tuple[int, int]:
    image_size = payload.get("image_size")
    if not isinstance(image_size, dict):
        if fallback_coordinate_size:
            return fallback_coordinate_size
        return page_width, page_height
    try:
        coordinate_width = int(float(image_size.get("width") or page_width))
        coordinate_height = int(float(image_size.get("height") or page_height))
    except (TypeError, ValueError):
        return page_width, page_height
    if coordinate_width <= 0 or coordinate_height <= 0:
        return page_width, page_height
    if _looks_like_normalized_1000_coordinate_space(
        raw_blocks=raw_blocks,
        coordinate_width=coordinate_width,
        coordinate_height=coordinate_height,
        page_width=page_width,
        page_height=page_height,
    ):
        return 1000, 1000
    return coordinate_width, coordinate_height


def _looks_like_normalized_1000_coordinate_space(
    *,
    raw_blocks: list[dict[str, Any]],
    coordinate_width: int,
    coordinate_height: int,
    page_width: int,
    page_height: int,
) -> bool:
    if page_width <= 1200 or page_height <= 1200:
        return False
    if abs(coordinate_width - page_width) > 2 or abs(coordinate_height - page_height) > 2:
        return False
    bboxes = [block.get("bbox") for block in raw_blocks if isinstance(block, dict)]
    if not bboxes:
        return False
    values: list[float] = []
    for bbox in bboxes:
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            values.extend(float(item) for item in bbox)
        except (TypeError, ValueError):
            continue
    if not values:
        return False
    return max(values) <= 1000 and page_width >= 1.5 * 1000 and page_height >= 1.5 * 1000


def _normalize_chart_bbox(
    value: Any,
    *,
    page_width: int,
    page_height: int,
    coordinate_width: int | None = None,
    coordinate_height: int | None = None,
) -> list[int] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = [int(float(item)) for item in value]
    except (TypeError, ValueError):
        return None
    source_width = coordinate_width or page_width
    source_height = coordinate_height or page_height
    x1 = max(0, min(x1, source_width))
    x2 = max(0, min(x2, source_width))
    y1 = max(0, min(y1, source_height))
    y2 = max(0, min(y2, source_height))
    if source_width != page_width or source_height != page_height:
        scale_x = page_width / source_width
        scale_y = page_height / source_height
        x1 = int(round(x1 * scale_x))
        x2 = int(round(x2 * scale_x))
        y1 = int(round(y1 * scale_y))
        y2 = int(round(y2 * scale_y))
    if x2 - x1 < max(80, int(page_width * 0.12)) or y2 - y1 < max(80, int(page_height * 0.03)):
        return None
    return [x1, y1, x2, y2]


def normalize_page_markdown(markdown: str, figures: list[dict[str, Any]]) -> str:
    normalized = markdown.strip()
    if not normalized:
        return normalized

    figure_markdowns = [
        f"![{figure.get('title') or figure.get('figure_id') or '图表'}]({figure['chart_image_path']})"
        for figure in figures
        if figure.get("chart_image_path")
    ]
    if not figure_markdowns:
        return _strip_visual_noise_lines(normalized)

    local_paths = {str(figure.get("chart_image_path")) for figure in figures if figure.get("chart_image_path")}
    inserted: list[str] = []

    def replace_remote(match: Any) -> str:
        nonlocal figure_markdowns
        alt_text = (match.group(1) or "").strip()
        image_path = (match.group(2) or "").strip()
        if image_path in local_paths:
            inserted.append(image_path)
            return match.group(0)
        if figure_markdowns:
            replacement = figure_markdowns.pop(0)
            inserted.append(replacement.split("](", 1)[1].rstrip(")"))
            if alt_text and alt_text not in {"图表", "chart", "Chart"}:
                return replacement.replace("![", f"![{alt_text} - ", 1)
            return replacement
        return match.group(0)

    import re

    normalized = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_remote, normalized)
    normalized = _inject_missing_figure_markdowns(normalized, figures)
    normalized = _rebalance_figure_markdowns(normalized, figures)
    normalized = _dedupe_figure_markdowns(normalized)
    normalized = _normalize_figure_spacing(normalized)
    normalized = _strip_visual_noise_lines(normalized)
    return normalized


def _inject_missing_figure_markdowns(markdown: str, figures: list[dict[str, Any]]) -> str:
    remaining = [
        figure
        for figure in figures
        if figure.get("chart_image_path") and str(figure["chart_image_path"]) not in markdown
    ]
    if not remaining:
        return markdown

    lines = markdown.splitlines()
    output: list[str] = []
    remaining_index = 0
    for index, line in enumerate(lines):
        output.append(line)
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if remaining_index >= len(remaining):
            continue
        next_line = ""
        for follow in lines[index + 1 :]:
            if follow.strip():
                next_line = follow.strip()
                break
        if next_line.startswith("!["):
            continue
        figure = remaining[remaining_index]
        output.extend(
            [
                "",
                f"![{figure.get('title') or figure.get('figure_id') or '图表'}]({figure['chart_image_path']})",
                "",
            ]
        )
        remaining_index += 1
    return "\n".join(output).strip()


def _rebalance_figure_markdowns(markdown: str, figures: list[dict[str, Any]]) -> str:
    import re

    figure_paths = [str(figure["chart_image_path"]) for figure in figures if figure.get("chart_image_path")]
    if not figure_paths:
        return markdown

    image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    matches = list(image_pattern.finditer(markdown))
    if not matches:
        return markdown

    used_paths = {match.group(2).strip() for match in matches if match.group(2).strip() in figure_paths}
    unused_paths = [path for path in figure_paths if path not in used_paths]
    duplicate_seen: set[str] = set()
    chunks: list[str] = []
    cursor = 0

    for match in matches:
        chunks.append(markdown[cursor : match.start()])
        alt_text = (match.group(1) or "").strip() or "图表"
        image_path = (match.group(2) or "").strip()
        replacement = match.group(0)

        if image_path in figure_paths:
            if image_path in duplicate_seen and unused_paths:
                next_path = unused_paths.pop(0)
                replacement = f"![{alt_text}]({next_path})"
                duplicate_seen.add(next_path)
            else:
                duplicate_seen.add(image_path)
        elif image_path.startswith(("http://", "https://")):
            # Preserve unresolved remote placeholders so later local figures can
            # be injected under the matching heading instead of overwriting an
            # already-correct local figure path.
            pass

        chunks.append(replacement)
        cursor = match.end()

    chunks.append(markdown[cursor:])
    return "".join(chunks)


def _strip_visual_noise_lines(markdown: str) -> str:
    import re

    noise_lines = {"即时市场展望", "即时市场洞察", "每日市场观察"}
    cleaned: list[str] = []
    last_blank = False

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            if not last_blank:
                cleaned.append("")
            last_blank = True
            continue
        if line in noise_lines:
            continue
        if re.fullmatch(r"图\d+", line):
            continue
        cleaned.append(raw_line)
        last_blank = False

    return "\n".join(cleaned).strip()


def _dedupe_figure_markdowns(markdown: str) -> str:
    import re

    lines = markdown.splitlines()
    deduped: list[str] = []
    previous_image_path = ""
    image_pattern = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("!["):
            match = image_pattern.fullmatch(stripped)
            image_path = (match.group(1).strip() if match else stripped)
            if image_path == previous_image_path:
                continue
            previous_image_path = image_path
        elif stripped:
            previous_image_path = ""
        deduped.append(line)

    return "\n".join(deduped).strip()


def _normalize_figure_spacing(markdown: str) -> str:
    lines = markdown.splitlines()
    normalized: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("![") and normalized and normalized[-1].strip():
            normalized.append("")
        normalized.append(line)
        if stripped.startswith("!["):
            normalized.append("")

    compacted: list[str] = []
    last_blank = False
    for line in normalized:
        if not line.strip():
            if not last_blank:
                compacted.append("")
            last_blank = True
            continue
        compacted.append(line)
        last_blank = False
    return "\n".join(compacted).strip()
