"""Typed Twelve Data REST client with raw response archival."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import httpx

from apps.runtime.secret_resolver import resolve_runtime_secret


TWELVE_DATA_API_URL = "https://api.twelvedata.com/time_series"
TWELVE_DATA_API_KEY_ENV = "TWELVE_DATA_API_KEY"
TWELVE_DATA_SOURCE_KEY = "twelvedata_xauusd"
TWELVE_DATA_SYMBOL = "XAU/USD"
SUPPORTED_INTERVALS: dict[str, str] = {
    "5min": "5m",
    "15min": "15m",
    "1h": "1h",
    "4h": "4h",
}


class TwelveDataError(RuntimeError):
    """Base error for Twelve Data collection failures."""


class TwelveDataTransportError(TwelveDataError):
    """The HTTP request did not produce a usable response."""


class TwelveDataQuotaError(TwelveDataError):
    """The provider rejected the request because quota was exhausted."""


class TwelveDataPayloadError(TwelveDataError):
    """The provider response did not satisfy the candle contract."""


@dataclass(frozen=True)
class TwelveDataCandle:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True)
class TwelveDataFetchResult:
    symbol: str
    provider_interval: str
    timeframe: str
    candles: tuple[TwelveDataCandle, ...]
    retrieved_at: datetime
    raw_path: str
    http_status: int
    credits_used: int | None
    credits_left: int | None

    def source_ref(self) -> dict[str, Any]:
        return {
            "provider": "twelve_data",
            "provider_symbol": self.symbol,
            "instrument_type": "composite_otc_spot_proxy",
            "source_key": TWELVE_DATA_SOURCE_KEY,
            "source_role": "validation_and_fallback",
            "provider_timeframe": self.provider_interval,
            "retrieved_at": self.retrieved_at.isoformat(),
            "raw_path": self.raw_path,
            "credits_used": self.credits_used,
            "credits_left": self.credits_left,
        }


class TwelveDataClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        storage_root: Path | str = "storage",
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 20.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_key = (api_key or resolve_runtime_secret(TWELVE_DATA_API_KEY_ENV) or "").strip()
        if not self._api_key:
            raise RuntimeError(f"{TWELVE_DATA_API_KEY_ENV} is not configured")
        self.storage_root = Path(storage_root)
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch_time_series(
        self,
        *,
        interval: str,
        outputsize: int = 20,
        symbol: str = TWELVE_DATA_SYMBOL,
        timezone: str = "UTC",
    ) -> TwelveDataFetchResult:
        if interval not in SUPPORTED_INTERVALS:
            raise ValueError(f"unsupported Twelve Data interval: {interval}")
        if timezone != "UTC":
            raise ValueError("Twelve Data candle collection currently requires timezone=UTC")
        normalized_outputsize = max(1, min(int(outputsize), 5000))
        retrieved_at = self._as_utc(self._clock())
        request_params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": normalized_outputsize,
            "timezone": timezone,
            "order": "DESC",
        }

        try:
            response = self._request(request_params)
        except httpx.HTTPError as exc:
            raw_path = self._archive(
                retrieved_at=retrieved_at,
                symbol=symbol,
                interval=interval,
                request_params=request_params,
                http_status=None,
                response_headers={},
                payload=None,
                error={"type": type(exc).__name__, "message": str(exc)},
            )
            raise TwelveDataTransportError(f"Twelve Data request failed; raw={raw_path}: {exc}") from exc

        payload = self._response_payload(response)
        credit_headers = self._credit_headers(response.headers)
        raw_path = self._archive(
            retrieved_at=retrieved_at,
            symbol=symbol,
            interval=interval,
            request_params=request_params,
            http_status=response.status_code,
            response_headers=credit_headers,
            payload=payload,
            error=None,
        )

        api_code = self._int_or_none(payload.get("code")) if isinstance(payload, dict) else None
        if response.status_code == 429 or api_code == 429:
            raise TwelveDataQuotaError(f"Twelve Data quota exhausted; raw={raw_path}")
        if response.status_code >= 400:
            raise TwelveDataTransportError(f"Twelve Data HTTP {response.status_code}; raw={raw_path}")
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            message = payload.get("message") if isinstance(payload, dict) else "non-object response"
            raise TwelveDataPayloadError(f"Twelve Data returned an error payload: {message}; raw={raw_path}")

        candles = self._parse_candles(payload.get("values"), raw_path=raw_path)
        return TwelveDataFetchResult(
            symbol=symbol,
            provider_interval=interval,
            timeframe=SUPPORTED_INTERVALS[interval],
            candles=tuple(candles),
            retrieved_at=retrieved_at,
            raw_path=raw_path,
            http_status=response.status_code,
            credits_used=self._int_or_none(credit_headers.get("api-credits-used")),
            credits_left=self._int_or_none(credit_headers.get("api-credits-left")),
        )

    def _request(self, params: dict[str, Any]) -> httpx.Response:
        headers = {"Authorization": f"apikey {self._api_key}", "User-Agent": "finance-agent/0.1"}
        if self._http_client is not None:
            return self._http_client.get(TWELVE_DATA_API_URL, params=params, headers=headers)
        with httpx.Client(timeout=self._timeout_seconds, trust_env=True) as client:
            return client.get(TWELVE_DATA_API_URL, params=params, headers=headers)

    @staticmethod
    def _response_payload(response: httpx.Response) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    @classmethod
    def _parse_candles(cls, values: Any, *, raw_path: str) -> list[TwelveDataCandle]:
        if not isinstance(values, list) or not values:
            raise TwelveDataPayloadError(f"Twelve Data payload has no candles; raw={raw_path}")

        candles: list[TwelveDataCandle] = []
        seen: set[datetime] = set()
        for row in values:
            if not isinstance(row, dict):
                raise TwelveDataPayloadError(f"Twelve Data candle is not an object; raw={raw_path}")
            try:
                open_time = cls._parse_datetime(row.get("datetime"))
                open_ = float(row["open"])
                high = float(row["high"])
                low = float(row["low"])
                close = float(row["close"])
            except (KeyError, TypeError, ValueError) as exc:
                raise TwelveDataPayloadError(f"Twelve Data candle fields are invalid; raw={raw_path}") from exc
            if open_time in seen:
                raise TwelveDataPayloadError(f"Twelve Data returned a duplicate timestamp; raw={raw_path}")
            if high < max(open_, close) or low > min(open_, close) or high < low:
                raise TwelveDataPayloadError(f"Twelve Data returned invalid OHLC; raw={raw_path}")
            seen.add(open_time)
            candles.append(TwelveDataCandle(open_time=open_time, open=open_, high=high, low=low, close=close))
        return sorted(candles, key=lambda item: item.open_time)

    def _archive(
        self,
        *,
        retrieved_at: datetime,
        symbol: str,
        interval: str,
        request_params: dict[str, Any],
        http_status: int | None,
        response_headers: dict[str, str],
        payload: dict[str, Any] | None,
        error: dict[str, str] | None,
    ) -> str:
        raw_dir = self.storage_root / "raw" / "market" / "twelvedata" / retrieved_at.date().isoformat()
        raw_dir.mkdir(parents=True, exist_ok=True)
        safe_symbol = symbol.replace("/", "-")
        suffix = retrieved_at.strftime("%H%M%S%f")
        raw_file = raw_dir / f"{safe_symbol}-{interval}-{suffix}-{uuid4().hex[:8]}.json"
        archive_payload = {
            "provider": "twelve_data",
            "provider_symbol": symbol,
            "source_key": TWELVE_DATA_SOURCE_KEY,
            "request": request_params,
            "retrieved_at": retrieved_at.isoformat(),
            "http_status": http_status,
            "response_headers": response_headers,
            "response": payload,
            "error": error,
            "parser_version": "twelvedata_time_series_v1",
        }
        raw_file.write_text(json.dumps(archive_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return raw_file.relative_to(self.storage_root).as_posix()

    @staticmethod
    def _credit_headers(headers: httpx.Headers) -> dict[str, str]:
        names = ("api-credits-used", "api-credits-left", "api-credits-request", "api-source-node")
        return {name: value for name in names if (value := headers.get(name)) is not None}

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("missing datetime")
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return TwelveDataClient._as_utc(parsed)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None
