from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

URL_RE = re.compile(r"https?://[^\s\]\)\"'<>]+")
SOURCE_MARKER = "来自金十数据APP重要推送"
LINK_KEYS = {"href", "url", "link"}
STRUCTURAL_KEYS = {"tag"}


@dataclass(frozen=True)
class FeishuMessageEnvelope:
    message_id: str
    chat_id: str
    sender_id: str | None
    sender_name: str | None
    message_type: str
    content: str
    links: list[str]
    published_at: str | None
    source_marker: str | None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_feishu_message(message: dict[str, Any]) -> FeishuMessageEnvelope:
    content_payload = _parse_content(_message_content(message))
    text_parts: list[str] = []
    links: list[str] = []
    _collect_content(content_payload, text_parts=text_parts, links=links)

    content = _normalize_space(" ".join(part for part in text_parts if part))
    if not content and isinstance(message.get("content"), str):
        content = str(message["content"]).strip()
    links = _dedupe([*links, *URL_RE.findall(content)])
    sender = message.get("sender") if isinstance(message.get("sender"), dict) else {}
    source_marker = SOURCE_MARKER if SOURCE_MARKER in content else None

    return FeishuMessageEnvelope(
        message_id=str(message.get("message_id") or ""),
        chat_id=str(message.get("chat_id") or ""),
        sender_id=_clean_optional(sender.get("id") or sender.get("sender_id")),
        sender_name=_clean_optional(sender.get("sender_name") or sender.get("name") or sender.get("id")),
        message_type=str(message.get("message_type") or message.get("msg_type") or ""),
        content=content,
        links=links,
        published_at=_parse_feishu_time(message.get("create_time") or message.get("update_time")),
        source_marker=source_marker,
        raw_payload=dict(message),
    )


def looks_like_jin10_message(envelope: FeishuMessageEnvelope) -> bool:
    sender = envelope.sender_name or ""
    content = envelope.content
    return (
        "金十" in sender
        or SOURCE_MARKER in content
        or "金十新闻" in content
        or "金十数据" in content
        or any("jin10.com" in link for link in envelope.links)
    )


def _message_content(message: dict[str, Any]) -> Any:
    if message.get("content") is not None:
        return message.get("content")
    body = message.get("body")
    if isinstance(body, dict):
        return body.get("content")
    return None


def _parse_content(raw_content: Any) -> Any:
    if not isinstance(raw_content, str):
        return raw_content
    try:
        return json.loads(raw_content)
    except json.JSONDecodeError:
        return raw_content


def _collect_content(payload: Any, *, text_parts: list[str], links: list[str], parent_key: str = "") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = str(key)
            if normalized_key in STRUCTURAL_KEYS:
                continue
            if normalized_key in LINK_KEYS and isinstance(value, str):
                links.extend(URL_RE.findall(value))
                continue
            if normalized_key == "multi_url" and isinstance(value, dict):
                for candidate in value.values():
                    if isinstance(candidate, str):
                        links.extend(URL_RE.findall(candidate))
                continue
            _collect_content(value, text_parts=text_parts, links=links, parent_key=normalized_key)
        return
    if isinstance(payload, list):
        for item in payload:
            _collect_content(item, text_parts=text_parts, links=links, parent_key=parent_key)
        return
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return
        if parent_key in LINK_KEYS:
            links.extend(URL_RE.findall(text))
            return
        text_parts.append(text)


def _parse_feishu_time(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw.isdigit():
        return None
    timestamp = int(raw)
    if timestamp > 10_000_000_000:
        timestamp = timestamp // 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.rstrip(".,;，。；")
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
