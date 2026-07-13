"""Jin10 page recognition agent package.

The parser owns orchestration and artifacts. This package owns the VLM client,
recognition prompts, response normalization, and page-level cache behavior.
"""

from apps.parsers.jin10.vision_recognition_agent.agent import (
    DEFAULT_MIMO_VL_MODEL,
    DEFAULT_VISION_PROVIDER,
    DEFAULT_VISION_MODEL,
    DEFAULT_VISION_REASONING_EFFORT,
    VisionMarkdownClient,
    normalize_page_markdown,
    recognize_figure_title_bands,
    recognize_pages_as_markdown,
    recognize_pages_layout,
    recognize_pages_unified,
)

__all__ = [
    "DEFAULT_MIMO_VL_MODEL",
    "DEFAULT_VISION_PROVIDER",
    "DEFAULT_VISION_MODEL",
    "DEFAULT_VISION_REASONING_EFFORT",
    "VisionMarkdownClient",
    "normalize_page_markdown",
    "recognize_figure_title_bands",
    "recognize_pages_as_markdown",
    "recognize_pages_layout",
    "recognize_pages_unified",
]
