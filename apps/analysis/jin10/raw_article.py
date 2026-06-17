from __future__ import annotations

import re
from pathlib import Path

from apps.documents.schemas import Jin10RawArticleReport, SourceDocument


def build_jin10_raw_article_report(
    document: SourceDocument,
    *,
    charts: list[dict[str, object]] | None = None,
    article_markdown_override: str | None = None,
) -> Jin10RawArticleReport:
    chart_items = charts if charts is not None else _charts_from_page_images(document)
    chart_items = [chart for chart in chart_items if not _is_low_value_chart(chart)]
    article_source = article_markdown_override if article_markdown_override is not None else document.report_text
    article_markdown = _strip_report_images_section(article_source)
    article_markdown = _polish_gold_daily_markdown(article_markdown)
    article_markdown = _drop_unbound_local_figure_refs(article_markdown, chart_items)
    article_markdown = _refill_local_image_slots_by_chart_sequence(article_markdown, chart_items)
    article_markdown = _insert_missing_local_charts_by_sequence(article_markdown, chart_items)
    return Jin10RawArticleReport(
        document_id=document.document_id,
        trade_date=document.trade_date,
        run_id=document.article_id,
        article_id=document.article_id,
        title=document.title,
        family="jin10_raw_article",
        source_url=document.source_url,
        article_markdown=article_markdown,
        charts=chart_items,
        source_refs=document.source_refs,
        generated_from={
            "source": document.source,
            "content_stage": "parsed_markdown",
            "external_report_dir": document.external_report_dir,
            "article_id": document.article_id,
            "article_context": build_raw_article_context(article_markdown, chart_items),
        },
    )


def render_jin10_raw_article_markdown(report: Jin10RawArticleReport) -> str:
    sections = [_normalize_multiline_image_markdown(report.article_markdown.strip())]
    remaining_charts = [
        chart
        for chart in _remaining_charts_for_render(report.article_markdown, report.charts or [])
        if not _is_low_value_chart(chart)
    ]
    if remaining_charts:
        sections.extend(["", "## 图表与页面", ""])
        charts = list(remaining_charts)
        fallback_only = all(_is_page_fallback_chart(chart) for chart in charts)
        visible_charts = charts[:4] if fallback_only and len(charts) > 4 else charts
        for index, chart in enumerate(visible_charts, start=1):
            title = _clean_inline_text(chart.get("title")) or f"图表 {index}"
            caption = _clean_inline_text(chart.get("caption"))
            summary = _clean_inline_text(chart.get("summary"))
            recognized_text = _clean_inline_text(chart.get("recognized_text"))
            sections.append(f"### {title}")
            if caption:
                sections.append("")
                sections.append(f"- 页面说明：{caption}")
            if summary:
                sections.append(f"- 图表要点：{summary}")
            elif recognized_text:
                sections.append(f"- 图中文字：{recognized_text}")
            if chart.get("image_path"):
                rel = _render_chart_image_ref(str(chart["image_path"]))
                sections.append("")
                sections.append(f"![{caption or title}]({rel})")
            sections.append("")
        if fallback_only and len(charts) > len(visible_charts):
            remaining = len(charts) - len(visible_charts)
            sections.append(f"_其余 {remaining} 页报告图已保留在归档资源中，可在 bundle asset 中继续查看。_")
            sections.append("")
    return "\n".join(sections).strip() + "\n"


def _charts_from_page_images(document: SourceDocument) -> list[dict[str, object]]:
    charts: list[dict[str, object]] = []
    for index, asset in enumerate(document.image_assets, start=1):
        file_name = asset.metadata.get("file") or Path(asset.path).name
        charts.append(
            {
                "seq": asset.metadata.get("seq", index),
                "title": f"图表 {index}",
                "image_path": asset.path,
                "caption": file_name,
                "width": asset.metadata.get("width"),
                "height": asset.metadata.get("height"),
            }
        )
    return charts


def _render_chart_image_ref(image_path: str) -> str:
    if image_path.startswith(("http://", "https://")):
        return image_path
    path = Path(image_path)
    return path.name if path.parent.name == "." else f"{path.parent.name}/{path.name}"


def _remaining_charts_for_render(markdown: str, charts: list[dict[str, object]]) -> list[dict[str, object]]:
    embedded_refs = {
        _normalize_chart_ref(match.group(1))
        for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", markdown or "")
    }
    if not embedded_refs:
        return list(charts)

    remaining: list[dict[str, object]] = []
    for chart in charts:
        image_path = str(chart.get("image_path") or "").strip()
        if not image_path:
            remaining.append(chart)
            continue
        chart_ref = _normalize_chart_ref(_render_chart_image_ref(image_path))
        if chart_ref in embedded_refs:
            continue
        remaining.append(chart)
    return remaining


def _normalize_chart_ref(value: str) -> str:
    return str(value or "").strip().lstrip("./").lower()


def _strip_report_images_section(markdown: str) -> str:
    marker = "\n## 报告图片"
    if marker in markdown:
        markdown = markdown.split(marker, 1)[0].rstrip()
    cleaned_lines: list[str] = []
    skip_next_blank = False
    for line in markdown.splitlines():
        text = line.strip()
        if _is_noise_line(text):
            skip_next_blank = True
            continue
        if text.startswith(("### 图表解析", "## 目录")):
            skip_next_blank = True
            continue
        if "图表解析: unavailable" in text or "missing_openai_api_key" in text:
            skip_next_blank = True
            continue
        if skip_next_blank and not text:
            continue
        skip_next_blank = False
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned + "\n"


def _polish_gold_daily_markdown(markdown: str) -> str:
    cleaned = _drop_low_value_sections(markdown)
    cleaned = _normalize_multiline_image_markdown(cleaned)
    cleaned = _reanchor_key_chart_images(cleaned)
    cleaned = _normalize_heading_levels(cleaned)
    cleaned = _normalize_report_title(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned + "\n"


def _normalize_multiline_image_markdown(markdown: str) -> str:
    lines = markdown.splitlines()
    normalized: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped.startswith("![") or "](" in stripped:
            normalized.append(line)
            index += 1
            continue

        alt_parts = [stripped[2:].strip()]
        index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            if "](" in candidate:
                alt_text, rest = candidate.split("](", 1)
                alt_parts.append(alt_text.strip())
                image_path = rest.rstrip().rstrip(")")
                alt = " ".join(part for part in " ".join(alt_parts).split() if part)
                normalized.append(f"![{alt}]({image_path})")
                index += 1
                break
            if candidate:
                alt_parts.append(candidate)
            index += 1
        else:
            normalized.append(line)
    return "\n".join(normalized).strip()


def _drop_unbound_local_figure_refs(markdown: str, charts: list[dict[str, object]]) -> str:
    bound_refs = {
        _normalize_chart_ref(_render_chart_image_ref(str(chart.get("image_path") or "")))
        for chart in charts
        if chart.get("image_path")
    }
    if not bound_refs:
        return markdown
    image_line = re.compile(r"^\s*!\[[^\]]*\]\(([^)]+)\)\s*$")
    output: list[str] = []
    for line in markdown.splitlines():
        match = image_line.match(line)
        if match:
            ref = _normalize_chart_ref(match.group(1))
            if ref.startswith("figures/") and ref not in bound_refs:
                continue
        output.append(line)
    return "\n".join(output).strip() + "\n"


def _refill_local_image_slots_by_chart_sequence(markdown: str, charts: list[dict[str, object]]) -> str:
    if not charts:
        return markdown
    image_line = re.compile(r"^(\s*)!\[[^\]]*\]\(([^)]+)\)\s*$")
    embedded_refs = []
    for line in markdown.splitlines():
        match = image_line.match(line)
        if match:
            ref = _normalize_chart_ref(match.group(2))
            if ref.startswith("figures/"):
                embedded_refs.append(ref)
    if len(embedded_refs) < 2:
        return markdown

    ordered_charts = sorted(
        [
            chart
            for chart in charts
            if _normalize_chart_ref(_render_chart_image_ref(str(chart.get("image_path") or ""))) in set(embedded_refs)
        ],
        key=_chart_sequence_sort_key,
    )
    if len(ordered_charts) != len(embedded_refs):
        return markdown

    replacements = iter(_chart_markdown_image(chart) for chart in ordered_charts)
    output: list[str] = []
    for line in markdown.splitlines():
        match = image_line.match(line)
        if match and _normalize_chart_ref(match.group(2)).startswith("figures/"):
            output.append(f"{match.group(1)}{next(replacements)}")
        else:
            output.append(line)
    return "\n".join(output).strip() + "\n"


def _chart_sequence_sort_key(chart: dict[str, object]) -> tuple[int, int, int]:
    image_path = _render_chart_image_ref(str(chart.get("image_path") or ""))
    figure_key = _chart_image_figure_sort_key(image_path)
    seq = chart.get("seq")
    try:
        seq_value = int(seq) if seq is not None else 10**9
    except (TypeError, ValueError):
        seq_value = 10**9
    return (figure_key[1], figure_key[2], seq_value)


def _chart_markdown_image(chart: dict[str, object]) -> str:
    title = _clean_inline_text(chart.get("caption") or chart.get("title") or chart.get("figure_id") or "图表")
    image_path = _render_chart_image_ref(str(chart.get("image_path") or ""))
    return f"![{title}]({image_path})"


def _clean_inline_text(value: object | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return " ".join(lines)


def _insert_missing_local_charts_by_sequence(markdown: str, charts: list[dict[str, object]]) -> str:
    if not charts:
        return markdown
    image_line = re.compile(r"^(\s*)!\[[^\]]*\]\(([^)]+)\)\s*$")
    lines = markdown.splitlines()
    embedded_refs = {
        _normalize_chart_ref(match.group(2))
        for line in lines
        if (match := image_line.match(line))
    }
    if not embedded_refs:
        return markdown

    ordered_charts = sorted(charts, key=_chart_sequence_sort_key)
    missing_by_prev_ref: dict[str, list[dict[str, object]]] = {}
    previous_ref_by_page: dict[int, str] = {}
    for chart in ordered_charts:
        ref = _normalize_chart_ref(_render_chart_image_ref(str(chart.get("image_path") or "")))
        if not ref:
            continue
        _, page_no, _ = _chart_image_figure_sort_key(ref)
        if page_no >= 10**9:
            continue
        if ref in embedded_refs:
            previous_ref_by_page[page_no] = ref
            continue
        previous_ref = previous_ref_by_page.get(page_no)
        if previous_ref:
            missing_by_prev_ref.setdefault(previous_ref, []).append(chart)
            embedded_refs.add(ref)
            previous_ref_by_page[page_no] = ref

    if not missing_by_prev_ref:
        return markdown

    output: list[str] = []
    for line in lines:
        output.append(line)
        match = image_line.match(line)
        if not match:
            continue
        ref = _normalize_chart_ref(match.group(2))
        for chart in missing_by_prev_ref.get(ref, []):
            if output and output[-1].strip():
                output.append("")
            output.append(f"{match.group(1)}{_chart_markdown_image(chart)}")
    return "\n".join(output).strip() + "\n"


def _drop_low_value_sections(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        heading = _heading_level_and_title(line)
        if heading is None:
            output.append(line)
            index += 1
            continue

        level, title = heading
        next_index = index + 1
        while next_index < len(lines):
            next_heading = _heading_level_and_title(lines[next_index])
            if next_heading is not None and next_heading[0] <= level:
                break
            next_index += 1
        section_lines = lines[index:next_index]
        if _is_low_value_section(title, section_lines):
            index = next_index
            while output and not output[-1].strip():
                output.pop()
            continue
        output.extend(section_lines)
        index = next_index
    return "\n".join(output).strip()


def _is_low_value_section(title: str, section_lines: list[str]) -> bool:
    compact_title = "".join(title.split())
    body = "\n".join(line.strip() for line in section_lines[1:] if line.strip())
    if compact_title == "技术指标":
        image_count = sum(1 for line in section_lines if line.strip().startswith("!["))
        has_generic_fear_greed = "50为中性" in body and "超过70" in body and "低于30" in body
        text_without_images = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", body)
        digit_tokens = re.findall(r"\d+(?:\.\d+)?%?", text_without_images)
        # Keep technical sections only when OCR captured specific indicator values beyond the generic legend.
        return has_generic_fear_greed and image_count <= 4 and set(digit_tokens).issubset({"1", "50", "70", "30", "16", "17"})
    return False


def _reanchor_key_chart_images(markdown: str) -> str:
    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        heading = _heading_level_and_title(lines[index])
        if heading is None or heading[1] != "关键图表":
            output.append(lines[index])
            index += 1
            continue

        level, _ = heading
        section_end = index + 1
        while section_end < len(lines):
            next_heading = _heading_level_and_title(lines[section_end])
            if next_heading is not None and next_heading[0] <= level:
                break
            section_end += 1
        output.extend(_reanchor_key_chart_section(lines[index:section_end], level=level))
        index = section_end
    return "\n".join(output).strip()


def _reanchor_key_chart_section(lines: list[str], *, level: int) -> list[str]:
    if not lines:
        return []
    image_pattern = re.compile(r"!\[[^\]]*\]\([^)]+\)")
    images = _sort_chart_images_by_figure_ref(
        [line.strip() for line in lines if image_pattern.fullmatch(line.strip())]
    )
    remaining_images = list(images)
    output: list[str] = [lines[0]]
    pending_blank = False

    for line in lines[1:]:
        stripped = line.strip()
        if image_pattern.fullmatch(stripped):
            pending_blank = True
            continue
        heading = _heading_level_and_title(line)
        if heading is not None and heading[0] > level:
            if output and output[-1].strip():
                output.append("")
            output.append(line)
            matched = _pop_matching_chart_image(heading[1], remaining_images)
            if matched is None and remaining_images:
                matched = remaining_images.pop(0)
            if matched:
                output.extend(["", matched])
            pending_blank = False
            continue
        if pending_blank and stripped and output and output[-1].strip():
            output.append("")
        output.append(line)
        pending_blank = False

    if remaining_images:
        if output and output[-1].strip():
            output.append("")
        output.extend(remaining_images)
    return output


def _sort_chart_images_by_figure_ref(images: list[str]) -> list[str]:
    return [
        image
        for _, image in sorted(
            enumerate(images),
            key=lambda item: (*_chart_image_figure_sort_key(item[1]), item[0]),
        )
    ]


def _chart_image_figure_sort_key(image_markdown: str) -> tuple[int, int, int]:
    match = re.search(r"fig_p(\d+)_(\d+)\.", image_markdown)
    if not match:
        return (1, 10**9, 10**9)
    return (0, int(match.group(1)), int(match.group(2)))


def _pop_matching_chart_image(title: str, images: list[str]) -> str | None:
    if not images:
        return None
    scores = [(_chart_image_match_score(title, image), index, image) for index, image in enumerate(images)]
    score, index, image = max(scores, key=lambda item: item[0])
    if score <= 0:
        return None
    images.pop(index)
    return image


def _chart_image_match_score(title: str, image_markdown: str) -> int:
    compact_title = "".join(title.lower().split())
    compact_image = "".join(image_markdown.lower().split())
    image_alt_match = re.search(r"!\[([^\]]*)\]", image_markdown)
    compact_alt = "".join((image_alt_match.group(1) if image_alt_match else "").lower().split())
    score = 0
    if compact_alt and (compact_alt == compact_title or compact_alt in compact_title or compact_title in compact_alt):
        score += 20
    if any(token in compact_title for token in ("收益率", "10年期", "美债")):
        if "fig_p11_001" in compact_image or "图表11-1" in compact_image:
            score += 10
    if any(token in compact_title for token in ("隐含波动率", "波动率", "gvz")):
        if "fig_p11_002" in compact_image or "gvz" in compact_image or "波动率" in compact_image:
            score += 10
    if any(token in compact_title for token in ("美伊", "和平协议", "概率")):
        if "fig_p11_003" in compact_image or "图表11-3" in compact_image or "协议" in compact_image:
            score += 10
    return score


def _normalize_heading_levels(markdown: str) -> str:
    lines = markdown.splitlines()
    seen_h1 = False
    normalized: list[str] = []
    for line in lines:
        heading = _heading_level_and_title(line)
        if heading is None:
            normalized.append(line)
            continue
        level, title = heading
        if not seen_h1:
            seen_h1 = True
            normalized.append(f"# {title}")
            continue
        normalized.append(f"{'#' * min(level + 1, 6)} {title}")
    return "\n".join(normalized).strip()


def _normalize_report_title(markdown: str) -> str:
    lines = markdown.splitlines()
    if not lines:
        return markdown
    heading = _heading_level_and_title(lines[0])
    if heading is None:
        return markdown
    title = re.sub(r"-金十数据VIP\s*$", "", heading[1]).strip()
    lines[0] = f"# {title}"
    return "\n".join(lines).strip()


def _heading_level_and_title(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def _is_noise_line(text: str) -> bool:
    compact = "".join(str(text).split()).lower()
    if not compact:
        return False
    if compact in {"仓报告", "-仓报告"}:
        return True
    noise_tokens = (
        "金十vip专享",
        "欢迎点击查看",
        "更多金银信号和消息汇总",
        "来看今天最新的金银报告",
        "vip专属报告系列",
        "金十数据research",
        "每日金银报告",
        "每日原油报告",
        "每日外汇报告",
        "每日市场观察",
        "技术刘pro",
        "黄金投资者周报",
    )
    return any(token in compact for token in noise_tokens)


def _is_page_fallback_chart(chart: dict[str, object]) -> bool:
    title = str(chart.get("title") or "").strip()
    caption = str(chart.get("caption") or "").strip()
    return title.startswith("第") and title.endswith("页报告图") and caption == title


def _is_low_value_chart(chart: dict[str, object]) -> bool:
    text = " ".join(
        str(chart.get(key) or "")
        for key in ("title", "caption", "summary", "recognized_text")
    )
    compact = "".join(text.split())
    noise_tokens = (
        "二维码",
        "扫码",
        "关注公众号",
        "下载app",
        "金十数据app",
        "广告",
        "每日原油报告",
        "每日外汇报告",
        "每日市场观察",
        "技术刘pro",
        "黄金投资者周报",
    )
    if any(token in compact.lower() for token in noise_tokens):
        return True
    if "恐惧贪婪指标" in compact:
        return True
    if compact in {"图表16-1", "图表17-1"}:
        return True
    bbox = chart.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        try:
            x1, y1, x2, y2 = [float(value) for value in bbox]
        except (TypeError, ValueError):
            pass
        else:
            width = max(0.0, x2 - x1)
            height = max(0.0, y2 - y1)
            title = str(chart.get("title") or chart.get("caption") or "").strip()
            if height > 0 and width / height >= 4.5 and re.fullmatch(r"图表\s*\d+-\d+", title):
                return True
    if "50为中性" in compact and "超过70" in compact and "低于30" in compact:
        return True
    return False


def _chart_render_mode(charts: list[dict[str, object]]) -> str:
    if not charts:
        return "none"
    if all(_is_page_fallback_chart(chart) for chart in charts):
        return "fallback_compact" if len(charts) > 4 else "fallback_full"
    return "structured"


def build_raw_article_context(markdown: str, charts: list[dict[str, object]]) -> dict[str, object]:
    body = str(markdown or "").strip()
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    paragraphs = [line for line in lines if not line.startswith("#") and not line.startswith("- ")]
    paragraph_snippets = paragraphs[:8]
    chart_summaries = []
    for chart in charts:
        summary_parts = []
        title = str(chart.get("title") or "").strip()
        caption = str(chart.get("caption") or "").strip()
        text = str(chart.get("recognized_text") or "").strip()
        summary = str(chart.get("summary") or "").strip()
        if title:
            summary_parts.append(f"title={title}")
        if caption:
            summary_parts.append(f"caption={caption}")
        if text:
            summary_parts.append(f"text={text}")
        if summary:
            summary_parts.append(f"summary={summary}")
        if summary_parts:
            chart_summaries.append("; ".join(summary_parts))
    key_sentences = _extract_key_sentences(paragraphs)
    sections = _extract_sections(lines)
    chart_anchors = _extract_chart_anchors(lines, charts)
    level_snippets = _extract_level_snippets(paragraphs)
    return {
        "paragraph_snippets": paragraph_snippets,
        "key_sentences": key_sentences,
        "sections": sections[:12],
        "chart_anchors": chart_anchors[:12],
        "level_snippets": level_snippets[:12],
        "chart_summaries": chart_summaries[:12],
        "chart_count": len(charts),
        "chart_render_mode": _chart_render_mode(charts),
    }


def _extract_key_sentences(paragraphs: list[str]) -> list[str]:
    keys = []
    pattern = re.compile(r"(行情回顾|关键指标|观点分享|文章导读|关键位|总结|风险)", re.I)
    for paragraph in paragraphs:
        if pattern.search(paragraph):
            keys.append(paragraph)
    if keys:
        return keys[:8]
    return paragraphs[:5]


def _extract_sections(lines: list[str]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    current_heading = "正文"
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        text = " ".join(buffer).strip()
        if not text:
            buffer.clear()
            return
        sections.append(
            {
                "heading": current_heading,
                "summary": text[:320],
                "paragraph_count": len(buffer),
            }
        )
        buffer.clear()

    for line in lines:
        if line.startswith("#"):
            flush()
            current_heading = line.lstrip("#").strip() or "正文"
            continue
        if line.startswith("!["):
            continue
        buffer.append(line)
    flush()
    return sections


def _extract_chart_anchors(lines: list[str], charts: list[dict[str, object]]) -> list[dict[str, object]]:
    anchors: list[dict[str, object]] = []
    image_lines = [line for line in lines if line.startswith("![") and "](" in line]
    for index, image_line in enumerate(image_lines):
        prev_line = ""
        next_line = ""
        line_index = lines.index(image_line)
        for candidate in reversed(lines[:line_index]):
            if not candidate.startswith("!["):
                prev_line = candidate
                break
        for candidate in lines[line_index + 1 :]:
            if not candidate.startswith("!["):
                next_line = candidate
                break
        chart = charts[index] if index < len(charts) else {}
        anchors.append(
            {
                "title": str(chart.get("title") or "").strip() or _image_alt_text(image_line),
                "image_path": _image_markdown_path(image_line),
                "before": prev_line[:220],
                "after": next_line[:220],
                "summary": str(chart.get("summary") or "").strip(),
            }
        )
    return anchors


def _extract_level_snippets(paragraphs: list[str]) -> list[str]:
    pattern = re.compile(r"(美元|收益率|支撑|阻力|关键位|跌破|站回|收复|目标|区间|最大痛点|OI|Put/Call|看涨期权|看跌期权)")
    return [paragraph[:240] for paragraph in paragraphs if pattern.search(paragraph)]


def _image_alt_text(markdown_line: str) -> str:
    match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", markdown_line)
    return (match.group(1) if match else "").strip()


def _image_markdown_path(markdown_line: str) -> str:
    match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", markdown_line)
    return (match.group(2) if match else "").strip()
