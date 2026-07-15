from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from apps.llm.audit import build_llm_call_audit_payload, sanitize_audit_value
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
    return LLMGateway(LLMConfig(providers={"cockpit": provider}, default_provider="cockpit"))


def test_audit_sanitizes_credentials_and_image_data_url() -> None:
    value = sanitize_audit_value(
        {
            "api_key": "secret",
            "messages": [{"content": "data:image/png;base64,ZmFrZQ=="}],
        }
    )
    assert value["api_key"] == "[REDACTED]"
    image = value["messages"][0]["content"]
    assert image["redacted"] == "data_url"
    assert image["sha256"]
    assert "ZmFrZQ" not in str(value)


def test_audit_sanitizes_credentials_embedded_in_plain_strings() -> None:
    value = sanitize_audit_value(
        "Authorization: Bearer abcdefghijklmnop api_key=top-secret user@example.com sk-abcdefghijk"
    )

    assert "abcdefghijklmnop" not in value
    assert "top-secret" not in value
    assert "user@example.com" not in value
    assert "sk-abcdefghijk" not in value


def test_gateway_records_exact_sanitized_request_and_output(monkeypatch) -> None:
    gateway = _gateway()
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="raw output"))],
                    usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
                )
            )
        )
    )
    gateway._sync_clients["cockpit"] = client
    captured: list[dict] = []
    monkeypatch.setenv("FINANCE_AGENT_ENABLE_LLM_AUDIT_IN_TESTS", "1")
    with patch("apps.llm.gateway.persist_llm_call_audit", side_effect=lambda payload: captured.append(payload) or "audit-1"):
        response = gateway.chat_sync(
            [{"role": "user", "content": "exact prompt"}],
            audit_context={"run_id": "run-1", "input_payload": {"value": 1}},
        )
    assert response.audit_id == "audit-1"
    assert len(captured) == 1
    assert captured[0]["request_messages"][0]["content"] == "exact prompt"
    assert captured[0]["response_text"] == "raw output"
    assert captured[0]["context"]["run_id"] == "run-1"
    assert captured[0]["request_config"]["resolved"]["model"] == "gpt-5.6-sol"


def test_audit_payload_hash_is_stable() -> None:
    payload = build_llm_call_audit_payload(
        call_id="call-1",
        status="success",
        caller="test",
        messages=[{"role": "user", "content": "prompt"}],
        request_config={"requested": {}, "resolved": {}, "parameters": {}},
        response_text="output",
        usage={"total_tokens": 1},
        latency_ms=1,
        attempts=[{"status": "success"}],
        error=None,
        audit_context=None,
    )
    assert len(payload["request_sha256"]) == 64
    assert len(payload["response_sha256"]) == 64


def test_audit_payload_sanitizes_response_and_error_and_reports_actual_redaction() -> None:
    payload = build_llm_call_audit_payload(
        call_id="call-secret",
        status="failed",
        caller="test",
        messages=[{"role": "user", "content": "safe prompt"}],
        request_config={"requested": {}, "resolved": {}, "parameters": {}},
        response_text="token=abcdefghijk",
        usage={},
        latency_ms=1,
        attempts=[],
        error=RuntimeError("Authorization: Bearer abcdefghijk"),
        audit_context=None,
    )

    assert "abcdefghijk" not in payload["response_text"]
    assert "abcdefghijk" not in payload["error_message"]
    assert payload["request_config"]["sanitization_performed"] is True
    assert payload["request_config"]["secrets_redacted"] is True
