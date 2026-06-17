"""Prompt helpers for Jin10 raw-article to visual HTML post-processing."""

from __future__ import annotations


def build_visual_report_prompt(raw_report: dict) -> str:
    charts = raw_report.get("charts", [])
    chart_lines = []
    for chart in charts:
        chart_lines.append(
            f"- 图表 {chart.get('seq')}: caption={chart.get('caption') or 'N/A'} image_path={chart.get('image_path')}"
        )
    chart_block = "\n".join(chart_lines) if chart_lines else "- 无图表"
    return f"""你是一位专业黄金市场编辑与可视化报告设计师。
请基于以下 Jin10 黄金日报原始材料，输出一份可直接保存为 `.html` 的完整 HTML 文档。

硬性要求：
1. 只输出完整 HTML，不要 Markdown，不要 JSON，不要解释。
2. 页面语言为简体中文，内容必须忠实于原始文章，不编造额外市场结论。
3. 页面必须包含：标题区、文章原文摘要区、图表区、来源区、风险提示区。
4. 图表区必须逐张引用给定图片路径，使用 `<img src=\"...\">`，不要丢图。
5. 视觉风格偏金融研究简报，强调可读性，不要做花哨动效。

=== 基本信息 ===
trade_date: {raw_report.get('trade_date', '')}
article_id: {raw_report.get('article_id', '')}
title: {raw_report.get('title', '')}
source_url: {raw_report.get('source_url', '')}

=== 原始文章 Markdown ===
{raw_report.get('article_markdown', '').strip()}

=== 图表清单 ===
{chart_block}

请输出完整 HTML。"""


def parse_visual_report_html(text: str) -> str:
    html = text.strip()
    if html.startswith("```"):
        lines = html.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        html = "\n".join(lines).strip()
    return html
