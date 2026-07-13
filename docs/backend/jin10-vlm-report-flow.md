# Jin10 VLM 图文报告解析流程

- Date: 2026-06-02
- Scope: Jin10 会员日报/周报的多页图片报告解析
- Owner module: `apps/parsers/jin10/`

## 目标

Jin10 会员报告的解析产物必须是人可读、可追溯、可复核的图文原文，而不是把网页抓取内容或图片文件名直接交给分析层。

最终主链保持：

```text
collector
-> raw archive
-> parser
-> raw_article_report.md / figures.json / vision snapshots
-> analysis
-> renderer / output
```

正式模型配置：

```text
页面识别与 bbox：gpt-5.6-luna + high，单页 120 秒，0 重试
Agent 二次分析：gpt-5.6-sol + high，整份 300 秒，0 重试
分析图片：最多 25 张，按正文顺序提交；长边 1600、JPEG 92
```

默认环境变量：

```text
JIN10_VISION_PROVIDER=cockpit
JIN10_VISION_MODEL=gpt-5.6-luna
JIN10_VISION_REASONING_EFFORT=high
JIN10_VISION_TIMEOUT=120
JIN10_VISION_MAX_RETRIES=0
JIN10_AGENT_PROVIDER=cockpit
JIN10_AGENT_MODEL=gpt-5.6-sol
JIN10_AGENT_REASONING_EFFORT=high
JIN10_AGENT_REQUEST_TIMEOUT=300
JIN10_AGENT_MAX_IMAGES=25
```

## 输入

解析入口是 `parse_report_images()`，主要输入来自抓取层归档：

- `detail.html`
- `report.md`
- `meta.json`
- `images/page-NNN.jpg`：采集阶段已按 VLM 尺寸与质量规范化的 canonical 页面 JPEG
- article metadata: `article_id`, `title`, `published_at`

日报和周报必须按 `category_code` 分流：

- 日报：`category_code=270`
- 周报：`category_code=536`

## VLM 主路径

默认主路径是一页图片只调用一次 VLM：

```text
page image
-> recognize_pages_unified()
-> page JSON: markdown + blocks + bbox
```

`recognize_pages_unified()` 位于 `apps/parsers/jin10/vision_recognition_agent/agent.py`。

单页 unified 输出必须包含：

- `image_size`: VLM 实际看到的图片尺寸
- `markdown`: 整页 OCR 后的 Markdown 原文
- `blocks`: 页面版面块
- `chart/table/image bbox`: 图表或表格本体裁剪框

要求：

- 正文、标题、图表标题都进入 `markdown`。
- 图表截图只裁图表/表格本体，不把标题带裁进图片。
- 坐标以 `image_size` 为准，解析层按比例还原到原图坐标。
- 纯文字页不需要产出 chart block。

## 本地处理

本地 OpenCV 不做文字识别，也不作为图表定位主判断。

OpenCV 只负责：

- 采集阶段把远端 PNG/JPG/WebP 统一解码、缩放并保存为 VLM-ready JPEG
- 读取页面 JPEG；符合约束时直接 Base64 发送给 VLM，不做第二次转码
- 按 VLM bbox 裁图
- 保存 `figures/*.png`

图表、标题、正文的主信号来自 VLM 返回结果：

```text
markdown -> 正文和标题主来源
blocks/bbox -> 图表裁剪主来源
title-band OCR -> 标题缺失时的局部兜底
```

## 兜底路径

只有 unified 结果不完整时才局部 fallback，不再默认每页跑两遍。

fallback 触发条件包括：

- unified 调用失败
- 页面有 chart/table/image block 但 markdown 缺正文
- 图表标题是 `图表 12-1` 这类泛称
- 图片引用和实际 figure 数量不一致
- 图后正文缺失但下一页是续句

fallback 顺序：

```text
unified page JSON
-> page-level markdown OCR fallback
-> title-band OCR fallback
-> deterministic merge / normalize
```

旧的 `recognize_pages_layout()` 和 `recognize_pages_as_markdown()` 保留为兼容 fallback 与测试注入，不再是默认远程主路径。

## 输出产物

每个报告 run 应产出：

- `page_images.json`: 页面图片清单
- `vision_layout.json`: VLM blocks/bbox 快照
- `vision_markdown.json`: VLM markdown 快照
- `figures.json`: 裁图、bbox、title、nearby_text
- `report_structured.json`: parser structured payload
- `parse_status.json`: 状态、warnings、页数、figure 数量
- `raw_article_report.md`: 人可读原文图文版
- `raw_article_report.json`: raw article JSON

图片只保留两个 canonical 位置：

- 页面 JPEG：`~/jin10-reports/<date>/<report_type>/<article_id>/images/page-NNN.jpg`
- 裁剪图：`storage/parsed/jin10/<date>/<article_id>/figures/*.png`

`storage/outputs/jin10` 不复制 `images` 或 `figures`。既有 report-bundle asset URL 保持不变，API 对页面图回源 external source refs，对裁剪图回源 parsed。完整 pipeline 结束后执行 30 天滚动保留；边界日保留，过期时只删除图片，不删除 Markdown、JSON、状态或 lineage。

`raw_article_report.md` 必须满足：

- 保留正文阅读顺序。
- 图表标题以 Markdown 标题文本出现。
- 图片紧跟对应标题。
- 图后正文不能丢失。
- 图表识别失败时显式留空或降级，不编造摘要。

## 状态标记

`parse_status.json` 中重点关注：

- `status`
- `vision_markdown_status`
- `vision_layout_status`
- `figures_total`
- `vision_pages_total`
- `warnings`

常见 warning：

- `vision_unified_page_recognition_primary`: 使用 unified 主路径。
- `vision_markdown_page_ocr_fallback:<pages>`: 指定页触发 markdown OCR 兜底。
- `vision_unified_failed:<reason>`: unified 失败，进入旧 fallback。
- `vision_page_limit_applied:<used>/<total>`: 页数限制生效。

## 验收命令

parser 回归：

```bash
rtk env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/parsers/test_jin10_report_image_parser.py -q
```

相关链路回归：

```bash
rtk env UV_CACHE_DIR=/tmp/uv-cache uv run pytest \
  tests/parsers/test_jin10_report_image_parser.py \
  tests/collectors/test_jin10_adapter.py \
  tests/renderer/test_jin10_agent_analysis_markdown_renderer.py \
  tests/analysis/test_jin10_agent_analysis.py \
  -q
```

日报实跑示例：

```bash
rtk env \
  JIN10_IMAGE_RECOGNITION=vlm \
  JIN10_VISION_PAGE_LIMIT=0 \
  JIN10_VISION_MODEL=gpt-5.6-luna \
  UV_CACHE_DIR=/tmp/uv-cache \
  timeout 600s \
  uv run python scripts/run_daily_report_pipeline.py \
  --date 2026-05-26 \
  --category 270 \
  --article-id 220232 \
  --vision-provider cockpit \
  --vision-model gpt-5.6-luna \
  --vision-reasoning-effort high \
  --analysis-provider cockpit \
  --analysis-model gpt-5.6-sol \
  --analysis-reasoning-effort high \
  --analysis-max-images 25
```

实跑后必须抽查：

- `raw_article_report.md` 中标题、图片、图后正文是否齐全。
- `figures.json` 中 bbox/title 是否合理。
- `parse_status.json` 是否 success，fallback 页是否可解释。

## 已验证样本

### 2026-05-25 / 220100

- 目标：验证多图页、机构动向页、图后正文。
- 结果：标题在 Markdown 文本中，截图只包含图表本体，图后正文恢复。

### 2026-05-26 / 220232

- 目标：验证 unified 一页一次调用。
- 结果：
  - `pages_total=17`
  - `figures_total=3`
  - page 11 三张图表正常裁图
  - `黄金机构动向` / `白银机构动向` 为纯文字“无变化”
  - warning 显示 unified 主路径，局部 fallback 页为 `11,16,17`
