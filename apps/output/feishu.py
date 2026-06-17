from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

FeishuMessageType = Literal["text", "post"]


@dataclass(frozen=True)
class FeishuSendResult:
    ok: bool
    dry_run: bool
    payload: dict[str, Any]
    status_code: int | None = None
    response_json: dict[str, Any] | None = None
    response_text: str | None = None
    error: str | None = None


def build_feishu_message_payload(
    message: str,
    *,
    title: str | None = None,
    message_type: FeishuMessageType = "text",
    secret: str | None = None,
    timestamp: int | None = None,
) -> dict[str, Any]:
    text = message.strip()
    if not text:
        raise ValueError("message cannot be empty")

    if message_type == "text":
        payload: dict[str, Any] = {"msg_type": "text", "content": {"text": text}}
    elif message_type == "post":
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": (title or "finance-agent").strip() or "finance-agent",
                        "content": [[{"tag": "text", "text": text}]],
                    }
                }
            },
        }
    else:
        raise ValueError(f"unsupported message_type: {message_type}")

    if secret:
        ts = int(timestamp if timestamp is not None else time.time())
        payload["timestamp"] = str(ts)
        payload["sign"] = _build_feishu_sign(secret=secret, timestamp=ts)

    return payload


def send_feishu_message(
    *,
    webhook_url: str,
    message: str,
    title: str | None = None,
    message_type: FeishuMessageType = "text",
    secret: str | None = None,
    dry_run: bool = False,
    timeout_seconds: float = 10.0,
    client: httpx.Client | None = None,
) -> FeishuSendResult:
    url = webhook_url.strip()
    if not url:
        raise ValueError("webhook_url cannot be empty")

    payload = build_feishu_message_payload(
        message,
        title=title,
        message_type=message_type,
        secret=secret,
    )
    if dry_run:
        return FeishuSendResult(ok=True, dry_run=True, payload=payload)

    owns_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds)
    try:
        response = http_client.post(url, json=payload)
    except httpx.HTTPError as exc:
        return FeishuSendResult(ok=False, dry_run=False, payload=payload, error=str(exc))
    finally:
        if owns_client:
            http_client.close()

    response_json: dict[str, Any] | None
    try:
        parsed = response.json()
        response_json = parsed if isinstance(parsed, dict) else None
    except ValueError:
        response_json = None

    response_text = None if response_json is not None else response.text
    feishu_code = response_json.get("code") if response_json else None
    ok = 200 <= response.status_code < 300 and feishu_code in (None, 0)
    error = None
    if not ok:
        if response_json:
            error = str(response_json.get("msg") or response_json.get("message") or response_json)
        else:
            error = response.text

    return FeishuSendResult(
        ok=ok,
        dry_run=False,
        payload=payload,
        status_code=response.status_code,
        response_json=response_json,
        response_text=response_text,
        error=error,
    )


def _build_feishu_sign(*, secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")
