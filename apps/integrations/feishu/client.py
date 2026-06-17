from __future__ import annotations

import time
from typing import Any

import httpx


class FeishuOpenApiError(RuntimeError):
    """Raised when Feishu OpenAPI returns a transport or application error."""


class FeishuOpenApiClient:
    """Small Feishu OpenAPI client using app credentials and tenant tokens."""

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        base_url: str = "https://open.feishu.cn",
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.app_id = app_id.strip()
        self.app_secret = app_secret.strip()
        self.base_url = base_url.rstrip("/")
        self._http_client = http_client or httpx.Client(timeout=timeout_seconds, headers={"User-Agent": "finance-agent/0.1"})
        self._owns_client = http_client is None
        self._tenant_access_token: str | None = None
        self._token_expires_at = 0.0

        if not self.app_id or not self.app_secret:
            raise ValueError("app_id and app_secret are required")

    def close(self) -> None:
        if self._owns_client:
            self._http_client.close()

    def get_tenant_access_token(self, *, force_refresh: bool = False) -> str:
        now = time.time()
        if not force_refresh and self._tenant_access_token and now < self._token_expires_at:
            return self._tenant_access_token

        response = self._http_client.post(
            f"{self.base_url}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        payload = _response_json(response)
        _raise_for_feishu_error(response=response, payload=payload, endpoint="tenant_access_token")
        token = str(payload.get("tenant_access_token") or "").strip()
        if not token:
            raise FeishuOpenApiError("tenant_access_token response did not include a token")
        expire_seconds = _coerce_int(payload.get("expire"), default=7200)
        self._tenant_access_token = token
        self._token_expires_at = now + max(expire_seconds - 300, 60)
        return token

    def list_chat_messages(
        self,
        *,
        chat_id: str,
        page_size: int = 50,
        page_token: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        sort_type: str = "ByCreateTimeDesc",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "page_size": page_size,
            "sort_type": sort_type,
        }
        if page_token:
            params["page_token"] = page_token
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        return self._get_json("/open-apis/im/v1/messages", params=params)

    def _get_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        token = self.get_tenant_access_token()
        response = self._http_client.get(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        payload = _response_json(response)
        if response.status_code == 401 or _looks_like_token_error(payload):
            token = self.get_tenant_access_token(force_refresh=True)
            response = self._http_client.get(
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            payload = _response_json(response)
        _raise_for_feishu_error(response=response, payload=payload, endpoint=path)
        return payload


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise FeishuOpenApiError(f"Feishu response is not JSON: HTTP {response.status_code}") from exc
    if not isinstance(payload, dict):
        raise FeishuOpenApiError(f"Feishu response JSON is not an object: HTTP {response.status_code}")
    return payload


def _raise_for_feishu_error(*, response: httpx.Response, payload: dict[str, Any], endpoint: str) -> None:
    if response.status_code >= 400:
        raise FeishuOpenApiError(f"{endpoint} HTTP {response.status_code}: {payload}")
    code = payload.get("code", 0)
    if code not in (0, None):
        raise FeishuOpenApiError(f"{endpoint} Feishu code {code}: {payload.get('msg') or payload.get('message') or payload}")


def _looks_like_token_error(payload: dict[str, Any]) -> bool:
    code = payload.get("code")
    if code in {99991661, 99991663, 99991664, 99991668}:
        return True
    message = str(payload.get("msg") or payload.get("message") or "").lower()
    return "token" in message and ("invalid" in message or "expire" in message)


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
