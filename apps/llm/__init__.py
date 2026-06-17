"""LLM Gateway — unified LLM call interface with multi-provider fallback.

Usage:
    from apps.llm import chat, LLMResponse

    response = await chat([
        {"role": "system", "content": "你是一个分析师。"},
        {"role": "user", "content": "分析当前黄金市场。"},
    ])
    print(response.content)
"""

from __future__ import annotations

from apps.llm.gateway import LLMGateway, LLMResponse, chat, chat_sync
from apps.llm.config import LLMConfig

__all__ = ["LLMGateway", "LLMResponse", "LLMConfig", "chat", "chat_sync"]
