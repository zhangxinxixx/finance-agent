from __future__ import annotations

from apps.analysis.jin10.llm_visual_report import build_visual_report_prompt, parse_visual_report_html


def test_build_visual_report_prompt_mentions_article_and_chart_context() -> None:
    raw_report = {
        "family": "jin10_raw_article",
        "trade_date": "2026-05-06",
        "article_id": "218330",
        "title": "测试标题",
        "source_url": "https://xnews.jin10.com/details/218330",
        "article_markdown": "# 测试标题\n\n正文第一段\n",
        "charts": [
            {
                "seq": 1,
                "title": "图表 1",
                "image_path": "images/chart-1.png",
                "caption": "黄金 4H 走势",
            }
        ],
    }

    prompt = build_visual_report_prompt(raw_report)

    assert "测试标题" in prompt
    assert "正文第一段" in prompt
    assert "黄金 4H 走势" in prompt
    assert "完整 HTML" in prompt


def test_parse_visual_report_html_strips_code_fences() -> None:
    wrapped = """```html
<html><body><h1>测试</h1></body></html>
```"""

    html = parse_visual_report_html(wrapped)

    assert html == "<html><body><h1>测试</h1></body></html>"
