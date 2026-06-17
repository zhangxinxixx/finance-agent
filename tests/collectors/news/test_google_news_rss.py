from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from apps.collectors.news.google_news_rss import collect_google_news_rss


GOOGLE_NEWS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <item>
      <title>Gold rises as Treasury yields slip before Fed decision</title>
      <link>https://news.google.com/rss/articles/gold-fed</link>
      <description><![CDATA[<a href="https://www.reuters.com/markets/commodities/gold-fed">Gold rises</a>]]></description>
      <pubDate>Wed, 10 Jun 2026 12:15:00 GMT</pubDate>
      <source url="https://www.reuters.com/markets/commodities/gold-fed">Reuters</source>
    </item>
  </channel>
</rss>
"""


class FakeGoogleNewsClient:
    def __init__(self, responses: dict[str, httpx.Response | Exception]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, params: dict[str, object]) -> httpx.Response:
        self.requests.append((url, params))
        result = self.responses[str(params["q"])]
        if isinstance(result, Exception):
            raise result
        return result


def _response(url: str, body: str) -> httpx.Response:
    return httpx.Response(200, content=body.encode("utf-8"), request=httpx.Request("GET", url))


def test_google_news_rss_maps_items_to_candidate_raw_news_items(tmp_path: Path) -> None:
    client = FakeGoogleNewsClient({
        "gold XAU Treasury yields Fed dollar": _response("https://news.google.com/rss/search", GOOGLE_NEWS_FIXTURE)
    })

    result = collect_google_news_rss(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"gold_macro": "gold XAU Treasury yields Fed dollar"},
        client=client,
    )

    assert result.status == "success"
    assert result.unavailable_feeds == []
    assert len(result.items) == 1

    item = result.items[0]
    assert item.source_key == "google_news_rss"
    assert item.source_name == "Google News RSS"
    assert item.source_type == "aggregator"
    assert item.feed_key == "gold_macro"
    assert item.title == "Gold rises as Treasury yields slip before Fed decision"
    assert item.url == "https://news.google.com/rss/articles/gold-fed"
    assert item.domain == "reuters.com"
    assert item.published_at == "2026-06-10T12:15:00+00:00"
    assert item.summary == "Gold rises"
    assert item.source_language == "en"
    assert item.event_type == "gold_market_narrative"
    assert item.verification_status == "single_source"
    assert item.duplicate_key.startswith("news:google_news_rss:")
    assert item.raw_payload["publisher"] == "Reuters"
    assert item.raw_payload["publisher_url"] == "https://www.reuters.com/markets/commodities/gold-fed"
    assert item.raw_path.startswith("raw/news/google_news_rss/2026-06-10/gold_macro-")
    assert item.parsed_path.startswith("parsed/news/google_news_rss/2026-06-10/gold_macro-")
    assert (tmp_path / item.raw_path).exists()
    assert (tmp_path / item.parsed_path).exists()

    assert client.requests[0][1]["hl"] == "en-US"
    assert client.requests[0][1]["gl"] == "US"
    assert client.requests[0][1]["ceid"] == "US:en"


def test_google_news_rss_limits_query_group_items(tmp_path: Path) -> None:
    feed = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>Iran headline 0</title><link>https://news.google.com/rss/articles/0</link><pubDate>Wed, 10 Jun 2026 12:00:00 GMT</pubDate></item>
  <item><title>Iran headline 1</title><link>https://news.google.com/rss/articles/1</link><pubDate>Wed, 10 Jun 2026 12:01:00 GMT</pubDate></item>
  <item><title>Iran headline 2</title><link>https://news.google.com/rss/articles/2</link><pubDate>Wed, 10 Jun 2026 12:02:00 GMT</pubDate></item>
</channel></rss>
"""
    client = FakeGoogleNewsClient({"Iran Israel Hormuz ceasefire sanctions oil tanker": _response("https://news.google.com/rss/search", feed)})

    result = collect_google_news_rss(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"middle_east": "Iran Israel Hormuz ceasefire sanctions oil tanker"},
        max_items_per_group=2,
        client=client,
    )

    assert result.status == "success"
    assert len(result.items) == 2
    assert [item.title for item in result.items] == ["Iran headline 0", "Iran headline 1"]
    assert all(item.verification_status == "single_source" for item in result.items)


def test_google_news_rss_partial_failure_keeps_successful_query_groups(tmp_path: Path) -> None:
    client = FakeGoogleNewsClient({
        "gold XAU Treasury yields Fed dollar": _response("https://news.google.com/rss/search", GOOGLE_NEWS_FIXTURE),
        "Brent WTI OPEC EIA crude stocks gasoline stocks": httpx.ConnectError("connection refused"),
    })

    result = collect_google_news_rss(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={
            "gold_macro": "gold XAU Treasury yields Fed dollar",
            "oil": "Brent WTI OPEC EIA crude stocks gasoline stocks",
        },
        client=client,
    )

    assert result.status == "partial"
    assert [item.feed_key for item in result.items] == ["gold_macro"]
    assert result.unavailable_feeds == ["oil"]
    assert result.source_refs[0]["status"] == "available"
    assert result.source_refs[-1]["status"] == "network_blocked"
    assert result.source_refs[-1]["reason_code"] == "network_blocked"
    assert "warning" not in result.source_refs[0]
    assert result.source_refs[-1]["warning"] == result.warnings[0]
    assert "network_blocked" in result.warnings[0]


def test_google_news_rss_invalid_xml_marks_feed_unavailable(tmp_path: Path) -> None:
    client = FakeGoogleNewsClient({
        "gold XAU Treasury yields Fed dollar": _response("https://news.google.com/rss/search", "<rss><broken>")
    })

    result = collect_google_news_rss(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"gold_macro": "gold XAU Treasury yields Fed dollar"},
        client=client,
    )

    assert result.status == "unavailable"
    assert result.unavailable_feeds == ["gold_macro"]
    assert result.source_refs[0]["status"] == "unavailable"
    assert result.source_refs[0]["reason_code"] == "invalid_payload"
    assert result.source_refs[0]["warning"] == result.warnings[0]


def test_google_news_rss_rate_limit_is_explicit_in_source_ref_status(tmp_path: Path) -> None:
    request = httpx.Request("GET", "https://news.google.com/rss/search")
    response = httpx.Response(429, request=request)
    error = httpx.HTTPStatusError("rate limited", request=request, response=response)
    client = FakeGoogleNewsClient({"Brent WTI OPEC EIA crude stocks gasoline stocks": error})

    result = collect_google_news_rss(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"oil": "Brent WTI OPEC EIA crude stocks gasoline stocks"},
        client=client,
    )

    assert result.status == "unavailable"
    assert result.unavailable_feeds == ["oil"]
    assert result.source_refs[0]["status"] == "rate_limited"
    assert result.source_refs[0]["reason_code"] == "rate_limited"
    assert result.source_refs[0]["warning"] == result.warnings[0]


def test_google_news_rss_uses_explicit_request_timeout_when_creating_httpx_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeHttpxClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def __enter__(self) -> "FakeHttpxClient":
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def get(self, url: str, params: dict[str, object]) -> httpx.Response:
            return _response(url, GOOGLE_NEWS_FIXTURE)

    monkeypatch.setattr("apps.collectors.news.google_news_rss.httpx.Client", FakeHttpxClient)

    result = collect_google_news_rss(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"gold_macro": "gold XAU Treasury yields Fed dollar"},
        request_timeout=3.5,
    )

    assert result.status == "success"
    assert captured["timeout"] == 3.5
    assert captured["headers"] == {"User-Agent": "finance-agent/0.1"}
    assert captured["trust_env"] is True


def test_google_news_rss_allows_disabling_env_proxy_and_passing_explicit_proxy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeHttpxClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def __enter__(self) -> "FakeHttpxClient":
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def get(self, url: str, params: dict[str, object]) -> httpx.Response:
            return _response(url, GOOGLE_NEWS_FIXTURE)

    monkeypatch.setattr("apps.collectors.news.google_news_rss.httpx.Client", FakeHttpxClient)

    result = collect_google_news_rss(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"gold_macro": "gold XAU Treasury yields Fed dollar"},
        request_proxy="http://127.0.0.1:7890",
        trust_env=False,
    )

    assert result.status == "success"
    assert captured["proxy"] == "http://127.0.0.1:7890"
    assert captured["trust_env"] is False
