from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from apps.collectors.macro import fedwatch_free
from apps.collectors.macro.fedwatch_free import IFRAME_URL, PARENT_URL, collect_fedwatch_free
from apps.parsers.macro.fedwatch_free import (
    FedWatchParseError,
    normalize_fedwatch_rows,
    parse_fedwatch_free_payload,
)


def _distribution(window: str, as_of: str, probabilities: tuple[float, float] = (0.4, 0.6)) -> list[dict]:
    return [
        {
            "meeting_date": "2026-10-28",
            "contract_ref": "ZQV6",
            "comparison_window": window,
            "as_of": as_of,
            "target_low": 3.75,
            "target_high": 4.0,
            "probability": probabilities[0],
        },
        {
            "meeting_date": "2026-10-28",
            "contract_ref": "ZQV6",
            "comparison_window": window,
            "as_of": as_of,
            "target_low": 4.0,
            "target_high": 4.25,
            "probability": probabilities[1],
        },
    ]


def test_normalize_rows_preserves_actual_window_dates_and_complete_coverage() -> None:
    # Synthetic normalized rows are contract tests, not claimed CME payloads.
    rows = [
        *_distribution("current", "2026-09-18T15:30:00Z"),
        *_distribution("1d", "2026-09-17T00:00:00Z"),
        *_distribution("1w", "2026-09-11T00:00:00Z"),
        *_distribution("1m", "2026-08-18T00:00:00Z"),
    ]

    normalized, warnings, coverage = normalize_fedwatch_rows(rows)

    assert warnings == []
    assert len(normalized) == 8
    assert {row["as_of"] for row in normalized if row["comparison_window"] == "1d"} == {
        "2026-09-17T00:00:00+00:00"
    }
    assert coverage == {
        "complete": True,
        "meetings": {
            "2026-10-28": {
                "available_windows": ["current", "1d", "1w", "1m"],
                "missing_windows": [],
                "window_as_of": {
                    "current": "2026-09-18T15:30:00+00:00",
                    "1d": "2026-09-17T00:00:00+00:00",
                    "1w": "2026-09-11T00:00:00+00:00",
                    "1m": "2026-08-18T00:00:00+00:00",
                },
                "window_precision": {},
            }
        },
    }


def test_normalize_rows_normalizes_tolerated_sum_once_and_records_drift() -> None:
    rows = _distribution("current", "2026-09-18T15:30:00Z", (0.4, 0.599))

    normalized, warnings, coverage = normalize_fedwatch_rows(rows)

    assert math.fsum(row["probability"] for row in normalized) == pytest.approx(1.0)
    assert warnings[0].startswith("normalized probability sum once")
    assert warnings[1] == "meeting 2026-10-28 missing comparison windows: 1d,1w,1m"
    assert coverage["complete"] is False


@pytest.mark.parametrize(
    "mutation,match",
    [
        ({"probability": float("nan")}, "must be finite"),
        ({"probability": 1.1}, "outside"),
        ({"as_of": "2026-09-18T15:30:00"}, "UTC offset"),
        ({"comparison_window": "yesterday"}, "unsupported"),
    ],
)
def test_normalize_rows_rejects_malformed_values(mutation: dict, match: str) -> None:
    rows = _distribution("current", "2026-09-18T15:30:00Z")
    rows[0].update(mutation)

    with pytest.raises(FedWatchParseError, match=match):
        normalize_fedwatch_rows(rows)


def test_normalize_rows_rejects_overlapping_target_ranges() -> None:
    rows = _distribution("current", "2026-09-18T15:30:00Z")
    rows[1]["target_low"] = 3.9

    with pytest.raises(FedWatchParseError, match="overlapping"):
        normalize_fedwatch_rows(rows)


def test_normalize_rows_rejects_distribution_outside_sum_tolerance() -> None:
    rows = _distribution("current", "2026-09-18T15:30:00Z", (0.3, 0.6))

    with pytest.raises(FedWatchParseError, match="expected 0.99..1.01"):
        normalize_fedwatch_rows(rows)


def test_normalize_rows_requires_current_distribution() -> None:
    rows = _distribution("1d", "2026-09-17T00:00:00Z")

    with pytest.raises(FedWatchParseError, match="no current"):
        normalize_fedwatch_rows(rows)


def test_payload_parser_recognizes_observed_quikstrike_denial() -> None:
    # This is only the public error marker observed during discovery, not a
    # fabricated successful source fixture.
    body = b"<html><body>Access to QuikStrike has been denied - unexpected null referrer</body></html>"

    with pytest.raises(FedWatchParseError, match="official referrer"):
        parse_fedwatch_free_payload(body, content_type="text/html; charset=utf-8")


def test_payload_parser_rejects_unverified_json_schema() -> None:
    with pytest.raises(FedWatchParseError, match="no verified free JSON schema"):
        parse_fedwatch_free_payload(b'{"probabilities": []}', content_type="application/json")


# Minimal excerpts reproduce only public elements observed during source
# discovery.  They are unit-test transport inputs, not archived CME fixtures.
_OBSERVED_PARENT_IFRAME_EXCERPT = f'<iframe src="{IFRAME_URL}"></iframe>'
_OBSERVED_DENIAL_EXCERPT = (
    "<html><body>Access to QuikStrike has been denied - unexpected null referrer</body></html>"
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_collector_uses_parent_session_referer_and_archives_parse_failure(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url) == PARENT_URL:
            return httpx.Response(
                200,
                text=_OBSERVED_PARENT_IFRAME_EXCERPT,
                headers={"content-type": "text/html; charset=utf-8", "set-cookie": "public_session=one"},
                request=request,
            )
        assert request.headers["referer"] == PARENT_URL
        return httpx.Response(
            200,
            text=_OBSERVED_DENIAL_EXCERPT,
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    with _client(handler) as client:
        result = collect_fedwatch_free(
            storage_root=tmp_path,
            client=client,
            now=datetime(2026, 9, 28, 1, 2, 3, tzinfo=timezone.utc),
        )

    assert [str(request.url) for request in requests] == [PARENT_URL, IFRAME_URL]
    assert result["parse_status"] == "parse_failed"
    assert "official referrer" in result["reason"]
    assert result["as_of"] is None
    assert result["rows"] == []
    assert result["coverage"]["complete"] is False
    assert result["warnings"] == [result["reason"]]
    assert result["content_hash"]
    assert len(result["source_refs"]) == 2
    manifest_path = tmp_path / result["raw_artifact_ref"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["snapshot_id"] == result["snapshot_id"]
    assert manifest["parse_status"] == "parse_failed"
    assert [entry["role"] for entry in manifest["responses"]] == ["parent", "iframe"]
    assert "set-cookie" not in manifest["responses"][0]["headers"]
    for source_ref in result["source_refs"]:
        assert (tmp_path / source_ref["raw_artifact_ref"]).is_file()


def test_repeated_same_body_keeps_distinct_collection_events(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _OBSERVED_PARENT_IFRAME_EXCERPT if str(request.url) == PARENT_URL else _OBSERVED_DENIAL_EXCERPT
        return httpx.Response(200, text=body, headers={"content-type": "text/html"}, request=request)

    with _client(handler) as client:
        first = collect_fedwatch_free(storage_root=tmp_path, client=client)
        second = collect_fedwatch_free(storage_root=tmp_path, client=client)

    assert first["snapshot_id"] != second["snapshot_id"]
    assert first["content_hash"] == second["content_hash"]
    assert first["raw_artifact_ref"] != second["raw_artifact_ref"]
    assert (tmp_path / first["raw_artifact_ref"]).is_file()
    assert (tmp_path / second["raw_artifact_ref"]).is_file()


def test_collector_rejects_redirect_outside_allowlist_and_archives_response(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://127.0.0.1/private"}, request=request)

    with _client(handler) as client:
        result = collect_fedwatch_free(storage_root=tmp_path, client=client)

    assert result["parse_status"] == "missing"
    assert "redirect_host_not_allowlisted_127.0.0.1" in result["reason"]
    assert result["http_status"] == 302
    assert result["rows"] == []
    assert (tmp_path / result["raw_artifact_ref"]).is_file()
    assert len(result["source_refs"]) == 1


def test_collector_bounds_response_bytes_and_marks_truncation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fedwatch_free, "MAX_RESPONSE_BYTES", 32)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 33, headers={"content-type": "text/html"}, request=request)

    with _client(handler) as client:
        result = collect_fedwatch_free(storage_root=tmp_path, client=client)

    assert result["parse_status"] == "missing"
    assert "exceeded_32_bytes" in result["reason"]
    manifest = json.loads((tmp_path / result["raw_artifact_ref"]).read_text(encoding="utf-8"))
    assert manifest["responses"][0]["bytes"] == 32
    assert manifest["responses"][0]["truncated"] is True


def test_collector_persists_transport_failure_without_fabricating_rows(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with _client(handler) as client:
        result = collect_fedwatch_free(storage_root=tmp_path, client=client)

    assert result["parse_status"] == "missing"
    assert result["http_status"] is None
    assert result["content_hash"] is None
    assert result["source_refs"] == []
    assert result["rows"] == []
    assert result["coverage"] == {"complete": False, "meetings": {}, "reason": result["reason"]}
    manifest = json.loads((tmp_path / result["raw_artifact_ref"]).read_text(encoding="utf-8"))
    assert manifest["responses"] == []
    assert "ConnectError" in manifest["reason"]
