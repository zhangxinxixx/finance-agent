from __future__ import annotations

import json

import httpx

from apps.integrations.feishu.client import FeishuOpenApiClient


def test_feishu_client_uses_app_credentials_and_caches_tenant_access_token() -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tenant-token", "expire": 7200})
        assert request.headers["authorization"] == "Bearer tenant-token"
        assert request.url.params["container_id_type"] == "chat"
        assert request.url.params["container_id"] == "chat_fixture"
        return httpx.Response(200, json={"code": 0, "data": {"items": []}})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = FeishuOpenApiClient(app_id="cli_test", app_secret="secret", http_client=http_client)

    client.list_chat_messages(chat_id="chat_fixture", page_size=20)
    client.list_chat_messages(chat_id="chat_fixture", page_size=20)

    token_calls = [call for call in calls if call[1].endswith("/tenant_access_token/internal")]
    message_calls = [call for call in calls if call[1].endswith("/im/v1/messages")]
    assert len(token_calls) == 1
    assert len(message_calls) == 2
    assert token_calls[0][2] == {"app_id": "cli_test", "app_secret": "secret"}


def test_feishu_client_refreshes_token_once_when_message_request_reports_token_error() -> None:
    tokens = ["old-token", "new-token"]
    seen_authorizations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": tokens.pop(0), "expire": 7200})
        seen_authorizations.append(request.headers["authorization"])
        if len(seen_authorizations) == 1:
            return httpx.Response(200, json={"code": 99991663, "msg": "tenant access token invalid"})
        return httpx.Response(200, json={"code": 0, "data": {"items": [{"message_id": "om_1"}]}})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = FeishuOpenApiClient(app_id="cli_test", app_secret="secret", http_client=http_client)

    payload = client.list_chat_messages(chat_id="chat_fixture")

    assert payload["data"]["items"][0]["message_id"] == "om_1"
    assert seen_authorizations == ["Bearer old-token", "Bearer new-token"]
