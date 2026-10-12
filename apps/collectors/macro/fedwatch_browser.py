"""Native Windows Chromium transport for the public QuikStrike widget.

Uses the existing Node/Chrome installation from WSL, with an isolated temporary
profile and explicit direct networking. It returns the same normalized snapshot
contract as the HTTP collector; it never reconstructs probabilities.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import uuid4

from apps.parsers.macro.fedwatch_free import FedWatchParseError, parse_fedwatch_free_payload


class BrowserCaptureError(ValueError):
    """Only fixed diagnostic codes, never raw subprocess output."""


def browser_available():
    return (os.environ.get("FEDWATCH_BROWSER_TRANSPORT", "auto") != "off"
            and Path("/mnt/c/Program Files/nodejs/node.exe").is_file()
            and Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe").is_file())


def _native_capture():
    """One bounded native process; stdout does not carry raw/session contents."""
    powershell = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    native_temp = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", "[System.IO.Path]::GetTempPath()"],
        capture_output=True, text=True, timeout=10, check=True,
    ).stdout.strip()
    temp_root = Path(subprocess.run(["wslpath", "-u", native_temp], capture_output=True,
                                    text=True, check=True, timeout=5).stdout.strip())
    if not temp_root.is_dir() or not temp_root.is_relative_to("/mnt/c"):
        raise ValueError("native_temp_unavailable")
    with tempfile.TemporaryDirectory(prefix="finance-fedwatch-", dir=temp_root,
                                     ignore_cleanup_errors=True) as temporary:
        folder = Path(temporary)
        source = Path(__file__).resolve().parents[3] / "scripts/fedwatch_browser_capture.cjs"
        shutil.copyfile(source, folder / "capture.cjs")
        native_folder = subprocess.run(["wslpath", "-w", str(folder)], capture_output=True,
                                       text=True, check=True, timeout=5).stdout.strip()
        process = subprocess.run([
            "/mnt/c/Program Files/nodejs/node.exe", native_folder + "\\capture.cjs",
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", native_folder + "\\result.json",
        ], capture_output=True, timeout=195, check=False)
        if process.returncode:
            code = process.stderr.decode("utf-8", errors="replace").strip()
            if code not in {"official_widget_unavailable", "browser_start_failed", "cdp_connect_failed",
                            "cdp_timeout", "meeting_limit_exceeded", "page_evaluation_failed"}:
                code = "native_process_failed"
            raise BrowserCaptureError(code)
        result_path = folder / "result.json"
        if result_path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("capture_limit_exceeded")
        return json.loads(result_path.read_text(encoding="utf-8"))


def collect_fedwatch_browser(*, storage_root, now=None, capture=None):
    return collect_fedwatch_pages(storage_root=storage_root, now=now,
                                 capture=capture or _native_capture,
                                 transport="native_chromium_direct", capture_kind="rendered_dom")


def collect_fedwatch_pages(*, storage_root, now, capture, transport, capture_kind):
    """Shared official-table normalization; transport never changes provenance."""
    if (transport, capture_kind) not in {
        ("native_chromium_direct", "rendered_dom"),
        ("curl_cffi_webforms", "http_response"),
    }:
        raise ValueError("unsupported_fedwatch_transport")
    # Local import avoids a circular dependency with the transport selector.
    from apps.collectors.macro.fedwatch_free import (
        _PublicResponse, _archive_collection, _ensure_utc, _snapshot,
    )
    clock = _ensure_utc(now or datetime.now(timezone.utc))
    identity = str(uuid4())
    source_url = "https://cmegroup-tools.quikstrike.net/User/QuikStrikeView.aspx?viewitemid=IntegratedFedWatchTool"
    responses, parsed, reason, pages = [], None, None, []
    status = "missing"
    try:
        result = capture()
        pages = result.get("pages", [])
        tabs = result.get("meeting_tabs")
        for page in result.get("raw_pages", pages):
            body = page.get("body", page.get("html", "").encode("utf-8"))
            if len(body) > 4 * 1024 * 1024:
                raise ValueError("capture_page_too_large")
            responses.append(_PublicResponse(
                role="iframe", requested_url=page.get("source_url", source_url),
                response_url=page.get("source_url", source_url),
                http_status=page.get("http_status") if capture_kind == "http_response" else None,
                content_type="text/html", headers={}, body=body, truncated=False,
            ))
        if not isinstance(tabs, int) or not 1 <= tabs <= 16 or not 1 <= len(pages) <= tabs:
            raise BrowserCaptureError(result.get("reason") or "invalid_meeting_coverage")
        rows, meetings, times = [], {}, set()
        for page in pages:
            one = parse_fedwatch_free_payload(page["html"].encode("utf-8"), content_type="text/html")
            overlap = meetings.keys() & one["coverage"]["meetings"].keys()
            if overlap:
                raise ValueError("duplicate_meeting_postback")
            rows.extend(one["rows"])
            meetings.update(one["coverage"]["meetings"])
            times.add(one["as_of"])
        # Live CME tables have distinct timestamps a few seconds apart. Keep
        # each row's actual timestamp; the envelope is only a knowledge cutoff.
        stamps = sorted(datetime.fromisoformat(t) for t in times)
        span = (stamps[-1] - stamps[0]).total_seconds()
        if span > 60:
            raise ValueError("meeting_source_times_inconsistent")
        all_tabs = len(pages) == tabs and not result.get("errors")
        complete = all_tabs and all(not m["missing_windows"] for m in meetings.values())
        parsed = {"as_of": stamps[-1].isoformat(), "rows": rows, "futures": [],
                  "parser_version": one["parser_version"],
                  "coverage": {"complete": complete, "meetings": meetings,
                               "meeting_scope": "official_meeting_tabs", "all_future_meetings": all_tabs,
                               "source_time_window": {"start": stamps[0].isoformat(),
                                                      "end": stamps[-1].isoformat(), "span_seconds": span},
                               "available_tab_count": tabs, "captured_tab_count": len(pages)},
                  "warnings": ["Historical comparisons expose dates only; missing cells remain missing."]}
        if not all_tabs:
            parsed["warnings"].append("Some meeting tabs were unavailable; only captured meetings are included.")
        status = "ok"
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        status = "parse_failed" if pages else "missing"
        prefix = "official_http_" if capture_kind == "http_response" else "official_browser_"
        reason = prefix + (str(exc) if isinstance(exc, (FedWatchParseError, BrowserCaptureError)) else type(exc).__name__)
    collected_at = (clock if now else datetime.now(timezone.utc)).isoformat()
    raw_ref, refs = _archive_collection(storage_root=Path(storage_root), snapshot_id=identity,
                                      collected_at=collected_at, responses=responses,
                                      parse_status=status, reason=reason,
                                      collector_version="fedwatch-pages-v2", capture_kind=capture_kind)
    snapshot = _snapshot(snapshot_id=identity, collected_at=collected_at, source_url=source_url,
                         http_status=(pages[0].get("http_status") if capture_kind == "http_response" and pages
                                      else responses[-1].http_status if responses else None),
                         content_hash=responses[0].content_hash if responses else None,
                         raw_artifact_ref=raw_ref, parse_status=status, reason=reason,
                         source_refs=refs, parse_result=parsed)
    snapshot.update(collector_version="fedwatch-pages-v2", transport=transport,
                    official_display_probability=status == "ok", capture_kind=capture_kind)
    return snapshot
