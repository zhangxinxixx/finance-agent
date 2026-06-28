from __future__ import annotations

import json
import os
from typing import Any, Mapping

from apps.analysis.agents.macro_event_followup_prompt import build_macro_event_followup_prompt_template
from apps.renderer.markdown.macro_event_followup import build_macro_event_followup_structured_payload

_SYSTEM_PROMPT = "你是一位贵金属宏观事件跟进分析 Agent。只输出 Markdown 正文。"
_PROMPT_VERSION = "macro_event_followup_agent_v1"


def build_macro_event_followup_prompt(snapshot: Mapping[str, Any]) -> str:
    structured = build_macro_event_followup_structured_payload(snapshot)
    payload = structured.model_dump(mode="json")
    return (
        f"{build_macro_event_followup_prompt_template()}\n\n"
        "=== 结构化输入 ===\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
    )


def invoke_macro_event_followup_llm(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    from apps.llm.gateway import chat_sync

    if _should_skip_live_llm():
        return {
            "markdown": "",
            "model": None,
            "provider": None,
            "latency_ms": None,
            "tokens": None,
            "prompt_version": _PROMPT_VERSION,
            "skipped": True,
        }

    prompt = build_macro_event_followup_prompt(snapshot)
    response = chat_sync(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
        max_retries=0,
    )
    return {
        "markdown": _parse_markdown(response.content),
        "model": response.model,
        "provider": response.provider,
        "latency_ms": response.latency_ms,
        "tokens": response.usage,
        "prompt_version": _PROMPT_VERSION,
        "skipped": False,
    }


def _parse_markdown(text: str) -> str:
    markdown = text.strip()
    if markdown.startswith("```"):
        lines = markdown.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        markdown = "\n".join(lines).strip()
    return markdown


def _should_skip_live_llm() -> bool:
    if os.getenv("FINANCE_AGENT_FORCE_LIVE_LLM", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return "PYTEST_CURRENT_TEST" in os.environ
