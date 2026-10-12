from __future__ import annotations

import json

import pytest

from apps.api import main
from apps.api.routes import jin10_market_routes


def test_jin10_flash_api_reports_disabled_without_refresh(monkeypatch):
    monkeypatch.setattr(jin10_market_routes, "jin10_disabled", lambda: True)
    monkeypatch.setattr(jin10_market_routes, "get_jin10_web_flash_briefs_latest", lambda: pytest.fail("disabled"))
    monkeypatch.setattr(
        "apps.scheduler.jin10_refresh.refresh_jin10_flash_cache",
        lambda: pytest.fail("disabled read must not refresh raw cache"),
    )
    result = main.api_jin10_flash()
    assert result["status"] == "disabled"
    assert result["items"] == []
    assert "FINANCE_AGENT_DISABLE_JIN10" in result["reason"]


def test_jin10_flash_api_uses_dws_brief_and_preserves_eligibility(monkeypatch):
    monkeypatch.setattr(jin10_market_routes, "jin10_disabled", lambda: False)
    monkeypatch.setattr("apps.scheduler.jin10_refresh.refresh_jin10_flash_cache", lambda: pytest.fail("page collection"))
    brief = {"brief_id": "new", "summary_zh": "新快讯摘要。", "verification_status": "unverified", "actionable": False}
    monkeypatch.setattr(jin10_market_routes, "get_jin10_web_flash_briefs_latest", lambda: {
        "status": "partial", "as_of": "2026-06-13T11:50:23+00:00", "briefs": [brief], "brief_count": 1,
    })
    result = main.api_jin10_flash()
    assert result["as_of"] == "2026-06-13T11:50:23+00:00"
    assert result["status"] == "partial"
    assert result["items"] == [brief]


def test_jin10_flash_api_does_not_fall_back_to_fresh_raw_cache(monkeypatch, tmp_path):
    cache = tmp_path / "storage" / "outputs" / "jin10" / "flash_cache.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"items": [{"content": "unprocessed source"}]}))
    monkeypatch.setattr(jin10_market_routes, "jin10_disabled", lambda: False)
    monkeypatch.setattr(jin10_market_routes, "get_jin10_web_flash_briefs_latest", lambda: None)
    monkeypatch.setattr("apps.scheduler.jin10_refresh.refresh_jin10_flash_cache", lambda: pytest.fail("page collection"))
    result = main.api_jin10_flash()
    assert result["status"] == "unavailable"
    assert result["reason"] == "dws_flash_unavailable"
    assert result["items"] == []
