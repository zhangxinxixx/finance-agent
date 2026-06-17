from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


def analyze_report_images(
    images: list[dict[str, Any]],
    *,
    api_key: str | None = None,
    model: str = "gpt-4.1-mini",
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    load_dotenv()
    resolved_api_key = api_key or os.getenv("OPENAI_API_KEY", "").strip()
    if not resolved_api_key:
        return [_unavailable_insight(image, reason="missing_openai_api_key") for image in images]

    own_client = client is None
    http_client = client or httpx.Client(timeout=60.0)
    try:
        results: list[dict[str, Any]] = []
        for image in images:
            results.append(
                _analyze_single_image(
                    image,
                    api_key=resolved_api_key,
                    model=model,
                    client=http_client,
                )
            )
        return results
    finally:
        if own_client:
            http_client.close()


def _analyze_single_image(
    image: dict[str, Any],
    *,
    api_key: str,
    model: str,
    client: httpx.Client,
) -> dict[str, Any]:
    path = Path(str(image["path"]))
    if not path.exists():
        return _unavailable_insight(image, reason="image_not_found")
    mime_type = _guess_mime_type(path)
    image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "请读取这张黄金/白银研究图表，只返回 JSON，字段固定为 "
                            '{"text":"图中文字摘录","summary":"一句中文摘要","chart_type":"图表类型"}。'
                            "如果无法识别，请尽量返回可见标题或坐标轴关键词。"
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{image_b64}",
                    },
                ],
            }
        ],
    }
    response = client.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    response.raise_for_status()
    data = response.json()
    text_output = _extract_output_text(data)
    try:
        parsed = json.loads(text_output)
    except json.JSONDecodeError:
        parsed = {
            "text": text_output.strip(),
            "summary": text_output.strip(),
            "chart_type": "unknown",
        }
    return {
        "seq": image.get("seq"),
        "file": image.get("file"),
        "path": image.get("path"),
        "status": "ok",
        "chart_type": parsed.get("chart_type") or "unknown",
        "text": str(parsed.get("text") or "").strip(),
        "summary": str(parsed.get("summary") or "").strip(),
    }


def _extract_output_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"])
    outputs = payload.get("output", [])
    parts: list[str] = []
    for item in outputs:
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


def _unavailable_insight(image: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "seq": image.get("seq"),
        "file": image.get("file"),
        "path": image.get("path"),
        "status": "unavailable",
        "reason": reason,
        "chart_type": "unknown",
        "text": "",
        "summary": "",
    }
