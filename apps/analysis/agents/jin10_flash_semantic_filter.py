"""Prompt template for Jin10 flash semantic key-event filtering."""

from __future__ import annotations

import json
from typing import Any

AGENT_ID = "jin10_flash_semantic_filter_agent"
PROMPT_SOURCE = "apps/analysis/agents/jin10_flash_semantic_filter.py::build_jin10_flash_semantic_filter_prompt_template"


def build_jin10_flash_semantic_filter_prompt_template() -> dict[str, Any]:
    """Return the settings-manageable prompt template for Jin10 flash filtering."""
    return {
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是金融市场实时快讯语义筛选器。你的任务是判断每条金十快讯是否足以进入"
                    "「实时重点事件播报」。不要按固定关键词机械判断，要根据事件是否可能影响黄金、美元、"
                    "原油、利率、风险情绪或核心宏观预期来做语义评估。只输出严格 JSON。\n\n"
                    "同时判断每条快讯的**内容形态**（content_type 字段）：\n"
                    "- flash: 单条市场快讯（一句话陈述、数据公布、官员表态）\n"
                    "- article: 中篇报道（带背景分析的多段新闻，通常 100-300 字）\n"
                    "- report: 长文/深度报告（多段深度分析、专题报道，通常 300+ 字）\n"
                    "- calendar: 财经日历汇总（含多个时间+事件条目的列表）"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请逐条评估下列快讯。\n"
                    "展示标准：\n"
                    "1. 重大央行、利率、通胀、就业、GDP、财政或监管消息，通常是重点。\n"
                    "2. 能通过能源、航运咽喉、制裁、军事升级、避险情绪传导到黄金/美元/油价/美债的地缘事件，是重点。\n"
                    "3. 例行表态、重复跟进、伤亡统计、安全确认、政治口水、没有清晰市场传导路径的消息，不展示。\n"
                    "4. 若信息不完整但可能影响市场，标为 medium；只有清晰影响主线的才标 high。\n\n"
                    "返回 JSON 格式必须为：\n"
                    "{\n"
                    '  "items": [\n'
                    "    {\n"
                    '      "index": 0,\n'
                    '      "is_key_event": true,\n'
                    '      "importance": "high|medium|normal",\n'
                    '      "signal_tags": ["macro_policy|rates|inflation|employment|usd|gold|oil|geopolitical_risk|shipping_chokepoint|risk_sentiment|low_signal_followup"],\n'
                    '      "filter_reason": "一句话说明为什么展示或过滤",\n'
                    '      "confidence": 0.0,\n'
                    '      "content_type": "flash|article|report|calendar"\n'
                    "    }\n"
                    "  ]\n"
                    "}\n\n"
                    "快讯 JSON：\n{{flash_items_json}}"
                ),
            },
        ],
        "variables": {
            "flash_items_json": "JSON array of normalized Jin10 flash items with index/id/time/content.",
        },
        "output_schema": {
            "items": [
                {
                    "index": 0,
                    "is_key_event": True,
                    "importance": "high|medium|normal",
                    "signal_tags": ["geopolitical_risk"],
                    "filter_reason": "一句话说明为什么展示或过滤",
                    "confidence": 0.0,
                    "content_type": "flash|article|report|calendar",
                }
            ]
        },
    }


def render_jin10_flash_semantic_filter_messages(
    prompt_template: dict[str, Any],
    items: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Render registry/DB prompt template into OpenAI-compatible messages."""
    payload = [
        {
            "index": idx,
            "id": str(item.get("id") or idx),
            "time": item.get("time"),
            "content": str(item.get("content") or item.get("title") or "").strip(),
        }
        for idx, item in enumerate(items)
    ]
    flash_items_json = json.dumps(payload, ensure_ascii=False)

    raw_messages = prompt_template.get("messages")
    if not isinstance(raw_messages, list):
        raw_messages = build_jin10_flash_semantic_filter_prompt_template()["messages"]

    rendered: list[dict[str, str]] = []
    for raw in raw_messages:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "user")
        content = str(raw.get("content") or "").replace("{{flash_items_json}}", flash_items_json)
        if content:
            rendered.append({"role": role, "content": content})
    if not rendered:
        return render_jin10_flash_semantic_filter_messages(
            build_jin10_flash_semantic_filter_prompt_template(),
            items,
        )
    return rendered
