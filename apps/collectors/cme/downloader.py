from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import fitz

DAILY_BULLETIN_INDEX_URL = "https://www.cmegroup.com/daily-bulletin/index.html"
DAILY_BULLETIN_BASE_URL = "https://www.cmegroup.com/daily_bulletin/current"
DEFAULT_SECTION_FILE = "Section64_Metals_Option_Products.pdf"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 2.0


@dataclass(frozen=True)
class CmeRawFile:
    source: str
    section: str
    source_url: str
    raw_path: str
    sha256: str
    report_date: str
    bytes: int
    retrieved_at: str
    date_source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def build_daily_bulletin_url(section_file: str = DEFAULT_SECTION_FILE) -> str:
    quoted_section = quote(section_file.lstrip("/"), safe="/")
    return f"{DAILY_BULLETIN_BASE_URL}/{quoted_section}"


def archive_cme_pdf(
    raw: bytes,
    *,
    report_date: str,
    section_file: str,
    source_url: str,
    storage_root: Path,
) -> CmeRawFile:
    _validate_pdf_header(raw)

    extracted_report_date = _extract_report_date_from_pdf(raw)
    normalized_report_date, date_source = _resolve_report_date(
        extracted_report_date=extracted_report_date,
        fallback_report_date=report_date,
    )

    pdf_sha256 = hashlib.sha256(raw).hexdigest()
    section_stem = Path(section_file).stem
    raw_path = Path("raw") / "cme" / "daily_bulletin" / normalized_report_date / (
        f"{section_stem}_{normalized_report_date}_{pdf_sha256[:12]}.pdf"
    )
    target = storage_root / raw_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)

    return CmeRawFile(
        source="cme",
        section=section_file,
        source_url=source_url,
        raw_path=raw_path.as_posix(),
        sha256=pdf_sha256,
        report_date=normalized_report_date,
        bytes=len(raw),
        retrieved_at=datetime.now(timezone.utc).isoformat(),
        date_source=date_source,
    )


def download_cme_pdf(
    *,
    section_file: str = DEFAULT_SECTION_FILE,
    report_date: str | None = None,
    storage_root: Path = Path("."),
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> CmeRawFile:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds must be non-negative")

    source_url = build_daily_bulletin_url(section_file)
    raw: bytes | None = None
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = _download_cme_pdf_bytes(source_url=source_url)
            break
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                time.sleep(retry_delay_seconds)
    if raw is None:
        raise RuntimeError(f"CME PDF download failed after {max_attempts} attempts: {last_error}") from last_error

    fallback_report_date = "" if report_date in (None, "", "latest") else report_date
    return archive_cme_pdf(
        raw,
        report_date=fallback_report_date,
        section_file=section_file,
        source_url=source_url,
        storage_root=storage_root,
    )


def _download_cme_pdf_bytes(*, source_url: str) -> bytes:
    chromium = _find_chromium_executable()
    if chromium is None:
        raise RuntimeError(
            "No Chromium executable found. Checked CHROMIUM_EXECUTABLE_PATH, /snap/bin/chromium, /usr/bin/chromium, "
            "and PATH."
        )

    proxy_server = _detect_proxy_server()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - exercised only when Playwright is missing
        raise RuntimeError("Playwright is required for the CME download path.") from exc

    with tempfile.TemporaryDirectory(prefix="cme-playwright-runtime-") as runtime_dir:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(chromium),
                proxy={"server": proxy_server} if proxy_server else None,
                args=["--disable-dev-shm-usage"],
                env={**os.environ, "XDG_RUNTIME_DIR": runtime_dir},
            )
            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    )
                )
                page = context.new_page()
                # CME's Daily Bulletin index can fail under some WSL/proxy paths with
                # ERR_HTTP2_PROTOCOL_ERROR. A browser-origin XHR from a neutral data URL
                # still uses Chromium's TLS/browser fingerprint and avoids that brittle
                # warm-up navigation.
                page.goto("data:text/html,<html></html>")
                payload = page.evaluate(
                    """
                    async (targetUrl) => {
                        return await new Promise((resolve, reject) => {
                            const xhr = new XMLHttpRequest();
                            xhr.open("GET", targetUrl, true);
                            xhr.responseType = "arraybuffer";
                            xhr.onload = () => {
                                if (xhr.status !== 200) {
                                    reject(new Error(`HTTP ${xhr.status} ${xhr.statusText}`));
                                    return;
                                }
                                resolve(Array.from(new Uint8Array(xhr.response)));
                            };
                            xhr.onerror = () => reject(new Error("CME PDF XHR network error"));
                            xhr.send();
                        });
                    }
                    """,
                    source_url,
                )
                return bytes(payload)
            finally:
                browser.close()


def _validate_pdf_header(raw: bytes) -> None:
    if not raw.startswith(b"%PDF"):
        raise ValueError("CME download did not start with a PDF header.")


def _extract_report_date_from_pdf(raw: bytes) -> str | None:
    try:
        with fitz.open(stream=raw, filetype="pdf") as document:
            if document.page_count == 0:
                return None
            text = document.load_page(0).get_text("text")
    except Exception:
        return None

    if not text:
        return None

    candidates = (
        r"(?P<date>[A-Z][a-z]{2},\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})",
        r"(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    )
    for pattern in candidates:
        match = re.search(pattern, text)
        if match:
            value = match.group("date")
            for fmt in ("%a, %b %d, %Y", "%A, %B %d, %Y", "%b %d, %Y", "%B %d, %Y"):
                try:
                    return datetime.strptime(value, fmt).date().isoformat()
                except ValueError:
                    continue
    return None


def _resolve_report_date(*, extracted_report_date: str | None, fallback_report_date: str) -> tuple[str, str]:
    if extracted_report_date:
        return extracted_report_date, "pdf"

    if fallback_report_date:
        return _normalize_report_date(fallback_report_date), "argument"

    raise ValueError("Could not determine CME report date from the PDF or the provided report_date argument.")


def _normalize_report_date(report_date: str) -> str:
    try:
        return datetime.strptime(report_date, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid report_date value: {report_date!r}") from exc


def _find_chromium_executable() -> Path | None:
    env_path = os.getenv("CHROMIUM_EXECUTABLE_PATH")
    candidates = [
        Path(env_path) if env_path else None,
        Path("/snap/chromium/current/usr/lib/chromium-browser/chrome"),
        Path("/snap/bin/chromium"),
        Path("/usr/bin/chromium"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate

    for binary in ("chromium", "chromium-browser"):
        resolved = shutil.which(binary)
        if resolved:
            return Path(resolved)
    return None


def _detect_proxy_server() -> str | None:
    for env_var in ("CME_PROXY_URL", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.getenv(env_var)
        if value:
            return value

    gateway = _detect_wsl_gateway()
    if gateway:
        return f"http://{gateway}:7890"
    return None


def _detect_wsl_gateway() -> str | None:
    version = Path("/proc/version")
    if not version.is_file():
        return None
    try:
        if "microsoft" not in version.read_text(encoding="utf-8", errors="ignore").lower():
            return None
    except Exception:
        return None

    try:
        completed = subprocess.run(
            ["ip", "route", "show", "default"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None

    match = re.search(r"default via (\S+)", completed.stdout)
    return match.group(1) if match else None
