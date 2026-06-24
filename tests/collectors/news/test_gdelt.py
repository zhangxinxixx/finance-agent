from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from apps.collectors.news.gdelt import collect_gdelt_docs


class FakeGdeltClient:
    def __init__(self, responses: dict[str, httpx.Response | Exception]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, params: dict[str, object]) -> httpx.Response:
        self.requests.append((url, params))
        result = self.responses[str(params["query"])]
        if isinstance(result, Exception):
            raise result
        return result


def _response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc"))


def test_gdelt_doc_items_map_to_candidate_raw_news_items(tmp_path: Path) -> None:
    client = FakeGdeltClient({
        'Iran Hormuz oil': _response({
            "articles": [
                {
                    "title": "Iran warns over Strait of Hormuz shipping",
                    "url": "https://example.com/hormuz",
                    "domain": "Example.com",
                    "sourceCountry": "United States",
                    "language": "English",
                    "seendate": "20260609151500",
                    "socialimage": "https://example.com/image.jpg",
                }
            ]
        })
    })

    result = collect_gdelt_docs(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"middle_east_hormuz": "Iran Hormuz oil"},
        client=client,
    )

    assert result.status == "success"
    assert result.unavailable_feeds == []
    assert len(result.items) == 1

    item = result.items[0]
    assert item.source_key == "gdelt_news"
    assert item.source_name == "GDELT DOC 2.0"
    assert item.source_type == "aggregator"
    assert item.feed_key == "middle_east_hormuz"
    assert item.title == "Iran warns over Strait of Hormuz shipping"
    assert item.url == "https://example.com/hormuz"
    assert item.domain == "example.com"
    assert item.source_country == "United States"
    assert item.source_language == "English"
    assert item.published_at == "2026-06-09T15:15:00+00:00"
    assert item.event_type == "hormuz_risk"
    assert item.verification_status == "single_source"
    assert item.duplicate_key.startswith("news:gdelt_news:")
    assert item.raw_payload["query_group"] == "middle_east_hormuz"
    assert item.raw_payload["image_url"] == "https://example.com/image.jpg"
    assert item.raw_path.startswith("raw/news/gdelt/2026-06-10/middle_east_hormuz-")
    assert item.parsed_path.startswith("parsed/news/gdelt/2026-06-10/middle_east_hormuz-")
    assert (tmp_path / item.raw_path).exists()
    assert (tmp_path / item.parsed_path).exists()

    assert client.requests[0][1]["mode"] == "artlist"
    assert client.requests[0][1]["format"] == "json"
    assert client.requests[0][1]["sort"] == "datedesc"
    assert client.requests[0][1]["maxrecords"] == 50


def test_gdelt_doc_uses_explicit_request_timeout_when_creating_http_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self, **kwargs: object) -> None:
            captured["kwargs"] = kwargs

        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, params: dict[str, object]) -> httpx.Response:
            request = httpx.Request("GET", url)
            return httpx.Response(200, json={"articles": []}, request=request)

    monkeypatch.setattr("apps.collectors.news.gdelt.httpx.Client", DummyClient)

    result = collect_gdelt_docs(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"fed_inflation": "Fed inflation"},
        request_timeout=3.5,
    )

    assert result.status == "unavailable"
    assert captured["kwargs"]["timeout"] == 3.5
    assert captured["kwargs"]["headers"] == {"User-Agent": "finance-agent/0.1"}
    assert captured["kwargs"]["trust_env"] is True


def test_gdelt_doc_allows_disabling_env_proxy_and_passing_explicit_proxy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self, **kwargs: object) -> None:
            captured["kwargs"] = kwargs

        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, params: dict[str, object]) -> httpx.Response:
            request = httpx.Request("GET", url)
            return httpx.Response(200, json={"articles": []}, request=request)

    monkeypatch.setattr("apps.collectors.news.gdelt.httpx.Client", DummyClient)

    collect_gdelt_docs(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"fed_inflation": "Fed inflation"},
        request_proxy="http://127.0.0.1:7890",
        trust_env=False,
    )

    assert captured["kwargs"]["proxy"] == "http://127.0.0.1:7890"
    assert captured["kwargs"]["trust_env"] is False


def test_gdelt_doc_query_groups_are_limited(tmp_path: Path) -> None:
    articles = [
        {
            "title": f"Federal Reserve headline {index}",
            "url": f"https://example.com/fed-{index}",
            "domain": "example.com",
            "seendate": "20260609151500",
        }
        for index in range(5)
    ]
    client = FakeGdeltClient({'Fed inflation': _response({"articles": articles})})

    result = collect_gdelt_docs(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"fed_inflation": "Fed inflation"},
        max_items_per_group=3,
        client=client,
    )

    assert result.status == "success"
    assert len(result.items) == 3
    assert [item.title for item in result.items] == [
        "Federal Reserve headline 0",
        "Federal Reserve headline 1",
        "Federal Reserve headline 2",
    ]
    assert all(item.verification_status == "single_source" for item in result.items)


def test_gdelt_doc_filters_irrelevant_yen_intervention_false_positives(tmp_path: Path) -> None:
    client = FakeGdeltClient({
        'yen query': _response({
            "articles": [
                {
                    "title": "Piyasalar alarmda : Gözler TCMB ve ECBnin kritik faiz kararlarında",
                    "url": "https://example.com/tcmb-ecb",
                    "domain": "example.com",
                    "seendate": "20260611100000",
                },
                {
                    "title": "Yen intervention risk rises as USD/JPY trades near key level",
                    "url": "https://example.com/usdjpy-yen",
                    "domain": "example.com",
                    "seendate": "20260611101000",
                },
            ]
        })
    })

    result = collect_gdelt_docs(
        retrieved_date="2026-06-11",
        storage_root=tmp_path,
        query_groups={"yen_intervention": "yen query"},
        client=client,
    )

    assert result.status == "success"
    assert len(result.items) == 1
    assert result.items[0].title == "Yen intervention risk rises as USD/JPY trades near key level"
    assert result.items[0].event_type == "yen_intervention_risk"


def test_gdelt_doc_partial_failure_keeps_successful_query_groups(tmp_path: Path) -> None:
    client = FakeGdeltClient({
        'Iran Hormuz oil': _response({
            "articles": [
                {
                    "title": "Oil tanker disruption near Hormuz",
                    "url": "https://example.com/oil",
                    "domain": "example.com",
                    "seendate": "20260609151500",
                }
            ]
        }),
        'Fed inflation': httpx.ConnectError("connection refused"),
    })

    result = collect_gdelt_docs(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={
            "middle_east_hormuz": "Iran Hormuz oil",
            "fed_inflation": "Fed inflation",
        },
        client=client,
    )

    assert result.status == "partial"
    assert [item.feed_key for item in result.items] == ["middle_east_hormuz"]
    assert result.unavailable_feeds == ["fed_inflation"]
    assert result.source_refs[0]["status"] == "available"
    assert result.source_refs[-1]["status"] == "network_blocked"
    assert result.source_refs[-1]["reason_code"] == "network_blocked"
    assert "warning" not in result.source_refs[0]
    assert result.source_refs[-1]["warning"] == result.warnings[0]
    assert "network_blocked" in result.warnings[0]


def test_gdelt_doc_rate_limit_is_explicit_in_source_ref_status(tmp_path: Path) -> None:
    request = httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc")
    response = httpx.Response(429, request=request)
    error = httpx.HTTPStatusError("rate limited", request=request, response=response)
    client = FakeGdeltClient({"Fed inflation": error})

    result = collect_gdelt_docs(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"fed_inflation": "Fed inflation"},
        client=client,
    )

    assert result.status == "unavailable"
    assert result.unavailable_feeds == ["fed_inflation"]
    assert result.source_refs[0]["status"] == "rate_limited"
    assert result.source_refs[0]["reason_code"] == "rate_limited"
    assert "429" in result.source_refs[0]["reason"]
    assert result.source_refs[0]["warning"] == result.warnings[0]
    assert "rate_limited" in result.warnings[0]
    assert result.source_refs[0]["parsed_path"].startswith("parsed/news/gdelt/2026-06-10/cooldown-fed_inflation.json")


def test_gdelt_doc_rate_limit_cooldown_skips_repeated_request(tmp_path: Path) -> None:
    request = httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc")
    response = httpx.Response(429, request=request)
    first_client = FakeGdeltClient({"Fed inflation": httpx.HTTPStatusError("rate limited", request=request, response=response)})
    now = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)

    first_result = collect_gdelt_docs(
        retrieved_date="2026-06-11",
        storage_root=tmp_path,
        query_groups={"fed_inflation": "Fed inflation"},
        client=first_client,
        rate_limit_cooldown_seconds=900,
        now=now,
    )

    assert first_result.status == "unavailable"
    assert len(first_client.requests) == 1
    cooldown_path = tmp_path / first_result.source_refs[0]["parsed_path"]
    assert cooldown_path.exists()

    second_client = FakeGdeltClient({"Fed inflation": _response({"articles": []})})
    second_result = collect_gdelt_docs(
        retrieved_date="2026-06-11",
        storage_root=tmp_path,
        query_groups={"fed_inflation": "Fed inflation"},
        client=second_client,
        rate_limit_cooldown_seconds=900,
        now=now + timedelta(seconds=60),
    )

    assert second_client.requests == []
    assert second_result.status == "unavailable"
    assert second_result.unavailable_feeds == ["fed_inflation"]
    assert second_result.source_refs[0]["status"] == "rate_limited"
    assert second_result.source_refs[0]["reason_code"] == "cooldown_active"
    assert "cooldown" in second_result.source_refs[0]["warning"]

    third_client = FakeGdeltClient({
        "Fed inflation": _response({
            "articles": [
                {
                    "title": "Federal Reserve inflation debate intensifies",
                    "url": "https://example.com/fed",
                    "domain": "example.com",
                    "seendate": "20260611120100",
                }
            ]
        })
    })
    third_result = collect_gdelt_docs(
        retrieved_date="2026-06-11",
        storage_root=tmp_path,
        query_groups={"fed_inflation": "Fed inflation"},
        client=third_client,
        rate_limit_cooldown_seconds=900,
        now=now + timedelta(seconds=901),
    )

    assert len(third_client.requests) == 1
    assert third_result.status == "success"
    assert len(third_result.items) == 1


def test_gdelt_doc_invalid_payload_marks_feed_unavailable(tmp_path: Path) -> None:
    client = FakeGdeltClient({"Fed inflation": _response({"articles": "bad-payload"})})

    result = collect_gdelt_docs(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        query_groups={"fed_inflation": "Fed inflation"},
        client=client,
    )

    assert result.status == "unavailable"
    assert result.source_refs[0]["status"] == "unavailable"
    assert result.source_refs[0]["reason_code"] == "invalid_payload"
    assert result.source_refs[0]["warning"] == result.warnings[0]
    assert result.unavailable_feeds == ["fed_inflation"]
