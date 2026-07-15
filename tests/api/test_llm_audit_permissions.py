from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.api.routes.llm_audit_routes import require_audit_reader
from apps.api.services.llm_audit_service import audit_detail


def _request(host: str, *, forwarded_for: str = "") -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host=host), headers={"x-forwarded-for": forwarded_for})


def test_audit_reader_permission_allows_unconfigured_local_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINANCE_AGENT_AUDIT_READER_TOKEN", raising=False)
    assert require_audit_reader(_request("127.0.0.1"), None) is None
    assert require_audit_reader(_request("::1"), None) is None
    assert require_audit_reader(_request("127.0.0.1", forwarded_for="::1"), None) is None

    with pytest.raises(HTTPException) as disabled:
        require_audit_reader(_request("203.0.113.7"), None)
    assert disabled.value.status_code == 503
    with pytest.raises(HTTPException) as proxied_remote:
        require_audit_reader(_request("127.0.0.1", forwarded_for="203.0.113.7"), None)
    assert proxied_remote.value.status_code == 503

    monkeypatch.setenv("FINANCE_AGENT_AUDIT_READER_TOKEN", "reader-secret")
    with pytest.raises(HTTPException) as forbidden:
        require_audit_reader(_request("127.0.0.1"), "wrong")
    assert forbidden.value.status_code == 403
    assert require_audit_reader(_request("203.0.113.7"), "reader-secret") is None


def test_audit_detail_hides_content_unless_explicitly_requested() -> None:
    row = SimpleNamespace(
        id="audit-1",
        call_id="call-1",
        status="success",
        caller="test",
        provider_requested=None,
        provider_resolved="local",
        model_requested=None,
        model_resolved="model",
        reasoning_effort_requested=None,
        reasoning_effort_resolved=None,
        request_config={"sanitization_performed": True, "secrets_redacted": True},
        request_messages=[{"role": "user", "content": "private prompt"}],
        request_sha256="a" * 64,
        response_text="private response",
        response_sha256="b" * 64,
        usage={},
        latency_ms=1,
        attempts=[{"status": "success"}],
        attempt_count=1,
        error_type=None,
        error_message=None,
        context={"private": True},
        source_refs=[{"source": "internal"}],
        run_id=None,
        snapshot_id=None,
        report_id=None,
        trade_date=None,
        created_at=None,
    )

    metadata = audit_detail(row, include_content=False)
    content = audit_detail(row, include_content=True)

    assert metadata["content_included"] is False
    assert metadata["request_messages"] == []
    assert metadata["response_text"] is None
    assert content["content_included"] is True
    assert content["request_messages"][0]["content"] == "private prompt"
