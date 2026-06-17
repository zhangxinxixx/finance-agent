from apps.analysis.jin10.raw_article import build_jin10_raw_article_report, render_jin10_raw_article_markdown
from apps.documents.schemas import SourceAssetRef, SourceDocument


def _document_with_charts() -> SourceDocument:
    return SourceDocument(
        document_id="jin10-2026-05-26-220232",
        source="jin10_external",
        trade_date="2026-05-26",
        title="测试图文渲染",
        category="金银报告",
        category_code="270",
        source_url="https://svip.jin10.com/news/220232",
        article_id="220232",
        external_report_dir="/tmp/jin10-220232",
        retrieved_at="2026-05-26T00:00:00+00:00",
        markdown_asset=SourceAssetRef(asset_type="report_md", path="/tmp/report.md", sha256="", size_bytes=0),
        meta_asset=SourceAssetRef(asset_type="meta_json", path="/tmp/meta.json", sha256="", size_bytes=0),
        image_assets=[],
        report_text="""# 测试图文渲染

1、行情回顾：黄金维持震荡。
2、关键位：上方关注3360，下方关注3300。
""",
        source_refs=[],
    )


def test_render_raw_article_markdown_groups_chart_sections_with_summary() -> None:
    report = build_jin10_raw_article_report(
        _document_with_charts(),
        charts=[
            {
                "title": "图表 1",
                "caption": "15分钟走势截图",
                "summary": "价格在3340附近反复测试后企稳。",
                "image_path": "figures/chart-1.png",
            },
            {
                "title": "图表 2",
                "caption": "指标面板",
                "recognized_text": "RSI 48.2, MACD靠近零轴",
                "image_path": "figures/chart-2.png",
            },
        ],
    )

    markdown = render_jin10_raw_article_markdown(report)

    assert "## 图表与页面" in markdown
    assert "### 图表 1" in markdown
    assert "- 页面说明：15分钟走势截图" in markdown
    assert "- 图表要点：价格在3340附近反复测试后企稳。" in markdown
    assert "![15分钟走势截图](figures/chart-1.png)" in markdown
    assert "- 图中文字：RSI 48.2, MACD靠近零轴" in markdown
    assert "![指标面板](figures/chart-2.png)" in markdown
    assert "图表解析: unavailable" not in markdown
    assert "missing_openai_api_key" not in markdown


def test_render_raw_article_markdown_appends_missing_charts_when_body_already_has_some_images() -> None:
    document = _document_with_charts()
    document.report_text = """# 测试图文渲染

正文。

![已有图片](figures/chart-1.png)
"""
    report = build_jin10_raw_article_report(
        document,
        charts=[
            {"title": "图表 1", "caption": "截图 1", "image_path": "figures/chart-1.png"},
            {"title": "图表 2", "caption": "截图 2", "image_path": "figures/chart-2.png"},
        ],
    )

    markdown = render_jin10_raw_article_markdown(report)

    assert markdown.count("![") == 2
    assert markdown.count("![已有图片](figures/chart-1.png)") == 1
    assert "## 图表与页面" in markdown
    assert "![截图 2](figures/chart-2.png)" in markdown


def test_render_raw_article_markdown_keeps_remote_chart_urls() -> None:
    report = build_jin10_raw_article_report(
        _document_with_charts(),
        charts=[
            {
                "title": "图表 1",
                "caption": "远程图",
                "image_path": "https://cdn-news.jin10.com/chart.png",
            }
        ],
    )

    markdown = render_jin10_raw_article_markdown(report)

    assert "![远程图](https://cdn-news.jin10.com/chart.png)" in markdown


def test_build_raw_article_report_collapses_multiline_image_markdown() -> None:
    document = _document_with_charts()
    document.report_text = """# 测试图文渲染

![COMEX GOLD OPTIONS: Put/Call Volume Ratio
Put-Volume (30d EMA) / Call-Volume (30d EMA)
May 22, 2026](figures/fig_p8_001.png)
"""

    report = build_jin10_raw_article_report(document, charts=[])

    assert "![COMEX GOLD OPTIONS: Put/Call Volume Ratio Put-Volume (30d EMA) / Call-Volume (30d EMA) May 22, 2026](figures/fig_p8_001.png)" in report.article_markdown
    assert "Put-Volume (30d EMA) / Call-Volume (30d EMA)\nMay 22, 2026](figures/fig_p8_001.png)" not in report.article_markdown


def test_render_raw_article_markdown_collapses_multiline_chart_titles_to_single_line() -> None:
    report = build_jin10_raw_article_report(
        _document_with_charts(),
        charts=[
            {
                "title": "COMEX GOLD OPTIONS: Put/Call Volume Ratio\nPut-Volume (30d EMA) / Call-Volume (30d EMA)\nMay 22, 2026",
                "caption": "COMEX GOLD OPTIONS: Put/Call Volume Ratio\nPut-Volume (30d EMA) / Call-Volume (30d EMA)\nMay 22, 2026",
                "summary": "看跌/看涨比率进入关键区间",
                "image_path": "figures/fig_p8_001.png",
            }
        ],
    )

    markdown = render_jin10_raw_article_markdown(report)

    assert "![COMEX GOLD OPTIONS: Put/Call Volume Ratio Put-Volume (30d EMA) / Call-Volume (30d EMA) May 22, 2026](figures/fig_p8_001.png)" in markdown
    assert "### COMEX GOLD OPTIONS: Put/Call Volume Ratio Put-Volume (30d EMA) / Call-Volume (30d EMA) May 22, 2026" in markdown


def test_build_raw_article_report_strips_directory_vip_and_brand_noise() -> None:
    document = _document_with_charts()
    document.report_text = """# 测试图文渲染

## 目录

VIP专属报告系列

金十数据 Research

每日 金银报告

1、行情回顾：黄金维持震荡。
2、关键位：上方关注3360，下方关注3300。
"""

    report = build_jin10_raw_article_report(document, charts=[])

    assert "行情回顾：黄金维持震荡。" in report.article_markdown
    assert "关键位：上方关注3360，下方关注3300。" in report.article_markdown
    assert "## 目录" not in report.article_markdown
    assert "VIP专属报告系列" not in report.article_markdown
    assert "金十数据 Research" not in report.article_markdown
    assert "每日 金银报告" not in report.article_markdown


def test_render_raw_article_markdown_compacts_many_fallback_page_images() -> None:
    report = build_jin10_raw_article_report(
        _document_with_charts(),
        charts=[
            {
                "title": f"第{index}页报告图",
                "caption": f"第{index}页报告图",
                "image_path": f"images/page-{index}.png",
            }
            for index in range(1, 8)
        ],
    )

    markdown = render_jin10_raw_article_markdown(report)

    assert "### 第1页报告图" in markdown
    assert "### 第4页报告图" in markdown
    assert "### 第5页报告图" not in markdown
    assert "其余 3 页报告图已保留在归档资源中" in markdown


def test_build_raw_article_context_marks_compacted_fallback_pages() -> None:
    report = build_jin10_raw_article_report(
        _document_with_charts(),
        charts=[
            {
                "title": f"第{index}页报告图",
                "caption": f"第{index}页报告图",
                "image_path": f"images/page-{index}.png",
            }
            for index in range(1, 8)
        ],
    )

    context = report.generated_from["article_context"]

    assert context["chart_count"] == 7
    assert context["chart_render_mode"] == "fallback_compact"


def test_raw_article_markdown_drops_low_value_fear_greed_without_values() -> None:
    document = _document_with_charts()
    document.report_text = """# 黄金报告-金十数据VIP

# 关键图表

![黄金 ETF 波动率指数](figures/fig_p11_002.png)

## 10年期美债收益率回落

正文说明。

# 技术指标

![恐惧贪婪指标（1日）](figures/fig_p16_002.png)

## 国际现货黄金

### 恐惧贪婪指标（1小时）

![图表 16-1](figures/fig_p16_001.png)

### 恐惧贪婪指标（1日）

说明：50为中性，数值越高说明市场越贪婪，超过70后需小心下跌风险；数值越低则表明市场越恐惧，低于30则需小心反弹风险。

# 黄金机构动向

## 无变化
"""

    report = build_jin10_raw_article_report(document, charts=[])

    assert "# 黄金报告" in report.article_markdown
    assert "10年期美债收益率回落" in report.article_markdown
    assert "恐惧贪婪指标" not in report.article_markdown
    assert "黄金机构动向" in report.article_markdown
    assert "无变化" in report.article_markdown
    assert "金十数据VIP" not in report.article_markdown


def test_build_raw_article_report_filters_low_value_fear_greed_charts_from_json() -> None:
    report = build_jin10_raw_article_report(
        _document_with_charts(),
        charts=[
            {
                "title": "恐惧贪婪指标（1小时）",
                "caption": "图表 16-1",
                "image_path": "figures/fig_p16_001.png",
            },
            {
                "title": "10年期美债收益率回落",
                "caption": "图表 11-1",
                "image_path": "figures/fig_p11_001.png",
            },
        ],
    )

    assert [chart["image_path"] for chart in report.charts] == ["figures/fig_p11_001.png"]
    assert report.generated_from["article_context"]["chart_count"] == 1
    assert "fig_p16_001.png" not in str(report.generated_from["article_context"])


def test_raw_article_markdown_drops_unbound_local_figure_refs() -> None:
    document = _document_with_charts()
    document.report_text = """# 黄金报告

正文一。

![孤儿图](figures/fig_p5_001.png)

## 关键图表

![绑定图](figures/fig_p11_001.png)
"""

    report = build_jin10_raw_article_report(
        document,
        charts=[{"title": "图表 11-1", "image_path": "figures/fig_p11_001.png"}],
    )

    assert "fig_p5_001.png" not in report.article_markdown
    assert "fig_p11_001.png" in report.article_markdown


def test_key_chart_images_are_reanchored_by_figure_sequence_when_vlm_order_is_wrong() -> None:
    document = _document_with_charts()
    document.report_text = """# 黄金报告

# 关键图表

![美国5月1年期通胀预期终值上升](figures/fig_p12_002.png)

## 美国密歇根大学消费者信心指数终值再创新低

![图表 12-1](figures/fig_p12_001.png)

## 美国5月1年期通胀预期终值上升

## 市场对美联储加息的预期提前至今年12月

![市场对美联储加息的预期提前至今年12月](figures/fig_p12_003.png)
"""

    report = build_jin10_raw_article_report(
        document,
        charts=[
            {"title": "美国密歇根大学消费者信心指数终值再创新低", "image_path": "figures/fig_p12_001.png"},
            {"title": "美国5月1年期通胀预期终值上升", "image_path": "figures/fig_p12_002.png"},
            {"title": "市场对美联储加息的预期提前至今年12月", "image_path": "figures/fig_p12_003.png"},
        ],
    )

    markdown = report.article_markdown

    first_heading = markdown.index("美国密歇根大学消费者信心指数终值再创新低")
    first_image = markdown.index("fig_p12_001.png")
    second_heading = markdown.index("美国5月1年期通胀预期终值上升", first_image)
    second_image = markdown.index("fig_p12_002.png", second_heading)
    third_heading = markdown.index("市场对美联储加息的预期提前至今年12月")
    third_image = markdown.index("fig_p12_003.png")
    assert first_heading < first_image < second_heading < second_image < third_heading < third_image


def test_markdown_image_slots_are_refilled_by_figure_sequence_outside_key_chart_section() -> None:
    document = _document_with_charts()
    document.report_text = """# 黄金周报

## 黄金

![第二张图](figures/fig_p2_002.png)

正文说明图1和图2。

![第一张图](figures/fig_p2_001.png)

## 白银

![第二张白银图](figures/fig_p13_002.png)

白银正文。

![第一张白银图](figures/fig_p13_001.png)
"""

    report = build_jin10_raw_article_report(
        document,
        charts=[
            {"title": "图表 2-1", "image_path": "figures/fig_p2_001.png"},
            {"title": "图表 2-2", "image_path": "figures/fig_p2_002.png"},
            {"title": "图表 13-1", "image_path": "figures/fig_p13_001.png"},
            {"title": "图表 13-2", "image_path": "figures/fig_p13_002.png"},
        ],
    )

    markdown = report.article_markdown

    assert markdown.index("fig_p2_001.png") < markdown.index("fig_p2_002.png")
    assert markdown.index("fig_p13_001.png") < markdown.index("fig_p13_002.png")


def test_missing_same_page_chart_is_inserted_after_previous_page_chart() -> None:
    document = _document_with_charts()
    document.report_text = """# 黄金周报

## 黄金

![第一张图](figures/fig_p7_001.png)

正文继续解释同页第二张图。
"""

    report = build_jin10_raw_article_report(
        document,
        charts=[
            {"title": "图表 7-1", "image_path": "figures/fig_p7_001.png"},
            {"title": "图表 7-2", "image_path": "figures/fig_p7_002.png"},
        ],
    )

    markdown = report.article_markdown

    assert markdown.index("fig_p7_001.png") < markdown.index("fig_p7_002.png")
    assert "fig_p7_002.png" in markdown


def test_generic_wide_text_banner_chart_is_filtered() -> None:
    report = build_jin10_raw_article_report(
        _document_with_charts(),
        charts=[
            {
                "title": "图表 20-1",
                "image_path": "figures/fig_p20_001.png",
                "bbox": [60, 945, 2146, 1263],
            },
            {
                "title": "COMEX 黄金持仓",
                "image_path": "figures/fig_p17_001.png",
                "bbox": [246, 1204, 1905, 3003],
            },
        ],
    )

    assert [chart["image_path"] for chart in report.charts] == ["figures/fig_p17_001.png"]


def test_raw_article_markdown_drops_report_product_menu_noise() -> None:
    document = _document_with_charts()
    document.report_text = """# 黄金ETF资金观望等待催化剂

正文说明。

- 每日原油报告
- 每日外汇报告
- 每日市场观察
- 技术刘PRO
- 仓报告
- 黄金投资者周报

## 关键图表

正文继续。
"""

    report = build_jin10_raw_article_report(document, charts=[])

    assert "正文说明" in report.article_markdown
    assert "关键图表" in report.article_markdown
    assert "每日原油报告" not in report.article_markdown
    assert "每日外汇报告" not in report.article_markdown
    assert "每日市场观察" not in report.article_markdown
    assert "技术刘PRO" not in report.article_markdown
    assert "黄金投资者周报" not in report.article_markdown


def test_qr_and_ad_charts_are_filtered_from_raw_article_json() -> None:
    report = build_jin10_raw_article_report(
        _document_with_charts(),
        charts=[
            {
                "title": "扫码关注二维码",
                "caption": "金十数据APP",
                "image_path": "figures/fig_p1_001.png",
            },
            {
                "title": "每日原油报告广告",
                "caption": "下载APP查看更多",
                "image_path": "figures/fig_p1_002.png",
            },
            {
                "title": "10年期美债收益率回落",
                "caption": "图表 11-1",
                "image_path": "figures/fig_p11_001.png",
            },
        ],
    )

    assert [chart["image_path"] for chart in report.charts] == ["figures/fig_p11_001.png"]
