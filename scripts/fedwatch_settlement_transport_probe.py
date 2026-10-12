"""Small, read-only cross-platform CME transport experiment; no retries or DB writes.

Run with project uv Python, or the same pinned curl_cffi in an isolated Windows
environment. Each request archives a bounded response and sanitized diagnostics.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import platform
import re
import statistics
import time
from uuid import uuid4

import curl_cffi
from curl_cffi import CurlInfo, CurlOpt, CurlHttpVersion, requests

URL = "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/305/FUT"
PROFILE = "chrome146"  # resolves to the successful M1 'chrome' profile in curl_cffi 0.15
MAX_BYTES = 4 * 1024 * 1024
SAFE_HEADERS = {"date", "content-type", "content-length", "server", "via", "x-cache", "cf-ray", "etag"}
INFOS = {
    "dns_seconds": CurlInfo.NAMELOOKUP_TIME,
    "connect_seconds": CurlInfo.CONNECT_TIME,
    "tls_seconds": CurlInfo.APPCONNECT_TIME,
    "ttfb_seconds": CurlInfo.STARTTRANSFER_TIME,
    "new_connections": CurlInfo.NUM_CONNECTS,
    "os_errno": CurlInfo.OS_ERRNO,
    "proxy_used": CurlInfo.USED_PROXY,
}


def sanitize_error(value):
    text = re.sub(r"(?i)\b(?:https?|socks\w*)://[^\s]+", "[URL_REDACTED]", str(value))
    text = re.sub(r"(?i)(authorization|proxy-authorization|cookie|set-cookie)\s*:[^\r\n]*", r"\1:[REDACTED]", text)
    text = re.sub(r"(?i)(token|password|secret|api[_-]?key)=([^\s&]+)", r"\1=[REDACTED]", text)
    return text[:800]


def classify(code, message, timings):
    mapping = {
        5: "proxy_failed",
        6: "dns_failed",
        7: "connect_failed",
        16: "http2_failed",
        35: "tls_failed",
        51: "tls_failed",
        52: "remote_closed",
        60: "tls_failed",
        92: "http2_failed",
        97: "proxy_failed",
    }
    if code == 28:
        if timings.get("tls_seconds", 0) > 0:
            return "read_timeout"
        if timings.get("connect_seconds", 0) > 0:
            return "tls_timeout"
        return "timeout_stage_unknown"
    if code == 56:
        return "connect_reset" if "reset" in message.lower() else "receive_failed"
    return mapping.get(code, "unknown_transport")


def environment():
    if platform.system() == "Windows":
        return "windows"
    if Path("/.dockerenv").exists():
        return "container"
    return "wsl" if "microsoft" in platform.release().lower() else "linux"


def session_for(case, tls):
    def debug(kind, data):
        # Never save verbose headers, cookies or body bytes. Extract only TLS version.
        if kind == 0:
            match = re.search(rb"SSL connection using (TLSv[0-9.]+)", data)
            if match:
                tls["version"] = match.group(1).decode("ascii")

    options = {CurlOpt.VERBOSE: 1, CurlOpt.DEBUGFUNCTION: debug}
    if case == "ipv4":
        options[CurlOpt.IPRESOLVE] = 1
    if case == "direct":
        options[CurlOpt.PROXY] = ""  # Explicit libcurl override; trust_env=False alone is not proof.
    return requests.Session(
        impersonate=PROFILE,
        trust_env=False,
        retry=0,
        curl_options=options,
        curl_infos=list(INFOS.values()),
        http_version=CurlHttpVersion.V1_1 if case == "http1" else None,
    )


def response_metrics(response):
    if response is None:
        return {}
    address = response.primary_ip or None
    family = None
    if address:
        try:
            family = "IPv" + str(ipaddress.ip_address(address).version)
        except ValueError:
            pass
    infos = getattr(response, "infos", {})
    return {
        "peer_ip": address,
        "resolved_ip": address if infos.get(CurlInfo.USED_PROXY) == 0 else None,
        "ip_family": family,
        "ip_family_scope": "TCP peer; may be proxy",
        "http_version": {0: None, 1: "HTTP/1.0", 2: "HTTP/1.1", 3: "HTTP/2", 30: "HTTP/3"}.get(response.http_version),
        "response_status": response.status_code or None,
        "response_headers": {k.lower(): v for k, v in response.headers.items() if k.lower() in SAFE_HEADERS},
        **{name: infos.get(key) for name, key in INFOS.items()},
    }


def request_once(client, *, day, case, attempt, run_id, output, tls, interval_seconds):
    identity = str(uuid4())
    tls.clear()
    start = time.monotonic()
    body = bytearray()
    record = {
        "schema_version": "cme_transport_probe.v1",
        "run_id": run_id,
        "request_id": identity,
        "attempt": attempt,
        "case": case,
        "environment": environment(),
        "requested_trade_date": day.isoformat(),
        "started_at": datetime.now(UTC).isoformat(),
        "requested_interval_seconds": interval_seconds,
        "session_mode": "reused" if case == "reuse" else "new",
        "impersonate_profile": PROFILE,
        "user_agent_profile": PROFILE,
        "curl_cffi_version": curl_cffi.__version__,
        "python_version": platform.python_version(),
        "retry_limit": 0,
        "proxy_config": "explicit_direct" if case == "direct" else "trust_env_false",
        "proxy_used": None,
        "resolved_ip": None,
        "ip_family": None,
        "http_version": None,
        "tls_version": None,
        "response_status": None,
        "response_headers": {},
        "exception_class": None,
        "curl_error_code": None,
        "error_message": None,
        "failure_type": None,
        "data_status": "unavailable",
        "truncated": False,
        "timing_scope": "curl_response_header_observation; elapsed_ms is full wall time",
    }
    try:
        with client.stream(
            "GET", URL + "?tradeDate=" + day.strftime("%m/%d/%Y"), timeout=20, allow_redirects=False
        ) as response:
            record.update(response_metrics(response))
            for chunk in response.iter_content():
                room = MAX_BYTES - len(body)
                body.extend(chunk[:room])
                if len(chunk) > room:
                    record["truncated"] = True
                    break
        if record["response_status"] == 200 and not record["truncated"]:
            try:
                payload = json.loads(body)
                assert payload["tradeDate"] == day.strftime("%m/%d/%Y")
                assert payload["dsHeader"] == "30 Day Federal Funds Future"
                rows = payload["settlements"]
                assert isinstance(rows, list) and type(payload["empty"]) is bool
                if payload["empty"]:
                    assert not rows
                    record["data_status"] = "upstream_empty"
                else:
                    valid = [r for r in rows if r["month"] != "Total" and math.isfinite(float(r["settle"]))]
                    assert valid
                    record.update(data_status="available", contract_count=len(valid), report_type=payload["reportType"])
            except (ValueError, KeyError, TypeError, AssertionError, OverflowError):
                record["data_status"] = "parse_failed"
        elif record["truncated"]:
            record["data_status"] = "response_too_large"
        else:
            record["failure_type"] = "http_status"
    except requests.RequestsError as exc:
        record.update(response_metrics(getattr(exc, "response", None)))
        code = int(exc.code) if getattr(exc, "code", None) is not None else None
        message = sanitize_error(exc)
        record.update(
            exception_class=type(exc).__name__,
            curl_error_code=code,
            error_message=message,
            failure_type=classify(code, message, {k: v for k, v in record.items() if v is not None}),
        )
    record.update(
        tls_version=tls.get("version"),
        elapsed_ms=round(1000 * (time.monotonic() - start)),
        bytes_received=len(body),
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    record["unknown_fields"] = [
        k for k in ("tls_version", "http_version", "resolved_ip", "proxy_used") if record[k] is None
    ]
    # UUID directory and exclusive creation preserve all unsuccessful attempts too.
    folder = output / identity
    folder.mkdir()
    with (folder / "response.body").open("xb") as handle:
        handle.write(body)
    with (folder / "diagnostic.json").open("x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, allow_nan=False)
    return record


def summarize(records):
    result = {}
    for case in dict.fromkeys(r["case"] for r in records):
        rows = [r for r in records if r["case"] == case]
        result[case] = {
            "requests": len(rows),
            "available": sum(r["data_status"] == "available" for r in rows),
            "failure_types": [r["failure_type"] for r in rows if r["failure_type"]],
            "latency_median_ms": statistics.median(r["elapsed_ms"] for r in rows),
        }
    return {
        "cases": result,
        "request_count": len(records),
        "production_slo_passed": False,
        "interpretation": "small diagnostic experiment; not an availability estimate",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cases",
        nargs="+",
        choices=["new", "reuse", "ipv4", "http1", "direct"],
        default=["new", "reuse", "ipv4", "http1"],
    )
    parser.add_argument("--repeats", type=int, choices=[1, 2, 3], default=2)
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument(
        "--cooldown-check", type=int, default=0, help="Optional last fresh request after 120..600 seconds"
    )
    args = parser.parse_args(argv)
    if not args.output.is_absolute() or not 30 <= args.interval <= 600:
        parser.error("absolute output path and interval 30..600 required")
    if args.cooldown_check and not 120 <= args.cooldown_check <= 600:
        parser.error("cooldown must be 0 or 120..600")
    if len(set(args.cases)) != len(args.cases) or len(args.cases) * args.repeats + bool(args.cooldown_check) > 12:
        parser.error("unique cases and at most 12 total requests required")
    if curl_cffi.__version__ != "0.15.0":
        parser.error("controlled experiment requires curl_cffi 0.15.0 on each environment")
    run_id = str(uuid4())
    output = args.output / run_id
    output.mkdir(parents=True, exist_ok=False)
    records = []
    last_start = None

    def request(client, case, attempt, tls, gap):
        nonlocal last_start
        if last_start is not None:
            time.sleep(max(0, gap - (time.monotonic() - last_start)))
        last_start = time.monotonic()
        row = request_once(
            client,
            day=args.trade_date,
            case=case,
            attempt=attempt,
            run_id=run_id,
            output=output,
            tls=tls,
            interval_seconds=gap,
        )
        records.append(row)
        print(
            json.dumps(
                {
                    k: row.get(k)
                    for k in [
                        "run_id",
                        "request_id",
                        "case",
                        "attempt",
                        "environment",
                        "response_status",
                        "data_status",
                        "curl_error_code",
                        "failure_type",
                        "elapsed_ms",
                        "http_version",
                        "ip_family",
                    ]
                }
            ),
            flush=True,
        )

    for case in args.cases:
        tls = {}
        if case == "reuse":
            with session_for(case, tls) as client:
                for attempt in range(1, args.repeats + 1):
                    request(client, case, attempt, tls, args.interval)
        else:
            for attempt in range(1, args.repeats + 1):
                with session_for(case, tls) as client:
                    request(client, case, attempt, tls, args.interval)
    if args.cooldown_check:
        tls = {}
        with session_for("new", tls) as client:
            request(client, "cooldown_new", 1, tls, args.cooldown_check)
    with (output / "summary.json").open("x") as handle:
        json.dump(summarize(records), handle, indent=2)
    print(json.dumps({"artifact_directory": str(output), **summarize(records)}), flush=True)


if __name__ == "__main__":
    main()
