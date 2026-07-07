"""Tests for Jin10 web flash collector shell."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

import apps.collectors.jin10.web_flash as web_flash
from apps.collectors.jin10.web_flash import collect_jin10_web_flash_from_html, collect_jin10_web_flash_with_fetcher


# ---------------------------------------------------------------------------
# Inline HTML fixtures (same as parser tests)
# ---------------------------------------------------------------------------

IMPORTANT_FLASH_HTML = """
<div class="jin-flash-item flash is-important" data-id="123456">
  <div class="flash-important-icon"></div>
  <div class="flash-content">
    <a href="https://flash-api.jin10.com/get?id=123456" class="flash-item-title">
      美联储宣布加息25个基点
    </a>
    <div class="flash-item-summary">美联储将联邦基金利率目标区间上调至5.25%-5.50%</div>
    <div class="flash-item-time">2026-06-20 20:30</div>
    <div class="flash-item-labels">
      <span class="color-label__item">央行</span>
      <span class="color-label__item">利率</span>
    </div>
  </div>
</div>
"""

VIP_FLASH_HTML = """
<div class="jin-flash-item flash is-vip" data-id="789012">
  <div class="flash-vip-icon"></div>
  <div class="flash-content">
    <div class="flash-item-title">非农数据大幅不及预期</div>
    <div class="flash-item-summary">美国6月非农就业人口增加15万，预期22万</div>
    <div class="flash-item-time">2026-06-20 20:30</div>
    <div class="flash-item-labels">
      <span class="color-label__item">就业</span>
    </div>
  </div>
</div>
"""

TOP_LIST_HTML = """
<div class="flash-top-list">
  <a class="flash-top-list__item" href="https://www.jin10.com/flash_newest.html#id=345678" data-id="345678">
    <span class="flash-top-list__title">欧洲央行维持利率不变</span>
    <span class="flash-top-list__time">2026-06-20 19:45</span>
  </a>
</div>
"""

UNRELATED_HTML = """
<html>
<body>
  <div class="some-random-content">
    <p>Nothing related to jin10 flash</p>
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCollectFromHtmlWritesStorage:
    """Raw HTML and parsed JSON are written to expected storage paths."""

    def test_writes_raw_and_parsed_artifacts(self, tmp_path: Path) -> None:
        html = IMPORTANT_FLASH_HTML + VIP_FLASH_HTML + TOP_LIST_HTML

        result = collect_jin10_web_flash_from_html(
            html,
            storage_root=tmp_path,
            retrieved_date="2026-06-20",
            run_id="run-001",
            fetched_at="2026-06-20T20:31:00+00:00",
        )

        # Verify raw artifact written
        raw_path = tmp_path / "storage" / "raw" / "jin10" / "web_flash" / "2026-06-20" / "run-001" / "home.html"
        assert raw_path.exists(), f"raw artifact not found at {raw_path}"
        assert raw_path.read_text(encoding="utf-8") == html

        # Verify parsed artifact written
        parsed_path = tmp_path / "storage" / "parsed" / "jin10" / "web_flash" / "2026-06-20" / "run-001" / "web_flash_items.json"
        assert parsed_path.exists(), f"parsed artifact not found at {parsed_path}"
        parsed_data = json.loads(parsed_path.read_text(encoding="utf-8"))
        assert len(parsed_data) == 3

        # Verify return dict paths match actual files
        assert result["rawArtifactPath"] == str(raw_path)
        assert result["parsedArtifactPath"] == str(parsed_path)


class TestCollectParsedOutputIncludesItems:
    """Parsed output includes important/VIP/top-list items from inline HTML fixture."""

    def test_returns_all_item_types(self, tmp_path: Path) -> None:
        html = IMPORTANT_FLASH_HTML + VIP_FLASH_HTML + TOP_LIST_HTML

        result = collect_jin10_web_flash_from_html(
            html,
            storage_root=tmp_path,
            retrieved_date="2026-06-20",
            run_id="run-002",
            fetched_at="2026-06-20T20:31:00+00:00",
        )

        assert result["status"] == "ok"
        assert result["itemCount"] == 3
        assert result["retrievedDate"] == "2026-06-20"
        assert result["runId"] == "run-002"

        source_keys = [item["sourceKey"] for item in result["items"]]
        assert "jin10_web_important_flash" in source_keys
        assert "jin10_web_vip_flash" in source_keys

        titles = [item["title"] for item in result["items"]]
        assert any("美联储" in t for t in titles)
        assert any("非农" in t for t in titles)
        assert any("欧洲央行" in t for t in titles)


class TestSchemaChangedPropagation:
    """schema_changed parser result is propagated for unrelated HTML."""

    def test_propagates_schema_changed(self, tmp_path: Path) -> None:
        result = collect_jin10_web_flash_from_html(
            UNRELATED_HTML,
            storage_root=tmp_path,
            retrieved_date="2026-06-20",
            run_id="run-003",
            fetched_at="2026-06-20T20:31:00+00:00",
        )

        assert result["status"] == "schema_changed"
        assert result["itemCount"] == 0
        assert result["items"] == []
        assert result["qualityFlags"]["schema_changed"] is True

        # Raw HTML still written even on schema_changed
        raw_path = tmp_path / "storage" / "raw" / "jin10" / "web_flash" / "2026-06-20" / "run-003" / "home.html"
        assert raw_path.exists()

        # Parsed JSON also written (empty list)
        parsed_path = tmp_path / "storage" / "parsed" / "jin10" / "web_flash" / "2026-06-20" / "run-003" / "web_flash_items.json"
        assert parsed_path.exists()
        parsed_data = json.loads(parsed_path.read_text(encoding="utf-8"))
        assert parsed_data == []


class TestFetcherExceptionReturnsUnavailable:
    """Fetcher exception returns explicit unavailable with quality flag and reason."""

    def test_fetcher_failure_returns_unavailable(self, tmp_path: Path) -> None:
        def failing_fetcher() -> str:
            raise ConnectionError("network timeout")

        result = collect_jin10_web_flash_with_fetcher(
            failing_fetcher,
            storage_root=tmp_path,
            retrieved_date="2026-06-20",
            run_id="run-004",
            fetched_at="2026-06-20T20:31:00+00:00",
        )

        assert result["status"] == "unavailable"
        assert result["itemCount"] == 0
        assert result["qualityFlags"]["fetch_failed"] is True
        assert "network timeout" in result["qualityFlags"].get("reason", "")

        # No artifacts written on fetch failure
        raw_path = tmp_path / "storage" / "raw" / "jin10" / "web_flash" / "2026-06-20" / "run-004"
        assert not raw_path.exists()


class TestBrowserProfileWrapper:
    """Browser-profile wrapper delegates fetch, preserves parser behavior, and fails closed."""

    def test_wrapper_delegates_to_injected_html_fetcher_and_writes_artifacts(self, tmp_path: Path) -> None:
        calls: list[dict[str, object]] = []

        def injected_html_fetcher(**kwargs: object) -> str:
            calls.append(kwargs)
            return IMPORTANT_FLASH_HTML + VIP_FLASH_HTML + TOP_LIST_HTML

        result = web_flash.collect_jin10_web_flash_with_browser_profile(
            storage_root=tmp_path,
            retrieved_date="2026-06-20",
            run_id="run-005",
            fetched_at="2026-06-20T20:31:00+00:00",
            user_data_dir=tmp_path / "profile",
            html_fetcher=injected_html_fetcher,
        )

        assert len(calls) == 1
        assert result["status"] == "ok"
        assert result["itemCount"] == 3
        assert result["qualityFlags"] == {}
        assert result["rawArtifactPath"] == str(
            tmp_path / "storage" / "raw" / "jin10" / "web_flash" / "2026-06-20" / "run-005" / "home.html"
        )
        assert result["parsedArtifactPath"] == str(
            tmp_path / "storage" / "parsed" / "jin10" / "web_flash" / "2026-06-20" / "run-005" / "web_flash_items.json"
        )

    def test_wrapper_returns_unavailable_when_browser_profile_is_missing(self, tmp_path: Path) -> None:
        result = web_flash.collect_jin10_web_flash_with_browser_profile(
            storage_root=tmp_path,
            retrieved_date="2026-06-20",
            run_id="run-006",
            fetched_at="2026-06-20T20:31:00+00:00",
            user_data_dir=tmp_path / "missing-profile",
        )

        assert result["status"] == "unavailable"
        assert result["itemCount"] == 0
        assert result["rawArtifactPath"] is None
        assert result["parsedArtifactPath"] is None
        assert result["qualityFlags"]["fetch_failed"] is True
        assert "missing-profile" in result["qualityFlags"]["reason"]

    def test_fetch_helper_can_be_monkeypatched_without_playwright(self, tmp_path: Path, monkeypatch) -> None:
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        chromium = tmp_path / "chromium"
        chromium.write_text("stub", encoding="utf-8")
        seen: dict[str, object] = {}

        def fake_find_chromium_executable() -> Path:
            seen["finder_called"] = True
            return chromium

        def fake_render_homepage_html(*, user_data_dir: Path, chromium_path: Path, homepage_url: str) -> str:
            seen["user_data_dir"] = user_data_dir
            seen["chromium_path"] = chromium_path
            seen["homepage_url"] = homepage_url
            return "<html><body>rendered</body></html>"

        monkeypatch.setattr(web_flash, "_find_chromium_executable", fake_find_chromium_executable)
        monkeypatch.setattr(web_flash, "_render_jin10_web_flash_home_html_via_browser_profile", fake_render_homepage_html)

        html = web_flash.fetch_jin10_web_flash_home_html_via_browser_profile(
            user_data_dir=profile_dir,
            homepage_url="https://www.jin10.com/",
        )

        assert html == "<html><body>rendered</body></html>"
        assert seen["finder_called"] is True
        assert seen["user_data_dir"] == profile_dir
        assert seen["chromium_path"] == chromium
        assert seen["homepage_url"] == "https://www.jin10.com/"

    def test_wrapper_returns_unavailable_when_fetcher_raises(self, tmp_path: Path) -> None:
        def failing_html_fetcher(**_: object) -> str:
            raise RuntimeError("browser renderer exploded")

        result = web_flash.collect_jin10_web_flash_with_browser_profile(
            storage_root=tmp_path,
            retrieved_date="2026-06-20",
            run_id="run-007",
            fetched_at="2026-06-20T20:31:00+00:00",
            user_data_dir=tmp_path / "profile",
            html_fetcher=failing_html_fetcher,
        )

        assert result["status"] == "unavailable"
        assert result["itemCount"] == 0
        assert result["qualityFlags"]["fetch_failed"] is True
        assert "browser renderer exploded" in result["qualityFlags"]["reason"]
        assert not (tmp_path / "storage" / "raw" / "jin10" / "web_flash" / "2026-06-20" / "run-007").exists()

    def test_fetch_helper_rejects_non_jin10_homepage_before_browser_launch(self, tmp_path: Path, monkeypatch) -> None:
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        chromium = tmp_path / "chromium"
        chromium.write_text("stub", encoding="utf-8")

        def fail_if_render_called(**_: object) -> str:
            raise AssertionError("browser renderer should not be called for invalid homepage_url")

        monkeypatch.setattr(web_flash, "_render_jin10_web_flash_home_html_via_browser_profile", fail_if_render_called)

        with pytest.raises(RuntimeError, match="Unsupported Jin10 homepage URL"):
            web_flash.fetch_jin10_web_flash_home_html_via_browser_profile(
                user_data_dir=profile_dir,
                executable_path=chromium,
                homepage_url="file:///etc/passwd",
            )

    def test_wrapper_invalid_homepage_url_returns_unavailable_without_artifacts(self, tmp_path: Path, monkeypatch) -> None:
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        chromium = tmp_path / "chromium"
        chromium.write_text("stub", encoding="utf-8")

        def fail_if_render_called(**_: object) -> str:
            raise AssertionError("browser renderer should not be called for invalid homepage_url")

        monkeypatch.setattr(web_flash, "_render_jin10_web_flash_home_html_via_browser_profile", fail_if_render_called)

        result = web_flash.collect_jin10_web_flash_with_browser_profile(
            storage_root=tmp_path,
            retrieved_date="2026-06-20",
            run_id="run-008",
            fetched_at="2026-06-20T20:31:00+00:00",
            user_data_dir=profile_dir,
            executable_path=chromium,
            homepage_url="http://www.jin10.com/",
        )

        assert result["status"] == "unavailable"
        assert result["itemCount"] == 0
        assert result["rawArtifactPath"] is None
        assert result["parsedArtifactPath"] is None
        assert result["qualityFlags"]["fetch_failed"] is True
        assert "Unsupported Jin10 homepage URL" in result["qualityFlags"]["reason"]
        assert not (tmp_path / "storage" / "raw" / "jin10" / "web_flash" / "2026-06-20" / "run-008").exists()

    def test_fetch_helper_requires_profile_directory_before_browser_launch(self, tmp_path: Path, monkeypatch) -> None:
        profile_file = tmp_path / "profile"
        profile_file.write_text("not a directory", encoding="utf-8")
        chromium = tmp_path / "chromium"
        chromium.write_text("stub", encoding="utf-8")

        def fail_if_render_called(**_: object) -> str:
            raise AssertionError("browser renderer should not be called for invalid profile path")

        monkeypatch.setattr(web_flash, "_render_jin10_web_flash_home_html_via_browser_profile", fail_if_render_called)

        with pytest.raises(RuntimeError, match="Browser profile is not a directory"):
            web_flash.fetch_jin10_web_flash_home_html_via_browser_profile(
                user_data_dir=profile_file,
                executable_path=chromium,
            )

    def test_fetch_helper_requires_executable_file_before_browser_launch(self, tmp_path: Path, monkeypatch) -> None:
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        chromium_dir = tmp_path / "chromium-dir"
        chromium_dir.mkdir()

        def fail_if_render_called(**_: object) -> str:
            raise AssertionError("browser renderer should not be called for invalid executable path")

        monkeypatch.setattr(web_flash, "_render_jin10_web_flash_home_html_via_browser_profile", fail_if_render_called)

        with pytest.raises(RuntimeError, match="Chromium executable is not a file"):
            web_flash.fetch_jin10_web_flash_home_html_via_browser_profile(
                user_data_dir=profile_dir,
                executable_path=chromium_dir,
            )

    def test_fetch_helper_rejects_malformed_homepage_url_without_low_level_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        chromium = tmp_path / "chromium"
        chromium.write_text("stub", encoding="utf-8")

        def fail_if_render_called(**_: object) -> str:
            raise AssertionError("browser renderer should not be called for malformed homepage_url")

        monkeypatch.setattr(web_flash, "_render_jin10_web_flash_home_html_via_browser_profile", fail_if_render_called)

        with pytest.raises(RuntimeError, match="Unsupported Jin10 homepage URL"):
            web_flash.fetch_jin10_web_flash_home_html_via_browser_profile(
                user_data_dir=profile_dir,
                executable_path=chromium,
                homepage_url="https://www.jin10.com:bad/",
            )

    def test_fetch_helper_rejects_non_root_jin10_homepage_url_before_browser_launch(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()
        chromium = tmp_path / "chromium"
        chromium.write_text("stub", encoding="utf-8")

        def fail_if_render_called(**_: object) -> str:
            raise AssertionError("browser renderer should not be called for non-root homepage_url")

        monkeypatch.setattr(web_flash, "_render_jin10_web_flash_home_html_via_browser_profile", fail_if_render_called)

        for homepage_url in (
            "https://www.jin10.com/flash_newest.html",
            "https://www.jin10.com/?redirect=https://example.test",
            "https://www.jin10.com/#/vip",
        ):
            with pytest.raises(RuntimeError, match="Unsupported Jin10 homepage URL"):
                web_flash.fetch_jin10_web_flash_home_html_via_browser_profile(
                    user_data_dir=profile_dir,
                    executable_path=chromium,
                    homepage_url=homepage_url,
                )

    def test_renderer_launches_persistent_context_with_safe_parameters(self, tmp_path: Path, monkeypatch) -> None:
        profile_dir = tmp_path / "profile"
        chromium = tmp_path / "chromium"
        profile_dir.mkdir()
        chromium.write_text("stub", encoding="utf-8")
        captured: dict[str, object] = {}

        class FakePage:
            def goto(self, url: str, **kwargs: object) -> None:
                captured["goto_url"] = url
                captured["goto_kwargs"] = kwargs

            def content(self) -> str:
                return IMPORTANT_FLASH_HTML

            def wait_for_load_state(self, *_args: object, **_kwargs: object) -> None:
                return None

            def wait_for_selector(self, *_args: object, **_kwargs: object) -> None:
                return None

        class FakeContext:
            def new_page(self) -> FakePage:
                return FakePage()

            def close(self) -> None:
                captured["closed"] = True

        class FakeChromium:
            def launch_persistent_context(self, **kwargs: object) -> FakeContext:
                captured["launch_kwargs"] = kwargs
                return FakeContext()

        class FakePlaywright:
            chromium = FakeChromium()

        class FakeSyncPlaywright:
            def __enter__(self) -> FakePlaywright:
                return FakePlaywright()

            def __exit__(self, *_args: object) -> None:
                return None

        sync_api_module = types.ModuleType("playwright.sync_api")
        sync_api_module.sync_playwright = lambda: FakeSyncPlaywright()
        playwright_module = types.ModuleType("playwright")
        playwright_module.sync_api = sync_api_module
        monkeypatch.setitem(sys.modules, "playwright", playwright_module)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api_module)

        html = web_flash._render_jin10_web_flash_home_html_via_browser_profile(
            user_data_dir=profile_dir,
            chromium_path=chromium,
            homepage_url="https://www.jin10.com/",
        )

        launch_kwargs = captured["launch_kwargs"]
        assert html == IMPORTANT_FLASH_HTML
        assert isinstance(launch_kwargs, dict)
        assert launch_kwargs["user_data_dir"] != str(profile_dir)
        assert str(launch_kwargs["user_data_dir"]).endswith("/profile")
        assert launch_kwargs["executable_path"] == str(chromium)
        assert launch_kwargs["headless"] is True
        assert "--disable-dev-shm-usage" in launch_kwargs["args"]
        assert "XDG_RUNTIME_DIR" in launch_kwargs["env"]
        assert captured["goto_url"] == "https://www.jin10.com/"
        assert captured["goto_kwargs"]["wait_until"] == "domcontentloaded"
        assert captured["closed"] is True

    def test_profile_copy_omits_singleton_locks(self, tmp_path: Path) -> None:
        source = tmp_path / "source-profile"
        target = tmp_path / "target-profile"
        source.mkdir()
        (source / "Cookies").write_text("cookie-data", encoding="utf-8")
        (source / "SingletonLock").write_text("locked", encoding="utf-8")
        (source / "SingletonSocket").write_text("socket", encoding="utf-8")

        web_flash._copy_browser_profile_for_readonly_launch(source, target)

        assert (target / "Cookies").read_text(encoding="utf-8") == "cookie-data"
        assert not (target / "SingletonLock").exists()
        assert not (target / "SingletonSocket").exists()
