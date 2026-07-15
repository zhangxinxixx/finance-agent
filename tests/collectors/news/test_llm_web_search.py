from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apps.collectors.news.llm_web_search import collect_llm_web_search_news


class _FakeResponse:
    def __init__(self, *, output_text: str, searched_urls: list[str]) -> None:
        self.output_text = output_text
        self._payload = {
            "id": "resp_test",
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "type": "search",
                        "queries": ["latest gold news"],
                        "sources": [{"type": "url", "url": url} for url in searched_urls],
                    },
                    "status": "completed",
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": output_text, "annotations": []}],
                },
            ],
        }

    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return self._payload


class _FakeResponses:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.responses = _FakeResponses(response)


def test_llm_web_search_defaults_to_available_jojocode_provider(tmp_path: Path) -> None:
    response = _FakeResponse(searched_urls=[], output_text=json.dumps({"items": []}))
    client = _FakeClient(response)
    config = SimpleNamespace(
        available_providers=["cockpit", "jojocode"],
        get_provider=lambda name: SimpleNamespace(
            name=name,
            api_key="existing-key",
            base_url="https://max.jojocode.com/v1",
            default_model="gpt-5.6-sol",
            timeout=60,
        ),
    )

    with (
        patch("apps.collectors.news.llm_web_search.LLMConfig.from_env", return_value=config),
        patch("apps.collectors.news.llm_web_search.OpenAI", return_value=client) as constructor,
    ):
        result = collect_llm_web_search_news(
            retrieved_date="2026-07-21",
            storage_root=tmp_path,
            query_groups={"gold_macro": "latest gold news"},
        )

    constructor.assert_called_once_with(
        api_key="existing-key",
        base_url="https://max.jojocode.com/v1",
        timeout=60.0,
    )
    assert result.source_refs[0]["provider"] == "jojocode"


def test_llm_web_search_archives_only_tool_sourced_candidates(tmp_path: Path) -> None:
    url = "https://example.com/latest-gold"
    response = _FakeResponse(
        searched_urls=[url],
        output_text=json.dumps({
            "items": [
                {
                    "title": "Gold rises as yields ease",
                    "url": url,
                    "published_at": "2026-07-21T09:10:00Z",
                    "summary": "Treasury yields eased before the policy decision.",
                    "publisher": "Example Wire",
                }
            ]
        }),
    )
    client = _FakeClient(response)

    result = collect_llm_web_search_news(
        retrieved_date="2026-07-21",
        storage_root=tmp_path,
        query_groups={"gold_macro": "latest gold news"},
        provider_name="test-provider",
        model="test-model",
        client=client,
    )

    assert result.status == "success"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.source_key == "llm_web_search"
    assert item.verification_status == "single_source"
    assert item.url == url
    assert item.published_at == "2026-07-21T09:10:00+00:00"
    assert item.raw_path is not None and (tmp_path / item.raw_path).exists()
    assert item.parsed_path is not None and (tmp_path / item.parsed_path).exists()
    assert result.source_refs[0]["provider_role"] == "online_research_fallback"
    call = client.responses.calls[0]
    assert call["tools"] == [{"type": "web_search", "search_context_size": "high"}]
    assert call["tool_choice"] == {"type": "web_search"}
    assert call["store"] is False


def test_llm_web_search_rejects_model_url_not_returned_by_tool(tmp_path: Path) -> None:
    response = _FakeResponse(
        searched_urls=["https://example.com/real"],
        output_text=json.dumps({
            "items": [
                {
                    "title": "Invented result",
                    "url": "https://example.com/invented",
                    "published_at": None,
                    "summary": "Not tied to the tool call.",
                    "publisher": "Example",
                }
            ]
        }),
    )

    result = collect_llm_web_search_news(
        retrieved_date="2026-07-21",
        storage_root=tmp_path,
        query_groups={"gold_macro": "latest gold news"},
        client=_FakeClient(response),
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.unavailable_feeds == ["gold_macro"]
    assert result.source_refs[0]["reason_code"] == "no_items"


def test_llm_web_search_requires_actual_web_search_call(tmp_path: Path) -> None:
    response = _FakeResponse(
        searched_urls=[],
        output_text=json.dumps({"items": []}),
    )

    result = collect_llm_web_search_news(
        retrieved_date="2026-07-21",
        storage_root=tmp_path,
        query_groups={"gold_macro": "latest gold news"},
        client=_FakeClient(response),
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.source_refs[0]["reason_code"] == "tool_unavailable"
    assert "no web_search_call source URLs" in result.source_refs[0]["reason"]
    assert result.source_refs[0]["raw_path"] is not None
    assert (tmp_path / result.source_refs[0]["raw_path"]).exists()


def test_llm_web_search_rejects_annotation_without_tool_call(tmp_path: Path) -> None:
    url = "https://example.com/annotation-only"
    response = _FakeResponse(
        searched_urls=[],
        output_text=json.dumps({"items": [{"title": "Annotation only", "url": url}]}),
    )
    response._payload["output"] = [
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": response.output_text,
                    "annotations": [{"type": "url_citation", "url": url}],
                }
            ],
        }
    ]

    result = collect_llm_web_search_news(
        retrieved_date="2026-07-21",
        storage_root=tmp_path,
        query_groups={"gold_macro": "latest gold news"},
        client=_FakeClient(response),
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.source_refs[0]["reason_code"] == "tool_unavailable"
