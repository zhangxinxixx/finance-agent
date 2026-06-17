from __future__ import annotations

from pathlib import Path

import httpx

from apps.collectors.news.reuters_public import collect_reuters_public_news


REUTERS_PUBLIC_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Reuters - Google News</title>
    <item>
      <title>Gold steadies as dollar weakens before Fed rate decision</title>
      <link>https://news.google.com/rss/articles/reuters-gold-fed</link>
      <description><![CDATA[<a href="https://www.reuters.com/markets/commodities/gold-fed">Gold steadies</a>]]></description>
      <pubDate>Wed, 10 Jun 2026 13:30:00 GMT</pubDate>
      <source url="https://www.reuters.com/markets/commodities/gold-fed">Reuters</source>
    </item>
  </channel>
</rss>
"""


class FakeReutersPublicClient:
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


def test_reuters_public_maps_public_metadata_to_candidate_items(tmp_path: Path) -> None:
    query = "site:reuters.com gold XAU Treasury yields Fed dollar"
    client = FakeReutersPublicClient({query: _response("https://news.google.com/rss/search", REUTERS_PUBLIC_FIXTURE)})

    result = collect_reuters_public_news(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"gold_macro": query},
        client=client,
    )

    assert result.status == "success"
    assert result.unavailable_feeds == []
    assert len(result.items) == 1
    assert result.source_refs[0]["status"] == "available"
    assert result.source_refs[0]["authorized_wire"] is False
    assert result.source_refs[0]["candidate_scope"] == "public_metadata_only"
    assert "warning" not in result.source_refs[0]

    item = result.items[0]
    assert item.source_key == "reuters_public_news"
    assert item.source_name == "Reuters Public Metadata"
    assert item.source_type == "wire_public_candidate"
    assert item.feed_key == "gold_macro"
    assert item.title == "Gold steadies as dollar weakens before Fed rate decision"
    assert item.url == "https://news.google.com/rss/articles/reuters-gold-fed"
    assert item.domain == "reuters.com"
    assert item.published_at == "2026-06-10T13:30:00+00:00"
    assert item.summary == "Gold steadies"
    assert item.event_type == "gold_market_narrative"
    assert item.verification_status == "single_source"
    assert item.raw_payload["authorized_wire"] is False
    assert item.raw_payload["discovery_method"] == "google_news_rss_site_filter"
    assert item.raw_payload["publisher_url"] == "https://www.reuters.com/markets/commodities/gold-fed"
    assert item.raw_path.startswith("raw/news/reuters_public/2026-06-10/gold_macro-")
    assert item.parsed_path.startswith("parsed/news/reuters_public/2026-06-10/gold_macro-")

    assert client.requests[0][1]["hl"] == "en-US"
    assert "site:reuters.com" in str(client.requests[0][1]["q"])


def test_reuters_public_filters_non_reuters_items(tmp_path: Path) -> None:
    query = "site:reuters.com Iran Hormuz"
    feed = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Non Reuters headline</title>
    <link>https://news.google.com/rss/articles/not-reuters</link>
    <pubDate>Wed, 10 Jun 2026 13:30:00 GMT</pubDate>
    <source url="https://example.com/article">Example</source>
  </item>
</channel></rss>
"""
    client = FakeReutersPublicClient({query: _response("https://news.google.com/rss/search", feed)})

    result = collect_reuters_public_news(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"middle_east_hormuz": query},
        client=client,
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.source_refs[0]["status"] == "empty"
    assert result.source_refs[0]["reason_code"] == "no_public_candidates"
    assert result.source_refs[0]["authorized_wire"] is False
    assert result.source_refs[0]["candidate_scope"] == "public_metadata_only"
    assert result.source_refs[0]["warning"] == result.warnings[0]
    assert "authorized_wire=false" in result.warnings[0]


def test_reuters_public_partial_failure_keeps_successful_query_groups(tmp_path: Path) -> None:
    success_query = "site:reuters.com gold XAU Treasury yields Fed dollar"
    failed_query = "site:reuters.com Brent WTI OPEC"
    client = FakeReutersPublicClient({
        success_query: _response("https://news.google.com/rss/search", REUTERS_PUBLIC_FIXTURE),
        failed_query: httpx.ConnectError("connection refused"),
    })

    result = collect_reuters_public_news(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={
            "gold_macro": success_query,
            "oil_supply": failed_query,
        },
        client=client,
    )

    assert result.status == "partial"
    assert [item.feed_key for item in result.items] == ["gold_macro"]
    assert result.unavailable_feeds == ["oil_supply"]
    assert result.source_refs[0]["status"] == "available"
    assert result.source_refs[-1]["status"] == "network_blocked"
    assert result.source_refs[-1]["reason_code"] == "network_blocked"
    assert result.source_refs[-1]["authorized_wire"] is False
    assert "warning" not in result.source_refs[0]
    assert result.source_refs[-1]["warning"] == result.warnings[0]


def test_reuters_public_rate_limit_is_explicit_in_source_ref_status(tmp_path: Path) -> None:
    query = "site:reuters.com Brent WTI OPEC"
    request = httpx.Request("GET", "https://news.google.com/rss/search")
    response = httpx.Response(429, request=request)
    error = httpx.HTTPStatusError("rate limited", request=request, response=response)
    client = FakeReutersPublicClient({query: error})

    result = collect_reuters_public_news(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"oil_supply": query},
        client=client,
    )

    assert result.status == "unavailable"
    assert result.unavailable_feeds == ["oil_supply"]
    assert result.source_refs[0]["status"] == "rate_limited"
    assert result.source_refs[0]["reason_code"] == "rate_limited"
    assert result.source_refs[0]["authorized_wire"] is False
    assert result.source_refs[0]["warning"] == result.warnings[0]


def test_reuters_public_uses_explicit_request_timeout_for_internal_client(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    query = "site:reuters.com gold XAU Treasury yields Fed dollar"
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def get(self, url: str, params: dict[str, object]) -> httpx.Response:
            return _response("https://news.google.com/rss/search", REUTERS_PUBLIC_FIXTURE)

    monkeypatch.setattr("apps.collectors.news.reuters_public.httpx.Client", FakeClient)

    result = collect_reuters_public_news(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"gold_macro": query},
        request_timeout=3.5,
    )

    assert result.status == "success"
    assert captured["timeout"] == 3.5
    assert captured["headers"] == {"User-Agent": "finance-agent/0.1"}
    assert captured["trust_env"] is True


def test_reuters_public_allows_disabling_env_proxy_and_passing_explicit_proxy(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    query = "site:reuters.com gold XAU Treasury yields Fed dollar"
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def get(self, url: str, params: dict[str, object]) -> httpx.Response:
            return _response("https://news.google.com/rss/search", REUTERS_PUBLIC_FIXTURE)

    monkeypatch.setattr("apps.collectors.news.reuters_public.httpx.Client", FakeClient)

    result = collect_reuters_public_news(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"gold_macro": query},
        request_proxy="http://127.0.0.1:7890",
        trust_env=False,
    )

    assert result.status == "success"
    assert captured["proxy"] == "http://127.0.0.1:7890"
    assert captured["trust_env"] is False
