from __future__ import annotations

import json
import os
import time

from apps.api import main


def test_jin10_flash_api_refreshes_stale_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "flash_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-13T01:48:21+00:00",
                "items": [{"id": "old", "time": "2026-06-13T09:33:22+08:00", "content": "old headline"}],
            }
        ),
        encoding="utf-8",
    )
    old_mtime = time.time() - 3600
    os.utime(cache_path, (old_mtime, old_mtime))

    monkeypatch.setattr(main, "_JIN10_FLASH_CACHE_PATH", cache_path)
    monkeypatch.setattr(main, "_JIN10_FLASH_CACHE_MAX_AGE_SECONDS", 60)

    def refresh() -> None:
        cache_path.write_text(
            json.dumps(
                {
                    "generated_at": "2026-06-13T11:50:23+00:00",
                    "items": [{"id": "new", "time": "2026-06-13T19:38:55+08:00", "content": "new headline"}],
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("apps.scheduler.jin10_refresh.refresh_jin10_flash_cache", refresh)

    result = main.api_jin10_flash()

    assert result["generated_at"] == "2026-06-13T11:50:23+00:00"
    assert result["items"][0]["id"] == "new"


def test_jin10_flash_api_keeps_fresh_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "flash_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-13T11:50:23+00:00",
                "items": [{"id": "fresh", "time": "2026-06-13T19:38:55+08:00", "content": "fresh headline"}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "_JIN10_FLASH_CACHE_PATH", cache_path)
    monkeypatch.setattr(main, "_JIN10_FLASH_CACHE_MAX_AGE_SECONDS", 60)

    def refresh() -> None:
        raise AssertionError("fresh cache should not refresh")

    monkeypatch.setattr("apps.scheduler.jin10_refresh.refresh_jin10_flash_cache", refresh)

    result = main.api_jin10_flash()

    assert result["generated_at"] == "2026-06-13T11:50:23+00:00"
    assert result["items"][0]["id"] == "fresh"
