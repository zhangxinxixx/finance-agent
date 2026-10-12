from __future__ import annotations

import asyncio
import json
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


def _failover_gateway() -> LLMGateway:
    cockpit = ProviderConfig(
        name="cockpit",
        api_key="cockpit-key",
        base_url="http://127.0.0.1:46483/v1",
        default_model="gpt-5.6-sol",
        default_reasoning_effort="high",
    )
    jojocode = ProviderConfig(
        name="jojocode",
        api_key="jojocode-key",
        base_url="https://max.jojocode.com/v1",
        default_model="gpt-5.6-sol",
        default_reasoning_effort="high",
    )
    mimo = ProviderConfig(
        name="mimo",
        api_key="mimo-key",
        base_url="https://example.invalid/v1",
        default_model="mimo-v2.5-pro",
    )
    return LLMGateway(
        LLMConfig(
            providers={"cockpit": cockpit, "jojocode": jojocode, "mimo": mimo},
            default_provider="cockpit",
            fallback_providers=("jojocode",),
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


def test_jojocode_reuses_existing_cockpit_account(monkeypatch, tmp_path) -> None:
    provider_file = tmp_path / "codex_model_providers.json"
    provider_file.write_text(
        json.dumps([
            {
                "name": "jojo",
                "baseUrl": "https://max.jojocode.com",
                "apiKeys": [{"apiKey": "wrong-root-key"}],
            },
            {
                "name": "jojo",
                "baseUrl": "https://max.jojocode.com/v1",
                "apiKeys": [{"apiKey": "existing-team-key"}],
            },
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("JOJOCODE_API_KEY", "")
    monkeypatch.setenv("JOJOCODE_BASE_URL", "")
    monkeypatch.setenv("JOJOCODE_COCKPIT_PROVIDERS_FILE", str(provider_file))

    provider = LLMConfig.from_env().get_provider("jojocode")

    assert provider.api_key == "existing-team-key"
    assert provider.base_url == "https://max.jojocode.com/v1"
    assert provider.default_model == "gpt-5.6-sol"


def test_config_builds_cockpit_jojocode_primary_backup_chain(monkeypatch) -> None:
    monkeypatch.setenv("COCKPIT_API_KEY", "cockpit-key")
    monkeypatch.setenv("COCKPIT_BASE_URL", "http://127.0.0.1:46483/v1")
    monkeypatch.setenv("JOJOCODE_API_KEY", "jojocode-key")
    monkeypatch.setenv("JOJOCODE_BASE_URL", "https://max.jojocode.com/v1")
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "cockpit")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "jojocode,missing,jojocode,cockpit")

    config = LLMConfig.from_env()

    assert config.default_provider == "cockpit"
    assert config.fallback_providers == ("jojocode",)
    assert config.provider_chain == ["cockpit", "jojocode"]


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


def test_gateway_uses_only_configured_primary_backup_chain() -> None:
    gateway = _failover_gateway()

    assert gateway._resolve_providers(None) == ["cockpit", "jojocode"]
    assert gateway._resolve_providers("cockpit") == ["cockpit", "jojocode"]
    assert gateway._resolve_providers("jojocode") == ["jojocode"]


def test_gateway_fails_over_from_cockpit_to_jojocode_and_audits_attempts() -> None:
    gateway = _failover_gateway()

    def cockpit_create(**kwargs):
        raise TimeoutError("cockpit timeout")

    def jojocode_create(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="backup ok"))],
            usage=None,
        )

    gateway._sync_clients["cockpit"] = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=cockpit_create))
    )
    gateway._sync_clients["jojocode"] = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=jojocode_create))
    )
    audits: list[dict] = []

    with patch(
        "apps.llm.gateway.persist_llm_call_audit",
        side_effect=lambda payload: audits.append(payload) or "audit-failover",
    ):
        response = gateway.chat_sync(
            [{"role": "user", "content": "test"}],
            provider="cockpit",
            max_retries=0,
        )

    assert response.content == "backup ok"
    assert response.provider == "jojocode"
    assert response.audit_id == "audit-failover"
    assert [item["provider"] for item in audits[0]["attempts"]] == ["cockpit", "jojocode"]
    assert [item["status"] for item in audits[0]["attempts"]] == ["failed", "success"]
    assert audits[0]["provider_resolved"] == "jojocode"


def test_async_gateway_fails_over_from_cockpit_to_jojocode() -> None:
    gateway = _failover_gateway()

    async def cockpit_create(**kwargs):
        raise TimeoutError("cockpit timeout")

    async def jojocode_create(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="backup ok"))],
            usage=None,
        )

    gateway._async_clients["cockpit"] = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=cockpit_create))
    )
    gateway._async_clients["jojocode"] = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=jojocode_create))
    )

    with patch("apps.llm.gateway.persist_llm_call_audit", return_value="audit-async"):
        response = asyncio.run(
            gateway.chat(
                [{"role": "user", "content": "test"}],
                provider="cockpit",
                max_retries=0,
            )
        )

    assert response.content == "backup ok"
    assert response.provider == "jojocode"
    assert response.audit_id == "audit-async"
