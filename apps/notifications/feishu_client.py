from __future__ import annotations

import os
from typing import Any

import httpx

from apps.notifications.schemas import FeishuNotificationConfig, NotificationRequest, NotificationResult
from apps.output.feishu import build_feishu_message_payload, send_feishu_message


class FeishuWebhookClient:
    def __init__(self, config: FeishuNotificationConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> "FeishuWebhookClient":
        return cls(
            FeishuNotificationConfig(
                enabled=_env_bool("FEISHU_ENABLE"),
                webhook_url=os.getenv("FEISHU_WEBHOOK_URL", ""),
                secret=os.getenv("FEISHU_SECRET") or None,
            )
        )

    def send(
        self,
        request: NotificationRequest,
        *,
        rendered_title: str,
        rendered_message: str,
        client: httpx.Client | None = None,
    ) -> NotificationResult:
        dry_run = bool(request.dry_run)
        if dry_run:
            payload = build_feishu_message_payload(
                rendered_message,
                title=rendered_title,
                message_type="post",
                secret=self.config.secret,
            )
            return NotificationResult(
                ok=True,
                status="dry_run",
                kind=request.kind,
                title=rendered_title,
                dry_run=True,
                enabled=self.config.enabled,
                payload_preview=_payload_preview(payload),
            )

        if not self.config.enabled:
            return NotificationResult(
                ok=False,
                status="disabled",
                kind=request.kind,
                title=rendered_title,
                dry_run=False,
                enabled=False,
                error="FEISHU_ENABLE is not true",
            )
        if not self.config.webhook_url.strip():
            return NotificationResult(
                ok=False,
                status="failed",
                kind=request.kind,
                title=rendered_title,
                dry_run=False,
                enabled=True,
                error="FEISHU_WEBHOOK_URL is not configured",
            )

        result = send_feishu_message(
            webhook_url=self.config.webhook_url,
            message=rendered_message,
            title=rendered_title,
            message_type="post",
            secret=self.config.secret,
            timeout_seconds=self.config.timeout_seconds,
            client=client,
        )
        return NotificationResult(
            ok=result.ok,
            status="sent" if result.ok else "failed",
            kind=request.kind,
            title=rendered_title,
            dry_run=False,
            enabled=True,
            status_code=result.status_code,
            response_json=result.response_json,
            response_text=result.response_text,
            error=result.error,
            payload_preview=_payload_preview(result.payload),
        )


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _payload_preview(payload: dict[str, Any]) -> dict[str, Any]:
    content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    post = content.get("post") if isinstance(content.get("post"), dict) else {}
    zh_cn = post.get("zh_cn") if isinstance(post.get("zh_cn"), dict) else {}
    blocks = zh_cn.get("content") if isinstance(zh_cn.get("content"), list) else []
    text = ""
    if blocks and isinstance(blocks[0], list) and blocks[0]:
        first = blocks[0][0]
        if isinstance(first, dict):
            text = str(first.get("text") or "")
    return {
        "msg_type": payload.get("msg_type"),
        "title": zh_cn.get("title"),
        "text_preview": text[:240],
        "has_sign": bool(payload.get("sign")),
    }
