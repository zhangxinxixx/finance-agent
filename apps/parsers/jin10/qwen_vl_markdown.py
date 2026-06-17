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
from openai import OpenAI

from apps.runtime.secret_resolver import resolve_runtime_secret


DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_VL_MODEL = "qwen3-vl-flash"
DEFAULT_QWEN_VL_TIMEOUT = 90.0
MAX_IMAGE_DATA_URL_CHARS = 9_500_000
SUPPORTED_RAW_IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class MissingDashScopeApiKey(RuntimeError):
    """Raised when Qwen VL recognition is requested but no API key is configured."""


@dataclass(slots=True)
class EncodedImage:
    data_url: str
    width: int
    height: int


class DashScopeVisionMarkdownClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DASHSCOPE_BASE_URL,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        load_dotenv()
        resolved_api_key = (api_key or resolve_runtime_secret("DASHSCOPE_API_KEY") or "").strip()
        if not resolved_api_key:
            raise MissingDashScopeApiKey("DASHSCOPE_API_KEY is not configured")
        self.model = model or os.getenv("JIN10_QWEN_VL_MODEL", DEFAULT_QWEN_VL_MODEL)
        self.timeout = float(timeout or os.getenv("JIN10_QWEN_VL_TIMEOUT", DEFAULT_QWEN_VL_TIMEOUT))
        self._client = OpenAI(api_key=resolved_api_key, base_url=base_url, timeout=self.timeout)

    def recognize_page_markdown(
        self,
        *,
        image_path: Path,
        page_no: int,
        figures: list[dict[str, Any]],
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
            encoded_image = _image_to_data_url(image_path)
        except ValueError as exc:
            return {
                "page_no": page_no,
                "status": "unavailable",
                "reason": str(exc),
                "markdown": "",
                "model": self.model,
            }

        completion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": encoded_image.data_url,
                            },
                        },
                        {
                            "type": "text",
                            "text": _build_page_markdown_prompt(page_no=page_no, figures=figures),
                        },
                    ],
                }
            ],
            temperature=0,
            extra_body={"enable_thinking": False},
        )
        content = completion.choices[0].message.content or ""
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
            encoded_image = _image_to_data_url(image_path)
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

        completion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": encoded_image.data_url,
                            },
                        },
                        {
                            "type": "text",
                            "text": _build_page_layout_prompt(
                                page_no=page_no,
                                page_width=encoded_image.width,
                                page_height=encoded_image.height,
                                original_page_width=page_width,
                                original_page_height=page_height,
                                expected_chart_count=expected_chart_count,
                                hint_titles=hint_titles or [],
                            ),
                        },
                    ],
                }
            ],
            temperature=0,
            extra_body={"enable_thinking": False},
        )
        content = completion.choices[0].message.content or ""
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
            encoded_image = _image_to_data_url(image_path)
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

        completion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": encoded_image.data_url,
                            },
                        },
                        {
                            "type": "text",
                            "text": _build_page_unified_prompt(
                                page_no=page_no,
                                page_width=encoded_image.width,
                                page_height=encoded_image.height,
                                original_page_width=page_width,
                                original_page_height=page_height,
                            ),
                        },
                    ],
                }
            ],
            temperature=0,
            extra_body={"enable_thinking": False},
        )
        payload = _parse_layout_json(completion.choices[0].message.content or "")
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
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": encoded_image.data_url,
                            },
                        },
                        {
                            "type": "text",
                            "text": _build_title_band_prompt(
                                page_width=encoded_image.width,
                                page_height=encoded_image.height,
                            ),
                        },
                    ],
                }
            ],
            temperature=0,
            extra_body={"enable_thinking": False},
        )
        return _normalize_title_band_text(completion.choices[0].message.content or "")


def recognize_pages_as_markdown(
    pages: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    *,
    client: DashScopeVisionMarkdownClient | None = None,
) -> dict[str, Any]:
    recognizer = client or DashScopeVisionMarkdownClient()
    figure_map: dict[int, list[dict[str, Any]]] = {}
    for figure in figures:
        figure_map.setdefault(int(figure["page_no"]), []).append(figure)

    page_results: list[dict[str, Any]] = []
    for page in pages:
        page_no = int(page["page_no"])
        image_path = Path(str(page["image_path"]))
        page_figures = figure_map.get(page_no, [])
        cached = _read_page_cache(
            kind="markdown",
            model=recognizer.model,
            image_path=image_path,
            page_no=page_no,
            payload_hint={"figures": page_figures},
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
            payload_hint={"figures": page_figures},
            result=result,
        )
        page_results.append(result)
    return {
        "provider": "dashscope",
        "model": recognizer.model,
        "pages": page_results,
    }


def recognize_pages_unified(
    pages: list[dict[str, Any]],
    *,
    client: DashScopeVisionMarkdownClient | None = None,
) -> dict[str, Any]:
    recognizer = client or DashScopeVisionMarkdownClient()
    page_results: list[dict[str, Any]] = []
    for page in pages:
        page_no = int(page["page_no"])
        image_path = Path(str(page["image_path"]))
        payload_hint = {
            "prompt_version": "unified-v1-markdown-and-layout",
            "page_width": int(page.get("width") or 0),
            "page_height": int(page.get("height") or 0),
        }
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
        result = recognizer.recognize_page_unified(
            image_path=image_path,
            page_no=page_no,
            page_width=payload_hint["page_width"],
            page_height=payload_hint["page_height"],
        )
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
        "provider": "dashscope",
        "model": recognizer.model,
        "pages": page_results,
    }


def recognize_pages_layout(
    pages: list[dict[str, Any]],
    *,
    client: DashScopeVisionMarkdownClient | None = None,
) -> dict[str, Any]:
    recognizer = client or DashScopeVisionMarkdownClient()
    page_results: list[dict[str, Any]] = []
    for page in pages:
        page_no = int(page["page_no"])
        image_path = Path(str(page["image_path"]))
        payload_hint = {
            "prompt_version": "layout-v4-sent-image-or-normalized-coordinate-space",
            "page_width": int(page.get("width") or 0),
            "page_height": int(page.get("height") or 0),
            "expected_chart_count": int(page.get("expected_chart_count") or 0),
            "hint_titles": [str(item) for item in (page.get("hint_titles") or [])],
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
        "provider": "dashscope",
        "model": recognizer.model,
        "pages": page_results,
    }


def recognize_figure_title_bands(
    bands: list[dict[str, Any]],
    *,
    client: DashScopeVisionMarkdownClient | None = None,
) -> list[dict[str, Any]]:
    recognizer = client or DashScopeVisionMarkdownClient()
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


def _build_page_markdown_prompt(*, page_no: int, figures: list[dict[str, Any]]) -> str:
    figure_lines = []
    for figure in figures:
        title = figure.get("title") or figure.get("figure_id") or "图表"
        figure_lines.append(f"- {title}: ![{title}]({figure['chart_image_path']})")
    figure_block = "\n".join(figure_lines) if figure_lines else "- 本页没有已裁剪图表"
    return f"""请把这张金十金银报告第 {page_no} 页逐字转写为 Markdown 原文。你是 OCR 转写器，不是摘要器，不要做市场分析。

要求：
1. 完整识别页面中的中文正文、标题、小标题、图表标题、图表说明和段落文字，保持原文顺序。
2. 不要输出页眉、页脚、免责声明、网址、联系方式、目录广告。
3. 如果页面中有图表，不要转述图表内部坐标轴和图例；在图表所在位置插入给定 Markdown 图片。
4. 如果页面没有图表，只输出识别到的文字。
5. 不要概括、不要压缩、不要改写、不要把多段内容合并成一句话。
6. 不要编造缺失内容，不要解释你的处理过程，只输出 Markdown。

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
) -> str:
    return f"""你是金十金银图片报告的单页 OCR 与图表定位器，不做市场分析。

请对第 {page_no} 页一次性输出完整 JSON，只返回 JSON，不要解释，不要 Markdown 代码块。

你当前看到的输入图片尺寸是 {page_width}x{page_height}。
原始报告页尺寸是 {original_page_width}x{original_page_height}，后续程序会按 `image_size` 缩放 bbox。

输出字段：
- image_size：必须填写当前输入图片尺寸。
- markdown：逐字转写正文、标题、小标题、图表标题、图后说明，保持页面阅读顺序。
- blocks：页面版面块，包含 title/text/chart/table/image/unknown。

markdown 要求：
1. 不要输出页眉、页脚、免责声明、网址、联系方式、目录广告。
2. 不要总结、不要改写、不要压缩段落。
3. 页面有图表时，在图表位置插入本地图片占位：`![图表标题](figures/fig_p{page_no}_001.png)`、`![图表标题](figures/fig_p{page_no}_002.png)`，按从上到下顺序编号。
4. 不要转写图表内部坐标轴、图例、刻度和 tooltip 数值。
5. 纯文字页 markdown 只输出正文。

blocks 要求：
1. bbox 使用你当前看到的输入图片像素坐标 [x1, y1, x2, y2]。
2. chart/table/image bbox 只框图表或表格本体，不要包含上方标题文字。
3. 图表标题作为 title block 返回，不要并进 chart bbox。
4. 纯文字页可以只返回 title/text blocks，完全没有图表时不要编造 chart。
5. 如果不确定某区域类型，type 写 unknown。

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


def _image_to_data_url(path: Path) -> EncodedImage:
    normalized = cv2.imread(str(path))
    if normalized is not None:
        return _image_array_to_data_url(normalized)

    mime_type = _guess_mime_type(path)
    if not mime_type:
        raise ValueError("image_not_decodable_or_unsupported_format")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    data_url = f"data:{mime_type};base64,{encoded}"
    if len(data_url) > MAX_IMAGE_DATA_URL_CHARS:
        raise ValueError("encoded_image_exceeds_dashscope_data_uri_limit")
    return EncodedImage(data_url=data_url, width=0, height=0)


def _image_array_to_data_url(image: Any) -> EncodedImage:
    if image is None:
        raise ValueError("image_not_decodable_or_unsupported_format")
    height, width = image.shape[:2]
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

    raise ValueError("encoded_image_exceeds_dashscope_data_uri_limit")


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
    if _looks_like_qwen_normalized_coordinate_space(
        raw_blocks=raw_blocks,
        coordinate_width=coordinate_width,
        coordinate_height=coordinate_height,
        page_width=page_width,
        page_height=page_height,
    ):
        return 1000, 1000
    return coordinate_width, coordinate_height


def _looks_like_qwen_normalized_coordinate_space(
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
