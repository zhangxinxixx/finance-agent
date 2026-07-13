# Jin10 Vision Recognition Agent

This package owns page-level visual recognition for Jin10 reports.

## Responsibilities

- encode and resize the current page image for VLM input
- build recognition-only prompts
- return OCR markdown and layout blocks with bbox coordinates
- normalize coordinates back to the original page size
- maintain page-level recognition cache entries

## Boundaries

- orchestration and parsed artifact writing remain in `report_image_parser.py`
- the Agent does not perform market analysis or generate investment conclusions
- the Agent does not modify raw images; final crops always use the archived source page
- model calls continue through the shared LLM gateway

## Public entry points

- `VisionMarkdownClient`
- `recognize_pages_unified`
- `recognize_pages_layout`
- `recognize_pages_as_markdown`
- `recognize_figure_title_bands`
