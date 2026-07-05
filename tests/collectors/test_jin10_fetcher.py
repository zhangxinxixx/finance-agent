from __future__ import annotations

import json
from dataclasses import dataclass

from apps.collectors.jin10.fetcher import parse_category_entries, parse_svip_report_html, write_external_report


@dataclass
class _FakeResponse:
    content: bytes

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, payloads: dict[str, bytes]):
        self.payloads = payloads

    def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        return _FakeResponse(self.payloads[url])


def test_parse_category_entries_extracts_ids_titles_and_urls():
    html = """
    <a href="/details/219824">最新金银报告</a>
    <p>摘要一段</p>
    <span>2026-05-22 08:00</span>
    <a href="https://xnews.jin10.com/details/219800">更早报告</a>
    """
    entries = parse_category_entries(html)
    assert entries[0].article_id == "219824"
    assert entries[0].title == "最新金银报告"
    assert entries[0].source_url == "https://xnews.jin10.com/details/219824"
    assert entries[0].published_at == "2026-05-22 08:00"


def test_parse_svip_report_html_builds_markdown_with_images():
    html = """
    <html><head>
      <meta property="og:title" content="黄金日报标题" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body">
        <p>金十VIP专享每日金银报告，欢迎点击查看！</p>
        <p>1、行情回顾：现货黄金报4557.55美元/盎司。</p>
        <p>2、关键指标：美国非制造业PMI维持在50荣枯线上方。</p>
        <p><img src="https://cdn-news.jin10.com/header.png" /></p>
        <p><img src="https://img.jin10.com/news/26/05/report-1.jpg" /></p>
      </div>
      <div class="related"><p>推荐阅读</p><img src="https://cdn.jin10.com/noise.png" /></div>
    </body></html>
    """
    report = parse_svip_report_html(html, article_id="219824", source_url="https://svip.jin10.com/news/219824")
    assert report.article_id == "219824"
    assert report.date
    assert report.report_type == "daily"  # HTML 含有 "金银报告" → daily
    assert "黄金日报标题" in report.report_markdown
    assert "行情回顾" in report.report_markdown
    assert "推荐阅读" not in report.report_markdown
    assert report.image_urls == [
        "https://cdn-news.jin10.com/header.png",
        "https://img.jin10.com/news/26/05/report-1.jpg",
    ]


def test_parse_svip_report_html_classifies_market_observation_report():
    html = """
    <html><head>
      <meta property="og:title" content="VIP每日市场观察：市场赔率表提示降息预期升温" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body">
        <p>VIP智库每日市场观察，市场赔率表显示降息概率上行。</p>
      </div>
    </body></html>
    """

    report = parse_svip_report_html(html, article_id="224000", source_url="https://svip.jin10.com/news/224000")

    assert report.report_type == "market_observation"
    assert report.category == "市场观察"
    assert "- 分类: 市场观察" in report.report_markdown


def test_parse_svip_report_html_drops_first_title_and_last_disclaimer_images_when_enough_pages():
    html = """
    <html><body>
      <div class="jin10vip-news-details-article-body">
        <p><img src="https://img.jin10.com/news/title-page.png" /></p>
        <p><img src="https://img.jin10.com/news/chart-1.jpg" /></p>
        <p><img src="https://img.jin10.com/news/chart-2.jpg" /></p>
        <p><img src="https://img.jin10.com/news/disclaimer-page.png" /></p>
      </div>
    </body></html>
    """
    report = parse_svip_report_html(html, article_id="219900", source_url="https://svip.jin10.com/news/219900")

    assert report.image_urls == [
        "https://img.jin10.com/news/chart-1.jpg",
        "https://img.jin10.com/news/chart-2.jpg",
    ]


def test_parse_svip_report_html_prefers_non_empty_article_body_when_ssr_has_empty_placeholder():
    html = """
    <html><head>
      <meta property="og:title" content="黄金日报标题" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body"></div>
      <div class="jin10vip-news-details-article-body" style="position: relative;">
        <p>1、行情回顾：黄金跳空高开。</p>
        <p><img src="https://cdn-news.jin10.com/cover.png" /></p>
        <p><img src="https://img.jin10.com/news/26/05/page-1.jpg" /></p>
        <p><img src="https://img.jin10.com/news/26/05/page-2.jpg" /></p>
        <p><img src="https://img.jin10.com/news/26/05/page-3.jpg" /></p>
        <p><img src="https://img.jin10.com/news/26/05/page-4.jpg" /></p>
        <p><img src="https://img.jin10.com/news/26/05/tail.jpg" /></p>
      </div>
      <div class="related"><img src="https://img.jin10.com/news/26/05/noise.jpg" /></div>
    </body></html>
    """

    report = parse_svip_report_html(html, article_id="220232", source_url="https://svip.jin10.com/news/220232")

    assert "黄金跳空高开" in report.report_markdown
    assert report.image_urls == [
        "https://img.jin10.com/news/26/05/page-1.jpg",
        "https://img.jin10.com/news/26/05/page-2.jpg",
        "https://img.jin10.com/news/26/05/page-3.jpg",
        "https://img.jin10.com/news/26/05/page-4.jpg",
    ]


def test_parse_svip_report_html_prefers_image_only_article_body_over_reduced_preview():
    html = r"""
    <html><head>
      <meta property="og:title" content="黄金日线底部确认，上涨窗口锁定6月至7月-金十数据VIP" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body" style="position: relative;">
        <p><img src="https://cdn-news.jin10.com/weekly-cover.png" /></p>
        <p>金十VIP专享黄金投资者周报，欢迎查看！</p>
        <p><img src="https://img.jin10.com/news/26/05/weekly-page-1.jpg" /></p>
        <p><img src="https://img.jin10.com/news/26/05/weekly-page-2.jpg" /></p>
        <p><img src="https://img.jin10.com/news/26/05/weekly-page-3.jpg" /></p>
        <p><img src="https://img.jin10.com/news/26/05/weekly-page-4.jpg" /></p>
        <p><img src="https://img.jin10.com/news/26/05/weekly-tail.jpg" /></p>
      </div>
      <script>
        window.__NUXT__={reduced_content:"\u003Cp\u003E往期报告：\u003C\u002Fp\u003E\n\u003Cp\u003E期权市场发出信号！黄金反转契机已现（05.24）\u003C\u002Fp\u003E\n\u003Cp\u003E\u003Cimg src=\"https:\u002F\u002Fcdn-news.jin10.com\u002Fpreview.png\"\u003E\u003C\u002Fp\u003E",audio_url:""};
      </script>
    </body></html>
    """

    report = parse_svip_report_html(html, article_id="220787", source_url="https://svip.jin10.com/news/220787")

    assert "往期报告" not in report.report_markdown
    assert report.image_urls == [
        "https://img.jin10.com/news/26/05/weekly-page-1.jpg",
        "https://img.jin10.com/news/26/05/weekly-page-2.jpg",
        "https://img.jin10.com/news/26/05/weekly-page-3.jpg",
        "https://img.jin10.com/news/26/05/weekly-page-4.jpg",
    ]


def test_write_external_report_writes_meta_and_markdown(tmp_path):
    report = parse_svip_report_html(
        """
        <html><head><title>测试报告</title></head><body><div>2026-05-22</div><p>正文内容</p></body></html>
        """,
        article_id="219824",
        source_url="https://svip.jin10.com/news/219824",
    )
    report_dir = write_external_report(report, external_root=tmp_path)
    assert (report_dir / "report.md").exists()
    assert (report_dir / "meta.json").exists()
    meta = json.loads((report_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["id"] == "219824"


def test_write_external_report_downloads_images_and_rewrites_markdown_to_local_paths(tmp_path):
    report = parse_svip_report_html(
        """
        <html><head><title>测试报告</title></head><body>
        <div>2026-05-22</div>
        <div class="jin10vip-news-details-article-body">
          <p>正文内容</p>
          <p><img src="https://img.jin10.com/news/26/05/report-1.jpg" /></p>
          <p><img src="https://img.jin10.com/news/26/05/report-2.png" /></p>
        </div>
        </body></html>
        """,
        article_id="219824",
        source_url="https://svip.jin10.com/news/219824",
    )
    client = _FakeClient(
        {
            "https://img.jin10.com/news/26/05/report-1.jpg": b"image-one",
            "https://img.jin10.com/news/26/05/report-2.png": b"image-two",
        }
    )

    report_dir = write_external_report(report, external_root=tmp_path, client=client)

    markdown = (report_dir / "report.md").read_text(encoding="utf-8")
    meta = json.loads((report_dir / "meta.json").read_text(encoding="utf-8"))
    assert "![01-report-1.jpg](images/01-report-1.jpg)" in markdown
    assert "![02-report-2.png](images/02-report-2.png)" in markdown
    assert (report_dir / "images" / "01-report-1.jpg").read_bytes() == b"image-one"
    assert (report_dir / "images" / "02-report-2.png").read_bytes() == b"image-two"
    assert meta["images"] == [
        {
            "seq": 1,
            "file": "01-report-1.jpg",
            "url": "https://img.jin10.com/news/26/05/report-1.jpg",
            "path": str(report_dir / "images" / "01-report-1.jpg"),
        },
        {
            "seq": 2,
            "file": "02-report-2.png",
            "url": "https://img.jin10.com/news/26/05/report-2.png",
            "path": str(report_dir / "images" / "02-report-2.png"),
        },
    ]


def test_write_external_report_appends_chart_insights_to_markdown(tmp_path):
    report = parse_svip_report_html(
        """
        <html><head><title>测试报告</title></head><body>
        <div class="jin10vip-news-details-article-body">
          <p>正文内容</p>
          <p><img src="https://img.jin10.com/news/26/05/report-1.jpg" /></p>
          <p><img src="https://img.jin10.com/news/26/05/report-2.png" /></p>
        </div>
        </body></html>
        """,
        article_id="219824",
        source_url="https://svip.jin10.com/news/219824",
    )
    client = _FakeClient(
        {
            "https://img.jin10.com/news/26/05/report-1.jpg": b"image-one",
            "https://img.jin10.com/news/26/05/report-2.png": b"image-two",
        }
    )
    image_insights = [
        {"seq": 1, "file": "01-report-1.jpg", "status": "ok", "text": "黄金周线图", "summary": "价格在关键支撑附近震荡。"},
        {"seq": 2, "file": "02-report-2.png", "status": "ok", "text": "白银日线图", "summary": "白银上破短期区间。"},
    ]

    report_dir = write_external_report(
        report,
        external_root=tmp_path,
        client=client,
        image_insights=image_insights,
    )

    markdown = (report_dir / "report.md").read_text(encoding="utf-8")
    assert "### 图表解析 1" in markdown
    assert "- 识别文字: 黄金周线图" in markdown
    assert "- 图表摘要: 价格在关键支撑附近震荡。" in markdown
    assert "### 图表解析 2" in markdown


def test_write_external_report_removes_stale_images_on_refetch(tmp_path):
    report = parse_svip_report_html(
        """
        <html><body>
        <div class="jin10vip-news-details-article-body">
          <p><img src="https://img.jin10.com/news/chart-1.jpg" /></p>
          <p><img src="https://img.jin10.com/news/chart-2.png" /></p>
        </div>
        </body></html>
        """,
        article_id="219824",
        source_url="https://svip.jin10.com/news/219824",
    )
    client = _FakeClient(
        {
            "https://img.jin10.com/news/chart-1.jpg": b"image-one",
            "https://img.jin10.com/news/chart-2.png": b"image-two",
        }
    )
    report_dir = tmp_path / report.date / report.report_type / report.article_id
    stale_dir = report_dir / "images"
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "stale.png").write_bytes(b"stale")

    write_external_report(report, external_root=tmp_path, client=client)

    kept = sorted(path.name for path in stale_dir.iterdir() if path.is_file())
    assert kept == ["01-chart-1.jpg", "02-chart-2.png"]


def test_parse_svip_report_daily_type():
    """日报: HTML 中包含 "金银报告" 关键词 → report_type='daily'"""
    html = """
    <html><head>
      <meta property="og:title" content="每日金银报告-黄金日报" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body">
        <p>金十VIP专享金银报告，欢迎点击查看！</p>
      </div>
    </body></html>
    """
    report = parse_svip_report_html(html, article_id="219824", source_url="https://svip.jin10.com/news/219824")
    assert report.report_type == "daily"
    assert report.category == "金银报告"


def test_parse_svip_report_weekly_type():
    """周报: HTML 中包含 "黄金周报" 关键词 → report_type='weekly'"""
    html = """
    <html><head>
      <meta property="og:title" content="VIP黄金周报-期权市场分析" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body">
        <p>本期黄金周报，重点分析期权市场信号。</p>
      </div>
    </body></html>
    """
    report = parse_svip_report_html(html, article_id="220071", source_url="https://svip.jin10.com/news/220071")
    assert report.report_type == "weekly"
    assert report.category == "黄金周报"


def test_parse_svip_report_html_classifies_stable_non_daily_categories() -> None:
    cases = [
        ("黄金期权持仓报告-金十数据VIP", "positioning", "持仓报告"),
        ("现货黄金点位报告-金十数据VIP", "technical_levels", "点位报告"),
        ("原油报告：供应端扰动升温-金十数据VIP", "oil", "原油报告"),
        ("外汇报告：美元指数维持强势-金十数据VIP", "fx", "外汇报告"),
    ]

    for title, report_type, category in cases:
        html = f"""
        <html><head>
          <meta property="og:title" content="{title}" />
        </head>
        <body>
          <div class="jin10vip-news-details-article-body">
            <p>{category}正文。</p>
          </div>
        </body></html>
        """
        report = parse_svip_report_html(html, article_id="230001", source_url="https://svip.jin10.com/news/230001")

        assert report.report_type == report_type
        assert report.category == category


def test_parse_svip_report_weekly_hotlist_type():
    html = """
    <html><head>
      <meta property="og:title" content="一周热榜精选：弱非农下加息押注退潮！大空头警告AI派对结束-金十数据VIP" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body">
        <p>现货黄金本周止跌反弹，五周来首次周线收涨。</p>
      </div>
    </body></html>
    """
    report = parse_svip_report_html(html, article_id="223594", source_url="https://svip.jin10.com/news/223594")

    assert report.report_type == "weekly"
    assert report.category == "黄金周报"


def test_parse_svip_report_gold_headline_is_not_weekly():
    html = """
    <html><head>
      <meta property="og:title" content="美伊谈判反复，金价仍陷入两难｜黄金头条-金十数据VIP" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body">
        <p>《黄金头条》——6月2日VIP深度汇总</p>
      </div>
    </body></html>
    """
    report = parse_svip_report_html(html, article_id="220973", source_url="https://svip.jin10.com/news/220973")

    assert report.report_type == "daily"
    assert report.category == "报告"


def test_parse_svip_report_html_falls_back_to_reduced_content_when_body_container_is_empty():
    html = r"""
    <html><head>
      <meta property="og:title" content="停火协议已成废纸，国际现货黄金长牛行情岌岌可危？-金十数据VIP" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body"></div>
      <script>
        window.__NUXT__={reduced_content:"\u003Cp style=\"text-align: justify;\"\u003E金十VIP专享\u003Cspan style=\"color: #eb6b56;\"\u003E每日金银报告\u003C\u002Fspan\u003E，欢迎点击查看！\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: justify;\"\u003E文章导读：美伊的&ldquo;边打边谈&rdquo;行为让暂时停火协议成为废纸。\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: justify;\"\u003E\u003Cstrong\u003E1、行情回顾：...\u003C\u002Fstrong\u003E\u003C\u002Fp\u003E\n\u003Cp\u003E\u003Cstrong\u003E2、关键指标：...\u003C\u002Fstrong\u003E\u003C\u002Fp\u003E\n\u003Cp\u003E下载地址：\u003C\u002Fp\u003E\n\u003Cp\u003E立即下载\u003C\u002Fp\u003E",audio_url:""};
      </script>
    </body></html>
    """

    report = parse_svip_report_html(html, article_id="220511", source_url="https://svip.jin10.com/news/220511")

    assert "文章导读" in report.report_markdown
    assert "1、行情回顾" in report.report_markdown
    assert "2、关键指标" in report.report_markdown
    assert "立即下载" not in report.report_markdown
    assert "证据不足：仅抓取到详情页 HTML，未稳定解析出正文。" not in report.report_markdown


def test_parse_svip_report_html_prefers_full_body_over_placeholder_reduced_content():
    html = r"""
    <html><head>
      <meta property="og:title" content="冲突再次接近终点，但黄金的上行空间可能已不及战前-金十数据VIP" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body"></div>
      <div class="jin10vip-news-details-content">
        <p>文章导读：美伊冲突结束的预期再次升温，但美国自身经济韧性已将降息空间压缩。</p>
        <p><strong>1、行情回顾：</strong>现货黄金开盘后一度跌至4024美元的日内低点，随后于美盘时段急速拉升。</p>
        <p><strong>2、关键指标：</strong>美国通胀预期和实际利率同步上行，压缩了美联储年内降息空间。</p>
        <p><strong>3、观点分享：</strong>油价回落难以带来鸽派反转，金价上行空间相较战前已经收窄。</p>
        <p><img src="https://img.jin10.com/news/26/06/full-body-chart.jpg" /></p>
      </div>
      <script>
        window.__NUXT__={reduced_content:"\u003Cp style=\"text-align: justify;\"\u003E文章导读：美伊冲突结束的预期再次升温。\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: justify;\"\u003E\u003Cstrong\u003E1、行情回顾：\u003C\u002Fstrong\u003E\u003Cstrong\u003E...\u003C\u002Fstrong\u003E\u003C\u002Fp\u003E\n\u003Cp\u003E\u003Cstrong\u003E2、关键指标：...\u003C\u002Fstrong\u003E\u003C\u002Fp\u003E\n\u003Cp\u003E\u003Cstrong\u003E3、观点分享：...\u003C\u002Fstrong\u003E\u003C\u002Fp\u003E",audio_url:""};
      </script>
    </body></html>
    """

    report = parse_svip_report_html(html, article_id="221732", source_url="https://svip.jin10.com/news/221732")

    assert "现货黄金开盘后一度跌至4024美元的日内低点" in report.report_markdown
    assert "美国通胀预期和实际利率同步上行" in report.report_markdown
    assert "油价回落难以带来鸽派反转" in report.report_markdown
    assert "1、行情回顾： ..." not in report.report_markdown
    assert "2、关键指标：..." not in report.report_markdown
    assert report.image_urls == ["https://img.jin10.com/news/26/06/full-body-chart.jpg"]


def test_parse_svip_report_html_drops_placeholder_reduced_lines_when_report_images_exist():
    html = r"""
    <html><head>
      <meta property="og:title" content="冲突再次接近终点，但黄金的上行空间可能已不及战前-金十数据VIP" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body"></div>
      <script>
        window.__NUXT__={reduced_content:"\u003Cp style=\"text-align: justify;\"\u003E文章导读：美伊冲突结束的预期再次升温，但美国自身经济韧性已将降息空间压缩。\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: justify;\"\u003E\u003Cstrong\u003E1、行情回顾：\u003C\u002Fstrong\u003E\u003Cstrong\u003E...\u003C\u002Fstrong\u003E\u003C\u002Fp\u003E\n\u003Cp\u003E\u003Cstrong\u003E2、关键指标：...\u003C\u002Fstrong\u003E\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: center;\"\u003E\u003Cimg src=\"https:\u002F\u002Fimg.jin10.com\u002Fnews\u002F26\u002F06\u002Freport-page.jpg\"\u003E\u003C\u002Fp\u003E",audio_url:""};
      </script>
    </body></html>
    """

    report = parse_svip_report_html(html, article_id="221732", source_url="https://svip.jin10.com/news/221732")

    assert "文章导读：美伊冲突结束的预期再次升温" in report.report_markdown
    assert "1、行情回顾： ..." not in report.report_markdown
    assert "2、关键指标：..." not in report.report_markdown
    assert report.image_urls == ["https://img.jin10.com/news/26/06/report-page.jpg"]


def test_parse_svip_report_html_keeps_reduced_content_text_and_images_when_body_is_empty() -> None:
    html = r"""
    <html><head>
      <meta property="og:title" content="停火协议已成废纸，国际现货黄金长牛行情岌岌可危？-金十数据VIP" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body"></div>
      <script>
        window.__NUXT__={reduced_content:"\u003Cp style=\"text-align: center;\"\u003E\u003Cimg src=\"https:\u002F\u002Fcdn-news.jin10.com\u002Fcover.jpg\"\u003E\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: justify;\"\u003E文章导读：非美普跌，美元独强。\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: justify;\"\u003E1、行情回顾：国际现货黄金承压。\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: justify;\"\u003E2、关键指标：收益率和美元同步走高。\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: center;\"\u003E\u003Cimg src=\"https:\u002F\u002Fimg.jin10.com\u002Fnews\u002F26\u002F05\u002Fbody-1.jpg\"\u003E\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: center;\"\u003E\u003Cimg src=\"https:\u002F\u002Fimg.jin10.com\u002Fnews\u002F26\u002F05\u002Fbody-2.jpg\"\u003E\u003C\u002Fp\u003E",audio_url:""};
      </script>
    </body></html>
    """

    report = parse_svip_report_html(html, article_id="220511", source_url="https://svip.jin10.com/news/220511")

    assert "文章导读：非美普跌，美元独强。" in report.report_markdown
    assert "1、行情回顾：国际现货黄金承压。" in report.report_markdown
    assert "2、关键指标：收益率和美元同步走高。" in report.report_markdown
    assert len(report.image_urls) >= 1
    assert any("body-1.jpg" in url or "body-2.jpg" in url for url in report.image_urls)


def test_parse_svip_report_html_filters_vip_promo_and_tail_marketing_lines():
    html = """
    <html><head>
      <meta property="og:title" content="黄金反弹进程受阻，美国“防御性”打击会摧毁和平前景吗？-金十数据VIP" />
    </head>
    <body>
      <div class="jin10vip-news-details-article-body">
        <p>金十VIP专享 每日金银报告 ，欢迎点击查看！</p>
        <p>1、行情回顾：国际现货黄金报4570.33美元/盎司。</p>
        <p>2、关键指标：10年期美债收益率从高位回落但仍守在4.5%附近。</p>
        <p>更多金银信号和消息汇总，来看今天最新的金银报告！</p>
      </div>
    </body></html>
    """

    report = parse_svip_report_html(html, article_id="220232", source_url="https://svip.jin10.com/news/220232")

    assert "欢迎点击查看" not in report.report_markdown
    assert "更多金银信号和消息汇总" not in report.report_markdown
    assert "行情回顾" in report.report_markdown
    assert "关键指标" in report.report_markdown


def test_parse_svip_report_html_prefers_article_header_date_over_embedded_recommendation_dates():
    html = """
    <html><head>
      <meta property="og:title" content="和谈波折持续洗盘，但震荡上行仍是贵金属宏观主基调-金十数据VIP" />
    </head>
    <body>
      <a class="jin10news__articleheader_info" target="_blank" href="https://xnews.jin10.com/category/270">
        <span class="jin10news__articleheader_author_name">VIP金银报告</span>
        <span class="jin10news__articleheader_time"> 2026-06-02 10:08 </span>
      </a>
      <div class="jin10vip-category-video-footer">
        <span data-time="2026-06-01 16:10:16" class="display-time-container"></span>
      </div>
      <script>
        window.__NUXT__={news:{display_datetime:"2026-06-02 10:08:00"}}
      </script>
      <div class="jin10vip-news-details-article-body">
        <p>金十VIP专享每日金银报告，欢迎点击查看！</p>
        <p>1、行情回顾：现货黄金再度跌破4500美元大关。</p>
      </div>
    </body></html>
    """

    report = parse_svip_report_html(html, article_id="220961", source_url="https://svip.jin10.com/news/220961")

    assert report.date == "2026-06-02"
