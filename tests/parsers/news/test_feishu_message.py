from __future__ import annotations

import json

from apps.parsers.news.feishu_message import looks_like_jin10_message, parse_feishu_message


def test_parse_text_message_extracts_content_marker_and_link() -> None:
    message = {
        "message_id": "om_text",
        "chat_id": "chat_fixture",
        "message_type": "text",
        "create_time": "1767225600000",
        "sender": {"id": "ou_sender", "sender_name": "金十新闻"},
        "content": json.dumps({
            "text": "霍尔木兹通行量虽远低于冲突前，油价和黄金避险升温 [点击查看详情](https://news.jin10.com/detail/1) [来自金十数据APP重要推送]"
        }, ensure_ascii=False),
    }

    envelope = parse_feishu_message(message)

    assert envelope.message_id == "om_text"
    assert envelope.chat_id == "chat_fixture"
    assert envelope.sender_name == "金十新闻"
    assert "霍尔木兹" in envelope.content
    assert envelope.links == ["https://news.jin10.com/detail/1"]
    assert envelope.source_marker == "来自金十数据APP重要推送"
    assert envelope.published_at.startswith("2026-")
    assert looks_like_jin10_message(envelope) is True


def test_parse_post_message_extracts_nested_link_nodes() -> None:
    message = {
        "message_id": "om_post",
        "chat_id": "chat_fixture",
        "message_type": "post",
        "create_time": "1767225600000",
        "sender": {"id": "ou_sender"},
        "content": json.dumps({
            "post": {
                "zh_cn": {
                    "title": "金十新闻",
                    "content": [[
                        {"tag": "text", "text": "美联储官员称通胀仍偏高"},
                        {"tag": "a", "text": "点击查看详情", "href": "https://news.jin10.com/detail/2"},
                    ]],
                }
            }
        }, ensure_ascii=False),
    }

    envelope = parse_feishu_message(message)

    assert envelope.content == "金十新闻 美联储官员称通胀仍偏高 点击查看详情"
    assert envelope.links == ["https://news.jin10.com/detail/2"]
    assert looks_like_jin10_message(envelope) is True


def test_parse_interactive_message_extracts_card_urls() -> None:
    message = {
        "message_id": "om_card",
        "chat_id": "chat_fixture",
        "message_type": "interactive",
        "create_time": "1767225600000",
        "sender": {"id": "ou_sender"},
        "content": json.dumps({
            "header": {"title": {"content": "金十新闻"}},
            "elements": [
                {"tag": "div", "text": {"content": "现货黄金刷新日高"}},
                {"tag": "action", "actions": [{"tag": "button", "text": {"content": "点击查看详情"}, "url": "https://news.jin10.com/detail/3"}]},
            ],
        }, ensure_ascii=False),
    }

    envelope = parse_feishu_message(message)

    assert "现货黄金刷新日高" in envelope.content
    assert envelope.links == ["https://news.jin10.com/detail/3"]
    assert looks_like_jin10_message(envelope) is True


def test_parse_real_message_list_shape_uses_msg_type_and_body_content() -> None:
    message = {
        "message_id": "om_real",
        "chat_id": "chat_fixture",
        "msg_type": "post",
        "create_time": "1767225600000",
        "sender": {"id": "cli_sender", "sender_type": "app"},
        "body": {
            "content": json.dumps({
                "title": "",
                "content": [[
                    {"tag": "text", "text": "据阿拉比亚电视台：伊朗已对相关信函作出回应。"},
                    {"tag": "a", "text": "点击查看详情", "href": "https://flash.jin10.com/detail/20260611193418720800?j=4286-7218"},
                ]],
            }, ensure_ascii=False)
        },
    }

    envelope = parse_feishu_message(message)

    assert envelope.message_type == "post"
    assert envelope.sender_id == "cli_sender"
    assert "伊朗" in envelope.content
    assert envelope.links == ["https://flash.jin10.com/detail/20260611193418720800?j=4286-7218"]
    assert looks_like_jin10_message(envelope) is True


def test_parse_malformed_content_preserves_raw_content() -> None:
    envelope = parse_feishu_message({
        "message_id": "om_bad",
        "chat_id": "chat_fixture",
        "message_type": "text",
        "create_time": "bad-time",
        "content": "plain text with https://example.com/raw",
    })

    assert envelope.content == "plain text with https://example.com/raw"
    assert envelope.links == ["https://example.com/raw"]
    assert envelope.published_at is None
