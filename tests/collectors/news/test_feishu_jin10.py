from __future__ import annotations

import json
from pathlib import Path

from apps.collectors.news.feishu_jin10 import collect_feishu_jin10_messages, is_feishu_jin10_enabled


class FakeFeishuClient:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, object]] = []

    def list_chat_messages(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def _text_message(message_id: str, text: str, sender_name: str = "金十新闻") -> dict[str, object]:
    return {
        "message_id": message_id,
        "chat_id": "chat_fixture",
        "message_type": "text",
        "create_time": "1767225600000",
        "sender": {"id": "ou_sender", "sender_name": sender_name},
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }


def test_collect_feishu_jin10_messages_archives_raw_payload_and_maps_high_value_items(tmp_path: Path) -> None:
    client = FakeFeishuClient([
        {
            "code": 0,
            "data": {
                "items": [
                    _text_message(
                        "om_high",
                        "霍尔木兹通行量下降，原油供应风险推升通胀预期，黄金避险需求升温 https://news.jin10.com/detail/1 来自金十数据APP重要推送",
                    ),
                    _text_message("om_low", "体育赛事门票销售火爆", sender_name="其他机器人"),
                ],
                "has_more": False,
            },
        }
    ])

    result = collect_feishu_jin10_messages(
        retrieved_date="2026-06-11",
        storage_root=tmp_path,
        chat_id="chat_fixture",
        client=client,
    )

    assert result.status == "success"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.source_key == "jin10_feishu"
    assert item.source_type == "supplemental"
    assert item.feed_key == "chat_fixture"
    assert item.event_type == "hormuz_risk"
    assert item.verification_status == "single_source"
    assert item.url == "https://news.jin10.com/detail/1"
    assert item.raw_payload["message_id"] == "om_high"
    assert item.raw_payload["ingest_channel"] == "feishu_chat_pull"
    assert item.raw_payload["relevance_decision"]["decision"] == "high_value"
    assert item.raw_path and (tmp_path / item.raw_path).exists()
    assert item.parsed_path and (tmp_path / item.parsed_path).exists()
    raw_payload = json.loads((tmp_path / item.raw_path).read_text(encoding="utf-8"))
    parsed_payload = json.loads((tmp_path / item.parsed_path).read_text(encoding="utf-8"))
    assert raw_payload["raw_message_count"] == 2
    assert raw_payload["retained_message_count"] == 1
    assert len(raw_payload["messages"]) == 1
    assert raw_payload["messages"][0]["message_id"] == "om_high"
    assert parsed_payload["raw_message_count"] == 2
    assert parsed_payload["retained_message_count"] == 1
    assert len(parsed_payload["messages"]) == 1
    assert parsed_payload["messages"][0]["message_id"] == "om_high"
    assert parsed_payload["messages"][0]["title"]
    assert "om_low" not in json.dumps(parsed_payload, ensure_ascii=False)
    assert result.source_refs[0]["status"] == "available"
    assert result.source_refs[0]["accepted_item_count"] == 1
    assert client.calls[0]["chat_id"] == "chat_fixture"


def test_collect_feishu_jin10_messages_requires_chat_id(tmp_path: Path) -> None:
    result = collect_feishu_jin10_messages(
        retrieved_date="2026-06-11",
        storage_root=tmp_path,
        chat_id="",
        client=FakeFeishuClient([]),
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.source_refs[0]["reason_code"] == "missing_chat_id"


def test_feishu_jin10_enablement_ignores_generic_lark_or_feishu_credentials(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_JIN10_CHAT_ID", "chat_fixture")
    monkeypatch.setenv("FEISHU_APP_ID", "cli_existing_docs")
    monkeypatch.setenv("FEISHU_APP_SECRET", "existing-docs-secret")
    monkeypatch.setenv("LARK_APP_ID", "cli_existing_generic")
    monkeypatch.setenv("LARK_APP_SECRET", "existing-generic-secret")
    monkeypatch.delenv("FEISHU_NEWS_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_NEWS_APP_SECRET", raising=False)

    assert is_feishu_jin10_enabled() is False

    monkeypatch.setenv("FEISHU_NEWS_APP_ID", "cli_news")
    monkeypatch.setenv("FEISHU_NEWS_APP_SECRET", "news-secret")

    assert is_feishu_jin10_enabled() is True


def test_collect_feishu_jin10_messages_archives_but_does_not_emit_low_value_messages(tmp_path: Path) -> None:
    client = FakeFeishuClient([
        {
            "code": 0,
            "data": {
                "items": [_text_message("om_marker", "点击查看详情 来自金十数据APP重要推送")],
                "has_more": False,
            },
        }
    ])

    result = collect_feishu_jin10_messages(
        retrieved_date="2026-06-11",
        storage_root=tmp_path,
        chat_id="chat_fixture",
        client=client,
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.source_refs[0]["status"] == "empty"
    assert result.source_refs[0]["raw_message_count"] == 1
    assert result.source_refs[0]["accepted_item_count"] == 0
    raw_payload = json.loads((tmp_path / result.source_refs[0]["raw_paths"][0]).read_text(encoding="utf-8"))
    parsed_payload = json.loads((tmp_path / result.source_refs[0]["parsed_path"]).read_text(encoding="utf-8"))
    assert raw_payload["retained_message_count"] == 0
    assert raw_payload["messages"] == []
    assert parsed_payload["retained_message_count"] == 0
    assert parsed_payload["messages"] == []


def test_collect_feishu_jin10_messages_keeps_completed_pages_when_next_page_fails(tmp_path: Path) -> None:
    client = FakeFeishuClient([
        {
            "code": 0,
            "data": {
                "items": [
                    _text_message(
                        "om_page_1",
                        "美联储利率预期重新定价，美元和美债收益率同步上行，黄金短线承压 来自金十数据APP重要推送",
                    )
                ],
                "has_more": True,
                "page_token": "cursor-page-2",
            },
        },
        RuntimeError("connection dropped"),
    ])

    result = collect_feishu_jin10_messages(
        retrieved_date="2026-06-11",
        storage_root=tmp_path,
        chat_id="chat_fixture",
        client=client,
        max_pages=2,
    )

    assert result.status == "partial"
    assert len(result.items) == 1
    assert result.items[0].raw_payload["message_id"] == "om_page_1"
    assert result.items[0].parsed_path and (tmp_path / result.items[0].parsed_path).exists()
    assert result.source_refs[0]["status"] == "partial"
    assert result.source_refs[0]["raw_message_count"] == 1
    assert result.source_refs[0]["accepted_item_count"] == 1
    assert result.source_refs[0]["reason_code"] == "request_failed"
    assert result.source_refs[0]["raw_paths"]
    assert result.source_refs[0]["parsed_path"] == result.items[0].parsed_path
    assert client.calls[1]["page_token"] == "cursor-page-2"
