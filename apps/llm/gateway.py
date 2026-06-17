"""LLM Gateway — unified call interface with retry and fallback."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI, OpenAI

from apps.llm.config import LLMConfig, ProviderConfig

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Standardized LLM response."""

    content: str
    model: str
    provider: str
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    cached: bool = False

    @property
    def prompt_tokens(self) -> int:
        return self.usage.get("prompt_tokens", 0)

    @property
    def completion_tokens(self) -> int:
        return self.usage.get("completion_tokens", 0)

    @property
    def total_tokens(self) -> int:
        return self.usage.get("total_tokens", 0)


class LLMGateway:
    """Unified LLM call gateway with multi-provider support and retry.

    Usage:
        gateway = LLMGateway.from_env()
        response = gateway.chat_sync([{"role": "user", "content": "分析黄金"}])
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self._sync_clients: dict[str, OpenAI] = {}
        self._async_clients: dict[str, AsyncOpenAI] = {}

    @classmethod
    def from_env(cls) -> LLMGateway:
        return cls(LLMConfig.from_env())

    def _get_sync_client(self, provider: ProviderConfig) -> OpenAI:
        if provider.name not in self._sync_clients:
            self._sync_clients[provider.name] = OpenAI(
                api_key=provider.api_key,
                base_url=provider.base_url,
                timeout=provider.timeout,
            )
        return self._sync_clients[provider.name]

    def _get_async_client(self, provider: ProviderConfig) -> AsyncOpenAI:
        if provider.name not in self._async_clients:
            self._async_clients[provider.name] = AsyncOpenAI(
                api_key=provider.api_key,
                base_url=provider.base_url,
                timeout=provider.timeout,
            )
        return self._async_clients[provider.name]

    def chat_sync(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        provider: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        json_mode: bool = False,
        max_retries: int = 2,
    ) -> LLMResponse:
        """Synchronous chat completion with retry."""
        last_error: Exception | None = None
        providers_to_try = self._resolve_providers(provider)

        for prov_name in providers_to_try:
            prov = self.config.get_provider(prov_name)
            client = self._get_sync_client(prov)
            resolved_model = model or prov.default_model
            resolved_max_tokens = max_tokens or prov.max_tokens

            for attempt in range(max_retries + 1):
                try:
                    start = time.monotonic()
                    kwargs: dict[str, Any] = {
                        "model": resolved_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": resolved_max_tokens,
                    }
                    if prov_name == "dashscope":
                        kwargs["extra_body"] = {"enable_thinking": False}
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}

                    result = client.chat.completions.create(**kwargs)
                    latency_ms = int((time.monotonic() - start) * 1000)

                    content = result.choices[0].message.content or ""
                    usage = {}
                    if result.usage:
                        usage = {
                            "prompt_tokens": result.usage.prompt_tokens,
                            "completion_tokens": result.usage.completion_tokens,
                            "total_tokens": result.usage.total_tokens,
                        }

                    logger.info(
                        "LLM call success: provider=%s model=%s latency=%dms tokens=%d",
                        prov_name, resolved_model, latency_ms, usage.get("total_tokens", 0),
                    )
                    return LLMResponse(
                        content=content,
                        model=resolved_model,
                        provider=prov_name,
                        usage=usage,
                        latency_ms=latency_ms,
                    )
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "LLM call failed: provider=%s model=%s attempt=%d/%d error=%s",
                        prov_name, resolved_model, attempt + 1, max_retries + 1, exc,
                    )
                    if attempt < max_retries:
                        time.sleep(1.0 * (attempt + 1))

        raise RuntimeError(
            f"All LLM providers failed. Tried: {providers_to_try}. "
            f"Last error: {last_error}"
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        provider: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        json_mode: bool = False,
        max_retries: int = 2,
    ) -> LLMResponse:
        """Async chat completion with retry."""
        last_error: Exception | None = None
        providers_to_try = self._resolve_providers(provider)

        for prov_name in providers_to_try:
            prov = self.config.get_provider(prov_name)
            client = self._get_async_client(prov)
            resolved_model = model or prov.default_model
            resolved_max_tokens = max_tokens or prov.max_tokens

            for attempt in range(max_retries + 1):
                try:
                    start = time.monotonic()
                    kwargs: dict[str, Any] = {
                        "model": resolved_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": resolved_max_tokens,
                    }
                    if prov_name == "dashscope":
                        kwargs["extra_body"] = {"enable_thinking": False}
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}

                    result = await client.chat.completions.create(**kwargs)
                    latency_ms = int((time.monotonic() - start) * 1000)

                    content = result.choices[0].message.content or ""
                    usage = {}
                    if result.usage:
                        usage = {
                            "prompt_tokens": result.usage.prompt_tokens,
                            "completion_tokens": result.usage.completion_tokens,
                            "total_tokens": result.usage.total_tokens,
                        }

                    logger.info(
                        "LLM call success: provider=%s model=%s latency=%dms tokens=%d",
                        prov_name, resolved_model, latency_ms, usage.get("total_tokens", 0),
                    )
                    return LLMResponse(
                        content=content,
                        model=resolved_model,
                        provider=prov_name,
                        usage=usage,
                        latency_ms=latency_ms,
                    )
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "LLM call failed: provider=%s model=%s attempt=%d/%d error=%s",
                        prov_name, resolved_model, attempt + 1, max_retries + 1, exc,
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(1.0 * (attempt + 1))

        raise RuntimeError(
            f"All LLM providers failed. Tried: {providers_to_try}. "
            f"Last error: {last_error}"
        )

    def _resolve_providers(self, provider: str | None) -> list[str]:
        """Resolve provider list: explicit > default > fallback chain."""
        if provider and provider in self.config.providers:
            return [provider]
        if provider:
            logger.warning("Provider '%s' not available, trying fallback", provider)
        # Try default first, then all others
        available = self.config.available_providers
        default = self.config.default_provider
        if default in available:
            return [default] + [p for p in available if p != default]
        return available


# ── Module-level convenience functions ──

_global_gateway: LLMGateway | None = None


def _get_gateway() -> LLMGateway:
    global _global_gateway
    if _global_gateway is None:
        _global_gateway = LLMGateway.from_env()
    return _global_gateway


def chat_sync(
    messages: list[dict[str, str]],
    **kwargs: Any,
) -> LLMResponse:
    """Module-level synchronous chat."""
    return _get_gateway().chat_sync(messages, **kwargs)


async def chat(
    messages: list[dict[str, str]],
    **kwargs: Any,
) -> LLMResponse:
    """Module-level async chat."""
    return await _get_gateway().chat(messages, **kwargs)
