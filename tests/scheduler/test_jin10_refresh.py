from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.scheduler import jin10_refresh as scheduler
from apps.collectors.news.jin10_detail_fetcher import Jin10DetailFetchResult
from database.models.analysis import AppSetting, DataSourceStatus, MarketCandle, ensure_analysis_tables


class _FakeClient:
    def __init__(self, *args, **kwargs):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_kline(self, symbol: str, count: int = 100):
        assert symbol == "XAUUSD"
        assert count == 100
        return {
            "data": {
                "klines": [
                    {"time": 1780645620, "open": "4462.47", "high": "4464.30", "low": "4461.88", "close": "4462.81", "volume": 20},
                    {"time": 1780645680, "open": "4462.82", "high": "4463.11", "low": "4461.90", "close": "4463.04", "volume": 18},
                ]
            }
        }


def test_refresh_jin10_kline_cache_inserts_only_new_rows(monkeypatch):
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        ensure_analysis_tables(session)
        session.add(
            MarketCandle(
                asset="XAUUSD",
                timeframe="1m",
                open_time=datetime.fromtimestamp(1780645620, tz=UTC),
                open=4462.47,
                high=4464.30,
                low=4461.88,
                close=4462.81,
                volume=20,
                source="jin10_mcp_kline_1m",
            )
        )
        session.commit()

    monkeypatch.setattr(scheduler, "_get_mcp_key", lambda: "fake-key")
    monkeypatch.setattr(scheduler, "Jin10MCPClient", _FakeClient)
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)

    scheduler.refresh_jin10_kline_cache()

    with session_factory() as session:
        rows = session.query(MarketCandle).order_by(MarketCandle.open_time.asc()).all()
        assert len(rows) == 2
        latest_open_time = rows[-1].open_time
        if latest_open_time.tzinfo is None:
            latest_open_time = latest_open_time.replace(tzinfo=UTC)
        assert latest_open_time == datetime.fromtimestamp(1780645680, tz=UTC)
        assert rows[-1].close == 4463.04
        assert rows[-1].source == "jin10_mcp_kline_1m"
        assert rows[-1].source_ref["source_key"] == "jin10_mcp_market"
        assert rows[-1].source_ref["source"] == "jin10_mcp"


def test_refresh_market_candle_daily_cache_upserts_daily_assets(monkeypatch):
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    base_time = datetime(2026, 7, 6, tzinfo=UTC)

    def fake_collect_daily_market_candles(*, storage_root, asset: str, range_: str):
        assert range_ == "10d"
        offset = 0 if asset == "XAUUSD" else 1
        return (
            [
                {
                    "open_time": base_time - timedelta(days=offset),
                    "open": 4100.0 + offset,
                    "high": 4120.0 + offset,
                    "low": 4090.0 + offset,
                    "close": 4110.0 + offset,
                    "volume": 100.0 + offset,
                }
            ],
            f"raw/{asset.lower()}.json",
            f"test_source_{asset.lower()}",
            {"ticker": asset},
        )

    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(scheduler, "_collect_daily_market_candles", fake_collect_daily_market_candles)

    scheduler.refresh_market_candle_daily_cache()

    with session_factory() as session:
        rows = session.query(MarketCandle).order_by(MarketCandle.asset.asc()).all()
        assert [row.asset for row in rows] == ["DXY", "XAUUSD"]
        assert {row.timeframe for row in rows} == {"1d"}
        assert rows[0].source_ref["refresh_role"] == "scheduled_daily_gap_repair"
        assert rows[1].source_ref["refresh_role"] == "scheduled_daily_gap_repair"


class _FakeHttpResponse:
    def __init__(self, *, text: str = "", headers: dict[str, str] | None = None):
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        return None


class _FakeFlashHttpxClient:
    def __init__(self, *args, **kwargs):
        self._calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url: str, json: dict | None = None, headers: dict | None = None):
        self._calls += 1
        if self._calls == 1:
            return _FakeHttpResponse(headers={"Mcp-Session-Id": "sid-test"})
        if self._calls == 2:
            return _FakeHttpResponse()
        assert json is not None
        assert json.get("method") == "tools/call"
        items = [
            {"id": f"flash-{idx}", "time": f"2026-06-13 09:{idx:02d}:00", "content": f"headline-{idx}"}
            for idx in range(60)
        ]
        payload = {
            "result": {
                "structuredContent": {
                    "status": 200,
                    "data": {"items": items},
                }
            }
        }
        return _FakeHttpResponse(text=f"data:{json_module(payload)}\n")


class _FakeCalendarHttpxClient:
    def __init__(self, *args, **kwargs):
        self._calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url: str, json: dict | None = None, headers: dict | None = None):
        self._calls += 1
        if self._calls == 1:
            return _FakeHttpResponse(headers={"Mcp-Session-Id": "sid-test"})
        if self._calls == 2:
            return _FakeHttpResponse()
        assert json is not None
        assert json.get("method") == "tools/call"
        payload = {
            "result": {
                "structuredContent": {
                    "status": 200,
                    "data": [
                        {"title": "窗口前事件", "pub_time": "2026-06-16 20:30", "star": 5, "actual": None},
                        {"title": "窗口内事件", "pub_time": "2026-06-24 02:00", "star": 5, "actual": None},
                        {"title": "窗口后事件", "pub_time": "2026-07-07 20:30", "star": 5, "actual": None},
                    ],
                }
            }
        }
        return _FakeHttpResponse(text=f"data:{json_module(payload)}\n")


def json_module(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


class _FakeLLMResponse:
    def __init__(self, content: str, *, provider: str = "mimo", model: str = "mimo-small-test"):
        self.content = content
        self.provider = provider
        self.model = model
        self.latency_ms = 12
        self.usage = {}


def test_refresh_jin10_flash_cache_handles_data_items_shape(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        ensure_analysis_tables(session)
        session.commit()

    monkeypatch.setattr(scheduler, "_get_mcp_key", lambda: "fake-key")
    monkeypatch.setattr(scheduler, "_FLASH_CACHE_PATH", tmp_path / "flash_cache.json")
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    monkeypatch.setitem(sys.modules, "httpx", type("FakeHttpxModule", (), {"Client": _FakeFlashHttpxClient})())

    def fake_chat_sync(*, messages, provider, model, temperature, max_tokens, json_mode, max_retries):
        assert provider == "mimo"
        assert model == "mimo-v2.5"
        assert temperature == 0.0
        assert json_mode is True
        assert max_retries == 1
        assert "不要按固定关键词机械判断" in messages[0]["content"]
        labels = [
            {
                "index": idx,
                "is_key_event": idx == 0,
                "importance": "high" if idx == 0 else "normal",
                "signal_tags": ["risk_sentiment"] if idx == 0 else [],
                "filter_reason": "LLM semantic decision",
                "confidence": 0.91 if idx == 0 else 0.74,
                "summary_zh": "黄金与美元短线波动加大。" if idx == 0 else "",
            }
            for idx in range(50)
        ]
        return _FakeLLMResponse(json.dumps({"items": labels}, ensure_ascii=False))

    monkeypatch.setattr(scheduler, "chat_sync", fake_chat_sync)

    scheduler.refresh_jin10_flash_cache()

    payload = json.loads((tmp_path / "flash_cache.json").read_text(encoding="utf-8"))
    assert len(payload["items"]) == 50
    assert payload["items"][0]["id"] == "flash-0"
    assert payload["items"][0]["is_key_event"] is True
    assert payload["items"][0]["importance"] == "high"
    assert payload["items"][0]["signal_tags"] == ["risk_sentiment"]
    assert payload["items"][0]["classification_provider"] == "mimo"
    assert payload["items"][0]["classification_model"] == "mimo-small-test"
    assert payload["items"][0]["classification_confidence"] == 0.91
    assert payload["items"][0]["summary_zh"] == "黄金与美元短线波动加大。"
    assert payload["items"][-1]["id"] == "flash-49"
    assert payload["classification_version"] == "jin10-flash-semantic-llm-v2"
    assert payload["classification_provider"] == "mimo"
    assert payload["key_item_count"] == 1

    with session_factory() as session:
        status = session.query(DataSourceStatus).filter_by(source_key="jin10_flash").one()
        assert status.status == "ok"
        assert status.configured is True
        assert status.raw_ingested is True
        assert status.parsed is True
        assert status.analysis_ready is True
        assert status.row_count == 50
        assert status.source_metadata["key_item_count"] == 1
        assert status.source_metadata["classification_provider"] == "mimo"
        assert status.source_metadata["classification_model"] == "mimo-small-test"
        assert status.source_metadata["cache_artifact_path"].endswith("flash_cache.json")
        assert status.source_metadata["lane_source_key"] == "jin10_mcp_flash"


def test_refresh_jin10_calendar_cache_persists_only_display_window(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "_get_mcp_key", lambda: "fake-key")
    monkeypatch.setattr(scheduler, "_CALENDAR_CACHE_PATH", tmp_path / "calendar_cache.json")
    monkeypatch.setattr(
        scheduler,
        "_jin10_calendar_window",
        lambda now=None: (
            datetime(2026, 6, 17, tzinfo=UTC),
            datetime(2026, 7, 6, 23, 59, 59, tzinfo=UTC),
        ),
    )
    monkeypatch.setitem(sys.modules, "httpx", type("FakeHttpxModule", (), {"Client": _FakeCalendarHttpxClient})())

    scheduler.refresh_jin10_calendar_cache()

    payload = json.loads((tmp_path / "calendar_cache.json").read_text(encoding="utf-8"))
    assert [event["title"] for event in payload["events"]] == ["窗口内事件"]


def test_refresh_jin10_web_flash_briefs_archives_homepage_items(monkeypatch, tmp_path):
    fixed_now = datetime(2026, 7, 9, 2, 30, tzinfo=UTC)

    def fake_collect(**kwargs):
        assert kwargs["storage_root"] == tmp_path
        assert kwargs["retrieved_date"] == "2026-07-09"
        assert kwargs["run_id"] == "jin10-web-flash-20260709T023000Z"
        assert kwargs["fetched_at"] == fixed_now.isoformat()
        assert kwargs["user_data_dir"] == tmp_path / "profile"
        return {
            "status": "ok",
            "retrievedDate": "2026-07-09",
            "runId": "jin10-web-flash-20260709T023000Z",
            "rawArtifactPath": str(tmp_path / "storage/raw/jin10/web_flash/2026-07-09/run/home.html"),
            "parsedArtifactPath": str(tmp_path / "storage/parsed/jin10/web_flash/2026-07-09/run/web_flash_items.json"),
            "itemCount": 1,
            "items": [
                {
                    "itemId": "web-flash-1",
                    "sourceKey": "jin10_web_vip_flash",
                    "contentFamily": "web_vip_flash.vip_report_article",
                    "title": "VIP贵金属报告更新",
                    "summary": "黄金关键位和美联储路径重新定价。",
                    "publishedAt": "2026-07-09 10:29:00",
                    "url": "https://www.jin10.com/",
                    "importanceSource": "homepage",
                    "verificationStatus": "single_source",
                    "accessStatus": "readable",
                    "tags": ["XAUUSD"],
                    "linkedUrls": ["https://svip.jin10.com/news/223999"],
                    "imageUrls": [],
                    "sourceRefs": [{"source_key": "jin10_web_vip_flash"}],
                    "artifactRefs": [],
                }
            ],
            "qualityFlags": {},
            "sourceRefs": [{"source": "jin10_homepage"}],
        }

    monkeypatch.setattr(scheduler, "collect_jin10_web_flash_with_browser_profile", fake_collect)

    summary = scheduler.refresh_jin10_web_flash_briefs(
        storage_root=tmp_path,
        browser_profile=tmp_path / "profile",
        now=fixed_now,
    )

    assert summary == {
        "status": "ok",
        "retrieved_date": "2026-07-09",
        "run_id": "jin10-web-flash-20260709T023000Z",
        "item_count": 1,
        "brief_count": 1,
        "artifact_path": "storage/features/news/2026-07-09/jin10-web-flash-20260709T023000Z/jin10_web_flash_briefs.json",
        "raw_artifact_path": str(tmp_path / "storage/raw/jin10/web_flash/2026-07-09/run/home.html"),
        "parsed_artifact_path": str(tmp_path / "storage/parsed/jin10/web_flash/2026-07-09/run/web_flash_items.json"),
    }
    artifact = (
        tmp_path
        / "storage"
        / "features"
        / "news"
        / "2026-07-09"
        / "jin10-web-flash-20260709T023000Z"
        / "jin10_web_flash_briefs.json"
    )
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    inner = payload["jin10_web_flash_briefs"]
    assert inner["brief_count"] == 1
    assert inner["briefs"][0]["display_bucket"] == "VIP报告/文章"
    assert inner["briefs"][0]["data_quality"]["content_format"] == "report_article"


def test_refresh_jin10_web_article_analysis_fetches_latest_report_articles(monkeypatch, tmp_path):
    storage_root = tmp_path / "storage"
    latest_dir = storage_root / "features" / "news" / "2026-07-09" / "jin10-web-flash-run"
    latest_dir.mkdir(parents=True)
    (latest_dir / "jin10_web_flash_briefs.json").write_text(
        json.dumps(
            {
                "retrieved_date": "2026-07-09",
                "run_id": "jin10-web-flash-run",
                "jin10_web_flash_briefs": {
                    "as_of": "2026-07-09T02:29:49+00:00",
                    "briefs": [
                        {
                            "brief_id": "b1",
                            "item_id": "article-1",
                            "source_key": "jin10_web_important_flash",
                            "headline": "加息阴影笼罩，美银砍金价预期14%但重申5000美元目标",
                            "summary": "黄金相关图文",
                            "url": "https://xnews.jin10.com/details/224056",
                            "published_at": "07-09 10:05",
                            "priority_bucket": "P0",
                            "verification_status": "single_source",
                            "data_quality": {"content_format": "report_article", "linked_urls": []},
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def fake_fetch_jin10_detail_page(**kwargs):
        calls.append(kwargs)
        return Jin10DetailFetchResult(
            detail_url=kwargs["url"],
            final_url=kwargs["url"],
            status="fetched",
            access_status="readable",
            title="加息阴影笼罩",
            raw_text="美银下调短期金价预期，但维持长期5000美元目标。",
            raw_html_path="raw/news/jin10_detail_pages/2026-07-09/detail.html",
            parsed_path="parsed/news/jin10_detail_pages/2026-07-09/detail.json",
            image_assets=[{"seq": 1, "path": "raw/news/jin10_detail_pages/2026-07-09/images/01.png", "vlm_eligible": True}],
            image_insights=[{"seq": 1, "status": "ok", "markdown": "图表显示金价预期路径。"}],
            fetched_at="2026-07-09T02:31:00+00:00",
        )

    monkeypatch.setattr(scheduler, "fetch_jin10_detail_page", fake_fetch_jin10_detail_page)

    summary = scheduler.refresh_jin10_web_article_analysis(
        storage_root=storage_root,
        browser_profile=tmp_path / "profile",
        now=datetime(2026, 7, 9, 2, 31, tzinfo=UTC),
    )

    assert summary["status"] == "ok"
    assert summary["candidate_count"] == 1
    assert summary["brief_count"] == 1
    assert calls[0]["url"] == "https://xnews.jin10.com/details/224056"
    assert calls[0]["run_vlm"] is True
    assert calls[0]["browser_profile"] == tmp_path / "profile"
    artifact = storage_root / summary["artifact_path"]
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["brief_count"] == 1
    assert payload["briefs"][0]["detail_artifacts"]["vlm_insight_count"] == 1


def test_refresh_jin10_flash_cache_respects_disabled_jin10_mcp_setting(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", echo=False)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        ensure_analysis_tables(session)
        session.add(
            AppSetting(
                setting_key="source.jin10_mcp.enabled",
                scope="source",
                source_key="jin10_mcp",
                value_json={"enabled": False},
            )
        )
        session.commit()

    monkeypatch.setattr(scheduler, "_FLASH_CACHE_PATH", tmp_path / "flash_cache.json")
    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(scheduler, "_get_mcp_key", lambda: "fake-key")
    monkeypatch.setitem(
        sys.modules,
        "httpx",
        type("UnexpectedHttpxModule", (), {"Client": lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("httpx should not be called"))})(),
    )

    scheduler.refresh_jin10_flash_cache()

    assert not (tmp_path / "flash_cache.json").exists()
    with session_factory() as session:
        status = session.query(DataSourceStatus).filter_by(source_key="jin10_flash").one()
        assert status.status == "disabled"
        assert status.configured is False
        assert status.raw_ingested is False
        assert status.error_message == "disabled_by_settings: source.jin10_mcp.enabled=false"


def test_classify_jin10_flash_items_with_llm_uses_semantic_labels(monkeypatch):
    def fake_chat_sync(**kwargs):
        assert kwargs["provider"] == "mimo"
        return _FakeLLMResponse(
            json.dumps(
                {
                    "items": [
                        {
                            "index": 0,
                            "is_key_event": True,
                            "importance": "medium",
                            "signal_tags": ["shipping_chokepoint", "oil"],
                            "filter_reason": "航运咽喉风险可能传导至油价和避险情绪",
                            "confidence": 0.86,
                            "summary_zh": "航运成本与原油风险溢价可能继续上行。",
                        },
                        {
                            "index": 1,
                            "is_key_event": False,
                            "importance": "normal",
                            "signal_tags": ["low_signal_followup"],
                            "filter_reason": "伤亡统计缺少新增市场传导",
                            "confidence": 0.88,
                        },
                    ]
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(scheduler, "chat_sync", fake_chat_sync)

    result = scheduler.classify_jin10_flash_items_with_llm(
        [
            {"id": "a", "content": "某海峡附近出现新的航运保险费率飙升迹象。"},
            {"id": "b", "content": "某机构更新伤亡统计。"},
        ]
    )

    assert result[0]["is_key_event"] is True
    assert result[0]["importance"] == "medium"
    assert result[0]["signal_tags"] == ["shipping_chokepoint", "oil"]
    assert result[0]["classification_provider"] == "mimo"
    assert result[0]["classification_model"] == "mimo-small-test"
    assert result[0]["summary_zh"] == "航运成本与原油风险溢价可能继续上行。"
    assert result[1]["is_key_event"] is False
    assert result[1]["filter_reason"] == "伤亡统计缺少新增市场传导"


def test_classify_jin10_flash_items_with_llm_falls_back_when_unavailable(monkeypatch):
    def fake_chat_sync(**kwargs):
        raise RuntimeError("mimo unavailable")

    monkeypatch.setattr(scheduler, "chat_sync", fake_chat_sync)

    result = scheduler.classify_jin10_flash_items_with_llm(
        [
            {
                "content": "【伊朗称霍尔木兹收服务费完全合理】金十数据6月13日讯，伊朗外长表示正在就霍尔木兹海峡通航问题进行磋商。",
                "time": "2026-06-13T19:54:58+08:00",
            }
        ]
    )

    assert result[0]["is_key_event"] is True
    assert result[0]["classification_provider"] == "fallback_rule"
    assert result[0]["classification_model"] == ""


def test_classify_jin10_flash_item_fallback_marks_key_events():
    strategic = scheduler.classify_jin10_flash_item_fallback(
        {
            "content": "【伊朗称霍尔木兹收服务费完全合理】金十数据6月13日讯，伊朗外长表示正在就霍尔木兹海峡通航问题进行磋商。",
            "time": "2026-06-13T19:54:58+08:00",
        }
    )
    assert strategic["is_key_event"] is True
    assert strategic["importance"] == "high"
    assert "strategic_channel" in strategic["signal_tags"]
    assert strategic["classification_provider"] == "fallback_rule"

    escalation = scheduler.classify_jin10_flash_item_fallback(
        {
            "content": "黎巴嫩真主党：我们在黎巴嫩南部用导弹击落了一架以色列无人机。",
            "time": "2026-06-13T19:58:11+08:00",
        }
    )
    assert escalation["is_key_event"] is True
    assert "geopolitical_escalation" in escalation["signal_tags"]

    low_signal = scheduler.classify_jin10_flash_item_fallback(
        {
            "content": "联合国：自以色列攻势开始以来，黎巴嫩已有135名医务工作者遇害。",
            "time": "2026-06-13T19:57:52+08:00",
        }
    )
    assert low_signal["is_key_event"] is False
    assert low_signal["filter_reason"] == "low_signal_followup"
