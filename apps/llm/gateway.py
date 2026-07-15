"""LLM Gateway — unified call interface with retry and fallback."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from openai import AsyncOpenAI, OpenAI

from apps.llm.config import LLMConfig, ProviderConfig
from apps.llm.audit import build_llm_call_audit_payload, infer_llm_caller, persist_llm_call_audit

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
    reasoning_effort: str | None = None
    audit_id: str | None = None

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
                max_retries=0,
            )
        return self._sync_clients[provider.name]

    def _get_async_client(self, provider: ProviderConfig) -> AsyncOpenAI:
        if provider.name not in self._async_clients:
            self._async_clients[provider.name] = AsyncOpenAI(
                api_key=provider.api_key,
                base_url=provider.base_url,
                timeout=provider.timeout,
                max_retries=0,
            )
        return self._async_clients[provider.name]

    def chat_sync(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        provider: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        json_mode: bool = False,
        max_retries: int = 2,
        reasoning_effort: str | None = None,
        request_timeout: float | None = None,
        audit_context: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        """Synchronous chat completion with retry."""
        call_id = str(uuid.uuid4())
        caller = str((audit_context or {}).get("caller") or infer_llm_caller())
        call_started = time.monotonic()
        last_error: Exception | None = None
        attempts: list[dict[str, Any]] = []
        providers_to_try = self._resolve_providers(provider)
        final_config: dict[str, Any] = {}

        for prov_name in providers_to_try:
            prov = self.config.get_provider(prov_name)
            client = self._get_sync_client(prov)
            resolved_model = model or prov.default_model
            resolved_max_tokens = max_tokens or prov.max_tokens
            resolved_reasoning_effort = reasoning_effort or prov.default_reasoning_effort
            final_config = _request_config(
                provider_requested=provider,
                model_requested=model,
                reasoning_effort_requested=reasoning_effort,
                provider_resolved=prov_name,
                model_resolved=resolved_model,
                reasoning_effort_resolved=resolved_reasoning_effort,
                provider_base_url=str(prov.base_url),
                temperature=temperature,
                max_tokens=resolved_max_tokens,
                json_mode=json_mode,
                max_retries=max_retries,
                request_timeout=request_timeout,
            )

            for attempt in range(max_retries + 1):
                attempt_started = time.monotonic()
                try:
                    start = time.monotonic()
                    kwargs: dict[str, Any] = {
                        "model": resolved_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": resolved_max_tokens,
                    }
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}
                    if resolved_reasoning_effort:
                        kwargs["reasoning_effort"] = resolved_reasoning_effort
                    if request_timeout is not None:
                        kwargs["timeout"] = request_timeout

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
                        "LLM call success: provider=%s model=%s reasoning=%s latency=%dms tokens=%d",
                        prov_name,
                        resolved_model,
                        resolved_reasoning_effort,
                        latency_ms,
                        usage.get("total_tokens", 0),
                    )
                    attempts.append(
                        {
                            "provider": prov_name,
                            "model": resolved_model,
                            "reasoning_effort": resolved_reasoning_effort,
                            "attempt": attempt + 1,
                            "status": "success",
                            "latency_ms": latency_ms,
                        }
                    )
                    audit_id = persist_llm_call_audit(
                        build_llm_call_audit_payload(
                            call_id=call_id,
                            status="success",
                            caller=caller,
                            messages=messages,
                            request_config=final_config,
                            response_text=content,
                            usage=usage,
                            latency_ms=int((time.monotonic() - call_started) * 1000),
                            attempts=attempts,
                            error=None,
                            audit_context=audit_context,
                        )
                    )
                    return LLMResponse(
                        content=content,
                        model=resolved_model,
                        provider=prov_name,
                        usage=usage,
                        latency_ms=latency_ms,
                        reasoning_effort=resolved_reasoning_effort,
                        audit_id=audit_id,
                    )
                except Exception as exc:
                    last_error = exc
                    attempts.append(
                        {
                            "provider": prov_name,
                            "model": resolved_model,
                            "reasoning_effort": resolved_reasoning_effort,
                            "attempt": attempt + 1,
                            "status": "failed",
                            "latency_ms": int((time.monotonic() - attempt_started) * 1000),
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        }
                    )
                    logger.warning(
                        "LLM call failed: provider=%s model=%s reasoning=%s attempt=%d/%d error=%s",
                        prov_name,
                        resolved_model,
                        resolved_reasoning_effort,
                        attempt + 1,
                        max_retries + 1,
                        exc,
                    )
                    if attempt < max_retries:
                        time.sleep(1.0 * (attempt + 1))

        final_error = RuntimeError(
            f"All LLM providers failed. Tried: {providers_to_try}. "
            f"Last error: {last_error}"
        )
        persist_llm_call_audit(
            build_llm_call_audit_payload(
                call_id=call_id,
                status="failed",
                caller=caller,
                messages=messages,
                request_config=final_config or _request_config(
                    provider_requested=provider,
                    model_requested=model,
                    reasoning_effort_requested=reasoning_effort,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    max_retries=max_retries,
                    request_timeout=request_timeout,
                ),
                response_text=None,
                usage=None,
                latency_ms=int((time.monotonic() - call_started) * 1000),
                attempts=attempts,
                error=last_error or final_error,
                audit_context=audit_context,
            )
        )
        raise final_error

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        provider: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        json_mode: bool = False,
        max_retries: int = 2,
        reasoning_effort: str | None = None,
        request_timeout: float | None = None,
        audit_context: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        """Async chat completion with retry."""
        call_id = str(uuid.uuid4())
        caller = str((audit_context or {}).get("caller") or infer_llm_caller())
        call_started = time.monotonic()
        last_error: Exception | None = None
        attempts: list[dict[str, Any]] = []
        providers_to_try = self._resolve_providers(provider)
        final_config: dict[str, Any] = {}

        for prov_name in providers_to_try:
            prov = self.config.get_provider(prov_name)
            client = self._get_async_client(prov)
            resolved_model = model or prov.default_model
            resolved_max_tokens = max_tokens or prov.max_tokens
            resolved_reasoning_effort = reasoning_effort or prov.default_reasoning_effort
            final_config = _request_config(
                provider_requested=provider,
                model_requested=model,
                reasoning_effort_requested=reasoning_effort,
                provider_resolved=prov_name,
                model_resolved=resolved_model,
                reasoning_effort_resolved=resolved_reasoning_effort,
                provider_base_url=str(prov.base_url),
                temperature=temperature,
                max_tokens=resolved_max_tokens,
                json_mode=json_mode,
                max_retries=max_retries,
                request_timeout=request_timeout,
            )

            for attempt in range(max_retries + 1):
                attempt_started = time.monotonic()
                try:
                    start = time.monotonic()
                    kwargs: dict[str, Any] = {
                        "model": resolved_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": resolved_max_tokens,
                    }
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}
                    if resolved_reasoning_effort:
                        kwargs["reasoning_effort"] = resolved_reasoning_effort
                    if request_timeout is not None:
                        kwargs["timeout"] = request_timeout

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
                        "LLM call success: provider=%s model=%s reasoning=%s latency=%dms tokens=%d",
                        prov_name,
                        resolved_model,
                        resolved_reasoning_effort,
                        latency_ms,
                        usage.get("total_tokens", 0),
                    )
                    attempts.append(
                        {
                            "provider": prov_name,
                            "model": resolved_model,
                            "reasoning_effort": resolved_reasoning_effort,
                            "attempt": attempt + 1,
                            "status": "success",
                            "latency_ms": latency_ms,
                        }
                    )
                    audit_id = persist_llm_call_audit(
                        build_llm_call_audit_payload(
                            call_id=call_id,
                            status="success",
                            caller=caller,
                            messages=messages,
                            request_config=final_config,
                            response_text=content,
                            usage=usage,
                            latency_ms=int((time.monotonic() - call_started) * 1000),
                            attempts=attempts,
                            error=None,
                            audit_context=audit_context,
                        )
                    )
                    return LLMResponse(
                        content=content,
                        model=resolved_model,
                        provider=prov_name,
                        usage=usage,
                        latency_ms=latency_ms,
                        reasoning_effort=resolved_reasoning_effort,
                        audit_id=audit_id,
                    )
                except Exception as exc:
                    last_error = exc
                    attempts.append(
                        {
                            "provider": prov_name,
                            "model": resolved_model,
                            "reasoning_effort": resolved_reasoning_effort,
                            "attempt": attempt + 1,
                            "status": "failed",
                            "latency_ms": int((time.monotonic() - attempt_started) * 1000),
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        }
                    )
                    logger.warning(
                        "LLM call failed: provider=%s model=%s reasoning=%s attempt=%d/%d error=%s",
                        prov_name,
                        resolved_model,
                        resolved_reasoning_effort,
                        attempt + 1,
                        max_retries + 1,
                        exc,
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(1.0 * (attempt + 1))

        final_error = RuntimeError(
            f"All LLM providers failed. Tried: {providers_to_try}. "
            f"Last error: {last_error}"
        )
        persist_llm_call_audit(
            build_llm_call_audit_payload(
                call_id=call_id,
                status="failed",
                caller=caller,
                messages=messages,
                request_config=final_config or _request_config(
                    provider_requested=provider,
                    model_requested=model,
                    reasoning_effort_requested=reasoning_effort,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    max_retries=max_retries,
                    request_timeout=request_timeout,
                ),
                response_text=None,
                usage=None,
                latency_ms=int((time.monotonic() - call_started) * 1000),
                attempts=attempts,
                error=last_error or final_error,
                audit_context=audit_context,
            )
        )
        raise final_error

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


def _request_config(
    *,
    provider_requested: str | None,
    model_requested: str | None,
    reasoning_effort_requested: str | None,
    temperature: float,
    max_tokens: int | None,
    json_mode: bool,
    max_retries: int,
    request_timeout: float | None,
    provider_resolved: str | None = None,
    model_resolved: str | None = None,
    reasoning_effort_resolved: str | None = None,
    provider_base_url: str | None = None,
) -> dict[str, Any]:
    return {
        "requested": {
            "provider": provider_requested,
            "model": model_requested,
            "reasoning_effort": reasoning_effort_requested,
        },
        "resolved": {
            "provider": provider_resolved,
            "model": model_resolved,
            "reasoning_effort": reasoning_effort_resolved,
            "base_url": provider_base_url,
        },
        "parameters": {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "json_mode": json_mode,
            "max_retries": max_retries,
            "request_timeout": request_timeout,
        },
        "secrets_redacted": True,
    }


# ── Module-level convenience functions ──

_global_gateway: LLMGateway | None = None


def _get_gateway() -> LLMGateway:
    global _global_gateway
    if _global_gateway is None:
        _global_gateway = LLMGateway.from_env()
    return _global_gateway


def chat_sync(
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> LLMResponse:
    """Module-level synchronous chat."""
    return _get_gateway().chat_sync(messages, **kwargs)


async def chat(
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> LLMResponse:
    """Module-level async chat."""
    return await _get_gateway().chat(messages, **kwargs)
