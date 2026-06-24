from __future__ import annotations

import httpx
import pytest

from apps.output.feishu import FeishuSendResult, build_feishu_message_payload, send_feishu_message


def test_build_text_payload():
    payload = build_feishu_message_payload("hello", message_type="text")

    assert payload == {"msg_type": "text", "content": {"text": "hello"}}


def test_build_post_payload():
    payload = build_feishu_message_payload("hello", title="Daily Report", message_type="post")

    assert payload == {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": "Daily Report",
                    "content": [[{"tag": "text", "text": "hello"}]],
                }
            }
        },
    }


def test_build_payload_with_signing_secret():
    payload = build_feishu_message_payload("hello", secret="secret", timestamp=1234567890)

    assert payload["timestamp"] == "1234567890"
    assert payload["sign"]


def test_rejects_empty_message():
    with pytest.raises(ValueError, match="message cannot be empty"):
        build_feishu_message_payload("   ")


def test_dry_run_does_not_post():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - should not be called
        raise AssertionError("dry-run must not send an HTTP request")

    result = send_feishu_message(
        webhook_url="https://example.com/webhook",
        message="hello",
        dry_run=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert isinstance(result, FeishuSendResult)
    assert result.ok is True
    assert result.dry_run is True
    assert result.payload["content"]["text"] == "hello"


def test_send_posts_payload_and_accepts_feishu_zero_code():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "body": request.content.decode()})
        return httpx.Response(200, json={"code": 0, "msg": "success"})

    result = send_feishu_message(
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/token",
        message="hello",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert result.ok is True
    assert result.status_code == 200
    assert result.response_json == {"code": 0, "msg": "success"}
    assert len(seen) == 1
    assert '"msg_type":"text"' in seen[0]["body"]


def test_send_marks_nonzero_feishu_code_as_failed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 19024, "msg": "sign match fail"})

    result = send_feishu_message(
        webhook_url="https://example.com/webhook",
        message="hello",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert result.ok is False
    assert result.status_code == 200
    assert result.error == "sign match fail"
