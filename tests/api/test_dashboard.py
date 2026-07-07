"""Dashboard endpoint smoke tests（不需要数据库）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


def test_dashboard_redirects_to_frontend_web(monkeypatch, tmp_path):
    """GET /dashboard 兼容旧入口，但实际跳转到 Vite 前端。"""
    monkeypatch.setattr("apps.api.services.frontend_compat_service._FRONTEND_DIST_DIR", tmp_path / "missing-dist")
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "http://localhost:8080/dashboard"


def test_dashboard_serves_built_frontend_when_dist_exists(tmp_path, monkeypatch):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<!doctype html><title>finance-agent</title>", encoding="utf-8")

    monkeypatch.setattr("apps.api.services.frontend_compat_service._FRONTEND_DIST_DIR", dist_dir)

    resp = client.get("/dashboard")

    assert resp.status_code == 200
    assert "finance-agent" in resp.text


def test_dashboard_assets_serve_from_built_frontend(tmp_path, monkeypatch):
    assets_dir = tmp_path / "dist" / "assets"
    assets_dir.mkdir(parents=True)
    (tmp_path / "dist" / "index.html").write_text("ok", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok');", encoding="utf-8")

    monkeypatch.setattr("apps.api.services.frontend_compat_service._FRONTEND_DIST_DIR", tmp_path / "dist")

    resp = client.get("/assets/app.js")

    assert resp.status_code == 200
    assert "console.log('ok');" in resp.text


def test_dashboard_system_status_returns_json():
    """GET /dashboard/system-status 返回 JSON，无 DB 时 db_available=false。"""
    resp = client.get("/dashboard/system-status")
    assert resp.status_code == 200
    data = resp.json()

    # 基础字段
    assert data["service"] == "finance-agent"
    assert data["version"] == "0.1.0"
    assert "generated_at" in data
    assert "test_status" not in data
    assert isinstance(data["db_available"], bool)

    # phases 结构
    phases = data["phases"]
    assert phases["phase_0_dev_prep"] == "done"
    assert phases["phase_5_dashboard"] == "done"
    assert phases["phase_6_p1_enhancements"] == "done"
    assert phases["phase_7_multi_asset"] == "not_started"

    # production_chain
    assert len(data["production_chain"]) == 9
    assert data["production_chain"][0] == "api"
    assert data["production_chain"][-1] == "output"

    # limitations
    assert data["limitations"]["mvp_readonly"] is True
    assert data["limitations"]["no_auto_trading"] is True

    # recent_tasks 无 DB 时应为空列表
    if not data["db_available"]:
        assert data["recent_tasks"] == []


def test_dashboard_system_status_has_all_phases():
    """MVP 状态必须包含所有 8 个 phase。"""
    resp = client.get("/dashboard/system-status")
    data = resp.json()
    phase_keys = list(data["phases"].keys())
    expected = [
        "phase_0_dev_prep",
        "phase_1_skeleton",
        "phase_2_macro",
        "phase_3_cme",
        "phase_4_reports",
        "phase_5_dashboard",
        "phase_6_p1_enhancements",
        "phase_7_multi_asset",
    ]
    assert phase_keys == expected, f"unexpected phase keys: {phase_keys}"
    for k in expected:
        assert data["phases"][k] in {"done", "in_progress", "not_started"}
