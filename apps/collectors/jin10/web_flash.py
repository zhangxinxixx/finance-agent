"""Collector shell for Jin10 homepage web flash (fixture-first, no live browser)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from apps.parsers.jin10.web_flash import parse_jin10_web_flash_html

_ALLOWED_JIN10_HOMEPAGE_HOSTS = frozenset({"www.jin10.com"})


def collect_jin10_web_flash_from_html(
    html: str,
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    fetched_at: str,
) -> dict[str, Any]:
    """Parse pre-fetched HTML and persist raw + parsed artifacts.

    Parameters
    ----------
    html:
        Full Jin10 homepage HTML string.
    storage_root:
        Base directory under which ``storage/raw/…`` and ``storage/parsed/…``
        are created.
    retrieved_date:
        ISO date string (``YYYY-MM-DD``) used in the storage path.
    run_id:
        Unique run identifier used in the storage path.
    fetched_at:
        ISO-8601 timestamp forwarded to the parser.

    Returns
    -------
    dict
        Collector result envelope with ``status``, artifact paths, items, and
        quality flags.
    """
    raw_dir = storage_root / "storage" / "raw" / "jin10" / "web_flash" / retrieved_date / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "home.html"
    raw_path.write_text(html, encoding="utf-8")

    parsed_result = parse_jin10_web_flash_html(
        html,
        fetched_at=fetched_at,
        raw_artifact_path=str(raw_path),
    )

    parsed_dir = storage_root / "storage" / "parsed" / "jin10" / "web_flash" / retrieved_date / run_id
    parsed_dir.mkdir(parents=True, exist_ok=True)
    parsed_json_path = parsed_dir / "web_flash_items.json"

    parsed_json_path.write_text(
        json.dumps(parsed_result["items"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    items = parsed_result["items"]
    return {
        "status": parsed_result["status"],
        "retrievedDate": retrieved_date,
        "runId": run_id,
        "rawArtifactPath": str(raw_path),
        "parsedArtifactPath": str(parsed_json_path),
        "itemCount": len(items),
        "items": items,
        "qualityFlags": parsed_result.get("qualityFlags", {}),
        "sourceRefs": [
            {
                "fetchedAt": fetched_at,
                "rawArtifactPath": str(raw_path),
                "parsedArtifactPath": str(parsed_json_path),
            }
        ],
    }


def collect_jin10_web_flash_with_fetcher(
    fetch_home_html: Callable[[], str],
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    fetched_at: str,
) -> dict[str, Any]:
    """Fetch HTML via *fetch_home_html*, then delegate to :func:`collect_jin10_web_flash_from_html`.

    Returns ``status: "unavailable"`` with a quality flag when the fetcher
    raises an exception.
    """
    try:
        html = fetch_home_html()
    except Exception as exc:
        return {
            "status": "unavailable",
            "retrievedDate": retrieved_date,
            "runId": run_id,
            "rawArtifactPath": None,
            "parsedArtifactPath": None,
            "itemCount": 0,
            "items": [],
            "qualityFlags": {
                "fetch_failed": True,
                "reason": str(exc),
            },
            "sourceRefs": [],
        }

    return collect_jin10_web_flash_from_html(
        html,
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        run_id=run_id,
        fetched_at=fetched_at,
    )


def fetch_jin10_web_flash_home_html_via_browser_profile(
    *,
    user_data_dir: Path | str,
    executable_path: Path | str | None = None,
    homepage_url: str = "https://www.jin10.com/",
) -> str:
    validated_homepage_url = _validate_jin10_homepage_url(homepage_url)

    profile_dir = Path(user_data_dir).expanduser()
    if not profile_dir.exists():
        raise RuntimeError(f"Browser profile not found: {profile_dir}")
    if not profile_dir.is_dir():
        raise RuntimeError(f"Browser profile is not a directory: {profile_dir}")

    chromium_path = _find_chromium_executable() if executable_path is None else Path(executable_path).expanduser()
    if chromium_path is None:
        raise RuntimeError("No Chromium executable found for Jin10 web flash browser-profile fetch.")
    if not chromium_path.exists():
        raise RuntimeError(f"Chromium executable not found: {chromium_path}")
    if not chromium_path.is_file():
        raise RuntimeError(f"Chromium executable is not a file: {chromium_path}")

    return _render_jin10_web_flash_home_html_via_browser_profile(
        user_data_dir=profile_dir,
        chromium_path=chromium_path,
        homepage_url=validated_homepage_url,
    )


def collect_jin10_web_flash_with_browser_profile(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    fetched_at: str,
    user_data_dir: Path | str,
    executable_path: Path | str | None = None,
    homepage_url: str = "https://www.jin10.com/",
    html_fetcher: Callable[..., str] | None = None,
) -> dict[str, Any]:
    fetcher = html_fetcher or fetch_jin10_web_flash_home_html_via_browser_profile

    def _fetch_home_html() -> str:
        return fetcher(
            user_data_dir=user_data_dir,
            executable_path=executable_path,
            homepage_url=homepage_url,
        )

    return collect_jin10_web_flash_with_fetcher(
        _fetch_home_html,
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        run_id=run_id,
        fetched_at=fetched_at,
    )


def _render_jin10_web_flash_home_html_via_browser_profile(
    *,
    user_data_dir: Path,
    chromium_path: Path,
    homepage_url: str,
) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - import availability is environment specific
        raise RuntimeError("Playwright is required for Jin10 web flash browser-profile fetch.") from exc

    with tempfile.TemporaryDirectory(prefix="jin10-web-flash-playwright-runtime-") as runtime_dir:
        env = {**os.environ, "XDG_RUNTIME_DIR": runtime_dir}
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                executable_path=str(chromium_path),
                headless=True,
                args=["--disable-dev-shm-usage"],
                env=env,
            )
            try:
                page = context.new_page()
                page.goto(homepage_url, wait_until="domcontentloaded", timeout=60000)
                _wait_for_jin10_web_flash_homepage(page)
                return page.content()
            finally:
                context.close()


def _wait_for_jin10_web_flash_homepage(page: Any) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    for selector in (".jin-flash-item.flash", ".flash-top-list__item"):
        try:
            page.wait_for_selector(selector, timeout=4000)
            return
        except Exception:
            continue

    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass


def _validate_jin10_homepage_url(homepage_url: str) -> str:
    parsed = urlparse(homepage_url)
    hostname = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = -1
    if (
        parsed.scheme != "https"
        or hostname not in _ALLOWED_JIN10_HOMEPAGE_HOSTS
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.path not in ("", "/")
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise RuntimeError("Unsupported Jin10 homepage URL; expected https://www.jin10.com/.")
    return homepage_url


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
