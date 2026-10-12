from contextlib import contextmanager
from datetime import date
import json
from types import SimpleNamespace

import pytest
from curl_cffi import CurlInfo, requests

from scripts import fedwatch_settlement_transport_probe as probe


@pytest.mark.parametrize(
    "code,message,timing,expected",
    [
        (5, "", {}, "proxy_failed"),
        (6, "", {}, "dns_failed"),
        (35, "", {}, "tls_failed"),
        (16, "", {}, "http2_failed"),
        (92, "", {}, "http2_failed"),
        (52, "", {}, "remote_closed"),
        (56, "connection reset by peer", {}, "connect_reset"),
        (56, "receive failure", {}, "receive_failed"),
        (28, "", {}, "timeout_stage_unknown"),
        (28, "", {"connect_seconds": 1}, "tls_timeout"),
        (28, "", {"tls_seconds": 1}, "read_timeout"),
    ],
)
def test_failure_classification_does_not_guess_unobserved_stage(code, message, timing, expected):
    assert probe.classify(code, message, timing) == expected


def test_redacts_error_urls_and_auth():
    value = "https://user:password@proxy.local?token=abc token=def\nAuthorization: Bearer ghijk\nCookie: secret"
    result = probe.sanitize_error(value)
    assert not any(secret in result for secret in ("password", "abc", "def", "ghijk", "secret", "proxy.local"))


def test_actual_proxy_info_not_inferred_from_configuration():
    response = SimpleNamespace(
        primary_ip="127.0.0.1",
        http_version=3,
        status_code=200,
        headers={"Set-Cookie": "secret", "Date": "today"},
        infos={CurlInfo.USED_PROXY: 1},
    )
    result = probe.response_metrics(response)
    assert result["proxy_used"] == 1
    assert result["http_version"] == "HTTP/2"
    assert result["response_headers"] == {"date": "today"}


def test_failed_request_archives_diagnostics_without_retry(tmp_path):
    calls = []

    class Client:
        @contextmanager
        def stream(self, *args, **kwargs):
            calls.append(1)
            raise requests.RequestsError("TLS error https://user:pass@proxy.local", code=35)
            yield  # pragma: no cover

    row = probe.request_once(
        Client(),
        day=date(2026, 9, 25),
        case="new",
        attempt=1,
        run_id="test",
        output=tmp_path,
        tls={},
        interval_seconds=30,
    )
    assert len(calls) == 1
    assert row["failure_type"] == "tls_failed" and row["response_status"] is None
    assert row["tls_version"] is None
    assert "proxy.local" not in json.dumps(row)
    assert (tmp_path / row["request_id"] / "diagnostic.json").exists()


@pytest.mark.parametrize(
    "extra", [["--interval", "0"], ["--repeats", "10"], ["--cases", "new", "new"], ["--cooldown-check", "1"]]
)
def test_cli_rejects_unbounded_or_high_frequency_requests(tmp_path, extra):
    with pytest.raises(SystemExit):
        probe.main(["--trade-date", "2026-09-25", "--output", str(tmp_path), *extra])


def test_explicit_direct_sets_libcurl_proxy_override(monkeypatch):
    captured = {}
    monkeypatch.setattr(probe.requests, "Session", lambda **kwargs: captured.update(kwargs))
    probe.session_for("direct", {})
    assert captured["curl_options"][probe.CurlOpt.PROXY] == ""
    assert captured["retry"] == 0
