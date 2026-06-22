from __future__ import annotations

import hashlib
import json
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.collectors.jin10.adapter import (
    _charts_from_report_images,
    _build_report_quality_audit,
    _copy_output_figures,
    _report_type_for_raw_report,
    build_jin10_agent_output_payload,
    build_jin10_outputs,
    persist_jin10_agent_outputs,
    persist_jin10_task_runs,
    write_jin10_outputs,
)
from apps.parsers.jin10.report import build_parsed_index
from database.models.execution import ExecutionEvent, ensure_execution_tables
from database.models.analysis import AgentOutput, ensure_analysis_tables
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep, ensure_task_tables


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "jin10"


def _session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    ensure_analysis_tables(engine)
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_build_jin10_outputs_indexes_existing_external_report_assets():
    outputs = build_jin10_outputs(external_root=FIXTURE_ROOT, date="2026-05-06", category="270")

    assert outputs["raw"]["as_of"] == "2026-05-06"
    assert outputs["raw"]["unavailable_symbols"] == []
    assert outputs["parsed"]["reports"][0]["article_id"] == "218330"
    assert outputs["parsed"]["reports"][0]["category_code"] == "270"
    assert outputs["parsed"]["reports"][0]["page_count"] == 2
    assert outputs["parsed"]["reports"][0]["parser_version"] == "jin10-vlm-parser-v0.2"
    assert outputs["parsed"]["reports"][0]["blocks"]
    assert outputs["parsed"]["artifacts"]["218330"]["report_structured"]["article_id"] == "218330"
    assert outputs["analysis"]["source_refs"] == outputs["parsed"]["source_refs"]
    assert outputs["analysis"]["reports"][0]["summary_status"] == "ready"
    assert outputs["daily_reports"][0]["run_id"] == "218330"
    assert outputs["daily_reports"][0]["json"]["family"] == "jin10_daily_visual"

    raw_report = outputs["raw"]["reports"][0]
    assert raw_report["meta_json"]["path"].endswith("/tests/fixtures/jin10/2026-05-06/报告/218330/meta.json")
    assert raw_report["report_md"]["path"].endswith("/tests/fixtures/jin10/2026-05-06/报告/218330/report.md")
    assert raw_report["images"][0]["path"].endswith("/images/报告_2026-05-06_01.png")
    assert raw_report["images"][0]["size_bytes"] == len("fixture-image-1\n")
    assert raw_report["images"][0]["sha256"] == hashlib.sha256(b"fixture-image-1\n").hexdigest()


def test_build_jin10_outputs_ignores_stale_image_files_not_listed_in_meta(tmp_path):
    fixture = tmp_path / "2026-05-06" / "报告" / "218330"
    images = fixture / "images"
    images.mkdir(parents=True, exist_ok=True)
    for name in ("01.png", "02.png", "03.png", "04.png", "stale.png"):
        (images / name).write_text(name, encoding="utf-8")
    (fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-05-06",
                "id": "218330",
                "title": "测试报告",
                "category": "报告",
                "images": [
                    {"seq": 1, "file": "01.png", "w": 100, "h": 100},
                    {"seq": 2, "file": "02.png", "w": 100, "h": 100},
                    {"seq": 3, "file": "03.png", "w": 100, "h": 100},
                    {"seq": 4, "file": "04.png", "w": 100, "h": 100},
                ],
                "source_url": "https://xnews.jin10.com/details/218330",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (fixture / "report.md").write_text("# 测试报告\n\n## 正文\n\n正文\n", encoding="utf-8")

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-05-06", category="270")

    kept = outputs["raw"]["reports"][0]["images"]
    assert [item["file"] for item in kept] == ["01.png", "02.png", "03.png", "04.png"]


def test_build_jin10_outputs_filters_out_weekly_reports_from_daily_category(tmp_path):
    daily_fixture = tmp_path / "2026-05-25" / "daily" / "220100"
    daily_fixture.mkdir(parents=True, exist_ok=True)
    (daily_fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-05-25",
                "id": "220100",
                "title": "日报测试",
                "category": "金银报告",
                "report_type": "daily",
                "images": [],
                "source_url": "https://svip.jin10.com/news/220100",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (daily_fixture / "report.md").write_text("# 日报测试\n\n## 正文\n\n正文。\n", encoding="utf-8")

    weekly_fixture = tmp_path / "2026-05-25" / "weekly" / "220071"
    weekly_fixture.mkdir(parents=True, exist_ok=True)
    (weekly_fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-05-25",
                "id": "220071",
                "title": "周报测试",
                "category": "黄金周报",
                "report_type": "weekly",
                "images": [],
                "source_url": "https://svip.jin10.com/news/220071",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (weekly_fixture / "report.md").write_text("# 周报测试\n\n## 正文\n\n正文。\n", encoding="utf-8")

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-05-25", category="270")

    assert [report["article_id"] for report in outputs["raw"]["reports"]] == ["220100"]


def test_report_type_for_raw_report_distinguishes_weekly_category() -> None:
    assert _report_type_for_raw_report({"category_code": "536"}) == "weekly"
    assert _report_type_for_raw_report({"category_code": "270"}) == "daily"
    assert _report_type_for_raw_report({"category_code": "270", "report_type": "weekly"}) == "daily"
    assert _report_type_for_raw_report({"category": "报告", "title": "美伊谈判反复，金价仍陷入两难｜黄金头条", "report_type": "weekly"}) == "daily"
    assert _report_type_for_raw_report({"category": "黄金周报", "title": "期权市场发出信号"}) == "weekly"


def test_build_jin10_outputs_dedupes_weekly_alias_directories_by_article_id(tmp_path, monkeypatch):
    def fake_build_parsed_index(raw):
        return {"reports": [], "artifacts": {}, **{key: raw[key] for key in ("source", "as_of", "source_refs", "unavailable_symbols")}}

    monkeypatch.setattr("apps.collectors.jin10.adapter.build_parsed_index", fake_build_parsed_index)
    monkeypatch.setattr("apps.collectors.jin10.adapter.build_analysis_index", lambda parsed: {"reports": []})
    monkeypatch.setattr("apps.collectors.jin10.adapter._build_daily_report_bundle", lambda report, parsed_report, source_refs: {})

    for parent in ("报告", "weekly"):
        fixture = tmp_path / "2026-05-24" / parent / "220071"
        images_dir = fixture / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        for index in range(1, 4):
            (images_dir / f"{index:02d}.png").write_text("image", encoding="utf-8")
        (fixture / "meta.json").write_text(
            json.dumps(
                {
                    "date": "2026-05-24",
                    "id": "220071",
                    "title": "周报测试",
                    "category": "黄金周报",
                    "report_type": "weekly",
                    "images": [{"seq": index, "file": f"{index:02d}.png"} for index in range(1, 4)],
                    "source_url": "https://svip.jin10.com/news/220071",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (fixture / "report.md").write_text("# 周报测试\n\n## 正文\n\n完整正文。\n", encoding="utf-8")

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-05-24", category="536")

    reports = outputs["raw"]["reports"]
    assert [report["article_id"] for report in reports] == ["220071"]
    assert reports[0]["external_report_dir"].endswith("/weekly/220071")


def test_build_jin10_outputs_skips_incomplete_vip_summary_preview(tmp_path):
    fixture = tmp_path / "2026-05-25" / "daily" / "220100"
    images_dir = fixture / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "01-cover.png").write_text("cover", encoding="utf-8")
    (images_dir / "02-preview.jpg").write_text("preview", encoding="utf-8")
    (fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-05-25",
                "id": "220100",
                "title": "黄金行情反复风险并未消除，不可将反弹视为反攻信号-金十数据VIP",
                "category": "金银报告",
                "report_type": "daily",
                "images": [
                    {"file": "01-cover.png", "seq": 1},
                    {"file": "02-preview.jpg", "seq": 2},
                ],
                "source_url": "https://svip.jin10.com/news/220100",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (fixture / "report.md").write_text(
        "# 黄金行情反复风险并未消除\n\n"
        "## 正文\n\n"
        "页数：21\n\n"
        "下载地址：每日金银报告2026.05.25（仅VIP查看）\n\n"
        "文章导读：周末美伊协议可能在短期内达成。\n\n"
        "1、行情回顾： ...\n\n"
        "2、关键指标：...\n\n"
        "3、 观点分享：...\n",
        encoding="utf-8",
    )
    (fixture / "detail.html").write_text(
        "<html><body>页数：21 下载地址：每日金银报告2026.05.25（仅VIP查看）</body></html>",
        encoding="utf-8",
    )

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-05-25", category="270")

    assert outputs["raw"]["reports"] == []
    assert outputs["parsed"]["reports"] == []
    assert outputs["daily_reports"] == []
    assert outputs["raw"]["unavailable_symbols"][0]["reason"] == "report_not_found"


def test_build_jin10_outputs_keeps_guided_daily_report_when_only_detail_page_has_download_chrome(tmp_path, monkeypatch):
    fixture = tmp_path / "2026-06-09" / "daily" / "221446"
    images_dir = fixture / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "01-chart.png").write_bytes(b"chart-one")
    (images_dir / "02-chart.jpg").write_bytes(b"chart-two")
    (fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-06-09",
                "id": "221446",
                "title": "黄金ETF资金观望等待催化剂，白银或已进入低估区间-金十数据VIP",
                "category": "金银报告",
                "report_type": "daily",
                "images": [
                    {"file": "01-chart.png", "seq": 1},
                    {"file": "02-chart.jpg", "seq": 2},
                ],
                "source_url": "https://svip.jin10.com/news/221446",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (fixture / "report.md").write_text(
        "# 黄金ETF资金观望等待催化剂\n\n"
        "## 正文\n\n"
        "文章导读：5月黄金ETF资金表现平稳，资金进入观望状态。\n\n"
        "1、行情回顾： ...\n\n"
        "2、关键指标：...\n\n"
        "3、 观点分享：...\n",
        encoding="utf-8",
    )
    (fixture / "detail.html").write_text(
        "<html><body><aside>页数：21 下载地址：历史推荐报告（仅VIP查看）</aside></body></html>",
        encoding="utf-8",
    )

    def fake_build_parsed_index(raw):
        return {"reports": [], "artifacts": {}, **{key: raw[key] for key in ("source", "as_of", "source_refs", "unavailable_symbols")}}

    monkeypatch.setattr("apps.collectors.jin10.adapter.build_parsed_index", fake_build_parsed_index)
    monkeypatch.setattr("apps.collectors.jin10.adapter.build_analysis_index", lambda parsed: {"reports": []})
    monkeypatch.setattr("apps.collectors.jin10.adapter._build_daily_report_bundle", lambda report, parsed_report, source_refs: {})

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-06-09", category="270")

    reports = outputs["raw"]["reports"]
    assert [report["article_id"] for report in reports] == ["221446"]
    assert outputs["raw"]["unavailable_symbols"] == []


def test_build_jin10_outputs_reparses_detail_html_when_external_report_is_title_only(tmp_path):
    fixture = tmp_path / "2026-05-28" / "金银报告" / "220511"
    fixture.mkdir(parents=True, exist_ok=True)
    (fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-05-28",
                "id": "220511",
                "title": "停火协议已成废纸，国际现货黄金长牛行情岌岌可危？-金十数据VIP",
                "category": "金银报告",
                "report_type": "daily",
                "images": [],
                "image_insights": [],
                "source_url": "https://svip.jin10.com/news/220511",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (fixture / "report.md").write_text(
        "# 停火协议已成废纸，国际现货黄金长牛行情岌岌可危？-金十数据VIP\n\n## 正文\n\n证据不足：仅抓取到详情页 HTML，未稳定解析出正文。\n",
        encoding="utf-8",
    )
    (fixture / "detail.html").write_text(
        r"""
        <html><head>
          <meta property="og:title" content="停火协议已成废纸，国际现货黄金长牛行情岌岌可危？-金十数据VIP" />
        </head>
        <body>
          <div class="jin10vip-news-details-article-body"></div>
          <script>
            window.__NUXT__={reduced_content:"\u003Cp style=\"text-align: justify;\"\u003E文章导读：非美普跌，美元独强。\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: justify;\"\u003E1、行情回顾：国际现货黄金承压。\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: justify;\"\u003E2、关键指标：收益率和美元同步走高。\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: center;\"\u003E\u003Cimg src=\"https:\u002F\u002Fimg.jin10.com\u002Fnews\u002F26\u002F05\u002Fbody-1.jpg\"\u003E\u003C\u002Fp\u003E\n\u003Cp style=\"text-align: center;\"\u003E\u003Cimg src=\"https:\u002F\u002Fimg.jin10.com\u002Fnews\u002F26\u002F05\u002Fbody-2.jpg\"\u003E\u003C\u002Fp\u003E",audio_url:""};
          </script>
        </body></html>
        """,
        encoding="utf-8",
    )

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-05-28", category="270")

    raw_report = outputs["raw"]["reports"][0]
    reparsed_markdown = Path(raw_report["report_md"]["path"]).read_text(encoding="utf-8")
    reparsed_meta = json.loads(Path(raw_report["meta_json"]["path"]).read_text(encoding="utf-8"))
    assert "文章导读：非美普跌，美元独强。" in reparsed_markdown
    assert "证据不足：仅抓取到详情页 HTML，未稳定解析出正文。" not in reparsed_markdown
    assert len(raw_report["images"]) == 2
    assert raw_report["images"][0]["path"].startswith("https://img.jin10.com/")
    assert raw_report["images"][0]["sha256"]
    assert len(reparsed_meta["images"]) == 2
    assert reparsed_meta["images"][0]["source_url"].startswith("https://img.jin10.com/")


def test_build_jin10_outputs_reparses_detail_html_when_external_report_contains_legacy_promo_noise(tmp_path):
    fixture = tmp_path / "2026-05-26" / "daily" / "220232"
    fixture.mkdir(parents=True, exist_ok=True)
    (fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-05-26",
                "id": "220232",
                "title": "黄金反弹进程受阻，美国“防御性”打击会摧毁和平前景吗？-金十数据VIP",
                "category": "金银报告",
                "report_type": "daily",
                "images": [
                    {"file": "01-body.jpg", "seq": 1, "source_url": "https://img.jin10.com/news/26/05/body.jpg"}
                ],
                "image_insights": [],
                "source_url": "https://svip.jin10.com/news/220232",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (fixture / "report.md").write_text(
        "# 黄金反弹进程受阻\n\n"
        "## 正文\n\n"
        "金十VIP专享 每日金银报告 ，欢迎点击查看！\n\n"
        "1、行情回顾：旧正文。\n\n"
        "更多金银信号和消息汇总，来看今天最新的金银报告！\n\n"
        "### 图表解析 1\n\n"
        "- 图表解析: unavailable (missing_openai_api_key)\n",
        encoding="utf-8",
    )
    (fixture / "detail.html").write_text(
        """
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
        """,
        encoding="utf-8",
    )

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-05-26")

    raw_report = outputs["raw"]["reports"][0]
    rebuilt = Path(raw_report["report_md"]["path"]).read_text(encoding="utf-8")
    assert "欢迎点击查看" not in rebuilt
    assert "更多金银信号和消息汇总" not in rebuilt
    assert "图表解析: unavailable" not in rebuilt
    assert "1、行情回顾：国际现货黄金报4570.33美元/盎司。" in rebuilt
    assert "2、关键指标：10年期美债收益率从高位回落但仍守在4.5%附近。" in rebuilt


def test_build_jin10_outputs_reparse_keeps_local_images_when_meta_source_names_change(tmp_path):
    fixture = tmp_path / "2026-05-26" / "daily" / "220232"
    images_dir = fixture / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / "01-body.jpg").write_bytes(b"image-one")
    (images_dir / "02-chart.jpg").write_bytes(b"image-two")
    (fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-05-26",
                "id": "220232",
                "title": "黄金反弹进程受阻，美国“防御性”打击会摧毁和平前景吗？-金十数据VIP",
                "category": "金银报告",
                "report_type": "daily",
                "images": [
                    {"file": "01-body.jpg", "seq": 1, "path": str(images_dir / "01-body.jpg")},
                    {"file": "02-chart.jpg", "seq": 2, "path": str(images_dir / "02-chart.jpg")},
                ],
                "image_insights": [],
                "source_url": "https://svip.jin10.com/news/220232",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (fixture / "report.md").write_text(
        "# 黄金反弹进程受阻\n\n## 正文\n\n金十VIP专享 每日金银报告 ，欢迎点击查看！\n",
        encoding="utf-8",
    )
    (fixture / "detail.html").write_text(
        """
        <html><head>
          <meta property="og:title" content="黄金反弹进程受阻，美国“防御性”打击会摧毁和平前景吗？-金十数据VIP" />
        </head>
        <body>
          <div class="jin10vip-news-details-article-body">
            <p>1、行情回顾：国际现货黄金报4570.33美元/盎司。</p>
            <p>2、关键指标：10年期美债收益率从高位回落但仍守在4.5%附近。</p>
            <p><img src="https://img.jin10.com/news/26/05/body.jpg" /></p>
            <p><img src="https://img.jin10.com/news/26/05/chart.jpg" /></p>
          </div>
        </body></html>
        """,
        encoding="utf-8",
    )

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-05-26")

    raw_report = outputs["raw"]["reports"][0]
    assert len(raw_report["images"]) == 2
    assert raw_report["images"][0]["path"].endswith("/01-body.jpg")
    assert raw_report["images"][1]["path"].endswith("/02-chart.jpg")


def test_charts_from_report_images_uses_human_readable_captions_when_only_fallback_images_exist():
    charts = _charts_from_report_images(
        {
            "images": [
                {
                    "file": "01-sti555IVWS6Q_lvtjE4Ju.jpg",
                    "path": "/tmp/01-sti555IVWS6Q_lvtjE4Ju.jpg",
                    "seq": 1,
                },
                {
                    "file": "02-kIs7otJbCe0M0JHQ6RCNE.jpg",
                    "path": "/tmp/02-kIs7otJbCe0M0JHQ6RCNE.jpg",
                    "seq": 2,
                },
            ],
            "meta_json": {"path": "/tmp/unused-meta.json"},
        }
    )

    assert charts is not None
    assert charts[0]["title"] == "第1页报告图"
    assert charts[0]["caption"] == "第1页报告图"
    assert charts[1]["title"] == "第2页报告图"


def test_daily_report_bundle_prefers_parsed_figures_for_raw_article_charts_when_available(monkeypatch):
    def fake_parse_report_images(**_: object) -> dict[str, object]:
        return {
            "page_images": {"article_id": "218330", "parser_version": "jin10-vlm-parser-v0.2", "pages": []},
            "figures": {
                "article_id": "218330",
                "parser_version": "jin10-vlm-parser-v0.2",
                "figures": [
                    {
                        "figure_id": "fig_p2_001",
                        "page_no": 2,
                        "bbox": [0, 0, 100, 100],
                        "chart_image_path": "figures/fig_p2_001.png",
                        "title": "识别图表",
                        "nearby_text": "收益率回落带来修复窗口",
                        "chart_type": "unknown",
                        "confidence": 0.88,
                    }
                ],
            },
            "report_structured": {"article_id": "218330", "parser_version": "jin10-vlm-parser-v0.2", "sections": []},
            "parse_status": {
                "article_id": "218330",
                "parser_version": "jin10-vlm-parser-v0.2",
                "parser_run_id": "test-run",
                "status": "success",
                "recognition_mode": "vlm",
                "figures_total": 1,
                "section_count": 0,
                "vision_markdown_status": "success",
            },
            "vision_markdown": {
                "pages": [
                    {
                        "page_no": 2,
                        "status": "success",
                        "markdown": "## 识别图表\n\n![图表](figures/fig_p2_001.png)\n\n收益率回落带来修复窗口。",
                    }
                ]
            },
            "body_markdown": "# 行情回顾\n\n完整正文。",
        }

    monkeypatch.setattr("apps.parsers.jin10.report.parse_report_images", fake_parse_report_images)

    outputs = build_jin10_outputs(external_root=FIXTURE_ROOT, date="2026-05-06", category="270")

    charts = outputs["daily_reports"][0]["raw_article_json"]["charts"]
    assert charts
    assert charts[0]["image_path"] == "figures/fig_p2_001.png"
    assert charts[0]["title"] == "识别图表"
    assert "收益率回落带来修复窗口" in charts[0]["summary"]


def test_build_jin10_outputs_keeps_vlm_markdown_when_images_missing(monkeypatch, tmp_path):
    fixture = tmp_path / "2026-05-06" / "报告" / "218331"
    fixture.mkdir(parents=True, exist_ok=True)
    (fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-05-06",
                "id": "218331",
                "title": "测试多图报告",
                "category": "报告",
                "images": [],
                "source_url": "https://xnews.jin10.com/details/218331",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (fixture / "report.md").write_text("", encoding="utf-8")

    def fake_parse_report_images(**kwargs: object) -> dict[str, object]:
        image_entries = list(kwargs["image_entries"])  # type: ignore[index]
        assert image_entries == []
        return {
            "page_images": {"article_id": "218331", "parser_version": "jin10-vlm-parser-v0.2", "pages": image_entries},
            "figures": {"article_id": "218331", "parser_version": "jin10-vlm-parser-v0.2", "figures": []},
            "report_structured": {"article_id": "218331", "parser_version": "jin10-vlm-parser-v0.2", "sections": []},
            "parse_status": {
                "article_id": "218331",
                "parser_version": "jin10-vlm-parser-v0.2",
                "parser_run_id": "test-run",
                "status": "success",
                "recognition_mode": "vlm",
                "figures_total": 0,
                "section_count": 0,
                "vision_markdown_status": "success",
            },
            "vision_markdown": {"pages": []},
            "body_markdown": "# 正文\n\n来自 VLM 识别结果的正文。",
        }

    monkeypatch.setattr("apps.parsers.jin10.report.parse_report_images", fake_parse_report_images)

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-05-06", category="270")

    raw_report = outputs["raw"]["reports"][0]
    assert raw_report["images"] == []
    assert not any(ref["asset_type"] == "report_pdf" for ref in outputs["raw"]["source_refs"])
    assert "来自 VLM 识别结果的正文。" in outputs["parsed"]["reports"][0]["body_text"]
    assert "来自 VLM 识别结果的正文。" in outputs["daily_reports"][0]["raw_article_markdown"]


def test_daily_report_bundle_uses_parsed_markdown_for_analysis_input(monkeypatch, tmp_path):
    fixture = tmp_path / "2026-05-06" / "报告" / "218399"
    fixture.mkdir(parents=True, exist_ok=True)
    (fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-05-06",
                "id": "218399",
                "title": "解析优先测试",
                "category": "报告",
                "images": [],
                "source_url": "https://xnews.jin10.com/details/218399",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (fixture / "report.md").write_text("# 原始抓取\n\n这里只是抓取原文占位，不应直接进入分析。\n", encoding="utf-8")

    def fake_parse_report_images(**kwargs: object) -> dict[str, object]:
        return {
            "page_images": {"article_id": "218399", "parser_version": "jin10-vlm-parser-v0.2", "pages": []},
            "figures": {"article_id": "218399", "parser_version": "jin10-vlm-parser-v0.2", "figures": []},
            "report_structured": {"article_id": "218399", "parser_version": "jin10-vlm-parser-v0.2", "sections": []},
            "parse_status": {
                "article_id": "218399",
                "parser_version": "jin10-vlm-parser-v0.2",
                "parser_run_id": "test-run",
                "status": "success",
                "recognition_mode": "vlm",
                "figures_total": 0,
                "section_count": 0,
                "vision_markdown_status": "success",
            },
            "vision_markdown": {"pages": []},
            "body_markdown": "# 解析后正文\n\n这是解析后的稳定 MD，应作为分析输入。\n\n关键位：4600 为确认位，4500 为分界位。",
        }

    monkeypatch.setattr("apps.parsers.jin10.report.parse_report_images", fake_parse_report_images)

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-05-06", category="270")

    raw_article = outputs["daily_reports"][0]["raw_article_json"]
    assert raw_article["generated_from"]["content_stage"] == "parsed_markdown"
    assert "解析后的稳定 MD" in raw_article["article_markdown"]
    assert "抓取原文占位" not in raw_article["article_markdown"]


def test_daily_report_bundle_raw_article_keeps_rebuilt_web_markdown_when_image_parser_is_empty(monkeypatch, tmp_path):
    fixture = tmp_path / "2026-05-28" / "金银报告" / "220511"
    fixture.mkdir(parents=True, exist_ok=True)
    rebuilt_markdown = (
        "# 停火协议已成废纸，国际现货黄金长牛行情岌岌可危？-金十数据VIP\n\n"
        "## 正文\n\n"
        "文章导读：非美普跌，美元独强。\n\n"
        "1、行情回顾：国际现货黄金承压。\n\n"
        "2、关键指标：收益率和美元同步走高。\n\n"
        "## 报告图片\n\n"
        "![body-1](https://img.jin10.com/news/26/05/body-1.jpg)\n"
    )
    (fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-05-28",
                "id": "220511",
                "title": "停火协议已成废纸，国际现货黄金长牛行情岌岌可危？-金十数据VIP",
                "category": "金银报告",
                "report_type": "daily",
                "images": [{"seq": 1, "file": "body-1.jpg", "source_url": "https://img.jin10.com/news/26/05/body-1.jpg"}],
                "source_url": "https://svip.jin10.com/news/220511",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (fixture / "report.md").write_text(rebuilt_markdown, encoding="utf-8")

    def fake_parse_report_images(**kwargs: object) -> dict[str, object]:
        return {
            "page_images": {"article_id": "220511", "parser_version": "jin10-vlm-parser-v0.2", "pages": []},
            "figures": {"article_id": "220511", "parser_version": "jin10-vlm-parser-v0.2", "figures": []},
            "report_structured": {"article_id": "220511", "parser_version": "jin10-vlm-parser-v0.2", "sections": []},
            "parse_status": {
                "article_id": "220511",
                "parser_version": "jin10-vlm-parser-v0.2",
                "parser_run_id": "test-run",
                "status": "empty",
                "recognition_mode": "vlm",
                "figures_total": 0,
                "section_count": 0,
                "vision_markdown_status": "empty",
            },
            "vision_markdown": {"pages": []},
            "body_markdown": "",
        }

    monkeypatch.setattr("apps.parsers.jin10.report.parse_report_images", fake_parse_report_images)

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-05-28", category="270")

    raw_article = outputs["daily_reports"][0]["raw_article_json"]
    assert "文章导读：非美普跌，美元独强。" in raw_article["article_markdown"]
    assert "行情回顾：国际现货黄金承压。" in raw_article["article_markdown"]
    assert "## 报告图片" not in raw_article["article_markdown"]


def test_daily_report_bundle_prefers_parsed_figures_for_raw_article_charts(monkeypatch, tmp_path):
    fixture = tmp_path / "2026-05-06" / "报告" / "218430"
    images = fixture / "images"
    images.mkdir(parents=True, exist_ok=True)
    (images / "01.png").write_text("stub-image", encoding="utf-8")
    (fixture / "meta.json").write_text(
        json.dumps(
            {
                "date": "2026-05-06",
                "id": "218430",
                "title": "图表优先测试",
                "category": "报告",
                "images": [{"seq": 1, "file": "01.png", "w": 100, "h": 100}],
                "source_url": "https://xnews.jin10.com/details/218430",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (fixture / "report.md").write_text("# 原始抓取\n\n占位正文。\n", encoding="utf-8")

    def fake_parse_report_images(**kwargs: object) -> dict[str, object]:
        return {
            "page_images": {"article_id": "218430", "parser_version": "jin10-vlm-parser-v0.2", "pages": []},
            "figures": {
                "article_id": "218430",
                "parser_version": "jin10-vlm-parser-v0.2",
                "figures": [
                    {
                        "figure_id": "fig_p2_001",
                        "page_no": 2,
                        "bbox": [0, 0, 100, 100],
                        "chart_image_path": "figures/fig_p2_001.png",
                        "title": "美国初请人数维持下行趋势",
                        "nearby_text": "收益率回落为黄金修复打开窗口",
                    }
                ],
            },
            "report_structured": {"article_id": "218430", "parser_version": "jin10-vlm-parser-v0.2", "sections": []},
            "parse_status": {
                "article_id": "218430",
                "parser_version": "jin10-vlm-parser-v0.2",
                "parser_run_id": "test-run",
                "status": "success",
                "recognition_mode": "vlm",
                "figures_total": 1,
                "section_count": 0,
                "vision_markdown_status": "success",
            },
            "vision_markdown": {
                "pages": [
                    {
                        "page_no": 2,
                        "status": "success",
                        "markdown": "## 美国初请人数维持下行趋势\n\n![图表](figures/fig_p2_001.png)\n\n收益率回落为黄金修复打开窗口。",
                    }
                ]
            },
            "body_markdown": "# 解析后正文\n\n收益率回落为黄金修复打开窗口。",
        }

    monkeypatch.setattr("apps.parsers.jin10.report.parse_report_images", fake_parse_report_images)

    outputs = build_jin10_outputs(external_root=tmp_path, date="2026-05-06", category="270")

    chart = outputs["daily_reports"][0]["raw_article_json"]["charts"][0]
    assert chart["image_path"] == "figures/fig_p2_001.png"
    assert chart["title"] == "美国初请人数维持下行趋势"
    assert chart["recognized_text"]


def test_build_jin10_outputs_returns_explicit_unavailable_for_missing_category():
    outputs = build_jin10_outputs(external_root=FIXTURE_ROOT, date="2026-05-06", category="271")

    assert outputs["raw"]["reports"] == []
    assert outputs["parsed"]["reports"] == []
    assert outputs["analysis"]["reports"] == []
    assert outputs["raw"]["unavailable_symbols"] == [
        {
            "symbol": "jin10:271:2026-05-06",
            "reason": "category_not_found",
            "source_root": str(FIXTURE_ROOT),
        }
    ]
    assert outputs["analysis"]["source_refs"] == []


def test_write_jin10_outputs_writes_layered_json_without_copying_images(tmp_path):
    outputs = build_jin10_outputs(external_root=FIXTURE_ROOT, date="2026-05-06")
    written = write_jin10_outputs(outputs, storage_root=tmp_path)

    raw_index = tmp_path / "raw" / "jin10" / "2026-05-06" / "index.json"
    parsed_index = tmp_path / "parsed" / "jin10" / "2026-05-06" / "index.json"
    analysis_index = tmp_path / "outputs" / "jin10" / "2026-05-06" / "analysis.json"

    assert written == {
        "raw": raw_index,
        "parsed": parsed_index,
        "analysis": analysis_index,
    }
    assert json.loads(raw_index.read_text(encoding="utf-8"))["source_refs"]
    assert json.loads(parsed_index.read_text(encoding="utf-8"))["reports"]
    assert json.loads(analysis_index.read_text(encoding="utf-8"))["source_refs"]
    assert (tmp_path / "parsed" / "jin10" / "2026-05-06" / "218330" / "page_images.json").exists()
    assert (tmp_path / "parsed" / "jin10" / "2026-05-06" / "218330" / "figures.json").exists()
    assert (tmp_path / "parsed" / "jin10" / "2026-05-06" / "218330" / "report_structured.json").exists()
    assert (tmp_path / "parsed" / "jin10" / "2026-05-06" / "218330" / "parse_status.json").exists()
    raw_article_json = tmp_path / "outputs" / "jin10" / "2026-05-06" / "218330" / "raw_article_report.json"
    raw_article_md = tmp_path / "outputs" / "jin10" / "2026-05-06" / "218330" / "raw_article_report.md"
    assert (tmp_path / "outputs" / "jin10" / "2026-05-06" / "218330" / "daily_analysis.json").exists()
    assert (tmp_path / "outputs" / "jin10" / "2026-05-06" / "218330" / "daily_analysis.html").exists()
    assert raw_article_json.exists()
    assert raw_article_md.exists()
    raw_article = json.loads(raw_article_json.read_text(encoding="utf-8"))
    assert raw_article["family"] == "jin10_raw_article"
    assert raw_article["charts"][0]["image_path"].endswith("/images/报告_2026-05-06_01.png")
    raw_article_markdown = raw_article_md.read_text(encoding="utf-8")
    assert "## 图表" in raw_article_markdown
    assert "## 报告图片" not in raw_article_markdown
    assert raw_article_markdown.count("![第1页报告图](images/报告_2026-05-06_01.png)") == 1
    assert not (tmp_path / "raw" / "jin10" / "2026-05-06" / "images").exists()


def test_copy_output_figures_only_copies_allowed_raw_article_charts(tmp_path):
    parsed_base = tmp_path / "parsed"
    figures_dir = parsed_base / "figures"
    figures_dir.mkdir(parents=True)
    (figures_dir / "fig_p11_001.png").write_text("keep", encoding="utf-8")
    (figures_dir / "fig_p16_001.png").write_text("drop", encoding="utf-8")
    output_base = tmp_path / "outputs"
    stale_dir = output_base / "figures"
    stale_dir.mkdir(parents=True)
    (stale_dir / "stale.png").write_text("stale", encoding="utf-8")

    _copy_output_figures(
        {
            "figures": {
                "figures": [
                    {"chart_image_path": "figures/fig_p11_001.png"},
                    {"chart_image_path": "figures/fig_p16_001.png"},
                ]
            }
        },
        parsed_base=parsed_base,
        output_base=output_base,
        allowed_paths={"figures/fig_p11_001.png"},
    )

    copied = sorted(path.name for path in (output_base / "figures").iterdir())
    assert copied == ["fig_p11_001.png"]


def test_build_jin10_outputs_prefers_vlm_body_markdown(monkeypatch):
    def fake_parse_report_images(**_: object) -> dict[str, object]:
        return {
            "page_images": {"article_id": "218330", "parser_version": "jin10-vlm-parser-v0.2", "pages": []},
            "figures": {
                "article_id": "218330",
                "parser_version": "jin10-vlm-parser-v0.2",
                "figures": [
                    {
                        "figure_id": "fig_p2_001",
                        "page_no": 2,
                        "bbox": [0, 0, 100, 100],
                        "chart_image_path": "figures/fig_p2_001.png",
                        "title": "美国初请人数维持下行趋势",
                        "nearby_text": "",
                        "chart_type": "unknown",
                        "confidence": 0.88,
                    }
                ],
            },
            "report_structured": {"article_id": "218330", "parser_version": "jin10-vlm-parser-v0.2", "sections": []},
            "parse_status": {
                "article_id": "218330",
                "parser_version": "jin10-vlm-parser-v0.2",
                "parser_run_id": "test-run",
                "status": "success",
                "recognition_mode": "vlm",
                "figures_total": 1,
                "section_count": 0,
                "vision_markdown_status": "success",
            },
            "vision_markdown": {"pages": []},
            "body_markdown": "# 行情回顾\n\n![美国初请人数维持下行趋势](figures/fig_p2_001.png)\n\n完整正文。",
        }

    monkeypatch.setattr("apps.parsers.jin10.report.parse_report_images", fake_parse_report_images)

    outputs = build_jin10_outputs(external_root=FIXTURE_ROOT, date="2026-05-06", category="270")

    body_text = outputs["parsed"]["reports"][0]["body_text"]
    raw_article_markdown = outputs["daily_reports"][0]["raw_article_markdown"]
    assert "完整正文。" in body_text
    assert "figures/fig_p2_001.png" in raw_article_markdown
    assert "## 图表" not in raw_article_markdown


def test_build_parsed_index_falls_back_to_web_markdown_when_structured_body_is_title_only(
    monkeypatch,
    tmp_path: Path,
):
    report_dir = tmp_path / "2026-05-28" / "daily" / "220511"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_md = report_dir / "report.md"
    meta_json = report_dir / "meta.json"
    report_md.write_text(
        "# 网页样本标题\n\n## 正文\n\n真实网页正文。\n\n![图1](https://img.example.com/1.png)\n",
        encoding="utf-8",
    )
    meta_json.write_text(
        json.dumps({"published_at": "2026-05-28 08:00"}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "apps.parsers.jin10.report.parse_report_images",
        lambda **kwargs: {
            "parse_status": {
                "parser_version": "test",
                "parser_run_id": "run",
                "status": "success",
                "vision_markdown_status": "empty",
                "section_count": 0,
                "figures_total": 0,
            },
            "report_structured": {"sections": []},
            "figures": {"figures": []},
            "body_markdown": "# 网页样本标题\n\n- 发布时间: 2026-05-28 08:00\n",
        },
    )

    parsed = build_parsed_index(
        {
            "source": "jin10_external",
            "as_of": "2026-05-28",
            "source_refs": [],
            "unavailable_symbols": [],
            "reports": [
                {
                    "article_id": "220511",
                    "date": "2026-05-28",
                    "title": "网页样本标题",
                    "category": "金银报告",
                    "category_code": "270",
                    "source_url": "https://svip.jin10.com/news/220511",
                    "external_report_dir": str(report_dir),
                    "retrieved_at": "2026-05-28T08:00:00+00:00",
                    "meta_json": {
                        "asset_type": "meta_json",
                        "path": str(meta_json),
                        "sha256": "meta",
                        "size_bytes": meta_json.stat().st_size,
                    },
                    "report_md": {
                        "asset_type": "report_md",
                        "path": str(report_md),
                        "sha256": "report",
                        "size_bytes": report_md.stat().st_size,
                    },
                    "images": [],
                }
            ],
        }
    )

    assert "真实网页正文。" in parsed["reports"][0]["body_text"]


def test_build_jin10_outputs_marks_vlm_failure_explicitly_and_still_returns_raw_article(monkeypatch):
    def fake_parse_report_images(**_: object) -> dict[str, object]:
        return {
            "page_images": {"article_id": "218330", "parser_version": "jin10-vlm-parser-v0.2", "pages": []},
            "figures": {"article_id": "218330", "parser_version": "jin10-vlm-parser-v0.2", "figures": []},
            "report_structured": {"article_id": "218330", "parser_version": "jin10-vlm-parser-v0.2", "sections": []},
            "parse_status": {
                "article_id": "218330",
                "parser_version": "jin10-vlm-parser-v0.2",
                "parser_run_id": "test-run",
                "status": "success",
                "recognition_mode": "vlm",
                "figures_total": 0,
                "section_count": 0,
                "vision_markdown_status": "failed",
                "warnings": ["vision_markdown_failed:APITimeoutError"],
            },
            "vision_markdown": None,
            "body_markdown": "# 报告正文\n\n解析超时后仍保留可读正文。",
        }

    monkeypatch.setattr("apps.parsers.jin10.report.parse_report_images", fake_parse_report_images)

    outputs = build_jin10_outputs(external_root=FIXTURE_ROOT, date="2026-05-06", category="270")

    parsed_report = outputs["parsed"]["reports"][0]
    raw_article = outputs["daily_reports"][0]["raw_article_json"]
    assert parsed_report["vlm_status"] == "failed"
    assert "解析超时后仍保留可读正文。" in parsed_report["body_text"]
    assert raw_article["generated_from"]["content_stage"] == "parsed_markdown"
    assert "解析超时后仍保留可读正文。" in raw_article["article_markdown"]


def test_build_jin10_agent_output_payload_exposes_prompt_claims_and_artifacts(tmp_path):
    outputs = build_jin10_outputs(external_root=FIXTURE_ROOT, date="2026-05-06", category="270")
    write_jin10_outputs(outputs, storage_root=tmp_path)

    payload = build_jin10_agent_output_payload(outputs["daily_reports"][0], storage_root=tmp_path)

    assert payload["snapshot_id"] == "jin10:2026-05-06:218330:agent_analysis"
    assert payload["agent_name"] == "jin10_report_analysis_agent"
    assert payload["module"] == "jin10_reports"
    assert payload["status"] in {"success", "partial"}
    assert payload["input_snapshot_ids"] == {
        "jin10_raw_article_report": "jin10:2026-05-06:218330:raw_article_report",
        "jin10_daily_visual": "jin10:2026-05-06:218330:daily_analysis",
    }
    assert payload["payload"]["prompt_version"] == "jin10_agent_analysis_v2"
    assert payload["payload"]["prompt_messages"][0]["role"] == "system"
    assert "## Agent 入库字段" not in payload["payload"]["prompt_messages"][1]["content"]
    assert "不输出 YAML、JSON 或 Agent 入库字段" in payload["payload"]["prompt_messages"][1]["content"]
    assert payload["payload"]["input_payload"]["raw_report"]["article_id"] == "218330"
    assert payload["payload"]["input_payload"]["daily_report"]["family"] == "jin10_daily_visual"
    assert payload["payload"]["artifact_refs"][-1].endswith("/agent_analysis_report.md")
    assert Path(payload["payload"]["artifact_refs"][0]).is_file()
    assert payload["payload"]["claims"]
    assert payload["payload"]["data_category"] == "external_opinion"


def test_persist_jin10_agent_outputs_stores_traceable_agent_output(tmp_path):
    outputs = build_jin10_outputs(external_root=FIXTURE_ROOT, date="2026-05-06", category="270")
    write_jin10_outputs(outputs, storage_root=tmp_path)
    session = _session()

    first = persist_jin10_agent_outputs(outputs, storage_root=tmp_path, session=session)
    session.commit()
    second = persist_jin10_agent_outputs(outputs, storage_root=tmp_path, session=session)
    session.commit()

    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["agent_output_id"] == second[0]["agent_output_id"]
    assert first[0]["agent_name"] == "jin10_report_analysis_agent"
    assert first[0]["fact_review_agent_output_id"] == second[0]["fact_review_agent_output_id"]
    assert first[0]["synthesis_agent_output_id"] == second[0]["synthesis_agent_output_id"]

    rows = session.scalars(select(AgentOutput).order_by(AgentOutput.agent_name)).all()
    assert len(rows) == 3
    fact_review_row = next(row for row in rows if row.agent_name == "fact_review_agent")
    synthesis_row = next(row for row in rows if row.agent_name == "synthesis_agent")
    row = next(row for row in rows if row.agent_name == "jin10_report_analysis_agent")
    assert row.snapshot_id == "jin10:2026-05-06:218330:agent_analysis"
    assert row.run_id == "218330"
    assert row.summary
    assert row.payload["prompt_version"] == "jin10_agent_analysis_v2"
    assert row.payload["prompt_messages"][1]["content"]
    assert row.payload["input_payload"]["raw_report"]["article_id"] == "218330"
    assert row.payload["narrative_md"].startswith("# ")
    assert row.payload["artifact_refs"][2].endswith("/daily_analysis.json")
    assert row.payload["claims"]
    assert fact_review_row.payload["fact_review_status"] in {"passed", "partial", "needs_review"}
    assert fact_review_row.payload["claim_reviews"]
    assert synthesis_row.payload["prompt_version"] == "synthesis_rules_v1"


def test_persist_jin10_task_runs_creates_agent_task_visible_run(tmp_path):
    outputs = build_jin10_outputs(external_root=FIXTURE_ROOT, date="2026-05-06", category="270")
    outputs["daily_reports"][0]["quality_audit"] = {"status": "accepted", "reasons": []}
    write_jin10_outputs(outputs, storage_root=tmp_path)
    session = _session()

    persisted = persist_jin10_task_runs(outputs, storage_root=tmp_path, session=session)
    session.commit()

    assert len(persisted) == 1
    run = session.query(TaskRun).filter(TaskRun.task_type == "jin10_report").one()
    steps = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).order_by(TaskStep.step_order.asc()).all()

    assert run.final_result_id == "218330"
    assert run.trade_date == "2026-05-06"
    assert run.snapshot_id == "jin10:2026-05-06:218330:agent_analysis"
    assert [step.name for step in steps] == ["external_ingest", "vlm_parse", "daily_analysis", "agent_analysis", "quality_audit"]
    assert any("agent_analysis_report.md" in (step.output_refs or "") for step in steps)
    assert run.status is TaskStatus.success
    assert steps[-1].status is StepStatus.success


def test_report_quality_audit_rejects_non_daily_report_title() -> None:
    audit = _build_report_quality_audit(
        report={
            "title": "美国就业岗位排行榜 薪资中位数最高的是哪个工种？丨财料-金十数据VIP",
            "date": "2026-06-08",
            "external_report_dir": "/home/zxx/jin10-reports/2026-06-08/daily/221274",
        },
        parsed_report={"vlm_status": "success"},
        raw_article={
            "generated_from": {
                "article_context": {
                    "key_sentences": [],
                    "level_snippets": [],
                    "chart_summaries": ["title=第1页报告图; caption=第1页报告图"],
                }
            }
        },
        visual={
            "core_conclusion": "解析已完成，但正文与图表证据仍不足以形成稳定结论。",
            "market_prices": [],
            "logic_chains": [{"label": "证据不足"}],
        },
    )

    assert audit["status"] == "rejected"
    assert {reason["code"] for reason in audit["reasons"]} >= {"non_daily_report_title", "evidence_insufficient"}


def test_persist_jin10_task_runs_marks_rejected_quality_as_degraded(tmp_path):
    outputs = build_jin10_outputs(external_root=FIXTURE_ROOT, date="2026-05-06", category="270")
    outputs["daily_reports"][0]["quality_audit"] = {
        "status": "rejected",
        "reasons": [{"code": "non_daily_report_title", "message": "not a gold/silver daily report"}],
    }
    write_jin10_outputs(outputs, storage_root=tmp_path)
    session = _session()

    persisted = persist_jin10_task_runs(outputs, storage_root=tmp_path, session=session)
    session.commit()

    assert persisted[0]["status"] == "degraded"
    run = session.query(TaskRun).filter(TaskRun.task_type == "jin10_report").one()
    steps = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).order_by(TaskStep.step_order.asc()).all()
    assert run.status is TaskStatus.degraded
    assert run.current_stage == "quality_audit"
    assert "quality audit" in (run.error_summary or "")
    assert steps[3].name == "agent_analysis"
    assert steps[3].status is StepStatus.blocked
    assert steps[4].name == "quality_audit"
    assert steps[4].status is StepStatus.blocked


def test_persist_jin10_task_runs_updates_existing_run_quality_status(tmp_path):
    outputs = build_jin10_outputs(external_root=FIXTURE_ROOT, date="2026-05-06", category="270")
    outputs["daily_reports"][0]["quality_audit"] = {"status": "accepted", "reasons": []}
    write_jin10_outputs(outputs, storage_root=tmp_path)
    session = _session()

    persist_jin10_task_runs(outputs, storage_root=tmp_path, session=session)
    session.commit()

    outputs["daily_reports"][0]["quality_audit"] = {
        "status": "rejected",
        "reasons": [{"code": "non_daily_report_title", "message": "not a gold/silver daily report"}],
    }
    persisted = persist_jin10_task_runs(outputs, storage_root=tmp_path, session=session)
    session.commit()

    assert persisted[0]["status"] == "degraded"
    run = session.query(TaskRun).filter(TaskRun.task_type == "jin10_report").one()
    steps = session.query(TaskStep).filter(TaskStep.task_run_id == run.id).order_by(TaskStep.step_order.asc()).all()
    events = session.query(ExecutionEvent).filter(ExecutionEvent.run_id == run.id).all()
    event_types = [event.event_type for event in events]
    assert run.status is TaskStatus.degraded
    assert steps[3].name == "agent_analysis"
    assert steps[3].status is StepStatus.blocked
    assert steps[4].name == "quality_audit"
    assert steps[4].status is StepStatus.blocked
    assert "non_daily_report_title" in (steps[4].error_json or "")
    assert event_types.count("RUN_FINISHED") == 2
    assert event_types.count("TASK_BLOCKED") == 2
