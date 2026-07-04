from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.collectors.news.base import NewsCollectionResult, RawNewsItem
from apps.collectors.news.jin10_detail_fetcher import Jin10DetailFetchResult
from scripts import run_feishu_jin10_detail_smoke


def _raw_item(title: str, url: str) -> RawNewsItem:
    text = title.lower()
    has_gold = any(keyword in text for keyword in ["黄金", "金价", "xau", "gold"])
    has_macro = any(keyword in text for keyword in ["美联储", "降息", "利率", "通胀", "fed", "鸽派"])
    has_energy = any(keyword in text for keyword in ["油价", "原油", "wti", "brent", "霍尔木兹", "伊朗", "美伊"])
    relevance_score = 0.92 if has_gold and (has_macro or has_energy) else 0.48
    relevance_decision = "high_value" if relevance_score >= 0.75 else "candidate"
    return RawNewsItem(
        source_key="jin10_feishu",
        source_name="Jin10 Feishu Chat Pull",
        source_type="supplemental",
        feed_key="oc_test",
        title=title,
        url=url,
        domain="xnews.jin10.com",
        published_at="2026-06-11T00:00:00+00:00",
        fetched_at="2026-06-11T00:00:01+00:00",
        summary=title,
        source_country="CN",
        source_language="zh-CN",
        event_type="hormuz_risk",
        verification_status="single_source",
        duplicate_key=f"news:jin10_feishu:{title}",
        raw_payload={
            "relevance_decision": {
                "decision": relevance_decision,
                "score": relevance_score,
                "asset_tags": ["XAUUSD", "WTI", "Brent", "DXY"] if has_gold or has_energy else [],
                "topic_tags": ["gold", "rates", "energy"] if has_gold or has_macro or has_energy else [],
                "need_detail_fetch": url.startswith(("http://", "https://")),
            },
            "source_refs": [{"source": "jin10_feishu", "source_ref": f"jin10_feishu:oc_test:{title}"}],
        },
    )


def test_dry_run_does_not_collect_or_write(tmp_path: Path, monkeypatch, capsys) -> None:
    def fail_collect(**kwargs: Any) -> NewsCollectionResult:
        raise AssertionError("dry-run should not call Feishu")

    monkeypatch.setattr(run_feishu_jin10_detail_smoke, "_collect_messages", fail_collect)

    exit_code = run_feishu_jin10_detail_smoke.main(
        [
            "--dry-run",
            "--no-env-file",
            "--storage-root",
            str(tmp_path),
            "--retrieved-date",
            "2026-06-11",
            "--run-id",
            "dry-run-test",
        ]
    )

    assert exit_code == 0
    assert list(tmp_path.iterdir()) == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_status"] == "dry_run"
    assert "raw/news/jin10_feishu/<retrieved_date>/messages-page-*.json" in payload["planned_writes"]
    assert "features/news/<retrieved_date>/<run_id>/daily_analysis_triggers.json" in payload["planned_writes"]


def test_collects_messages_fetches_detail_links_and_writes_summary(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_collect(**kwargs: Any) -> NewsCollectionResult:
        calls.append({"collect": kwargs})
        return NewsCollectionResult(
            source_key="jin10_feishu",
            status="success",
            items=[
                _raw_item("霍尔木兹风险推升油价和通胀，黄金关注美联储降息", "https://xnews.jin10.com/details/1"),
                _raw_item("飞书本地消息", "feishu://messages/om_1"),
                _raw_item("黄金技术图", "https://flash.jin10.com/detail/2"),
            ],
            source_refs=[{"source_ref": "jin10_feishu:oc_test", "status": "available"}],
        )

    def fake_fetch(**kwargs: Any) -> Jin10DetailFetchResult:
        calls.append({"fetch": kwargs})
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"] + "?opened=1",
            status="fetched",
            access_status="readable",
            content_type="text/html; charset=utf-8",
            title="金十详情页",
            raw_text="霍尔木兹风险正文",
            raw_html_path="raw/news/jin10_detail_pages/2026-06-11/detail.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-06-11/detail.json",
            image_assets=[
                {
                    "seq": 1,
                    "path": "raw/news/jin10_detail_pages/2026-06-11/images/chart.png",
                    "vlm_eligible": True,
                }
            ],
            image_insights=[{"seq": 1, "status": "ok", "markdown": "图表解析"}],
            fetched_at="2026-06-11T00:00:02+00:00",
        )

    monkeypatch.setattr(run_feishu_jin10_detail_smoke, "_collect_messages", fake_collect)
    monkeypatch.setattr(run_feishu_jin10_detail_smoke, "_fetch_detail_page", fake_fetch)

    exit_code = run_feishu_jin10_detail_smoke.main(
        [
            "--no-env-file",
            "--storage-root",
            str(tmp_path),
            "--retrieved-date",
            "2026-06-11",
            "--run-id",
            "detail-smoke-test",
            "--max-items",
            "1",
            "--run-vlm",
            "--min-vlm-width",
            "800",
            "--min-vlm-height",
            "400",
            "--min-vlm-bytes",
            "20000",
        ]
    )

    assert exit_code == 0
    assert calls[0]["collect"]["page_size"] == 20
    assert len([call for call in calls if "fetch" in call]) == 1
    fetch_kwargs = calls[1]["fetch"]
    assert fetch_kwargs["url"] == "https://xnews.jin10.com/details/1"
    assert fetch_kwargs["run_vlm"] is True
    assert fetch_kwargs["min_vlm_width"] == 800
    assert fetch_kwargs["min_vlm_height"] == 400
    assert fetch_kwargs["min_vlm_bytes"] == 20000

    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_status"] == "success"
    assert payload["collection"]["item_count"] == 3
    assert payload["detail_fetch"]["requested_count"] == 1
    assert payload["detail_fetch"]["fetched_count"] == 1
    assert payload["detail_fetch"]["vlm_insight_count"] == 1
    assert payload["article_briefs"]["brief_count"] == 1
    assert payload["article_briefs"]["artifact_path"] == "features/news/2026-06-11/detail-smoke-test/jin10_article_briefs.json"
    assert payload["daily_analysis_triggers"]["artifact_path"] == (
        "features/news/2026-06-11/detail-smoke-test/daily_analysis_triggers.json"
    )
    assert (tmp_path / payload["artifact_path"]).exists()
    assert (tmp_path / payload["article_briefs"]["artifact_path"]).exists()
    assert (tmp_path / payload["daily_analysis_triggers"]["artifact_path"]).exists()


def test_collects_detail_links_with_browser_profile_fallback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    calls: list[dict[str, Any]] = []
    profile_dir = tmp_path / "jin10-profile"
    profile_dir.mkdir()
    target_url = "https://xnews.jin10.com/details/221732"

    def fake_collect(**kwargs: Any) -> NewsCollectionResult:
        return NewsCollectionResult(
            source_key="jin10_feishu",
            status="success",
            items=[
                _raw_item(
                    "美伊冲突结束预期升温，但降息空间压缩，金价上行空间收窄。",
                    target_url,
                )
            ],
            source_refs=[{"source_ref": "jin10_feishu:oc_test", "status": "available"}],
        )

    def fake_fetch(**kwargs: Any) -> Jin10DetailFetchResult:
        calls.append(kwargs)
        assert kwargs["run_browser_fallback"] is True
        assert kwargs["browser_profile"] == profile_dir
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="readable",
            content_type="text/html; rendered=playwright",
            title="金价的上行空间相较战前已经收窄",
            raw_text=(
                "浏览器登录态完整正文：美伊冲突结束预期升温，但美国经济韧性压缩降息空间，"
                "油价回落也难带来鸽派反转，黄金继续受美元和美债收益率约束。"
            ),
            raw_html_path="raw/news/jin10_detail_pages/2026-06-12/221732-browser.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-06-12/221732-browser.json",
            fetched_at="2026-06-12T02:30:00+00:00",
            fetch_method="browser_profile",
            browser_fallback_attempted=True,
            browser_fallback_status="success",
        )

    monkeypatch.setattr(run_feishu_jin10_detail_smoke, "_collect_messages", fake_collect)
    monkeypatch.setattr(run_feishu_jin10_detail_smoke, "_fetch_detail_page", fake_fetch)

    exit_code = run_feishu_jin10_detail_smoke.main(
        [
            "--no-env-file",
            "--storage-root",
            str(tmp_path),
            "--retrieved-date",
            "2026-06-12",
            "--run-id",
            "detail-browser-fallback",
            "--max-items",
            "1",
            "--run-browser-fallback",
            "--browser-profile",
            str(profile_dir),
        ]
    )

    assert exit_code == 0
    assert len(calls) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_browser_fallback"] is True
    assert payload["browser_profile_exists"] is True
    assert payload["detail_fetch"]["browser_fallback_attempted_count"] == 1
    assert payload["detail_fetch"]["browser_fallback_success_count"] == 1
    result = payload["detail_fetch"]["results"][0]
    assert result["fetch_method"] == "browser_profile"
    assert result["browser_fallback_status"] == "success"
    brief = payload["article_briefs"]["briefs"][0]
    assert brief["access_status"] == "readable"
    assert brief["display_bucket"] == "重点分析"
    assert brief["detail_artifacts"]["fetch_method"] == "browser_profile"
    assert "需要金十 VIP 登录态" not in brief["analysis_summary"]
    assert "浏览器登录态完整正文" in brief["original_excerpt"]


def test_prioritizes_gold_macro_xnews_for_detail_fetch_and_daily_trigger(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    calls: list[dict[str, Any]] = []
    target_url = "https://xnews.jin10.com/details/221732?j=9868-0006"

    def fake_collect(**kwargs: Any) -> NewsCollectionResult:
        return NewsCollectionResult(
            source_key="jin10_feishu",
            status="success",
            items=[
                _raw_item("G7官员：美伊谅解备忘录可能周日签署", "https://flash.jin10.com/detail/1"),
                _raw_item("原油跌向85美元，市场真信霍尔木兹要开了？", "https://xnews.jin10.com/details/221790"),
                _raw_item(
                    "美伊冲突结束的预期再次升温，但美国自身经济韧性已将降息空间压缩，"
                    "油价回落也难带来鸽派反转？金价的上行空间相较战前已经收窄。",
                    target_url,
                ),
            ],
            source_refs=[{"source_ref": "jin10_feishu:oc_test", "status": "available"}],
        )

    def fake_fetch(**kwargs: Any) -> Jin10DetailFetchResult:
        calls.append({"fetch": kwargs})
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="vip_locked",
            content_type="text/html; charset=utf-8",
            title="金价的上行空间相较战前已经收窄",
            raw_text="美伊冲突结束预期升温，降息空间压缩，油价回落难带来鸽派反转，金价上行空间收窄。",
            raw_html_path="raw/news/jin10_detail_pages/2026-06-12/221732.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-06-12/221732.json",
            fetched_at="2026-06-12T02:30:00+00:00",
        )

    monkeypatch.setattr(run_feishu_jin10_detail_smoke, "_collect_messages", fake_collect)
    monkeypatch.setattr(run_feishu_jin10_detail_smoke, "_fetch_detail_page", fake_fetch)

    exit_code = run_feishu_jin10_detail_smoke.main(
        [
            "--no-env-file",
            "--storage-root",
            str(tmp_path),
            "--retrieved-date",
            "2026-06-12",
            "--run-id",
            "detail-smoke-221732",
            "--max-items",
            "1",
        ]
    )

    assert exit_code == 0
    assert [call["fetch"]["url"] for call in calls] == [target_url]

    payload = json.loads(capsys.readouterr().out)
    assert payload["daily_analysis_triggers"]["trigger_count"] >= 1
    assert any(
        trigger["source_url"] == target_url
        and trigger["trigger_type"] == "jin10_daily_analysis"
        and trigger["status"] == "queued"
        for trigger in payload["daily_analysis_triggers"]["triggers"]
    )
    assert payload["article_briefs"]["briefs"][0]["source_url"] == target_url


def test_env_file_loader_only_sets_dedicated_missing_keys(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "FEISHU_NEWS_APP_ID=cli_from_file",
                "FEISHU_NEWS_APP_SECRET='secret_from_file'",
                "FEISHU_JIN10_CHAT_ID=oc_from_file",
                "LARK_APP_SECRET=must_not_load",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("FEISHU_NEWS_APP_ID", raising=False)
    monkeypatch.setenv("FEISHU_NEWS_APP_SECRET", "existing_secret")
    monkeypatch.delenv("FEISHU_JIN10_CHAT_ID", raising=False)
    monkeypatch.delenv("LARK_APP_SECRET", raising=False)

    loaded = run_feishu_jin10_detail_smoke._load_env_file(env_file)

    assert loaded == ["FEISHU_NEWS_APP_ID", "FEISHU_JIN10_CHAT_ID"]
    assert run_feishu_jin10_detail_smoke.os.environ["FEISHU_NEWS_APP_ID"] == "cli_from_file"
    assert run_feishu_jin10_detail_smoke.os.environ["FEISHU_NEWS_APP_SECRET"] == "existing_secret"
    assert run_feishu_jin10_detail_smoke.os.environ["FEISHU_JIN10_CHAT_ID"] == "oc_from_file"
    assert run_feishu_jin10_detail_smoke.os.getenv("LARK_APP_SECRET") is None
