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
        return self.payloads.pop(0)


def _text_message(message_id: str, text: str, sender_name: str = "金十新闻") -> dict[str, object]:
    return {
        "message_id": message_id,
        "chat_id": "oc_jin10",
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
        chat_id="oc_jin10",
        client=client,
    )

    assert result.status == "success"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.source_key == "jin10_feishu"
    assert item.source_type == "supplemental"
    assert item.feed_key == "oc_jin10"
    assert item.event_type == "hormuz_risk"
    assert item.verification_status == "single_source"
    assert item.url == "https://news.jin10.com/detail/1"
    assert item.raw_payload["message_id"] == "om_high"
    assert item.raw_payload["ingest_channel"] == "feishu_chat_pull"
    assert item.raw_payload["relevance_decision"]["decision"] == "high_value"
    assert item.raw_path and (tmp_path / item.raw_path).exists()
    assert item.parsed_path and (tmp_path / item.parsed_path).exists()
    assert result.source_refs[0]["status"] == "available"
    assert result.source_refs[0]["accepted_item_count"] == 1
    assert client.calls[0]["chat_id"] == "oc_jin10"


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
    monkeypatch.setenv("FEISHU_JIN10_CHAT_ID", "oc_jin10")
    monkeypatch.setenv("FEISHU_APP_ID", "cli_existing_docs")
    monkeypatch.setenv("FEISHU_APP_SECRET", "existing-docs-secret")
    monkeypatch.setenv("LARK_APP_ID", "cli_existing_bridge")
    monkeypatch.setenv("LARK_APP_SECRET", "existing-bridge-secret")
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
        chat_id="oc_jin10",
        client=client,
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.source_refs[0]["status"] == "empty"
    assert result.source_refs[0]["raw_message_count"] == 1
    assert result.source_refs[0]["accepted_item_count"] == 0
