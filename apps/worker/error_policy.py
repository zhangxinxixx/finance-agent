from __future__ import annotations


RETRYABLE_ERROR_TYPES = frozenset({"network_timeout", "data_unavailable"})


def classify_error_type(exc: Exception) -> str:
    """Classify an exception into a structured error type for observability."""
    exc_name = type(exc).__name__
    exc_msg = str(exc).lower()

    # Network / connectivity errors
    if exc_name in (
        "ConnectionError",
        "TimeoutError",
        "ConnectTimeout",
        "ReadTimeout",
        "ConnectionResetError",
        "SocketError",
    ) or "timeout" in exc_msg or "connection" in exc_msg:
        return "network_timeout"

    # Data unavailable (source returned no data / 404)
    if exc_name in ("DataUnavailableError",) or "not found" in exc_msg or "unavailable" in exc_msg:
        return "data_unavailable"

    # Parse / validation errors (bad data, won't fix on retry)
    if exc_name in (
        "ValueError",
        "TypeError",
        "KeyError",
        "JSONDecodeError",
        "ValidationError",
    ) or "parse" in exc_msg:
        return "parse_failure"

    # Config / setup errors (won't fix on retry)
    if exc_name in (
        "ConfigError",
        "EnvironmentError",
        "KeyError",
    ) or "config" in exc_msg or "api key" in exc_msg:
        return "config_error"

    # Default: unknown, conservatively retryable by caller policy if desired.
    return "unknown"


def is_retryable_error_type(error_type: str | None) -> bool:
    return str(error_type or "") in RETRYABLE_ERROR_TYPES
