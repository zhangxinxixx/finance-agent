from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from apps.llm.config import LLMConfig, ProviderConfig
from apps.llm.gateway import LLMGateway


def _gateway() -> LLMGateway:
    provider = ProviderConfig(
        name="cockpit",
        api_key="test-key",
        base_url="http://127.0.0.1:46483/v1",
        default_model="gpt-5.6-sol",
        max_tokens=4096,
        timeout=180.0,
        default_reasoning_effort="high",
    )
    return LLMGateway(
        LLMConfig(
            providers={"cockpit": provider},
            default_provider="cockpit",
        )
    )


def test_gateway_disables_sync_sdk_retries() -> None:
    gateway = _gateway()
    provider = gateway.config.get_provider("cockpit")

    with patch("apps.llm.gateway.OpenAI") as constructor:
        gateway._get_sync_client(provider)

    constructor.assert_called_once_with(
        api_key="test-key",
        base_url="http://127.0.0.1:46483/v1",
        timeout=180.0,
        max_retries=0,
    )


def test_gateway_disables_async_sdk_retries() -> None:
    gateway = _gateway()
    provider = gateway.config.get_provider("cockpit")

    with patch("apps.llm.gateway.AsyncOpenAI") as constructor:
        gateway._get_async_client(provider)

    constructor.assert_called_once_with(
        api_key="test-key",
        base_url="http://127.0.0.1:46483/v1",
        timeout=180.0,
        max_retries=0,
    )


def test_cockpit_defaults_to_sol_high(monkeypatch) -> None:
    monkeypatch.setenv("COCKPIT_API_KEY", "test-key")
    monkeypatch.setenv("COCKPIT_BASE_URL", "http://127.0.0.1:46483/v1")
    monkeypatch.delenv("LLM_COCKPIT_MODEL", raising=False)
    monkeypatch.delenv("LLM_COCKPIT_REASONING_EFFORT", raising=False)

    provider = LLMConfig.from_env().get_provider("cockpit")

    assert provider.default_model == "gpt-5.6-sol"
    assert provider.default_reasoning_effort == "high"


def test_gateway_passes_default_reasoning_effort_to_cockpit() -> None:
    gateway = _gateway()
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                    usage=None,
                    request_kwargs=kwargs,
                )
            )
        )
    )
    gateway._sync_clients["cockpit"] = client

    with patch.object(client.chat.completions, "create", wraps=client.chat.completions.create) as create:
        response = gateway.chat_sync([{"role": "user", "content": "test"}])

    assert create.call_args.kwargs["model"] == "gpt-5.6-sol"
    assert create.call_args.kwargs["reasoning_effort"] == "high"
    assert response.model == "gpt-5.6-sol"
    assert response.reasoning_effort == "high"
